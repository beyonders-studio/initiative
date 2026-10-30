"""The custom roles routes: a role gives a member the surfaces it names, and
nobody makes, gives or takes off a role past what they hold."""

from app.core.messages import CustomRoleMessages, GuildMessages
from app.core.rules import SURFACE_CUSTOM_ROLES, SetBy
from app.models.platform.guild import CommunityRole
from app.services.platform import rules


async def _make(client, actor, **role) -> int:
    made = await client.post(
        actor.g("/custom-roles/"), headers=actor.headers, json=role
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


async def _give(client, actor, user_id: int, role_id: int | None):
    return await client.put(
        actor.g(f"/custom-roles/holders/{user_id}"),
        headers=actor.headers,
        json={"role_id": role_id},
    )


async def test_a_member_role_opens_the_surfaces_it_names(client, acting_user):
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    invites = f"/api/v1/communities/{admin.guild.id}/invites"

    assert (await client.get(invites, headers=member.headers)).status_code == 403

    doors = await _make(
        client, admin, name="Doors", base_rung="member", surfaces=["invites"]
    )
    assert (await _give(client, admin, member.user.id, doors)).status_code == 204
    held = await client.get(member.g("/custom-roles/held"), headers=member.headers)
    assert held.json() == {"surfaces": ["invites"]}
    holders = await client.get(
        member.g("/custom-roles/holders"), headers=member.headers
    )
    assert holders.json() == [{"user_id": member.user.id, "role_id": doors}]

    issued = await client.post(invites, headers=member.headers, json={})
    assert issued.status_code == 201, issued.text
    listed = await client.get(invites, headers=member.headers)
    assert listed.status_code == 200 and len(listed.json()) == 1

    refused = await client.post(
        admin.g("/custom-roles/"),
        headers=admin.headers,
        json={"name": "Bins", "base_rung": "member", "surfaces": ["trash"]},
    )
    assert refused.status_code == 400
    assert (
        refused.json()["detail"]
        == CustomRoleMessages.CUSTOM_ROLE_SURFACE_NOT_FOR_MEMBERS
    )


async def test_a_narrowed_admin_hands_out_no_more_than_it_holds(client, acting_user):
    admin = await acting_user(guild_role=CommunityRole.admin)
    narrowed = await acting_user(guild_role=CommunityRole.admin, guild=admin.guild)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    roster = await _make(
        client, admin, name="Roster", base_rung="admin", surfaces=["members", "roles"]
    )
    assert (await _give(client, admin, narrowed.user.id, roster)).status_code == 204

    beyond = await client.post(
        narrowed.g("/custom-roles/"),
        headers=narrowed.headers,
        json={"name": "Doors", "base_rung": "member", "surfaces": ["invites"]},
    )
    assert beyond.status_code == 403
    assert beyond.json()["detail"] == CustomRoleMessages.CUSTOM_ROLE_BEYOND_YOURS

    widens = await _give(client, narrowed, narrowed.user.id, None)
    assert widens.status_code == 403
    assert widens.json()["detail"] == CustomRoleMessages.CUSTOM_ROLE_WIDENS_AN_ADMIN

    promoted = await client.patch(
        f"/api/v1/communities/{admin.guild.id}/members/{member.user.id}",
        headers=narrowed.headers,
        json={"role": "admin"},
    )
    assert promoted.status_code == 403
    assert promoted.json()["detail"] == GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE


async def test_closed_custom_roles_change_nothing_and_keep_applying(
    client, acting_user, session
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    doors = await _make(
        client, admin, name="Doors", base_rung="member", surfaces=["invites"]
    )
    await _give(client, admin, member.user.id, doors)
    await rules.put(
        session,
        SURFACE_CUSTOM_ROLES,
        False,
        guild_id=admin.guild.id,
        set_by=SetBy.deployment,
    )
    await session.commit()

    closed = await _give(client, admin, member.user.id, None)
    assert closed.status_code == 403
    assert closed.json()["detail"] == GuildMessages.COMMUNITY_SURFACE_CLOSED
    listed = await client.get(
        f"/api/v1/communities/{admin.guild.id}/invites", headers=member.headers
    )
    assert listed.status_code == 200
