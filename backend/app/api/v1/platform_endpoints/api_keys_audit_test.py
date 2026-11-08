"""A personal API key arriving and leaving.

The key is the account's own credential, so it is both actor and subject. The
record carries its scope and never the key — not its name, not its prefix, not
its hash.
"""

from __future__ import annotations

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.testing import emitted
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


async def test_minting_and_dropping_a_key_are_both_recorded(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await create_user(session)
    user_id = user.id
    headers = get_auth_headers(user)
    capfd.readouterr()

    minted = await client.post(
        "/api/v1/me/api-keys", headers=headers, json={"name": "laptop"}
    )
    assert minted.status_code == 201, minted.text
    key_id = minted.json()["api_key"]["id"]

    created = emitted(capfd, AuditEventType.API_KEY_CREATED)
    assert [_where(row) for row in created] == [
        (user_id, user_id, None, {"type": "user_api_key", "id": key_id})
    ]
    assert created[0]["detail"] == {
        "read_only": False,
        "expires_at": None,
        "guild_bound": False,
        "resource_type": None,
    }
    # What the key is called is the account's business, not the log's.
    assert "name" not in created[0]["detail"]

    dropped = await client.delete(f"/api/v1/me/api-keys/{key_id}", headers=headers)
    assert dropped.status_code == 204, dropped.text

    deleted = emitted(capfd, AuditEventType.API_KEY_DELETED)
    assert [_where(row) for row in deleted] == [
        (user_id, user_id, None, {"type": "user_api_key", "id": key_id})
    ]


async def test_a_key_bound_to_one_community_records_which(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await create_user(session)
    user_id = user.id
    guild = await create_guild(session)
    guild_id = guild.id
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    capfd.readouterr()

    minted = await client.post(
        "/api/v1/me/api-keys",
        headers=get_auth_headers(user),
        json={"name": "ci", "community_id": guild_id, "read_only": True},
    )
    assert minted.status_code == 201, minted.text
    key_id = minted.json()["api_key"]["id"]

    created = emitted(capfd, AuditEventType.API_KEY_CREATED)
    assert [_where(row) for row in created] == [
        (user_id, user_id, guild_id, {"type": "user_api_key", "id": key_id})
    ]
    assert created[0]["detail"] == {
        "read_only": True,
        "expires_at": None,
        "guild_bound": True,
        "resource_type": None,
    }


async def test_dropping_a_key_that_is_not_yours_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner = await create_user(session)
    other = await create_user(session)

    minted = await client.post(
        "/api/v1/me/api-keys",
        headers=get_auth_headers(owner),
        json={"name": "laptop"},
    )
    assert minted.status_code == 201, minted.text
    key_id = minted.json()["api_key"]["id"]
    capfd.readouterr()

    refused = await client.delete(
        f"/api/v1/me/api-keys/{key_id}", headers=get_auth_headers(other)
    )
    assert refused.status_code == 404
    assert emitted(capfd, AuditEventType.API_KEY_DELETED) == []
