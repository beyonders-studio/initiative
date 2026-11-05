"""Tests for the socket register (``content_sockets``).

Rooms are ``(guild_id, kind, id)``, so per-schema ids never collide across
guilds. A re-check re-runs the guild entry and then the socket's own authorizer,
and what the authorizer returns replaces the socket's rooms; nothing (or an
error) closes it. Frames go through each socket's own outbox.
"""

import asyncio
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi import status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import GuildAccessError
from app.core import auth_context
from app.core.tools import Tool
from app.models.platform.user import Presence, UserStatus
from app.services import content_sockets
from app.services.auth import sessions as session_service
from app.services.content_sockets import (
    WS_CREDENTIAL_ENDED,
    ContentSockets,
    Credential,
    Subscriber,
    Wire,
    guild_room,
    initiative_room,
    resource_room,
)
from app.services.platform.ws_auth import authenticate_ws_token
from app.testing import create_user, get_auth_token


class FakeWebSocket:
    """Records the frames it was sent and the close code it received."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.sent_bytes: list[bytes] = []
        self.closed: Optional[int] = None

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)

    async def send_bytes(self, payload: bytes) -> None:
        self.sent_bytes.append(payload)

    async def close(self, code: Optional[int] = None) -> None:
        self.closed = code


class ExplodingWebSocket(FakeWebSocket):
    async def send_json(self, message: dict) -> None:
        raise RuntimeError("connection reset")


class StalledWebSocket(FakeWebSocket):
    """A reader that never takes a frame."""

    async def send_json(self, message: dict) -> None:
        await asyncio.sleep(3600)


USER = SimpleNamespace(id=1)
DOC = resource_room(1, "file", 3)


@pytest.fixture
async def register():
    # Async so its teardown runs on the loop that owns the sockets' writer
    # tasks. A socket's credential is read off the auth context at join; start
    # each test with none recorded.
    auth_context.reset()
    reg = ContentSockets()
    yield reg
    for sub in list(reg._subs.values()):
        reg.leave(sub.websocket)
    if reg._loop_task is not None:
        reg._loop_task.cancel()


async def settle() -> None:
    """Let the writer tasks drain what was queued."""
    for _ in range(10):
        await asyncio.sleep(0)


def _join(
    reg: ContentSockets,
    ws,
    *,
    rooms,
    guild_id: int = 1,
    user=USER,
    authorize=None,
    wire: Wire = Wire.json,
    presence: bool = False,
    meta=None,
    chosen_presence: Presence = Presence.online,
) -> Subscriber:
    rooms = frozenset(rooms)

    async def keep(_session, _user):
        return rooms

    sub = Subscriber(
        websocket=ws,
        user=user,
        guild_id=guild_id,
        wire=wire,
        authorize=authorize or keep,
        credential=Credential.captured(),
        rooms=rooms,
        presence=presence,
        meta=meta or {},
    )
    reg.join(sub, chosen_presence=chosen_presence)
    return sub


# ── fan-out ─────────────────────────────────────────────────────────────────


async def test_a_signal_is_isolated_by_guild_and_kind(register) -> None:
    same = FakeWebSocket()
    other_guild_same_id = FakeWebSocket()
    same_guild_other_kind = FakeWebSocket()
    _join(register, same, rooms={resource_room(1, "counter_group", 5)})
    _join(
        register,
        other_guild_same_id,
        rooms={resource_room(2, "counter_group", 5)},
        guild_id=2,
    )
    _join(register, same_guild_other_kind, rooms={resource_room(1, "calendar", 5)})

    register.signal(1, Tool.counter_group, 5, "counter_updated")
    await settle()

    assert len(same.sent) == 1
    # counter group 5 in guild 2 is a different group (per-schema ids).
    assert other_guild_same_id.sent == []
    assert same_guild_other_kind.sent == []


async def test_a_signal_names_the_change_and_carries_no_content(register) -> None:
    ws = FakeWebSocket()
    _join(register, ws, rooms={resource_room(1, "counter_group", 5)})

    register.signal(1, Tool.counter_group, 5, "counter_added")
    await settle()

    (frame,) = ws.sent
    assert set(frame) == {"type", "id", "timestamp"}
    assert frame["type"] == "counter_added"
    assert frame["id"] == 5


async def test_an_unrouted_signal_sends_nothing(register) -> None:
    ws = FakeWebSocket()
    _join(register, ws, rooms={resource_room(1, "counter_group", 5)})

    register.signal(None, Tool.counter_group, 5, "counter_added")
    await settle()

    assert ws.sent == []


async def test_json_never_reaches_a_byte_stream_and_bytes_never_a_json_one(
    register,
) -> None:
    """A file's room holds collaboration sockets; a sharing signal to the
    same room is for JSON readers only."""
    editor = FakeWebSocket()
    watcher = FakeWebSocket()
    _join(register, editor, rooms={DOC}, wire=Wire.bytes)
    _join(register, watcher, rooms={DOC}, wire=Wire.json)

    register.emit_json(DOC, {"type": "permissions_changed"})
    register.emit_bytes(DOC, b"\x02update")
    await settle()

    assert editor.sent == [] and editor.sent_bytes == [b"\x02update"]
    assert watcher.sent_bytes == [] and len(watcher.sent) == 1


async def test_emit_bytes_reaches_a_second_connection_of_the_same_account(
    register,
) -> None:
    """Exclusion is by socket: the only frame withheld is the sender's own."""
    first, second = FakeWebSocket(), FakeWebSocket()
    _join(register, first, rooms={DOC}, wire=Wire.bytes)
    _join(register, second, rooms={DOC}, wire=Wire.bytes)

    register.emit_bytes(DOC, b"\x02update", exclude=first)
    await settle()

    assert second.sent_bytes == [b"\x02update"]
    assert first.sent_bytes == []


