"""The Guilds tab where the billing service sets each community's plan.

The caps and entitlements are shown and not set, the one status change is a
suspension, deleting goes through the community, and a restore returns it to
billing's status or a suspension. The database holds the same rule (``app/db/billing_managed_test.py``); these hold the endpoints to it,
and to the answers they give when refusing.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.break_glass_test import _enrol_factor, _next_code
from app.models.platform.guild import CommunityRole
from app.testing import create_guild, create_guild_membership, create_user
from app.testing.billing_managed import billing_manages_plans

GUILDS = "/api/v1/settings/communities"


def _billing_sets_plans(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example.com")
    monkeypatch.setattr(settings, "BILLING_PUBLIC_KEY_PEM", "test-public-key")
    monkeypatch.setattr(
        settings, "BILLING_STATEMENT_PUBLIC_KEY_PEM", "test-statement-key"
    )


async def _record(session: AsyncSession, guild_id: int, status: str) -> None:
    await session.exec(
        text(
            "UPDATE public.guild_administration SET billing_status = :s"
            " WHERE guild_id = :g"
        ).bindparams(s=status, g=guild_id)
    )
    await session.commit()


async def _row(client: AsyncClient, headers: dict, guild_id: int) -> dict:
    resp = await client.get(GUILDS, headers=headers)
    assert resp.status_code == 200, resp.text
    return next(row for row in resp.json()["items"] if row["id"] == guild_id)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"max_users": 10}, id="member-cap"),
        pytest.param({"max_storage_bytes": 1024}, id="storage-cap"),
        pytest.param({"auth_options": ["providers"]}, id="sign-in"),
        pytest.param({"banner_image_enabled": False}, id="banner"),
        pytest.param({"support_enabled": False}, id="help"),
    ],
)
async def test_the_plan_is_billings_to_set(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, body
):
    operator = await acting_user("operator")
    guild_id = (await create_guild(session)).id
    _billing_sets_plans(monkeypatch)

    async with billing_manages_plans(session):
        resp = await client.patch(
            f"{GUILDS}/{guild_id}", json=body, headers=operator.headers
        )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "COMMUNITY_PLAN_SET_BY_BILLING"


async def test_the_operator_sets_the_plan_where_billing_does_not(
    client: AsyncClient, session: AsyncSession, acting_user
):
    operator = await acting_user("operator")
    guild_id = (await create_guild(session)).id

    resp = await client.patch(
        f"{GUILDS}/{guild_id}", json={"max_users": 10}, headers=operator.headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["max_users"] == 10
    assert resp.json()["status_choices"] == [
        "active",
        "read_only",
        "on_hold",
        "suspended",
    ]


async def test_a_suspension_lifts_to_what_billing_last_said(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    operator = await acting_user("operator")
    guild_id = (await create_guild(session)).id
    await _record(session, guild_id, "on_hold")
    _billing_sets_plans(monkeypatch)
    patch = f"{GUILDS}/{guild_id}"

    async with billing_manages_plans(session):
        assert (await _row(client, operator.headers, guild_id))["status_choices"] == [
            "active",
            "suspended",
        ]
        suspended = await client.patch(
            patch, json={"status": "suspended"}, headers=operator.headers
        )
        assert suspended.status_code == 200, suspended.text
        assert suspended.json()["status_choices"] == ["on_hold", "suspended"]

        elsewhere = await client.patch(
            patch, json={"status": "active"}, headers=operator.headers
        )
        assert elsewhere.status_code == 409, elsewhere.text
        assert elsewhere.json()["detail"] == "COMMUNITY_STATUS_SET_BY_BILLING"

        lifted = await client.patch(
            patch, json={"status": "on_hold"}, headers=operator.headers
        )
        assert lifted.status_code == 200, lifted.text
        assert lifted.json()["status"] == "on_hold"


@pytest.mark.parametrize("target", ["read_only", "on_hold"])
async def test_no_other_status_is_the_operators(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, target
):
    operator = await acting_user("operator")
    guild_id = (await create_guild(session)).id
    _billing_sets_plans(monkeypatch)

    async with billing_manages_plans(session):
        resp = await client.patch(
            f"{GUILDS}/{guild_id}", json={"status": target}, headers=operator.headers
        )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "COMMUNITY_STATUS_SET_BY_BILLING"


@pytest.mark.parametrize("managed", [True, False])
async def test_the_app_says_whether_billing_sets_plans(
    client: AsyncClient, monkeypatch, managed
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example.com")
    if managed:
        _billing_sets_plans(monkeypatch)

    resp = await client.get("/api/v1/config")

    assert resp.status_code == 200, resp.text
    assert resp.json()["billing"]["manages_plans"] is managed


async def test_the_billing_grant_takes_the_second_factor(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    monkeypatch,
    handoff_signing_key,
):
    """Issued once, after the account's own factor; reused without it while it
    lasts."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example.com")
    operator = await acting_user("operator")
    secret, _codes = await _enrol_factor(client, session, operator)
    guild_id = (await create_guild(session)).id
    handoff = f"{GUILDS}/{guild_id}/billing/service-handoff"

    bare = await client.post(handoff, headers=operator.headers)
    assert bare.status_code == 401, bare.text
    assert bare.json()["detail"] == "ACCESS_GRANT_SECOND_FACTOR_REQUIRED"

    answered = await client.post(
        handoff, json={"code": _next_code(secret)}, headers=operator.headers
    )
    assert answered.status_code == 200, answered.text

    reused = await client.post(handoff, headers=operator.headers)
    assert reused.status_code == 200, reused.text


async def _deleted_at(session: AsyncSession, recorded: str) -> int:
    """A deleted community whose seat survived, billing having last set
    ``recorded``."""
    seat = await create_user(session)
    guild = await create_guild(session, creator=seat)
    assert guild.id is not None
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await _record(session, guild.id, recorded)
    await session.exec(
        text("UPDATE public.guilds SET status = 'deleted' WHERE id = :g").bindparams(
            g=guild.id
        )
    )
    await session.commit()
    return guild.id


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"status": "active"}, id="active"),
        pytest.param({}, id="default"),
    ],
)
async def test_a_restore_does_not_lift_what_billing_set(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, body
):
    operator = await acting_user("operator")
    guild_id = await _deleted_at(session, "read_only")
    _billing_sets_plans(monkeypatch)

    async with billing_manages_plans(session):
        resp = await client.post(
            f"{GUILDS}/{guild_id}/restore", json=body, headers=operator.headers
        )

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "COMMUNITY_RESTORE_STATUS_SET_BY_BILLING"


@pytest.mark.parametrize("target", ["read_only", "suspended"])
async def test_a_restore_returns_to_billings_status_or_a_suspension(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, target
):
    operator = await acting_user("operator")
    guild_id = await _deleted_at(session, "read_only")
    _billing_sets_plans(monkeypatch)

    async with billing_manages_plans(session):
        resp = await client.post(
            f"{GUILDS}/{guild_id}/restore",
            json={"status": target},
            headers=operator.headers,
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == target


@pytest.mark.parametrize("target", ["active", "read_only", "on_hold", "suspended"])
async def test_a_restore_lands_anywhere_where_billing_does_not_set_plans(
    client: AsyncClient, session: AsyncSession, acting_user, target
):
    operator = await acting_user("operator")
    guild_id = await _deleted_at(session, "read_only")

    resp = await client.post(
        f"{GUILDS}/{guild_id}/restore",
        json={"status": target},
        headers=operator.headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == target
