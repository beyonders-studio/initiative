"""An operator acts on a community's seat only through the community's own
routes, holding the break-glass pair.

The case this covers: the only superadmin cannot pass the seat on themselves
(unreachable, asking for erasure, banned). Breaking glass issues a
``read_write`` content grant and a ``superadmin`` settings grant; together they
let the holder seat somebody from inside the community, or delete it from its
own settings — either of which clears the account's deletion blocker.
"""

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import (
    CommunityRole,
    CommunityStatus,
    Guild,
    GuildMembership,
)

BREAK_GLASS = "/api/v1/access-grants/break-glass"
PASSWORD = "testpassword123"


async def test_a_break_glass_holder_seats_a_superadmin_from_the_guilds_own_route(
    client: AsyncClient, session: AsyncSession, acting_user
):
    keyholder = await acting_user(guild_role=CommunityRole.superadmin)
    guild_id = keyholder.guild.id
    keyholder_id = keyholder.user.id
    successor = await acting_user(
        guild_role=CommunityRole.member, guild=keyholder.guild
    )
    successor_id = successor.user.id
    operator = await acting_user("operator")

    role_route = f"/api/v1/communities/{guild_id}/members/{successor_id}"
    eligibility = f"/api/v1/operator/users/{keyholder_id}/deletion-eligibility"

    blocked = await client.get(eligibility, headers=operator.headers)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["can_delete"] is False
    assert [g["community_id"] for g in blocked.json()["community_blockers"]] == [
        guild_id
    ]

    # Not a member and no grant yet: the route is not theirs.
    before = await client.patch(
        role_route, headers=operator.headers, json={"role": "superadmin"}
    )
    assert before.status_code == 403, before.text

    issued = await client.post(
        BREAK_GLASS,
        json={"community_id": guild_id, "reason": "sole superadmin unreachable"},
        headers=operator.headers,
    )
    assert issued.status_code == 201, issued.text

    seated = await client.patch(
        role_route, headers=operator.headers, json={"role": "superadmin"}
    )
    assert seated.status_code == 204, seated.text

    session.expire_all()
    row = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == successor_id,
            )
        )
    ).one()
    assert row.role == CommunityRole.superadmin

    cleared = await client.get(eligibility, headers=operator.headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["can_delete"] is True
    assert cleared.json()["community_blockers"] == []


async def test_a_break_glass_holder_deletes_the_community_from_its_own_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    keyholder = await acting_user(guild_role=CommunityRole.superadmin)
    guild_id = keyholder.guild.id
    guild_name = keyholder.guild.name
    keyholder_id = keyholder.user.id
    await acting_user(guild_role=CommunityRole.member, guild=keyholder.guild)
    operator = await acting_user("operator")

    eligibility = f"/api/v1/operator/users/{keyholder_id}/deletion-eligibility"
    body = {
        "password": PASSWORD,
        "confirmation_text": f"DELETE COMMUNITY {guild_name.upper()}",
    }

    # Not a member and no grant yet: the community's delete is not theirs.
    before = await client.request(
        "DELETE", f"/api/v1/communities/{guild_id}", headers=operator.headers, json=body
    )
    assert before.status_code == 403, before.text

    issued = await client.post(
        BREAK_GLASS,
        json={"community_id": guild_id, "reason": "sole superadmin unreachable"},
        headers=operator.headers,
    )
    assert issued.status_code == 201, issued.text

    deleted = await client.request(
        "DELETE", f"/api/v1/communities/{guild_id}", headers=operator.headers, json=body
    )
    assert deleted.status_code == 204, deleted.text

    session.expire_all()
    guild = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    assert guild.status == CommunityStatus.deleted.value

    cleared = await client.get(eligibility, headers=operator.headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["community_blockers"] == []


async def test_the_platform_has_no_route_of_its_own_to_delete_a_community(
    client: AsyncClient, acting_user
):
    keyholder = await acting_user(guild_role=CommunityRole.superadmin)
    operator = await acting_user("operator")

    response = await client.delete(
        f"/api/v1/operator/communities/{keyholder.guild.id}"
        f"?blocked_user_id={keyholder.user.id}",
        headers=operator.headers,
    )
    assert response.status_code in (404, 405), response.text
