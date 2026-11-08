"""External data reaching a widget: the proxy behind the ``plugin`` binding.

A widget never names an address. It names a *read endpoint* on an installed
plug-in, and this module turns that into one bounded call to the plug-in's own service
and hands back rows. Everything the call needs — where the plug-in lives, which
credentials it may use, how long an answer is good for — comes from state the
guild and the operator already own, never from the request.

**Authorization happens before this module caches anything.** The route runs
under the caller's own guild session, so the install row is reachable only from
inside that guild and a guild admin's wider reach is inherited rather than
re-implemented. What is left here is the plugin-shaped part of the decision:
whether the endpoint is for the community's admins alone, the two kill switches
(the guild's install and the operator's registration), and whether the
credentials the endpoint declared it needs are actually present.

**The cache key contains every credential the response depended on.** That is
the whole rule, and it is what makes a stored body safe to replay:

* the guild, the install, and the pinned listing version — an entry is
  unreachable from a session that is not already inside that guild;
* the endpoint and its parameters;
* a fingerprint of the install's stored configuration, so rotating a credential
  retires the answers it produced;
* the opaque handles of every per-member connection the call used, so two
  members with different vendor accounts never share an entry while one
  member's repeated widgets and open tabs still collapse to a single fetch.

**Two bounds keep one plug-in from costing everyone else.** Calls for the same key
are coalesced, so twenty viewers of a dashboard are one upstream request; and a
per-worker in-flight cap per plug-in means a service that stops answering ties up a
fixed number of connections rather than the pool.

**The answer is read through the endpoint's own declaration.** A manifest says
what an endpoint hands back — a key, a type, and whether it holds several — and
that is the whole of what a widget may bind, so it is also how the answer is
read here: the returns that hold several become rows, side by side, and the ones
holding a single value stay whole beside them. Nothing interprets a value; the
projection is by name alone, on its way to a sandboxed widget that is handed the
result as data.

**The same call serves one plug-in calling another.** :mod:`plugin_hub` checks such a
call and makes it through :func:`_call_plugin` and :func:`cached_call`, reading
the answer whole rather than through the returns.

**A declarative plug-in is called the same way.** It has no container: Initiative
makes its calls itself (:mod:`app.services.marketplace.declarative`) behind
:func:`_call_plugin`, and hands back the envelope a container answers with, so
everything around the call is the same for both.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx2
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import (
    GuildPluginMessages,
    PluginDataMessages,
    PluginServiceMessages,
)
from app.core.security import (
    PluginPlatformSigningNotConfiguredError,
    plugin_platform_signing_enabled,
)
from app.db.session import guild_context, routed_context, routed_guild_id
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.schemas.tenant.plugin_data import (
    PluginDataResponse,
    PluginSummaryListResponse,
    PluginSummaryRead,
    PluginSummaryReturn,
)
from app.services.marketplace.community_status import community_status
from app.services.marketplace.context_jwt import mint_context_token
from app.services.marketplace.plugin_refs import (
    PluginNameRefused,
    ensure_plugin_guild_ref,
)
from app.services.marketplace.registration_lookup import (
    RegistrationSnapshot,
    is_declarative,
    load_registrations,
    registration_for_definition,
    service_public_id,
)
from app.services.marketplace.service_plugins import _requests, is_admin_only
from app.services.safe_http import build_validated_request
from app.services.tenant import plugin_config as plugin_config_service
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)


__all__ = [
    "MAX_CACHE_TTL_SECONDS",
    "MAX_INFLIGHT_PER_PLUGIN",
    "MAX_PARAMS_BYTES",
    "MAX_PARAM_VALUES",
    "MAX_RESPONSE_BYTES",
    "REQUEST_TIMEOUT_SECONDS",
    "CallingPlugin",
    "PluginDataError",
    "PluginDataResult",
    "cached_call",
    "clear_plugin_data_cache",
    "fetch_plugin_source",
    "find_param",
    "find_read_endpoint",
    "first_actor",
    "prepare_for_session",
    "prepare_plugin_source",
    "project_returns",
    "resolve_param_options",
    "row_columns",
    "validate_params",
]


# --- bounds -----------------------------------------------------------------
#
# All per worker, all deliberately small. A dashboard is a display surface: a
# endpoint that cannot answer in five seconds inside a megabyte is not going to
# render usefully, and letting it try costs everyone sharing the process.

#: Wall-clock budget for one upstream call. Connect and read are capped
#: separately so a service that accepts a connection and then stalls still
#: returns inside the budget.
REQUEST_TIMEOUT_SECONDS = 5.0
#: Response ceiling. Read as a bounded stream, so an oversized body is abandoned
#: rather than buffered.
MAX_RESPONSE_BYTES = 1024 * 1024
#: The encoded ``params`` object a request may carry.
MAX_PARAMS_BYTES = 2048
#: How many values one ``list`` parameter may carry. Bounded for the same
#: reason the object is: a request is a request, not a bulk upload.
MAX_PARAM_VALUES = 64
#: How many calls to one plug-in this worker will hold open at once. Refused rather
#: than queued: waiting behind a stalled plug-in is the same outage with a longer
#: fuse.
MAX_INFLIGHT_PER_PLUGIN = 8
#: The longest a response is reused, whatever the manifest asks for. The manifest
#: value is already clamped at publish time; this is the deployment's own ceiling
#: so a listing cannot decide how stale a dashboard may be.
MAX_CACHE_TTL_SECONDS = 300
#: How many responses one worker keeps. Entries are small (rows for one widget)
#: and expire on their own; this only bounds a pathological spread of parameter
#: combinations.
MAX_CACHE_ENTRIES = 2048


class PluginDataError(CodedError):
    """A refusal with the message code and status the endpoint should answer,
    and ``detail`` for the log."""

    def __init__(self, code: str, status_code: int, detail: str = "") -> None:
        super().__init__(code, status_code)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail or self.code


@dataclass(frozen=True)
class PluginDataResult:
    """One endpoint's answer, and when it was actually obtained upstream."""

    #: One entry per index across the endpoint's ``list`` returns.
    rows: list[dict[str, Any]]
    #: The endpoint's single-valued returns, once — what the answer says about
    #: itself rather than about any one item in it.
    values: dict[str, Any]
    fetched_at: datetime
    #: True when this body came from the response cache rather than the plug-in.
    cached: bool = False


