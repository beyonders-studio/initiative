"""What the login-provider registry writes down.

A provider is a way into the deployment, so every change to one is a record:
which fields moved, and whether the client secret moved with them. The value
never does — the register holds the secret, and the log holds the fact that it
changed.
"""

from __future__ import annotations

import json

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.user import UserRole
from app.testing import emitted
from app.testing.factories import create_auth_provider, create_user, get_auth_headers

BASE = "/api/v1/settings/auth/providers/"
SECRET = "s3cret-value"
ISSUER = "https://idp.example.com"

_CREATE = {
    "slug": "corp",
    "display_name": "Corp SSO",
    "issuer": ISSUER,
    "client_id": "client-123",
    "client_secret": SECRET,
}


async def _owner(session: AsyncSession) -> tuple[int | None, dict[str, str]]:
    """The one tier that reaches this surface, as an id and its headers."""
    owner = await create_user(session, role=UserRole.owner)
    return owner.id, get_auth_headers(owner)


async def test_creating_a_provider_names_its_fields_and_that_a_secret_was_set(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    capfd.readouterr()

    created = await client.post(BASE, headers=headers, json=_CREATE)
    assert created.status_code == 201, created.text
    provider_id = created.json()["id"]

    rows = emitted(capfd, AuditEventType.AUTH_PROVIDER_CREATED)
    assert [(r["actor_user_id"], r["target"]) for r in rows] == [
        (owner_id, {"type": "auth_provider", "id": provider_id})
    ]
    detail = rows[0]["detail"]
    assert detail["secret_set"] is True
    # Every field the row was born with is named; only the ones whose type
    # rules out a secret carry a value.
    assert {"display_name", "issuer", "client_id", "enabled"} <= set(detail["changed"])
    assert detail["values"]["enabled"] == {"from": None, "to": True}
    assert "display_name" not in detail["values"]
    assert "issuer" not in detail["values"]


async def test_editing_a_provider_records_what_moved_and_whether_the_secret_did(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="edited")
    provider_id = provider.id
    capfd.readouterr()

    edited = await client.patch(
        f"{BASE}{provider_id}",
        headers=headers,
        json={"enabled": False, "client_secret": "rotated-secret"},
    )
    assert edited.status_code == 200, edited.text

    rows = emitted(capfd, AuditEventType.AUTH_PROVIDER_UPDATED)
    assert [(r["actor_user_id"], r["target"]["id"]) for r in rows] == [
        (owner_id, provider_id)
    ]
    detail = rows[0]["detail"]
    assert detail["changed"] == ["enabled"]
    assert detail["values"]["enabled"] == {"from": True, "to": False}
    assert detail["secret_changed"] is True


async def test_an_edit_that_changes_nothing_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    """A no-op write is not a change, so it leaves no record."""
    _, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="unchanged")
    capfd.readouterr()

    same = await client.patch(
        f"{BASE}{provider.id}",
        headers=headers,
        json={"display_name": provider.display_name, "enabled": provider.enabled},
    )
    assert same.status_code == 200, same.text

    assert emitted(capfd, AuditEventType.AUTH_PROVIDER_UPDATED) == []


async def test_a_refused_request_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    member = await create_user(session, role=UserRole.member)
    provider = await create_auth_provider(session, slug="refused")
    capfd.readouterr()

    refused = await client.patch(
        f"{BASE}{provider.id}",
        headers=get_auth_headers(member),
        json={"enabled": False},
    )
    assert refused.status_code == 403

    assert emitted(capfd, AuditEventType.AUTH_PROVIDER_UPDATED) == []


async def test_deleting_a_provider_records_the_kind_it_was(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="gone")
    provider_id = provider.id
    capfd.readouterr()

    gone = await client.delete(f"{BASE}{provider_id}", headers=headers)
    assert gone.status_code == 204, gone.text

    rows = emitted(capfd, AuditEventType.AUTH_PROVIDER_DELETED)
    assert [(r["actor_user_id"], r["target"]) for r in rows] == [
        (owner_id, {"type": "auth_provider", "id": provider_id})
    ]
    assert rows[0]["detail"] == {"kind": "oidc"}


async def test_the_deployments_own_answer_is_recorded_set_and_withdrawn(
    client: AsyncClient, session: AsyncSession, capfd
):
    owner_id, headers = await _owner(session)
    provider = await create_auth_provider(session, slug="answered")
    provider_id = provider.id
    capfd.readouterr()

    answered = await client.put(
        f"{BASE}{provider_id}/default",
        headers=headers,
        json={"claim": "hd", "claim_values": ["morels.me"], "enabled": True},
    )
    assert answered.status_code == 200, answered.text
    withdrawn = await client.delete(f"{BASE}{provider_id}/default", headers=headers)
    assert withdrawn.status_code == 204, withdrawn.text

    written = emitted(capfd)
    rows = [
        row
        for row in written
        if row["event_type"] == AuditEventType.AUTH_PROVIDER_DEFAULT_SET.value
    ]
    assert [(r["actor_user_id"], r["target"]) for r in rows] == [
        (owner_id, {"type": "auth_provider", "id": provider_id})
    ]
    detail = rows[0]["detail"]
    assert {"claim", "claim_values", "enabled"} == set(detail["changed"])
    # Which claim, and which of its values count, are strings: named, never
    # copied.
    assert set(detail["values"]) == {"enabled"}

    cleared = [
        row
        for row in written
        if row["event_type"] == AuditEventType.AUTH_PROVIDER_DEFAULT_CLEARED.value
    ]
    assert [(r["actor_user_id"], r["target"]["id"]) for r in cleared] == [
        (owner_id, provider_id)
    ]
    assert cleared[0]["detail"] == {}


async def test_no_record_of_a_provider_ever_carries_its_secret(
    client: AsyncClient, session: AsyncSession, capfd
):
    _, headers = await _owner(session)
    capfd.readouterr()

    created = await client.post(BASE, headers=headers, json=_CREATE)
    assert created.status_code == 201, created.text
    provider_id = created.json()["id"]
    rotated = await client.patch(
        f"{BASE}{provider_id}",
        headers=headers,
        json={"client_secret": SECRET, "display_name": "Renamed"},
    )
    assert rotated.status_code == 200, rotated.text

    envelopes = [
        row
        for row in emitted(capfd)
        if row["event_type"]
        in {
            AuditEventType.AUTH_PROVIDER_CREATED.value,
            AuditEventType.AUTH_PROVIDER_UPDATED.value,
        }
    ]
    assert envelopes
    for envelope in envelopes:
        written = json.dumps(envelope)
        assert SECRET not in written
        assert ISSUER not in written
