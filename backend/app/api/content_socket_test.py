"""How a guild socket is entered: the first frame, and what refuses it.

Every guild socket enters through ``admit``, so these hold the rules once: the
credential rides in a first frame that must arrive in time, a revoked sign-in
is refused, and a tool row is watched only while its tool is switched on and
its sharing admits the reader.
"""

import asyncio
import json
from typing import Optional

import pytest
from fastapi import status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import content_socket
from app.api.content_socket import MSG_AUTH, read_auth_frame, serve_tool_stream
from app.core.security import SESSION_COOKIE_NAME
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.services.content_sockets import resource_room, sockets
from app.testing import create_counter_group, get_auth_token
from app.testing.sockets import settle


class InboundWebSocket:
    """A client that sends ``frames`` and then waits for the server."""

    def __init__(
        self,
        frames: list[dict],
        cookies: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> None:
        self._frames = list(frames)
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.accepted = False
        self.closed: Optional[int] = None
        self.sent: list[dict] = []
        self.seated = asyncio.Event()

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict:
        if self._frames:
            return self._frames.pop(0)
        # Past the handshake: the socket is registered by now. Hang up once
        # the test has looked.
        self.seated.set()
        await asyncio.sleep(0.05)
        return {"type": "websocket.disconnect", "code": 1000}

    async def close(self, code: int = 1000) -> None:
        self.closed = code

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


def _binary(payload: dict) -> dict:
    return {
        "type": "websocket.receive",
        "bytes": bytes([MSG_AUTH]) + json.dumps(payload).encode(),
    }


def _text(payload: dict) -> dict:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


# ── the first frame ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("frame", [_binary, _text], ids=["binary", "text"])
async def test_the_first_frame_carries_the_token(frame) -> None:
    websocket = InboundWebSocket([frame({"token": "abc", "away_seconds": 4})])

    first = await read_auth_frame(websocket)  # type: ignore[arg-type]

    assert first is not None
    token, payload = first

    assert token == "abc"
    assert payload["away_seconds"] == 4
    assert websocket.closed is None


async def test_a_session_cookie_stands_in_for_a_null_token() -> None:
    cookies = {SESSION_COOKIE_NAME: "from-cookie"}
    websocket = InboundWebSocket([_binary({"token": None})], cookies=cookies)
    # A handshake that presents a bearer header is not the cookie's to answer.
    beside_bearer = InboundWebSocket(
        [_binary({"token": None})],
        cookies=cookies,
        headers={"authorization": "Bearer a-token"},
    )

    first = await read_auth_frame(websocket)  # type: ignore[arg-type]

    assert first is not None and first[0] == "from-cookie"
    assert await read_auth_frame(beside_bearer) is None  # type: ignore[arg-type]
    assert beside_bearer.closed == status.WS_1008_POLICY_VIOLATION


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "websocket.receive", "bytes": bytes([0]) + b'{"token": "abc"}'},
        {"type": "websocket.receive", "bytes": bytes([MSG_AUTH]) + b"not json"},
        {"type": "websocket.receive", "text": "[1, 2]"},
        _binary({"token": None}),
        _binary({"token": 7}),
    ],
    ids=["not-auth", "malformed", "not-an-object", "no-token", "not-a-string"],
)
async def test_a_first_frame_that_is_no_credential_is_refused(frame) -> None:
    websocket = InboundWebSocket([frame])

    assert await read_auth_frame(websocket) is None  # type: ignore[arg-type]
    assert websocket.closed == status.WS_1008_POLICY_VIOLATION


async def test_a_socket_that_never_sends_its_first_frame_is_closed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(content_socket, "AUTH_TIMEOUT_SECONDS", 0.01)
    websocket = InboundWebSocket([])

    async def silent() -> dict:
        await asyncio.sleep(60)
        raise AssertionError("should have timed out")

    monkeypatch.setattr(websocket, "receive", silent)

    assert await read_auth_frame(websocket) is None  # type: ignore[arg-type]
    assert websocket.closed == status.WS_1008_POLICY_VIOLATION


async def test_hanging_up_before_the_first_frame_closes_nothing() -> None:
    websocket = InboundWebSocket([{"type": "websocket.disconnect", "code": 1000}])

    assert await read_auth_frame(websocket) is None  # type: ignore[arg-type]
    assert websocket.closed is None


# ── a tool row's stream ─────────────────────────────────────────────────────


async def _watch(guild_id: int, group_id: int, token: str) -> InboundWebSocket:
    """Open a counter group's stream and hold it until the handshake is done."""
    websocket = InboundWebSocket([_binary({"token": token})])
    serving = asyncio.create_task(
        serve_tool_stream(websocket, guild_id, Tool.counter_group, group_id)  # type: ignore[arg-type]
    )
    done, _ = await asyncio.wait(
        {serving, asyncio.create_task(websocket.seated.wait())},
        return_when=asyncio.FIRST_COMPLETED,
    )
    websocket.serving = serving  # type: ignore[attr-defined]
    return websocket


async def test_a_reader_of_the_counter_group_is_seated_and_told_of_changes(
    session: AsyncSession, acting_user
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)

    websocket = await _watch(a.guild.id, group.id, get_auth_token(a.user))
    assert websocket.closed is None
    room = resource_room(a.guild.id, "counter_group", group.id)
    assert sockets.room_size(room) == 1

    sockets.signal(a.guild.id, Tool.counter_group, group.id, "counter_updated")
    await settle()
    await websocket.serving  # type: ignore[attr-defined]

    assert [frame["type"] for frame in websocket.sent] == ["counter_updated"]
    assert sockets.room_size(room) == 0


