"""Every socket a page holds open, in one register.

A guild page opens up to three kinds of socket: the events bus
(``/c/{guild}/events/updates``), a change signal for one counter group
(``/c/{guild}/{tool}/{id}/ws``) and a collaboration room for one file body.
Every page also holds the account's own socket (``/notifications/stream``),
which belongs to no guild: it is registered with ``guild_id=None`` in its
account's room, and ``app.services.platform.user_stream`` sends to that room.
They differ in what they carry.
What they share is everything else, and that lives here once:

* **Rooms.** A socket sits in a set of rooms, each ``(guild_id, kind, id)``. The
  guild id is part of every key: content ids are per-schema sequences and
  collide across guilds, so a bare id would reach the wrong community. The
  events bus sits in its guild's room and in one room per initiative it may
  read; a tool socket sits in its tool's room; a collaboration socket in its
  body's.
* **Admission is the re-check.** Each socket is registered with the function
  that decided which rooms it may be in. The same function runs again on every
  re-check, and what it returns *replaces* the socket's rooms — so a room is
  left as surely as it is entered, and there is no second rule for staying.
  ``None`` (or nothing) disconnects.
* **Continuous re-authorization.** Removing someone from a guild or an
  initiative re-checks their sockets at once (``revoke_user``); a change to
  one resource's sharing re-checks that room (``recheck_room``); everything
  else is caught by the loop every ``REAUTH_INTERVAL_SECONDS``. The credential
  the socket was opened with is re-checked too: ending a sign-in
  (``revoke_user_everywhere``) closes the sockets that sign-in opened, with
  ``WS_CREDENTIAL_ENDED``, and leaves the account's others open.
* **One writer per socket.** Every frame to a registered socket goes through
  its own bounded outbox, drained by its own task — the account socket's
  inbox and account frames included. Fan-out puts a frame in each outbox and
  returns, so one slow reader never holds up a room; a reader that falls
  ``OUTBOX_LIMIT`` frames behind is closed and reconnects.

A re-check groups sockets by the account, guild and sign-in that opened them,
and runs one guild entry per group on one session — a person with a board, a
counter group and a file open costs one entry, not three — with at most
``RECHECK_CONCURRENCY`` groups in flight.

What this holds is one process's own sockets. Where the API runs as several
workers each holds a share; the events bus reaches every worker because the
room sink reads the change log, not because anything here is shared.
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, status
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import GuildAccessError, establish_guild_access
from app.core import auth_context
from app.core.tools import Tool
from app.db import post_commit
from app.db import session as db_session
from app.db.cohorts import request_sessionmaker
from app.db.session import RLS_CONTEXT_MAX_AGE_SECONDS
from app.models.platform.user import Presence, User, UserStatus
from app.services.auth import sessions as session_service
from app.services.platform import presence

logger = logging.getLogger(__name__)

#: How long a within-initiative sharing or settings change can take to reach an
#: open socket. Half the session layer's snapshot-age bound, so a healthy loop
#: re-validates every socket well before a held context could go stale.
REAUTH_INTERVAL_SECONDS = RLS_CONTEXT_MAX_AGE_SECONDS // 2

#: Groups re-checked at once. Each holds one pooled connection while it runs.
RECHECK_CONCURRENCY = 8

#: Frames one socket may have waiting before it is closed as too slow.
OUTBOX_LIMIT = 256

#: The close code for a socket whose credential has ended, as opposed to one
#: whose access has (``WS_1008_POLICY_VIOLATION``). A client holding a newer
#: credential for the same account reconnects with it.
WS_CREDENTIAL_ENDED = 4001

#: ``(guild_id, kind, id)``; ``guild_id`` is ``None`` only for an account room.
RoomKey = tuple[int | None, str, int]

_GUILD = "guild"
_INITIATIVE = "initiative"
_ACCOUNT = "account"


def guild_room(guild_id: int) -> RoomKey:
    """Every events-bus socket open on one guild."""
    return (guild_id, _GUILD, guild_id)


def initiative_room(guild_id: int, initiative_id: int) -> RoomKey:
    """The events-bus sockets that may read one initiative."""
    return (guild_id, _INITIATIVE, initiative_id)


def resource_room(guild_id: int, kind: str, resource_id: int) -> RoomKey:
    """The sockets watching one resource. ``kind`` is a ``Tool`` value or a
    collaborative body's entity type."""
    return (guild_id, kind, resource_id)


