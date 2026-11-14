"""Each ladder is spelled once, by the enum that owns it; the SQL reads it.

The unit tests pin the spelling. The database tests ask the rendered rule the
way a request does — on the request login, through the seam — and compare its
answer with the enum's, rung by rung.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.db.authorization import sql_values, standing_arg
from app.models.platform.access_grant import SettingsLevel
from app.models.platform.guild import GUILD_STORED_ROLES, CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant.resource_grant import (
    RESOURCE_LEVEL_LADDER,
    WRITE_LEVELS,
    ResourceAccessLevel,
)
from app.testing import (
    create_access_grant,
    create_project,
    create_resource_grant,
    create_user,
    route_as,
)


def test_a_value_list_is_spelled_from_the_enum():
    assert sql_values(
        r.value for r in (CommunityRole.admin, CommunityRole.superadmin)
    ) == ("'admin', 'superadmin'")
    assert sql_values(level.value for level in WRITE_LEVELS) == "'write', 'owner'"


def test_the_sharing_ladder_reaches_downward():
    assert RESOURCE_LEVEL_LADDER == (
        ResourceAccessLevel.read,
        ResourceAccessLevel.write,
        ResourceAccessLevel.owner,
    )
    assert ResourceAccessLevel.owner.reaches(ResourceAccessLevel.write)
    assert ResourceAccessLevel.write.reaches(ResourceAccessLevel.read)
    assert not ResourceAccessLevel.read.reaches(ResourceAccessLevel.write)
    assert not ResourceAccessLevel.write.reaches(ResourceAccessLevel.owner)
    assert WRITE_LEVELS == (ResourceAccessLevel.write, ResourceAccessLevel.owner)


# A guest's row needs an end, so its standing is read in guests_test.
@pytest.mark.parametrize(
    "rung",
    sorted(GUILD_STORED_ROLES - {CommunityRole.guest}, key=lambda r: r.value),
)
async def test_the_standing_reads_the_admin_fact_off_the_ladder(
    acting_user, role_session, rung
):
    a = await acting_user(guild_role=rung)
    s = await role_session("app_user")
    context = await route_as(s, user_id=a.user.id, guild_id=a.guild.id)
    assert context.guild_admin is rung.reaches(CommunityRole.admin)
    assert context.guild_seat is rung.reaches(CommunityRole.superadmin)


@pytest.mark.parametrize("level", list(SettingsLevel))
async def test_the_settings_rung_reads_the_grant_off_the_ladder(
    session, acting_user, role_session, level
):
    a = await acting_user(guild_role=CommunityRole.admin)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session,
        user=support,
        guild=a.guild,
        access_level=level.value,
        purpose="settings",
    )
    s = await role_session("app_user")
    context = await route_as(s, user_id=support.id, guild_id=a.guild.id, settings=True)
    assert context.settings_rung == level.value
    assert context.guild_seat is (level is SettingsLevel.superadmin)


@pytest.mark.parametrize("level", list(RESOURCE_LEVEL_LADDER))
async def test_the_write_leg_reads_the_sharing_ladder(
    session, acting_user, role_session, level
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    if level is ResourceAccessLevel.owner:
        # A project has one owner, and creating it is how that grant is made.
        project = await create_project(session, a.initiative, member.user)
    else:
        project = await create_project(session, a.initiative, a.user)
        await create_resource_grant(session, project, user=member.user, level=level)

    s = await role_session("app_user")
    await route_as(s, user_id=member.user.id, guild_id=a.guild.id)
    reads = (
        await s.exec(
            select(
                func.resource_access(
                    "project",
                    project.id,
                    member.user.id,
                    a.initiative.id,
                    False,
                    standing_arg(),
                )
            )
        )
    ).one()
    writes = (
        await s.exec(
            select(
                func.resource_access(
                    "project",
                    project.id,
                    member.user.id,
                    a.initiative.id,
                    True,
                    standing_arg(),
                )
            )
        )
    ).one()
    assert reads is True
    assert writes is level.reaches(ResourceAccessLevel.write)
