"""Origin checking for cookie-authenticated writes.

Each case is a request shape a browser can actually produce, including a
multipart form post from another origin -- which is a simple request, so no
preflight is involved and CORS is not what decides it.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.csrf import CSRF_ERROR_CODE, CsrfOriginMiddleware
from app.core.security import SESSION_COOKIE_NAME

SERVED = "https://app.example.test"


async def _write(request):
    return JSONResponse({"wrote": True})


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        type(settings), "cors_origins", property(lambda _self: [SERVED])
    )
    app = Starlette(
        routes=[
            Route("/write", _write, methods=["POST", "PUT", "PATCH", "DELETE"]),
            Route("/read", _write, methods=["GET"]),
        ]
    )
    app.add_middleware(CsrfOriginMiddleware)
    return TestClient(app)


def _cookie(client: TestClient) -> None:
    client.cookies.set(SESSION_COOKIE_NAME, "a-session")


def test_a_cross_site_form_post_is_refused(client):
    # A form on another origin, multipart so no preflight is involved, with the
    # session cookie attached as a browser would attach it.
    _cookie(client)

    response = client.post(
        "/write",
        files={"file": ("x.png", b"data", "image/png")},
        headers={"origin": "https://attacker.test", "sec-fetch-site": "cross-site"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == CSRF_ERROR_CODE


def test_a_refusal_is_counted_by_the_security_rules_and_not_written_down(client):
    from app.services.platform import security_signals

    security_signals.discard()
    _cookie(client)
    client.post(
        "/write",
        files={"file": ("x.png", b"data", "image/png")},
        headers={"origin": "https://attacker.test", "sec-fetch-site": "cross-site"},
    )
    try:
        assert "csrf_burst" in security_signals._counts.rules
    finally:
        security_signals.discard()


def test_a_cross_site_post_with_no_origin_at_all_is_refused(client):
    # Browsers send Origin on an unsafe method as a matter of course, so its
    # absence is not an answer of yes.
    _cookie(client)

    response = client.post("/write", json={})

    assert response.status_code == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_unsafe_method_is_covered(client, method):
    # All four, so the rule does not depend on which verb a route happens to
    # use.
    _cookie(client)

    response = client.request(
        method, "/write", headers={"origin": "https://attacker.test"}
    )

    assert response.status_code == 403


def test_a_same_origin_write_succeeds(client):
    _cookie(client)

    response = client.post(
        "/write", json={}, headers={"origin": SERVED, "sec-fetch-site": "same-origin"}
    )

    assert response.status_code == 200


def test_a_split_origin_deployment_still_writes(client):
    # The SPA hosted somewhere other than the API. Sec-Fetch-Site says
    # cross-site and it is legitimate; the allowlist is what distinguishes it,
    # and it is the same list CORS already credentials.
    _cookie(client)

    response = client.post(
        "/write", json={}, headers={"origin": SERVED, "sec-fetch-site": "cross-site"}
    )

    assert response.status_code == 200


def test_a_plain_http_deployment_writes_without_fetch_metadata(client):
    # Browsers send no Sec-Fetch-* to an origin they do not consider
    # trustworthy, so a deployment reached over plain HTTP at a LAN name gets
    # no conclusive answer -- and its Origin is not the configured APP_URL
    # either. The Host it was addressed to is what settles it (issue #1857).
    _cookie(client)

    response = client.post(
        "/write",
        json={},
        headers={"origin": "http://nas.local:8173", "host": "nas.local:8173"},
    )

    assert response.status_code == 200


def test_another_origin_is_refused_even_with_no_fetch_metadata(client):
    # The fallback compares the two; it does not stop asking.
    _cookie(client)

    response = client.post(
        "/write",
        json={},
        headers={"origin": "http://attacker.test", "host": "nas.local:8173"},
    )

    assert response.status_code == 403


def test_a_different_port_on_the_same_host_is_a_different_origin(client):
    _cookie(client)

    response = client.post(
        "/write",
        json={},
        headers={"origin": "http://nas.local:9999", "host": "nas.local:8173"},
    )

    assert response.status_code == 403


def test_fetch_metadata_is_believed_over_the_host_comparison(client):
    # A browser that did answer is not second-guessed: cross-site is an answer
    # of no, whatever the Host happens to say.
    _cookie(client)

    response = client.post(
        "/write",
        json={},
        headers={
            "origin": "http://nas.local:8173",
            "host": "nas.local:8173",
            "sec-fetch-site": "cross-site",
        },
    )

    assert response.status_code == 403


def test_an_http_page_writing_to_a_tls_request_is_refused(monkeypatch):
    # Same host, different scheme: a different origin, and the one direction
    # the host comparison must not wave through.
    monkeypatch.setattr(type(settings), "cors_origins", property(lambda _s: [SERVED]))
    app = Starlette(routes=[Route("/write", _write, methods=["POST"])])
    app.add_middleware(CsrfOriginMiddleware)
    tls_client = TestClient(app, base_url="https://nas.local")
    tls_client.cookies.set(SESSION_COOKIE_NAME, "a-session")

    response = tls_client.post(
        "/write", json={}, headers={"origin": "http://nas.local"}
    )

    assert response.status_code == 403


def test_a_tls_page_behind_a_proxy_that_drops_the_scheme_still_writes(client):
    # The proxy terminates TLS and was not asked to forward the scheme, so the
    # server sees http while the page was served over https. Same host, and the
    # browser would not have sent the request at all were it not.
    _cookie(client)

    response = client.post(
        "/write", json={}, headers={"origin": "https://nas.local", "host": "nas.local"}
    )

    assert response.status_code == 200


def test_same_site_is_not_taken_as_proof(client):
    # Same-site includes sibling subdomains, which is wider than the allowlist
    # this is meant to match.
    _cookie(client)

    response = client.post(
        "/write",
        json={},
        headers={"origin": "https://other.example.test", "sec-fetch-site": "same-site"},
    )

    assert response.status_code == 403


def test_a_header_authenticated_client_is_not_asked_for_anything(client):
    # Bearer tokens, API keys and device tokens are out of scope here; asking
    # them for an Origin would break API scripts and mobile shells for nothing.
    # Another scheme authenticates nothing, so beside it the cookie is still
    # what the request is authenticated by, and it is asked.
    _cookie(client)

    bearer = client.post("/write", json={}, headers={"authorization": "bearer a-token"})
    basic = client.post("/write", json={}, headers={"authorization": "Basic a-token"})

    assert bearer.status_code == 200
    assert basic.status_code == 403
    assert basic.json()["detail"] == CSRF_ERROR_CODE


def test_an_anonymous_request_is_not_refused_here(client):
    # No session cookie, so this has nothing to say about it. Whether the
    # request is allowed is the authentication layer's decision, and a 403 from
    # here would hide the 401 that explains it.
    response = client.post(
        "/write", json={}, headers={"origin": "https://attacker.test"}
    )

    assert response.status_code == 200


def test_a_read_is_untouched(client):
    _cookie(client)

    response = client.get("/read", headers={"origin": "https://attacker.test"})

    assert response.status_code == 200


def test_a_cookie_whose_name_merely_ends_in_the_session_name_is_not_a_session(client):
    # Whole-name comparison: `x_session_token` contains the session cookie's
    # name without being it.
    client.cookies.set(f"x_{SESSION_COOKIE_NAME}", "not-a-session")

    response = client.post(
        "/write", json={}, headers={"origin": "https://attacker.test"}
    )

    assert response.status_code == 200


# --- WebSocket handshakes ----------------------------------------------------
#
# WebSockets carry the session cookie and are not bound by the same-origin
# policy, and five routes fall back to that cookie when the first message
# supplies no token (collaboration, counters, events, queues, notifications).
# The HTTP rule above does not reach them: the middleware returned early on any
# non-HTTP scope.


def _ws_scope(
    *,
    cookie: str | None = None,
    origin: str | None = None,
    host: str | None = None,
    scheme: str = "ws",
) -> dict:
    headers = []
    if cookie is not None:
        headers.append((b"cookie", cookie.encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if host is not None:
        headers.append((b"host", host.encode()))
    return {
        "type": "websocket",
        "path": "/ws",
        "scheme": scheme,
        "headers": headers,
    }


async def _handshake(scope: dict) -> list[dict]:
    """Drive one handshake through the middleware and collect what it sent."""
    sent: list[dict] = []
    connected = {"value": False}

    async def app(_scope, _receive, send):
        connected["value"] = True
        await send({"type": "websocket.accept"})

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    await CsrfOriginMiddleware(app)(scope, receive, send)
    return [*sent, {"reached_plugin": connected["value"]}]


async def test_a_cross_site_websocket_with_a_session_cookie_is_refused(monkeypatch):
    monkeypatch.setattr(type(settings), "cors_origins", property(lambda _s: [SERVED]))

    result = await _handshake(
        _ws_scope(
            cookie=f"{SESSION_COOKIE_NAME}=a-session", origin="https://attacker.test"
        )
    )

    assert result[0]["type"] == "websocket.close"
    assert result[-1]["reached_plugin"] is False


async def test_a_same_origin_websocket_connects(monkeypatch):
    monkeypatch.setattr(type(settings), "cors_origins", property(lambda _s: [SERVED]))

    result = await _handshake(
        _ws_scope(cookie=f"{SESSION_COOKIE_NAME}=a-session", origin=SERVED)
    )

    assert result[-1]["reached_plugin"] is True


async def test_a_plain_http_websocket_connects_on_the_host_comparison(monkeypatch):
    # The other half of issue #1857: the same deployment's event stream. A
    # handshake carries no fetch metadata to an untrusted origin either.
    monkeypatch.setattr(type(settings), "cors_origins", property(lambda _s: [SERVED]))

    result = await _handshake(
        _ws_scope(
            cookie=f"{SESSION_COOKIE_NAME}=a-session",
            origin="http://nas.local:8173",
            host="nas.local:8173",
        )
    )

    assert result[-1]["reached_plugin"] is True


async def test_a_websocket_from_another_origin_on_the_same_host_is_refused(monkeypatch):
    monkeypatch.setattr(type(settings), "cors_origins", property(lambda _s: [SERVED]))

    result = await _handshake(
        _ws_scope(
            cookie=f"{SESSION_COOKIE_NAME}=a-session",
            origin="http://attacker.test",
            host="nas.local:8173",
        )
    )

    assert result[0]["type"] == "websocket.close"
    assert result[-1]["reached_plugin"] is False


async def test_a_websocket_without_a_session_cookie_is_not_this_rule_s_business(
    monkeypatch,
):
    # A token-authenticated client. Whether it may connect is the route's
    # decision, and refusing it here would hide that answer.
    monkeypatch.setattr(type(settings), "cors_origins", property(lambda _s: [SERVED]))

    result = await _handshake(_ws_scope(origin="https://attacker.test"))

    assert result[-1]["reached_plugin"] is True
