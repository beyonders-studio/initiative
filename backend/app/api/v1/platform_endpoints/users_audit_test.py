"""What a guild admin's member screens write down.

A roster leaving as a spreadsheet, somebody being taken off it, and content
changing hands are all guild-scoped, so each record carries the guild it
happened in and runs on the guild-routed session that performs it.
"""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.services.tenant import ownership as ownership_service
from app.testing import TOOL_FACTORIES, emitted, route_session_to_guild
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
)


def _where(row) -> tuple:
    return (
        row["actor_user_id"],
        row["target_user_id"],
        row["guild_id"],
        row["target"],
    )


# --- the roster -------------------------------------------------------------


async def test_exporting_a_roster_is_recorded_with_its_count(
    client: AsyncClient, session: AsyncSession, capfd
):
    """Nothing changed, so the record is the whole write this request makes."""
    guild = await create_guild(session)
    guild_id = guild.id
    admin = await create_user(session)
    admin_id = admin.id
    member = await create_user(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    capfd.readouterr()

    response = await client.get(
        f"/api/v1/c/{guild_id}/users/export.csv", headers=get_auth_headers(admin)
    )
    assert response.status_code == 200, response.text

    rows = emitted(capfd, AuditEventType.GUILD_MEMBERS_EXPORTED)
    assert [_where(row) for row in rows] == [
        (admin_id, None, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert rows[0]["detail"] == {"count": 2}
    assert rows[0]["is_write"] is False


async def test_an_export_that_matched_nobody_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    guild = await create_guild(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    capfd.readouterr()

    response = await client.get(
        f"/api/v1/c/{guild.id}/users/export.csv?user_id=9999999",
        headers=get_auth_headers(admin),
    )
    assert response.status_code == 404
    assert emitted(capfd, AuditEventType.GUILD_MEMBERS_EXPORTED) == []


async def test_removing_a_member_is_recorded_against_the_admin_who_did_it(
    client: AsyncClient, session: AsyncSession, capfd
):
    guild = await create_guild(session)
    guild_id = guild.id
    admin = await create_user(session)
    admin_id = admin.id
    member = await create_user(session)
    member_id = member.id
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    capfd.readouterr()

    response = await client.delete(
        f"/api/v1/c/{guild_id}/users/{member_id}", headers=get_auth_headers(admin)
    )
    assert response.status_code == 204, response.text

    rows = emitted(capfd, AuditEventType.GUILD_MEMBER_REMOVED)
    assert [_where(row) for row in rows] == [
        (admin_id, member_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert rows[0]["detail"] == {"role": "member", "via": "admin"}


async def test_removing_someone_who_is_not_a_member_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    guild = await create_guild(session)
    admin = await create_user(session)
    outsider = await create_user(session)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    capfd.readouterr()

    response = await client.delete(
        f"/api/v1/c/{guild.id}/users/{outsider.id}", headers=get_auth_headers(admin)
    )
    assert response.status_code == 404
    assert emitted(capfd, AuditEventType.GUILD_MEMBER_REMOVED) == []


# --- ownership --------------------------------------------------------------


async def test_a_transfer_records_one_move_counted_by_tool(
    client: AsyncClient, session: AsyncSession, acting_user, capfd
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    await TOOL_FACTORIES[Tool.project](session, admin.initiative, member.user)
    capfd.readouterr()

    response = await client.post(
        admin.g(f"/users/{member.user.id}/transfer-ownership"),
        headers=admin.headers,
        json={"new_owner_id": admin.user.id},
    )
    assert response.status_code == 200, response.text

    rows = emitted(capfd, AuditEventType.CONTENT_OWNERSHIP_TRANSFERRED)
    assert [_where(row) for row in rows] == [
        (admin.user.id, member.user.id, admin.guild.id, None)
    ]
    detail = rows[0]["detail"]
    assert detail["from_user_id"] == member.user.id
    assert detail["to_user_id"] == admin.user.id
    assert detail["counts"][Tool.project.value] == 1


async def test_a_claim_records_the_move_with_no_previous_owner(
    client: AsyncClient, session: AsyncSession, acting_user, capfd
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    project = await TOOL_FACTORIES[Tool.project](session, admin.initiative, admin.user)
    await route_session_to_guild(session, admin.guild.id)
    await ownership_service.set_resource_owner(
        session, tool=Tool.project, row=project, new_owner=None
    )
    await session.commit()
    capfd.readouterr()

    response = await client.post(
        admin.g("/users/unowned-content/claim"),
        headers=admin.headers,
        json={"new_owner_id": admin.user.id},
    )
    assert response.status_code == 200, response.text

    rows = emitted(capfd, AuditEventType.CONTENT_OWNERSHIP_TRANSFERRED)
    assert [_where(row) for row in rows] == [
        # Nobody held it, so there is no previous owner to name.
        (admin.user.id, None, admin.guild.id, None)
    ]
    detail = rows[0]["detail"]
    assert detail["from_user_id"] is None
    assert detail["to_user_id"] == admin.user.id
    assert detail["counts"][Tool.project.value] == 1


async def test_a_transfer_that_moved_nothing_records_nothing(
    client: AsyncClient, acting_user, capfd
):
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    capfd.readouterr()

    response = await client.post(
        admin.g(f"/users/{member.user.id}/transfer-ownership"),
        headers=admin.headers,
        json={"new_owner_id": admin.user.id},
    )
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 0
    assert emitted(capfd, AuditEventType.CONTENT_OWNERSHIP_TRANSFERRED) == []
