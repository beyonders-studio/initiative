import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from pydantic import TypeAdapter
from pydantic.json_schema import models_json_schema
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware, _should_exempt, sync_check_limits

from sqlalchemy.exc import DBAPIError

from app.api.deps import (
    CommunityIdPath,
    GuildAccessError,
    SessionDep,
    establish_guild_access,
    get_upload_user,
    raise_for_guild_access,
)
from app.api.plugin_openapi import build_plugin_openapi, mark_plugin_scopes
from app.api.embed_csp import content_security_policy, plugin_frame_policy
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.compression import TextCompressionMiddleware
from app.core.csrf import CsrfOriginMiddleware
from app.api.v1.api import api_router
from app.api.well_known import router as well_known_router
from app.core.errors import CodedError
from app.core.messages import (
    CommonMessages,
    GuildMessages,
)
from app.core.rate_limit import limiter
from app.core.security import (
    billing_support_handoff_enabled,
)
from app.core.config import API_V1_STR, PROJECT_NAME, settings
from app.core.logging_config import configure_logging
from app.core.request_audit import RequestAuditMiddleware, server_error
from app.core.routing import MOUNTED, route_endpoint
from app.core.version import __version__
from app.core.smart_chips import SmartChipKind
from app.schemas.platform.ticket import (
    AppealTicketCreate,
    FeedbackTicketCreate,
    ModerationTicketCreate,
    SecurityTicketCreate,
    SupportTicketCreate,
)
from app.db.errors import INSUFFICIENT_PRIVILEGE_SQLSTATE, dbapi_sqlstate
from app.db.frozen import FROZEN_PARENT_CONSTRAINT, frozen_refusal
from app.db.session import SystemSessionLocal
from app.models.platform.user import User
from app.services import background_tasks as background_tasks_service
from app.services import captcha_config

# Before anything in this process logs: the served wiring for the application
# stream and the audit stream (see app.core.logging_config).
configure_logging()

logger = logging.getLogger(__name__)

#: The same question for a row written before the type column existed: its
#: stored name is the only thing that describes it.
NAMED_AS_MARKUP = (".svg", ".html", ".htm")

#: How long a browser may reuse a served upload before asking again.
#:
#: A stored blob is immutable, so this is not about staleness — it is how
#: often access is re-checked. Five minutes: long enough that scrolling a
#: collection up and down is not a request per picture per pass, short enough to
#: stay close to the current answer.
UPLOAD_CACHE_SECONDS = 300

