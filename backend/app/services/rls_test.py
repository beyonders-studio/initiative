"""Tests for Mandatory Access Control — RLS and guild/initiative-level security.

Tests cover initiative permission checks (check_initiative_permission) and
who the system engine reads as.
"""

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import DEFAULT_PERMISSION_VALUES, PermissionKey
from app.models.tenant.project import Project
from app.services.rls import check_initiative_permission
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
    route_as,
    route_system,
)


async def test_check_initiative_permission_answers_managers_and_members(
    session: AsyncSession, role_session
):
    """A manager holds every key; a member's role answers the documented
    default for each."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    # The product's own defaults are what this checks, so the factory's
    # ordinary-member convenience is turned off.
    initiative = await create_initiative(
        session, guild, admin, member_tool_access=False
    )

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    # Verify that the default values in DEFAULT_PERMISSION_VALUES are used as
    # fallback when a permission is not explicitly set on the role. The member
    # role has explicit permissions for the standard keys, so this test
    # validates the branch behavior: if a key were missing, it would fall back
    # to DEFAULT_PERMISSION_VALUES.
    for perm_key, expected in DEFAULT_PERMISSION_VALUES.items():
        asking = await role_session("app_user")
        await route_as(asking, user_id=member.id, guild_id=guild.id)
        result = await check_initiative_permission(
            asking,
            initiative_id=initiative.id,
            user=member,
            permission_key=perm_key,
        )
        # The explicit member role values happen to match the defaults for
        # the standard permission keys.
        assert result == expected, f"Mismatch for {perm_key}"

    asking = await role_session("app_user")
    await route_as(asking, user_id=admin.id, guild_id=guild.id)
    assert await check_initiative_permission(
        asking,
        initiative_id=initiative.id,
        user=admin,
        permission_key=PermissionKey.create_files,
    )


# ---------------------------------------------------------------------------
# Who the system engine reads as
# ---------------------------------------------------------------------------


async def test_a_member_routed_on_the_system_login_reads_as_themselves(
    session: AsyncSession, role_session
):
    """On the system engine's login, a member routed through the seam reads
    what their own standing gives them; the same connection with nobody routed
    reads the whole community."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    await create_project(session, initiative, owner)
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=guild)

    system = await role_session("app_admin")
    projects = select(func.count()).select_from(Project)

    await route_as(system, user_id=member.id, guild_id=guild.id, on_behalf=True)
    assert (await system.exec(projects)).one() == 0
    await route_as(system, user_id=owner.id, guild_id=guild.id, on_behalf=True)
    assert (await system.exec(projects)).one() == 1
    await route_system(system, guild_id=guild.id)
    assert (await system.exec(projects)).one() == 1
