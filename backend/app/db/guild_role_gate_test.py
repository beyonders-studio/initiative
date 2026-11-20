"""The database decides what a member's initiative role may engage.

Each test reads the table with a plain SELECT, carrying no clause of its own,
so what comes back is what the policies allowed.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.models.platform.guild import CommunityRole
from app.models.tenant.wiki import Wiki
from app.testing import (
    create_resource_grant,
    create_wiki,
    grant_role_permission,
)


async def _names(reading_as, guild_id, actor) -> list[str]:
    """Wiki names the database hands back for a bare SELECT, on the request
    login — the one the policies actually bind."""
    session = await reading_as(actor.user.id, guild_id)
    return sorted(await session.exec(select(Wiki.name)))


@pytest.mark.parametrize(("enabled", "names"), [(False, []), (True, ["Stock counts"])])
async def test_the_role_permission_decides(
    session, acting_user, reading_as, enabled, names
):
    """Shared with them, in their initiative — and reached only when their
    role holds wikis."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    wiki = await create_wiki(session, a.initiative, a.user, name="Stock counts")
    await create_resource_grant(session, wiki, user=b.user)
    await grant_role_permission(session, a.initiative, "wikis_enabled", enabled=enabled)

    assert await _names(reading_as, a.guild.id, b) == names


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
    wiki = await create_wiki(session, a.initiative, a.user, name="Stock counts")
    await create_resource_grant(session, wiki, user=b.user)

    assert await _names(reading_as, a.guild.id, b) == ["Stock counts"]


async def test_the_routed_guild_admin_still_reaches_it(
    session, acting_user, reading_as
):
    """Guild admin sits above all four gates."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await create_wiki(session, a.initiative, a.user, name="Stock counts")

    assert await _names(reading_as, a.guild.id, a) == ["Stock counts"]
