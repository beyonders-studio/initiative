"""
Real-time collaboration service using Yjs (via pycrdt).

A room is the Yjs document plus its persistence, for ANY body several people
can write at once — a file with an editor, a wiki page. Which row a room is
a body of, and whose sharing decides who may open it, is declared once in
:mod:`app.services.tenant.collaborative_resources`; nothing here knows about
files in particular.

A room deliberately does **not**
keep a list of who is connected: that register lives once, in
:mod:`app.services.content_sockets`, keyed by socket. A channel that keeps its own
copy has to keep the two in step, and the moment they disagree — which is every
time one account opens a second tab — delivery and authorization stop matching
the sockets that actually exist.
"""

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from pycrdt import Doc
from sqlalchemy import func
from sqlalchemy import update as sa_update
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.db import cohorts
from app.db.session import set_rls_context
from app.services import editor_engine
from app.services.content_sockets import resource_room, sockets
from app.services.tenant import attachments as attachments_service
from app.services.tenant import body_states
from app.services.tenant.body_states import BodyState
from app.services.tenant.collaborative_resources import (
    YJS_STATE_COLUMN,
    YJS_UPDATED_COLUMN,
    resource_for,
)
from app.db.request_context import SystemGuild

logger = logging.getLogger(__name__)


class CollaborationRoom:
    """The live Yjs state of one body, and what it owes the database.

    Holds the merged ``Doc`` every connection reads and writes, and enough
    bookkeeping to know whether it has moved since it was last written down.
    """

    def __init__(self, guild_id: int, resource_type: str, resource_id: int):
        self.guild_id = guild_id
        #: Which kind of body this is — the key into the resource registry, and
        #: the namespace this room occupies in the stream register.
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.doc = Doc()
        self._lock = asyncio.Lock()
        self._initialized = False
        # Reading this room's state out of the database is the one slow thing a
        # room does, and it happens once. It gets a lock of its own so it is not
        # done under the lock the registry uses.
        self._load_lock = asyncio.Lock()
        self._loaded = False
        # One writer at a time. A sweep and a disconnect can reach the same
        # room together, and the row must end up holding the newer of the two
        # snapshots rather than whichever commits last.
        self._write_lock = asyncio.Lock()
        # One versioned write at a time, so two naming the same version cannot
        # both find it current.
        self._edit_lock = asyncio.Lock()
        # Connections that have been handed this room but have not yet reached
        # the register. They are on their way in, so the room is not idle.
        self._holds = 0
        #: Everyone who has changed the document in this room.
        self.writers: set[int] = set()
        #: The digest of the stored state this room last read or wrote. A row
        #: holding another one was written since — by a room in another
        #: process, or a write outside any room — and that is merged in.
        self.stored_digest: Optional[str] = None
        # A room dropped from the registry. Nothing should reach one — the
        # registry only drops rooms with no connections — but a write that does
        # would go nowhere, so it says so instead of swallowing it.
        self.detached = False
        # Revisions, not a boolean: a write serializes a snapshot and then
        # commits, and an edit landing in between must not be marked saved.
        self._revision = 0
        self._persisted_revision = 0
        #: How the body moves between its views, for a body with a live
        #: editor: the server makes its Yjs state and renders its content.
        self.body: Optional[BodyState] = None

    @property
    def renders_content(self) -> bool:
        """Whether the server renders this body's content from its state."""
        return self.body is not None

    @property
    def is_loaded(self) -> bool:
        """Whether this room has had its one read of the database."""
        return self._loaded

    @property
    def is_dirty(self) -> bool:
        """Whether anything has changed since the last successful write."""
        return self._revision != self._persisted_revision

    def connection_count(self) -> int:
        """How many sockets are in this room, asked of the one register."""
        return sockets.room_size(
            resource_room(self.guild_id, self.resource_type, self.resource_id)
        )

    def is_empty(self) -> bool:
        """Whether nothing is in this room and nothing is arriving.

        A connection is handed its room before it reaches the register, so
        the count alone would read a room as idle during that gap.
        """
        return self.connection_count() == 0 and self._holds == 0

    def hold(self) -> None:
        """Claim this room for a connection that is joining, or a write that is
        on its way in."""
        self._holds += 1

    def release(self) -> None:
        """Drop a claim, once the connection holding it has reached the
        register or given up."""
        if self._holds > 0:
            self._holds -= 1

    async def load_once(self, session: AsyncSession) -> None:
        """Read this room's stored state, once, however many callers arrive.

        Callers can reach a room the moment it is claimed, before anyone has
        loaded it. The first one through does the read and the rest wait on it
        rather than repeating it. A document that is no longer there still
        counts as read: the room stays empty rather than asking again.

        ``session`` must be routed to the guild whose schema holds the row.
        """
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            spec = resource_for(self.resource_type)
            statement = select(
                getattr(spec.model, YJS_STATE_COLUMN), spec.body_kind()
            ).where(spec.model.id == self.resource_id)
            row = (await session.exec(statement)).one_or_none()
            if row:
                state, self.body = row[0], body_states.for_kind(row[1])
                if self.body is not None and (
                    state is None or not self.body.holds_body(state)
                ):
                    state = await _bootstrapped(
                        self.guild_id, self.resource_type, self.resource_id, self.body
                    )
                self.stored_digest = _digest(state)
                await self.initialize_from_db(yjs_state=state)
            self._loaded = True

    async def initialize_from_db(self, yjs_state: Optional[bytes]) -> None:
        """Initialize the Y.Doc from database state.

        An editor body arrives with a state the server made; any other body
        with none yet starts empty, and the first browser editing it fills it.
        """
        async with self._lock:
            if self._initialized:
                return

            if yjs_state:
                # Restore from existing Yjs state
                try:
                    self.doc.apply_update(yjs_state)
                    logger.info(
                        "%s %s: restored from Yjs state",
                        self.resource_type,
                        self.resource_id,
                    )
                except Exception as e:
                    logger.warning(
                        "%s %s: failed to restore Yjs state: %s",
                        self.resource_type,
                        self.resource_id,
                        e,
                    )
            else:
                logger.info(
                    "%s %s: no Yjs state, the first editor will fill it",
                    self.resource_type,
                    self.resource_id,
                )

            self._initialized = True

    def get_state(self) -> bytes:
        """Get the current Y.Doc state as an update that can be applied by clients."""
        # get_update() with empty state vector returns the full document as an update
        # This is compatible with JavaScript Yjs's Y.applyUpdate()
        return bytes(self.doc.get_update())

    def get_state_diff(self, state_vector: bytes) -> bytes:
        """Get only the updates the client is missing based on their state vector.

        This is more efficient than get_state() when the client already has
        some of the document state.
        """
        if not state_vector:
            return self.get_state()
        return bytes(self.doc.get_update(state_vector))

    def state_vector(self) -> bytes:
        """What this room already has, for a client to answer with the rest.

        The other half of the sync handshake: a client that reconnects holding
        work the room never saw can only hand it over if it is asked, and this
        is the asking.
        """
        return bytes(self.doc.get_state())

    def apply_update(self, update: bytes, user_id: int | None = None) -> None:
        """Apply a Yjs update from a client, sent by ``user_id``."""
        self.doc.apply_update(update)
        self._revision += 1
        if user_id is not None:
            self.writers.add(user_id)

    async def rendering(self) -> Optional[dict]:
        """What this body reads as now, rendered from its live document."""
        assert self.body is not None
        return await self.body.render(self.get_state())

    async def write(self, content: dict, version: str, user_id: Optional[int]) -> bool:
        """Write ``content`` into this body's live document, as its editor
        makes it read, if the body still reads as ``version``,
        and hand the change to everyone in the room. It is saved as their
        edits are.

        Returns whether it was written. The room is held until the write is in
        it, so it stays registered for the save; one the last editor left in
        the meantime is saved and retired here.
        """
        self.hold()
        try:
            async with self._edit_lock:
                assert self.body is not None
                current = await self.rendering()
                if current is None or content_version(current) != version:
                    return False
                update = await self.body.apply(self.get_state(), content)
                self.apply_update(update, user_id=user_id)
                sockets.emit_bytes(
                    resource_room(self.guild_id, self.resource_type, self.resource_id),
                    bytes([MSG_UPDATE]) + update,
                )
                return True
        finally:
            self.release()
            await collaboration_manager.leave(
                self.guild_id, self.resource_type, self.resource_id
            )

    def take_stored(self, stored: bytes) -> None:
        """Merge a stored state written since this room read it, and hand
        what it adds to everyone here."""
        before = self.doc.get_state()
        self.apply_update(stored)
        sockets.emit_bytes(
            resource_room(self.guild_id, self.resource_type, self.resource_id),
            bytes([MSG_UPDATE]) + bytes(self.doc.get_update(before)),
        )

    def snapshot(self) -> Tuple[int, bytes]:
        """The revision being written, and the state it is."""
        return self._revision, self.get_state()

    def mark_persisted(self, revision: int) -> None:
        """Record that ``revision`` reached the database.

        Only moves forward: an edit that landed while the write was in flight
        leaves the room dirty, so the next sweep picks it up.
        """
        if revision > self._persisted_revision:
            self._persisted_revision = revision


