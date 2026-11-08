"""An owner is a person, a live install, or nobody — over HTTP.

An installed plug-in owns what it creates, and a guild admin may hand a member's
content, or the unowned pile, to a plug-in that may own all of it: one that is
switched on, holds the tool's write scope and is placed in the content's
initiative. What a live plug-in owns is not unowned; what a switched-off one owns
is, while it is off; uninstalling leaves its content unowned.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import UserMessages
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.tenant import ownership as ownership_service
from app.testing import (
    create_file,
    create_guild_plugin,
    create_initiative,
    create_project,
    route_session_to_guild,
)

_DEFINITION = {"plugin_kind": "service", "service": {"public_id": "tests.owner-plugin"}}
_WRITES_PROJECTS = ["projects:write"]


async def _plugin(
    session: AsyncSession,
    admin: Any,
    *,
    granted: list[str],
    placed: bool = True,
    enabled: bool = True,
) -> GuildPlugin:
    """An install in ``admin``'s community, placed in their initiative."""
    plugin = await create_guild_plugin(
        session,
        admin.guild,
        admin.user,
        definition=_DEFINITION,
        name="Automations",
        granted_scopes=granted,
        enabled=enabled,
    )
    if placed:
        await route_session_to_guild(session, admin.guild.id)
        session.add(
            PluginPlacement(install_id=plugin.id, initiative_id=admin.initiative.id)
        )
        await session.commit()
    return plugin


async def _owned_by_plugin(
    session: AsyncSession, admin: Any, plugin: GuildPlugin
) -> Any:
    project = await create_project(session, admin.initiative, admin.user)
    await route_session_to_guild(session, admin.guild.id)
    await ownership_service.set_resource_owner(
        session,
        tool=Tool.project,
        row=project,
        new_owner=ownership_service.Owner(plugin_install_id=plugin.id),
    )
    await session.commit()
    return project


async def _owner(session: AsyncSession, guild_id: int, tool: Tool, resource_id: int):
    await route_session_to_guild(session, guild_id)
    return await ownership_service.current_owner(
        session, tool=tool, resource_id=resource_id
    )


async def _unowned_ids(client: AsyncClient, admin: Any) -> set[int]:
    listed = await client.get(admin.g("/users/unowned-content"), headers=admin.headers)
    assert listed.status_code == 200, listed.text
    return {item["id"] for item in listed.json()["items"]}


# ---------------------------------------------------------------------------
# What a plug-in owns
# ---------------------------------------------------------------------------


async def test_a_live_plugins_content_is_owned_and_a_claim_leaves_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=_WRITES_PROJECTS)
    project = await _owned_by_plugin(session, admin, plugin)

    assert project.id not in await _unowned_ids(client, admin)

    claimed = await client.post(
        admin.g("/users/unowned-content/claim"),
        headers=admin.headers,
        json={"new_owner_id": admin.user.id},
    )
    assert claimed.status_code == 200, claimed.text
    assert await _owner(
        session, admin.guild.id, Tool.project, project.id
    ) == ownership_service.Owner(plugin_install_id=plugin.id)


async def test_a_switched_off_plugins_content_is_unowned_while_it_is_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=_WRITES_PROJECTS)
    project = await _owned_by_plugin(session, admin, plugin)

    await route_session_to_guild(session, admin.guild.id)
    plugin.enabled = False
    session.add(plugin)
    await session.commit()
    assert project.id in await _unowned_ids(client, admin)

    plugin.enabled = True
    session.add(plugin)
    await session.commit()
    assert project.id not in await _unowned_ids(client, admin)


async def test_uninstalling_leaves_its_content_unowned(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=_WRITES_PROJECTS)
    project = await _owned_by_plugin(session, admin, plugin)

    await route_session_to_guild(session, admin.guild.id)
    await session.delete(plugin)
    await session.commit()

    assert await _owner(session, admin.guild.id, Tool.project, project.id) is None
    assert project.id in await _unowned_ids(client, admin)


async def test_a_claim_of_a_switched_off_plugins_content_keeps_it_writing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The plug-in is the owner being replaced, so it keeps write."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=_WRITES_PROJECTS, enabled=True)
    project = await _owned_by_plugin(session, admin, plugin)
    await route_session_to_guild(session, admin.guild.id)
    plugin.enabled = False
    session.add(plugin)
    await session.commit()

    claimed = await client.post(
        admin.g("/users/unowned-content/claim"),
        headers=admin.headers,
        json={"new_owner_id": admin.user.id},
    )
    assert claimed.status_code == 200, claimed.text

    await route_session_to_guild(session, admin.guild.id)
    rows = (
        await session.exec(
            select(
                ResourceGrant.level,
                ResourceGrant.user_id,
                ResourceGrant.plugin_install_id,
            )
            .where(
                ResourceGrant.resource_type == Tool.project.value,
                ResourceGrant.resource_id == project.id,
            )
            .order_by(ResourceGrant.level)
        )
    ).all()
    assert (ResourceAccessLevel.owner, admin.user.id, None) in rows
    assert (ResourceAccessLevel.write, None, plugin.id) in rows


# ---------------------------------------------------------------------------
# Handing content to a plug-in
# ---------------------------------------------------------------------------


async def _members_project(session: AsyncSession, admin: Any, acting_user) -> tuple:
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, member.user)
    return member, project


