"""FOSS-balance invariants for the billing boundary.

The governing principle: the FOSS app **enforces numbers, never plans**.
With billing unconfigured (the self-host default — every ``BILLING_*``
setting unset) the app behaves exactly as if billing did not exist, and
even with billing rows present the operator surface keeps full authority
over the caps it governs. Pinned here:

1. billing absent = billing off, nothing else changes (endpoints 503;
   guild lifecycle and cap enforcement work; nothing is sent to billing —
   see ``billing_ping_test.py`` — and its change log is not written);
2. ``tier_name`` is never an enforcement input (static scan);
3. operator sovereignty — ``PATCH /settings/communities/{id}`` still fully
   controls caps/status on a guild that has billing metadata;
4. no pricing data in the repo (the rule lives in the billing service
   module docstring; the scan here keeps tier_name from leaking into
   enforcement, where plan awareness would start).

Unlike ``billing_test.py``, this module does NOT configure the billing
envelope — it runs in the self-host default state.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.billing import BillingEventLog
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.services.platform import guilds as guilds_service
from app.services.platform.guilds import GuildCapacityError
from app.testing import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    guild_administration,
)


def test_billing_settings_default_off():
    """The self-host default: every billing credential/URL is unset."""
    assert settings.BILLING_PUBLIC_KEY_PEM is None
    assert settings.BILLING_STATEMENT_PUBLIC_KEY_PEM is None
    assert settings.BILLING_SERVICE_URL is None


@pytest.mark.parametrize(
    "endpoint",
    ["communities/sync", "statements", "communities/read", "notices", "changes"],
)
async def test_unconfigured_endpoints_fail_closed_503(
    client: AsyncClient, session: AsyncSession, endpoint: str
):
    """Every billing endpoint answers 503 (fail closed, retryable) on a
    self-host — including for a completely unsigned request."""
    guild = await create_guild(session)
    response = await client.post(
        f"/api/v1/billing/{endpoint}",
        content=json.dumps({"guild_id": guild.id}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "BILLING_NOT_CONFIGURED"


async def test_partial_configuration_still_fails_closed(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """One key without the other is still OFF — no half-open state."""
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings, "BILLING_STATEMENT_PUBLIC_KEY_PEM", "half"
    )
    guild = await create_guild(session)
    response = await client.post(
        "/api/v1/billing/communities/sync",
        content=json.dumps({"guild_id": guild.id}).encode(),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "BILLING_NOT_CONFIGURED"


async def test_cap_enforcement_works_with_billing_absent(session: AsyncSession):
    """Numeric enforcement is billing-independent: an operator-set
    ``max_users`` refuses a join with no BILLING_* configured."""
    guild = await create_guild(session, max_users=1)
    first = await create_user(session, email="foss-cap-1@example.com")
    await guilds_service.ensure_membership(session, guild_id=guild.id, user_id=first.id)
    await session.commit()

    second = await create_user(session, email="foss-cap-2@example.com")
    with pytest.raises(GuildCapacityError):
        await guilds_service.ensure_membership(
            session, guild_id=guild.id, user_id=second.id
        )
    await session.rollback()


async def test_operator_keeps_full_authority_over_billed_guild(
    client: AsyncClient, session: AsyncSession
):
    """Billing holds no exclusive lock: on a guild with a tier label and
    billing audit rows, the operator surface still sets caps and status."""
    owner = await create_user(
        session, email="owner-foss-sov@example.com", role=UserRole.owner
    )
    guild = await create_guild(session, creator=owner, tier_name="gold")
    await create_guild_membership(
        session, user=owner, guild=guild, role=CommunityRole.admin
    )
    session.add(
        BillingEventLog(
            event_id="evt-foss-sov",
            guild_id=guild.id,
            op="community_notice",
            source="billing",
            applied_at=guild.created_at,
        )
    )
    await session.commit()
    headers = get_auth_headers(owner)

    caps = await client.patch(
        f"/api/v1/settings/communities/{guild.id}",
        json={"max_storage_bytes": 123_456, "max_users": 7},
        headers=headers,
    )
    assert caps.status_code == 200, caps.text
    assert caps.json()["max_storage_bytes"] == 123_456
    assert caps.json()["max_users"] == 7

    status_change = await client.patch(
        f"/api/v1/settings/communities/{guild.id}",
        json={"status": "read_only"},
        headers=headers,
    )
    assert status_change.status_code == 200, status_change.text
    assert status_change.json()["status"] == "read_only"

    await session.refresh(guild)
    administration = await guild_administration(session, guild)
    await session.refresh(administration)
    assert administration.tier_name == "gold"  # display metadata survives, untouched


# --- tier_name is never an enforcement input --------------------------------

# The complete surface allowed to mention tier_name. Everything else in
# app/ — enforcement, services, deps, quota checks — must not: enforcement
# reads only max_storage_bytes / max_users / status. The display read
# (CommunityRead + its serializer) is allowed — it renders the plan label, it does
# not gate anything.
_TIER_NAME_ALLOWED = {
    "models/platform/guild_administration.py",  # the column + its contract
    "testing/factories.py",  # routes the override to the administration row
    "models/platform/billing.py",  # audit vocabulary docstrings
    "schemas/platform/billing.py",  # the billing payloads
    "services/platform/billing.py",  # the boundary write
    "api/v1/platform_endpoints/billing.py",  # the boundary endpoints
    # The plan summary billing answers for the seat's Billing tab: read per
    # request, returned for display, kept nowhere.
    "services/platform/billing_ping.py",
    "schemas/platform/guild.py",  # CommunityRead display field
    "api/v1/platform_endpoints/guilds.py",  # _serialize_guild passes it through
    # The operator's guild list shows the label next to the caps it does NOT
    # set; both uses build PlatformCommunityStorageRead and read nothing from it.
    "api/v1/platform_endpoints/settings.py",
}


@pytest.mark.always
def test_tier_name_confined_to_the_billing_surface():
    app_dir = Path(__file__).resolve().parents[3]
    assert app_dir.name == "app"
    offenders: list[str] = []
    pattern = re.compile(r"\btier_name\b")
    for path in sorted(app_dir.rglob("*.py")):
        rel = path.relative_to(app_dir).as_posix()
        if rel in _TIER_NAME_ALLOWED or rel.endswith("_test.py"):
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert not offenders, (
        "tier_name leaked outside the billing surface — it is display/audit "
        f"metadata and must never become an enforcement input: {offenders}"
    )
