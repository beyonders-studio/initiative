"""Unit tests for the collaboration room registry.

The rooms themselves are exercised through the WebSocket endpoint; what is
covered here is how they are *addressed*. Ids are per-guild-schema sequences,
so the id alone does not name a body — the key has to carry the guild — and two
kinds number independently, so it has to carry the kind too.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.search import SearchEntityType
from app.services.content_sockets import RoomMember
from app.services.tenant import collaboration as collaboration_module
from app.services.tenant.collaboration import (
    CollaborationManager,
    CollaborationRoom,
    room_roster,
    user_has_connection,
)

#: The kind most of these use. Which kind a room is for does not change how it
#: is addressed, so one stands for all of them except where two are the point.
DOC = SearchEntityType.file.value
PAGE = SearchEntityType.wiki_page.value


class FakeResult:
    def __init__(self, value):
        self._value = value

    def one_or_none(self):
        return self._value


class SlowSession:
    """A session whose read takes as long as the test says it does.

    Standing in for the database lets a test say what the registry does *while*
    a room is being read in, which is the whole point of doing that read outside
    the registry's lock.
    """

    def __init__(self, file=None, delay: float = 0.05):
        self.file = file
        self.delay = delay
        self.reads = 0

    async def exec(self, _statement):
        self.reads += 1
        await asyncio.sleep(self.delay)
        return FakeResult(self.file)


def loaded_room(
    guild_id: int, resource_id: int, resource_type: str = DOC
) -> CollaborationRoom:
    """A room as it stands once its one read of the database is done."""
    room = CollaborationRoom(guild_id, resource_type, resource_id)
    room._loaded = True
    return room


async def test_the_same_file_id_in_two_guilds_is_two_rooms() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, DOC, 5)] = loaded_room(1, 5)
    manager._rooms[(2, DOC, 5)] = loaded_room(2, 5)

    first = manager._rooms.get((1, DOC, 5))
    second = manager._rooms.get((2, DOC, 5))

    assert first is not None
    assert second is not None
    assert first is not second
    assert set(manager._rooms) == {(1, DOC, 5), (2, DOC, 5)}


async def test_the_same_id_in_two_kinds_is_two_rooms() -> None:
    """File 5 and wiki page 5 are both real, and both exist in the same
    guild. Keyed by the pair alone they would share one Yjs document, and each
    would be served the other's body."""
    manager = CollaborationManager()
    manager._rooms[(1, DOC, 5)] = loaded_room(1, 5, DOC)
    manager._rooms[(1, PAGE, 5)] = loaded_room(1, 5, PAGE)

    file_room = manager._rooms.get((1, DOC, 5))
    page_room = manager._rooms.get((1, PAGE, 5))

    assert file_room is not None
    assert page_room is not None
    assert file_room is not page_room
    assert file_room.resource_type == DOC
    assert page_room.resource_type == PAGE


async def test_a_room_is_reached_only_from_its_own_guild() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, DOC, 5)] = loaded_room(1, 5)

    assert manager._rooms.get((1, DOC, 5)) is not None
    assert manager._rooms.get((2, DOC, 5)) is None
    assert manager.live_room(2, DOC, 5) is None


async def test_removing_a_room_leaves_the_other_guild_alone() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, DOC, 5)] = loaded_room(1, 5)
    manager._rooms[(2, DOC, 5)] = loaded_room(2, 5)

    # Both are empty of collaborators, so both are removable — only the one
    # named should go.
    await manager.remove_room(1, DOC, 5)

    assert manager._rooms.get((1, DOC, 5)) is None
    assert manager._rooms.get((2, DOC, 5)) is not None


async def test_invalidating_a_room_leaves_the_other_guild_alone() -> None:
    manager = CollaborationManager()
    manager._rooms[(1, DOC, 5)] = loaded_room(1, 5)
    manager._rooms[(2, DOC, 5)] = loaded_room(2, 5)

    assert await manager.invalidate_room_if_empty(1, DOC, 5) is True

    assert manager._rooms.get((1, DOC, 5)) is None
    assert manager._rooms.get((2, DOC, 5)) is not None


