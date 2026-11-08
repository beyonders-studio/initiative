"""The change log reaching the rooms watching it.

The sink is the only thing that puts a frame on the ``/events/updates`` bus, so
these pin what it will and will not send: the tenancy boundary it inherits from
the room key, the envelope staying identifiers-only, and the two ways it reads
the log covering for each other.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Self

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import SystemGuild
from app.models.platform.guild import CommunityRole
from app.models.tenant.event_outbox import EventOutbox
from app.services.content_sockets import RoomKey, guild_room, initiative_room, sockets
from app.services.tenant import room_sink
from app.testing import (
    create_comment,
    create_file,
    create_initiative_member,
    create_tag,
    create_task,
)
from app.testing.sockets import FakeWebSocket, settle, watch_events_bus

#: A socket belonging to nobody in particular. Rooms are otherwise recomputed
#: for whoever holds the socket when a roster they are on moves, so a test that
#: means "only the rooms I was constructed with" holds a socket no roster names.
NOBODY = 0


class _Watcher:
    """A socket in one room, brought up to the log on entry."""

    def __init__(
        self, guild_id: int, *initiative_ids: int, user_id: int = NOBODY
    ) -> None:
        self._guild_id = guild_id
        self._initiative_ids = initiative_ids
        self._user_id = user_id
        self.socket = FakeWebSocket()

    async def __aenter__(self) -> Self:
        room_sink._missed_hints = False
        watch_events_bus(
            self._guild_id,
            self._initiative_ids,
            self.socket,
            user_id=self._user_id,
        )
        await room_sink.process_room_sweep()
        await settle()
        return self

    async def __aexit__(self, *exc) -> None:
        sockets.leave(self.socket)  # type: ignore[arg-type]
        room_sink._delivered.pop(self._guild_id, None)

    async def catch_up(self) -> None:
        await room_sink.process_room_sweep()
        await settle()

    @property
    def changes(self) -> list[dict]:
        return [c for frame in self.socket.sent for c in frame.get("changes", [])]

    def named(self, resource_type: str) -> list[dict]:
        return [c for c in self.changes if c["resource"]["type"] == resource_type]


async def test_a_write_reaches_the_room_it_belongs_to(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project)
        await watcher.catch_up()

        tasks = watcher.named("tasks")
        assert tasks, f"the room heard nothing; got {watcher.changes}"
        assert tasks[-1]["resource"] == {"type": "tasks", "id": task.id}
        assert tasks[-1]["parents"] == [{"type": "projects", "id": a.project.id}]


async def test_the_frame_carries_identifiers_and_nothing_else(session, acting_user):
    """Identifiers, an action and the columns it touched, and nothing a reader
    would not fetch anyway."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project, title="Move the session")
        await create_comment(session, a.user, task=task, content="secret text")
        await watcher.catch_up()

        assert watcher.changes, "the room heard nothing"
        for change in watcher.changes:
            assert set(change) == {
                "resource",
                "parents",
                "initiative_id",
                "action",
                "changed",
            }
            assert change["initiative_id"] == a.initiative.id
            assert set(change["resource"]) == {"type", "id"}
            assert all(set(p) == {"type", "id"} for p in change["parents"])


async def test_a_comment_names_its_thread_and_the_project(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project)
        comment = await create_comment(session, a.user, task=task)
        await watcher.catch_up()

        comments = watcher.named("comments")
        assert comments, f"no comment change; got {watcher.changes}"
        assert comments[-1]["resource"]["id"] == comment.id
        assert comments[-1]["parents"] == [
            {"type": "tasks", "id": task.id},
            {"type": "projects", "id": a.project.id},
        ]


async def test_another_initiatives_room_hears_nothing(session, acting_user):
    """The room key is (guild, initiative), and the sink routes by it."""
    from app.testing import create_initiative

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    elsewhere = await create_initiative(session, a.guild, a.user)

    async with _Watcher(a.guild.id, elsewhere.id) as watcher:
        await create_task(session, a.project)
        await watcher.catch_up()

        assert watcher.named("tasks") == []


async def test_a_guild_wide_change_reaches_a_member_of_no_initiative(
    session, acting_user
):
    """A tag belongs to no initiative and every member can already read it, so
    it goes to the guild's sockets rather than to a room."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    async with _Watcher(a.guild.id) as watcher:
        tag = await create_tag(session, a.guild)
        await watcher.catch_up()

        tags = watcher.named("tags")
        assert tags, f"the guild heard nothing; got {watcher.changes}"
        assert tags[-1]["resource"] == {"type": "tags", "id": tag.id}


async def test_a_first_connect_is_told_nothing(session, acting_user):
    """Whoever just arrived fetched as they mounted; the log before that is not
    theirs to hear."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project)
    await create_file(session, a.initiative, a.user)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        assert watcher.changes == []


