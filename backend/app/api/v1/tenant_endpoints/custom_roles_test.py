"""The custom roles routes: a role gives a member the surfaces it names, and
nobody makes, gives or takes off a role past what they hold."""

from app.core.messages import CustomRoleMessages, GuildMessages
from app.core.rules import SURFACE_CUSTOM_ROLES, SetBy
from app.models.platform.guild import CommunityRole
from app.services.platform import rules
from app.testing import create_guild_plugin


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
    assert held.json() == {"surfaces": ["invites"], "plugin_permissions": []}
    holders = await client.get(
        member.g("/custom-roles/holders"), headers=member.headers
    )
    assert holders.json() == [{"user_id": member.user.id, "role_id": doors}]

    issued = await client.post(invites, headers=member.headers, json={})
    assert issued.status_code == 201, issued.text
    # A guest invite can open any initiative, which a member doesn't see.
    guest_invite = await client.post(
        invites, headers=member.headers, json={"guest_days": 7}
    )
    assert guest_invite.status_code == 403
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


async def test_a_name_another_role_has_is_a_conflict(client, acting_user):
    admin = await acting_user(guild_role=CommunityRole.admin)
    await _make(client, admin, name="Doors", base_rung="member", surfaces=[])
    other = await _make(client, admin, name="Roll", base_rung="member", surfaces=[])

    made = await client.post(
        admin.g("/custom-roles/"),
        headers=admin.headers,
        json={"name": "Doors", "base_rung": "member", "surfaces": []},
    )
    renamed = await client.patch(
        admin.g(f"/custom-roles/{other}"), headers=admin.headers, json={"name": "Doors"}
    )
    for response in (made, renamed):
        assert response.status_code == 409
        assert response.json()["detail"] == CustomRoleMessages.CUSTOM_ROLE_NAME_TAKEN


async def test_a_narrowed_admin_hands_out_no_more_than_it_holds(
    client, acting_user, session
):
    admin = await acting_user(guild_role=CommunityRole.admin)
    narrowed = await acting_user(guild_role=CommunityRole.admin, guild=admin.guild)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    plugin = await create_guild_plugin(
        session,
        admin.guild,
        admin.user,
        definition={
            "permissions": [{"id": "console", "level": "community", "name": {}}]
        },
    )
    console = [{"install_id": plugin.id, "permission": "console"}]
    roster = await _make(
        client, admin, name="Roster", base_rung="admin", surfaces=["members", "roles"]
    )
    assert (await _give(client, admin, narrowed.user.id, roster)).status_code == 204
    held = await client.get(narrowed.g("/custom-roles/held"), headers=narrowed.headers)
    assert held.json()["plugin_permissions"] == []

    async def make(actor, rung: str, permissions) -> int:
        made = await client.post(
            actor.g("/custom-roles/"),
            headers=actor.headers,
            json={
                "name": f"{rung} {len(permissions)}",
                "base_rung": rung,
                "plugin_permissions": permissions,
            },
        )
        return made.status_code

    # A plug-in's community permission is kept by a role on the admin rung,
    # one the plug-in declares, given by somebody who holds it.
    assert await make(narrowed, "admin", console) == 403
    assert await make(admin, "member", console) == 400
    assert await make(admin, "admin", [{**console[0], "permission": "x"}]) == 422
    assert await make(admin, "admin", console) == 201
    listed = await client.get(admin.g("/custom-roles/"), headers=admin.headers)
    assert {r["name"]: r["plugin_permissions"] for r in listed.json()} == {
        "Roster": [],
        "admin 1": console,
    }

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
