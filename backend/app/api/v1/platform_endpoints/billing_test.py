"""The billing boundary's envelope, and the sync and read verbs.

Pinned:

* the v2 envelope — a compact EdDSA JWS binding method, path and body hash,
  ``typ`` pinned, at most 60 seconds, used once — with a refusal test for
  every claim, the key bundle's rotation, and the self-host default (503);
* ``communities/sync``: a community takes billing's whole state at a version
  only when it's newer, and is answered with the version it holds; each item
  stands alone; a capability package replaces rather than merges; the pushed
  storage cap is the one uploads are held to; a suspension is never lifted;
  a hold tells the seat once;
* ``communities/read``: status, usage, members, guests, name, the version
  held and each statement's version, and nothing for a community that isn't
  there.
"""

from __future__ import annotations

import time

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing import community_plan
from app.core import config as config_module
from app.core.login_methods import LoginMethod
from app.models.platform.billing import BillingJti
from app.models.platform.guild import CommunityRole, CommunityStatus
from app.models.platform.guild_administration import GuildAdministration
from app.services.marketplace import plugin_entitlements
from app.services.platform import rules
from app.services.tenant.attachments import (
    StorageQuotaExceededError,
    enforce_storage_quota,
)
from app.testing import (
    billing_boundary,
    billing_guild_ref,
    create_guest,
    create_guild,
    create_guild_membership,
    create_upload,
    create_user,
    drain_notices,
)
from app.testing.schema_harness import route_session_to_guild

LISTING = "PAYDAPP0000001"


@pytest.fixture(autouse=True)
def _configure_billing(monkeypatch):
    billing_boundary.configure(monkeypatch)


def _fields(**over) -> dict:
    return {
        "tier_name": "Gold",
        "max_storage_bytes": 10 * 1024**3,
        "max_users": 50,
        "max_guests": 5,
        "feature_keys": [],
        "status": "active",
        **over,
    }


async def _sync(client: AsyncClient, *items: tuple[int, int, dict]):
    """Sync (guild id, version, fields) items; the response."""
    return await billing_boundary.post(
        client,
        "communities/sync",
        {
            "communities": [
                {
                    "community_ref": await billing_guild_ref(guild_id),
                    "version": version,
                    "fields": fields,
                }
                for guild_id, version, fields in items
            ]
        },
    )


async def _administration(session: AsyncSession, guild_id: int) -> GuildAdministration:
    session.expire_all()
    return (
        await session.exec(
            select(GuildAdministration).where(GuildAdministration.guild_id == guild_id)
        )
    ).one()


# --- the envelope --------------------------------------------------------------


