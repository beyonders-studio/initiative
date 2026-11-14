"""The refresh trigger indexes what the registry declares.

These assert the seam between ``SEARCH_SOURCES`` and a real Postgres: that an
ordinary write lands in ``search_entries`` at all, that the row carries the
initiative and sharing identity the query layer will filter on, and that the
three shapes the design turns on — trash leaving the index, an unrelated update
costing nothing, and long text chunking — hold against the database rather than
against the rendering code.
"""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, select

from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.request_context import SystemGuild
from app.db.search_index import (
    COMMENT_PREVIEW_CHARS,
    NOT_SEARCHABLE,
    SEARCH_SOURCES,
    TOOL_OVERRIDES,
    addressable_tables,
    entity_types,
    render_guild_search_ddl,
)
from app.db.session import set_rls_context
from app.db.tenancy import INITIATIVE_SCOPED_TABLES
from app.models.platform.guild import CommunityRole
from app.models.tenant.search_entry import SearchEntry
from app.testing import (
    create_comment,
    create_file,
    create_project,
    create_tag,
    create_task,
    route_system,
)


async def _entries(
    session: AsyncSession,
    guild_id: int,
    entity_type: str,
    entity_id: int,
) -> list[SearchEntry]:
    """What the index holds, read with nobody asking — the sweep's own view."""
    await route_system(session, guild_id=guild_id)
    rows = await session.exec(
        select(SearchEntry)
        .where(
            SearchEntry.entity_type == entity_type,
            SearchEntry.entity_id == entity_id,
        )
        .order_by(SearchEntry.chunk_ix.asc())
    )
    return list(rows)


# --- registry -------------------------------------------------------------


def test_every_initiative_scoped_table_is_placed():
    """A new content table is searchable or says why not — never silently
    absent, which would ship a tool no one can find."""
    placed = set(SEARCH_SOURCES) | set(NOT_SEARCHABLE)
    # Junctions carry no id to address and no text of their own, so they are
    # out by construction rather than by 22 entries saying the same thing.
    addressable = addressable_tables(SQLModel.metadata)
    missing = (set(INITIATIVE_SCOPED_TABLES) & addressable) - placed
    assert not missing, (
        f"add to SEARCH_SOURCES or NOT_SEARCHABLE in app/db/search_index.py: "
        f"{sorted(missing)}"
    )


def test_a_table_is_not_placed_twice():
    assert not (set(SEARCH_SOURCES) & set(NOT_SEARCHABLE))


def test_entity_types_are_unique():
    values = [s.entity_type for s in SEARCH_SOURCES.values()]
    assert len(values) == len(set(values))


def test_update_trigger_carries_a_when_clause():
    """The clause is the write-path design: an update touching none of the
    indexed columns never enters the function."""
    ddl = render_guild_search_ddl()
    block = next(b for b in ddl.split("\n\n") if "search_task_upd" in b)
    assert "FOR EACH ROW WHEN (" in block
    assert "OLD.title IS DISTINCT FROM NEW.title" in block
    # ...and the insert trigger cannot carry one (OLD is not bound on INSERT).
    ins = next(b for b in ddl.split("\n\n") if "search_task_ins" in b)
    assert "WHEN (" not in ins


def test_comments_are_the_one_source_a_caller_has_to_ask_for():
    """Everything else answers a query that names no types. Comments are the
    highest-volume table in a busy guild, so reaching them is a decision."""
    assert set(entity_types()) - set(entity_types(default_scope_only=True)) == {
        SearchEntityType.comment
    }


def test_the_enum_and_the_registry_name_the_same_set():
    """Neither can grow a member alone: the enum is what the API accepts, the
    registry is what is actually indexed."""
    assert set(entity_types()) == set(SearchEntityType)


def test_every_tool_is_searchable_under_its_own_name():
    """A tool's rows are indexed under the tool's own name, which is what lets
    the enum derive from ``Tool`` instead of restating it."""
    for tool in Tool:
        assert SearchEntityType(tool.value) in set(entity_types())


# --- the trigger ----------------------------------------------------------


