"""Every request is named, and says so on the way out."""

import logging

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from prometheus_client import REGISTRY
from starlette.datastructures import Headers

from app.core import audit_context, metrics, request_audit
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.request_audit import (
    REQUEST_ID_HEADER,
    RequestAuditMiddleware,
    record_privileged_edit,
    server_error,
)
from app.testing import emitted, in_request_tasks

VERSION = "/api/v1/version"
SIGN_IN = "/api/v1/auth/token"


async def test_a_response_carries_the_id_of_the_request(client: AsyncClient):
    answered = await client.get(VERSION)
    assert answered.status_code == 200
    assert audit_context.clean_request_id(answered.headers[REQUEST_ID_HEADER])


async def test_each_request_is_named_once(client: AsyncClient):
    first = await client.get(VERSION)
    second = await client.get(VERSION)
    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


async def test_a_supplied_id_is_ignored_where_nothing_sits_in_front(
    client: AsyncClient, monkeypatch
):
    """Reached directly, nothing upstream has named this request, so what
    arrives claiming to be its name is not."""
    monkeypatch.setattr(settings, "BEHIND_PROXY", False)
    answered = await client.get(VERSION, headers={REQUEST_ID_HEADER: "from-outside"})
    assert answered.headers[REQUEST_ID_HEADER] != "from-outside"


async def test_a_proxys_id_is_kept_so_both_logs_say_the_same_name(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "BEHIND_PROXY", True)
    answered = await client.get(VERSION, headers={REQUEST_ID_HEADER: "edge-abc-123"})
    assert answered.headers[REQUEST_ID_HEADER] == "edge-abc-123"


async def test_an_unusable_id_is_replaced_rather_than_passed_on(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "BEHIND_PROXY", True)
    answered = await client.get(VERSION, headers={REQUEST_ID_HEADER: "two words"})
    assert answered.headers[REQUEST_ID_HEADER] != "two words"
    assert audit_context.clean_request_id(answered.headers[REQUEST_ID_HEADER])


async def test_a_line_written_during_a_request_says_which_request(
    client: AsyncClient, capfd
):
    """The thread between this stream and the deployment's own logs: the id on
    the response is the id in the record."""
    capfd.readouterr()
    answered = await client.post(
        SIGN_IN, data={"username": "nobody@example.com", "password": "wrong-password"}
    )
    assert answered.status_code == 400

    (line,) = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert line["context"]["request_id"] == answered.headers[REQUEST_ID_HEADER]
    assert line["context"]["source_ip"]
    assert "grant_id" not in line["context"]


async def test_a_line_written_by_nobody_carries_no_request(session, capfd):
    """A sweep runs outside any request and says so, rather than borrowing the
    name of one."""
    from app.services import audit as audit_service
    from app.testing import create_user

    actor = await create_user(session)
    capfd.readouterr()
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
    )
    await session.commit()

    (line,) = emitted(capfd, AuditEventType.USER_AVATAR_REMOVED)
    assert line["context"] is None


async def test_a_request_that_fails_is_answered_and_written_under_its_name(caplog):
    """The server writes the traceback after the app has raised, in the task
    it ran the request in, where the request's context is still open; and
    Starlette's error middleware answers with the request's id."""
    app = FastAPI()
    app.add_middleware(RequestAuditMiddleware)
    app.add_exception_handler(Exception, server_error)

    @app.get("/api/v1/c/{community_id}/tasks/{task_id}")
    async def boom(community_id: int, task_id: int) -> None:
        raise RuntimeError("task failed")

    async def run_asgi(scope, receive, send):
        """What uvicorn does with each request."""
        try:
            await app(scope, receive, send)
        except Exception:
            logging.getLogger("uvicorn.error").exception(
                "Exception in ASGI application"
            )

    with caplog.at_level(logging.ERROR):
        async with AsyncClient(
            transport=ASGITransport(app=in_request_tasks(run_asgi)),
            base_url="http://test",
        ) as client:
            answered = await client.get("/api/v1/c/7/tasks/3")

    assert answered.status_code == 500
    [record] = [r for r in caplog.records if r.name == "uvicorn.error"]
    assert record.log_context == {
        "request_id": answered.headers[REQUEST_ID_HEADER],
        "guild_id": 7,
        "route": "/api/v1/c/{community_id}/tasks/{task_id}",
    }
    assert audit_context.current() is None


