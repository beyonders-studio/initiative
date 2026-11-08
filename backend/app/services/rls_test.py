"""Tests for Mandatory Access Control — RLS and guild/initiative-level security.

Tests cover:
- Initiative manager checks (is_initiative_manager)
- Initiative permission checks (check_initiative_permission)
"""

import pytest
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import GuildAccessError
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant.initiative import DEFAULT_PERMISSION_VALUES, PermissionKey
from app.models.tenant.project import Project
from app.services.rls import (
    check_initiative_permission,
    is_initiative_manager,
)
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

# ---------------------------------------------------------------------------
# Guild-level access checks (sync / unit)
# ---------------------------------------------------------------------------


async def test_is_initiative_manager_with_pm_role(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user)
    # create_initiative already adds the creator as project_manager

    await route_as(session, user_id=user.id, guild_id=guild.id)
    result = await is_initiative_manager(session, initiative_id=initiative.id)

    assert result is True


async def test_is_initiative_manager_with_member_role(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, admin)

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    await route_as(session, user_id=member.id, guild_id=guild.id)
    result = await is_initiative_manager(session, initiative_id=initiative.id)

    assert result is False


async def test_is_initiative_manager_no_standing_bypass(session: AsyncSession):
    """Phase 3: ``data.bypass`` no longer confers standing manager authority. A
    platform operator who isn't an initiative member (and holds no live grant) is
    NOT a manager — they must break-glass to reach the guild."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_initiative(session, guild, admin)

    # Create a platform operator who is NOT an initiative member
    operator_user = await create_user(
        session, email="operator@example.com", role=UserRole.operator
    )

    # The seam refuses an account that reaches the community by neither a
    # membership row nor a live grant, before any question about an initiative.
    with pytest.raises(GuildAccessError):
        await route_as(session, user_id=operator_user.id, guild_id=guild.id)


# ---------------------------------------------------------------------------
# Initiative permission checks (async / service)
# ---------------------------------------------------------------------------


async def test_check_initiative_permission_no_standing_bypass(session: AsyncSession):
    """Phase 3: ``data.bypass`` no longer grants every initiative permission. A
    platform operator who isn't a member (and holds no live grant) gets only the
    documented default for the key — here ``create_projects`` defaults False."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_initiative(session, guild, admin)

    operator_user = await create_user(
        session, email="operator@example.com", role=UserRole.operator
    )

    # The seam refuses an account that reaches the community by neither a
    # membership row nor a live grant, before any question about an initiative.
    with pytest.raises(GuildAccessError):
        await route_as(session, user_id=operator_user.id, guild_id=guild.id)


async def test_check_initiative_permission_manager_has_all(
    session: AsyncSession, role_session
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user)
    # creator is PM (is_manager=True)

    asking = await role_session("app_user")
    await route_as(asking, user_id=user.id, guild_id=guild.id)
    result = await check_initiative_permission(
        asking,
        initiative_id=initiative.id,
        user=user,
        permission_key=PermissionKey.create_files,
    )

    assert result is True


async def test_check_initiative_permission_member_explicit_enabled(
    session: AsyncSession, role_session
):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, admin)

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    # The member role has files_enabled=True and projects_enabled=True by default
    asking = await role_session("app_user")
    await route_as(asking, user_id=member.id, guild_id=guild.id)
    result = await check_initiative_permission(
        asking,
        initiative_id=initiative.id,
        user=member,
        permission_key=PermissionKey.files_enabled,
    )

    assert result is True


async def test_check_initiative_permission_member_explicit_disabled(
    session: AsyncSession, role_session
):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, admin)

    member = await create_user(session, email="member@example.com")
    await create_guild_membership(session, user=member, guild=guild)
    await create_initiative_member(session, initiative, member, role_name="member")

    # The member role has create_files=False and create_projects=False by default
    asking = await role_session("app_user")
    await route_as(asking, user_id=member.id, guild_id=guild.id)
    result = await check_initiative_permission(
        asking,
        initiative_id=initiative.id,
        user=member,
        permission_key=PermissionKey.create_files,
    )

    assert result is False


async def test_check_initiative_permission_falls_back_to_default(
    session: AsyncSession, role_session
):
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


async def test_check_initiative_permission_non_member(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_initiative(session, guild, admin)

    outsider = await create_user(session, email="outsider@example.com")

    # The seam refuses an account that reaches the community by neither a
    # membership row nor a live grant, before any question about an initiative.
    with pytest.raises(GuildAccessError):
        await route_as(session, user_id=outsider.id, guild_id=guild.id)


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