async def test_a_comment_on_a_task_is_shared_as_its_project(session, acting_user):
    """A comment hangs off exactly one parent, and is reached by whoever can
    reach that parent. A task is shared as part of its project, so that is the
    gate a comment on one carries."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="vendor renewal")
    comment = await create_comment(
        session, a.user, task=task, content="the renewal terms changed in March"
    )

    rows = await _entries(session, a.guild.id, "comment", comment.id)
    assert rows, "commenting produced no search entry"
    row = rows[0]
    assert row.dac_tool == Tool.project.value
    assert row.dac_id == a.project.id
    assert row.initiative_id == a.initiative.id
    # The whole comment is searchable; the title is the opening it is shown by.
    assert "renewal terms changed" in (row.body or "")
    assert row.title == "the renewal terms changed in March"


async def test_a_comment_on_a_file_is_shared_as_that_file(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    file = await create_file(session, a.initiative, a.user)
    comment = await create_comment(
        session, a.user, file=file, content="second draft reads better"
    )

    rows = await _entries(session, a.guild.id, "comment", comment.id)
    assert rows
    assert rows[0].dac_tool == Tool.file.value
    assert rows[0].dac_id == file.id


async def test_moving_a_task_moves_the_comments_on_it(session, acting_user):
    """A comment's gate is derived from its task's project, and a task can
    move. The comment row does not change when it does, so nothing would
    rewrite its entry — leaving searchable text answering to the project it
    used to be under."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    elsewhere = await create_project(session, a.initiative, a.user, name="Elsewhere")
    task = await create_task(session, a.project)
    comment = await create_comment(session, a.user, task=task, content="ordered timber")

    task.project_id = elsewhere.id  # ty: ignore[invalid-assignment] — persisted
    session.add(task)
    await session.commit()

    rows = await _entries(session, a.guild.id, "comment", comment.id)
    assert rows, "the comment lost its entry when its task moved"
    assert rows[0].dac_id == elsewhere.id


async def test_a_long_comment_is_shown_by_its_opening(session, acting_user):
    """Storing the whole of one would put an essay where a name goes."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)
    comment = await create_comment(session, a.user, task=task, content="x" * 500)

    rows = await _entries(session, a.guild.id, "comment", comment.id)
    assert len(rows[0].title) == COMMENT_PREVIEW_CHARS
    assert "x" * 500 in (rows[0].body or "")


async def test_creating_a_task_is_indexed(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="vendor renewal terms")

    rows = await _entries(session, a.guild.id, "task", task.id)
    assert rows, "creating a task produced no search entry"
    row = rows[0]
    assert row.title == "vendor renewal terms"
    assert row.initiative_id == a.initiative.id
    # A task is governed by its project's sharing, not its own id.
    assert row.dac_tool == "project"
    assert row.dac_id == a.project.id


async def test_the_entry_is_full_text_searchable(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="quarterly vendor renewal")

    await set_rls_context(session, SystemGuild(a.guild.id))
    found = await session.exec(
        text(
            "SELECT title FROM search_entries "
            "WHERE tsv @@ websearch_to_tsquery('simple', :q)"
        ).bindparams(q="vendor renewal")
    )
    assert [r[0] for r in found] == ["quarterly vendor renewal"]


async def test_renaming_reindexes_in_place(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="before")

    task.title = "after"
    session.add(task)
    await session.commit()

    rows = await _entries(session, a.guild.id, "task", task.id)
    assert [r.title for r in rows] == ["after"]


async def test_soft_delete_removes_it_from_the_index(session, acting_user):
    """Trash is browsed through the trash surface, not found by searching."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="gone")
    assert await _entries(session, a.guild.id, "task", task.id)

    from datetime import datetime

    task.deleted_at = datetime.now(UTC)
    session.add(task)
    await session.commit()

    assert await _entries(session, a.guild.id, "task", task.id) == []


async def test_a_guild_level_tag_is_indexed_without_an_initiative(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin)
    tag = await create_tag(session, a.guild, name="urgent")

    rows = await _entries(session, a.guild.id, "tag", tag.id)
    assert rows, "creating a tag produced no search entry"
    # Guild-level vocabulary: no initiative to gate on, and no sharing gate.
    assert rows[0].initiative_id is None
    assert rows[0].dac_tool is None