async def test_a_members_content_goes_to_a_plugin_that_may_own_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=_WRITES_PROJECTS)
    member, project = await _members_project(session, admin, acting_user)

    listed = await client.get(
        admin.g(f"/users/{member.user.id}/owned-content"),
        headers=admin.headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["eligible_plugins"] == [
        {"id": plugin.id, "name": "Automations", "avatar_url": None}
    ]

    moved = await client.post(
        admin.g(f"/users/{member.user.id}/transfer-ownership"),
        headers=admin.headers,
        json={"new_owner_plugin_id": plugin.id},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["counts"] == {Tool.project.value: 1}
    assert await _owner(
        session, admin.guild.id, Tool.project, project.id
    ) == ownership_service.Owner(plugin_install_id=plugin.id)


async def test_the_unowned_pile_goes_to_a_plugin_that_may_own_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=_WRITES_PROJECTS)
    project = await create_project(session, admin.initiative, admin.user)
    await route_session_to_guild(session, admin.guild.id)
    await ownership_service.set_resource_owner(
        session, tool=Tool.project, row=project, new_owner=None
    )
    await session.commit()

    listed = await client.get(admin.g("/users/unowned-content"), headers=admin.headers)
    assert [a["id"] for a in listed.json()["eligible_plugins"]] == [plugin.id]

    claimed = await client.post(
        admin.g("/users/unowned-content/claim"),
        headers=admin.headers,
        json={"new_owner_plugin_id": plugin.id},
    )
    assert claimed.status_code == 200, claimed.text
    assert await _owner(
        session, admin.guild.id, Tool.project, project.id
    ) == ownership_service.Owner(plugin_install_id=plugin.id)


@pytest.mark.parametrize("why", ["no_write_scope", "not_placed", "switched_off"])
async def test_content_is_not_handed_to_a_plugin_that_may_not_own_it(
    client: AsyncClient, session: AsyncSession, acting_user, why: str
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(
        session,
        admin,
        granted=["projects:read"] if why == "no_write_scope" else _WRITES_PROJECTS,
        placed=why != "not_placed",
        enabled=why != "switched_off",
    )
    member, project = await _members_project(session, admin, acting_user)

    listed = await client.get(
        admin.g(f"/users/{member.user.id}/owned-content"),
        headers=admin.headers,
    )
    assert listed.json()["eligible_plugins"] == []

    moved = await client.post(
        admin.g(f"/users/{member.user.id}/transfer-ownership"),
        headers=admin.headers,
        json={"new_owner_plugin_id": plugin.id},
    )
    assert moved.status_code == 422, moved.text
    assert moved.json()["detail"] == UserMessages.OWNER_PLUGIN_NOT_ELIGIBLE
    assert await _owner(
        session, admin.guild.id, Tool.project, project.id
    ) == ownership_service.Owner(user_id=member.user.id)


async def test_a_plugin_placed_elsewhere_takes_none_of_a_mixed_pile(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Eligibility is for every item moved: one project in an initiative the plug-in
    is not placed in keeps the whole move from happening."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=_WRITES_PROJECTS)
    member, placed_project = await _members_project(session, admin, acting_user)
    elsewhere = await create_initiative(session, admin.guild, admin.user, name="B")
    await create_project(session, elsewhere, member.user)

    moved = await client.post(
        admin.g(f"/users/{member.user.id}/transfer-ownership"),
        headers=admin.headers,
        json={"new_owner_plugin_id": plugin.id},
    )
    assert moved.status_code == 422, moved.text
    assert await _owner(
        session, admin.guild.id, Tool.project, placed_project.id
    ) == ownership_service.Owner(user_id=member.user.id)


async def test_a_transfer_names_exactly_one_recipient(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=_WRITES_PROJECTS)
    for body in ({}, {"new_owner_id": admin.user.id, "new_owner_plugin_id": plugin.id}):
        response = await client.post(
            admin.g("/users/unowned-content/claim"),
            headers=admin.headers,
            json=body,
        )
        assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# The read models name the plug-in
# ---------------------------------------------------------------------------


async def test_the_read_models_name_the_owning_plugin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    plugin = await _plugin(session, admin, granted=["projects:write", "files:write"])
    project = await _owned_by_plugin(session, admin, plugin)
    file = await create_file(session, admin.initiative, admin.user)
    await route_session_to_guild(session, admin.guild.id)
    await ownership_service.set_resource_owner(
        session,
        tool=Tool.file,
        row=file,
        new_owner=ownership_service.Owner(plugin_install_id=plugin.id),
    )
    await session.commit()
    owning_plugin = {"id": plugin.id, "name": "Automations", "avatar_url": None}

    read = await client.get(admin.g(f"/projects/{project.id}"), headers=admin.headers)
    assert read.status_code == 200, read.text
    body = read.json()
    assert body["owner_plugin"] == owning_plugin
    assert body["owner_id"] is None and body["owner"] is None

    listed = await client.get(
        admin.g(f"/projects/?initiative_id={admin.initiative.id}"),
        headers=admin.headers,
    )
    row = next(p for p in listed.json()["items"] if p["id"] == project.id)
    assert row["owner_plugin"] == owning_plugin

    doc = await client.get(admin.g(f"/files/{file.id}"), headers=admin.headers)
    assert doc.status_code == 200, doc.text
    assert doc.json()["owner_plugin"] == owning_plugin
    assert doc.json()["owner"] is None

    docs = await client.get(
        admin.g(f"/files/?initiative_id={admin.initiative.id}"),
        headers=admin.headers,
    )
    row = next(d for d in docs.json()["items"] if d["id"] == file.id)
    assert row["owner_plugin"] == owning_plugin


async def test_a_person_owner_is_named_and_no_plugin_is(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    file = await create_file(session, admin.initiative, admin.user)

    doc = await client.get(admin.g(f"/files/{file.id}"), headers=admin.headers)
    assert doc.status_code == 200, doc.text
    assert doc.json()["owner"]["id"] == admin.user.id
    assert doc.json()["owner_plugin"] is None
