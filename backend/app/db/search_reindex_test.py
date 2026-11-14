"""Content that predates the index gets indexed.

The refresh trigger only sees writes that happen after it exists, so a guild's
existing work would be absent from search until each row was next touched. The
sweep walks each source table and writes the same entries the trigger would,
and a generation marker on the guild's ``search_entries`` records what it was
last swept for.
"""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import text
from sqlmodel import select

from app.db import cohorts, schema_provisioning
from app.db import session as db_session
from app.db.request_context import SystemGuild
from app.db.schema_provisioning import backfill_guild_search, reindex_guild_search
from app.db.search_index import search_generation
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.tenant.search_entry import SearchEntry
from app.testing import create_project, create_tag, create_task


async def _entries(session, guild_id: int, entity_type: str) -> list[SearchEntry]:
    await set_rls_context(session, SystemGuild(guild_id))
    return list(
        await session.exec(
            select(SearchEntry).where(SearchEntry.entity_type == entity_type)
        )
    )


async def _reindex(guild_id: int) -> int:
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        return await reindex_guild_search(session, guild_id)


async def _wipe(guild_id: int) -> None:
    """Leave the guild looking like one whose content predates the index.

    Through the provisioning engine: it owns these tables, which commenting on
    them requires.
    """
    async with db_session.provisioning_engine.begin() as conn:
        await conn.exec_driver_sql(f'DELETE FROM "guild_{guild_id}".search_entries')
        await conn.exec_driver_sql(
            f'COMMENT ON TABLE "guild_{guild_id}".search_entries IS NULL'
        )


async def test_it_indexes_content_that_predates_the_index(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="vendor renewal terms")
    tag = await create_tag(session, a.guild, name="urgent")
    await _wipe(a.guild.id)
    assert await _entries(session, a.guild.id, "task") == []

    written = await _reindex(a.guild.id)
    assert written > 0

    tasks = await _entries(session, a.guild.id, "task")
    assert [r.title for r in tasks if r.entity_id == task.id] == [
        "vendor renewal terms"
    ]
    tags = await _entries(session, a.guild.id, "tag")
    assert [r.title for r in tags if r.entity_id == tag.id] == ["urgent"]


async def test_the_swept_rows_carry_the_same_identity_the_trigger_writes(
    session, acting_user
):
    """A swept row and a trigger-written row must be interchangeable, or search
    would rank and gate them differently."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="quarterly report")
    before = next(
        r for r in await _entries(session, a.guild.id, "task") if r.entity_id == task.id
    )
    fields = (before.initiative_id, before.dac_tool, before.dac_id, before.title)

    await _wipe(a.guild.id)
    await _reindex(a.guild.id)

    after = next(
        r for r in await _entries(session, a.guild.id, "task") if r.entity_id == task.id
    )
    assert (after.initiative_id, after.dac_tool, after.dac_id, after.title) == fields


async def test_soft_deleted_content_is_not_swept_in(session, acting_user):
    from datetime import datetime

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="trashed")
    task.deleted_at = datetime.now(UTC)
    session.add(task)
    await session.commit()
    await _wipe(a.guild.id)

    await _reindex(a.guild.id)
    assert [
        r for r in await _entries(session, a.guild.id, "task") if r.entity_id == task.id
    ] == []


async def test_a_current_guild_is_left_alone(session, acting_user):
    """The marker is what keeps a boot from rewriting every guild's index."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="already indexed")
    await _wipe(a.guild.id)

    first = await _reindex(a.guild.id)
    assert first > 0
    second = await _reindex(a.guild.id)
    assert second == 0, "a guild already at the current generation was swept again"


async def test_the_marker_records_the_generation(session, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_project(session, a.initiative, a.user, name="p")
    await _wipe(a.guild.id)
    await _reindex(a.guild.id)

    await set_rls_context(session, SystemGuild(a.guild.id))
    marker = (
        await session.exec(
            text("SELECT obj_description(to_regclass(:t), 'pg_class')").bindparams(
                t=f"guild_{a.guild.id}.search_entries"
            )
        )
    ).one()[0]
    assert marker == search_generation()


def test_every_reindex_statement_locks_the_rows_it_rewrites():
    """The sweep reads a row's text and replaces that row's entries.

    Without the lock those are two moments: a write landing between them is
    replaced by what the batch read beforehand, and the index keeps the older
    text until the row is next touched. Locking makes the write the row's
    current state by definition.
    """
    from app.db.search_index import reindex_plan

    for entity_type, statement in reindex_plan():
        assert statement.rstrip().endswith("FOR UPDATE"), (
            f"the {entity_type} reindex statement does not lock its rows"
        )


async def test_a_write_during_the_sweep_wins(session, acting_user):
    """A trigger write is always newer than what a sweep batch read, so the
    sweep must not put the older text back."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="original")
    await _wipe(a.guild.id)

    # The ordinary path: a write lands, then the sweep runs over it.
    task.title = "edited"
    session.add(task)
    await session.commit()

    await _reindex(a.guild.id)

    rows = [
        r for r in await _entries(session, a.guild.id, "task") if r.entity_id == task.id
    ]
    assert [r.title for r in rows] == ["edited"]


async def test_the_boot_sweep_reindexes_each_stale_guild(
    session, acting_user, monkeypatch
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="swept at boot")
    await _wipe(a.guild.id)

    assert await backfill_guild_search() > 0
    assert [
        r.title
        for r in await _entries(session, a.guild.id, "task")
        if r.entity_id == task.id
    ] == ["swept at boot"]

    # Once current, the next boot visits nothing.
    visited: list[int] = []

    async def reindex(_session, guild_id):
        visited.append(guild_id)
        return 0

    monkeypatch.setattr(schema_provisioning, "reindex_guild_search", reindex)
    await backfill_guild_search()
    assert visited == []