async def test_long_text_is_chunked(session, acting_user):
    """Chunking is a length rule: the cap cannot be reached because a row's
    text is bounded by construction."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    body = " ".join(f"word{n}" for n in range(6000))
    project = await create_project(
        session, a.initiative, a.user, name="big", description=body
    )

    rows = await _entries(session, a.guild.id, "project", project.id)
    assert len(rows) > 1, "a long description produced a single chunk"
    assert [r.chunk_ix for r in rows] == list(range(len(rows)))
    # Every chunk carries the title, so a title match ranks the entity whichever
    # chunk it lands in.
    assert {r.title for r in rows} == {"big"}


async def test_short_text_is_exactly_one_chunk(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    project = await create_project(
        session, a.initiative, a.user, name="small", description="one line"
    )
    rows = await _entries(session, a.guild.id, "project", project.id)
    assert len(rows) == 1
    assert rows[0].chunk_ix == 0


async def test_a_guild_member_outside_the_initiative_sees_nothing(
    session, acting_user, reading_as
):
    """The initiative gate this table registers, proven against the database.

    A guild member who is not in the initiative gets no rows — the same answer
    the content tables give, from the same ``initiative_access`` call.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    # Both actors up front: reading routes the session into a guild role, which
    # the factories cannot run under.
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    task = await create_task(session, a.project, title="quarterly vendor renewal")

    assert await _entries(session, a.guild.id, "task", task.id)
    reader = await reading_as(outsider.user.id, a.guild.id)
    assert (
        list(
            await reader.exec(
                select(SearchEntry).where(
                    SearchEntry.entity_type == "task",
                    SearchEntry.entity_id == task.id,
                )
            )
        )
        == []
    )


async def test_a_guild_level_tag_is_visible_to_any_member(
    session, acting_user, reading_as
):
    """The NULL-initiative leg: guild vocabulary every member already sees in
    every picker is not hidden from them in search."""
    a = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    tag = await create_tag(session, a.guild, name="urgent")

    reader = await reading_as(member.user.id, a.guild.id)
    rows = await reader.exec(
        select(SearchEntry).where(
            SearchEntry.entity_type == "tag", SearchEntry.entity_id == tag.id
        )
    )
    assert [r.title for r in rows] == ["urgent"]


def test_each_source_gates_on_a_column_that_points_at_its_tool():
    """The declared sharing identity has to name the resource that governs the
    row — a task by its project, a calendar event by its calendar.

    Only ``task`` was exercised end to end; this covers every source
    structurally, so a new one naming the wrong column (``counter_group_id``
    where ``calendar_id`` was meant) fails here rather than gating search against a
    resource that has nothing to do with the row.
    """
    for table, source in sorted(SEARCH_SOURCES.items()):
        if source.dac_tool is None:
            assert source.dac_id is None, (
                f"{table} declares dac_id without a dac_tool to test it against"
            )
            continue
        tool_table = source.dac_tool.plural
        if source.dac_id is None:
            # The row IS the shared resource.
            assert table == tool_table, (
                f"{table} gates on its own id but is not {tool_table}"
            )
            continue
        column = SQLModel.metadata.tables[table].columns[source.dac_id]
        targets = {fk.column.table.name for fk in column.foreign_keys}
        assert tool_table in targets, (
            f"{table}.{source.dac_id} does not reference {tool_table}; "
            f"search would gate it against the wrong resource"
        )


async def test_moving_a_task_regates_it(session, acting_user):
    """The sharing identity is stored, so a row changing parents has to be
    rewritten or it would keep answering to the old one."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    other = await create_project(session, a.initiative, a.user, name="elsewhere")
    assert other.id is not None
    task = await create_task(session, a.project, title="moving")
    assert (await _entries(session, a.guild.id, "task", task.id))[0].dac_id == (
        a.project.id
    )

    task.project_id = other.id
    session.add(task)
    await session.commit()

    assert (await _entries(session, a.guild.id, "task", task.id))[0].dac_id == other.id


def test_every_tool_is_searchable_without_being_listed():
    """A tool's own rows are indexed because it is a tool.

    The six entries are derived from ``Tool``, so this fails the moment a
    seventh is added and its table is not reachable under the same rule.
    """
    for tool in Tool:
        source = SEARCH_SOURCES[tool.plural]
        assert source.entity_type.value == tool.value
        assert source.dac_tool is tool


def test_a_tool_that_overrides_nothing_takes_the_shared_shape():
    """Only what differs is written down."""
    plain = [t for t in Tool if t not in TOOL_OVERRIDES]
    assert plain, "the derivation is pointless if every tool overrides it"
    for tool in plain:
        source = SEARCH_SOURCES[tool.plural]
        assert source.title == "name"
        assert source.body == ("description",)
        assert source.body_sql is None