async def test_a_revoked_sign_in_is_refused(session: AsyncSession, acting_user) -> None:
    """A sign-in ended by bumping ``token_version`` opens no socket."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    token = get_auth_token(a.user)
    a.user.token_version += 1
    session.add(a.user)
    await session.commit()

    websocket = await _watch(a.guild.id, group.id, token)
    await websocket.serving  # type: ignore[attr-defined]

    assert websocket.closed == status.WS_1008_POLICY_VIOLATION


async def test_a_counter_group_whose_tool_is_switched_off_is_not_streamed(
    session: AsyncSession, acting_user
) -> None:
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    a.initiative.counter_groups_enabled = False
    session.add(a.initiative)
    await session.commit()

    websocket = await _watch(a.guild.id, group.id, get_auth_token(a.user))
    await websocket.serving  # type: ignore[attr-defined]

    assert websocket.closed == status.WS_1008_POLICY_VIOLATION


async def test_a_member_the_counter_group_is_not_shared_with_is_refused(
    session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    group = await create_counter_group(session, owner.initiative, owner.user)
    outsider = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await session.commit()

    websocket = await _watch(owner.guild.id, group.id, get_auth_token(outsider.user))
    await websocket.serving  # type: ignore[attr-defined]

    assert websocket.closed == status.WS_1008_POLICY_VIOLATION


# ── a held socket ───────────────────────────────────────────────────────────


async def test_a_held_socket_hands_on_binary_frames_and_beats_when_quiet(
    monkeypatch,
) -> None:
    """Every socket beats the same way, the collaboration socket included, so
    one client-side check notices a connection that has stopped carrying."""
    from types import SimpleNamespace

    from app.services.content_sockets import (
        ContentSockets,
        Credential,
        Subscriber,
        Wire,
    )
    from app.testing.sockets import FakeWebSocket

    register = ContentSockets()
    monkeypatch.setattr(content_socket, "sockets", register)
    monkeypatch.setattr(content_socket, "HEARTBEAT_SECONDS", 0.01)

    inbound = [
        {"type": "websocket.receive", "bytes": b"\x02edit"},
        None,  # the client says nothing for a while
        {"type": "websocket.receive", "text": "ignored"},
        {"type": "websocket.disconnect", "code": 1000},
    ]

    class Client(FakeWebSocket):
        async def receive(self) -> dict:
            # Let the writer deliver what is queued, as a real socket would.
            await settle()
            frame = inbound.pop(0)
            if frame is None:
                await asyncio.sleep(1)
                return {}
            return frame

    websocket = Client()

    async def keep(_session, _user):
        return frozenset({resource_room(1, "file", 3)})

    sub = Subscriber(
        websocket=websocket,  # type: ignore[arg-type]
        user=SimpleNamespace(id=1),  # type: ignore[arg-type]
        guild_id=1,
        wire=Wire.bytes,
        authorize=keep,
        credential=Credential(),
        rooms=frozenset({resource_room(1, "file", 3)}),
    )
    register.join(sub)
    received: list[bytes] = []
    try:
        await content_socket.hold_open(sub, on_bytes=received.append)
        await settle()
    finally:
        if register._loop_task is not None:
            register._loop_task.cancel()

    assert received == [b"\x02edit"]
    assert content_socket.HEARTBEAT_FRAME in websocket.sent
    assert register.room_size(resource_room(1, "file", 3)) == 0


async def test_a_socket_that_keeps_talking_is_still_beaten_to(monkeypatch) -> None:
    """Someone typing alone in a file sends constantly and is sent nothing
    back — edits are relayed to everyone else. The beat is measured from what
    the server last said, so their client still hears one and keeps the socket."""
    from types import SimpleNamespace

    from app.services.content_sockets import (
        ContentSockets,
        Credential,
        Subscriber,
        Wire,
    )
    from app.testing.sockets import FakeWebSocket

    register = ContentSockets()
    monkeypatch.setattr(content_socket, "sockets", register)
    monkeypatch.setattr(content_socket, "HEARTBEAT_SECONDS", 0.05)

    # An edit every 10ms for 300ms: never quiet for a whole beat.
    edits = 30

    class Typist(FakeWebSocket):
        async def receive(self) -> dict:
            nonlocal edits
            await settle()
            if edits == 0:
                return {"type": "websocket.disconnect", "code": 1000}
            edits -= 1
            await asyncio.sleep(0.01)
            return {"type": "websocket.receive", "bytes": b"\x02edit"}

    websocket = Typist()

    async def keep(_session, _user):
        return frozenset({resource_room(1, "file", 3)})

    sub = Subscriber(
        websocket=websocket,  # type: ignore[arg-type]
        user=SimpleNamespace(id=1),  # type: ignore[arg-type]
        guild_id=1,
        wire=Wire.bytes,
        authorize=keep,
        credential=Credential(),
        rooms=frozenset({resource_room(1, "file", 3)}),
    )
    register.join(sub)
    try:
        await content_socket.hold_open(sub, on_bytes=lambda _data: None)
        await settle()
    finally:
        if register._loop_task is not None:
            register._loop_task.cancel()

    assert websocket.sent.count(content_socket.HEARTBEAT_FRAME) >= 2
