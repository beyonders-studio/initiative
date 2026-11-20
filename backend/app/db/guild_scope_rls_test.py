"""What `initiative_id IS NULL` means at the database layer.

A row that belongs to no initiative belongs to the guild. The initiative gate has
nothing to decide about it, so `initiative_access` passes for any session routed
into that guild's schema — and the gates on either side of it still hold: the
schema boundary keeps the row inside its own guild, and grants decide which
members may read or write it.

These run under the real `app_user` login with a routed context rather than the
superuser-backed `session` fixture, because the whole subject is what a policy
does — and a superuser session would show none of it.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.calendar import Calendar
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing import (
    create_guild,
    create_guild_calendar,
    create_guild_membership,
    create_resource_grant,
    create_user,
    route_as,
)


async def _access(
    session: AsyncSession, initiative_id: int | None, user_id: int, write: bool = False
) -> bool:
    """Ask the policy function directly — it is the single rule every content
    policy defers to, so this is the decision under test."""
    return (
        await session.exec(
            text(
                "SELECT initiative_access(:initiative_id, :user_id, :need_write,"
                " (SELECT current_standing()))"
            ).bindparams(initiative_id=initiative_id, user_id=user_id, need_write=write)
        )
    ).scalar()


@pytest.fixture
async def guild_member(session):
    """A guild member who belongs to no initiative — the case that separates
    guild scope from initiative scope."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    return user, guild


class TestGuildScope:
    async def test_a_guild_level_row_is_readable_and_writable_at_this_layer(
        self, session, role_session, guild_member
    ):
        """The initiative gate does not decide a row that belongs to no
        initiative — grants do, one layer up. This pins that the policy itself
        does not silently withhold it."""
        user, guild = guild_member
        s = await role_session("app_user")
        await route_as(s, user_id=user.id, guild_id=guild.id)
        assert await _access(s, None, user.id) is True
        assert await _access(s, None, user.id, write=True) is True


class TestBoundariesStillHold:
    async def test_an_unrouted_session_reaches_no_guild_content_at_all(
        self, session, role_session, guild_member
    ):
        """Guild-level rows are not reachable without being routed first.

        Not expressed through `initiative_access`: that function resolves
        `initiative_members` through the routed search path, so calling it
        unrouted raises rather than answering. Which is the point — the boundary
        that protects a guild-level row from an unrouted session is the schema
        and the role, one layer below the policy, and that is what this asserts.
        """
        _, guild = guild_member
        s = await role_session("app_user")
        with pytest.raises(DBAPIError):
            await s.exec(text(f"SELECT count(*) FROM guild_{guild.id}.calendars"))


class TestGuildLevelTools:
    async def test_a_guild_calendar_is_written_by_the_guild_admin(
        self, session, role_session
    ):
        """Its sharing decides who writes what a guild calendar holds; the row
        itself is the admin's, whatever grant a member holds on it. The row's
        actions say the same: ``edit`` where the UPDATE lands, ``contribute``
        wherever the grant writes."""
        admin = await create_user(session)
        guild = await create_guild(session, creator=admin)
        member = await create_user(session)
        await create_guild_membership(session, user=member, guild=guild)
        calendar = await create_guild_calendar(session, guild, admin)
        await create_resource_grant(
            session, calendar, level=ResourceAccessLevel.write, user=member
        )

        for user, renamed, actions in (
            (member, 0, {"contribute"}),
            (admin, 1, {"contribute", "edit"}),
        ):
            s = await role_session("app_user")
            await route_as(s, user_id=user.id, guild_id=guild.id)
            row = (
                await s.exec(
                    select(Calendar)
                    .where(Calendar.id == calendar.id)
                    .options(undefer(Calendar.actions))
                )
            ).one()
            assert set(row.actions) & {"contribute", "edit"} == actions
            result = await s.exec(
                text("UPDATE calendars SET name = 'Renamed' WHERE id = :id").bindparams(
                    id=calendar.id
                )
            )
            assert result.rowcount == renamed
            await s.rollback()
