"""The database fills in who made a row.

``public.fn_set_author`` is a BEFORE INSERT trigger on every guild-content
table, reading ``app.current_user_id`` — the GUC the request already sets for
RLS. Doing it here rather than in the ORM is what makes it unconditional: the
same shape as the ``fn_*_set_guild_id`` triggers beside it, and it covers writes
that never pass through a flush.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant._mixins import ActorKind
from app.models.tenant.wiki import Wiki
from app.testing import route_as, route_system
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
)


async def _workspace(session: AsyncSession):
    """A guild with an initiative in it, plus a second admin to act as:
    somebody who may write there, so the trigger is the only question."""
    creator = await create_user(session)
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild=guild, creator=creator)
    actor = await create_user(session)
    await create_guild_membership(
        session, user=actor, guild=guild, role=CommunityRole.admin
    )
    return guild, initiative.id, actor


async def _route(session: AsyncSession, guild_id: int, user_id: int | None) -> None:
    session.expunge_all()
    if user_id is None:
        await route_system(session, guild_id=guild_id)
    else:
        await route_as(session, user_id=user_id, guild_id=guild_id)


async def _add(session: AsyncSession, initiative_id: int, name: str, **row) -> int:
    """A wiki written through the ORM, flushed. Its timestamps are the
    model's; who made it is the database's to say unless ``row`` says."""
    now = datetime.now(UTC)
    wiki = Wiki(
        initiative_id=initiative_id, name=name, created_at=now, updated_at=now, **row
    )
    session.add(wiki)
    await session.flush()
    assert wiki.id is not None
    return wiki.id


async def _reload(session: AsyncSession, wiki_id: int) -> Wiki:
    """Read the row back. The trigger writes to the row, not to the identity
    map, so a freshly flushed object still holds None until it is refreshed."""
    session.expunge_all()
    return (await session.exec(select(Wiki).where(Wiki.id == wiki_id))).one()


async def test_insert_records_the_acting_user(session: AsyncSession):
    guild, initiative_id, actor = await _workspace(session)

    await _route(session, guild.id, actor.id)
    wiki_id = await _add(session, initiative_id, "check the wiring")

    assert (await _reload(session, wiki_id)).created_by == actor.id


async def test_a_write_that_skips_the_orm_is_stamped_too(session: AsyncSession):
    """The reason this is a trigger and not a flush hook.

    A bulk ``insert()`` never reaches the ORM's unit of work, so an app-layer
    hook could not see it. The database does not care how the row arrived.
    """
    guild, initiative_id, actor = await _workspace(session)

    await _route(session, guild.id, actor.id)
    # A Core insert also skips the Python-side column defaults, so the
    # timestamps are supplied here; ``created_by`` is the database's job.
    now = datetime.now(UTC)
    await session.exec(
        insert(Wiki).values(
            initiative_id=initiative_id,
            name="written by statement",
            created_at=now,
            updated_at=now,
        )
    )

    row = (
        await session.exec(select(Wiki).where(Wiki.name == "written by statement"))
    ).one()
    assert row.created_by == actor.id


async def test_an_explicit_author_is_kept(session: AsyncSession):
    """A caller restoring original authorship (backup import) keeps it."""
    guild, initiative_id, actor = await _workspace(session)
    original = await create_user(session)

    await _route(session, guild.id, actor.id)
    wiki_id = await _add(
        session,
        initiative_id,
        "imported",
        created_by=original.id,
        created_by_kind=ActorKind.member,
    )

    assert (await _reload(session, wiki_id)).created_by == original.id


async def test_an_edit_by_someone_else_leaves_the_author(session: AsyncSession):
    """Authorship is a historical fact: the trigger is INSERT-only."""
    guild, initiative_id, author = await _workspace(session)
    editor = await create_user(session)
    await create_guild_membership(
        session, user=editor, guild=guild, role=CommunityRole.admin
    )

    await _route(session, guild.id, author.id)
    wiki_id = await _add(session, initiative_id, "first draft")

    await _route(session, guild.id, editor.id)
    row = await _reload(session, wiki_id)
    row.name = "second draft"
    await session.flush()

    assert (await _reload(session, wiki_id)).created_by == author.id


async def test_a_system_session_stamps_nothing(session: AsyncSession):
    """Background work and seeding have no one to name, so they name no one;
    nor has a plug-in acting as its community, on the tool tables its scopes
    can write."""
    guild, initiative_id, _ = await _workspace(session)

    await _route(session, guild.id, None)
    wiki_id = await _add(session, initiative_id, "swept up by a job")

    assert (await _reload(session, wiki_id)).created_by is None


@pytest.mark.always
async def test_every_author_table_has_the_trigger(session: AsyncSession):
    """``created_by_kind`` is NOT NULL, so a table that carries it without the
    trigger refuses every write that names no author."""
    missing = (
        await session.exec(
            text(
                """
                SELECT c.relname FROM pg_class c
                JOIN pg_namespace n
                  ON n.oid = c.relnamespace AND n.nspname = 'guild_template'
                JOIN pg_attribute a
                  ON a.attrelid = c.oid AND a.attname = 'created_by_kind'
                WHERE c.relkind = 'r' AND NOT EXISTS (
                    SELECT 1 FROM pg_trigger t
                    WHERE t.tgrelid = c.oid
                      AND t.tgfoid = 'public.fn_set_author'::regproc
                )
                ORDER BY 1
                """
            )
        )
    ).all()
    assert missing == []