uploads_path = Path(settings.UPLOADS_DIR)
uploads_path.mkdir(parents=True, exist_ok=True)
static_path = Path("static")
static_path.mkdir(parents=True, exist_ok=True)
static_index_path = static_path / "index.html"
static_root = static_path.resolve()
#: Paths the SPA never answers for. ``.well-known`` holds only what
#: ``app.api.well_known`` serves: anything else there is a 404 rather than the
#: index page, because a phone reads an HTML 200 there as a broken association.
reserved_prefixes = [
    prefix.strip("/")
    for prefix in {API_V1_STR, "/.well-known"}
    if prefix and prefix.strip("/")
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown.

    Modern replacement for the deprecated ``@app.on_event`` handlers. When the
    MCP server is mounted (``ENABLE_MCP``), its Streamable-HTTP session-manager
    lifespan is combined with this one via ``combine_lifespans`` in the mount
    block after ``include_router`` — so the MCP server boots alongside the API.
    """
    from app.db.init_db import prepare_database
    from app.db.soft_delete_filter import install_soft_delete_filter

    # Surface the effective CORS allowlist so a misconfigured split-origin
    # deployment (SPA served from a host other than APP_URL) is self-diagnosing.
    logger.info("CORS allowed origins: %s", settings.cors_origins)

    install_soft_delete_filter()
    # Everything the database needs before this process serves it: the
    # bootstrap, migrations, the heals and the seeds. The same function is
    # `python -m app.db.init_db`.
    await prepare_database()
    # Passkeys are bound to a named host reached over https, so a deployment
    # addressed any other way is told once at boot rather than per refusal.
    from app.services.auth import passkeys as passkey_service

    site_refusal = passkey_service.site_refusal()
    if site_refusal is not None:
        logger.warning(
            "APP_URL (%s) is %s, so passkey registration will be refused; "
            "serve this deployment from a domain name over https to offer it.",
            settings.APP_URL,
            {
                "ip_host": "an address rather than a domain name",
                "no_host": "not a whole URL, so it names no host",
            }.get(site_refusal, "plain http"),
        )
    if settings.BILLING_URL and not billing_support_handoff_enabled():
        # The Guilds tab shows its billing button whenever a portal URL is set;
        # without the handoff key every click fails closed (503).
        logger.warning(
            "BILLING_URL is set but HANDOFF_SIGNING_PRIVATE_KEY_PEM is not; every "
            "handoff into billing will fail closed until it is configured."
        )
    async with SystemSessionLocal() as session:
        # Prime the process-wide storage config snapshot from the DB so the
        # request path uses the saved backend/credentials, not just env vars.
        from app.services import storage_config

        await storage_config.refresh_storage_config(session)
        # Whether objects stored encrypted are left to read with
        # STORAGE_ENCRYPTION unset; nothing to do where it is set or never was.
        from app.services import storage_keys

        await storage_keys.prime(session)
        # The same for the captcha secret and the FCM service account: both are
        # read from paths that hold no usable session (a synchronous predicate,
        # a background dispatch), so each keeps a process-wide snapshot, and it
        # has to be primed here or the first request answers from the env seed.
        from app.services.platform import push_config

        await captcha_config.refresh_captcha_config(session)
        await push_config.refresh_push_config(session)
    # The plug-in platform's signing key: the stored one when env names none,
    # generated by whichever process starts first. Loaded before the
    # background tasks, which sign plug-in tokens too. A database error here
    # fails startup like the settings reads above, so a process never serves
    # without the key it could have loaded.
    from app.services.platform import app_settings as app_settings_service

    async with SystemSessionLocal() as session:
        await app_settings_service.load_plugin_platform_signing_key(session)

    app.state.notification_tasks = background_tasks_service.start_background_tasks()

    # The cross-worker nudge bus, and its subscribers. Starting it is
    # fire-and-forget by design: it maintains its own connection in the
    # background and a deployment that cannot reach it still delivers every
    # frame to the sockets this process holds.
    from app.db import timers
    from app.services import sweep_timers
    from app.services.platform import (
        billing_changes,
        email_outbox,
        notice_outbox,
        notify_bus,
        user_stream,
    )
    from app.services.tenant import outbox_poller, room_sink

    notify_bus.register(
        user_stream.CHANNEL,
        user_stream.deliver_remote,
        on_connect=user_stream.on_bus_connected,
    )
    notify_bus.register(
        room_sink.CHANNEL, room_sink.deliver, on_connect=room_sink.on_bus_connected
    )
    # The same hint wakes the webhook drain in a subscribed community.
    notify_bus.register(room_sink.CHANNEL, outbox_poller.hint)
    notify_bus.register(timers.WAKE_CHANNEL, sweep_timers.hint)
    notify_bus.register(notice_outbox.CHANNEL, notice_outbox.hint)
    notify_bus.register(email_outbox.CHANNEL, email_outbox.hint)
    # A committed change row: billing is pinged to read its change log.
    notify_bus.register(billing_changes.CHANNEL, billing_changes.hint)
    await notify_bus.start()

    # Write collaborative bodies that have changed on an interval, so what a
    # live editing session has produced does not depend on its last connection
    # closing cleanly to reach the database.
    from app.services.tenant.collaboration import collaboration_manager

    collaboration_manager.ensure_persistence_loop()

    try:
        yield
    finally:
        await collaboration_manager.stop_persistence_loop()
        await notify_bus.stop()
        # Shutdown: cancel the background notification tasks.
        tasks = getattr(app.state, "notification_tasks", [])
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        # Imports and exports the dispatcher started run as tasks of their own.
        from app.services.data_jobs import cancel_running_jobs

        await cancel_running_jobs()
        # Work a commit started, and every task spawned beside it, finishes
        # before the pools close.
        from app.db import post_commit

        await post_commit.settle_all()
        # The expression evaluators of declarative plug-ins, the document
        # editor and the image worker, if any started.
        from app.services import editor_engine
        from app.services.marketplace import expressions
        from app.services.tenant import spreadsheet_import, thumbnails

        expressions.shutdown()
        editor_engine.shutdown()
        thumbnails.shutdown()
        spreadsheet_import.shutdown()


# docs_url is left None: the default route would inherit the app-wide CSP and
# the jsDelivr-hosted Swagger assets get blocked. The custom routes below serve
# the same UI with a docs-scoped CSP instead.
app = FastAPI(
    title=PROJECT_NAME,
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    openapi_url=f"{API_V1_STR}/openapi.json",
    redoc_url=None,
    # An operation is named after its handler (``list_projects``), which the
    # generated client and the MCP tools take as their names.
    generate_unique_id_function=lambda route: route.name,
)


def _swagger_ui(openapi_url: str, title: str) -> Response:
    """Swagger UI over ``openapi_url``, with the docs-scoped CSP.

    The page loads its JS/CSS from jsDelivr, which only this response permits.
    The middleware uses setdefault, so this explicit header wins.
    """
    response = get_swagger_ui_html(openapi_url=openapi_url, title=title)
    response.headers["Content-Security-Policy"] = settings.docs_content_security_policy
    return response


@app.get(f"{API_V1_STR}/docs", include_in_schema=False)
async def swagger_ui_html() -> Response:
    return _swagger_ui(f"{API_V1_STR}/openapi.json", f"{PROJECT_NAME} - Swagger UI")


def plugin_openapi() -> dict:
    """The plug-in API's document (``app.api.plugin_openapi``), built once per
    process from the main one."""
    cached = getattr(app.state, "plugin_openapi_schema", None)
    if cached is None:
        cached = build_plugin_openapi(app.openapi(), app.routes)
        app.state.plugin_openapi_schema = cached
    return cached


@app.get(f"{API_V1_STR}/plugin-platform/openapi.json", include_in_schema=False)
async def plugin_openapi_json() -> JSONResponse:
    return JSONResponse(plugin_openapi())


@app.get(f"{API_V1_STR}/plugin-platform/docs", include_in_schema=False)
async def app_swagger_ui_html() -> Response:
    return _swagger_ui(
        f"{API_V1_STR}/plugin-platform/openapi.json",
        "Initiative plug-in API - Swagger UI",
    )


# Initialize rate limiter (uses shared limiter from app.core.rate_limit)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Starlette's error middleware answers a request that raised with this.
app.add_exception_handler(Exception, server_error)
# Register the middleware so the limiter's `default_limits` actually apply to
# *every* route, not just the handful with an explicit `@limiter.limit(...)`
# decorator. Without this the global default was inert. The middleware
# short-circuits when `limiter.enabled` is False (the test suite sets that), and
# routes that already carry a decorator are exempted from the default here.


class _DefaultRateLimit(SlowAPIMiddleware):
    """The global default limit, applied against the route that will run.

    Upstream picks a request's handler by scanning every route and keeping the
    LAST one that matches. This app registers 600-odd routes and ends with a
    catch-all serving the SPA, which matches everything — so upstream resolves
    every request to ``serve_spa``, and three things follow from that:

    * ``@limiter.exempt`` is never seen, because the name it registers is not
      the name the middleware looks up.
    * A route's own ``@limiter.limit`` never displaces the default, so one
      set deliberately ABOVE the default is silently held down to it.
    * Every request pays a full scan of all 600 routes — ~430µs, measured.

    Resolving the way the router itself does (``app.core.routing``) settles
    all three, so this replaces ``dispatch`` rather than wrapping it:
    delegating upward would run the scan it is here to avoid.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_limiter = request.app.state.limiter
        if not request_limiter.enabled:
            return await call_next(request)

        endpoint = route_endpoint(request.scope)
        if endpoint is MOUNTED:
            # Nothing to read a marker off, so a mount is limited like any
            # undecorated route — by the URL it was asked for.
            handler = None
        elif _should_exempt(request_limiter, endpoint) or _is_app_file(
            request, endpoint
        ):
            return await call_next(request)
        else:
            handler = endpoint

        error_response, inject_headers = sync_check_limits(
            request_limiter, request, handler, request.app
        )
        if error_response is not None:
            return error_response
        response = await call_next(request)
        if inject_headers:
            response = request_limiter._inject_headers(
                response, request.state.view_rate_limit
            )
        return response


app.add_middleware(_DefaultRateLimit)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Strip the echoed ``input`` (and the pydantic docs ``url``) from 422
    bodies so a failed validation never echoes the submitted value — e.g. a
    password or client secret on an auth/settings endpoint.
    Field locations and messages are kept: they're already public via the
    OpenAPI schema and the SPA surfaces them.
    """
    safe_errors = [
        {key: value for key, value in error.items() if key in ("type", "loc", "msg")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": safe_errors},
    )


@app.exception_handler(CodedError)
async def coded_error_handler(request: Request, exc: CodedError) -> JSONResponse:
    """A service's refusal, answered with its message code and status.

    Handled here rather than at each route because a refusal is raised where
    it is decided, often below every route that reaches it."""
    return JSONResponse(status_code=exc.status_code, content=exc.body)


@app.exception_handler(DBAPIError)
async def insufficient_privilege_handler(
    request: Request, exc: DBAPIError
) -> JSONResponse:
    """Map a database-layer refusal to the answer it deserves.

    The lifecycle freeze comes first: the content is archived or in the trash —
    or what it sits inside is — the caller may well be its owner, and the thing
    to do is bring one or the other back. 409, naming which, rather than a
    permission answer.

    Otherwise, map Postgres ``insufficient_privilege`` (42501) to a generic 403.

    Denials enforced at the role layer — e.g. a write attempted while routed
    into the SELECT-only ``guild_<id>_ro`` role (PAM read grants, guilds in
    ``read_only`` status) — surface as asyncpg errors, not app-layer checks.
    They ARE authorization denials, so answer 403 with the same generic code
    the resolver uses; deliberately no status-specific detail (a member of a
    read-only-suspended guild learns nothing about why). Everything else
    re-raises to the default 500 path.

    Always logged server-side: 42501 is expected only on the read-only-role
    write paths, so any other occurrence (a missing SET ROLE, a revoked table
    grant, a misconfigured login role) must be findable in the logs — the
    client body is deliberately too generic to debug from.
    """
    refusal = frozen_refusal(exc)
    if refusal is not None:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": CommonMessages.PARENT_IS_FROZEN
                if refusal == FROZEN_PARENT_CONSTRAINT
                else CommonMessages.CONTENT_IS_FROZEN
            },
        )
    if dbapi_sqlstate(exc) == INSUFFICIENT_PRIVILEGE_SQLSTATE:
        logger.warning(
            "insufficient_privilege mapped to 403: %s %s orig=%s",
            request.method,
            request.url.path,
            getattr(exc, "orig", exc),
        )
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": GuildMessages.COMMUNITY_ACCESS_DENIED},
        )
    raise exc


# The three WebAssembly workers — the dashboard widget sandbox, the direct
# message ratchet and the PDF viewer's pdf.js worker — and only they, are served
# with a policy that admits WebAssembly. Vite emits worker bundles into
# `assets/workers/` with a content hash (see `worker.rolldownOptions` in
# frontend/vite.config.ts) and the pdfjs plugin there puts pdf.js beside them
# under its version, so the match is by directory + stem; the literals are
# pinned by tests on both sides.
_WASM_WORKER_ASSET_PREFIXES = (
    "assets/workers/sandbox.worker-",
    "assets/workers/ratchet.worker-",
    "assets/workers/pdf.worker-",
)
# The first two are bundled by Vite as classic `.js`; pdf.js ships an ES module
# and is emitted under its own name.
_WASM_WORKER_ASSET_SUFFIXES = (".js", ".mjs")
_WASM_WORKER_CSP = settings.wasm_worker_content_security_policy


def _is_wasm_worker_asset(path: str) -> bool:
    """True for the built files that carry the WebAssembly worker policy.

    The hash varies per build, so the tail is open — but only as far as the one
    filename: anything nested below that name is an ordinary asset.
    """
    if not path.endswith(_WASM_WORKER_ASSET_SUFFIXES):
        return False
    return any(
        path.startswith(prefix) and "/" not in path[len(prefix) :]
        for prefix in _WASM_WORKER_ASSET_PREFIXES
    )


# Emit HSTS only when the public origin is HTTPS: the header is
# inert over plain HTTP and pinning a dev http:// origin to HTTPS would break it.
# Two years + includeSubDomains is the preload-eligible baseline; computed once
# since Settings are immutable for the process lifetime.
_STRICT_TRANSPORT_SECURITY = (
    "max-age=63072000; includeSubDomains" if settings.app_url_is_https else None
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # A response whose own policy names who may frame it is answered by
        # that alone (the captcha page the apps frame).
        if "frame-ancestors" not in response.headers.get("Content-Security-Policy", ""):
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        # setdefault: preserve any stricter per-response CSP (e.g. the upload
        # route's `script-src 'none'`) instead of overriding it.
        response.headers.setdefault(
            "Content-Security-Policy",
            content_security_policy(captcha_config.current_captcha_config().provider),
        )
        if _STRICT_TRANSPORT_SECURITY is not None:
            # Unconditional (not setdefault): unlike CSP there is no legitimate
            # per-route reason to weaken HSTS, so the middleware always wins.
            response.headers["Strict-Transport-Security"] = _STRICT_TRANSPORT_SECURITY
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Text-like responses gzipped, outside the headers above; see
# app/core/compression.py.
app.add_middleware(TextCompressionMiddleware, minimum_size=1024, compresslevel=6)

# Body-size bounds for every request — a route's own where it has one, a
# default otherwise — enforced at the ASGI seam so an oversized (or chunked,
# length-less) request is refused before its body is buffered, not after
# FastAPI has already parsed it.
app.add_middleware(BodySizeLimitMiddleware)

# Origin checking for cookie-authenticated writes; see app/core/csrf.py.
#
# Added BEFORE CORSMiddleware. Starlette applies middleware in reverse order of
# addition, so CORS ends up outermost and answers a preflight before this runs.
# A refusal from here carries no Access-Control-Allow-Origin, so a caller whose
# origin is not on the allowlist reads it as a CORS error rather than as the
# 403 body -- which is why the body is a code for logs and same-origin clients.
app.add_middleware(CsrfOriginMiddleware)

app.add_middleware(
    CORSMiddleware,
    # Explicit allowlist (never "*"): wildcard + allow_credentials reflects any
    # origin and would let any site make authenticated requests (CRIT-001).
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Export downloads name the file server-side (Content-Disposition); the
    # SPA reads it to name the blob it saves — expose it for the native
    # (cross-origin) app, web is same-origin and sees it regardless.
    # A resumable upload's client reads where the upload is and how far it got.
    expose_headers=[
        "Content-Disposition",
        "Location",
        "Upload-Offset",
        "Upload-Length",
        "Upload-Expires",
        "Tus-Resumable",
        "Tus-Version",
        "Tus-Extension",
    ],
)

# Added last, so it sits outside the rest: every request gets its id here,
# whatever answers it, and a request served through a privileged-access grant
# is written down once its response is finished. See app/core/request_audit.py.
app.add_middleware(RequestAuditMiddleware)


@app.get("/uploads/{community_id}/{filename:path}", include_in_schema=False)
@limiter.limit("600/minute")
async def serve_upload_file(
    request: Request,
    guild_id: CommunityIdPath,
    filename: str,
    current_user: Annotated[User, Depends(get_upload_user)],
    session: SessionDep,
) -> Response:
    """Serve an uploaded file — requires authentication and an Upload row in
    the path-addressed guild."""
    from pathlib import Path as FilePath

    from sqlalchemy import text

    from app.services.storage import (
        INLINE_UPLOAD_TYPES,
        USER_CONTENT_CSP,
        build_upload_response,
        get_guild_storage,
        requested_range,
    )

    # Media is referenced by pages inside a guild, and ``<img>``/iframe can't
    # send headers, so the guild rides in the URL (and a cookie is per-browser,
    # not per-tab). Access is established through the one seam every guild
    # request uses, which routes the session into that guild. No access and no
    # Upload row both 404, so the blob's existence is never confirmed; a
    # refusal that names what is missing answers as it does everywhere else.
    try:
        await establish_guild_access(session, current_user, guild_id)
    except GuildAccessError as exc:
        if exc.detail == GuildMessages.COMMUNITY_ACCESS_DENIED:
            raise HTTPException(status_code=404) from exc
        raise_for_guild_access(exc)
    fname = FilePath(filename).name
    hit = (
        await session.exec(
            text("SELECT content_type FROM uploads WHERE filename = :fn LIMIT 1"),
            params={"fn": fname},
        )
    ).first()
    if hit is None:
        raise HTTPException(status_code=404)

    # Storage is touched only after authorization passes. open_readable returns
    # None for a missing/traversal key -> 404 (same fail-closed shape as before).
    blob = get_guild_storage(guild_id).open_readable(
        filename, byte_range=requested_range(request.headers.get("range"))
    )
    if blob is None:
        raise HTTPException(status_code=404)

    # A stored file never changes under its name — every write, including a
    # new version of a picture, gets a fresh UUID — so the bytes behind a URL
    # are safe to reuse. The decision above them is re-made per request, so
    # the window is short rather than a year: long enough for the repeat
    # requests one session of scrolling a collection makes, and short enough that
    # access is re-checked while somebody is still reading. ``private`` keeps
    # shared caches out of it, and ``must-revalidate`` bounds the entry to
    # that window.
    headers: dict[str, str] = {
        "Cache-Control": f"private, max-age={UPLOAD_CACHE_SECONDS}, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }
    # What the file is, as the server recorded it when it was written — so a
    # local blob and an S3 one describe themselves the same way, rather than
    # each backend answering from what it happens to have. A row from before
    # the column existed carries nothing; its name is read instead, and the
    # backend keeps naming the type as it always has.
    stored_type = hit[0]
    inline = (
        stored_type in INLINE_UPLOAD_TYPES
        if stored_type is not None
        else not fname.lower().endswith(NAMED_AS_MARKUP)
    )
    if not inline:
        headers["Content-Disposition"] = "attachment"
        headers["Content-Security-Policy"] = USER_CONTENT_CSP
    logger.info("upload_served filename=%s user=%d", filename, current_user.id)
    return build_upload_response(blob, media_type=stored_type, headers=headers)


app.include_router(api_router, prefix=API_V1_STR)
app.include_router(well_known_router)


def _inject_query_schemas(openapi_schema: dict) -> None:
    """Inject shared query filter/sort schemas into OpenAPI components.

    These schemas (FilterCondition, FilterOp, FilterGroup, SortField, SortDir)
    are defined in ``app.schemas.query`` and used by list endpoints that accept
    a ``conditions`` JSON query parameter.  Injecting them here lets Orval
    auto-generate TypeScript types so the frontend never hand-defines them.
    """
    from app.schemas.query import (
        FilterCondition,
        FilterGroup,
        FilterOp,
        SortDir,
        SortField,
    )

    schemas = openapi_schema.setdefault("components", {}).setdefault("schemas", {})

    for model in (FilterCondition, FilterGroup, SortField):
        full = model.model_json_schema(
            ref_template="#/components/schemas/{model}",
        )
        defs = full.pop("$defs", {})
        # For self-referencing models (e.g. FilterGroup) the top level is
        # just {"$ref": "..."} and the real schema lives in $defs.
        if "$ref" in full and not full.get("properties"):
            real = defs.pop(model.__name__, full)
            schemas[model.__name__] = real
        else:
            schemas[model.__name__] = full
        for name, sub_schema in defs.items():
            schemas.setdefault(name, sub_schema)

    # Enums as standalone schemas (may already be added via $defs above)
    for enum_cls in (FilterOp, SortDir):
        schemas.setdefault(
            enum_cls.__name__,
            {
                "title": enum_cls.__name__,
                "type": "string",
                "enum": [e.value for e in enum_cls],
            },
        )

    # The ``conditions`` and ``sorting`` query parameters each carry one
    # JSON-encoded value. Publishing them under ``content: application/json``
    # gives the decoded type, and tells a client to send the whole list as a
    # single JSON string rather than as repeated keys.
    fc_ref = {"$ref": "#/components/schemas/FilterCondition"}
    fg_ref = {"$ref": "#/components/schemas/FilterGroup"}
    sf_ref = {"$ref": "#/components/schemas/SortField"}
    json_params = {
        # An item is either a leaf comparison or an AND/OR group.
        "conditions": {"type": "array", "items": {"anyOf": [fc_ref, fg_ref]}},
        "sorting": {"type": "array", "items": sf_ref},
    }
    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            for param in operation.get("parameters", []):
                schema = json_params.get(param.get("name"))
                if schema is None or param.get("in") != "query":
                    continue
                param.pop("schema", None)
                param["content"] = {"application/json": {"schema": schema}}


def custom_openapi() -> dict:
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = openapi_schema.setdefault("components", {})
    security_schemes = components.setdefault("securitySchemes", {})
    security_schemes.setdefault(
        "ApiKeyAuth",
        {
            "type": "http",
            "scheme": "bearer",
            "description": "Paste a personal API key issued from Settings → API Keys.",
        },
    )

    _inject_query_schemas(openapi_schema)

    # The chips an editor may offer. No route returns the list, but the client
    # builds its menu from this enum, so it is published for Orval to generate.
    components.setdefault("schemas", {})["SmartChipKind"] = TypeAdapter(
        SmartChipKind
    ).json_schema()

    # What a filing's ``payload`` part holds. The route takes it as a JSON
    # string beside the files, so the shapes are published here instead.
    _, ticket_schemas = models_json_schema(
        [
            (SupportTicketCreate, "validation"),
            (ModerationTicketCreate, "validation"),
            (SecurityTicketCreate, "validation"),
            (FeedbackTicketCreate, "validation"),
            (AppealTicketCreate, "validation"),
        ],
        ref_template="#/components/schemas/{model}",
    )
    for name, schema in ticket_schemas.get("$defs", {}).items():
        components["schemas"].setdefault(name, schema)

    for path_item in openapi_schema.get("paths", {}).values():
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            security = operation.get("security")
            if not security:
                continue
            has_api_key = any(
                isinstance(item, dict) and "ApiKeyAuth" in item for item in security
            )
            if not has_api_key:
                security.append({"ApiKeyAuth": []})

    mark_plugin_scopes(openapi_schema, app.routes)

    app.openapi_schema = openapi_schema
    return app.openapi_schema


# Attach the custom OpenAPI generator now — BEFORE the MCP server is built below.
# ``build_mcp_server(app)`` calls ``app.openapi()`` to derive its tools; if the
# override isn't in place yet, FastAPI's default generator runs and caches a spec
# without the ``_inject_query_schemas`` upgrades, which then leaks into the frontend
# type generation (conditions/sorting collapse back to ``string``). The SPA catch-all
# registered later is ``include_in_schema=False``, so the spec is already complete here.
app.openapi = custom_openapi  # ty: ignore[invalid-assignment]


class McpBarePathMiddleware:
    """Serve ``/api/v1/mcp`` as ``/api/v1/mcp/``.

    A Starlette ``Mount`` matches only the trailing-slash spelling, and MCP
    clients differ over which one they send. Rewriting the path in place serves
    both from the one mount, with nothing for the client to follow. Plain ASGI
    rather than ``BaseHTTPMiddleware``, so the streamed body passes through.
    """

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == self.prefix:
            scope = {**scope, "path": f"{self.prefix}/"}
        await self.app(scope, receive, send)


if settings.ENABLE_MCP:
    # Build the route-backed MCP server from the fully-routed app and mount it at
    # /api/v1/mcp (before the SPA catch-all below, so it wins that path). Build
    # order matters: the routers above must already be included so the read-only
    # RouteMap can see them. ``combine_lifespans`` runs the MCP session-manager
    # lifespan alongside the app's own startup/shutdown (see ``lifespan``).
    from fastmcp.utilities.lifespan import combine_lifespans

    from app.mcp_server import build_mcp_server

    _mcp_app = build_mcp_server(app).http_app(path="/")
    app.mount(f"{API_V1_STR}/mcp", _mcp_app)
    app.add_middleware(McpBarePathMiddleware, prefix=f"{API_V1_STR}/mcp")
    app.router.lifespan_context = combine_lifespans(lifespan, _mcp_app.lifespan)


def _is_reserved_path(path: str) -> bool:
    normalized = path.strip("/")
    for prefix in reserved_prefixes:
        if not prefix:
            continue
        if normalized == prefix or normalized.startswith(f"{prefix}/"):
            return True
    return False


def _resolve_static_file(path: str) -> Path | None:
    try:
        candidate = (static_path / path).resolve()
        candidate.relative_to(static_root)
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def _is_app_file(request: Request, endpoint: object) -> bool:
    """Whether the request is for one of the app's own built files, which take
    no limit: they are read from disk, unchanged once built, and a first visit
    asks for over a hundred. A path that falls back to the index is counted."""
    return (
        endpoint is serve_spa
        and _resolve_static_file(request.url.path.lstrip("/")) is not None
    )


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str) -> FileResponse:
    if _is_reserved_path(full_path):
        raise HTTPException(status_code=404)
    static_file = _resolve_static_file(full_path) if full_path else None
    if static_file:
        if full_path.startswith("assets/"):
            headers = {"Cache-Control": "public, max-age=31536000, immutable"}
            # The middleware sets the app-wide policy with setdefault, so this
            # per-asset one wins where it applies.
            if _is_wasm_worker_asset(full_path):
                headers["Content-Security-Policy"] = _WASM_WORKER_CSP
            return FileResponse(static_file, headers=headers)
        return FileResponse(
            static_file,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    if static_index_path.is_file():
        # A document is where `frame-src` means anything, so the registered plug-in
        # origins are named here rather than on every response (see
        # app.api.embed_csp). The middleware sets the app-wide policy with
        # setdefault, so this one wins.
        headers = {
            "Cache-Control": "no-cache",
            "Content-Security-Policy": await plugin_frame_policy(),
        }
        return FileResponse(static_index_path, headers=headers)
    raise HTTPException(status_code=404, detail="SPA bundle not found")