async def test_frames_to_one_socket_arrive_in_order(register) -> None:
    ws = FakeWebSocket()
    sub = _join(register, ws, rooms={DOC}, wire=Wire.bytes)

    sub.send_bytes(b"\x00first")
    register.emit_bytes(DOC, b"\x02second")
    sub.send_bytes(b"\x01third")
    await settle()

    assert ws.sent_bytes == [b"\x00first", b"\x02second", b"\x01third"]


async def test_a_failed_send_drops_the_socket(register) -> None:
    bad = ExplodingWebSocket()
    _join(register, bad, rooms={initiative_room(9, 1)}, guild_id=9)

    register.emit_json(initiative_room(9, 1), {"x": 1})
    await settle()

    assert register.room_size(initiative_room(9, 1)) == 0


async def test_a_reader_that_falls_behind_is_closed(register, monkeypatch) -> None:
    """One slow reader never holds up a room: past its outbox it is closed, and
    the others keep receiving."""
    monkeypatch.setattr(content_sockets, "OUTBOX_LIMIT", 2)
    slow, quick = StalledWebSocket(), FakeWebSocket()
    _join(register, slow, rooms={DOC})
    _join(register, quick, rooms={DOC})

    for n in range(5):
        register.emit_json(DOC, {"n": n})
        # Each writer gets its turn, as it would between real frames: the
        # quick reader keeps up and the stalled one falls behind.
        await settle()

    assert slow.closed == status.WS_1013_TRY_AGAIN_LATER
    assert register.room_size(DOC) == 1
    assert [frame["n"] for frame in quick.sent] == [0, 1, 2, 3, 4]


async def test_leave_empties_every_room_and_is_idempotent(register) -> None:
    ws = FakeWebSocket()
    _join(
        register,
        ws,
        rooms={guild_room(1), initiative_room(1, 2), initiative_room(1, 3)},
    )

    register.leave(ws)
    register.leave(ws)

    for key in (guild_room(1), initiative_room(1, 2), initiative_room(1, 3)):
        assert register.room_size(key) == 0


async def test_room_members_carries_the_channels_own_state(register) -> None:
    ws = FakeWebSocket()
    _join(register, ws, rooms={DOC}, meta={"name": "Ada", "can_write": True})

    (member,) = register.room_members(DOC)

    assert member.user is USER
    assert member.meta == {"name": "Ada", "can_write": True}


# ── presence ────────────────────────────────────────────────────────────────