async def test_loading_one_room_does_not_stall_another() -> None:
    """The registry lock is not held across the read.

    A slow file in one guild must not hold up a room in another, which is
    what a lock held across I/O would do.
    """
    manager = CollaborationManager()
    slow = SlowSession(delay=0.2)
    quick = SlowSession(delay=0.0)

    async def open_slow():
        await manager.get_or_create_room(1, DOC, 5, slow)

    slow_task = asyncio.create_task(open_slow())
    await asyncio.sleep(0.01)  # let it get as far as the read

    # While that one is still reading, another room opens and returns.
    await asyncio.wait_for(manager.get_or_create_room(2, DOC, 9, quick), timeout=0.1)

    await slow_task
    assert set(manager._rooms) == {(1, DOC, 5), (2, DOC, 9)}


async def test_a_room_is_read_once_however_many_arrive_together() -> None:
    """Two callers on the same new room make one read between them."""
    manager = CollaborationManager()
    session = SlowSession(delay=0.05)

    first, second = await asyncio.gather(
        manager.get_or_create_room(1, DOC, 5, session),
        manager.get_or_create_room(1, DOC, 5, session),
    )

    assert first is second
    assert session.reads == 1
    # And a later arrival does not read again.
    await manager.get_or_create_room(1, DOC, 5, session)
    assert session.reads == 1


async def test_a_room_being_read_in_is_not_collected_as_idle() -> None:
    """An unread room is empty because nobody has arrived, not because they left."""
    manager = CollaborationManager()
    slow = SlowSession(delay=0.2)

    opening = asyncio.create_task(manager.get_or_create_room(1, DOC, 5, slow))
    await asyncio.sleep(0.01)

    await manager.remove_room(1, DOC, 5)
    assert await manager.invalidate_room_if_empty(1, DOC, 5) is False
    assert manager._rooms.get((1, DOC, 5)) is not None

    room = await opening
    assert room is manager._rooms.get((1, DOC, 5))

    # Once it has been read in, an empty room is collectable as before.
    assert await manager.invalidate_room_if_empty(1, DOC, 5) is True
    assert manager._rooms.get((1, DOC, 5)) is None


# ── the connection register is the only register ─────────────────────────────


class FakeRegister:
    """Stands in for the socket register, holding connections per room."""

    def __init__(self) -> None:
        self.rooms: dict[tuple, list[RoomMember]] = {}

    def add(self, guild_id, file_id, member) -> None:
        self.rooms.setdefault((guild_id, "file", file_id), []).append(member)

    def room_size(self, room) -> int:
        return len(self.rooms.get(room, []))

    def room_members(self, room):
        return list(self.rooms.get(room, []))


def member(user_id: int, *, name: str = "Ada", can_write: bool = True) -> RoomMember:
    return RoomMember(
        user=SimpleNamespace(id=user_id),
        meta={"name": name, "can_write": can_write, "avatar_url": None},
    )


@pytest.fixture
def authority(monkeypatch):
    fake = FakeRegister()
    monkeypatch.setattr(collaboration_module, "sockets", fake)
    return fake


async def test_two_tabs_of_one_account_are_one_collaborator(authority) -> None:
    """The roster is about people; delivery is about connections."""
    authority.add(1, 5, member(7, name="Ada"))
    authority.add(1, 5, member(7, name="Ada"))
    authority.add(1, 5, member(9, name="Grace"))

    roster = room_roster(1, DOC, 5)

    assert sorted(entry["user_id"] for entry in roster) == [7, 9]


async def test_a_reader_who_opens_a_writable_tab_can_write(authority) -> None:
    authority.add(1, 5, member(7, can_write=False))
    authority.add(1, 5, member(7, can_write=True))

    assert room_roster(1, DOC, 5)[0]["can_write"] is True