# --- reading the pinned definition ------------------------------------------


def _endpoints(definition: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    declared = (definition or {}).get("endpoints")
    if not isinstance(declared, list):
        return []
    return [entry for entry in declared if isinstance(entry, dict)]


def endpoint_by_id(
    definition: Mapping[str, Any] | None,
    endpoint_id: Any,
    *,
    directions: Collection[str] | None = None,
) -> dict[str, Any] | None:
    """One endpoint of the *pinned* definition by its id, of one of
    ``directions`` (any, when none are given), or None.

    Pinned rather than current on purpose: what an install offers is the version
    its guild chose, so publishing a new one never silently widens what an
    existing install will answer.
    """
    for endpoint in _endpoints(definition):
        if endpoint.get("id") == endpoint_id and (
            directions is None or endpoint.get("direction") in directions
        ):
            return endpoint
    return None


def find_read_endpoint(
    definition: Mapping[str, Any] | None, endpoint_id: str
) -> dict[str, Any] | None:
    """One readable endpoint from the pinned definition, or None.

    Readable rather than declared, because this is the fetch path. A write and
    an emission are both real endpoints and neither is reachable from here — a
    dashboard rendering a tile must not be a way to make a plug-in act.
    """
    return endpoint_by_id(definition, endpoint_id, directions=("read",))


# --- reading an answer through what was declared ----------------------------


def row_columns(endpoint: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """The columns the rows of this endpoint hold, as it declared them: each
    return marked ``list`` (see :func:`project_returns`), by its key and type.

    Declared rather than discovered, which is what lets a statement over them
    be checked, and offered to somebody writing one, before the endpoint has
    ever run.
    """
    return tuple(
        (entry["key"], str(entry.get("type") or "string"))
        for entry in _declared_returns(endpoint)
        if entry.get("list") is True
    )


def _declared_returns(endpoint: Mapping[str, Any]) -> list[dict[str, Any]]:
    declared = endpoint.get("returns")
    if not isinstance(declared, list):
        return []
    return [
        entry
        for entry in declared
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    ]


def project_returns(
    result: Mapping[str, Any], endpoint: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """An endpoint's answer, read through the returns it declares.

    A plug-in answers with the keys its manifest named, and this is where they
    become the two things a widget is handed. It is the same declaration the
    binding was made against, so what a tile draws and what the publisher
    described cannot come apart.

    Returns marked ``list`` are read **side by side rather than joined**: the
    third entry of each describes the same third thing, which is the shape a
    read answering about a set already has. Those become the rows. A return
    holding a single value describes the answer rather than any one item in it —
    how many there are in all, or why there is nothing — so it stays whole in
    ``values``, which is also where an answer with an empty set still has
    somewhere to put it.

    A key the endpoint does not declare is left out, and a declared key the plug-in
    did not send is simply absent: the manifest is the vocabulary, and a widget
    binds against it before the endpoint has ever run.
    """
    columns: dict[str, list[Any]] = {}
    values: dict[str, Any] = {}
    for entry in _declared_returns(endpoint):
        key = entry["key"]
        if key not in result:
            continue
        supplied = result[key]
        if entry.get("list") is True:
            # A declared list that arrived as something else describes no set,
            # so it contributes no column rather than a column of one.
            if isinstance(supplied, list):
                columns[key] = supplied
        else:
            values[key] = supplied

    length = max((len(column) for column in columns.values()), default=0)
    rows = [
        {key: column[index] for key, column in columns.items() if index < len(column)}
        for index in range(length)
    ]
    return rows, values


# --- parameters -------------------------------------------------------------


def _coerce_param(field_spec: Mapping[str, Any], value: Any) -> str | list[str]:
    """One parameter, checked against what its endpoint declared about it.

    Cardinality first, then type. A parameter marked ``list`` takes an array and
    nothing else, and each entry is held to the same type rules a single value
    would be — so ``list`` is the whole of what says whether one value or
    several are expected, which is the point of declaring it. The alternative it
    replaced is a plug-in declaring a string and documenting a comma, which is a
    convention nothing on this side can validate.

    An empty array is refused rather than forwarded. "None of them" is a
    parameter that is absent; an array with nothing in it is a request nobody
    meant to make.
    """
    if field_spec.get("list") is True:
        if not isinstance(value, list) or not value:
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
        if len(value) > MAX_PARAM_VALUES:
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
        return [_coerce_scalar(field_spec, entry) for entry in value]
    if isinstance(value, list):
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
    return _coerce_scalar(field_spec, value)


def _coerce_scalar(field_spec: Mapping[str, Any], value: Any) -> str:
    """One value, checked against its declared type and rendered for the
    wire. The types are the manifest's closed enum minus ``secret`` — a
    credential is supplied once and held in custody, never restated per call."""
    field_type = field_spec.get("type")

    if field_type == "bool":
        if not isinstance(value, bool):
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
        return "true" if value else "false"

    if field_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
        return str(value)

    if not isinstance(value, str):
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
    text = value.strip()
    if not text or len(text) > plugin_config_service.MAX_CONFIG_VALUE_LENGTH:
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)

    if field_type == "select":
        options = field_spec.get("options")
        if not isinstance(options, list) or text not in options:
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
        return text

    if field_type == "datetime":
        try:
            datetime.fromisoformat(text)
        except ValueError as exc:
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400) from exc
        return text

    if field_type == "url":
        if " " in text or not (text.startswith(("https://", "http://"))):
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
        return text

    if field_type != "string":
        # A type the manifest validator would not have stored. Refused rather
        # than passed through as an unchecked string.
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
    return text


def validate_params(
    endpoint: Mapping[str, Any], raw: str | None
) -> tuple[dict[str, str | list[str]], str]:
    """Check a request's parameters against the ones the endpoint declares.

    Returns the values to send upstream and their canonical form for the cache
    key. A parameter the endpoint does not declare is refused rather than
    forwarded: the schema is the whole of what a widget may vary, and anything
    else would be a caller shaping the plug-in's request directly.
    """
    if raw is None or not raw.strip():
        supplied: dict[str, Any] = {}
    else:
        if len(raw.encode("utf-8")) > MAX_PARAMS_BYTES:
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
        try:
            supplied = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400) from exc
        if not isinstance(supplied, dict):
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)

    declared_raw = endpoint.get("params")
    declared = {
        entry["key"]: entry
        for entry in (declared_raw if isinstance(declared_raw, list) else [])
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    }

    values: dict[str, str | list[str]] = {}
    for key, value in supplied.items():
        field_spec = declared.get(key)
        if field_spec is None:
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
        values[key] = _coerce_param(field_spec, value)

    for key, field_spec in declared.items():
        if field_spec.get("required") is True and key not in values:
            raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)

    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return values, canonical