async def test_presence_counts_people_not_sockets_and_only_presence_sockets(
    register,
) -> None:
    tab_one, tab_two, counters_page = FakeWebSocket(), FakeWebSocket(), FakeWebSocket()
    _join(register, tab_one, rooms={guild_room(1)}, presence=True)
    _join(register, tab_two, rooms={guild_room(1)}, presence=True)
    _join(
        register,
        counters_page,
        rooms={resource_room(1, "counter_group", 4)},
        user=SimpleNamespace(id=2),
    )

    assert register.present_count(1) == 1
    assert register.users_in_guild(1) == {1}
    assert register.guild_ids() == [1]

    register.leave(tab_one)
    assert register.present_count(1) == 1
    register.leave(tab_two)
    assert register.present_count(1) == 0
    assert register.guild_ids() == []


async def test_the_guild_count_is_open_tabs_not_dots(register) -> None:
    """Someone appearing offline still has the guild open."""
    _join(
        register,
        FakeWebSocket(),
        rooms={guild_room(1)},
        presence=True,
        chosen_presence=Presence.offline,
    )
    _join(
        register,
        FakeWebSocket(),
        rooms={guild_room(1)},
        presence=True,
        user=SimpleNamespace(id=8),
    )

    assert register.present_counts([1, 2]) == {1: 2, 2: 0}


# ── re-checks ───────────────────────────────────────────────────────────────


class _FakeSession:
    """The session a re-check opens, with no database behind it. ``get``
    answers with the account as it stands now."""

    def __init__(self, account_status: UserStatus = UserStatus.active) -> None:
        self._account_status = account_status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False

    async def get(self, _model, pk):
        return SimpleNamespace(id=pk, status=self._account_status)

    async def rollback(self):
        return None


def _patch_entry(
    monkeypatch,
    *,
    establish_ok: bool = True,
    account_status: UserStatus = UserStatus.active,
    gate=None,
):
    """Drive the guild entry without a database. Returns what it was shown."""
    seen: list = []

    async def fake_establish(_session, user, guild_id, satisfied_providers=None):
        seen.append((guild_id, user.id, satisfied_providers))
        if gate is not None:
            gate()
        if not establish_ok:
            raise GuildAccessError()

    monkeypatch.setattr(
        content_sockets,
        "request_sessionmaker",
        lambda _guild_id: lambda: _FakeSession(account_status),
    )
    monkeypatch.setattr(content_sockets, "establish_guild_access", fake_establish)
    return seen


def _answers(*rooms):
    async def authorize(_session, _user):
        return frozenset(rooms) if rooms else None

    return authorize


async def test_a_socket_still_authorized_keeps_its_room(register, monkeypatch) -> None:
    _patch_entry(monkeypatch)
    ws = FakeWebSocket()
    _join(register, ws, rooms={DOC}, authorize=_answers(DOC))

    await register.revoke_user(1, USER.id)

    assert ws.closed is None
    assert register.room_size(DOC) == 1


async def test_losing_the_resource_closes_the_socket(register, monkeypatch) -> None:
    _patch_entry(monkeypatch)
    ws = FakeWebSocket()
    _join(register, ws, rooms={DOC}, authorize=_answers())

    await register.revoke_user(1, USER.id)

    assert ws.closed == status.WS_1008_POLICY_VIOLATION
    assert register.room_size(DOC) == 0


async def test_losing_the_guild_closes_the_socket(register, monkeypatch) -> None:
    _patch_entry(monkeypatch, establish_ok=False)
    ws = FakeWebSocket()
    _join(register, ws, rooms={DOC}, authorize=_answers(DOC))

    await register.revoke_user(1, USER.id)

    assert ws.closed == status.WS_1008_POLICY_VIOLATION


async def test_an_authorizer_that_raises_closes_the_socket(
    register, monkeypatch
) -> None:
    _patch_entry(monkeypatch)

    async def broken(_session, _user):
        raise RuntimeError("boom")

    ws = FakeWebSocket()
    _join(register, ws, rooms={DOC}, authorize=broken)

    await register.revoke_user(1, USER.id)

    assert ws.closed == status.WS_1008_POLICY_VIOLATION


async def test_a_recheck_replaces_the_rooms(register, monkeypatch) -> None:
    """Rooms are left as surely as they are entered: removed from initiative 2
    and added to initiative 3, the socket moves on the next re-check."""
    _patch_entry(monkeypatch)
    now = {guild_room(1), initiative_room(1, 2)}

    async def authorize(_session, _user):
        return frozenset(now)

    ws = FakeWebSocket()
    _join(register, ws, rooms=now, authorize=authorize)
    now = {guild_room(1), initiative_room(1, 3)}

    await register.refresh_users(1, [USER.id])

    assert register.room_size(initiative_room(1, 2)) == 0
    assert register.room_size(initiative_room(1, 3)) == 1
    assert ws.closed is None


