"""What a community's own surfaces write down.

Every record here is staged on the session that performs the action, inside the
transaction that performs it, and carries the guild it happened in — which is
the column an operator reads the log by. The negatives matter as much: a
request that was refused, and a write that changed nothing, leave no record.
"""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.testing import emitted
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_guild_provider_connection,
    create_user,
    get_auth_headers,
    get_auth_token,
)


def _where(row) -> tuple:
    """The four columns every record is read by."""
    return (
        row["actor_user_id"],
        row["target_user_id"],
        row["guild_id"],
        row["target"],
    )


def _of_type(written: list[dict], event_type: AuditEventType) -> list[dict]:
    return [row for row in written if row["event_type"] == event_type.value]


async def _guild_with_admin(
    session: AsyncSession, *, role: CommunityRole = CommunityRole.admin, **overrides
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin, **overrides)
    await create_guild_membership(session, user=admin, guild=guild, role=role)
    return admin, guild


# --- membership -------------------------------------------------------------


async def test_a_role_change_short_of_the_seat_is_its_own_event(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner, guild = await _guild_with_admin(session, role=CommunityRole.superadmin)
    owner_id, guild_id = owner.id, guild.id
    member = await create_user(session)
    member_id = member.id
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    capfd.readouterr()

    promoted = await client.patch(
        f"/api/v1/communities/{guild_id}/members/{member_id}",
        headers=get_auth_headers(owner),
        json={"role": "admin"},
    )
    assert promoted.status_code == 204, promoted.text

    written = emitted(capfd)
    rows = _of_type(written, AuditEventType.GUILD_MEMBER_ROLE_CHANGED)
    assert [_where(row) for row in rows] == [
        (owner_id, member_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert rows[0]["detail"] == {"from": "member", "to": "admin"}
    # The seat moving is a different event, and this was not the seat.
    assert _of_type(written, AuditEventType.GUILD_SUPERADMIN_CHANGED) == []

    # Restating the role they already hold moved nothing.
    again = await client.patch(
        f"/api/v1/communities/{guild_id}/members/{member_id}",
        headers=get_auth_headers(owner),
        json={"role": "admin"},
    )
    assert again.status_code == 204, again.text
    assert emitted(capfd, AuditEventType.GUILD_MEMBER_ROLE_CHANGED) == []


# --- settings ---------------------------------------------------------------


async def test_retention_is_recorded_as_its_own_area_with_its_values(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin, guild = await _guild_with_admin(session)
    guild_id = guild.id
    capfd.readouterr()

    response = await client.patch(
        f"/api/v1/communities/{guild_id}",
        headers=get_auth_headers(admin),
        json={"retention_days": 30},
    )
    assert response.status_code == 200, response.text

    rows = emitted(capfd, AuditEventType.GUILD_SETTINGS_CHANGED)
    assert [row["detail"] for row in rows] == [
        {
            "area": "retention",
            "changed": ["retention_days"],
            # A number, so the record carries both sides of it.
            "values": {"retention_days": {"from": 90, "to": 30}},
        }
    ]


async def test_the_seats_own_switches_are_recorded_area_by_area(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin, guild = await _guild_with_admin(session, role=CommunityRole.superadmin)
    admin_id, guild_id = admin.id, guild.id
    headers = get_auth_headers(admin)
    capfd.readouterr()

    push = await client.patch(
        f"/api/v1/communities/{guild_id}/auth-settings",
        headers=headers,
        json={"allow_push_notifications": False},
    )
    assert push.status_code == 200, push.text

    session_limit = await client.patch(
        f"/api/v1/communities/{guild_id}/auth-settings",
        headers=headers,
        json={"enforce_compliance_session": True},
    )
    assert session_limit.status_code == 200, session_limit.text

    rows = emitted(capfd, AuditEventType.GUILD_SETTINGS_CHANGED)
    assert [_where(row) for row in rows] == [
        (admin_id, None, guild_id, {"type": "guild", "id": guild_id}),
        (admin_id, None, guild_id, {"type": "guild", "id": guild_id}),
    ]
    assert [row["detail"] for row in rows] == [
        {
            "area": "notifications",
            "changed": ["allow_push_notifications"],
            "values": {"allow_push_notifications": {"from": True, "to": False}},
        },
        {
            "area": "session_limit",
            "changed": ["enforce_compliance_session"],
            "values": {"enforce_compliance_session": {"from": False, "to": True}},
        },
    ]

    # Setting a switch to what it already reads changed nothing.
    again = await client.patch(
        f"/api/v1/communities/{guild_id}/auth-settings",
        headers=headers,
        json={"allow_push_notifications": False},
    )
    assert again.status_code == 200, again.text
    assert emitted(capfd, AuditEventType.GUILD_SETTINGS_CHANGED) == []


async def test_setting_and_clearing_a_sign_in_requirement_is_recorded(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin, guild = await _guild_with_admin(session, role=CommunityRole.superadmin)
    admin_id, guild_id = admin.id, guild.id
    provider = await create_auth_provider(session, slug="corp")
    provider_id = provider.id
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    headers = {
        "Authorization": "Bearer "
        + get_auth_token(admin, satisfied_providers=[provider_id])
    }
    body = {"policy": "required", "provider_id": provider_id}
    capfd.readouterr()

    required = await client.patch(
        f"/api/v1/communities/{guild_id}/auth-settings",
        headers=headers,
        json={"auth_policy": body},
    )
    assert required.status_code == 200, required.text

    rows = emitted(capfd, AuditEventType.GUILD_AUTH_POLICY_CHANGED)
    assert [_where(row) for row in rows] == [
        (admin_id, None, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert rows[0]["detail"] == {
        "from": "open",
        "to": "required",
        "provider_id": provider_id,
        "require_methods": [],
    }

    # Restating the same requirement moved nothing.
    restated = await client.patch(
        f"/api/v1/communities/{guild_id}/auth-settings",
        headers=headers,
        json={"auth_policy": body},
    )
    assert restated.status_code == 200, restated.text
    assert emitted(capfd, AuditEventType.GUILD_AUTH_POLICY_CHANGED) == []

    cleared = await client.patch(
        f"/api/v1/communities/{guild_id}/auth-settings",
        headers=headers,
        json={"auth_policy": {"policy": "open"}},
    )
    assert cleared.status_code == 200, cleared.text
    rows = emitted(capfd, AuditEventType.GUILD_AUTH_POLICY_CHANGED)
    assert rows[-1]["detail"] == {
        "from": "required",
        "to": "open",
        "provider_id": None,
        "require_methods": [],
    }
