"""What a community's own surfaces write down.

Every record here is staged on the session that performs the action, inside the
transaction that performs it, and carries the guild it happened in — which is
the column an operator reads the log by. The negatives matter as much: a
request that was refused, and a write that changed nothing, leave no record.
"""

from __future__ import annotations

from httpx import AsyncClient
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

PASSWORD = "testpassword123"


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


async def test_creating_a_guild_records_the_guild_and_its_first_member(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await create_user(session)
    user_id = user.id
    capfd.readouterr()

    response = await client.post(
        "/api/v1/communities/", headers=get_auth_headers(user), json={"name": "Audited"}
    )
    assert response.status_code == 201, response.text
    guild_id = response.json()["id"]

    written = emitted(capfd)
    created = _of_type(written, AuditEventType.GUILD_CREATED)
    assert [_where(row) for row in created] == [
        (user_id, user_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert created[0]["detail"] == {"owner_is_actor": True}

    added = _of_type(written, AuditEventType.GUILD_MEMBER_ADDED)
    assert [_where(row) for row in added] == [
        (user_id, user_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert added[0]["detail"] == {"role": "superadmin", "via": "created"}


async def test_an_invite_is_recorded_when_it_is_minted_redeemed_and_withdrawn(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin, guild = await _guild_with_admin(session)
    admin_id, guild_id = admin.id, guild.id
    capfd.readouterr()

    minted = await client.post(
        f"/api/v1/communities/{guild_id}/invites",
        headers=get_auth_headers(admin),
        json={"max_uses": 3},
    )
    assert minted.status_code == 201, minted.text
    invite = minted.json()

    rows = emitted(capfd, AuditEventType.GUILD_INVITE_CREATED)
    assert [_where(row) for row in rows] == [
        (admin_id, None, guild_id, {"type": "guild_invite", "id": invite["id"]})
    ]
    assert rows[0]["detail"]["max_uses"] == 3
    assert rows[0]["detail"]["addressed"] is False
    # The code is the invite; the record describes its terms and never carries it.
    assert "code" not in rows[0]["detail"]

    joiner = await create_user(session)
    joiner_id = joiner.id
    accepted = await client.post(
        "/api/v1/communities/invite/accept",
        headers=get_auth_headers(joiner),
        json={"code": invite["code"]},
    )
    assert accepted.status_code == 200, accepted.text

    added = emitted(capfd, AuditEventType.GUILD_MEMBER_ADDED)
    assert [_where(row) for row in added] == [
        (joiner_id, joiner_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert added[0]["detail"] == {
        "role": "member",
        "via": "invite",
        "invite_id": invite["id"],
    }

    withdrawn = await client.delete(
        f"/api/v1/communities/{guild_id}/invites/{invite['id']}",
        headers=get_auth_headers(admin),
    )
    assert withdrawn.status_code == 204, withdrawn.text
    revoked = emitted(capfd, AuditEventType.GUILD_INVITE_REVOKED)
    assert [_where(row) for row in revoked] == [
        (admin_id, None, guild_id, {"type": "guild_invite", "id": invite["id"]})
    ]


async def test_withdrawing_an_invite_that_is_not_there_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin, guild = await _guild_with_admin(session)
    capfd.readouterr()

    response = await client.delete(
        f"/api/v1/communities/{guild.id}/invites/9999999",
        headers=get_auth_headers(admin),
    )
    assert response.status_code == 204, response.text
    assert emitted(capfd, AuditEventType.GUILD_INVITE_REVOKED) == []


async def test_leaving_a_guild_is_recorded_against_the_leaver(
    client: AsyncClient, session: AsyncSession, capfd
):
    """Nobody else acted, so the person leaving is both actor and subject."""
    _owner, guild = await _guild_with_admin(session, role=CommunityRole.superadmin)
    guild_id = guild.id
    member = await create_user(session)
    member_id = member.id
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    capfd.readouterr()

    response = await client.delete(
        f"/api/v1/communities/{guild_id}/leave", headers=get_auth_headers(member)
    )
    assert response.status_code == 204, response.text

    rows = emitted(capfd, AuditEventType.GUILD_MEMBER_REMOVED)
    assert [_where(row) for row in rows] == [
        (member_id, member_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert rows[0]["detail"] == {"role": "member", "via": "left"}


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


async def test_a_members_api_access_changing_is_recorded(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner, guild = await _guild_with_admin(session, role=CommunityRole.superadmin)
    owner_id, guild_id = owner.id, guild.id
    member = await create_user(session)
    member_id = member.id
    await create_guild_membership(session, user=member, guild=guild)
    capfd.readouterr()
    path = f"/api/v1/communities/{guild_id}/members/{member_id}/api-access"

    revoked = await client.put(
        path, headers=get_auth_headers(owner), json={"api_keys_allowed": False}
    )
    assert revoked.status_code == 204, revoked.text

    rows = emitted(capfd, AuditEventType.GUILD_MEMBER_API_ACCESS_CHANGED)
    assert [_where(row) for row in rows] == [
        (owner_id, member_id, guild_id, {"type": "guild", "id": guild_id})
    ]
    assert rows[0]["detail"] == {"api_keys_allowed": False}

    # Restating what it already reads moved nothing.
    again = await client.put(
        path, headers=get_auth_headers(owner), json={"api_keys_allowed": False}
    )
    assert again.status_code == 204, again.text
    assert emitted(capfd, AuditEventType.GUILD_MEMBER_API_ACCESS_CHANGED) == []


# --- settings ---------------------------------------------------------------


async def test_a_profile_edit_names_the_fields_that_moved_and_copies_neither(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin, guild = await _guild_with_admin(session)
    admin_id, guild_id = admin.id, guild.id
    capfd.readouterr()

    response = await client.patch(
        f"/api/v1/communities/{guild_id}",
        headers=get_auth_headers(admin),
        json={"name": "Renamed", "description": "Now described"},
    )
    assert response.status_code == 200, response.text

    rows = emitted(capfd, AuditEventType.GUILD_SETTINGS_CHANGED)
    assert [_where(row) for row in rows] == [
        (admin_id, None, guild_id, {"type": "guild", "id": guild_id})
    ]
    detail = rows[0]["detail"]
    assert detail["area"] == "profile"
    assert detail["changed"] == ["description", "name"]
    # Both hold free text, so the record names them and carries neither value.
    assert detail["values"] == {}

    unchanged = await client.patch(
        f"/api/v1/communities/{guild_id}",
        headers=get_auth_headers(admin),
        json={"name": "Renamed"},
    )
    assert unchanged.status_code == 200, unchanged.text
    assert emitted(capfd, AuditEventType.GUILD_SETTINGS_CHANGED) == []


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


# --- the end of a guild -----------------------------------------------------


async def test_deleting_a_guild_is_recorded_in_the_transaction_that_deletes_it(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin, guild = await _guild_with_admin(
        session, name="To Delete", role=CommunityRole.superadmin
    )
    admin_id, guild_id = admin.id, guild.id
    capfd.readouterr()

    response = await client.request(
        "DELETE",
        f"/api/v1/communities/{guild_id}",
        headers=get_auth_headers(admin),
        json={
            "password": PASSWORD,
            "confirmation_text": "DELETE COMMUNITY TO DELETE",
        },
    )
    assert response.status_code == 204, response.text

    rows = emitted(capfd, AuditEventType.GUILD_DELETED)
    # The record outlives the row it names — no foreign key follows the guild,
    # and the row itself is retained until the purge either way.
    assert [_where(row) for row in rows] == [
        (admin_id, None, guild_id, {"type": "guild", "id": guild_id})
    ]
    # One member, so the roster is the person deleting it and goes with it.
    # A community with other people in it keeps theirs.
    assert rows[0]["detail"] == {"via": "admin", "roster_cleared": True}


async def test_a_refused_guild_deletion_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin, guild = await _guild_with_admin(
        session, name="To Delete", role=CommunityRole.superadmin
    )
    capfd.readouterr()

    response = await client.request(
        "DELETE",
        f"/api/v1/communities/{guild.id}",
        headers=get_auth_headers(admin),
        json={"password": PASSWORD, "confirmation_text": "DELETE COMMUNITY WRONG"},
    )
    assert response.status_code == 400
    assert emitted(capfd, AuditEventType.GUILD_DELETED) == []
