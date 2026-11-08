"""The account's own "where you're signed in" list, and ending one from it."""

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints import session_opening
from app.api.v1.platform_endpoints import sessions as sessions_endpoints
from app.api.v1.platform_endpoints import users as users_endpoints
from app.api.v1.platform_endpoints.dm_transport_test import _registration
from app.core import auth_context
from app.core.security import get_password_hash
from app.models.platform.dm_device import DmDevice
from app.models.platform.user import UserStatus
from app.services import content_sockets
from app.services.content_sockets import (
    WS_CREDENTIAL_ENDED,
    ContentSockets,
    Credential,
    Subscriber,
    Wire,
    resource_room,
)
from app.services.platform import api_keys as api_keys_service
from app.services.platform.ws_auth import authenticate_ws_token
from app.testing import create_user, get_auth_headers

CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
FIREFOX_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0"
)

PASSWORD = "testpassword123"


async def _signed_in_user(session: AsyncSession, email: str):
    return await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(PASSWORD),
        status=UserStatus.active,
        email_verified=True,
    )


async def _sign_in(
    client: AsyncClient, email: str, *, user_agent: str, device: bool = False
):
    """A browser's sign-in, or with ``device`` the app's, which it tells apart
    by the origin it presents."""
    headers = {"user-agent": user_agent}
    if device:
        headers["Origin"] = "https://studio.beyonders.initiative"
    return await client.post(
        "/api/v1/auth/token",
        data={"username": email, "password": PASSWORD},
        headers=headers,
    )


async def _keep_messages(client: AsyncClient, signed_in, seed: int) -> str:
    """Register a message key store under the session ``signed_in`` opened."""
    registered = await client.post(
        "/api/v1/me/dm/devices",
        json=_registration(seed),
        headers={"Authorization": f"Bearer {signed_in.json()['access_token']}"},
    )
    assert registered.status_code == 201, registered.text
    return registered.json()["device_id"]


async def test_the_list_names_each_browser_and_marks_the_one_asking(
    client: AsyncClient, session: AsyncSession
):
    """Two browsers signed in; the list says what each one is and which of
    them is reading it."""
    await _signed_in_user(session, "two-browsers@example.com")

    first = await _sign_in(
        client, "two-browsers@example.com", user_agent=FIREFOX_WINDOWS
    )
    assert first.status_code == 200
    client.cookies.clear()
    second = await _sign_in(client, "two-browsers@example.com", user_agent=CHROME_MAC)
    asking = second.json()["access_token"]

    listed = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {asking}", "user-agent": CHROME_MAC},
    )
    assert listed.status_code == 200
    rows = listed.json()

    labels = {row["label"] for row in rows}
    assert labels == {"Chrome on macOS", "Firefox on Windows"}
    assert all(row["kind"] == "desktop" for row in rows)

    current = [row for row in rows if row["is_current"]]
    assert [row["label"] for row in current] == ["Chrome on macOS"]


async def test_the_list_carries_no_refresh_token(
    client: AsyncClient, session: AsyncSession
):
    """The row a person reads is the one they need to recognise a device, and
    nothing from the credential columns beside it."""
    await _signed_in_user(session, "no-secrets@example.com")
    login = await _sign_in(client, "no-secrets@example.com", user_agent=CHROME_MAC)

    listed = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert listed.status_code == 200
    assert set(listed.json()[0]) == {
        "id",
        "message_device_id",
        "device",
        "label",
        "kind",
        "ip",
        "started_at",
        "last_used_at",
        "is_current",
    }


async def test_a_session_is_dated_from_its_sign_in_not_its_last_renewal(
    client: AsyncClient, session: AsyncSession
):
    """A refresh mints a new row, so reading the tip's own age would report a
    month-old browser as a quarter of an hour old."""
    await _signed_in_user(session, "long-lived@example.com")
    login = await _sign_in(client, "long-lived@example.com", user_agent=CHROME_MAC)
    before = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    started = before.json()[0]["started_at"]

    rotated = await client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200

    after = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {rotated.json()['access_token']}"},
    )
    rows = after.json()
    # Still one sign-in, still dated from it.
    assert len(rows) == 1
    assert rows[0]["started_at"] == started


