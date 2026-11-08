"""Tests for the shared guild/initiative membership helpers."""

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant.initiative import Initiative
from app.services import membership as membership_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
)


async def _setup(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    outsider = await create_user(session, email="outsider@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, member)
    return admin, member, outsider, guild, initiative


async def test_guild_role_map_batch(session: AsyncSession):
    admin, member, outsider, guild, _initiative = await _setup(session)

    roles = await membership_service.guild_role_map(
        session, guild.id, (admin.id, member.id, outsider.id)
    )
    assert roles == {admin.id: CommunityRole.admin, member.id: CommunityRole.member}


async def test_initiative_scope_clause_legs(session: AsyncSession, reading_as):
    """member / guild-admin / (no standing platform-bypass) legs of the clause.

    The clause defers to ``initiative_access``, which answers about the reader
    the session was established for — so each of these enters the community as
    that reader, the way a request does.
    """
    from app.api.deps import GuildAccessError

    admin, member, outsider, guild, initiative = await _setup(session)
    platform_operator = await create_user(
        session, email="platform@example.com", role=UserRole.operator
    )

    async def scoped_ids(user) -> list[int]:
        try:
            reader = await reading_as(user.id, guild.id)
        except GuildAccessError:
            # Not in the community at all, which is the narrower answer.
            return []
        stmt = select(Initiative.id).where(
            membership_service.initiative_scope_clause(user.id, Initiative.id)
        )
        rows = list((await reader.exec(stmt)).all())
        await reader.rollback()
        return rows

    assert await scoped_ids(member) == [initiative.id]  # member leg
    assert await scoped_ids(admin) == [initiative.id]  # guild-admin leg
    assert await scoped_ids(outsider) == []  # no leg
    # ``data.bypass`` is NOT a standing leg — a platform operator with no
    # membership and no live grant sees nothing (they must break-glass).
    assert await scoped_ids(platform_operator) == []


async def test_initiative_scope_clause_pam_leg(session: AsyncSession, reading_as):
    """A live read grant satisfies the scope clause via initiative_access's
    pam_read leg; the same account with no grant reaches nothing at all.
    """
    from app.api.deps import GuildAccessError
    from app.testing import create_access_grant

    _admin, _member, outsider, guild, initiative = await _setup(session)

    def stmt():
        return select(Initiative.id).where(
            membership_service.initiative_scope_clause(outsider.id, Initiative.id)
        )

    # Without the grant there is no way in: the seam refuses an account that
    # belongs to neither the community nor a live grant.
    with pytest.raises(GuildAccessError):
        await reading_as(outsider.id, guild.id)

    # A grant counts only for a rung that may hold it.
    outsider.role = UserRole.support
    session.add(outsider)
    await create_access_grant(session, user=outsider, guild=guild)
    reader = await reading_as(outsider.id, guild.id)
    assert list((await reader.exec(stmt())).all()) == [initiative.id]
    await reader.rollback()