# --- sockets ------------------------------------------------------------


async def _drive_socket(scope: dict, inside) -> None:
    """Run ``inside`` as the app a socket handshake reaches."""

    async def app(_scope, _receive, _send):
        inside()

    async def receive():
        return {"type": "websocket.connect"}

    async def send(_message):
        return None

    await in_request_tasks(RequestAuditMiddleware(app))(scope, receive, send)


def _ws_scope() -> dict:
    return {
        "type": "websocket",
        "path": "/ws",
        "client": ("203.0.113.7", 51234),
        "headers": [
            (b"user-agent", b"Firefox/1"),
            (b"x-forwarded-for", b"198.51.100.20"),
        ],
    }


async def test_a_socket_is_named_for_as_long_as_it_is_open():
    """A socket has no response to carry an id back on, but every line it
    writes still says which session wrote it, and where it came from: the
    peer the ASGI server resolved, not a header the request carried."""
    seen = {}

    def inside():
        context = audit_context.current()
        seen["request_id"] = context.request_id
        seen["source_ip"] = audit_context.client_ip()
        seen["user_agent"] = audit_context.client_user_agent()

    await _drive_socket(_ws_scope(), inside)

    assert audit_context.clean_request_id(seen["request_id"])
    assert seen["source_ip"] == "203.0.113.7"
    assert seen["user_agent"] == "Firefox/1"
    assert audit_context.current() is None


def _requests_counted(route: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "initiative_http_requests_total",
            {"method": "GET", "route": route, "status": status},
        )
        or 0.0
    )


async def test_a_request_is_counted_by_the_route_it_matched(client: AsyncClient):
    """The label is the route as written, so every community's list is one
    series rather than one per community."""
    route = "/api/v1/c/{community_id}/initiatives/"
    before = _requests_counted(route, "401")

    answered = await client.get("/api/v1/c/424242/initiatives/")

    assert answered.status_code == 401
    assert _requests_counted(route, "401") == before + 1
    assert (
        REGISTRY.get_sample_value(
            "initiative_http_request_duration_seconds_count",
            {"method": "GET", "route": route},
        )
        or 0
    ) >= 1
    assert (
        REGISTRY.get_sample_value(
            "initiative_http_requests_in_progress", {"method": "GET"}
        )
        == 0
    )


async def test_an_open_socket_is_counted_until_it_closes():
    seen = {}

    def inside():
        seen["open"] = REGISTRY.get_sample_value("initiative_websocket_connections")

    before = REGISTRY.get_sample_value("initiative_websocket_connections")
    await _drive_socket(_ws_scope(), inside)

    assert seen["open"] == before + 1
    assert REGISTRY.get_sample_value("initiative_websocket_connections") == before


def test_an_unknown_method_is_labelled_other():
    assert metrics.method_label("GET") == "GET"
    assert metrics.method_label("BREW") == "other"
    assert metrics.method_label(None) == "other"


async def test_a_grantees_first_edit_is_written_down(capfd):
    """One line per session: that they edited it is the fact worth having."""
    recorded = {}

    def inside():
        audit_context.note_grant(
            actor_user_id=42, guild_id=7, grant_id=88, access_level="read_write"
        )
        capfd.readouterr()
        recorded["first"] = record_privileged_edit(
            guild_id=7, resource_type="file", resource_id=931, actor_user_id=42
        )
        recorded["lines"] = emitted(capfd, AuditEventType.PAM_CONTENT_EDITED)

    await _drive_socket(_ws_scope(), inside)

    assert recorded["first"] is True
    (line,) = recorded["lines"]
    assert line["actor_user_id"] == 42
    assert line["guild_id"] == 7
    assert line["target"] == {"type": "file", "id": 931}
    assert line["is_write"] is True
    assert line["context"]["grant_id"] == 88
    assert line["context"]["source_ip"] == "203.0.113.7"