def _digest(state: Optional[bytes]) -> Optional[str]:
    """A stored state's digest, as Postgres's ``md5`` gives it."""
    return hashlib.md5(state, usedforsecurity=False).hexdigest() if state else None


def _merged(state: bytes, update: bytes) -> bytes:
    doc = Doc()
    doc.apply_update(state)
    doc.apply_update(update)
    return bytes(doc.get_update())


async def _bootstrapped(
    guild_id: int, resource_type: str, resource_id: int, body: BodyState
) -> Optional[bytes]:
    """A body's Yjs state, made from its content by the server when the row
    has none, or has one that holds no body.

    Taken under the row's lock on a system session, so rooms opening the same
    row together make it once, and a reader opening it can still have it made.
    """
    spec = resource_for(resource_type)
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        row = (
            await session.exec(
                select(
                    getattr(spec.model, YJS_STATE_COLUMN),
                    getattr(spec.model, spec.content_column),
                )
                .where(spec.model.id == resource_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            return None
        state, content = row
        if state is None or not body.holds_body(state):
            made = await body.bootstrap(content)
            # A state a browser saved before writing anything into it keeps
            # what it has, and gains the body beside it.
            state = made if state is None else _merged(state, made)
            await session.exec(
                sa_update(spec.model)
                .where(spec.model.id == resource_id)
                .values(
                    {
                        YJS_STATE_COLUMN: state,
                        YJS_UPDATED_COLUMN: datetime.now(timezone.utc),
                    }
                )
            )
            await session.commit()
        return state


async def written_into(
    body: BodyState, state: Optional[bytes], content: dict
) -> Optional[bytes]:
    """A body's stored Yjs state with ``content`` written into it.

    Only what changed is rewritten, so the state keeps the history its editors
    made and a session reopening it starts from this content. A body with no
    state keeps none: the room makes it when it opens. Content the editor
    refuses leaves no state either, and the room makes one from the content in
    the same way.
    """
    if state is None:
        return None
    try:
        update = await body.apply(state, content)
    except editor_engine.EditorError:
        logger.exception("The editor could not write content into a stored state")
        return None
    return _merged(state, update)


#: The socket frame that carries a Yjs update.
MSG_UPDATE = 2


def content_version(content: dict) -> str:
    """A body's version, as a write names the one it read: a digest of the
    content, so it moves exactly when what the body reads as does."""
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


async def current_content(
    guild_id: int, resource_type: str, resource_id: int, stored: dict
) -> dict:
    """What a body reads as now: an open editor room's rendering of its live
    document, or ``stored`` while no room is open."""
    room = collaboration_manager.live_room(guild_id, resource_type, resource_id)
    if room is None or not room.renders_content:
        return stored
    return await room.rendering() or stored


async def versioned(read: Any, guild_id: int, resource_type: str) -> Any:
    """``read`` with the content its body reads as now and that content's
    version, for the next write to name."""
    read.content = await current_content(guild_id, resource_type, read.id, read.content)
    read.content_version = content_version(read.content)
    return read


# A room is identified by (guild_id, resource_type, resource_id). The guild_id
# is part of the key because bodies live in per-guild schemas (`guild_<id>.…`,
# `id SERIAL`): ids are per-schema sequences, so id 5 names a different row in
# every guild that has one. The resource_type is part of it because two kinds
# number independently — file 5 and wiki page 5 are both real. This manager
# is a single process-global structure, so neither the id nor the pair without
# the guild identifies a body. Never key collaboration state by a
# guild-schema-local id alone.
RoomKey = Tuple[int, str, int]

# How often the sweeper writes rooms that have changed.
PERSISTENCE_INTERVAL_SECONDS = 30


class CollaborationManager:
    """
    Manages every active collaboration room, of every kind.

    Handles:
    - Room lifecycle (create, destroy)
    - Persistence scheduling
    - Global state tracking
    """

    def __init__(self):
        self._rooms: Dict[RoomKey, CollaborationRoom] = {}
        self._lock = asyncio.Lock()
        self._persistence_interval = PERSISTENCE_INTERVAL_SECONDS
        self._persistence_task: Optional[asyncio.Task] = None

    async def get_or_create_room(
        self,
        guild_id: int,
        resource_type: str,
        resource_id: int,
        session: AsyncSession,
    ) -> CollaborationRoom:
        """Get an existing room or create a new one.

        ``session`` must be routed to ``guild_id`` — the body is loaded through
        it, from that guild's schema.
        """
        key = (guild_id, resource_type, resource_id)
        # The registry lock is held only long enough to claim the room's slot.
        # Reading its state is database I/O, and doing that here would make one
        # slow document a wait for every other room in the process, in every
        # guild. It happens below, guarded by the room itself.
        async with self._lock:
            room = self._rooms.get(key)
            if room is None:
                room = CollaborationRoom(guild_id, resource_type, resource_id)
                self._rooms[key] = room
                logger.info(
                    "Created collaboration room for %s %s in guild %s",
                    resource_type,
                    resource_id,
                    guild_id,
                )

        await room.load_once(session)
        return room

    async def remove_room(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> None:
        """Remove a room once nothing is connected to it."""
        key = (guild_id, resource_type, resource_id)
        async with self._lock:
            room = self._rooms.get(key)
            if not room:
                return
            # A room that has been claimed but not yet read in is empty because
            # nobody has arrived yet, not because everyone has left. Whoever is
            # loading it is about to join it.
            if not room.is_loaded:
                return
            if not room.is_empty():
                return
            # Anything unsaved is written by the caller before this point; a
            # room still dirty here would lose it, so it stays until the sweep.
            if room.is_dirty:
                return
            room.detached = True
            del self._rooms[key]
            logger.info(
                "Removed empty collaboration room for %s %s", resource_type, resource_id
            )

    async def invalidate_room_if_empty(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> bool:
        """Remove a room if it exists and has no active connections.

        Used when a body is modified externally (e.g. unlinking the
        references to a file that is purged) so the next session loads
        fresh state from the database instead of stale in-memory state.

        Returns True if the room was removed, False if it is still in use (in
        which case its connections hold their state until reload).
        """
        key = (guild_id, resource_type, resource_id)
        async with self._lock:
            room = self._rooms.get(key)
            if not room:
                return True  # No room, nothing to invalidate
            if not room.is_loaded:
                # Being read in right now: leave it to the caller doing that,
                # who is about to join it.
                return False
            if room.is_empty():
                if room.is_dirty:
                    # Empty but still owing the database: the sweep has it.
                    logger.info(
                        "%s %s has unsaved state; keeping its room until it is written",
                        resource_type,
                        resource_id,
                    )
                    return False
                room.detached = True
                del self._rooms[key]
                logger.info(
                    "Invalidated empty collaboration room for %s %s",
                    resource_type,
                    resource_id,
                )
                return True
            else:
                logger.warning(
                    "%s %s has active collaborators - "
                    "they may see stale references until reload",
                    resource_type,
                    resource_id,
                )
                return False

    async def save(self, room: CollaborationRoom) -> None:
        """Write one room, on a system session from its community's cohort
        routed into it.

        The one way a room reaches the database: the sweep, the last
        connection leaving and a handed-over edit all come here, so none of
        them depends on whose request happened to be last in the room.
        """
        async with cohorts.system_session(room.guild_id) as session:
            await set_rls_context(session, SystemGuild(room.guild_id))
            await self._write_room(room, session)

    async def leave(self, guild_id: int, resource_type: str, resource_id: int) -> None:
        """Save a room nothing is connected to any more, and retire it.

        A room somebody is still in, or on their way into, is left alone. A
        save that fails leaves the room dirty, and the sweep tries again.
        """
        async with self._lock:
            room = self._rooms.get((guild_id, resource_type, resource_id))
        if room is None or not room.is_empty():
            return
        if room.is_dirty:
            try:
                await self.save(room)
            except Exception as exc:
                logger.error(
                    "Failed to save %s %s in guild %s (%s)",
                    resource_type,
                    resource_id,
                    guild_id,
                    type(exc).__name__,
                )
        await self.remove_room(guild_id, resource_type, resource_id)

    async def _write_room(self, room: CollaborationRoom, session: AsyncSession) -> None:
        """Bring one room and its row together: merge into the room what was
        stored since it last looked, then write both views of it in a single
        statement if it has edits of its own.

        Several processes can each hold a room for one body. Each merges what
        the others saved before writing, under the row's lock, so a save keeps
        every process's edits rather than the last one's.

        ``content`` is the server's rendering of the state. A state that
        renders no body leaves the column as it stands rather than blanking
        it.
        """
        async with room._write_lock:
            await self._write_room_locked(room, session)

    async def _write_room_locked(
        self, room: CollaborationRoom, session: AsyncSession
    ) -> None:
        spec = resource_for(room.resource_type)
        state_column = getattr(spec.model, YJS_STATE_COLUMN)
        this_row = spec.model.id == room.resource_id
        # Where the room stood before this save waits on the database: an edit
        # arriving meanwhile is the room's own, and is written.
        before = room.snapshot()[0]
        own_edits = room.is_dirty
        stored = (
            await session.exec(
                select(spec.model.id, func.md5(state_column))
                .where(this_row)
                .with_for_update()
            )
        ).one_or_none()
        digest = stored[1] if stored is not None else None
        newer = None
        if digest is not None and digest != room.stored_digest:
            newer = (await session.exec(select(state_column).where(this_row))).one()
        own_edits = own_edits or room.snapshot()[0] != before
        if newer is not None:
            room.take_stored(newer)
            room.stored_digest = digest
        if not own_edits and not (stored is not None and digest is None):
            # Everything the room holds is stored. A row whose state was
            # cleared is written again: the room's is the document its editors
            # hold.
            room.mark_persisted(room.snapshot()[0])
            await session.commit()
            return
        revision, state = room.snapshot()
        content = await room.body.render(state) if room.body is not None else None
        now = datetime.now(timezone.utc)
        values: Dict[str, Any] = {YJS_STATE_COLUMN: state, YJS_UPDATED_COLUMN: now}
        if content is not None:
            # Imported here rather than at module scope: the sync reaches back
            # into this registry to retire idle rooms.
            from app.services.tenant import content_references
            from app.services.tenant.relationships import Endpoint

            try:
                await content_references.sync_for_entity(
                    session,
                    Endpoint(spec.entity_type, room.resource_id),
                    body=content,
                )
            except Exception as exc:
                logger.error(
                    "Failed to sync references for %s %s in guild %s (%s)",
                    room.resource_type,
                    room.resource_id,
                    room.guild_id,
                    type(exc).__name__,
                )
            values[spec.content_column] = content
            # The body changed, as much as a PATCH of it would have changed
            # it: a reader judging what it holds against the row's age (a
            # device's unsaved scene, a list sorted by recent edits) sees it.
            values["updated_at"] = now
        try:
            result = await session.exec(
                sa_update(spec.model)
                .where(spec.model.id == room.resource_id)
                .values(**values)
            )
            if content is not None and result.rowcount:
                # The files its writers uploaded are claimed. Nothing is copied:
                # the content is the rendering of the room's document, which
                # the next save writes again as they hold it.
                await attachments_service.claim_uploads(
                    session,
                    await session.get(spec.model, room.resource_id),
                    uploaded_by=room.writers,
                )
            await session.commit()
            if result.rowcount:
                room.mark_persisted(revision)
                room.stored_digest = _digest(state)
                logger.debug(
                    "Persisted Yjs state for %s %s",
                    room.resource_type,
                    room.resource_id,
                )
            else:
                # The row was not reachable on this session — deleted, or the
                # context was not routed to its guild. Either way nothing was
                # written, and the room stays dirty rather than reporting a
                # save that did not happen.
                logger.warning(
                    "Persisting %s %s in guild %s matched no row; leaving it unsaved",
                    room.resource_type,
                    room.resource_id,
                    room.guild_id,
                )
        except Exception as e:
            logger.error(
                "Failed to persist Yjs state for %s %s in guild %s (%s)",
                room.resource_type,
                room.resource_id,
                room.guild_id,
                type(e).__name__,
            )
            await session.rollback()

    async def persist_dirty_rooms(self) -> int:
        """Write every room that has changed since it was last written, bring
        every room somebody is in up to date with what is stored, then retire
        the ones nobody is in.

        Returns how many rooms it saved or brought up to date. A room somebody
        is in takes what another process saved within one sweep. One nobody is
        in any more — its last save failed, or the connection that left could
        not finish — is retired here once it is saved, rather than held for the
        life of the process.
        """
        async with self._lock:
            targets = [
                room
                for room in self._rooms.values()
                if room.is_dirty or not room.is_empty()
            ]
        for room in targets:
            try:
                await self.save(room)
            except Exception as exc:
                logger.error(
                    "Sweep failed to persist %s %s in guild %s (%s)",
                    room.resource_type,
                    room.resource_id,
                    room.guild_id,
                    type(exc).__name__,
                )
        async with self._lock:
            idle = [key for key, room in self._rooms.items() if room.is_empty()]
        for key in idle:
            await self.remove_room(*key)
        return len(targets)

    def ensure_persistence_loop(self) -> None:
        """Start the sweeper if it isn't already running."""
        if self._persistence_task is None or self._persistence_task.done():
            self._persistence_task = asyncio.create_task(self._persistence_loop())

    async def stop_persistence_loop(self) -> None:
        """Stop the sweeper, writing anything outstanding on the way out.

        A shutdown is the last chance to write what is open, so it takes it
        rather than waiting out the rest of the interval.
        """
        task = self._persistence_task
        self._persistence_task = None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        try:
            await self.persist_dirty_rooms()
        except Exception as exc:
            logger.error(
                "final collaboration persistence sweep failed (%s)", type(exc).__name__
            )

    async def _persistence_loop(self) -> None:
        """Write changed rooms on an interval.

        Durability that depends on a clean disconnect is durability a crash,
        a restart or a dropped connection takes with it. This bounds what an
        abnormal exit can cost to one interval's worth of edits.
        """
        while True:
            await asyncio.sleep(self._persistence_interval)
            try:
                await self.persist_dirty_rooms()
            except Exception as exc:
                logger.error(
                    "collaboration persistence sweep failed (%s)", type(exc).__name__
                )

    def has_active_collaborators(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> bool:
        """Check if a document has any live connection."""
        return self.live_room(guild_id, resource_type, resource_id) is not None

    def live_room(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> Optional[CollaborationRoom]:
        """The room a body is being edited in, if anyone is connected to it."""
        room = self._rooms.get((guild_id, resource_type, resource_id))
        return room if room is not None and not room.is_empty() else None


def room_roster(guild_id: int, resource_type: str, resource_id: int) -> list[dict]:
    """Who is editing a document, one entry per person.

    Read from the connection register, so it cannot drift from the sockets
    that exist. Two tabs are two connections and one collaborator: the roster
    is about people, and a person is here if any of their connections is. They
    can write if any of those connections may.
    """
    by_user: Dict[int, dict] = {}
    for member in sockets.room_members(
        resource_room(guild_id, resource_type, resource_id)
    ):
        user_id = member.user.id
        if user_id is None:
            continue
        entry = by_user.get(user_id)
        if entry is None:
            by_user[user_id] = {
                "user_id": user_id,
                "name": member.meta.get("name") or "",
                "can_write": bool(member.meta.get("can_write")),
                "avatar_url": member.meta.get("avatar_url"),
            }
        elif member.meta.get("can_write"):
            entry["can_write"] = True
    return list(by_user.values())


def user_has_connection(
    guild_id: int, resource_type: str, resource_id: int, user_id: int
) -> bool:
    """Whether this account still holds any connection to a document.

    A person leaves a document when their last tab does, not when one of
    several does.
    """
    return any(
        member.user.id == user_id
        for member in sockets.room_members(
            resource_room(guild_id, resource_type, resource_id)
        )
    )


def broadcast_awareness(
    guild_id: int,
    resource_type: str,
    resource_id: int,
    awareness_data: dict,
    *,
    exclude=None,
) -> None:
    """Send a JSON awareness frame to a document's room.

    ``exclude`` is the originating connection, never its account — the frame
    is about one socket's cursor, and the same person's other tab has its own.
    """
    MSG_AWARENESS = 3
    message = (
        bytes([MSG_AWARENESS])
        + json.dumps({"type": "awareness", "data": awareness_data}).encode()
    )
    sockets.emit_bytes(
        resource_room(guild_id, resource_type, resource_id), message, exclude=exclude
    )


# Global collaboration manager instance
collaboration_manager = CollaborationManager()