async def test_a_room_is_kept_while_any_connection_is_in_it(authority) -> None:
    """A room is retired on its connections, one per socket — so one tab
    closing leaves a room that another tab is still holding."""
    manager = CollaborationManager()
    manager._rooms[(1, DOC, 5)] = loaded_room(1, 5)
    authority.add(1, 5, member(7))

    await manager.remove_room(1, DOC, 5)
    assert manager._rooms.get((1, DOC, 5)) is not None

    assert await manager.invalidate_room_if_empty(1, DOC, 5) is False
    assert manager._rooms.get((1, DOC, 5)) is not None


async def test_a_room_with_unsaved_work_is_not_retired(authority) -> None:
    """Nothing is dropped while it still owes the database something."""
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room
    room.apply_update(_an_update())

    await manager.remove_room(1, DOC, 5)

    assert manager._rooms.get((1, DOC, 5)) is room
    assert room.detached is False


# ── persistence ──────────────────────────────────────────────────────────────


class FakeExecResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount

    def one_or_none(self) -> None:
        # Nothing stored since the room read it.
        return None


class RecordingSession:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.statements: list = []
        self.commits = 0
        self.rollbacks = 0

    async def exec(self, statement):
        self.statements.append(statement)
        return FakeExecResult(self.rowcount)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def test_a_room_is_clean_once_its_revision_reaches_the_row() -> None:
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room
    room.apply_update(_an_update())
    assert room.is_dirty is True

    await manager._write_room(room, RecordingSession())

    assert room.is_dirty is False


async def test_a_write_that_reaches_no_row_leaves_the_room_unsaved() -> None:
    """A save that matched nothing is not a save.

    A room reports itself clean on the strength of rows actually written, so
    a write that reached none leaves it owing the same work.
    """
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room
    room.apply_update(_an_update())

    await manager._write_room(room, RecordingSession(rowcount=0))

    assert room.is_dirty is True


async def test_an_edit_during_a_write_survives_it() -> None:
    """The revision saved is the one that was serialized, not whatever is
    current when the commit returns."""
    room = loaded_room(1, 5)
    revision, _state = room.snapshot()
    room.apply_update(_an_update())  # lands while the write is in flight
    room.mark_persisted(revision)

    assert room.is_dirty is True


async def test_an_edit_while_a_sweep_reads_the_row_is_written() -> None:
    """A sweep of a room with nothing to write waits on the database first;
    an edit landing in that wait is the room's own, and is written."""
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room

    class EditedMeanwhile(RecordingSession):
        async def exec(self, statement):
            if not self.statements:
                room.apply_update(_an_update())
            return await super().exec(statement)

    reading = EditedMeanwhile()
    await manager._write_room(room, reading)

    assert len(reading.statements) == 2  # the read, then the write
    assert room.is_dirty is False


async def test_an_unchanged_room_is_not_rewritten(monkeypatch) -> None:
    """Idle files cost nothing to keep open."""
    manager = CollaborationManager()
    clean = loaded_room(1, 5)
    dirty = loaded_room(1, 6)
    dirty.apply_update(_an_update())
    manager._rooms[(1, DOC, 5)] = clean
    manager._rooms[(1, DOC, 6)] = dirty

    written: list[int] = []

    async def fake_save(room):
        written.append(room.resource_id)
        room.mark_persisted(room._revision)

    monkeypatch.setattr(manager, "save", fake_save)

    assert await manager.persist_dirty_rooms() == 1
    assert written == [6]
    # Nobody is in either, and both are saved: the sweep retires them.
    assert manager._rooms == {}


async def test_the_sweep_keeps_a_room_somebody_is_in(authority, monkeypatch) -> None:
    manager = CollaborationManager()
    occupied, arriving = loaded_room(1, 5), loaded_room(1, 6)
    manager._rooms[(1, DOC, 5)] = occupied
    manager._rooms[(1, DOC, 6)] = arriving
    authority.add(1, 5, member(7))
    arriving.hold()

    await manager.persist_dirty_rooms()

    assert set(manager._rooms) == {(1, DOC, 5), (1, DOC, 6)}


