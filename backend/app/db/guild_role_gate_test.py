"""The database decides what a member's initiative role may engage.

Each test reads the table with a plain SELECT, carrying no clause of its own,
so what comes back is what the policies allowed.
"""

from __future__ import annotations

from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.tenant.counter import CounterGroup
from app.testing import (
    create_counter_group,
    create_resource_grant,
    grant_role_permission,
)


async def _names(reading_as, guild_id, actor) -> list[str]:
    """Counter group names the database hands back for a bare SELECT, on the request
    login — the one the policies actually bind."""
    session = await reading_as(actor.user.id, guild_id)
    return sorted(await session.exec(select(CounterGroup.name)))


async def test_a_role_that_cannot_engage_the_tool_is_refused(
    session, acting_user, reading_as
):
    """Shared with them, in their initiative — and still not theirs to reach,
    because their role does not hold counter groups."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    group = await create_counter_group(
        session, a.initiative, a.user, name="Stock counts"
    )
    await create_resource_grant(session, group, user=b.user)
    # The factory's member may use the initiative's tools, as somebody the
    # sharing picker would have offered. This one may not.
    await grant_role_permission(
        session, a.initiative, "counter_groups_enabled", enabled=False
    )

    assert await _names(reading_as, a.guild.id, b) == []


async def test_the_role_permission_admits_them(session, acting_user, reading_as):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    group = await create_counter_group(
        session, a.initiative, a.user, name="Stock counts"
    )
    await create_resource_grant(session, group, user=b.user)
    await grant_role_permission(session, a.initiative, "counter_groups_enabled")

    assert await _names(reading_as, a.guild.id, b) == ["Stock counts"]


async def test_a_manager_role_needs_no_row(session, acting_user, reading_as):
    """A manager holds every key whether or not one is stored — the same rule
    the application's resolver applies."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="project_manager",
    )
    group = await create_counter_group(
        session, a.initiative, a.user, name="Stock counts"
    )
    await create_resource_grant(session, group, user=b.user)

    assert await _names(reading_as, a.guild.id, b) == ["Stock counts"]


async def test_the_routed_guild_admin_still_reaches_it(
    session, acting_user, reading_as
):
    """Guild admin sits above all four gates."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_counter_group(session, a.initiative, a.user, name="Stock counts")

    assert await _names(reading_as, a.guild.id, a) == ["Stock counts"]