# --- which credentials this endpoint runs on --------------------------------


def _required_connection_ids(endpoint: Mapping[str, Any]) -> tuple[list[str], bool]:
    """The connections an endpoint names, and whether all of them are needed.

    ``requires`` is one level with one operator (§7.4). Absent means the endpoint
    needs no credential at all.
    """
    requires = endpoint.get("requires")
    if not isinstance(requires, dict):
        return [], True
    for key, needs_all in (("all_of", True), ("any_of", False)):
        terms = requires.get(key)
        if isinstance(terms, list):
            return [term for term in terms if isinstance(term, str)], needs_all
    return [], True


def _request_connection(request: Mapping[str, Any], actor: str | None) -> str | None:
    """The connection whose credential ``request`` carries on a call made as
    ``actor``: the one it names for every call, or, when it names one per
    actor, the one it names for ``actor``. ``None`` when it names none for
    ``actor``, as on a call made as no actor."""
    named = request.get("connection")
    if isinstance(named, dict):
        named = named.get(actor) if actor is not None else None
    return named if isinstance(named, str) else None


def _connection_ids(endpoint: Mapping[str, Any], actor: str | None) -> list[str]:
    """The connections the endpoint's requests carry on a call made as
    ``actor`` (:func:`_request_connection`), once each."""
    named = (_request_connection(request, actor) for request in _requests(endpoint))
    return list(dict.fromkeys(name for name in named if name is not None))


