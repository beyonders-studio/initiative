"""The guild-admin ownership screens, over HTTP.

Handing content to somebody is the one place ownership moves by hand, so the
request runs inside the guild's own schema, as that guild's admin. Everything
it reads has to be readable from there — a guild session reads people through
``guild_member_profiles``, not ``users`` — and the service-level tests for
``app.services.tenant.ownership`` run on the setup session, which sees more
than a request does.
"""

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserStatus
from app.services.tenant import archive as archive_service
from app.services.tenant import ownership as ownership_service
from app.testing import (
    TOOL_FACTORIES,
    create_resource_grant,
    route_session_to_guild,
)


async def _released_project(session: AsyncSession, actor):
    """A project in ``actor``'s initiative that nobody owns."""
    project = await TOOL_FACTORIES[Tool.project](session, actor.initiative, actor.user)
    await route_session_to_guild(session, actor.guild.id)
    await ownership_service.set_resource_owner(
        session, tool=Tool.project, row=project, new_owner=None
    )
    await session.commit()
    return project


async def test_a_guild_admin_can_claim_unowned_content(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    project = await _released_project(session, admin)

    response = await client.post(
        f"/api/v1/c/{admin.guild.id}/users/unowned-content/claim",
        headers=admin.headers,
        json={"new_owner_id": admin.user.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1, response.text

    await route_session_to_guild(session, admin.guild.id)
    owners = await ownership_service.summarize_unowned_content(
        session, guild_id=admin.guild.id
    )
    assert (Tool.project, project.id) not in {(i.tool, i.id) for i in owners}


async def test_content_cannot_be_handed_to_an_ordinary_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The recipient check is the same query, from the other side."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    await _released_project(session, admin)

    response = await client.post(
        f"/api/v1/c/{admin.guild.id}/users/unowned-content/claim",
        headers=admin.headers,
        json={"new_owner_id": member.user.id},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "OWNER_MUST_BE_COMMUNITY_ADMIN"


async def test_ownership_transfers_between_guild_admins(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    receiver = await acting_user(
        guild_role=CommunityRole.admin,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="project_manager",
    )
    await TOOL_FACTORIES[Tool.project](session, owner.initiative, owner.user)

    response = await client.post(
        f"/api/v1/c/{owner.guild.id}/users/{owner.user.id}/transfer-ownership",
        headers=owner.headers,
        json={"new_owner_id": receiver.user.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1, response.text


async def test_ownership_moves_on_archived_tools(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Who owns a tool is administration, not an edit, so an archive does not
    hold it: every tool can be handed on and claimed while it is archived —
    including to somebody it was already shared with, whose own grant gives way
    to the owner's."""
    owner = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    receiver = await acting_user(
        guild_role=CommunityRole.admin,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="project_manager",
    )
    rows = {
        tool: await TOOL_FACTORIES[tool](session, owner.initiative, owner.user)
        for tool in Tool
    }
    for row in rows.values():
        await create_resource_grant(session, row, user=receiver.user)
    await archive_service.archive_entity(session, owner.initiative)
    await session.commit()

    response = await client.post(
        f"/api/v1/c/{owner.guild.id}/users/{owner.user.id}/transfer-ownership",
        headers=owner.headers,
        json={"new_owner_id": receiver.user.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == len(Tool), response.text

    await route_session_to_guild(session, owner.guild.id)
    for tool, row in rows.items():
        await ownership_service.set_resource_owner(
            session, tool=tool, row=row, new_owner=None
        )
    await session.commit()
    response = await client.post(
        f"/api/v1/c/{owner.guild.id}/users/unowned-content/claim",
        headers=owner.headers,
        json={"new_owner_id": owner.user.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == len(Tool), response.text


async def test_content_cannot_be_handed_outside_the_guild(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The roster view is a column boundary, not a row one: it publishes those
    nine columns for every account. What confines the recipient to this guild
    is the membership row the check joins to — scoped to the current guild by
    that table's own policy, and named again by the query. An admin of some
    other guild is refused exactly like a stranger.
    """
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    elsewhere = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    assert elsewhere.guild.id != admin.guild.id
    await _released_project(session, admin)

    response = await client.post(
        f"/api/v1/c/{admin.guild.id}/users/unowned-content/claim",
        headers=admin.headers,
        json={"new_owner_id": elsewhere.user.id},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "OWNER_MUST_BE_COMMUNITY_ADMIN"


async def test_content_cannot_be_handed_to_a_suspended_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``status`` is the one thing the roster view supplies that the
    membership row cannot, and it is why the check reads the view at all."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    frozen = await acting_user(guild_role=CommunityRole.admin, guild=admin.guild)
    frozen.user.status = UserStatus.suspended
    session.add(frozen.user)
    await session.commit()
    await _released_project(session, admin)

    response = await client.post(
        f"/api/v1/c/{admin.guild.id}/users/unowned-content/claim",
        headers=admin.headers,
        json={"new_owner_id": frozen.user.id},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "OWNER_MUST_BE_COMMUNITY_ADMIN"