def account_room(user_id: int) -> RoomKey:
    """An account's own sockets, which belong to no guild."""
    return (None, _ACCOUNT, user_id)


class Wire(enum.Enum):
    """What a socket's frames are. A JSON signal is never sent to a byte
    stream, and the other way round."""

    json = "json"
    bytes = "bytes"


#: Decides which rooms one socket may be in, on a session the guild entry has
#: already routed. The join and every re-check call it; ``None`` or an empty
#: set refuses.
Authorizer = Callable[[AsyncSession, User], Awaitable[frozenset[RoomKey] | None]]


async def account_authorizer(
    _session: AsyncSession, user: User
) -> frozenset[RoomKey] | None:
    """An account socket's rooms: its account's own, while the account is
    active and the sign-in it was opened with stands (both asked before this
    runs)."""
    if user.id is None:
        return None
    return frozenset({account_room(user.id)})


@dataclass(frozen=True)
class Credential:
    """The sign-in a socket was opened with, as its authenticator recorded it.

    Captured at join because a re-check runs in another task, and the gate
    inside the guild entry reads these from the auth context: the re-check
    presents the socket's own values rather than whatever is in flight.
    """

    satisfied_providers: frozenset[int] = frozenset()
    session_amr: frozenset[str] = frozenset()
    satisfied_claims: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    session_id: uuid.UUID | None = None
    token_version: int | None = None

    @classmethod
    def captured(cls) -> Credential:
        recorded = auth_context.current()
        session = recorded.session_credential
        return cls(
            satisfied_providers=recorded.satisfied_providers,
            session_amr=recorded.session_amr,
            satisfied_claims=recorded.satisfied_claims,
            session_id=session.session_id if session else None,
            token_version=session.token_version if session else None,
        )

    def presented(self) -> tuple[Any, ...]:
        """What the guild entry is shown, for grouping sockets that share it."""
        return (
            self.satisfied_providers,
            self.session_amr,
            tuple(
                sorted(
                    (provider, tuple(sorted((k, tuple(v)) for k, v in claims.items())))
                    for provider, claims in self.satisfied_claims.items()
                )
            ),
        )


@dataclass(eq=False)
class Subscriber:
    """One registered socket."""

    websocket: WebSocket
    user: User
    #: The guild the socket was admitted to, or ``None`` for an account socket:
    #: its re-check is the credential and the account's standing alone.
    guild_id: int | None
    wire: Wire
    authorize: Authorizer
    credential: Credential
    rooms: frozenset[RoomKey] = frozenset()
    #: Whether this socket counts its user as online, and as present in its
    #: guild. The events bus and the account socket do; a tool or file
    #: socket is a page inside a guild already counted.
    presence: bool = False
    #: Whatever the channel attached at join: collaboration keeps the display
    #: name and write level here, so nothing else keys state by socket.
    meta: dict[str, Any] = field(default_factory=dict)
    #: The first frame's payload, for a channel that reads more than the token.
    first_frame: Mapping[str, Any] = field(default_factory=dict)
    #: The sign-in chain moves forward as re-checks find the row it has reached.
    session_id: uuid.UUID | None = None
    outbox: asyncio.Queue[Any] = field(
        default_factory=lambda: asyncio.Queue(maxsize=OUTBOX_LIMIT)
    )
    writer: asyncio.Task[None] | None = None
    #: When a frame was last queued for this socket, on the monotonic clock:
    #: what the heartbeat measures the server's own silence against.
    last_sent_at: float = field(default_factory=time.monotonic)
    #: The register it joined, which owns its writer.
    register: ContentSockets | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        # Read once: the row outlives the session that loaded it, and an
        # expired attribute cannot be reloaded once that session has closed.
        user_id = self.user.id
        assert user_id is not None, "a socket is only opened by a stored account"
        self._user_id: int = user_id

    @property
    def user_id(self) -> int:
        """The account's id."""
        return self._user_id

    def send_json(self, message: Mapping[str, Any]) -> None:
        """Queue one JSON frame for this socket."""
        if self.register is not None:
            self.register.enqueue(self, dict(message))

    def send_bytes(self, payload: bytes) -> None:
        """Queue one binary frame for this socket."""
        if self.register is not None:
            self.register.enqueue(self, payload)


