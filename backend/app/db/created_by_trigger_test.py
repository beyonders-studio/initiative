"""The database fills in who made a row.

``public.fn_set_created_by`` is a BEFORE INSERT trigger on every guild-content
table, reading ``app.current_user_id`` — the GUC the request already sets for
RLS. Doing it here rather than in the ORM is what makes it unconditional: the
same shape as the ``fn_*_set_guild_id`` triggers beside it, and it covers writes
that never pass through a flush.
"""

from datetime import datetime, timezone

from sqlalchemy import insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.counter import Counter, CounterGroup
from app.testing.factories import (
    create_counter,
    create_counter_group,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
)
from app.testing import route_as, route_system


async def _workspace(session: AsyncSession):
    """A guild with a counter group in it, plus a second admin to act as:
    somebody who may write the group, so the trigger is the only question."""
    creator = await create_user(session)
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild=guild, creator=creator)
    group = await create_counter_group(session, initiative=initiative, creator=creator)
    actor = await create_user(session)
    await create_guild_membership(
        session, user=actor, guild=guild, role=CommunityRole.admin
    )
    return guild, group, actor


async def _route(session: AsyncSession, guild_id: int, user_id: int | None) -> None:
    session.expunge_all()
    if user_id is None:
        await route_system(session, guild_id=guild_id)
    else:
        await route_as(session, user_id=user_id, guild_id=guild_id)


async def _reload(session: AsyncSession, counter_id: int) -> Counter:
    """Read the row back. The trigger writes to the row, not to the identity
    map, so a freshly flushed object still holds None until it is refreshed."""
    session.expunge_all()
    return (await session.exec(select(Counter).where(Counter.id == counter_id))).one()


async def test_insert_records_the_acting_user(session: AsyncSession):
    guild, group, actor = await _workspace(session)

    await _route(session, guild.id, actor.id)
    counter = await create_counter(
        session, group, name="check the wiring", commit=False
    )
    await session.flush()

    assert (await _reload(session, counter.id)).created_by == actor.id


async def test_a_write_that_skips_the_orm_is_stamped_too(session: AsyncSession):
    """The reason this is a trigger and not a flush hook.

    A bulk ``insert()`` never reaches the ORM's unit of work, so an app-layer
    hook could not see it. The database does not care how the row arrived.
    """
    guild, group, actor = await _workspace(session)

    await _route(session, guild.id, actor.id)
    # A Core insert also skips the Python-side column defaults, so the
    # timestamps are supplied here; ``created_by`` is the database's job.
    now = datetime.now(timezone.utc)
    await session.exec(
        insert(Counter).values(
            counter_group_id=group.id,
            name="written by statement",
            created_at=now,
            updated_at=now,
        )
    )

    row = (
        await session.exec(
            select(Counter).where(Counter.name == "written by statement")
        )
    ).one()
    assert row.created_by == actor.id


async def test_an_explicit_author_is_kept(session: AsyncSession):
    """A caller restoring original authorship (backup import) keeps it."""
    guild, group, actor = await _workspace(session)
    original = await create_user(session)

    await _route(session, guild.id, actor.id)
    counter = await create_counter(
        session, group, name="imported", created_by=original.id, commit=False
    )
    await session.flush()

    assert (await _reload(session, counter.id)).created_by == original.id


async def test_an_edit_by_someone_else_leaves_the_author(session: AsyncSession):
    """Authorship is a historical fact: the trigger is INSERT-only."""
    guild, group, author = await _workspace(session)
    editor = await create_user(session)
    await create_guild_membership(
        session, user=editor, guild=guild, role=CommunityRole.admin
    )

    await _route(session, guild.id, author.id)
    counter = await create_counter(session, group, name="first draft", commit=False)
    await session.flush()
    counter_id = counter.id

    await _route(session, guild.id, editor.id)
    row = await _reload(session, counter_id)
    row.name = "second draft"
    await session.flush()

    assert (await _reload(session, counter_id)).created_by == author.id


async def test_a_system_session_stamps_nothing(session: AsyncSession):
    """Background work and seeding have no one to name, so they name no one."""
    guild, group, _ = await _workspace(session)

    await _route(session, guild.id, None)
    counter = await create_counter(
        session, group, name="swept up by a job", commit=False
    )
    await session.flush()

    assert (await _reload(session, counter.id)).created_by is None


async def test_content_a_plugin_writes_may_name_no_author(session: AsyncSession):
    """A plug-in acting as its community has no one to name either, on the tool
    tables its scopes can write."""
    guild, group, _ = await _workspace(session)

    await _route(session, guild.id, None)
    written = CounterGroup(
        initiative_id=group.initiative_id, name="written by a plug-in"
    )
    session.add(written)
    await session.flush()
    session.expunge_all()

    reloaded = (
        await session.exec(select(CounterGroup).where(CounterGroup.id == written.id))
    ).one()
    assert reloaded.created_by is None