async def test_unconfigured_boundary_refuses_everything(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(config_module.settings, "BILLING_PUBLIC_KEY_PEM", None)
    guild = await create_guild(session)
    response = await _sync(client, (guild.id, 1, _fields()))
    # 503, not 403: billing absent is the self-host default, not a caller
    # fault (see billing_foss_test.py for the full unconfigured surface).
    assert response.status_code == 503
    assert response.json()["detail"] == "BILLING_NOT_CONFIGURED"


async def test_an_unsigned_request_is_refused(client: AsyncClient):
    response = await client.post("/api/v1/billing/changes", json={})
    assert response.status_code == 403
    assert response.json()["detail"] == "BILLING_MISSING_SIGNATURE"


@pytest.mark.parametrize(
    ("claims", "detail"),
    [
        (
            {"private_pem": billing_boundary.OTHER_PRIVATE_PEM},
            "BILLING_BOUNDARY_INVALID",
        ),
        ({"typ": "JWT"}, "BILLING_BOUNDARY_WRONG_TYPE"),
        ({"aud": "initiative:billing"}, "BILLING_BOUNDARY_INVALID"),
        ({"iss": "initiative"}, "BILLING_BOUNDARY_INVALID"),
        ({"htp": "/api/v1/billing/communities/read"}, "BILLING_BOUNDARY_WRONG_REQUEST"),
        ({"htm": "GET"}, "BILLING_BOUNDARY_WRONG_REQUEST"),
        ({"bsh": "not-the-body"}, "BILLING_BOUNDARY_WRONG_BODY"),
        ({"exp": int(time.time()) + 3600}, "BILLING_BOUNDARY_LIFETIME"),
        (
            {"iat": int(time.time()) - 600, "exp": int(time.time()) - 540},
            "BILLING_BOUNDARY_EXPIRED",
        ),
        ({"jti": None}, "BILLING_BOUNDARY_INVALID"),
        ({"jti": "j" * 65}, "BILLING_BOUNDARY_INVALID"),
    ],
)
async def test_every_claim_is_held(client: AsyncClient, claims, detail):
    response = await billing_boundary.post(client, "changes", {}, **claims)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == detail


async def test_a_jti_is_used_once(client: AsyncClient, session: AsyncSession):
    first = await billing_boundary.post(client, "changes", {}, jti="once")
    again = await billing_boundary.post(client, "changes", {}, jti="once")
    assert first.status_code == 200, first.text
    assert again.status_code == 403
    assert again.json()["detail"] == "BILLING_REPLAYED_TOKEN"
    assert (
        await session.exec(select(BillingJti.jti).where(BillingJti.jti == "once"))
    ).all() == ["once"]


async def test_both_keys_verify_while_billing_rotates(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(
        config_module.settings,
        "BILLING_PUBLIC_KEY_PEM",
        billing_boundary.PUBLIC_PEM + billing_boundary.OTHER_PUBLIC_PEM,
    )
    for pem in (billing_boundary.PRIVATE_PEM, billing_boundary.OTHER_PRIVATE_PEM):
        response = await billing_boundary.post(client, "changes", {}, private_pem=pem)
        assert response.status_code == 200, response.text


async def test_an_unreadable_key_answers_503_not_403(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(config_module.settings, "BILLING_PUBLIC_KEY_PEM", "garbage")
    response = await billing_boundary.post(client, "changes", {})
    assert response.status_code == 503
    assert response.json()["detail"] == "BILLING_NOT_CONFIGURED"


async def test_a_malformed_batch_is_refused_after_verification(client: AsyncClient):
    response = await billing_boundary.post(
        client, "communities/sync", {"communities": []}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "BILLING_INVALID_PAYLOAD"


# --- communities/sync ----------------------------------------------------------


async def test_a_newer_version_lands_and_an_older_one_changes_nothing(
    client: AsyncClient, session: AsyncSession
):
    guild = await create_guild(session)
    guild_id = guild.id
    ref = await billing_guild_ref(guild_id)

    first = await _sync(client, (guild_id, 5, _fields(tier_name="Gold")))
    assert first.status_code == 200, first.text
    assert first.json() == {"results": [{"community_ref": ref, "version": 5}]}
    older = await _sync(client, (guild_id, 4, _fields(tier_name="Silver")))
    same = await _sync(client, (guild_id, 5, _fields(tier_name="Silver")))
    assert older.json() == same.json() == first.json()

    administration = await _administration(session, guild_id)
    assert (administration.tier_name, administration.billing_version) == ("Gold", 5)
    plan = await community_plan(session, guild_id)
    assert (plan["max_users"], plan["max_guests"]) == (50, 5)

    newer = await _sync(
        client, (guild_id, 9, _fields(tier_name="Silver", max_users=None))
    )
    assert newer.json()["results"] == [{"community_ref": ref, "version": 9}]
    administration = await _administration(session, guild_id)
    assert administration.tier_name == "Silver"
    assert (await community_plan(session, guild_id))["max_users"] is None


async def test_each_item_stands_alone(client: AsyncClient, session: AsyncSession):
    guild = await create_guild(session)
    ref = await billing_guild_ref(guild.id)
    response = await billing_boundary.post(
        client,
        "communities/sync",
        {
            "communities": [
                None,
                {"community_ref": "gbil_nobody", "version": 1, "fields": _fields()},
                {
                    "community_ref": ref,
                    "version": 1,
                    "fields": _fields(status="suspended"),
                },
                {"community_ref": ref, "version": 1, "fields": {"tier_name": "x"}},
                {"community_ref": ref, "version": 2, "fields": _fields()},
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"] == [
        {"community_ref": None, "error": "BILLING_INVALID_PAYLOAD"},
        {"community_ref": "gbil_nobody", "error": "BILLING_COMMUNITY_NOT_FOUND"},
        {"community_ref": ref, "error": "BILLING_INVALID_PAYLOAD"},
        {"community_ref": ref, "error": "BILLING_INVALID_PAYLOAD"},
        {"community_ref": ref, "version": 2},
    ]


async def test_a_capability_package_replaces_rather_than_merges(
    client: AsyncClient, session: AsyncSession
):
    """A downgrade is one write: a capability missing from the package is
    withdrawn by the same write that renamed the tier. A name this build
    can't enforce is ignored, not a reason to drop the caps beside it."""
    guild = await create_guild(session)
    guild_id = guild.id

    every = ["banner_image", "help_requests", "community_sign_in", "security_standards"]
    await _sync(client, (guild_id, 1, _fields(feature_keys=every)))
    plan = await community_plan(session, guild_id)
    assert all(plan[key] is True for key in every)

    await _sync(
        client, (guild_id, 2, _fields(feature_keys=["banner_image", "teleportation"]))
    )
    plan = await community_plan(session, guild_id)
    assert plan["banner_image"] is True
    assert not any(plan[key] for key in every if key != "banner_image")


async def test_the_deployments_rules_stand_over_the_seat_until_withdrawn(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A rule the sync sets wins over the community's own, is shown to its
    seat and refused from it; a sync without it gives the community back its
    own answer. A key this build doesn't know is ignored; one the plan's
    fields carry, or a value its rule doesn't take, refuses the item."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    guild_id = seat.guild.id
    settings_url = f"/api/v1/communities/{guild_id}/auth-settings"

    async def read() -> dict:
        response = await client.get(settings_url, headers=seat.headers)
        assert response.status_code == 200, response.text
        return response.json()

    restricted = _fields(feature_keys=["security_standards"])
    await _sync(client, (guild_id, 1, restricted))
    own = await client.patch(
        settings_url, headers=seat.headers, json={"allow_ai": False}
    )
    assert own.status_code == 200, own.text

    control = [{"key": "allow_ai", "value": True}, {"key": "teleport", "value": 1}]
    synced = await _sync(client, (guild_id, 2, {**restricted, "rules": control}))
    assert synced.json()["results"] == [
        {"community_ref": await billing_guild_ref(guild_id), "version": 2}
    ]
    held = await read()
    assert held["allow_ai"] is True
    assert held["set_by_deployment"] == ["allow_ai"]
    refused = await client.patch(
        settings_url, headers=seat.headers, json={"allow_ai": False}
    )
    assert refused.status_code == 409
    assert refused.json()["detail"] == "COMMUNITY_RULE_SET_BY_DEPLOYMENT"

    await _sync(client, (guild_id, 3, restricted))
    released = await read()
    assert released["allow_ai"] is False
    assert released["set_by_deployment"] == []

    for bad in (
        [{"key": "max_users", "value": 3}],
        [{"key": "allow_ai", "value": 3}],
        [{"key": "guest_max_days", "value": True}],
        [{"key": "allow_ai", "value": True}, {"key": "allow_ai", "value": False}],
    ):
        refused_item = await _sync(client, (guild_id, 4, {**restricted, "rules": bad}))
        assert refused_item.json()["results"][0]["error"] == "BILLING_INVALID_PAYLOAD"


async def test_a_rule_the_deployment_offers_nothing_to_meet_refuses_the_item(
    client: AsyncClient, session: AsyncSession
):
    guild = await create_guild(session)
    await rules.put(session, "login_methods", frozenset({LoginMethod.password}))
    await session.commit()
    factor = [{"key": "require_second_factor", "value": True}]
    response = await _sync(client, (guild.id, 1, _fields(rules=factor)))
    assert response.json()["results"][0]["error"] == "BILLING_RULE_NOT_OFFERED"


async def test_the_pushed_ceiling_is_the_one_uploads_are_held_to(
    client: AsyncClient, session: AsyncSession
):
    guild = await create_guild(session)
    guild_id = guild.id
    uploader = await create_user(session, email="ceiling@example.com")
    await route_session_to_guild(session, guild_id)
    await create_upload(session, guild, uploader, size_bytes=900)

    # Cleared: no ceiling to hit.
    await _sync(client, (guild_id, 1, _fields(max_storage_bytes=None)))
    await route_session_to_guild(session, guild_id)
    await enforce_storage_quota(session, guild_id=guild_id, incoming_bytes=200)

    await _sync(client, (guild_id, 2, _fields(max_storage_bytes=1000)))
    await route_session_to_guild(session, guild_id)
    with pytest.raises(StorageQuotaExceededError):
        await enforce_storage_quota(session, guild_id=guild_id, incoming_bytes=200)


async def test_a_suspended_community_stays_suspended(
    client: AsyncClient, session: AsyncSession
):
    """A status write never lifts the operator's time out; the caps still
    land, and the status is recorded for when the suspension lifts."""
    guild = await create_guild(session)
    guild.status = CommunityStatus.suspended.value
    session.add(guild)
    await session.commit()
    guild_id = guild.id

    response = await _sync(
        client, (guild_id, 1, _fields(status="on_hold", max_storage_bytes=2048))
    )
    assert response.status_code == 200, response.text
    administration = await _administration(session, guild_id)
    assert administration.billing_status == "on_hold"
    assert (await community_plan(session, guild_id))["max_storage_bytes"] == 2048
    read = await billing_boundary.post(
        client,
        "communities/read",
        {"community_refs": [await billing_guild_ref(guild_id)]},
    )
    assert read.json()["communities"][0]["status"] == "suspended"


async def _hold_notices(session: AsyncSession, user_id: int) -> int:
    from app.models.platform.notification import Notification, NotificationType

    session.expire_all()
    await drain_notices()
    rows = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == NotificationType.community_on_hold,
        )
    )
    return len(rows.all())


async def test_a_hold_tells_the_seat_once(client: AsyncClient, session: AsyncSession):
    guild = await create_guild(session)
    seat = await create_user(session)
    admin = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    guild_id, seat_id, admin_id = guild.id, seat.id, admin.id

    first = await _sync(client, (guild_id, 1, _fields(status="on_hold")))
    assert first.status_code == 200, first.text
    assert await _hold_notices(session, seat_id) == 1
    assert await _hold_notices(session, admin_id) == 0

    await _sync(client, (guild_id, 2, _fields(status="on_hold", max_users=60)))
    assert await _hold_notices(session, seat_id) == 1


# --- communities/read ----------------------------------------------------------


async def test_billing_reads_what_a_community_holds(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    guild = await create_guild(session, name="Acme")
    member = await create_user(session)
    await create_guild_membership(session, user=member, guild=guild)
    await create_guest(session, guild=guild)
    await route_session_to_guild(session, guild.id)
    await create_upload(session, guild, member, size_bytes=1234)
    guild_id = guild.id
    ref = await billing_guild_ref(guild_id)
    await _sync(client, (guild_id, 7, _fields()))
    await plugin_entitlements.store_statement(
        guild_id, LISTING, statement="x.y.z", version=3, values={"active": True}
    )

    response = await billing_boundary.post(
        client, "communities/read", {"community_refs": [ref, "gbil_nobody", ref]}
    )

    assert response.status_code == 200, response.text
    (read,) = response.json()["communities"]
    assert read == {
        "community_ref": ref,
        "status": "active",
        "usage_bytes": 1234,
        "members": read["members"],
        "guests": 1,
        "name": "Acme",
        "version": 7,
        "statements": {LISTING: 3},
    }
    assert read["members"] >= 1