async def test_nothing_is_read_for_a_guild_nobody_is_watching(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project)

    room_sink._delivered.pop(a.guild.id, None)
    await room_sink.process_room_sweep()

    assert a.guild.id not in room_sink._delivered


async def test_what_is_remembered_is_pruned_to_the_window(session, acting_user):
    """The record of what has been sent is the window, so it cannot grow."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        await create_task(session, a.project)
        await watcher.catch_up()

        from sqlmodel import select

        from app.db.session import set_rls_context

        await set_rls_context(session, SystemGuild(a.guild.id))
        in_window = {
            row.id
            for row in await session.exec(
                select(EventOutbox).where(
                    EventOutbox.occurred_at
                    > datetime.now(UTC)
                    - timedelta(seconds=room_sink.SWEEP_WINDOW_SECONDS)
                )
            )
        }
        assert room_sink._delivered[a.guild.id] == in_window


async def test_leaving_drops_the_mark(session, acting_user):
    """So the next socket to arrive is brought up to the log's end rather than
    told everything that happened while nobody was looking."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id):
        assert a.guild.id in room_sink._delivered

    await room_sink.process_room_sweep()
    assert a.guild.id not in room_sink._delivered


async def test_the_same_change_is_not_sent_twice_by_the_sweep(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        await create_task(session, a.project)
        await watcher.catch_up()
        first = len(watcher.named("tasks"))
        assert first

        await watcher.catch_up()
        assert len(watcher.named("tasks")) == first


async def _txn_of(session, guild_id: int, resource_type: str, resource_id: int) -> int:
    """The transaction the log recorded one change under."""
    from sqlmodel import select

    from app.db.session import set_rls_context

    await set_rls_context(session, SystemGuild(guild_id))
    row = (
        await session.exec(
            select(EventOutbox)
            .where(EventOutbox.resource_type == resource_type)
            .where(EventOutbox.resource_id == resource_id)
            .order_by(EventOutbox.id.asc())
        )
    ).first()
    assert row is not None, f"nothing was logged for {resource_type} {resource_id}"
    return row.txn_id


async def test_a_change_below_one_already_sent_is_still_delivered(session, acting_user):
    """Outbox ids are handed out before commit, so "everything above the
    highest id sent" would step over a transaction that became visible late.

    Here the second change is delivered by its hint and the first one's hint is
    never raised — the reconnect case. The sweep has to go back for it, and to
    not repeat the one already sent.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        earlier = await create_task(session, a.project)
        later = await create_task(session, a.project)

        # Only the later transaction is announced.
        await room_sink.deliver(
            f"guild_{a.guild.id}:{await _txn_of(session, a.guild.id, 'tasks', later.id)}"
        )
        assert [c["resource"]["id"] for c in watcher.named("tasks")] == [later.id]

        await watcher.catch_up()

        sent = [c["resource"]["id"] for c in watcher.named("tasks")]
        assert earlier.id in sent, f"the earlier change was stepped over; got {sent}"
        assert sent.count(later.id) == 1, f"the announced change repeated; got {sent}"


async def test_a_hint_names_the_transaction_it_is_raised_for(session, acting_user):
    """The prompt path: no watermark, just the rows that transaction wrote."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project)

        await room_sink.deliver(
            f"guild_{a.guild.id}:{await _txn_of(session, a.guild.id, 'tasks', task.id)}"
        )

        assert [c["resource"]["id"] for c in watcher.named("tasks")] == [task.id]


async def test_a_gap_in_the_hints_tells_the_room_to_read_the_guild(
    session, acting_user
):
    """Hints reach only whoever is listening, and a transaction older than the
    window cannot be found by reading it. When the bus has come up again since
    the last pass, the room is told that much rather than a list of ids."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        await create_task(session, a.project)
        # The bus coming up is the notice that it was down.
        await room_sink.on_bus_connected()

        await watcher.catch_up()

        assert watcher.socket.sent[-1] == {"changes": [], "more": True}
        # And the ids are not also sent: the guild is being read again whole.
        assert watcher.named("tasks") == []


async def test_a_steady_bus_names_the_ids(session, acting_user):
    """The counterpart: no gap, so the frame is precise."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)

    async with _Watcher(a.guild.id, a.initiative.id) as watcher:
        task = await create_task(session, a.project)
        await watcher.catch_up()

        assert [c["resource"]["id"] for c in watcher.named("tasks")] == [task.id]
        assert all(not frame.get("more") for frame in watcher.socket.sent)


async def test_an_unreadable_hint_is_dropped() -> None:
    """Nothing on the bus is load-bearing enough to raise over."""
    await room_sink.deliver("not-a-schema")
    await room_sink.deliver("guild_x:1")
    await room_sink.deliver("guild_1:not-a-txn")


def test_a_transaction_too_large_to_name_says_so_instead() -> None:
    """A bulk write would otherwise send every id it touched to every socket."""
    rows = [
        EventOutbox(
            id=i,
            txn_id=1,
            actor_user_id=None,
            initiative_id=1,
            resource_type="tasks",
            resource_id=i,
            action="created",
            changed=[],
            parents=[],
        )
        for i in range(room_sink.MAX_CHANGES + 1)
    ]
    frame = room_sink._frame(rows)

    assert frame == {"changes": [], "more": True}


def test_one_row_written_repeatedly_is_one_change() -> None:
    """One change, naming every column any of the writes touched."""
    rows = [
        EventOutbox(
            id=i,
            txn_id=1,
            actor_user_id=None,
            initiative_id=1,
            resource_type="tasks",
            resource_id=4,
            action="updated",
            changed=changed,
            parents=[{"type": "projects", "id": 7}],
        )
        for i, changed in enumerate((["title"], ["status_id"], ["title"]), start=1)
    ]

    frame = room_sink._frame(rows)

    assert frame["changes"] == [
        {
            "resource": {"type": "tasks", "id": 4},
            "parents": [{"type": "projects", "id": 7}],
            "initiative_id": 1,
            "action": "updated",
            "changed": ["status_id", "title"],
        }
    ]


async def _age_the_log(session: AsyncSession, guild_id: int) -> None:
    """Push everything already in the log out of any reasonable gap."""
    from sqlalchemy import text

    from app.db.session import set_rls_context

    await set_rls_context(session, SystemGuild(guild_id))
    await session.exec(
        text("UPDATE event_outbox SET occurred_at = occurred_at - interval '1 day'")
    )
    await session.commit()


def _seated(guild_id: int, *initiative_ids: int) -> frozenset[RoomKey]:
    """The rooms an events-bus socket is given: its guild's, and each initiative's."""
    return frozenset(
        {guild_room(guild_id), *(initiative_room(guild_id, i) for i in initiative_ids)}
    )


async def test_a_socket_that_missed_something_is_told_so(session, acting_user):
    """The one question a reconnect asks: whether its rooms were sent anything.

    Asked of the rooms rather than of what the person may open, so a change the
    room would have carried says so even where the person's sharing has gone.
    Somebody outside the initiative hears only the guild's own.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    member, outside = _seated(a.guild.id, a.initiative.id), _seated(a.guild.id)
    await _age_the_log(session, a.guild.id)

    assert await room_sink.missed_while_away(a.guild.id, member, 5) is False

    await create_task(session, a.project)

    assert await room_sink.missed_while_away(a.guild.id, member, 5) is True
    assert await room_sink.missed_while_away(a.guild.id, outside, 5) is False

    await create_tag(session, a.guild)

    assert await room_sink.missed_while_away(a.guild.id, outside, 5) is True


async def test_a_change_older_than_the_gap_is_not_news(session, acting_user):
    """A tab away for a moment is not told about the hour before it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project)
    await _age_the_log(session, a.guild.id)

    seated = _seated(a.guild.id, a.initiative.id)
    assert await room_sink.missed_while_away(a.guild.id, seated, 5) is False


