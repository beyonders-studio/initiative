"""What a community's own sign-in configuration writes down.

Two halves of one sentence, and both are recorded against the community they
are about: which provider its people come in through, and where the groups
that provider asserts land. Every record carries ``guild_id``, which is the
column a community's log is read by.
"""

from __future__ import annotations

import json

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole, Guild
from app.testing import emitted
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_guild_provider_connection,
    create_user,
    get_auth_headers,
)

TENANT_CLAIM_VALUE = "morels.me"
GROUP_CLAIM_VALUE = "eng-team"


async def _seat(session: AsyncSession) -> tuple[int | None, Guild, dict[str, str]]:
    """A community and the seat that decides who may enter it."""
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.superadmin
    )
    return admin.id, guild, get_auth_headers(admin)


def _connections(guild_id: int) -> str:
    return f"/api/v1/communities/{guild_id}/auth/connections"


def _rules(guild_id: int) -> str:
    return f"/api/v1/communities/{guild_id}/auth/rules"


def _of_type(written: list[dict], event_type: AuditEventType) -> list[dict]:
    return [row for row in written if row["event_type"] == event_type.value]


# --- connections -------------------------------------------------------------


async def test_connecting_narrowing_and_disconnecting_are_each_recorded(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin_id, guild, headers = await _seat(session)
    guild_id = guild.id
    provider = await create_auth_provider(session, slug="google")
    provider_id = provider.id
    capfd.readouterr()

    connected = await client.post(
        _connections(guild_id),
        headers=headers,
        json={
            "provider_id": provider_id,
            "claim": "hd",
            "claim_values": [TENANT_CLAIM_VALUE],
        },
    )
    assert connected.status_code == 201, connected.text
    connection_id = connected.json()["id"]

    narrowed = await client.patch(
        f"{_connections(guild_id)}/{connection_id}",
        headers=headers,
        json={"auto_join": True},
    )
    assert narrowed.status_code == 200, narrowed.text
    gone = await client.delete(
        f"{_connections(guild_id)}/{connection_id}", headers=headers
    )
    assert gone.status_code == 204, gone.text

    written = emitted(capfd)
    for event in (
        AuditEventType.GUILD_PROVIDER_CONNECTED,
        AuditEventType.GUILD_PROVIDER_CONNECTION_UPDATED,
        AuditEventType.GUILD_PROVIDER_DISCONNECTED,
    ):
        rows = _of_type(written, event)
        assert [(r["actor_user_id"], r["guild_id"], r["target"]) for r in rows] == [
            (
                admin_id,
                guild_id,
                {"type": "guild_provider_connection", "id": connection_id},
            )
        ], event
        assert rows[0]["detail"]["provider_id"] == provider_id

    born = _of_type(written, AuditEventType.GUILD_PROVIDER_CONNECTED)[0]
    detail = born["detail"]
    assert {"provider_id", "claim", "claim_values", "enabled"} <= set(detail["changed"])
    # The claim and the values that count are strings: named, never copied.
    assert "claim" not in detail["values"]
    assert "claim_values" not in detail["values"]
    assert detail["values"]["enabled"] == {"from": None, "to": True}
    assert TENANT_CLAIM_VALUE not in json.dumps(born)

    updated = AuditEventType.GUILD_PROVIDER_CONNECTION_UPDATED
    moved = _of_type(written, updated)[0]
    assert moved["detail"]["changed"] == ["auto_join"]
    assert moved["detail"]["values"]["auto_join"] == {
        "from": False,
        "to": True,
    }


async def test_a_connection_edit_that_changes_nothing_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    _, guild, headers = await _seat(session)
    provider = await create_auth_provider(session, slug="google")
    connection = await create_guild_provider_connection(
        session, guild=guild, provider=provider
    )
    capfd.readouterr()

    same = await client.patch(
        f"{_connections(guild.id)}/{connection.id}",
        headers=headers,
        json={"enabled": True, "auto_join": False},
    )
    assert same.status_code == 200, same.text

    assert emitted(capfd, AuditEventType.GUILD_PROVIDER_CONNECTION_UPDATED) == []


async def test_a_refused_connection_write_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    """Running a community is not the seat that decides who may enter it."""
    _, guild, _ = await _seat(session)
    ordinary = await create_user(session)
    await create_guild_membership(
        session, user=ordinary, guild=guild, role=CommunityRole.admin
    )
    provider = await create_auth_provider(session, slug="google")
    capfd.readouterr()

    refused = await client.post(
        _connections(guild.id),
        headers=get_auth_headers(ordinary),
        json={"provider_id": provider.id},
    )
    assert refused.status_code == 403, refused.text

    assert emitted(capfd, AuditEventType.GUILD_PROVIDER_CONNECTED) == []


# --- the rules riding a connection -------------------------------------------


async def test_a_communitys_own_rule_is_recorded_through_its_life(
    client: AsyncClient, session: AsyncSession, capfd
):
    admin_id, guild, headers = await _seat(session)
    guild_id = guild.id
    provider = await create_auth_provider(
        session, slug="entra", role_claim_path="groups"
    )
    provider_id = provider.id
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    capfd.readouterr()

    created = await client.post(
        _rules(guild_id),
        headers=headers,
        json={
            "provider_id": provider_id,
            "claim_value": GROUP_CLAIM_VALUE,
            "community_role": "member",
        },
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    gone = await client.delete(f"{_rules(guild_id)}/{rule_id}", headers=headers)
    assert gone.status_code == 204, gone.text

    written = emitted(capfd)
    for event in (
        AuditEventType.CLAIM_RULE_CREATED,
        AuditEventType.CLAIM_RULE_DELETED,
    ):
        rows = _of_type(written, event)
        assert [(r["actor_user_id"], r["guild_id"], r["target"]) for r in rows] == [
            (admin_id, guild_id, {"type": "claim_rule", "id": rule_id})
        ], event
        # Recorded as written from the community's own surface.
        assert rows[0]["detail"]["via"] == "guild"

    born = _of_type(written, AuditEventType.CLAIM_RULE_CREATED)[0]
    assert GROUP_CLAIM_VALUE not in json.dumps(born)
    assert born["detail"]["values"]["provider_id"] == {
        "from": None,
        "to": provider_id,
    }