async def test_ending_a_session_stops_it_renewing(
    client: AsyncClient, session: AsyncSession
):
    """And withdraws the message device collecting under it."""
    await _signed_in_user(session, "end-one@example.com")
    doomed = await _sign_in(client, "end-one@example.com", user_agent=FIREFOX_WINDOWS)
    doomed_refresh = doomed.cookies.get("refresh_token")
    keys = await _keep_messages(client, doomed, seed=1)
    client.cookies.clear()
    asking = await _sign_in(client, "end-one@example.com", user_agent=CHROME_MAC)
    headers = {"Authorization": f"Bearer {asking.json()['access_token']}"}

    rows = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    target = next(row for row in rows if row["label"] == "Firefox on Windows")
    assert target["message_device_id"] == keys

    # It renews after the list was read, which moves its key store to the
    # chain's new row; ending the row listed still takes it.
    client.cookies.clear()
    client.cookies.set("refresh_token", doomed_refresh, path="/api/v1/auth")
    renewed = await client.post("/api/v1/auth/refresh")
    assert renewed.status_code == 200
    doomed_refresh = renewed.cookies.get("refresh_token")
    client.cookies.clear()

    ended = await client.delete(
        f"/api/v1/auth/sessions/{target['id']}", headers=headers
    )
    assert ended.status_code == 204

    client.cookies.clear()
    client.cookies.set("refresh_token", doomed_refresh, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401

    remaining = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    assert [row["label"] for row in remaining] == ["Chrome on macOS"]
    assert await session.get(DmDevice, uuid.UUID(keys)) is None


async def test_somebody_elses_session_answers_as_missing(
    client: AsyncClient, session: AsyncSession
):
    """The id is the only thing the caller supplied, so a session that is not
    theirs and one that does not exist answer the same."""
    await _signed_in_user(session, "owner@example.com")
    theirs = await _sign_in(client, "owner@example.com", user_agent=CHROME_MAC)
    listed = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {theirs.json()['access_token']}"},
    )
    target = listed.json()[0]["id"]

    stranger = await create_user(session, email="stranger@example.com")
    refused = await client.delete(
        f"/api/v1/auth/sessions/{target}", headers=get_auth_headers(stranger)
    )
    assert refused.status_code == 404
    assert refused.json()["detail"] == "SESSION_NOT_FOUND"

    # And it is still live for the account that owns it.
    still_there = await client.get(
        "/api/v1/auth/sessions",
        headers={"Authorization": f"Bearer {theirs.json()['access_token']}"},
    )
    assert len(still_there.json()) == 1


async def test_signing_out_everywhere_else_spares_the_one_asking(
    client: AsyncClient, session: AsyncSession
):
    await _signed_in_user(session, "sweep@example.com")
    await _sign_in(client, "sweep@example.com", user_agent=FIREFOX_WINDOWS)
    client.cookies.clear()
    asking = await _sign_in(client, "sweep@example.com", user_agent=CHROME_MAC)
    headers = {"Authorization": f"Bearer {asking.json()['access_token']}"}

    assert len((await client.get("/api/v1/auth/sessions", headers=headers)).json()) == 2

    swept = await client.post("/api/v1/auth/sessions/revoke-others", headers=headers)
    assert swept.status_code == 204

    rows = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    assert [row["label"] for row in rows] == ["Chrome on macOS"]
    assert rows[0]["is_current"] is True


