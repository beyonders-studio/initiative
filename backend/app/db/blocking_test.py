"""What each kind says about still being in the way.

:data:`~app.db.blocking.OPEN_WHEN` is a set of judgement calls, so these pin the
calls themselves rather than the mechanism: a recurring event never blocks
however it is dated, a counter with no target has no finish line to reach, and a
kind nobody wrote a rule for says nothing at all rather than saying "no".

The registry names columns as strings, which is the only way a table-keyed
registry can name them. The unit half is what fails on a rename instead of a
request failing at runtime.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import ENDPOINT_KINDS
from app.core.search import SearchEntityType
from app.db.blocking import OPEN_WHEN, blocking_kinds, open_expr
from app.db.reference_targets import resolve_many
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import TaskStatusCategory
from app.testing.factories import (
    create_calendar,
    create_calendar_event,
    create_counter,
    create_counter_group,
    create_file,
    create_task,
)
from app.testing.schema_harness import route_session_to_guild

# ---------------------------------------------------------------------------
# The registry itself
# ---------------------------------------------------------------------------


def test_every_rule_names_columns_that_exist():
    tables = {
        key.split(".")[-1]: table for key, table in SQLModel.metadata.tables.items()
    }
    for table_name in OPEN_WHEN:
        assert table_name in tables, f"{table_name} is not a table"
        # Building the expression is the check: a renamed column raises here.
        assert open_expr(table_name, tables[table_name]) is not None


def test_every_blocking_kind_is_something_an_edge_may_name():
    """A rule for a kind no relationship can reach would never be consulted."""
    for kind, _table, _expr in blocking_kinds():
        assert SearchEntityType(kind) in ENDPOINT_KINDS


def test_a_kind_with_no_rule_has_no_opinion():
    tables = {
        key.split(".")[-1]: table for key, table in SQLModel.metadata.tables.items()
    }
    assert "files" not in OPEN_WHEN
    # NULL, not false: "this never finishes" is not the same claim as "this is
    # finished", and only one of them should keep a blocker off a count.
    assert open_expr("files", tables["files"]).compile().string == "NULL"


# ---------------------------------------------------------------------------
# What the wire actually carries
# ---------------------------------------------------------------------------


async def _is_open(
    session: AsyncSession, kind: SearchEntityType, entity_id: int, user_id: int
):
    """What the resolver reports, which is what ``RelatedEnd.is_open`` carries."""
    found = await resolve_many(session, kind, [entity_id], user_id=user_id)
    return found[entity_id].is_open


async def test_a_task_is_open_until_it_is_done(session: AsyncSession, acting_user):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    todo = await create_task(
        session, a.project, status_category=TaskStatusCategory.todo
    )
    done = await create_task(
        session, a.project, status_category=TaskStatusCategory.done
    )

    await route_session_to_guild(session, a.guild.id)
    assert await _is_open(session, SearchEntityType.task, todo.id, a.user.id) is True
    assert await _is_open(session, SearchEntityType.task, done.id, a.user.id) is False


async def test_an_event_blocks_until_it_has_passed(session: AsyncSession, acting_user):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    calendar = await create_calendar(session, a.initiative, a.user)
    now = datetime.now(UTC)
    upcoming = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=now + timedelta(hours=1),
        end_at=now + timedelta(hours=2),
    )
    past = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=now - timedelta(hours=2),
        end_at=now - timedelta(hours=1),
    )

    await route_session_to_guild(session, a.guild.id)
    assert (
        await _is_open(session, SearchEntityType.calendar_event, upcoming.id, a.user.id)
        is True
    )
    assert (
        await _is_open(session, SearchEntityType.calendar_event, past.id, a.user.id)
        is False
    )


async def test_a_recurring_event_has_no_opinion(session: AsyncSession, acting_user):
    """It has no last occurrence for an end date to be the end of. NULL rather
    than "finished", so a surface that dims a dealt-with blocker does not strike
    through an event that recurs forever."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    calendar = await create_calendar(session, a.initiative, a.user)
    now = datetime.now(UTC)
    event = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=now + timedelta(hours=1),
        end_at=now + timedelta(hours=2),
        recurrence="FREQ=WEEKLY",
    )

    await route_session_to_guild(session, a.guild.id)
    assert (
        await _is_open(session, SearchEntityType.calendar_event, event.id, a.user.id)
        is None
    )


async def test_a_counter_blocks_until_it_reaches_its_target(
    session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    short = await create_counter(session, group, count=3, max=10)
    reached = await create_counter(session, group, count=10, max=10)

    await route_session_to_guild(session, a.guild.id)
    assert (
        await _is_open(session, SearchEntityType.counter, short.id, a.user.id) is True
    )
    assert (
        await _is_open(session, SearchEntityType.counter, reached.id, a.user.id)
        is False
    )


async def test_a_counter_with_no_target_has_no_finish_line(
    session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)
    counter = await create_counter(session, group, count=3, max=None)

    await route_session_to_guild(session, a.guild.id)
    assert (
        await _is_open(session, SearchEntityType.counter, counter.id, a.user.id) is None
    )


async def test_a_project_is_open_until_its_work_is_done(
    session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task(session, a.project, status_category=TaskStatusCategory.todo)

    await route_session_to_guild(session, a.guild.id)
    assert (
        await _is_open(session, SearchEntityType.project, a.project.id, a.user.id)
        is True
    )


async def test_a_project_closes_when_every_task_is_done(
    session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task(session, a.project, status_category=TaskStatusCategory.done)
    await create_task(session, a.project, status_category=TaskStatusCategory.done)

    await route_session_to_guild(session, a.guild.id)
    assert (
        await _is_open(session, SearchEntityType.project, a.project.id, a.user.id)
        is False
    )


async def test_an_empty_project_has_not_finished(session: AsyncSession, acting_user):
    """ "All of them are done" is vacuously true of no tasks at all, and a
    project nobody has filled in is the one thing it certainly is not."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    await route_session_to_guild(session, a.guild.id)
    assert (
        await _is_open(session, SearchEntityType.project, a.project.id, a.user.id)
        is True
    )


async def test_an_archived_task_neither_holds_a_project_open_nor_closes_it(
    session: AsyncSession, acting_user
):
    """Archived work is not work anybody is waiting on. A project holding only
    archived tasks has still never finished anything."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    done = await create_task(
        session, a.project, status_category=TaskStatusCategory.done
    )
    shelved = await create_task(
        session, a.project, status_category=TaskStatusCategory.todo
    )
    await route_session_to_guild(session, a.guild.id)
    shelved.archived_at = datetime.now(UTC)
    session.add(shelved)
    await session.commit()

    # The archived to-do no longer keeps it open; the done one closes it.
    assert (
        await _is_open(session, SearchEntityType.project, a.project.id, a.user.id)
        is False
    )
    assert done.completed_at is not None


async def test_a_file_never_answers(session: AsyncSession, acting_user):
    """Nothing on a file says when it stops holding something up."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_file(session, a.initiative, a.user)

    await route_session_to_guild(session, a.guild.id)
    assert await _is_open(session, SearchEntityType.file, doc.id, a.user.id) is None
