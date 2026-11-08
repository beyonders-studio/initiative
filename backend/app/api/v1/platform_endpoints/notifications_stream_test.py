"""The notification bell's push socket — the handshake and its bookkeeping.

The invariant under test: the registry holds exactly the sockets that
authenticated, for exactly as long as they are connected. A socket joins it
only after a credential resolves to an active user, and leaves it when the
connection ends, however it ends.

The socket is driven directly rather than over the wire — the HTTP test client
here is ``httpx2``, which speaks no WebSocket — with a stand-in that records what
the endpoint did to it.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi import WebSocketDisconnect

from app.api import content_socket
from app.api.content_socket import MSG_AUTH
from app.api.v1.platform_endpoints import notifications as notifications_endpoint
from app.api.v1.platform_endpoints.notifications import (
    MSG_ACTIVE,
    websocket_notifications,
)
from app.core.security import SESSION_COOKIE_NAME
from app.services.content_sockets import ContentSockets, account_room
from app.services.platform import presence
from app.testing import create_user, get_auth_token

WS_POLICY_VIOLATION = 1008


class FakeWebSocket:
    """Drives the endpoint through one handshake, then hangs up.

    ``frames`` are the client's inbound frames: the handshake reads the first,
    the keepalive loop the rest. Once they run out the socket reports a
    disconnect, which is how a real client leaving arrives.
    """

    def __init__(self, frames: list[bytes], cookies: dict | None = None) -> None:
        self._frames = list(frames)
        self.cookies = cookies or {}
        self.headers: dict[str, str] = {}
        self.accepted = False
        self.closed_with: int | None = None
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def receive_bytes(self) -> bytes:
        if not self._frames:
            raise WebSocketDisconnect(code=1000)
        return self._frames.pop(0)

    async def receive(self) -> dict:
        """The raw ASGI message, as Starlette hands it over: a disconnect
        arrives here as a message rather than an exception."""
        if not self._frames:
            return {"type": "websocket.disconnect", "code": 1000}
        return {"type": "websocket.receive", "bytes": self._frames.pop(0)}

    @property
    def pending(self) -> bool:
        return bool(self._frames)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def _auth_frame(payload: bytes) -> bytes:
    return bytes([MSG_AUTH]) + payload


@pytest.fixture
async def register(monkeypatch) -> AsyncIterator[ContentSockets]:
    """A register of this test's own, so assertions see only its sockets."""
    fresh = ContentSockets()
    monkeypatch.setattr(notifications_endpoint, "sockets", fresh)
    yield fresh
    for websocket in list(fresh._subs):
        fresh.leave(websocket)


def _held(register: ContentSockets, user_id: int) -> int:
    return register.room_size(account_room(user_id))


async def test_a_valid_token_joins_and_then_leaves_the_registry(
    session, register
) -> None:
    user = await create_user(session)
    await session.commit()
    token = get_auth_token(user)
    websocket = FakeWebSocket([_auth_frame(f'{{"token": "{token}"}}'.encode())])

    await websocket_notifications(websocket)

    assert websocket.accepted
    assert websocket.closed_with is None
    # The keepalive loop ended with the client's disconnect, and the socket
    # left with it.
    assert _held(register, user.id) == 0


async def test_the_socket_is_registered_while_the_loop_runs(
    session, register, monkeypatch
) -> None:
    """The registry entry has to exist *during* the socket's life, which the
    disconnect above tears down before we can look at it."""
    user = await create_user(session)
    await session.commit()
    token = get_auth_token(user)
    websocket = FakeWebSocket([_auth_frame(f'{{"token": "{token}"}}'.encode())])

    counted: list[int] = []

    handshake = websocket.receive

    async def receive() -> dict:
        if websocket.pending:
            return await handshake()
        counted.append(_held(register, user.id))
        return {"type": "websocket.disconnect", "code": 1000}

    monkeypatch.setattr(websocket, "receive", receive)
    await websocket_notifications(websocket)

    assert counted == [1]


