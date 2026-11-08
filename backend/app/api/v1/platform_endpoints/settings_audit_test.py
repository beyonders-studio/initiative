"""What the deployment's own settings page writes down.

Three surfaces meet here because one record type covers them: the settings
singleton (``detail.area`` says which part of it moved), the operator's claim
rules, and what an operator sets for one community. Every record names the
fields that moved; a password or a key is named and never copied.
"""

from __future__ import annotations

import json

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.user import UserRole
from app.testing import emitted
from app.testing.factories import (
    create_guild,
    create_user,
    get_auth_headers,
)

SMTP_PASSWORD = "smtp-pa55word"
S3_SECRET = "s3-secret-access-key"

_EMAIL = {
    "host": "smtp.example.com",
    "port": 587,
    "secure": True,
    "reject_unauthorized": True,
    "username": "mailer",
    "from_address": "noreply@example.com",
}


async def _owner(session: AsyncSession) -> tuple[int | None, dict[str, str]]:
    """The operator, as an id and its headers."""
    owner = await create_user(session, role=UserRole.owner)
    return owner.id, get_auth_headers(owner)


def _areas(rows) -> list[str]:
    return [row["detail"]["area"] for row in rows]


def _of_type(written: list[dict], event_type: AuditEventType) -> list[dict]:
    return [row for row in written if row["event_type"] == event_type.value]


# --- the settings singleton --------------------------------------------------