async def test_leaving_saves_then_retires_an_empty_room(monkeypatch) -> None:
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room
    room.apply_update(_an_update())
    saved: list[int] = []

    async def fake_save(saving):
        saved.append(saving.resource_id)
        saving.mark_persisted(saving._revision)

    monkeypatch.setattr(manager, "save", fake_save)

    await manager.leave(1, DOC, 5)

    assert saved == [5]
    assert manager._rooms == {}


async def test_a_failed_save_on_leaving_keeps_the_room_for_the_sweep(
    monkeypatch,
) -> None:
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room
    room.apply_update(_an_update())

    async def failing_save(_room):
        raise RuntimeError("database away")

    monkeypatch.setattr(manager, "save", failing_save)

    await manager.leave(1, DOC, 5)

    assert manager._rooms.get((1, DOC, 5)) is room


def _an_update() -> bytes:
    """A real Yjs update, so the room's document genuinely moves."""
    from pycrdt import Doc, Map

    doc = Doc()
    doc["cells"] = Map()
    doc["cells"]["A1"] = "value"
    return bytes(doc.get_update())


async def test_a_person_is_still_here_while_one_of_their_tabs_remains(
    authority,
) -> None:
    authority.add(1, 5, member(7))

    assert user_has_connection(1, DOC, 5, 7) is True
    assert user_has_connection(1, DOC, 5, 9) is False


async def test_a_room_being_joined_is_not_retired(authority) -> None:
    """A connection is handed its room before it reaches the register.

    The room is held across that gap, so the last connection leaving during it
    retires nothing.
    """
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room
    room.hold()

    await manager.remove_room(1, DOC, 5)
    assert manager._rooms.get((1, DOC, 5)) is room
    assert await manager.invalidate_room_if_empty(1, DOC, 5) is False

    room.release()
    await manager.remove_room(1, DOC, 5)
    assert manager._rooms.get((1, DOC, 5)) is None


async def test_an_empty_room_with_unsaved_work_is_not_invalidated(authority) -> None:
    """External invalidation holds the same line as retirement."""
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room
    room.apply_update(_an_update())

    assert await manager.invalidate_room_if_empty(1, DOC, 5) is False
    assert manager._rooms.get((1, DOC, 5)) is room


async def test_two_writes_of_one_room_do_not_interleave() -> None:
    """A sweep and a disconnect can reach one room together.

    They take the room's write lock in turn, so the row ends up holding the
    later snapshot rather than whichever commit returns last.
    """
    manager = CollaborationManager()
    room = loaded_room(1, 5)
    manager._rooms[(1, DOC, 5)] = room
    room.apply_update(_an_update())

    concurrent: list[int] = []
    active = {"n": 0}

    class SlowWriteSession:
        async def exec(self, _statement):
            active["n"] += 1
            concurrent.append(active["n"])
            await asyncio.sleep(0.02)
            active["n"] -= 1
            return FakeExecResult(1)

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    await asyncio.gather(
        manager._write_room(room, SlowWriteSession()),
        manager._write_room(room, SlowWriteSession()),
    )

    assert max(concurrent) == 1
    assert room.is_dirty is False


def test_every_collaborative_kind_declares_where_its_body_lives() -> None:
    """A room reads and writes a body through the registry alone, so a kind
    that registered without one would open a socket that saves nowhere."""
    from app.services.tenant.collaborative_resources import (
        registered_types,
        resource_for,
    )

    kinds = registered_types()
    assert DOC in kinds and PAGE in kinds
    for kind in kinds:
        spec = resource_for(kind)
        assert spec.resource_type == kind
        # The column the body is in, and the Yjs columns beside it.
        assert hasattr(spec.model, spec.content_column)
        assert hasattr(spec.model, "yjs_state")
        assert hasattr(spec.model, "yjs_updated_at")