async def test_a_session_cookie_stands_in_for_a_null_token(
    session, register, monkeypatch
) -> None:
    """Web sessions hold the JWT in an HttpOnly cookie the page cannot read, so
    they send ``{"token": null}`` and the socket reads the cookie itself."""
    user = await create_user(session)
    await session.commit()
    websocket = FakeWebSocket(
        [_auth_frame(b'{"token": null}')],
        cookies={SESSION_COOKIE_NAME: get_auth_token(user)},
    )

    counted: list[int] = []

    handshake = websocket.receive

    async def receive() -> dict:
        if websocket.pending:
            return await handshake()
        counted.append(_held(register, user.id))
        return {"type": "websocket.disconnect", "code": 1000}

    monkeypatch.setattr(websocket, "receive", receive)
    await websocket_notifications(websocket)

    assert websocket.closed_with is None
    assert counted == [1]


async def test_an_active_frame_marks_its_person_present(
    session, register, monkeypatch
) -> None:
    """The one frame the client sends back says its person is at the keyboard,
    and names nobody — the socket already knows whose it is."""
    user = await create_user(session)
    await session.commit()
    token = get_auth_token(user)
    websocket = FakeWebSocket(
        [_auth_frame(f'{{"token": "{token}"}}'.encode()), bytes([MSG_ACTIVE])]
    )

    seen: list[int] = []
    monkeypatch.setattr(presence.online, "active", seen.append)

    await websocket_notifications(websocket)

    assert seen == [user.id]
    assert websocket.closed_with is None


async def test_an_invalid_token_is_refused(session, register) -> None:
    websocket = FakeWebSocket([_auth_frame(b'{"token": "not-a-token"}')])

    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION


async def test_a_revoked_token_is_refused(session, register) -> None:
    """Logout / password change revoke by bumping ``token_version``; the socket
    must honour that the same way the REST path does."""
    user = await create_user(session)
    await session.commit()
    token = get_auth_token(user)
    user.token_version += 1
    session.add(user)
    await session.commit()

    websocket = FakeWebSocket([_auth_frame(f'{{"token": "{token}"}}'.encode())])
    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION
    assert _held(register, user.id) == 0


async def test_a_first_frame_that_is_not_msg_auth_is_refused(register) -> None:
    websocket = FakeWebSocket([bytes([0]) + b"{}"])

    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION


async def test_a_malformed_auth_payload_is_refused(register) -> None:
    websocket = FakeWebSocket([_auth_frame(b"not json")])

    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION


async def test_no_token_and_no_cookie_is_refused(register) -> None:
    websocket = FakeWebSocket([_auth_frame(b'{"token": null}')])

    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION


async def test_a_socket_that_never_sends_its_first_frame_is_closed(
    register, monkeypatch
) -> None:
    """An accepted socket is not held open waiting for a frame that may never
    come."""
    monkeypatch.setattr(content_socket, "AUTH_TIMEOUT_SECONDS", 0.01)
    websocket = FakeWebSocket([])

    async def receive() -> dict:
        await asyncio.sleep(60)
        raise AssertionError("should have timed out")

    monkeypatch.setattr(websocket, "receive", receive)
    await websocket_notifications(websocket)

    assert websocket.closed_with == WS_POLICY_VIOLATION
    assert websocket.sent == []


async def test_hanging_up_before_authenticating_registers_nothing(register) -> None:
    websocket = FakeWebSocket([])

    await websocket_notifications(websocket)

    assert websocket.accepted
    assert websocket.closed_with is None


async def test_the_socket_closes_when_its_sign_in_ends(
    session, register, monkeypatch
) -> None:
    """The bell is its account's socket in the register: a re-check while the
    sign-in stands leaves it open, and one after the sign-in ends closes it."""
    from sqlalchemy import update

    from app.models.platform.user import User
    from app.services.auth import sessions as session_service
    from app.services.content_sockets import WS_CREDENTIAL_ENDED

    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    token = get_auth_token(user, session_id=issued.session.id)
    websocket = FakeWebSocket([_auth_frame(f'{{"token": "{token}"}}'.encode())])
    seen: list[int | None] = []
    handshake = websocket.receive

    async def receive() -> dict:
        if websocket.pending:
            return await handshake()
        await register.revoke_user_everywhere(user.id)
        seen.append(websocket.closed_with)
        await session.exec(
            update(User)
            .where(User.id == user.id)
            .values(token_version=User.token_version + 1)
        )
        await session.commit()
        await register.revoke_user_everywhere(user.id)
        seen.append(websocket.closed_with)
        return {"type": "websocket.disconnect", "code": 1000}

    monkeypatch.setattr(websocket, "receive", receive)
    await websocket_notifications(websocket)

    assert seen == [None, WS_CREDENTIAL_ENDED]
    assert _held(register, user.id) == 0
