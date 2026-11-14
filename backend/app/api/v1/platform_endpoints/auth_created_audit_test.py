"""Where an account comes from, written down once.

Three doors lead to a new account — somebody registers, an identity provider
vouches for somebody nobody has seen before, or the deployment seeds its first
owner — and all three leave the same record, told apart by ``detail.via``. What
the record never carries is the address or the name the account arrived with.
"""

from __future__ import annotations

import json

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.auth_test import (
    _enable_platform_oidc,
    _run_oidc_flow,
    _wire_fake_idp,
)
from app.core.audit_events import AuditEventType
from app.testing import emitted
from app.testing.factories import create_user

REGISTERED_EMAIL = "registered-audit@example.com"


def _registration(email: str = REGISTERED_EMAIL) -> dict:
    return {
        "email": email,
        "username": "registered-audit",
        "password": "securepassword123",
    }


async def test_registering_records_the_account_and_how_it_arrived(
    client: AsyncClient, capfd
):
    capfd.readouterr()
    registered = await client.post("/api/v1/auth/register", json=_registration())
    assert registered.status_code == 201, registered.text
    user_id = registered.json()["id"]

    rows = emitted(capfd, AuditEventType.USER_CREATED)
    # The account is both who did it and who it was done to: nobody else was
    # involved.
    assert [(r["actor_user_id"], r["target_user_id"], r["guild_id"]) for r in rows] == [
        (user_id, user_id, None)
    ]
    assert rows[0]["detail"] == {
        "via": "registration",
        "first_user": True,
        "invited": False,
    }
    written = json.dumps(rows[0])
    assert REGISTERED_EMAIL not in written
    assert "Registered Person" not in written


async def test_an_account_after_the_first_is_recorded_as_one(
    client: AsyncClient, session: AsyncSession, capfd
):
    await create_user(session, email="already-here@example.com")
    capfd.readouterr()

    registered = await client.post("/api/v1/auth/register", json=_registration())
    assert registered.status_code == 201, registered.text

    rows = emitted(capfd, AuditEventType.USER_CREATED)
    assert [r["detail"]["first_user"] for r in rows] == [False]


async def test_a_refused_registration_records_nothing(
    client: AsyncClient, session: AsyncSession, capfd
):
    await create_user(session, email=REGISTERED_EMAIL)
    capfd.readouterr()

    refused = await client.post("/api/v1/auth/register", json=_registration())
    assert refused.status_code == 400
    assert refused.json()["detail"] == "EMAIL_ALREADY_REGISTERED"

    assert emitted(capfd, AuditEventType.USER_CREATED) == []


async def test_a_first_arrival_through_a_provider_records_which_one(
    client: AsyncClient, session: AsyncSession, monkeypatch, capfd
):
    from app.services.auth.platform_provider import get_platform_provider

    await _enable_platform_oidc(session)
    provider = await get_platform_provider(session)
    provider_id = provider.id
    from app.testing.oidc import FakeIdp

    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)
    capfd.readouterr()

    arrived = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "sso-arrival@example.com",
            "username": "sso-arrival",
            "email_verified": True,
        },
    )
    assert arrived.status_code in (302, 307)

    rows = emitted(capfd, AuditEventType.USER_CREATED)
    assert len(rows) == 1
    assert rows[0]["actor_user_id"] == rows[0]["target_user_id"] is not None
    assert rows[0]["detail"] == {"via": "sso", "provider_id": provider_id}
    assert "sso-arrival@example.com" not in json.dumps(rows[0])


async def test_a_second_sign_in_through_the_same_provider_creates_nobody(
    client: AsyncClient, session: AsyncSession, monkeypatch, capfd
):
    """The record is for an account arriving, not for a sign-in."""
    from app.testing.oidc import FakeIdp

    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)
    claims = {
        "email": "sso-returning@example.com",
        "username": "sso-returning",
        "email_verified": True,
    }
    capfd.readouterr()

    first = await _run_oidc_flow(client, idp, id_token_claims=claims)
    assert first.status_code in (302, 307)
    second = await _run_oidc_flow(client, idp, id_token_claims=claims)
    assert second.status_code in (302, 307)

    rows = emitted(capfd, AuditEventType.USER_CREATED)
    assert len(rows) == 1