async def _resolve_connections(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    endpoint: Mapping[str, Any],
    user_id: int | None,
    actor: str | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Decide whether this endpoint can run, and collect the handles it runs
    with and each satisfied connection's non-secret fields, by connection id.

    Satisfaction is presence alone — which fields hold a value. This build never
    inspects a credential, calls a vendor, or learns a scope; whether a stored
    credential carries the permissions it needs is the plug-in's to report.

    A guild-scoped connection is the same answer for everyone; a per-member one
    is answered for the caller, so a colleague who has connected sees data while
    someone who has not is told to connect rather than being served the other
    person's view.

    ``actor`` is set on a call made as one of the endpoint's actors:
    ``installation`` has no member (``user_id`` is ``None``), so a per-member
    connection is never satisfied, and ``member`` hands on only the member's
    own handles, not the community's. A call made as an actor also needs
    each connection of that actor's its requests carry
    (:func:`_connection_ids`): the member's own, or the community's, as an
    ``all_of`` term would, which a request naming one per actor need not name
    in ``requires``.
    """
    required, needs_all = _required_connection_ids(endpoint)
    #: The actor's own connections the call carries beyond those ``requires``
    #: names, every one needed.
    own = [
        connection_id
        for connection_id in (
            _connection_ids(endpoint, actor)
            if actor in ("member", "installation")
            else ()
        )
        if connection_id not in required
        and (
            plugin_config_service.connection_by_id(plugin.definition, connection_id)
            or {}
        ).get("scope")
        == ("interactive" if actor == "member" else "static")
    ]
    if not required and not own:
        return {}, {}

    config = plugin.config or {}
    secret_fields = plugin.secret_fields or {}
    refs: dict[str, str] = {}
    #: The connections whose handle is a member's own.
    member_refs: set[str] = set()
    satisfied: list[str] = []
    fields: dict[str, dict[str, Any]] = {}
    #: The first reason a candidate failed, reported when nothing satisfies:
    #: the member's own come first, so a call they cannot make says so.
    refusal: PluginDataError | None = None

    for connection_id in [*own, *required]:
        connection = plugin_config_service.connection_by_id(
            plugin.definition, connection_id
        )
        if connection is None:
            # The pinned definition names a connection it does not declare —
            # nothing can satisfy it, so the endpoint cannot run.
            refusal = refusal or PluginDataError(
                PluginDataMessages.NEEDS_CONFIGURATION, 409
            )
            continue

        if connection.get("scope") == "interactive":
            if user_id is None:
                refusal = refusal or PluginDataError(
                    PluginDataMessages.CONNECTION_REQUIRED, 409
                )
                continue
            row = await _member_connection(
                session,
                plugin_id=plugin.id,
                connection_id=connection_id,
                user_id=user_id,
            )
            if row is not None and row.blocked_at is not None:
                refusal = refusal or PluginDataError(
                    GuildPluginMessages.CONNECTION_BLOCKED, 403
                )
                continue
            # A flow's connection is usable only while it is connected: one
            # whose refresh was refused reads as expired until it is made again.
            usable = row is not None and (
                row.status == "connected"
                or not plugin_config_service.runs_vendor_flow(connection)
            )
            if not usable or not plugin_config_service.is_satisfied(
                connection, row.config, row.secret_fields
            ):
                refusal = refusal or PluginDataError(
                    PluginDataMessages.CONNECTION_REQUIRED, 409
                )
                continue
            refs[connection_id] = row.connection_ref
            member_refs.add(connection_id)
            satisfied.append(connection_id)
            fields[connection_id] = plugin_config_service.without_tokens(row.config)
            continue

        if not plugin_config_service.is_satisfied(
            connection,
            config.get(connection_id) or {},
            secret_fields.get(connection_id) or {},
        ):
            refusal = refusal or PluginDataError(
                PluginDataMessages.NEEDS_CONFIGURATION, 409
            )
            continue
        # A guild-wide connection the plug-in can ask a token for travels by its
        # handle too.
        guild_ref = (plugin.connection_refs or {}).get(connection_id)
        if isinstance(guild_ref, str) and guild_ref:
            refs[connection_id] = guild_ref
        satisfied.append(connection_id)
        fields[connection_id] = plugin_config_service.without_tokens(
            config.get(connection_id)
        )

    met = [connection_id for connection_id in required if connection_id in satisfied]
    if (
        any(connection_id not in satisfied for connection_id in own)
        or (needs_all and len(met) != len(required))
        or (not needs_all and not met)
    ):
        raise refusal or PluginDataError(PluginDataMessages.NEEDS_CONFIGURATION, 409)
    # For ``any_of`` the handles of every satisfied candidate travel, and the plug-in
    # picks the least-privileged one it recognizes. They are part of the cache
    # key either way, so an answer is only ever replayed to a caller holding the
    # same set.
    if actor == "member":
        refs = {key: ref for key, ref in refs.items() if key in member_refs}
    return refs, fields


async def first_actor(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    endpoint: Mapping[str, Any],
    user_id: int | None,
    actors: Collection[str],
) -> tuple[str, dict[str, str], dict[str, dict[str, Any]]]:
    """The first of ``actors`` a call can be made as, with the handles and
    non-secret fields it runs with (:func:`_resolve_connections`): ``member``
    on ``user_id``'s own connections and ``installation`` on the community's,
    its ``requires`` met and every connection its requests name for that actor
    able to travel
    (:func:`~app.services.marketplace.declarative.request_refusal`). When none
    can, the first one's refusal is the answer."""
    # Imported here: the declarative executor reads this module's limits.
    from app.services.marketplace.declarative import request_refusal

    refusals: list[PluginDataError] = []
    for actor in actors:
        try:
            refs, fields = await _resolve_connections(
                session,
                plugin=plugin,
                endpoint=endpoint,
                user_id=user_id if actor == "member" else None,
                actor=actor,
            )
        except PluginDataError as exc:
            refusals.append(exc)
            continue
        refused = request_refusal(plugin.definition, endpoint, refs, actor)
        if refused is not None:
            refusals.append(refused)
            continue
        return actor, refs, fields
    raise (
        refusals[0]
        if refusals
        else PluginDataError(PluginDataMessages.CONNECTION_REQUIRED, 409)
    )


async def _member_connection(
    session: AsyncSession, *, plugin_id: int, connection_id: str, user_id: int
) -> GuildPluginUserConnection | None:
    return (
        await session.exec(
            select(GuildPluginUserConnection).where(
                GuildPluginUserConnection.plugin_id == plugin_id,
                GuildPluginUserConnection.connection_id == connection_id,
                GuildPluginUserConnection.user_id == user_id,
            )
        )
    ).first()


# --- the registration -------------------------------------------------------


async def _load_registration(
    public_id: str | None,
    *,
    guild_id: int | None,
    plugin: GuildPlugin | None = None,
) -> RegistrationSnapshot:
    """Where this plug-in lives and whether the operator still allows it in
    community ``guild_id``: the registration for ``public_id``, or the one
    behind ``plugin``.

    Read from the registration snapshot every request path shares
    (:mod:`app.services.marketplace.registration_lookup`), which an operator's
    write drops at once and a replica that did not serve it reloads within its
    TTL.
    """
    row = (
        await registration_for_definition(
            plugin.definition, listing_uid=plugin.listing_uid
        )
        if plugin is not None
        else (await load_registrations()).get(public_id or "")
    )
    if row is None:
        raise PluginDataError(PluginDataMessages.SERVICE_NOT_REGISTERED, 404)
    if not row.live_in(guild_id):
        raise PluginDataError(PluginDataMessages.SERVICE_DISABLED, 409)
    return row


# --- the response cache -----------------------------------------------------


@dataclass
class _CacheEntry:
    result: Any
    expires_at: float


#: Keyed by the tuple built in ``_cache_key``, which contains every credential
#: the body depended on. Per worker, and per process — a body is never shared
#: across a boundary the key does not already name.
_cache: dict[str, _CacheEntry] = {}
#: One in-flight upstream call per key, so concurrent viewers of the same
#: dashboard collapse into a single request instead of a thundering herd.
_pending: dict[str, asyncio.Future[Any]] = {}
#: Upstream calls currently open per plug-in, for the per-worker cap.
_inflight: dict[str, int] = {}


def clear_plugin_data_cache(
    *, guild_id: int | None = None, plugin_id: int | None = None
) -> int:
    """Drop cached bodies, optionally narrowed to one guild or one install.

    A kill must not be outlived by a cached body: uninstalling, disabling, or
    revoking a credential all end with entries that were produced under the
    authority just withdrawn. The kill switches are re-read on every request, so
    this is defence in depth rather than the only thing standing between a
    revocation and a stale row.
    """
    prefix = ""
    if guild_id is not None:
        prefix = f"{guild_id}:" if plugin_id is None else f"{guild_id}:{plugin_id}:"
    dropped = [key for key in _cache if not prefix or key.startswith(prefix)]
    for key in dropped:
        _cache.pop(key, None)
    return len(dropped)


def _cache_key(
    *,
    guild_id: int | None,
    plugin: GuildPlugin,
    endpoint_id: str,
    canonical_params: str,
    refs: Mapping[str, str],
    fields: Mapping[str, Mapping[str, Any]],
    actor: str | None = None,
) -> str:
    """Every credential the response depended on, in one string.

    Guild and install lead so an entry is scoped to the same boundary the
    request was, and a prefix drop can retire one install's answers. The
    fingerprint covers the stored configuration as a whole rather than only the
    connections this endpoint named: rotating a credential is rare next to reading
    a widget, and narrowing it would trade a cheap hash for the chance of
    serving a body a withdrawn credential produced.
    """
    depends: dict[str, Any] = {
        "version": plugin.listing_version,
        "config": plugin.config or {},
        "secret_fields": plugin.secret_fields or {},
        "refs": dict(sorted(refs.items())),
        "actor": actor,
    }
    if is_declarative(plugin.definition):
        # What a declarative endpoint's expressions read, a member's own
        # connection's fields and the install's settings among them.
        depends["fields"] = fields
        depends["installed"] = plugin_config_service.install_settings(plugin)
    fingerprint = hashlib.sha256(
        json.dumps(
            depends,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"{guild_id}:{plugin.id}:{endpoint_id}:{canonical_params}:{fingerprint}"


def _cache_get(key: str) -> Any:
    entry = _cache.get(key)
    if entry is None:
        return None
    if entry.expires_at <= time.monotonic():
        _cache.pop(key, None)
        return None
    return entry.result


def _cache_put(key: str, result: Any, ttl: int) -> None:
    if ttl <= 0:
        return
    if len(_cache) >= MAX_CACHE_ENTRIES:
        now = time.monotonic()
        for stale in [k for k, v in _cache.items() if v.expires_at <= now]:
            _cache.pop(stale, None)
        while len(_cache) >= MAX_CACHE_ENTRIES:
            # Dicts preserve insertion order, so the oldest write goes first.
            _cache.pop(next(iter(_cache)), None)
    _cache[key] = _CacheEntry(result=result, expires_at=time.monotonic() + ttl)


def _effective_ttl(endpoint: Mapping[str, Any]) -> int:
    declared = endpoint.get("cache_ttl_seconds")
    if isinstance(declared, bool) or not isinstance(declared, int):
        return 0
    return max(0, min(declared, MAX_CACHE_TTL_SECONDS))


# --- the upstream call ------------------------------------------------------


#: Every plug-in answers every endpoint here. Fixed by the protocol rather than
#: chosen per plug-in, so a caller that knows an id needs nothing else.
ENDPOINTS_PATH = "/v1/endpoints"


def _endpoints_url(registration: RegistrationSnapshot) -> str:
    """Where this plug-in answers: the operator's base URL joined to the one path
    every plug-in serves. A manifest names an endpoint; only a registration says
    where the plug-in is."""
    return f"{registration.base_url.rstrip('/')}{ENDPOINTS_PATH}"


async def _read_body(
    request: httpx2.Request | Answered,
    *,
    transport: httpx2.AsyncBaseTransport | None,
) -> dict[str, Any]:
    """Send one bounded request and read what it answered with.

    Read as a stream against a byte ceiling, parsed as JSON only, and refused
    unless the body is an object carrying a ``result`` object. Everything else
    is reported as the plug-in being unavailable — a dashboard tile says "this plug-in
    is not answering", which is true whether the service is down or talking a
    shape this build does not accept.

    The body is returned whole. What a widget reads of its result is the
    endpoint's own declaration; see :func:`project_returns`. A declarative
    call's envelope (:class:`Answered`) is read the same way, unsent.
    """
    body = (
        request.body
        if isinstance(request, Answered)
        else await _send(request, transport=transport)
    )

    # The plug-in answers with what it did — the endpoint it ran, whose credential
    # ran it, and the result — so the returns are one level in. Reported as the
    # plug-in being unavailable rather than as a bad request: from a dashboard's
    # side "this plug-in is not answering" is true whether the service is down or
    # talking a shape this build does not accept.
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict):
        raise PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE,
            502,
            "plug-in answered without a result",
        )
    return body


async def _send(
    request: httpx2.Request, *, transport: httpx2.AsyncBaseTransport | None
) -> Any:
    """Send one bounded request, and its body as JSON."""
    timeout = httpx2.Timeout(REQUEST_TIMEOUT_SECONDS, connect=REQUEST_TIMEOUT_SECONDS)
    try:
        async with httpx2.AsyncClient(
            timeout=timeout, follow_redirects=False, transport=transport
        ) as client:
            response = await client.send(request, stream=True)
            try:
                if response.status_code >= 400:
                    raise PluginDataError(
                        PluginDataMessages.SERVICE_UNAVAILABLE,
                        502,
                        f"plug-in answered {response.status_code}",
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise PluginDataError(
                            PluginDataMessages.RESPONSE_TOO_LARGE,
                            502,
                            "response exceeded the ceiling",
                        )
                    chunks.append(chunk)
            finally:
                await response.aclose()
    except httpx2.HTTPError as exc:
        raise PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE,
            502,
            f"plug-in could not be read: {exc}",
        ) from exc

    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE,
            502,
            "plug-in did not answer with JSON",
        ) from exc