@dataclass(frozen=True)
class RoomMember:
    """One connection in a room, as a channel sees it. Two connections from one
    account are two members; a roster of people folds by ``user.id``."""

    user: User
    meta: Mapping[str, Any]


class ContentSockets:
    """The register. Every mutation is synchronous, so the asyncio loop is its
    lock: nothing reads it half-changed."""

    def __init__(self) -> None:
        self._subs: dict[WebSocket, Subscriber] = {}
        self._rooms: dict[RoomKey, set[Subscriber]] = {}
        # user_id -> guild_id (``None`` for the account socket) -> sockets.
        self._by_user: dict[int, dict[int | None, set[Subscriber]]] = {}
        # guild_id -> user_id -> how many of that user's presence sockets are
        # open here. Two tabs are one person.
        self._present: dict[int, dict[int, int]] = {}
        self._loop_task: asyncio.Task[None] | None = None

    # ── membership ─────────────────────────────────────────────────────────

    def join(
        self,
        sub: Subscriber,
        *,
        chosen_presence: Presence = Presence.online,
        presence_known_at: float | None = None,
    ) -> None:
        """Register an admitted socket in the rooms it was admitted to."""
        sub.register = self
        sub.session_id = sub.credential.session_id
        self._subs[sub.websocket] = sub
        self._by_user.setdefault(sub.user_id, {}).setdefault(sub.guild_id, set()).add(
            sub
        )
        for key in sub.rooms:
            self._rooms.setdefault(key, set()).add(sub)
        if sub.presence:
            if sub.guild_id is not None:
                present = self._present.setdefault(sub.guild_id, {})
                present[sub.user_id] = present.get(sub.user_id, 0) + 1
            presence.online.arrived(
                sub.user_id, chosen_presence, known_at=presence_known_at
            )
        sub.writer = asyncio.create_task(self._write(sub))
        self._ensure_loop()

    def leave(self, websocket: WebSocket) -> None:
        """Forget a socket. Idempotent: the endpoint's ``finally`` and a
        disconnect from here may both call it."""
        sub = self._subs.pop(websocket, None)
        if sub is None:
            return
        self._place(sub, frozenset())
        guilds = self._by_user.get(sub.user_id, {})
        owners = guilds.get(sub.guild_id)
        if owners is not None:
            owners.discard(sub)
            if not owners:
                del guilds[sub.guild_id]
                if not guilds:
                    del self._by_user[sub.user_id]
        if sub.presence:
            presence.online.left(sub.user_id)
            present = (
                self._present.get(sub.guild_id) if sub.guild_id is not None else None
            )
            if present is not None:
                remaining = present.get(sub.user_id, 0) - 1
                if remaining > 0:
                    present[sub.user_id] = remaining
                else:
                    present.pop(sub.user_id, None)
                    if not present:
                        del self._present[sub.guild_id]
        if sub.writer is not None and sub.writer is not asyncio.current_task():
            sub.writer.cancel()

    def _place(self, sub: Subscriber, rooms: frozenset[RoomKey]) -> None:
        """Move a socket into exactly ``rooms``."""
        for key in sub.rooms - rooms:
            members = self._rooms.get(key)
            if members is not None:
                members.discard(sub)
                if not members:
                    del self._rooms[key]
        for key in rooms - sub.rooms:
            self._rooms.setdefault(key, set()).add(sub)
        sub.rooms = rooms

    # ── sending ────────────────────────────────────────────────────────────

    def enqueue(self, sub: Subscriber, frame: Any) -> None:
        """Queue one frame; close a socket that has fallen too far behind."""
        if sub.websocket not in self._subs:
            return
        try:
            sub.outbox.put_nowait(frame)
            sub.last_sent_at = time.monotonic()
        except asyncio.QueueFull:
            logger.warning(
                "content socket outbox full for user %s in guild %s; closing",
                sub.user_id,
                sub.guild_id,
            )
            post_commit.spawn(
                self._disconnect(sub, code=status.WS_1013_TRY_AGAIN_LATER)
            )

    def emit_json(self, room: RoomKey, message: Mapping[str, Any]) -> None:
        """Send one JSON frame to every JSON socket in a room."""
        frame = dict(message)
        for sub in list(self._rooms.get(room, ())):
            if sub.wire is Wire.json:
                self.enqueue(sub, frame)

    def emit_bytes(
        self, room: RoomKey, payload: bytes, *, exclude: WebSocket | None = None
    ) -> None:
        """Send one binary frame to every byte-stream socket in a room.

        ``exclude`` is the connection the frame came from, never a user: one
        account's other connections are peers of it.
        """
        for sub in list(self._rooms.get(room, ())):
            if sub.wire is Wire.bytes and sub.websocket is not exclude:
                self.enqueue(sub, payload)

    def signal(
        self, guild_id: int | None, tool: Tool, resource_id: int, event: str
    ) -> None:
        """Tell a tool's room that it changed, and nothing else.

        The frame names the change and the resource, never its content: the
        client refetches through the REST path, which is where the reader's own
        access is decided. A ``None`` guild (an unrouted session) sends nothing.
        """
        if guild_id is None:
            return
        self.emit_json(
            resource_room(guild_id, tool.value, resource_id),
            {
                "type": event,
                "id": resource_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    async def _write(self, sub: Subscriber) -> None:
        """Drain one socket's outbox in order. A send that fails drops it."""
        try:
            while True:
                frame = await sub.outbox.get()
                if isinstance(frame, bytes):
                    await sub.websocket.send_bytes(frame)
                else:
                    await sub.websocket.send_json(frame)
        except asyncio.CancelledError:
            raise
        except Exception:
            self.leave(sub.websocket)
            with contextlib.suppress(Exception):
                await sub.websocket.close()

    # ── reading ────────────────────────────────────────────────────────────

    def room_members(self, room: RoomKey) -> list[RoomMember]:
        return [
            RoomMember(user=sub.user, meta=sub.meta)
            for sub in self._rooms.get(room, ())
        ]

    def room_size(self, room: RoomKey) -> int:
        return len(self._rooms.get(room, ()))

    def users_in_guild(self, guild_id: int) -> set[int]:
        """The users this process holds an events-bus socket for in one guild."""
        return set(self._present.get(guild_id, {}))

    def guild_ids(self) -> list[int]:
        """The guilds this process holds an events-bus socket for."""
        return list(self._present)

    def present_count(self, guild_id: int) -> int:
        """How many distinct users have this guild open on this process."""
        return len(self._present.get(guild_id, {}))

    def present_counts(self, guild_ids: Iterable[int]) -> dict[int, int]:
        return {guild_id: self.present_count(guild_id) for guild_id in guild_ids}

    def account_ids(self) -> list[int]:
        """The accounts this process holds an account socket for."""
        return [user_id for user_id, guilds in self._by_user.items() if None in guilds]

    # ── re-checks ──────────────────────────────────────────────────────────

    async def revoke_user(self, guild_id: int, user_id: int) -> None:
        """Re-check one account's sockets in one guild now. Call after a guild
        or initiative membership change, a role change or a grant revoke."""
        await self._recheck(list(self._by_user.get(user_id, {}).get(guild_id, ())))

    async def refresh_users(self, guild_id: int, user_ids: Iterable[int]) -> None:
        """The same for several accounts: their rooms are recomputed, so an
        initiative someone was just added to reaches their open tab."""
        await self._recheck(
            [
                sub
                for user_id in set(user_ids)
                for sub in self._by_user.get(user_id, {}).get(guild_id, ())
            ]
        )

    async def revoke_user_everywhere(self, user_id: int) -> None:
        """Re-check an account's sockets in every guild. For a change to the
        account or to one of its sign-ins; each socket answers for its own
        credential, so those opened on one that still stands stay open."""
        await self._recheck(
            [sub for subs in self._by_user.get(user_id, {}).values() for sub in subs]
        )

    async def recheck_room(self, room: RoomKey) -> None:
        """Re-check everyone in one room, after that resource's sharing changed."""
        await self._recheck(list(self._rooms.get(room, ())))

    async def _recheck(self, targets: list[Subscriber]) -> None:
        if not targets:
            return
        ended = await self._ended_credentials(targets)
        groups: dict[tuple[Any, ...], list[Subscriber]] = {}
        for sub in targets:
            if sub in ended:
                await self._disconnect(sub, code=WS_CREDENTIAL_ENDED)
                continue
            key = (sub.guild_id, sub.user_id, sub.credential.presented())
            groups.setdefault(key, []).append(sub)
        if not groups:
            return
        limit = asyncio.Semaphore(RECHECK_CONCURRENCY)

        async def bounded(group: list[Subscriber]) -> None:
            async with limit:
                await self._reauthorize(group)

        # Each group runs in its own task, so the credential it presents to the
        # auth context stays in that task and never reaches the caller's.
        await asyncio.gather(*(bounded(group) for group in groups.values()))

    async def _reauthorize(self, group: list[Subscriber]) -> None:
        """Run the guild entry once for a group, then each socket's own check.

        Fail closed: an error drops the sockets it was deciding for.
        """
        first = group[0]
        decided: dict[Subscriber, frozenset[RoomKey] | None] = {}
        try:
            async with request_sessionmaker(first.guild_id)() as session:
                current = await session.get(User, first.user_id)
                if (
                    current is not None
                    and current.status == UserStatus.active
                    and first.guild_id is not None
                ):
                    # Present this socket's sign-in and nothing else: whatever
                    # the task that asked for the re-check had recorded (an
                    # API key, another session) is not this socket's.
                    auth_context.reset(
                        auth_context.AuthContext(
                            session_amr=first.credential.session_amr,
                            satisfied_claims=first.credential.satisfied_claims,
                        )
                    )
                    try:
                        await establish_guild_access(
                            session,
                            current,
                            first.guild_id,
                            satisfied_providers=first.credential.satisfied_providers,
                        )
                    except GuildAccessError:
                        current = None
                if current is not None and current.status == UserStatus.active:
                    for sub in group:
                        try:
                            decided[sub] = await sub.authorize(session, current)
                        except Exception:
                            logger.exception(
                                "content socket re-check failed; closing to fail closed"
                            )
                            decided[sub] = None
                            await session.rollback()
        except Exception:
            logger.exception("content socket re-check failed; closing to fail closed")
        for sub in group:
            rooms = decided.get(sub)
            if not rooms:
                await self._disconnect(sub)
            elif sub.websocket in self._subs:
                self._place(sub, rooms)

    async def _ended_credentials(self, targets: list[Subscriber]) -> set[Subscriber]:
        """The sockets among ``targets`` whose credential no longer stands.

        One statement for the whole batch, on the system engine. A session's id moves to the live row its chain has reached.
        Fail closed: a lookup that errors ends every credential it was asked
        about.
        """
        session_ids = {s.session_id for s in targets if s.session_id is not None}
        versioned = {
            s.user_id for s in targets if s.credential.token_version is not None
        }
        if not session_ids:
            return set()
        try:
            async with db_session.SystemSessionLocal() as system_session:
                tips = await session_service.live_chain_tips(
                    system_session, session_ids=session_ids
                )
                versions: dict[int, int] = {}
                if versioned:
                    rows = await system_session.exec(
                        select(User.id, User.token_version).where(
                            col(User.id).in_(versioned)
                        )
                    )
                    versions = {user_id: version for user_id, version in rows.all()}
        except Exception:
            logger.exception(
                "content socket credential check failed; closing to fail closed"
            )
            return {s for s in targets if s.session_id is not None}

        ended: set[Subscriber] = set()
        for sub in targets:
            if sub.session_id is not None:
                tip = tips.get(sub.session_id)
                if (
                    tip is None
                    or versions.get(sub.user_id) != sub.credential.token_version
                ):
                    ended.add(sub)
                    continue
                sub.session_id = tip
        return ended

    async def _disconnect(
        self, sub: Subscriber, *, code: int = status.WS_1008_POLICY_VIOLATION
    ) -> None:
        self.leave(sub.websocket)
        with contextlib.suppress(Exception):
            await sub.websocket.close(code=code)

    def _ensure_loop(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._reauth_loop())

    async def _reauth_loop(self) -> None:
        """Re-check every socket every interval: the bound on how long a change
        nobody announced can take to reach an open socket."""
        while True:
            await asyncio.sleep(REAUTH_INTERVAL_SECONDS)
            try:
                await self._recheck(list(self._subs.values()))
            except Exception:
                logger.exception("content socket re-check loop iteration failed")


sockets = ContentSockets()