async def test_a_members_own_editing_is_not_written_down(capfd):
    """This records privileged access. A member editing their community's own
    file is ordinary work."""
    recorded = {}

    def inside():
        capfd.readouterr()
        recorded["wrote"] = record_privileged_edit(
            guild_id=7, resource_type="file", resource_id=931, actor_user_id=42
        )
        recorded["lines"] = emitted(capfd)

    await _drive_socket(_ws_scope(), inside)

    assert recorded["wrote"] is False
    assert recorded["lines"] == []


async def test_an_edit_outside_any_session_records_nothing():
    assert (
        record_privileged_edit(
            guild_id=7, resource_type="file", resource_id=931, actor_user_id=42
        )
        is False
    )


async def test_every_429_is_counted_and_nothing_else():
    """Whichever limit answered it, a 429 is counted against the address."""
    from app.services.platform import security_signals

    async def answering(status: int):
        async def app(_scope, _receive, send):
            await send({"type": "http.response.start", "status": status, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        async def receive():
            return {"type": "http.request", "body": b""}

        async def send(_message):
            return None

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "client": ("203.0.113.8", 4000),
            "headers": [],
        }
        await RequestAuditMiddleware(app)(scope, receive, send)

    security_signals.discard()
    try:
        await answering(200)
        assert security_signals.pending() == 0
        await answering(429)
        assert "rate_limit_burst" in security_signals._counts.rules
    finally:
        security_signals.discard()


def test_a_proxy_not_trusted_is_pointed_out_where_one_is_expected(monkeypatch, caplog):
    """A forwarded header left unread from a public peer is a proxy to name
    in FORWARDED_ALLOW_IPS when the deployment says one sits in front, and
    passing traffic otherwise."""
    forwarded = Headers({"x-forwarded-for": "198.51.100.20"})
    with caplog.at_level(logging.WARNING, logger=request_audit.logger.name):
        for behind_proxy in (False, True):
            monkeypatch.setattr(settings, "BEHIND_PROXY", behind_proxy)
            monkeypatch.setattr(request_audit, "_forwarded_hint_at", None)
            request_audit._note_ignored_forwarded_header(forwarded, "93.184.216.34")

    [hint] = [r.getMessage() for r in caplog.records]
    assert "Set FORWARDED_ALLOW_IPS to the proxy's address" in hint


@pytest.mark.parametrize(
    ("behind_proxy", "client", "connecting", "seen"),
    [
        (True, "162.158.1.2", "2001:4860:0:0:0:0:0:8888", "2001:4860::8888"),
        (True, "162.158.1.2", "198.51.100.20", "198.51.100.20"),
        (True, "162.158.1.2", "not an address", "162.158.1.2"),
        (True, "203.0.113.7", "198.51.100.20", "203.0.113.7"),
        (False, "162.158.1.2", "198.51.100.20", "162.158.1.2"),
    ],
    ids=[
        "cloudflare names the visitor, in its own spelling",
        "cloudflare names the visitor",
        "cloudflare names no address",
        "a client that is not cloudflare's",
        "no proxy in front",
    ],
)
async def test_a_request_through_cloudflare_comes_from_its_visitor(
    monkeypatch, behind_proxy, client, connecting, seen
):
    """Behind Cloudflare's proxy and the deployment's own, the server
    resolves Cloudflare's edge; the visitor CF-Connecting-IP names is the
    client every reader sees, the scope's included."""
    monkeypatch.setattr(settings, "BEHIND_PROXY", behind_proxy)
    scope = {**_ws_scope(), "client": (client, 443)}
    scope["headers"] = [*scope["headers"], (b"cf-connecting-ip", connecting.encode())]
    found = {}

    def inside():
        found["source_ip"] = audit_context.client_ip()

    await _drive_socket(scope, inside)

    assert found["source_ip"] == seen
    assert scope["client"][0] == seen
