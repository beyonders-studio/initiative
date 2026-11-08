"""A community that holds its members to the twelve-hour session standard.

The switch is the guild's own, on the same surface and behind the same seat as
the rest of its sign-in configuration.
"""

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


async def test_the_seat_switches_the_standard_and_reads_it_back(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.superadmin
    )
    headers = get_auth_headers(admin)
    settings = f"/api/v1/communities/{guild.id}/auth-settings"

    read = await client.get(settings, headers=headers)
    assert read.json()["enforce_compliance_session"] is False

    on = await client.patch(
        settings, headers=headers, json={"enforce_compliance_session": True}
    )
    assert on.status_code == 200, on.text
    assert on.json()["enforce_compliance_session"] is True
    read = await client.get(settings, headers=headers)
    assert read.json()["enforce_compliance_session"] is True

    off = await client.patch(
        settings, headers=headers, json={"enforce_compliance_session": False}
    )
    assert off.json()["enforce_compliance_session"] is False


async def test_a_member_is_not_told_the_standard(
    client: AsyncClient, session: AsyncSession
):
    """It is read by the surface that sets it; the guild list tells nobody
    about it, and a member cannot read that surface."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.superadmin
    )
    await client.patch(
        f"/api/v1/communities/{guild.id}/auth-settings",
        headers=get_auth_headers(admin),
        json={"enforce_compliance_session": True},
    )

    member = await create_user(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    member_headers = get_auth_headers(member)
    listed = await client.get("/api/v1/communities/", headers=member_headers)
    assert all("enforce_compliance_session" not in g for g in listed.json())
    read = await client.get(
        f"/api/v1/communities/{guild.id}/auth-settings", headers=member_headers
    )
    assert read.status_code == 403
