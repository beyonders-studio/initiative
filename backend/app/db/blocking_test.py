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
from typing import Any

import pytest
import sqlalchemy as sa
from httpx2 import AsyncClient
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tool_set import BUILTIN_TOOLS
from app.db.blocking import OPEN_WHEN, blocking_kinds, open_expr
from app.db.plugin_tools import DECLARED
from app.db.reference_targets import resolve_many
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import TaskStatusCategory
from app.testing import add_counter, install_tool_plugin
from app.testing.factories import (
    create_calendar,
    create_calendar_event,
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
        assert open_expr(tables[table_name]) is not None


def test_every_blocking_kind_is_something_an_edge_may_name():
    """A rule for a kind no relationship can reach would never be consulted."""
    for kind, _table, _expr in blocking_kinds(BUILTIN_TOOLS):
        assert kind in BUILTIN_TOOLS.endpoint_codes


def test_a_kind_with_no_rule_has_no_opinion():
    tables = {
        key.split(".")[-1]: table for key, table in SQLModel.metadata.tables.items()
    }
    assert "files" not in OPEN_WHEN
    # NULL, not false: "this never finishes" is not the same claim as "this is
    # finished", and only one of them should keep a blocker off a count.
    assert open_expr(tables["files"]).compile().string == "NULL"


def _declared_item(open_while: dict[str, Any]) -> sa.Table:
    """An item table of a tool plug-in, as ``app.db.plugin_tools`` builds one:
    a column per declared field, its kind in the column's ``info``."""
    return sa.Table(
        "p_uid_item",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("count", sa.Numeric, info={"field": "counter"}),
        sa.Column("max", sa.Numeric, info={"field": "number"}),
        sa.Column("done", sa.Boolean, info={"field": "checkbox"}),
        sa.Column("stage", sa.Text, info={"field": "select"}),
        sa.Column("due", sa.Date, info={"field": "date"}),
        sa.Column("ends", sa.DateTime(timezone=True), info={"field": "datetime"}),
        info={DECLARED: {"key": "item", "open_while": open_while}},
    )


@pytest.mark.parametrize(
    ("open_while", "sql", "params"),
    [
        ({"field": "count", "below": {"field": "max"}}, "count < max", {}),
        (
            {"field": "count", "at_least": 5},
            "count >= :count_1",
            {"count_1": 5},
        ),
        ({"field": "max", "not_equals": 0}, "max != :max_1", {"max_1": 0}),
        ({"field": "done", "is": False}, "done IS NOT true", {}),
        ({"field": "done", "is": True}, "done IS true", {}),
        (
            {"field": "stage", "in": ["todo", "doing"]},
            "stage IN (:stage_1_1, :stage_1_2)",
            {"stage_1_1": "todo", "stage_1_2": "doing"},
        ),
        ({"field": "due", "not_passed": True}, "due >= CURRENT_DATE", {}),
        ({"field": "ends", "not_passed": True}, "ends > now()", {}),
    ],
)
def test_a_declared_open_while_reads_as_its_condition(open_while, sql, params):
    """A tool plug-in's item says when it is still outstanding, one condition
    on one field, and every value it compares with is a bound parameter."""
    compiled = open_expr(_declared_item(open_while)).compile(
        compile_kwargs={"render_postcompile": True}
    )
    assert compiled.string.replace("p_uid_item.", "") == sql
    assert compiled.params == params


def test_an_item_that_declares_nothing_has_no_opinion():
    table = _declared_item({})
    table.info[DECLARED].pop("open_while")
    assert open_expr(table).compile().string == "NULL"


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


async def test_a_tool_plugins_item_blocks_while_its_declaration_holds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Counters declares a counter open while its count is below its maximum,
    so a task depending on one is held up until the count reaches it."""
    seat = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    await install_tool_plugin(client, session, seat)
    tools, _group, counter = await add_counter(
        session, seat.guild.id, seat.initiative.id, count=3, max=5
    )
    (tool,) = tools.installed
    ((item_kind, item, _rule),) = [
        arm for arm in blocking_kinds(tools) if arm[1].name == tool.items[0].name
    ]
    task = await create_task(session, seat.project)
    response = await client.post(
        seat.g("/relationships/"),
        headers=seat.headers,
        json={
            "source": {"type": "task", "id": task.id},
            "relationship_type": RelationshipType.depends_on.value,
            "target": {"type": item_kind, "id": counter},
        },
    )
    assert response.status_code == 201, response.text

    response = await client.get(seat.g(f"/tasks/{task.id}"), headers=seat.headers)
    assert response.json()["blocked_by_open_count"] == 1, response.text

    await route_session_to_guild(session, seat.guild.id)
    await session.exec(sa.update(item).where(item.c.id == counter).values(count=5))
    await session.commit()
    response = await client.get(seat.g(f"/tasks/{task.id}"), headers=seat.headers)
    assert response.json()["blocked_by_open_count"] == 0, response.text
    links = await client.get(
        seat.g("/relationships/"),
        headers=seat.headers,
        params={"entity": f"task:{task.id}"},
    )
    assert [link["other"]["is_open"] for link in links.json()] == [False]