async def test_a_long_enough_gap_is_answered_without_reading(session, acting_user):
    """Past the bound the log cannot say, so the answer is the honest one."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _age_the_log(session, a.guild.id)

    seated = _seated(a.guild.id, a.initiative.id)
    away = room_sink.CATCHUP_MAX_SECONDS + 1
    assert await room_sink.missed_while_away(a.guild.id, seated, away) is True


async def test_a_new_member_hears_the_initiative_without_reconnecting(
    session, acting_user
):
    """A socket resolves its rooms once, at connect.

    Being added to an initiative is the one thing that changes what those
    rooms should be without anything about the session itself moving — so
    nothing would prompt the reconnect that fixes it.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    # In the guild with a tab open, and in no initiative: no rooms at all.
    async with _Watcher(a.guild.id, user_id=b.user.id) as watcher:
        await create_task(session, a.project)
        await watcher.catch_up()
        assert not watcher.named("tasks"), "heard an initiative it is not in"

        await create_initiative_member(session, a.initiative, b.user)
        await watcher.catch_up()

        await create_task(session, a.project)
        await watcher.catch_up()
        assert watcher.named("tasks"), f"heard nothing after joining; {watcher.changes}"


async def test_a_roster_change_does_not_evict_a_watcher(session, acting_user):
    """A socket can be in a room for a reason the roster does not show."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    # A guild admin reaches every initiative without being on any roster.
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)

    async with _Watcher(a.guild.id, a.initiative.id, user_id=admin.user.id) as watcher:
        await create_initiative_member(session, a.initiative, b.user)
        await watcher.catch_up()

        await create_task(session, a.project)
        await watcher.catch_up()
        assert watcher.named("tasks"), "the roster moving closed a room it did not open"