async def test_one_guild_entry_serves_every_socket_of_one_sign_in(
    register, monkeypatch
) -> None:
    """A board, a counter group and a file open in one guild cost one entry."""
    seen = _patch_entry(monkeypatch)
    for key in (guild_room(1), resource_room(1, "counter_group", 4), DOC):
        _join(register, FakeWebSocket(), rooms={key}, authorize=_answers(key))

    await register.revoke_user(1, USER.id)

    assert len(seen) == 1


async def test_recheck_room_reaches_only_that_room(register, monkeypatch) -> None:
    _patch_entry(monkeypatch)
    in_room, elsewhere = FakeWebSocket(), FakeWebSocket()
    _join(register, in_room, rooms={DOC}, authorize=_answers())
    _join(
        register,
        elsewhere,
        rooms={resource_room(1, "file", 4)},
        authorize=_answers(),
    )

    await register.recheck_room(DOC)

    assert in_room.closed == status.WS_1008_POLICY_VIOLATION
    assert elsewhere.closed is None


async def test_revoke_is_scoped_to_guild_and_user(register, monkeypatch) -> None:
    _patch_entry(monkeypatch, establish_ok=False)
    target, other_user, other_guild = FakeWebSocket(), FakeWebSocket(), FakeWebSocket()
    _join(register, target, rooms={DOC}, authorize=_answers(DOC))
    _join(
        register,
        other_user,
        rooms={DOC},
        user=SimpleNamespace(id=2),
        authorize=_answers(DOC),
    )
    _join(
        register,
        other_guild,
        rooms={resource_room(2, "file", 3)},
        guild_id=2,
        authorize=_answers(resource_room(2, "file", 3)),
    )

    await register.revoke_user(1, 1)

    assert target.closed == status.WS_1008_POLICY_VIOLATION
    assert other_user.closed is None
    assert other_guild.closed is None


async def test_recheck_replays_join_time_satisfied_providers(
    register, monkeypatch
) -> None:
    seen = _patch_entry(monkeypatch)
    auth_context.record(satisfied_providers=frozenset({42}))
    ws = FakeWebSocket()
    _join(register, ws, rooms={DOC}, authorize=_answers(DOC))
    auth_context.record(satisfied_providers=frozenset())

    await register.revoke_user(1, USER.id)

    assert seen == [(1, USER.id, frozenset({42}))]
    assert ws.closed is None


async def test_recheck_answers_for_the_session_that_opened_the_socket(
    register, monkeypatch
) -> None:
    """A community that asks for a passkey is answered against each socket's
    own session, and the checking context is left as it was."""

    def wants_a_passkey():
        if not auth_context.current().session_amr & {"hwk", "swk"}:
            raise GuildAccessError()

    _patch_entry(monkeypatch, gate=wants_a_passkey)

    with_a_key = FakeWebSocket()
    auth_context.record(session_amr=frozenset({"mfa", "hwk"}))
    _join(register, with_a_key, rooms={DOC}, authorize=_answers(DOC))
    with_a_password = FakeWebSocket()
    auth_context.record(session_amr=frozenset())
    other = resource_room(1, "file", 4)
    _join(register, with_a_password, rooms={other}, authorize=_answers(other))

    auth_context.record(session_amr=frozenset({"mfa", "hwk"}))
    await register.revoke_user(1, USER.id)

    assert with_a_key.closed is None
    assert with_a_password.closed == status.WS_1008_POLICY_VIOLATION
    assert auth_context.current().session_amr == frozenset({"mfa", "hwk"})