async def _read_answer(
    request: httpx2.Request | Answered,
    *,
    endpoint: Mapping[str, Any],
    transport: httpx2.AsyncBaseTransport | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """What a widget reads of one answer: its result, through the returns the
    endpoint declares (:func:`project_returns`)."""
    body = await _read_body(request, transport=transport)
    return project_returns(body["result"], endpoint)


@dataclass(frozen=True)
class Answered:
    """An envelope a declarative call already answered with, read as a
    container's would be."""

    body: dict[str, Any]


@dataclass(frozen=True)
class CallingPlugin:
    """Another plug-in on whose request Initiative calls this one, and for whom.

    Carried into the context token (``act``, ``actor``, ``member``,
    ``initiative_id``) so the plug-in called knows who asked and on whose behalf.
    """

    #: The calling plug-in's public id.
    public_id: str
    #: ``installation`` or ``member``.
    actor: str
    #: The member, by the called install's own reference for them.
    member_ref: str | None = None
    #: The initiative the caller's token is narrowed to.
    initiative_id: int | None = None


async def _call_plugin[T](
    *,
    registration: RegistrationSnapshot,
    plugin: GuildPlugin,
    guild_id: int | None,
    endpoint_id: str,
    params: Mapping[str, Any],
    refs: Mapping[str, str],
    fields: Mapping[str, Mapping[str, Any]],
    transport: httpx2.AsyncBaseTransport | None,
    read: Callable[[httpx2.Request | Answered], Awaitable[T]],
    caller: CallingPlugin | None = None,
    viewer: str | None = None,
    subject: Mapping[str, Any] | None = None,
    actor: str | None = None,
    item: Mapping[str, Any] | None = None,
    element: str | None = None,
) -> T:
    """One upstream call, under this worker's in-flight cap for the plug-in, and
    what ``read`` made of its answer. Sent once: nothing here retries.

    ``viewer`` and ``subject`` are a container's action's: the reader who ran
    it, by this install's reference for them, and the item it was run on.

    A declarative plug-in is called by Initiative itself
    (:func:`~app.services.marketplace.declarative.call_endpoint`), with no
    context token and no signature, since there is no plug-in to receive either.
    Its action's call names the ``actor`` whose credential it runs on, the
    ``item`` and the list ``element`` it was run from, which the endpoint's
    expressions read.
    """
    declarative = is_declarative(plugin.definition)
    if not declarative and not plugin_platform_signing_enabled():
        raise PluginDataError(PluginServiceMessages.SIGNING_NOT_CONFIGURED, 503)

    public_id = registration.public_id
    if _inflight.get(public_id, 0) >= MAX_INFLIGHT_PER_PLUGIN:
        logger.info(
            "plug-in data: %s is at this worker's in-flight ceiling (%s)",
            public_id,
            MAX_INFLIGHT_PER_PLUGIN,
        )
        raise PluginDataError(PluginDataMessages.BUSY, 503)
    _inflight[public_id] = _inflight.get(public_id, 0) + 1
    try:
        if declarative:
            # Imported here: the executor reaches the connection flows, which
            # read this module's limits.
            from app.services.marketplace.declarative import call_endpoint

            return await read(
                Answered(
                    await call_endpoint(
                        registration=registration,
                        plugin=plugin,
                        guild_id=int(guild_id or 0),
                        endpoint_id=endpoint_id,
                        params=params,
                        refs=refs,
                        fields=fields,
                        actor=caller.actor if caller is not None else actor,
                        item=item,
                        element=element,
                    )
                )
            )
        # What this plug-in calls the guild, and where the guild stands, which
        # the token carries.
        community = int(guild_id or 0)
        try:
            guild_ref = await ensure_plugin_guild_ref(
                guild_id=community, public_id=public_id
            )
        except PluginNameRefused as exc:
            raise PluginDataError(PluginDataMessages.PLUGIN_DISABLED, 409) from exc
        status = await community_status(community)
        try:
            token, _ = mint_context_token(
                public_id=public_id,
                guild_ref=guild_ref,
                plugin_install_id=plugin.id,
                scope="endpoint",
                community_status=status,
                endpoint_id=endpoint_id,
                connection_refs=refs,
                caller=caller.public_id if caller is not None else None,
                actor=caller.actor if caller is not None else None,
                member=caller.member_ref if caller is not None else None,
                initiative_id=caller.initiative_id if caller is not None else None,
                viewer=viewer,
                subject=subject,
            )
        except PluginPlatformSigningNotConfiguredError as exc:
            raise PluginDataError(
                PluginServiceMessages.SIGNING_NOT_CONFIGURED, 503
            ) from exc

        # POST rather than GET, and a body rather than a query string: one
        # path serves every endpoint, so which one is being called is part of
        # what is sent rather than part of where it is sent.
        try:
            request = await build_validated_request(
                "POST",
                _endpoints_url(registration),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                content=json.dumps(
                    {
                        "endpoint": endpoint_id,
                        "params": dict(params),
                    }
                ).encode("utf-8"),
                # A plug-in service is an operator-configured destination and is
                # typically a container on the deployment's own network. Plain
                # http stays confined to those addresses by the target policy.
                allow_private=True,
            )
        except (WebhookTargetUrlError, WebhookTargetUrlPrivateError) as exc:
            raise PluginDataError(
                PluginDataMessages.SERVICE_UNAVAILABLE, 502, f"target refused: {exc}"
            ) from exc

        return await read(request)
    finally:
        remaining = _inflight.get(public_id, 1) - 1
        if remaining > 0:
            _inflight[public_id] = remaining
        else:
            _inflight.pop(public_id, None)


# --- the whole path ---------------------------------------------------------


async def fetch_plugin_source(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    endpoint_id: str,
    raw_params: str | None,
    user_id: int | None,
    is_guild_admin: bool,
    as_installation: bool = False,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> PluginDataResult:
    """Resolve one endpoint for one caller (:func:`prepare_plugin_source`),
    and make the call."""
    call = await prepare_plugin_source(
        session,
        plugin=plugin,
        endpoint_id=endpoint_id,
        raw_params=raw_params,
        user_id=user_id,
        is_guild_admin=is_guild_admin,
        as_installation=as_installation,
        transport=transport,
    )
    return await call()


async def prepare_plugin_source(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    endpoint_id: str,
    raw_params: str | None,
    user_id: int | None,
    is_guild_admin: bool,
    as_installation: bool = False,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> Callable[[], Awaitable[PluginDataResult]]:
    """Resolve one endpoint for one caller, and hand back the call to make.

    Everything the call needs from *session* is read here, so the call itself
    reads nothing from it, and several can be made at once.

    The install has already been loaded under the caller's own guild session, so
    the guild boundary and a guild admin's wider reach are settled before this
    runs. What is decided here is the plug-in's own vocabulary: the endpoint exists,
    the caller may read it, both kill switches are open, the parameters are ones
    the endpoint declared, and the credentials it named are present.

    The call is made as the first of the endpoint's ``actors`` it can be
    (:func:`first_actor`), or, where it declares none, on every credential
    the caller and the community hold. ``as_installation`` is a dashboard
    that runs as its initiative: the call is made as the installation, on the
    community's connections alone.
    """
    endpoint = find_read_endpoint(plugin.definition, endpoint_id)
    if endpoint is None or (
        service_public_id(plugin.definition) is None
        and not is_declarative(plugin.definition)
    ):
        raise PluginDataError(PluginDataMessages.ENDPOINT_NOT_FOUND, 404)

    if is_admin_only(endpoint) and not is_guild_admin:
        raise PluginDataError(PluginDataMessages.ADMIN_ONLY, 403)
    if not plugin.enabled:
        raise PluginDataError(PluginDataMessages.PLUGIN_DISABLED, 409)

    guild_id = routed_guild_id(session)
    registration = await _load_registration(None, guild_id=guild_id, plugin=plugin)
    params, canonical = validate_params(endpoint, raw_params)
    declared = endpoint.get("actors")
    actors = declared if isinstance(declared, list) and declared else None
    actor: str | None = None
    if as_installation or actors is not None:
        actor, refs, fields = await first_actor(
            session,
            plugin=plugin,
            endpoint=endpoint,
            user_id=user_id,
            actors=[
                candidate
                for candidate in actors or ["installation"]
                if not as_installation or candidate == "installation"
            ],
        )
    else:
        refs, fields = await _resolve_connections(
            session, plugin=plugin, endpoint=endpoint, user_id=user_id
        )

    key = _cache_key(
        guild_id=guild_id,
        plugin=plugin,
        endpoint_id=endpoint_id,
        canonical_params=canonical,
        refs=refs,
        fields=fields,
        actor=actor,
    )

    async def read(
        request: httpx2.Request | Answered,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return await _read_answer(request, endpoint=endpoint, transport=transport)

    async def call() -> PluginDataResult:
        rows, values = await _call_plugin(
            registration=registration,
            plugin=plugin,
            guild_id=guild_id,
            endpoint_id=endpoint_id,
            params=params,
            refs=refs,
            fields=fields,
            transport=transport,
            read=read,
            actor=actor,
        )
        return PluginDataResult(rows=rows, values=values, fetched_at=datetime.now(UTC))

    async def answer() -> PluginDataResult:
        result, cached = await cached_call(key, _effective_ttl(endpoint), call)
        return replace(result, cached=True) if cached else result

    return answer


async def prepare_for_session(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    endpoint_id: str,
    params: Mapping[str, Any],
    as_installation: bool = False,
) -> Callable[[], Awaitable[PluginDataResult]]:
    """The call to one of *plugin*'s read endpoints with *params*, for the
    person *session* was routed for (:func:`prepare_plugin_source`). A
    plug-in's minimum age holds for its rows as for its tiles."""
    # Imported here: the age check reads the platform's settings.
    from app.services.tenant import plugin_age

    user_id = routed_context(session).user_id
    if plugin_age.declared_minimum(plugin.definition) and not plugin_age.age_allows(
        plugin.definition, await plugin_age.current_viewer(user_id)
    ):
        raise PluginDataError(GuildPluginMessages.AGE_RESTRICTED, 403)
    standing = guild_context(session)
    return await prepare_plugin_source(
        session,
        plugin=plugin,
        endpoint_id=endpoint_id,
        raw_params=json.dumps(dict(params)),
        user_id=user_id,
        is_guild_admin=bool(standing and standing.is_admin),
        as_installation=as_installation,
    )


async def cached_call[T](
    key: str, ttl: int, call: Callable[[], Awaitable[T]]
) -> tuple[T, bool]:
    """``call``'s answer through the response cache, and whether it came from
    there.

    A stored answer is reused until ``ttl`` runs out, and concurrent callers
    with the same ``key`` share one upstream call. ``key`` must contain every
    credential the answer depended on (:func:`_cache_key`).
    """
    hit = _cache_get(key)
    if hit is not None:
        return hit, True

    pending = _pending.get(key)
    if pending is not None:
        # Someone is already asking this exact question with these exact
        # credentials. Wait for their answer rather than making a second call.
        return await asyncio.shield(pending), False

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    _pending[key] = future
    try:
        result = await call()
    except BaseException as exc:
        if not future.done():
            future.set_exception(exc)
        # Nobody may be waiting; reading the result keeps asyncio from logging
        # the exception as never retrieved.
        future.exception()
        raise
    else:
        if not future.done():
            future.set_result(result)
        _cache_put(key, result, ttl)
        return result, False
    finally:
        _pending.pop(key, None)


# --- where the community stands -----------------------------------------------
#
# A manifest may name one of its reads as its ``community_summary``: where the
# community stands with the plug-in (runs used this period, credits left). The
# community's Usage tab draws it, and so does the operator's sheet for the
# community. Both read it through these, on a session already routed to the
# community.


def community_summary_endpoint(plugin: GuildPlugin) -> dict[str, Any] | None:
    """The read an enabled install names as its ``community_summary``, or None."""
    endpoint_id = (plugin.definition or {}).get("community_summary")
    if not plugin.enabled or not isinstance(endpoint_id, str):
        return None
    return find_read_endpoint(plugin.definition, endpoint_id)


async def community_summaries(session: AsyncSession) -> PluginSummaryListResponse:
    """The installs whose summary declares something it returns, with what it
    returns. Nothing is fetched here: each summary is read on its own, so one
    slow plug-in holds up only its own card."""
    plugins = (await session.exec(select(GuildPlugin).order_by(GuildPlugin.id))).all()
    items = []
    for plugin in plugins:
        returns = (community_summary_endpoint(plugin) or {}).get("returns") or []
        if returns:
            items.append(
                PluginSummaryRead(
                    plugin_id=plugin.id,
                    name=plugin.name,
                    returns=[PluginSummaryReturn(**value) for value in returns],
                )
            )
    return PluginSummaryListResponse(items=items)


async def read_community_summary(
    session: AsyncSession, *, plugin_id: int, user_id: int | None
) -> PluginDataResponse:
    """One install's summary, read with the community's admin standing.

    ``user_id`` is the reader when they are one of the community's people, so a
    per-member connection can answer for them; an operator reads with none. An
    install that names no summary, or is switched off, answers 404.
    """
    plugin = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
    ).first()
    endpoint = community_summary_endpoint(plugin) if plugin else None
    if plugin is None or endpoint is None:
        raise PluginDataError(PluginDataMessages.ENDPOINT_NOT_FOUND, 404)
    result = await fetch_plugin_source(
        session,
        plugin=plugin,
        endpoint_id=endpoint["id"],
        raw_params=None,
        user_id=user_id,
        is_guild_admin=True,
    )
    return PluginDataResponse(
        rows=result.rows,
        values=result.values,
        fetched_at=result.fetched_at,
        cached=result.cached,
    )


# --- filling a menu ---------------------------------------------------------
#
# A parameter whose permitted values only the plug-in can know — a repository, a
# label, a board — declares ``options_from``: a read of the plug-in's own that
# answers which values there are, and which of its returns holds them. Without
# something resolving that, a consumer has the declaration and no way to act on
# it, so every such parameter is a text box somebody fills in from memory.
#
# **This is the one route that reaches an endpoint no dashboard has bound.** It
# has to be: the whole point is filling in a form for a widget that is not
# placed yet, so there is no dashboard whose gates could decide it. What stands
# in for that is structural rather than a second permission check:
#
# * the source is never named by the caller. It is read out of the plug-in's own
#   pinned declaration, from the ``options_from`` of the parameter being filled
#   in, so the reachable set is exactly the reads a publisher marked as menu
#   sources — not every read the plug-in offers;
# * the parameters that source is called with are the ones its ``needs`` names,
#   mapped from answers the same form already holds, so a caller cannot shape
#   the upstream request;
# * the source is fetched by ``fetch_plugin_source`` exactly as it is for a placed
#   tile, on the caller's own credentials and with its own ``admin_only``
#   enforced. What comes back is what this caller may see, or nothing.

#: The most values one menu hands back. A picker is a control somebody reads,
#: and a plug-in answering with thousands is answering a different question.
MAX_PARAM_OPTIONS = 500

#: Why there is no menu. **None of these are errors.** A parameter whose source
#: will not resolve stays enterable — a vendor outage, a credential nobody has
#: connected, a sibling not yet chosen must never turn into a value that cannot
#: be typed, because that makes a valid configuration unreachable.
#:
#: The parameter declares no source at all: there was never a menu to offer.
OPTIONS_NO_SOURCE = "no-source"
#: The source needs a sibling this form has not answered yet — a repository's
#: labels before a repository is chosen. Ask again once it has one.
OPTIONS_NEEDS_SIBLING = "needs-sibling"
#: The source was called and did not answer: the plug-in is down, a credential is
#: missing, or this caller may not read it.
OPTIONS_UNRESOLVED = "unresolved"


def find_param(endpoint: Mapping[str, Any], param_key: str) -> dict[str, Any] | None:
    """One declared parameter of an endpoint, or None."""
    declared = endpoint.get("params")
    for entry in declared if isinstance(declared, list) else []:
        if isinstance(entry, dict) and entry.get("key") == param_key:
            return entry
    return None


def _option_values(
    rows: list[dict[str, Any]], key: str, label_key: str | None
) -> list[dict[str, str]]:
    """The column a source names, as values a control can offer.

    Read by name and nothing else, the same way a widget reads an answer. A row
    missing the value contributes nothing; one whose value repeats is kept once,
    in the order the plug-in gave, because that order is the plug-in's answer to "which
    of these first".
    """
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        raw = row.get(key)
        if raw is None or isinstance(raw, (dict, list, bool)):
            continue
        value = str(raw)
        if not value or value in seen:
            continue
        seen.add(value)
        option = {"value": value}
        if label_key:
            shown = row.get(label_key)
            if shown is not None and not isinstance(shown, (dict, list)):
                option["label"] = str(shown)
        options.append(option)
        if len(options) >= MAX_PARAM_OPTIONS:
            break
    return options


def _supplied_siblings(endpoint: Mapping[str, Any], raw: str | None) -> dict[str, Any]:
    """A part-filled form's answers, keyed by the parameters it declares.

    Deliberately *not* ``validate_params``: that one is the fetch path and holds
    a form to the whole contract, refusing a call that leaves a required
    parameter out. A form being filled in is incomplete by definition — that is
    what filling one in means — so the check here is only that a key is one the
    endpoint declares. Anything else is dropped rather than forwarded, so what
    reaches the source is a sibling's answer and never a caller's own key.
    """
    if raw is None or not raw.strip():
        return {}
    if len(raw.encode("utf-8")) > MAX_PARAMS_BYTES:
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400) from exc
    if not isinstance(parsed, dict):
        raise PluginDataError(PluginDataMessages.INVALID_PARAMS, 400)

    declared = {
        entry["key"]
        for entry in (endpoint.get("params") or [])
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    }
    return {key: value for key, value in parsed.items() if key in declared}


async def resolve_param_options(
    session: AsyncSession,
    *,
    plugin: GuildPlugin,
    endpoint_id: str,
    param_key: str,
    raw_params: str | None,
    user_id: int,
    is_guild_admin: bool,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> tuple[list[dict[str, str]], str | None]:
    """The values one parameter permits, from the read its plug-in named.

    The parameter may be a read's, for a widget's binding, or a write's, for
    the question an action asks before it runs: either way what is called is
    the read the parameter's ``options_from`` names, never the endpoint
    declaring it, so filling in a form is no way to make a plug-in act.

    Returns the options and, when there are none, why — never an exception for
    a source that simply would not resolve. The caller draws a menu when there
    is one and leaves the field typeable when there is not.
    """
    endpoint = endpoint_by_id(
        plugin.definition, endpoint_id, directions=("read", "write")
    )
    if endpoint is None:
        raise PluginDataError(PluginDataMessages.ENDPOINT_NOT_FOUND, 404)
    # A form for an endpoint the caller may not read is not theirs to fill in.
    if is_admin_only(endpoint) and not is_guild_admin:
        raise PluginDataError(PluginDataMessages.ADMIN_ONLY, 403)

    param = find_param(endpoint, param_key)
    if param is None:
        raise PluginDataError(PluginDataMessages.PARAM_NOT_FOUND, 404)

    source = param.get("options_from")
    if not isinstance(source, dict):
        return [], OPTIONS_NO_SOURCE

    source_id = source.get("endpoint")
    key = source.get("key")
    if not isinstance(source_id, str) or not isinstance(key, str):
        return [], OPTIONS_NO_SOURCE

    # What the same form has answered so far, which is the only thing a sibling
    # can be filled from.
    supplied = _supplied_siblings(endpoint, raw_params)

    needs = source.get("needs")
    asked: dict[str, Any] = {}
    for theirs, ours in (needs if isinstance(needs, dict) else {}).items():
        answer = supplied.get(ours)
        # Absent, blank and empty-list are one state: the form has not answered
        # it yet, so the source is not asked and the field stays enterable.
        if answer is None or (isinstance(answer, (str, list)) and not answer):
            return [], OPTIONS_NEEDS_SIBLING
        if isinstance(answer, str) and not answer.strip():
            return [], OPTIONS_NEEDS_SIBLING
        asked[theirs] = answer

    try:
        result = await fetch_plugin_source(
            session,
            plugin=plugin,
            endpoint_id=source_id,
            raw_params=json.dumps(asked) if asked else None,
            user_id=user_id,
            is_guild_admin=is_guild_admin,
            transport=transport,
        )
    except PluginDataError:
        return [], OPTIONS_UNRESOLVED

    label_key = source.get("label_key")
    options = _option_values(
        result.rows, key, label_key if isinstance(label_key, str) else None
    )
    return options, None if options else OPTIONS_UNRESOLVED
