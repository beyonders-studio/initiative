"""Tests for app-level exception handlers in app.main."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from httpx2 import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

import app.main as main_module
from app.core.config import API_V1_STR, Settings, settings
from app.core.errors import CodedError
from app.main import (
    McpBarePathMiddleware,
    SecurityHeadersMiddleware,
    coded_error_handler,
    validation_exception_handler,
)
from app.testing import (
    captcha_switched_on,
    create_plugin_service_registration,
    in_request_tasks,
)


async def test_validation_handler_strips_input_and_url() -> None:
    # FastAPI's default 422 echoes back `input` (and a pydantic docs `url`). On
    # a failed password/secret validation that would echo the submitted value.
    # The handler must drop them while keeping loc/msg/type.
    exc = RequestValidationError(
        [
            {
                "type": "string_too_long",
                "loc": ("body", "password"),
                "msg": "String should have at most 128 characters",
                "input": "correct horse battery staple - do not echo",
                "url": "https://errors.pydantic.dev/2/v/string_too_long",
            }
        ]
    )

    response = await validation_exception_handler(None, exc)

    assert response.status_code == 422
    payload = json.loads(response.body)
    assert payload == {
        "detail": [
            {
                "type": "string_too_long",
                "loc": ["body", "password"],
                "msg": "String should have at most 128 characters",
            }
        ]
    }
    # The echoed secret and the pydantic docs URL must be gone entirely.
    assert "do not echo" not in response.body.decode()
    assert "errors.pydantic.dev" not in response.body.decode()


async def test_coded_error_is_answered_with_its_code_and_status() -> None:
    assert main_module.app.exception_handlers[CodedError] is coded_error_handler

    response = await coded_error_handler(None, CodedError("SOME_REFUSAL", 409))

    assert response.status_code == 409
    assert json.loads(response.body) == {"detail": "SOME_REFUSAL"}

    with_params = await coded_error_handler(
        None, CodedError("SOME_REFUSAL", 404, params={"kind": "file"})
    )
    assert json.loads(with_params.body) == {
        "detail": "SOME_REFUSAL",
        "params": {"kind": "file"},
    }


async def test_responses_carry_content_security_policy(client: AsyncClient) -> None:
    # The CSP middleware must attach an enforced policy to served responses.
    resp = await client.get("/api/v1/config")
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp


async def test_csp_admits_the_stored_captcha_provider(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The provider is a setting, so the header follows the stored value rather
    # than the env the process started with.
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", None)
    with captcha_switched_on():
        resp = await client.get("/api/v1/config")
    assert "https://*.hcaptcha.com" in resp.headers.get("content-security-policy", "")


# --- WebAssembly worker assets (WebAssembly is named on these responses only) ---


def test_wasm_worker_match_names_only_those_files() -> None:
    match = main_module._is_wasm_worker_asset
    # The widget sandbox (QuickJS) and the direct message ratchet (vodozemac),
    # bundled by Vite as classic scripts; pdf.js ships an ES module and is
    # emitted under its own version rather than a content hash.
    assert match("assets/workers/sandbox.worker-DQURGIoN.js")
    assert match("assets/workers/ratchet.worker-DQURGIoN.js")
    assert match("assets/workers/pdf.worker-6.3.289.mjs")

    # Every other built file is an ordinary asset: a fourth worker, a worker
    # whose name merely starts the same way, anything nested under a directory
    # that starts with the name, the sourcemap, and the app's own chunks.
    assert not match("assets/workers/other.worker-DQURGIoN.js")
    assert not match("assets/workers/worker-DQURGIoN.js")
    assert not match("assets/workers/sandbox.worker-DQURGIoN/payload.js")
    assert not match("assets/workers/ratchet.worker-DQURGIoN/payload.js")
    assert not match("assets/workers/pdf.worker-6.3.289/payload.mjs")
    assert not match("assets/workers/sandbox.worker-DQURGIoN.js.map")
    assert not match("assets/workers/pdf.worker-6.3.289.mjs.map")
    assert not match("assets/index-lSaaosYz.js")
    assert not match("assets/workers/")

    # The WebAssembly modules the pdf.js worker fetches are data, not script —
    # `script-src` never applies to them, and they take the app-wide policy.
    assert not match("assets/pdfjs-wasm/6.3.289/jbig2.wasm")
    assert not match("assets/pdfjs-wasm/6.3.289/jbig2_nowasm_fallback.js")


@pytest.mark.parametrize(
    ("stem", "suffix"),
    [("sandbox.worker", ".js"), ("ratchet.worker", ".js"), ("pdf.worker", ".mjs")],
)
async def test_only_the_wasm_worker_assets_carry_their_policy(
    client: AsyncClient, stem: str, suffix: str
) -> None:
    # End-to-end through the SPA file route: the worker bundle answers with the
    # WebAssembly policy, and the chunk next to it answers with the app-wide one.
    # Both filenames carry the stem: the cases share one static directory and can
    # run on different xdist workers, so a name common to both would be deleted
    # out from under whichever case is still reading it.
    worker = main_module.static_path / "assets" / "workers" / f"{stem}-t3st{suffix}"
    ordinary = main_module.static_path / "assets" / f"index-{stem}-t3st{suffix}"
    worker.parent.mkdir(parents=True, exist_ok=True)
    ordinary.parent.mkdir(parents=True, exist_ok=True)
    worker.write_text("// wasm worker\n")
    ordinary.write_text("// app chunk\n")
    try:
        worker_resp = await client.get(f"/assets/workers/{worker.name}")
        other_resp = await client.get(f"/assets/{ordinary.name}")
    finally:
        worker.unlink(missing_ok=True)
        ordinary.unlink(missing_ok=True)

    assert worker_resp.status_code == 200
    worker_csp = worker_resp.headers.get("content-security-policy", "")
    assert worker_csp == settings.wasm_worker_content_security_policy

    assert other_resp.status_code == 200
    other_csp = other_resp.headers.get("content-security-policy", "")
    assert "'wasm-unsafe-eval'" not in other_csp
    assert "script-src 'self'" in other_csp


# --- The registered plug-in frame origins (named on documents, and only there) ---


@pytest.mark.parametrize(
    "route",
    ["/c/7/plugins/12", "/c/7/initiatives/3/plugins/12", "/"],
)
async def test_every_document_frames_the_registered_plugins(
    client: AsyncClient, session: AsyncSession, route: str
) -> None:
    """One header, whatever the route. A plug-in opens the same way from a guild
    page, from inside an initiative, and from a tab the SPA navigated to after
    loading somewhere else — so the permission cannot be a property of which
    document the browser happened to ask for."""
    await create_plugin_service_registration(
        session,
        public_id="tests.framed",
        base_url="https://framed.example.test",
        allowed_origins=["https://framed.example.test"],
    )
    index = main_module.static_index_path
    # A real build leaves one here; only a run without one writes and removes it.
    written = not index.is_file()
    if written:
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text("<!doctype html>\n")
    try:
        document = await client.get(route)
        api = await client.get("/api/v1/config")
    finally:
        if written:
            index.unlink(missing_ok=True)

    assert document.status_code == 200
    assert "https://framed.example.test" in document.headers.get(
        "content-security-policy", ""
    )
    # Only a document frames anything, so every other response is unchanged.
    assert "https://framed.example.test" not in api.headers.get(
        "content-security-policy", ""
    )


async def test_register_validation_error_omits_input(client: AsyncClient) -> None:
    # End-to-end: a 422 from a real endpoint must not echo the submitted value.
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "supersecret-no-echo"},
    )
    assert resp.status_code == 422
    assert "supersecret-no-echo" not in resp.text
    for err in resp.json()["detail"]:
        assert "input" not in err


# --- HSTS (Strict-Transport-Security) ---


async def _hsts_for(app_url: str) -> str | None:
    """Run a request through SecurityHeadersMiddleware with the header value
    that ``app_url`` would produce, and return the emitted HSTS header (or None).

    The real ``_STRICT_TRANSPORT_SECURITY`` is computed once at import from the
    process Settings, so this drives the middleware with the value a fresh
    ``Settings(APP_URL=...)`` would have produced — covering both http and https.
    """
    hsts_value = (
        "max-age=63072000; includeSubDomains"
        if Settings(APP_URL=app_url).app_url_is_https
        else None
    )
    probe = FastAPI()
    probe.add_middleware(SecurityHeadersMiddleware)

    @probe.get("/ping")
    async def _ping() -> dict[str, str]:
        return {"ok": "true"}

    # Patch the module-level constant the middleware reads.
    original = main_module._STRICT_TRANSPORT_SECURITY
    main_module._STRICT_TRANSPORT_SECURITY = hsts_value
    try:
        async with AsyncClient(
            transport=ASGITransport(app=in_request_tasks(probe)), base_url="http://test"
        ) as ac:
            resp = await ac.get("/ping")
    finally:
        main_module._STRICT_TRANSPORT_SECURITY = original
    return resp.headers.get("strict-transport-security")


async def test_hsts_emitted_for_https_app_url() -> None:
    # An https APP_URL must yield a long-lived, subdomain-covering HSTS header.
    hsts = await _hsts_for("https://app.example.com")
    assert hsts == "max-age=63072000; includeSubDomains"


async def test_hsts_absent_for_http_app_url() -> None:
    # Over plain http the header is meaningless and must be omitted.
    assert await _hsts_for("http://localhost:5173") is None


async def test_no_hsts_in_test_env_http(client: AsyncClient) -> None:
    # The suite's APP_URL is http, so the live app must not emit HSTS.
    resp = await client.get("/api/v1/config")
    assert "strict-transport-security" not in resp.headers


# --- API docs ---


async def test_docs_and_openapi_are_served(client: AsyncClient) -> None:
    docs = await client.get("/api/v1/docs")
    schema = await client.get("/api/v1/openapi.json")
    assert docs.status_code == 200
    assert schema.status_code == 200
    assert schema.json()["info"]["title"]


async def test_docs_page_serves_scoped_csp(client: AsyncClient) -> None:
    # The custom /docs route relaxes CSP so Swagger's jsDelivr assets load, but
    # the relaxation must stay scoped to that page — /config keeps script-src 'self'.
    docs_csp = (await client.get("/api/v1/docs")).headers.get(
        "content-security-policy", ""
    )
    assert "https://cdn.jsdelivr.net" in docs_csp
    assert "https://static.cloudflareinsights.com" in docs_csp

    config_resp = await client.get("/api/v1/config")
    assert config_resp.status_code == 200
    other_csp = config_resp.headers.get("content-security-policy", "")
    assert "script-src" in other_csp
    assert "cdn.jsdelivr.net" not in other_csp.split("script-src")[1].split(";")[0]


def test_mcp_is_served_with_or_without_the_trailing_slash() -> None:
    """Both spellings of the MCP URL reach the mount, and neither redirects.

    ``ENABLE_MCP`` is off in the suite, so this mirrors the wiring in
    ``app.main`` — a sub-app mounted at ``/api/v1/mcp`` whose only route is its
    own root — and drives it over HTTP. ``root_path`` is echoed back because it
    is what the mount resolved, so the two spellings arriving alike is the
    assertion.
    """
    prefix = f"{API_V1_STR}/mcp"

    class _Root:  # a bare ASGI app, as fastmcp's streamable-HTTP handler is
        async def __call__(self, scope, receive, send) -> None:
            await PlainTextResponse(scope["root_path"])(scope, receive, send)

    mounted = FastAPI()
    mounted.mount(prefix, Starlette(routes=[Route("/", endpoint=_Root())]))
    mounted.add_middleware(McpBarePathMiddleware, prefix=prefix)

    http = TestClient(mounted)
    bare = http.get(prefix, follow_redirects=False)
    slashed = http.get(f"{prefix}/", follow_redirects=False)
    assert bare.status_code == slashed.status_code == 200
    assert bare.text == slashed.text == prefix

    # The rewrite is that one path and nothing around it.
    assert http.get(f"{prefix}other", follow_redirects=False).status_code == 404


@pytest.mark.always
def test_every_operation_has_its_own_name() -> None:
    names = [
        route.name
        for route in iter_route_contexts(main_module.app.routes)
        if isinstance(route.original_route, APIRoute) and route.include_in_schema
    ]
    assert sorted({n for n in names if names.count(n) > 1}) == []


#: Query parameter names a list does not take, and what it takes instead.
_LIST_PARAM_SPELLINGS = {
    "q": "search",
    "query": "search",
    "offset": "page",
    "skip": "page",
    "per_page": "page_size",
}


@pytest.mark.always
def test_every_list_pages_and_searches_the_same_way() -> None:
    """A list takes ``search`` for its search box and ``page``/``page_size`` for
    its pages, and a paged answer says whether there is more (``has_next``) —
    either itself, or in each group of a grouped answer. A feed that pages by
    ``cursor`` takes ``limit``, and is not a paged list."""
    spec = main_module.app.openapi()
    schemas = spec["components"]["schemas"]

    def resolved(schema: dict) -> dict:
        ref = schema.get("$ref")
        return schemas[ref.rsplit("/", 1)[-1]] if ref else schema

    def says_if_more(schema: dict) -> bool:
        fields = resolved(schema).get("properties", {})
        return "has_next" in fields or any(
            "has_next" in resolved(field.get("items", {})).get("properties", {})
            for field in fields.values()
            if field.get("type") == "array"
        )

    misspelt, unpaired, unpaged = [], [], []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            route = f"{method.upper()} {path}"
            params = {
                p["name"] for p in operation.get("parameters", []) if p["in"] == "query"
            }
            misspelt += [
                f"{route}: {name} -> {_LIST_PARAM_SPELLINGS[name]}"
                for name in sorted(params & _LIST_PARAM_SPELLINGS.keys())
            ]
            if ("page" in params) != ("page_size" in params):
                unpaired.append(route)
            if "page" in params:
                answer = (
                    operation["responses"]
                    .get("200", {})
                    .get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                )
                if not says_if_more(answer):
                    unpaged.append(route)

    assert misspelt == []
    assert unpaired == []
    # Subclass ``PageMeta`` and build the answer with ``build_paginated_response``.
    assert unpaged == []