async def test_recheck_answers_a_narrowed_provider_from_the_socket(
    register, monkeypatch
) -> None:
    def wants_the_claim():
        asserted = auth_context.current().satisfied_claims.get("7", {})
        if "acme.com" not in asserted.get("hd", []):
            raise GuildAccessError()

    _patch_entry(monkeypatch, gate=wants_the_claim)

    from_acme = FakeWebSocket()
    auth_context.record(satisfied_claims={"7": {"hd": ["acme.com"]}})
    _join(register, from_acme, rooms={DOC}, authorize=_answers(DOC))
    from_elsewhere = FakeWebSocket()
    auth_context.record(satisfied_claims={"7": {"hd": ["other.example"]}})
    other = resource_room(1, "file", 4)
    _join(register, from_elsewhere, rooms={other}, authorize=_answers(other))

    auth_context.record(satisfied_claims={"7": {"hd": ["third.example"]}})
    await register.revoke_user(1, USER.id)

    assert from_acme.closed is None
    assert from_elsewhere.closed == status.WS_1008_POLICY_VIOLATION
    assert auth_context.current().satisfied_claims == {"7": {"hd": ["third.example"]}}


async def test_recheck_does_not_carry_the_askers_api_key(register, monkeypatch) -> None:
    """A re-check asked for by a request made with an API key limited to
    another guild is answered for the socket's own sign-in, not the key."""

    def refuses_a_key_pinned_elsewhere():
        recorded = auth_context.current()
        if recorded.api_key_credential or recorded.api_key_guild_id:
            raise GuildAccessError()

    _patch_entry(monkeypatch, gate=refuses_a_key_pinned_elsewhere)
    ws = FakeWebSocket()
    _join(register, ws, rooms={DOC}, authorize=_answers(DOC))

    auth_context.record(api_key_credential=True, api_key_guild_id=99)
    try:
        await register.revoke_user(1, USER.id)
    finally:
        auth_context.reset()

    assert ws.closed is None


@pytest.mark.parametrize(
    "account_status",
    [UserStatus.suspended, UserStatus.deactivated, UserStatus.anonymized],
)
async def test_an_account_no_longer_live_is_closed(
    register, monkeypatch, account_status
) -> None:
    """Suspension leaves every membership in place, so the account itself is
    read again rather than trusted from the join."""
    _patch_entry(monkeypatch, account_status=account_status)
    ws = FakeWebSocket()
    _join(register, ws, rooms={DOC}, authorize=_answers(DOC))

    await register.revoke_user_everywhere(USER.id)

    assert ws.closed == status.WS_1008_POLICY_VIOLATION
    assert register.room_size(DOC) == 0


# ── the credential the socket was opened with ───────────────────────────────


async def _open(
    reg: ContentSockets, token: str, session: AsyncSession
) -> FakeWebSocket:
    """Authenticate ``token`` the way the handshake does, then join, so the
    socket carries exactly the credential a real connection would."""
    user = await authenticate_ws_token(token, session)
    assert user is not None
    ws = FakeWebSocket()
    _join(reg, ws, rooms={DOC}, user=user, authorize=_answers(DOC))
    return ws


async def test_a_socket_on_an_ended_session_is_closed(
    register, monkeypatch, session: AsyncSession
) -> None:
    _patch_entry(monkeypatch)
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    ws = await _open(
        register, get_auth_token(user, session_id=issued.session.id), session
    )

    await register.revoke_user_everywhere(user.id)
    assert ws.closed is None

    await session_service.revoke_chain(session, session_id=issued.session.id)
    await session.commit()
    await register.revoke_user_everywhere(user.id)

    assert ws.closed == WS_CREDENTIAL_ENDED
    assert register.room_size(DOC) == 0


async def test_a_socket_follows_its_session_through_a_renewal(
    register, monkeypatch, session: AsyncSession
) -> None:
    _patch_entry(monkeypatch)
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    ws = await _open(
        register, get_auth_token(user, session_id=issued.session.id), session
    )

    renewed = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token
    )
    assert renewed.ok and renewed.issued is not None
    await session.commit()
    await register.revoke_user_everywhere(user.id)
    assert ws.closed is None

    await session_service.revoke_chain(session, session_id=renewed.issued.session.id)
    await session.commit()
    await register.revoke_user_everywhere(user.id)
    assert ws.closed == WS_CREDENTIAL_ENDED


async def test_a_token_version_bump_closes_the_socket(
    register, monkeypatch, session: AsyncSession
) -> None:
    _patch_entry(monkeypatch)
    user = await create_user(session)
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    ws = await _open(
        register, get_auth_token(user, session_id=issued.session.id), session
    )

    user.token_version += 1
    session.add(user)
    await session.commit()
    await register.revoke_user_everywhere(user.id)

    assert ws.closed == WS_CREDENTIAL_ENDED