async def test_signing_out_everywhere_else_takes_the_phones_too(
    client: AsyncClient, session: AsyncSession
):
    """The app's sign-in is a session like any other, so the sweep ends it. The
    phone keeps its messages for its next sign-in, and the list shows it as a
    device that is not signed in; another browser's go with its session."""
    await _signed_in_user(session, "sweep-phones@example.com")
    phone = await _sign_in(
        client, "sweep-phones@example.com", user_agent=FIREFOX_WINDOWS, device=True
    )
    phone_keys = await _keep_messages(client, phone, seed=1)
    client.cookies.clear()
    browser = await _sign_in(client, "sweep-phones@example.com", user_agent=CHROME_MAC)
    browser_keys = await _keep_messages(client, browser, seed=5)
    client.cookies.clear()
    asking = await _sign_in(client, "sweep-phones@example.com", user_agent=CHROME_MAC)
    headers = {"Authorization": f"Bearer {asking.json()['access_token']}"}
    listed = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    assert [
        row["device"] for row in listed if row["message_device_id"] == phone_keys
    ] == [True]

    swept = await client.post("/api/v1/auth/sessions/revoke-others", headers=headers)
    assert swept.status_code == 204

    rows = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    kept = [row for row in rows if row["id"] is None]
    assert [row["message_device_id"] for row in kept] == [phone_keys]
    assert await session.get(DmDevice, uuid.UUID(browser_keys)) is None

    client.cookies.clear()
    spent = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": phone.json()["refresh_token"]}
    )
    assert spent.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/auth/sessions"),
        ("POST", "/api/v1/auth/sessions/revoke-others"),
    ],
)
async def test_a_standing_credential_does_not_manage_sign_ins(
    client: AsyncClient, session: AsyncSession, method: str, path: str
):
    """The account's sign-ins are the person's to list and end, not a key's."""
    user = await _signed_in_user(session, f"sessions-key-{method}@example.com")
    secret, _row = await api_keys_service.create_api_key(
        session, user=user, name="script"
    )
    await session.commit()

    response = await client.request(
        method, path, headers={"Authorization": f"Bearer {secret}"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"


# ── open connections follow the sign-ins they were opened on ─────────────────


class _Socket:
    """Stands in for a content WebSocket: records the code it was closed with."""

    def __init__(self) -> None:
        self.closed: int | None = None

    async def close(self, code: int | None = None) -> None:
        self.closed = code


class _LiveAccountSession:
    """The session a surviving socket's access re-check opens, answering that
    the account is live. What these tests are about is the credential."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def exec(self, *_a, **_k):
        return None

    async def get(self, _model, _pk):
        return SimpleNamespace(status=UserStatus.active)


@pytest.fixture
async def streams(monkeypatch):
    """A socket register the endpoints under test report to, whose guild and
    resource checks pass, so a socket closes on its credential or not at all."""
    auth_context.reset()
    register = ContentSockets()

    async def _admitted(*_a, **_k):
        return None

    monkeypatch.setattr(
        content_sockets, "request_sessionmaker", lambda _guild_id: _LiveAccountSession
    )
    monkeypatch.setattr(content_sockets, "establish_guild_access", _admitted)
    monkeypatch.setattr(sessions_endpoints, "content_sockets", register)
    monkeypatch.setattr(users_endpoints, "content_sockets", register)
    monkeypatch.setattr(session_opening, "content_sockets", register)
    yield register
    for sub in list(register._subs.values()):
        register.leave(sub.websocket)
    if register._loop_task is not None:
        register._loop_task.cancel()


async def _open_stream(
    register: ContentSockets, token: str, session: AsyncSession
) -> _Socket:
    """Authenticate the way a socket's handshake does, then join a room."""
    user = await authenticate_ws_token(token, session)
    assert user is not None
    room = frozenset({resource_room(1, "file", 1)})

    async def _readable(_session, _user):
        return room

    socket = _Socket()
    register.join(
        Subscriber(
            websocket=socket,  # type: ignore[arg-type]
            user=user,
            guild_id=1,
            wire=Wire.json,
            authorize=_readable,
            credential=Credential.captured(),
            rooms=room,
        )
    )
    return socket


async def test_ending_a_session_closes_the_connections_opened_on_it(
    client: AsyncClient, session: AsyncSession, streams: ContentSockets
):
    await _signed_in_user(session, "end-streams@example.com")
    doomed = await _sign_in(
        client, "end-streams@example.com", user_agent=FIREFOX_WINDOWS
    )
    client.cookies.clear()
    asking = await _sign_in(client, "end-streams@example.com", user_agent=CHROME_MAC)
    asking_token = asking.json()["access_token"]
    headers = {"Authorization": f"Bearer {asking_token}"}

    on_doomed = await _open_stream(streams, doomed.json()["access_token"], session)
    on_asking = await _open_stream(streams, asking_token, session)

    rows = (await client.get("/api/v1/auth/sessions", headers=headers)).json()
    target = next(row for row in rows if row["label"] == "Firefox on Windows")
    ended = await client.delete(
        f"/api/v1/auth/sessions/{target['id']}", headers=headers
    )
    assert ended.status_code == 204

    assert on_doomed.closed == WS_CREDENTIAL_ENDED
    assert on_asking.closed is None


async def test_signing_out_everywhere_else_keeps_this_sessions_connections(
    client: AsyncClient, session: AsyncSession, streams: ContentSockets
):
    await _signed_in_user(session, "sweep-streams@example.com")
    elsewhere = await _sign_in(
        client, "sweep-streams@example.com", user_agent=FIREFOX_WINDOWS
    )
    client.cookies.clear()
    asking = await _sign_in(client, "sweep-streams@example.com", user_agent=CHROME_MAC)
    asking_token = asking.json()["access_token"]
    client.cookies.clear()
    phone = (
        await _sign_in(
            client, "sweep-streams@example.com", user_agent=CHROME_MAC, device=True
        )
    ).json()["access_token"]

    on_elsewhere = await _open_stream(
        streams, elsewhere.json()["access_token"], session
    )
    on_phone = await _open_stream(streams, phone, session)
    on_asking = await _open_stream(streams, asking_token, session)

    swept = await client.post(
        "/api/v1/auth/sessions/revoke-others",
        headers={"Authorization": f"Bearer {asking_token}"},
    )
    assert swept.status_code == 204

    assert on_elsewhere.closed == WS_CREDENTIAL_ENDED
    assert on_phone.closed == WS_CREDENTIAL_ENDED
    assert on_asking.closed is None


async def test_a_password_change_closes_the_connections_opened_before_it(
    client: AsyncClient, session: AsyncSession, streams: ContentSockets
):
    """Every credential the account held goes with the old password, this
    device's included; its replacement session is what it reconnects with."""
    await _signed_in_user(session, "pw-streams@example.com")
    elsewhere = await _sign_in(
        client, "pw-streams@example.com", user_agent=FIREFOX_WINDOWS
    )
    client.cookies.clear()
    asking = await _sign_in(client, "pw-streams@example.com", user_agent=CHROME_MAC)
    asking_token = asking.json()["access_token"]
    client.cookies.clear()
    phone = (
        await _sign_in(
            client, "pw-streams@example.com", user_agent=CHROME_MAC, device=True
        )
    ).json()["access_token"]

    on_elsewhere = await _open_stream(
        streams, elsewhere.json()["access_token"], session
    )
    on_phone = await _open_stream(streams, phone, session)
    on_asking = await _open_stream(streams, asking_token, session)

    changed = await client.patch(
        "/api/v1/me",
        json={"password": "newpassword456", "current_password": PASSWORD},
        headers={"Authorization": f"Bearer {asking_token}"},
    )
    assert changed.status_code == 200, changed.text

    assert on_elsewhere.closed == WS_CREDENTIAL_ENDED
    assert on_phone.closed == WS_CREDENTIAL_ENDED
    assert on_asking.closed == WS_CREDENTIAL_ENDED