async def test_each_area_of_the_settings_page_records_its_own_change(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    capfd.readouterr()

    interface = await client.put(
        "/api/v1/settings/interface",
        headers=headers,
        json={"light_accent_color": "#123456", "dark_accent_color": "#abcdef"},
    )
    assert interface.status_code == 200, interface.text
    community = await client.put(
        "/api/v1/settings/community",
        headers=headers,
        json={"community_directory_enabled": True},
    )
    assert community.status_code == 200, community.text
    lifetime = await client.patch(
        "/api/v1/settings/auth/platform",
        headers=headers,
        json={"session_max_hours": 72},
    )
    assert lifetime.status_code == 200, lifetime.text

    rows = emitted(capfd, AuditEventType.PLATFORM_SETTINGS_CHANGED)
    assert _areas(rows) == ["interface", "community", "session_lifetime"]
    assert {row["actor_user_id"] for row in rows} == {owner_id}
    # Nothing here belongs to a guild or is done to an account.
    assert {
        (row["guild_id"], row["target_user_id"], row["target"]) for row in rows
    } == {(None, None, None)}

    colours, directory, hours = (row["detail"] for row in rows)
    # Accents are strings: named, never copied.
    assert set(colours["changed"]) == {"light_accent_color", "dark_accent_color"}
    assert colours["values"] == {}
    assert directory["values"]["community_directory_enabled"] == {
        "from": False,
        "to": True,
    }
    assert hours["values"]["session_max_hours"] == {"from": None, "to": 72}


async def test_an_email_change_says_whether_the_password_moved(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    capfd.readouterr()

    first = await client.put(
        "/api/v1/settings/email",
        headers=headers,
        json={**_EMAIL, "password": SMTP_PASSWORD},
    )
    assert first.status_code == 200, first.text
    # The same host again, with no password sent: nothing moves at all.
    again = await client.put("/api/v1/settings/email", headers=headers, json=_EMAIL)
    assert again.status_code == 200, again.text

    rows = emitted(capfd, AuditEventType.PLATFORM_SETTINGS_CHANGED)
    assert _areas(rows) == ["email"]
    assert rows[0]["actor_user_id"] == owner_id
    detail = rows[0]["detail"]
    assert detail["secret_changed"] is True
    assert {"smtp_host", "smtp_username", "smtp_password_encrypted"} <= set(
        detail["changed"]
    )
    assert detail["values"]["smtp_port"] == {"from": None, "to": 587}
    assert "smtp_host" not in detail["values"]
    assert SMTP_PASSWORD not in json.dumps(rows[0])


async def test_a_storage_change_says_whether_the_key_moved(
    client: AsyncClient, session: AsyncSession, capfd
):
    _, headers = await _owner(session)
    capfd.readouterr()

    stored = await client.put(
        "/api/v1/settings/storage",
        headers=headers,
        json={
            "backend": "local",
            "s3_bucket": "uploads",
            "s3_access_key_id": "AKIAEXAMPLE",
            "s3_secret_access_key": S3_SECRET,
        },
    )
    assert stored.status_code == 200, stored.text

    rows = emitted(capfd, AuditEventType.PLATFORM_SETTINGS_CHANGED)
    assert _areas(rows) == ["storage"]
    detail = rows[0]["detail"]
    assert detail["secret_changed"] is True
    assert {"s3_bucket", "s3_access_key_id", "s3_secret_access_key_encrypted"} <= set(
        detail["changed"]
    )
    written = json.dumps(rows[0])
    assert S3_SECRET not in written
    assert "AKIAEXAMPLE" not in written


async def test_a_write_that_changes_nothing_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    _, headers = await _owner(session)
    payload = {"light_accent_color": "#123456", "dark_accent_color": "#abcdef"}

    assert (
        await client.put("/api/v1/settings/interface", headers=headers, json=payload)
    ).status_code == 200
    capfd.readouterr()
    assert (
        await client.put("/api/v1/settings/interface", headers=headers, json=payload)
    ).status_code == 200

    assert emitted(capfd, AuditEventType.PLATFORM_SETTINGS_CHANGED) == []


async def test_a_refused_settings_write_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    member = await create_user(session, role=UserRole.member)
    capfd.readouterr()

    refused = await client.put(
        "/api/v1/settings/interface",
        headers=get_auth_headers(member),
        json={"light_accent_color": "#000000", "dark_accent_color": "#ffffff"},
    )
    assert refused.status_code == 403

    assert emitted(capfd, AuditEventType.PLATFORM_SETTINGS_CHANGED) == []


# --- what an operator sets for one community ---------------------------------


async def test_caps_and_status_are_recorded_against_the_community(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    guild = await create_guild(session)
    guild_id = guild.id
    capfd.readouterr()

    capped = await client.patch(
        f"/api/v1/settings/communities/{guild_id}",
        headers=headers,
        json={"max_users": 7},
    )
    assert capped.status_code == 200, capped.text
    suspended = await client.patch(
        f"/api/v1/settings/communities/{guild_id}",
        headers=headers,
        json={"status": "read_only"},
    )
    assert suspended.status_code == 200, suspended.text

    written = emitted(capfd)
    settings_rows = _of_type(written, AuditEventType.GUILD_SETTINGS_CHANGED)
    assert [
        (r["actor_user_id"], r["guild_id"], r["target"]) for r in settings_rows
    ] == [(owner_id, guild_id, {"type": "guild", "id": guild_id})]
    detail = settings_rows[0]["detail"]
    assert detail["area"] == "administration"
    assert detail["changed"] == ["max_users"]
    assert detail["values"]["max_users"] == {"from": None, "to": 7}

    status_rows = _of_type(written, AuditEventType.GUILD_STATUS_CHANGED)
    assert [
        (r["actor_user_id"], r["guild_id"], r["target"]["id"]) for r in status_rows
    ] == [(owner_id, guild_id, guild_id)]
    assert status_rows[0]["detail"] == {
        "from": "active",
        "to": "read_only",
    }


async def test_setting_a_cap_to_what_it_already_is_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    _, headers = await _owner(session)
    guild = await create_guild(session)
    capfd.readouterr()

    for _ in range(2):
        response = await client.patch(
            f"/api/v1/settings/communities/{guild.id}",
            headers=headers,
            json={"max_users": 7},
        )
        assert response.status_code == 200, response.text

    written = emitted(capfd)
    assert len(_of_type(written, AuditEventType.GUILD_SETTINGS_CHANGED)) == 1
    assert _of_type(written, AuditEventType.GUILD_STATUS_CHANGED) == []
