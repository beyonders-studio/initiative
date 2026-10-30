"""Tests for the platform settings endpoints.

The page is several surfaces behind one router: the SMTP test-email path
(a failed delivery answers with a machine-readable code and
keeps the mail host in the server log), the OIDC claim-mapping editor, the
operator's Guilds tab (caps, lifecycle status, sign-in entitlements, the
billing handoff), object storage, the community directory and how long a
session lasts. One table at the end states the tier every route answers to.
"""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.testing import community_plan
from app.core.intake import IntakeStream
from app.core.messages import GuildMessages
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, CommunityRole, CommunityStatus
from app.models.platform.access_grant import AccessLevel
from app.models.platform.user import UserRole
from app.models.tenant.intake import IntakeBinding
from app.services import email as email_service
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    guild_administration,
    drain_notices,
)
from sqlmodel import select
from app.db.request_context import SystemGuild, Unattributed

GUILDS = "/api/v1/settings/communities"


@pytest.fixture
async def owner(acting_user):
    """An account holding ``config.manage`` — the deployment's own settings."""
    return await acting_user("owner")


@pytest.fixture
async def operator(acting_user):
    """An account holding ``communities.manage`` and not ``config.manage`` — the
    Guilds tab is theirs, the configuration pages are not."""
    return await acting_user("operator")


async def test_a_failed_test_email_answers_with_a_code_and_logs_its_type(
    client: AsyncClient,
    owner,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The caller gets the generic machine-readable code and nothing about the
    mail host; the server log names the failure by its type."""
    sensitive = "SMTPConnectError to smtp.internal.example.com:587 (535 auth failed)"

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError(sensitive)

    monkeypatch.setattr(email_service, "send_test_email", _boom)

    with caplog.at_level(
        logging.WARNING, logger="app.api.v1.platform_endpoints.settings"
    ):
        resp = await client.post(
            "/api/v1/settings/email/test",
            json={"recipient": "dest@example.com"},
            headers=owner.headers,
        )

    assert resp.status_code == 502
    assert resp.json()["detail"] == "SETTINGS_EMAIL_SEND_FAILED"
    assert sensitive not in resp.text
    assert "smtp.internal.example.com" not in resp.text
    assert "Test email delivery failed (RuntimeError)" in caplog.text
    assert sensitive not in caplog.text


# --- The Guilds tab: the operator's dials -----------------------------------
#
# The caps, the lifecycle status and the entitlements are one PATCH with
# omit-to-skip semantics, so they are one table: what a dial is set to, what it
# reads when nobody has touched it, and a value the schema refuses.

_GUILD_DIALS = [
    pytest.param("max_storage_bytes", 5_000_000, None, -1, id="storage-cap"),
    pytest.param("max_users", 25, None, 0, id="user-cap"),
    # 0 is a setting here: the community takes no new guests.
    pytest.param("max_guests", 0, None, -1, id="guest-cap"),
    pytest.param(
        "status",
        CommunityStatus.suspended.value,
        CommunityStatus.active.value,
        "nope",
        id="lifecycle-status",
    ),
]


@pytest.mark.parametrize("dial,value,untouched,_refused", _GUILD_DIALS)
async def test_the_guilds_tab_lists_every_guild_with_its_dials(
    client: AsyncClient,
    session: AsyncSession,
    operator,
    dial,
    value,
    untouched,
    _refused,
) -> None:
    """The tab lists every guild — not just the reader's own — with its member
    count and each dial. An unset cap reads null, a guild nobody has moved
    reads active with no transition stamped, and a guild with no membership
    rows reports 0 members. Read here by an operator (``communities.manage``), which
    is the tier the tab is for."""
    theirs = await create_guild(session, name="Dialled Guild", **{dial: value})
    await create_guild_membership(
        session, user=operator.user, guild=theirs, role=CommunityRole.admin
    )
    untouched_guild = await create_guild(session, name="Untouched Guild")

    resp = await client.get(GUILDS, headers=operator.headers)
    assert resp.status_code == 200
    rows = {row["name"]: row for row in resp.json()["items"]}

    assert rows["Dialled Guild"]["id"] == theirs.id
    assert rows["Dialled Guild"][dial] == value
    assert rows["Dialled Guild"]["member_count"] == 1
    assert rows["Untouched Guild"]["id"] == untouched_guild.id
    assert rows["Untouched Guild"][dial] == untouched
    assert rows["Untouched Guild"]["member_count"] == 0
    assert rows["Untouched Guild"]["status_changed_at"] is None


@pytest.mark.parametrize("dial,value,untouched,_refused", _GUILD_DIALS)
async def test_an_operator_sets_each_dial_and_puts_it_back(
    client: AsyncClient,
    session: AsyncSession,
    operator,
    dial,
    value,
    untouched,
    _refused,
) -> None:
    """A cap goes on and back to unlimited (null); a suspended guild is
    reactivated."""
    guild = await create_guild(session)

    set_it = await client.patch(
        f"{GUILDS}/{guild.id}", json={dial: value}, headers=operator.headers
    )
    assert set_it.status_code == 200, set_it.text
    assert set_it.json()[dial] == value

    back = await client.patch(
        f"{GUILDS}/{guild.id}", json={dial: untouched}, headers=operator.headers
    )
    assert back.status_code == 200, back.text
    assert back.json()[dial] == untouched


@pytest.mark.parametrize("dial,value,_untouched,_refused", _GUILD_DIALS)
async def test_each_dial_moves_on_its_own(
    client: AsyncClient,
    session: AsyncSession,
    operator,
    dial,
    value,
    _untouched,
    _refused,
) -> None:
    """Omit-to-skip: a PATCH carrying one dial leaves the others exactly as
    they were (the endpoint keys off ``model_fields_set``)."""
    before = {
        "max_storage_bytes": 2048,
        "max_users": 5,
        "max_guests": 2,
        "status": CommunityStatus.read_only.value,
    }
    guild = await create_guild(session, **before)

    resp = await client.patch(
        f"{GUILDS}/{guild.id}", json={dial: value}, headers=operator.headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()[dial] == value
    for other, unchanged in before.items():
        if other != dial:
            assert resp.json()[other] == unchanged, other


@pytest.mark.parametrize("dial,_value,_untouched,refused", _GUILD_DIALS)
async def test_a_dial_refuses_a_value_outside_its_range(
    client: AsyncClient,
    session: AsyncSession,
    operator,
    dial,
    _value,
    _untouched,
    refused,
) -> None:
    """Negative bytes, a guild with no seats at all (``ge=1`` — a guild always
    has at least its creator), and a status that is not one of the three are
    all refused by validation."""
    guild = await create_guild(session)

    resp = await client.patch(
        f"{GUILDS}/{guild.id}", json={dial: refused}, headers=operator.headers
    )

    assert resp.status_code == 422


async def test_a_real_status_transition_is_stamped(
    client: AsyncClient, session: AsyncSession, operator
) -> None:
    """Moving a guild's status records when it moved, for the tab to show."""
    guild = await create_guild(session)

    resp = await client.patch(
        f"{GUILDS}/{guild.id}",
        json={"status": CommunityStatus.suspended.value},
        headers=operator.headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == CommunityStatus.suspended.value
    assert resp.json()["status_changed_at"] is not None


async def test_a_hold_tells_the_seat(
    client: AsyncClient, session: AsyncSession, operator
) -> None:
    """A transition into on_hold tells the community's seat holder, once.
    (Where billing manages plans, it reads every transition from its change
    log: ``billing_changes_test``.)"""
    from app.models.platform.guild import CommunityRole
    from app.models.platform.notification import Notification, NotificationType
    from app.testing import create_guild_membership, create_user

    guild = await create_guild(session)
    seat = await create_user(session)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    guild_id, guild_name, seat_id = guild.id, guild.name, seat.id

    for status in (CommunityStatus.suspended, CommunityStatus.on_hold):
        resp = await client.patch(
            f"{GUILDS}/{guild_id}",
            json={"status": status.value},
            headers=operator.headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == status.value

    session.expire_all()
    await drain_notices()
    notices = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == seat_id,
                Notification.type == NotificationType.community_on_hold,
            )
        )
    ).all()
    assert len(notices) == 1
    assert notices[0].data["community"] == guild_name


async def test_operator_grants_and_withdraws_guild_auth_options(
    client: AsyncClient, session: AsyncSession, operator
) -> None:
    """An operator grants a guild's sign-in options from the Guilds tab, one at
    a time or together, and withdraws them; the set round-trips through list +
    patch. A sent list replaces the set outright."""
    guild = await create_guild(session, auth_options=[])

    listed = await client.get(GUILDS, headers=operator.headers)
    assert listed.status_code == 200
    assert {r["name"]: r for r in listed.json()["items"]}[guild.name][
        "auth_options"
    ] == []

    # One switch without the other: neither needs the other to count.
    for sent in (["providers"], ["providers", "restrictions"], []):
        resp = await client.patch(
            f"{GUILDS}/{guild.id}",
            json={"auth_options": sent},
            headers=operator.headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["auth_options"] == sent


async def test_guild_auth_options_null_is_noop(
    client: AsyncClient, session: AsyncSession, operator
) -> None:
    """An explicit JSON null for auth_options is meaningless for an entitlement
    and must not silently withdraw one — Pydantic keeps the null in
    model_fields_set, so a naive provided-flag would coerce it to empty. A
    sibling field in the same PATCH still applies, proving the null is a no-op,
    not a poisoned request."""
    guild = await create_guild(session, auth_options=["providers", "restrictions"])

    resp = await client.patch(
        f"{GUILDS}/{guild.id}",
        json={"auth_options": None, "max_users": 5},
        headers=operator.headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["auth_options"] == ["providers", "restrictions"]
    assert resp.json()["max_users"] == 5


async def test_guild_auth_options_are_operator_only(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A guild's own admin cannot grant itself an option through the
    guild-facing PATCH — they are operator fields (like caps and status). The
    guild-admin endpoint simply doesn't accept them, leaving the set empty."""
    guild = await create_guild(session, auth_options=[])
    a = await acting_user(guild_role=CommunityRole.admin, guild=guild)
    guild_id = guild.id

    resp = await client.patch(
        f"/api/v1/communities/{guild_id}",
        json={"auth_options": ["providers"]},
        headers=a.headers,
    )

    # The guild-admin schema ignores unknown fields; the set stays empty.
    assert resp.status_code == 200, resp.text
    session.expire_all()
    guild = await session.get(Guild, guild_id)
    plan = await community_plan(session, guild.id)
    assert not (plan["community_sign_in"] or plan["security_standards"])


async def test_lowering_the_cap_below_the_headcount_keeps_the_members(
    client: AsyncClient, session: AsyncSession, operator
) -> None:
    """A cap under the current headcount is accepted and removes nobody. What
    it governs from then on is the next join, which is
    ``services/platform/guilds_test.py::test_ensure_membership_enforces_max_users``.
    """
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=operator.user, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(session, guild=guild)

    resp = await client.patch(
        f"{GUILDS}/{guild.id}", json={"max_users": 1}, headers=operator.headers
    )

    assert resp.status_code == 200
    assert resp.json()["max_users"] == 1
    assert resp.json()["member_count"] == 2


async def test_raising_cap_reopens_joins(
    client: AsyncClient, session: AsyncSession, acting_user, operator
) -> None:
    """A full guild blocks joins; raising the cap lets the same invite through."""
    from app.services.platform import guilds as guild_service

    guild = await create_guild(session, max_users=1)
    invitee = await acting_user()
    # Minted while the seat is still free, redeemed after it is taken —
    # minting itself is capacity-gated, so the order here is the scenario.
    invite, invite_code = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by=operator.user.id, max_uses=5
    )
    await guild_service.ensure_membership(
        session, guild_id=guild.id, user_id=operator.user.id, role=CommunityRole.admin
    )
    await session.commit()

    # Full (1/1) — the invite is refused, and it is NOT consumed (the cap check
    # runs before the invite's use count is incremented).
    blocked = await client.post(
        "/api/v1/communities/invite/accept",
        headers=invitee.headers,
        json={"code": invite_code},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "COMMUNITY_USER_LIMIT_REACHED"

    patched = await client.patch(
        f"{GUILDS}/{guild.id}", json={"max_users": 5}, headers=operator.headers
    )
    assert patched.status_code == 200

    accepted = await client.post(
        "/api/v1/communities/invite/accept",
        headers=invitee.headers,
        json={"code": invite_code},
    )
    assert accepted.status_code == 200
    # The cap itself is an admin-only field, and the invitee joins as a plain
    # member, so their own payload withholds it (``_serialize_guild``). What
    # proves the raise landed is the join that was refused a moment ago.
    assert accepted.json()["max_users"] is None
    assert accepted.json()["member_count"] == 2

    # And it reads back as 5 for somebody entitled to see it.
    listed = await client.get(GUILDS, headers=operator.headers)
    assert listed.status_code == 200
    assert {row["id"]: row for row in listed.json()["items"]}[guild.id][
        "max_users"
    ] == 5


async def test_the_guilds_tab_is_paged_and_searched(
    client: AsyncClient, session: AsyncSession, operator
) -> None:
    alpha = await create_guild(session, name="Alpha Lodge")
    await create_guild(session, name="Beta Lodge")
    await create_guild(session, name="Gamma Hall")

    resp = await client.get(
        GUILDS,
        params={"search": "lodge", "page_size": 1},
        headers=operator.headers,
    )

    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page["total_count"] == 2
    assert page["has_next"] is True
    assert [row["id"] for row in page["items"]] == [alpha.id]


async def test_guild_list_exposes_tier_name(
    client: AsyncClient, session: AsyncSession, operator
) -> None:
    """The Guilds tab reads the plan label verbatim off the administration row."""
    guild = await create_guild(session)
    await guild_administration(session, guild, tier_name="Bespoke Plan")

    resp = await client.get(GUILDS, headers=operator.headers)

    assert resp.status_code == 200
    row = next(g for g in resp.json()["items"] if g["id"] == guild.id)
    assert row["tier_name"] == "Bespoke Plan"


# --- Object storage (platform settings → Storage tab) ----------------------


@pytest.fixture
def reset_storage_cache():
    """Keep the process-wide storage-config snapshot from leaking across tests:
    a test that saves an ``s3`` backend would otherwise route a later upload
    test's writes at a non-existent bucket."""
    from app.services import storage_config

    storage_config.reset_for_tests()
    yield
    storage_config.reset_for_tests()


_S3_PAYLOAD = {
    "backend": "s3",
    "s3_bucket": "my-bucket",
    "s3_region": "eu-west-1",
    "s3_endpoint_url": "https://s3.example.com",
    "s3_access_key_id": "GKEXAMPLE",
    "s3_secret_access_key": "super-secret-value",
    "s3_use_path_style": True,
    "s3_local_fallback": True,
}


async def test_storage_settings_round_trip_never_returns_secret(
    client: AsyncClient,
    session: AsyncSession,
    owner,
    reset_storage_cache: None,
) -> None:
    """PUT saves S3 config; GET reflects it but never echoes the secret (only a
    ``has_secret_access_key`` flag). The secret is persisted encrypted."""
    put = await client.put(
        "/api/v1/settings/storage", json=_S3_PAYLOAD, headers=owner.headers
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["backend"] == "s3"
    assert body["s3_bucket"] == "my-bucket"
    assert body["s3_region"] == "eu-west-1"
    assert body["s3_use_path_style"] is True
    assert body["s3_local_fallback"] is True
    assert body["has_secret_access_key"] is True
    # The plaintext secret must never appear in any response.
    assert "super-secret-value" not in put.text
    assert "s3_secret_access_key" not in body

    get = await client.get("/api/v1/settings/storage", headers=owner.headers)
    assert get.status_code == 200
    assert get.json()["s3_bucket"] == "my-bucket"
    assert get.json()["has_secret_access_key"] is True
    assert "super-secret-value" not in get.text

    # Stored encrypted on the credentials row, and decrypts back to the original.
    from app.core.encryption import SALT_S3_SECRET_KEY, decrypt_field
    from app.services.platform.app_settings import get_app_setting_secrets

    row = await get_app_setting_secrets(session)
    assert row.s3_secret_access_key_encrypted
    assert row.s3_secret_access_key_encrypted != "super-secret-value"
    assert (
        decrypt_field(row.s3_secret_access_key_encrypted, SALT_S3_SECRET_KEY)
        == "super-secret-value"
    )


async def test_email_password_is_stored_apart_and_reported_as_set(
    client: AsyncClient,
    session: AsyncSession,
    owner,
) -> None:
    """The SMTP password is written to ``app_setting_secrets`` and reported only
    as ``has_password``; a save that omits it keeps it, and an empty one clears
    it."""
    from app.core.encryption import SALT_SMTP_PASSWORD, decrypt_field
    from app.services.platform.app_settings import get_app_setting_secrets

    email = {
        "host": "smtp.example.com",
        "port": 587,
        "secure": False,
        "reject_unauthorized": True,
        "username": "mailer",
        "from_address": "noreply@example.com",
    }
    put = await client.put(
        "/api/v1/settings/email",
        json={**email, "password": "smtp-pa55word"},
        headers=owner.headers,
    )
    assert put.status_code == 200, put.text
    assert put.json()["has_password"] is True
    assert "smtp-pa55word" not in put.text

    row = await get_app_setting_secrets(session)
    assert row.smtp_password_encrypted
    assert (
        decrypt_field(row.smtp_password_encrypted, SALT_SMTP_PASSWORD)
        == "smtp-pa55word"
    )

    kept = await client.put(
        "/api/v1/settings/email",
        json={**email, "host": "mail.example.com"},
        headers=owner.headers,
    )
    assert kept.status_code == 200, kept.text
    assert kept.json()["host"] == "mail.example.com"
    assert kept.json()["has_password"] is True

    get = await client.get("/api/v1/settings/email", headers=owner.headers)
    assert get.status_code == 200
    assert get.json()["has_password"] is True

    cleared = await client.put(
        "/api/v1/settings/email",
        json={**email, "password": ""},
        headers=owner.headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["has_password"] is False


async def test_storage_update_keeps_secret_when_omitted(
    client: AsyncClient,
    session: AsyncSession,
    owner,
    reset_storage_cache: None,
) -> None:
    """Re-saving without ``s3_secret_access_key`` keeps the stored key (the SMTP
    password pattern), so an owner can tweak the bucket without re-typing it."""
    assert (
        await client.put(
            "/api/v1/settings/storage", json=_S3_PAYLOAD, headers=owner.headers
        )
    ).status_code == 200

    no_secret = {k: v for k, v in _S3_PAYLOAD.items() if k != "s3_secret_access_key"}
    no_secret["s3_bucket"] = "renamed-bucket"
    resp = await client.put(
        "/api/v1/settings/storage", json=no_secret, headers=owner.headers
    )
    assert resp.status_code == 200
    assert resp.json()["s3_bucket"] == "renamed-bucket"
    assert resp.json()["has_secret_access_key"] is True

    from app.core.encryption import SALT_S3_SECRET_KEY, decrypt_field
    from app.services.platform.app_settings import get_app_setting_secrets

    row = await get_app_setting_secrets(session)
    assert row.s3_secret_access_key_encrypted
    assert (
        decrypt_field(row.s3_secret_access_key_encrypted, SALT_S3_SECRET_KEY)
        == "super-secret-value"
    )


async def test_storage_clearing_a_field_does_not_revert_to_env(
    client: AsyncClient,
    owner,
    monkeypatch: pytest.MonkeyPatch,
    reset_storage_cache: None,
) -> None:
    """An owner clearing an S3 field must stay cleared even when the matching
    ``S3_*`` env var is still set — the DB is authoritative once saved (env only
    seeds the first-run/migrated row, never re-seeds on read)."""
    from app.core.config import settings as app_config

    monkeypatch.setattr(app_config, "S3_BUCKET", "env-bucket", raising=False)

    assert (
        await client.put(
            "/api/v1/settings/storage", json=_S3_PAYLOAD, headers=owner.headers
        )
    ).status_code == 200

    cleared = {**_S3_PAYLOAD, "s3_bucket": None}
    resp = await client.put(
        "/api/v1/settings/storage", json=cleared, headers=owner.headers
    )
    assert resp.status_code == 200
    assert resp.json()["s3_bucket"] is None  # NOT re-seeded to "env-bucket"

    get = await client.get("/api/v1/settings/storage", headers=owner.headers)
    assert get.json()["s3_bucket"] is None


async def test_storage_update_refreshes_process_config(
    client: AsyncClient, owner, reset_storage_cache: None
) -> None:
    """Saving updates the live process snapshot so the request path uses the new
    backend without a restart."""
    resp = await client.put(
        "/api/v1/settings/storage", json=_S3_PAYLOAD, headers=owner.headers
    )
    assert resp.status_code == 200

    from app.services import storage_config

    cfg = storage_config.current_storage_config()
    assert cfg.backend == "s3"
    assert cfg.bucket == "my-bucket"
    assert cfg.secret_access_key == "super-secret-value"
    assert cfg.use_path_style is True


async def test_storage_backfill_requires_bucket(
    client: AsyncClient, owner, reset_storage_cache: None
) -> None:
    """The backfill writes to S3, so it needs a bucket configured first."""
    resp = await client.post("/api/v1/settings/storage/backfill", headers=owner.headers)

    assert resp.status_code == 400
    assert resp.json()["detail"] == "SETTINGS_STORAGE_BACKFILL_NOT_CONFIGURED"


async def test_storage_backfill_status_reads_shared_row(
    client: AsyncClient, session: AsyncSession, owner
) -> None:
    """GET status returns the shared UNLOGGED-table row (idle by default), so
    every worker reports the same thing rather than its own in-memory guess."""
    from app.services import storage_backfill

    # The UNLOGGED status row persists across tests within a worker; clear it so a
    # prior test's terminal status doesn't bleed into this fresh-state assertion.
    await storage_backfill._ensure_table()
    await session.exec(text("DELETE FROM storage_backfill_state"))
    await session.commit()

    resp = await client.get("/api/v1/settings/storage/backfill", headers=owner.headers)

    assert resp.status_code == 200
    assert resp.json()["status"] == "idle"
    assert resp.json()["copied"] == 0


# --- Guilds tab: billing portal operator handoff ---


def _configure_billing(monkeypatch) -> str:
    """A billing portal, and the handoff key; returns the key's public PEM."""
    from app.core.config import settings as app_settings
    from app.testing.billing_boundary import use_handoff_key

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")
    return use_handoff_key(monkeypatch)


def _handoff(guild_id: int) -> str:
    return f"{GUILDS}/{guild_id}/billing/service-handoff"


@pytest.mark.parametrize(
    "unset,expected,detail",
    [
        pytest.param(
            ["BILLING_URL"], 404, "BILLING_PORTAL_NOT_CONFIGURED", id="no-portal"
        ),
        pytest.param(
            ["HANDOFF_SIGNING_PRIVATE_KEY_PEM"],
            503,
            "BILLING_PORTAL_SIGNING_NOT_CONFIGURED",
            id="no-signing-material",
        ),
    ],
)
async def test_the_billing_button_says_what_the_deployment_is_missing(
    client: AsyncClient,
    session: AsyncSession,
    owner,
    monkeypatch,
    unset,
    expected,
    detail,
) -> None:
    """A deployment with no portal has nowhere to hand off to; one with a portal
    and no signing material cannot say who is arriving."""
    from app.core.config import settings as app_settings

    _configure_billing(monkeypatch)
    for name in unset:
        monkeypatch.setattr(app_settings, name, None)
    guild = await create_guild(session)

    resp = await client.post(_handoff(guild.id), headers=owner.headers)

    assert resp.status_code == expected
    assert resp.json()["detail"] == detail


@pytest.mark.parametrize(
    "method,path",
    [
        pytest.param("patch", f"{GUILDS}/999999", id="setting-a-dial"),
        pytest.param("post", _handoff(999999), id="handing-off-to-billing"),
    ],
)
async def test_a_guild_that_is_not_there_is_a_404(
    client: AsyncClient, owner, monkeypatch, method, path
) -> None:
    _configure_billing(monkeypatch)

    resp = await getattr(client, method)(
        path, json={"max_storage_bytes": 1024}, headers=owner.headers
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "COMMUNITY_NOT_FOUND"


async def test_billing_handoff_self_issues_a_grant_and_names_it(
    client: AsyncClient, session: AsyncSession, owner, monkeypatch
):
    """The token verifies against the handoff key's public half (Ed25519, as
    every handoff into billing) and carries the claim set the receiver
    requires, naming the grant it just self-issued."""
    import jwt
    from sqlmodel import select as sm_select

    from app.core.security import (
        BILLING_SUPPORT_HANDOFF_AUDIENCE,
        TOKEN_ISSUER,
    )
    from app.models.platform.access_grant import AccessGrant

    public_pem = _configure_billing(monkeypatch)
    guild = await create_guild(session)  # the owner is deliberately not a member

    resp = await client.post(_handoff(guild.id), headers=owner.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert 0 < body["expires_in_seconds"] <= 300

    header = jwt.get_unverified_header(body["handoff_token"])
    assert (header["alg"], header["kid"]) == ("EdDSA", "test-handoff-key")
    payload = jwt.decode(
        body["handoff_token"],
        public_pem,
        algorithms=["EdDSA"],
        audience=BILLING_SUPPORT_HANDOFF_AUDIENCE,
        issuer=TOKEN_ISSUER,
    )
    # Everyone on the token is named by reference, `sub` included; no row id
    # of ours is in the claims at all.
    assert payload["sub"] == payload["user_ref"]
    assert payload["user_ref"].startswith("ubil_")
    assert payload["community_ref"].startswith("gbil_")
    assert "guild_id" not in payload
    assert "guild_name" not in payload
    assert payload["jti"]
    # Lifetime stays inside the receiver's ceiling.
    assert payload["exp"] - payload["iat"] <= 300

    grant = (
        await session.exec(
            sm_select(AccessGrant).where(
                AccessGrant.user_id == owner.user.id,
                AccessGrant.guild_id == guild.id,
            )
        )
    ).one()
    assert payload["grant_id"] == str(grant.id)
    # The approver too — it names a person, so it is a reference like the rest.
    assert payload["approver"] == payload["user_ref"]
    assert grant.access_level == "read"
    assert grant.status == "approved"


async def test_billing_handoff_records_the_grant_it_issues(
    client: AsyncClient, session: AsyncSession, owner, monkeypatch, capfd
):
    """A billing grant is self-issued like breaking glass, so it is recorded
    the same way — once, when it is issued, and not again when it is reused."""
    from app.core.audit_events import AuditEventType
    from app.testing.audit import emitted

    _configure_billing(monkeypatch)
    guild = await create_guild(session)
    capfd.readouterr()

    first = await client.post(_handoff(guild.id), headers=owner.headers)
    second = await client.post(_handoff(guild.id), headers=owner.headers)
    assert first.status_code == second.status_code == 200

    issued = emitted(capfd, AuditEventType.ACCESS_GRANT_SELF_ISSUED)
    assert len(issued) == 1
    assert issued[0]["actor_user_id"] == owner.user.id
    assert issued[0]["guild_id"] == guild.id
    assert issued[0]["detail"] == {
        "purpose": "billing",
        "level": "read",
        "self_approved": True,
    }


async def test_billing_handoff_reuses_a_live_grant(
    client: AsyncClient, session: AsyncSession, owner, monkeypatch
):
    """A second click inside the window names the same grant, not a new one."""
    import jwt
    from sqlmodel import select as sm_select

    from app.models.platform.access_grant import AccessGrant

    _configure_billing(monkeypatch)
    guild = await create_guild(session)

    first = await client.post(_handoff(guild.id), headers=owner.headers)
    second = await client.post(_handoff(guild.id), headers=owner.headers)
    assert first.status_code == second.status_code == 200

    def grant_of(resp):
        return jwt.decode(
            resp.json()["handoff_token"], options={"verify_signature": False}
        )["grant_id"]

    assert grant_of(first) == grant_of(second)
    # ...and each click is a distinct one-shot token.
    assert first.json()["handoff_token"] != second.json()["handoff_token"]

    grants = (
        await session.exec(
            sm_select(AccessGrant).where(
                AccessGrant.user_id == owner.user.id,
                AccessGrant.guild_id == guild.id,
            )
        )
    ).all()
    assert len(grants) == 1


async def test_billing_handoff_breaks_glass_even_for_a_member(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """Belonging to the guild is content access, not billing authority, so the
    grant is still issued and named."""
    import jwt
    from sqlmodel import select as sm_select

    from app.models.platform.access_grant import AccessGrant

    _configure_billing(monkeypatch)
    a = await acting_user("owner", guild_role=CommunityRole.admin)

    resp = await client.post(_handoff(a.guild.id), headers=a.headers)
    assert resp.status_code == 200

    grant = (
        await session.exec(
            sm_select(AccessGrant).where(
                AccessGrant.user_id == a.user.id, AccessGrant.guild_id == a.guild.id
            )
        )
    ).one()
    payload = jwt.decode(
        resp.json()["handoff_token"], options={"verify_signature": False}
    )
    assert payload["grant_id"] == str(grant.id)
    assert grant.access_level == "read"


async def test_billing_grant_confers_no_access_to_the_guild(
    client: AsyncClient, session: AsyncSession, owner, monkeypatch
):
    """The grant the billing button issues authorises billing and nothing else:
    a non-member holding one still reads the guild as a stranger."""
    _configure_billing(monkeypatch)
    guild = await create_guild(session)  # the owner is not a member

    before = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/", headers=owner.headers
    )
    assert before.status_code == 403

    minted = await client.post(_handoff(guild.id), headers=owner.headers)
    assert minted.status_code == 200

    # Still refused: the live grant is a billing one, so the guild resolver
    # does not accept it.
    after = await client.get(
        f"/api/v1/c/{guild.id}/initiatives/", headers=owner.headers
    )
    assert after.status_code == 403


async def test_billing_grant_does_not_block_a_content_break_glass(
    session: AsyncSession, owner
):
    """The two purposes stack independently — holding a billing grant must not
    make the ordinary break-glass path report an overlap."""
    from app.models.platform.access_grant import AccessGrantPurpose
    from app.schemas.platform.access_grant import BreakGlassCreate
    from app.services.platform import access_grants as service

    guild = await create_guild(session)

    billing = await service.break_glass(
        session,
        actor=owner.user,
        payload=BreakGlassCreate(community_id=guild.id, reason="billing portal"),
        purpose=AccessGrantPurpose.billing,
        level=AccessLevel.read.value,
    )
    content = await service.break_glass(
        session,
        actor=owner.user,
        payload=BreakGlassCreate(community_id=guild.id, reason="incident"),
        level=AccessLevel.read_write.value,
    )
    assert billing.purpose == "billing"
    assert content.purpose == "content"

    # Each purpose resolves only its own row.
    assert (
        await service.get_live_grant(session, user_id=owner.user.id, guild_id=guild.id)
    ).id == content.id
    assert (
        await service.get_live_grant(
            session,
            user_id=owner.user.id,
            guild_id=guild.id,
            purpose=AccessGrantPurpose.billing,
        )
    ).id == billing.id


async def test_billing_grant_does_not_block_a_content_request(
    session: AsyncSession, acting_user
):
    """A live billing grant must not make the request->approve flow report an
    overlap: the two authorities are independent."""
    from app.models.platform.access_grant import AccessGrantPurpose
    from app.schemas.platform.access_grant import AccessGrantCreate, BreakGlassCreate
    from app.services.platform import access_grants as service

    support = await acting_user("support")
    guild = await create_guild(session)

    await service.break_glass(
        session,
        actor=support.user,
        payload=BreakGlassCreate(community_id=guild.id, reason="billing portal"),
        purpose=AccessGrantPurpose.billing,
        level=AccessLevel.read.value,
    )

    requested = (
        await service.request_grants(
            session,
            asks=[("content", AccessLevel.read.value)],
            requester=support.user,
            payload=AccessGrantCreate(
                community_id=guild.id,
                reason="investigating a ticket",
                access_level=AccessLevel.read,
            ),
        )
    )[0]
    assert requested.purpose == "content"


# ---------------------------------------------------------------------------
# The community-directory switch
# ---------------------------------------------------------------------------


async def test_owner_switches_the_community_directory_on_and_off(
    client: AsyncClient, owner
) -> None:
    """The value the write sets is read back from /config, which is where the
    SPA learns whether to offer the directory at all."""
    assert (await client.get("/api/v1/config")).json()[
        "community_directory_enabled"
    ] is False

    for wanted in (True, False):
        resp = await client.put(
            "/api/v1/settings/community",
            json={"community_directory_enabled": wanted},
            headers=owner.headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["community_directory_enabled"] is wanted
        assert (await client.get("/api/v1/config")).json()[
            "community_directory_enabled"
        ] is wanted


# ---------------------------------------------------------------------------
# Ranking by engagement
# ---------------------------------------------------------------------------


async def test_the_deployment_and_a_community_each_turn_engagement_ranking_off(
    client: AsyncClient, session: AsyncSession, owner, acting_user
) -> None:
    """The owner answers for the deployment and the seat for its community,
    and the community's page is told the deployment's answer beside its own."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    await guild_administration(session, seat.guild, auth_options=["restrictions"])
    community = f"/api/v1/communities/{seat.guild.id}/auth-settings"

    written = await client.patch(
        community, json={"allow_engagement_ranking": False}, headers=seat.headers
    )
    assert written.status_code == 200, written.text
    assert written.json()["allow_engagement_ranking"] is False
    assert written.json()["engagement_ranking_allowed_by_platform"] is True

    resp = await client.put(
        "/api/v1/settings/community",
        json={
            "community_directory_enabled": False,
            "engagement_ranking_enabled": False,
        },
        headers=owner.headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["engagement_ranking_enabled"] is False

    body = (await client.get(community, headers=seat.headers)).json()
    assert body["engagement_ranking_allowed_by_platform"] is False
    assert body["allow_engagement_ranking"] is False


# ---------------------------------------------------------------------------
# How long somebody stays signed in
# ---------------------------------------------------------------------------


async def test_the_session_limit_starts_unset(client: AsyncClient, owner):
    """A self-hosted deployment is not answering to anybody, so it asks for no
    limit until somebody sets one."""
    response = await client.get("/api/v1/settings/auth/platform", headers=owner.headers)

    assert response.status_code == 200, response.text
    assert response.json()["session_max_hours"] is None


async def test_an_owner_sets_and_clears_the_session_limit(client: AsyncClient, owner):
    set_it = await client.patch(
        "/api/v1/settings/auth/platform",
        json={"session_max_hours": 12},
        headers=owner.headers,
    )
    assert set_it.status_code == 200, set_it.text
    assert set_it.json()["session_max_hours"] == 12

    cleared = await client.patch(
        "/api/v1/settings/auth/platform",
        json={"session_max_hours": None},
        headers=owner.headers,
    )
    assert cleared.json()["session_max_hours"] is None


async def test_a_zero_hour_limit_is_refused(client: AsyncClient, owner):
    response = await client.patch(
        "/api/v1/settings/auth/platform",
        json={"session_max_hours": 0},
        headers=owner.headers,
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Which tier each route answers to
#
# These handlers read and write through the system engine, so the
# capability gate is what each one is scoped by. Every route is listed here
# per-endpoint, stated rather than derived from ``capabilities.py``, so that a
# change to the ladder has to be made here too.
# ---------------------------------------------------------------------------

_CONFIG_MANAGE = "config.manage"  # owner only
_GUILDS_MANAGE = "communities.manage"  # operator and owner
_GUILDS_READ = "communities.read"  # support and above
_BILLING_INSIGHTS = "billing.insights"  # operator and owner
_BILLING_CONTRACTS = "billing.contracts"  # operator and owner
_BILLING_DIRECTORY = "billing.directory"  # owner only
_BILLING_CONTROL = "billing.control"  # owner only

#: (capability, method, path — ``{community_id}`` is filled in, json body or None)
_ROUTES: list[tuple[str, str, str, dict | None]] = [
    (_CONFIG_MANAGE, "get", "/api/v1/settings/storage", None),
    (_CONFIG_MANAGE, "put", "/api/v1/settings/storage", {"backend": "local"}),
    (_CONFIG_MANAGE, "post", "/api/v1/settings/storage/test", {"backend": "local"}),
    (_CONFIG_MANAGE, "post", "/api/v1/settings/storage/backfill", None),
    (_CONFIG_MANAGE, "get", "/api/v1/settings/storage/backfill", None),
    (
        _CONFIG_MANAGE,
        "put",
        "/api/v1/settings/community",
        {"community_directory_enabled": True},
    ),
    (
        _CONFIG_MANAGE,
        "patch",
        "/api/v1/settings/auth/platform",
        {"session_max_hours": 12},
    ),
    (_GUILDS_READ, "get", GUILDS, None),
    (_GUILDS_MANAGE, "patch", GUILDS + "/{community_id}", {"max_storage_bytes": 1024}),
    (_GUILDS_MANAGE, "patch", GUILDS + "/{community_id}", {"status": "suspended"}),
    (
        _GUILDS_MANAGE,
        "post",
        GUILDS + "/{community_id}/billing/service-handoff?console=operator",
        None,
    ),
    (_BILLING_INSIGHTS, "post", "/api/v1/settings/billing/insights-handoff", None),
    (_BILLING_CONTRACTS, "post", "/api/v1/settings/billing/contracts-handoff", None),
    (_BILLING_DIRECTORY, "post", "/api/v1/settings/billing/directory-handoff", None),
    (_BILLING_CONTROL, "post", "/api/v1/settings/billing/control-handoff", None),
]

#: The tiers each capability sits above.
_BELOW_THE_BAR: dict[str, list[UserRole]] = {
    _CONFIG_MANAGE: [
        UserRole.member,
        UserRole.support,
        UserRole.moderator,
        UserRole.operator,
    ],
    _GUILDS_MANAGE: [UserRole.member, UserRole.support, UserRole.moderator],
    _GUILDS_READ: [UserRole.member],
    _BILLING_INSIGHTS: [UserRole.member, UserRole.support, UserRole.moderator],
    _BILLING_CONTRACTS: [UserRole.member, UserRole.support, UserRole.moderator],
    _BILLING_DIRECTORY: [
        UserRole.member,
        UserRole.support,
        UserRole.moderator,
        UserRole.operator,
    ],
    _BILLING_CONTROL: [
        UserRole.member,
        UserRole.support,
        UserRole.moderator,
        UserRole.operator,
    ],
}


@pytest.mark.parametrize(
    "capability,tier",
    [
        pytest.param(capability, tier, id=f"{capability}-as-{tier.value}")
        for capability, tiers in _BELOW_THE_BAR.items()
        for tier in tiers
    ],
)
async def test_a_tier_below_the_bar_reaches_none_of_its_routes(
    client: AsyncClient, acting_user, monkeypatch, capability, tier
) -> None:
    """Each route answers 403 to every tier under its capability, before any
    handler logic runs — never a 200/201/204, and never the 400/404 that would
    say the request reached the handler. The caller is the target guild's own
    admin, which is a guild role and so changes nothing here."""
    _configure_billing(monkeypatch)
    a = await acting_user(tier, guild_role=CommunityRole.admin)

    for gate, method, path, body in _ROUTES:
        if gate != capability:
            continue
        resp = await getattr(client, method)(
            path.format(community_id=a.guild.id),
            headers=a.headers,
            **({"json": body} if body is not None else {}),
        )
        assert resp.status_code == 403, (
            f"{method.upper()} {path} as {tier.value}: {resp.status_code}"
        )
        assert resp.json()["detail"] == "INSUFFICIENT_PRIVILEGES"


@pytest.mark.parametrize(
    "method,path,body",
    [
        pytest.param(method, path, body, id=f"{method}-{path}")
        for method, path, body in {
            (method, path): (method, path, body)
            for _gate, method, path, body in _ROUTES
        }.values()
    ],
)
async def test_every_route_needs_an_account(
    client: AsyncClient, method, path, body
) -> None:
    """Unauthenticated callers are rejected outright (401), never reaching the
    system-engine handlers."""
    resp = await getattr(client, method)(
        path.format(community_id=1), **({"json": body} if body is not None else {})
    )

    assert resp.status_code == 401, f"{method.upper()} {path}: {resp.status_code}"


# --- help requests need somewhere to land -----------------------------------


async def _bind_support_stream(session: AsyncSession) -> None:
    """Give the deployment an operations guild with the support stream bound.

    The same two halves the operator's Intake page writes: the pointer on the
    settings singleton, and a binding inside the guild it names.
    """
    staff_user = await create_user(session)
    staff = await create_guild(session, creator=staff_user)
    initiative = await create_initiative(session, staff, staff_user)
    project = await create_project(session, initiative, staff_user)

    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = staff.id
    session.add(row)
    await session.commit()

    await set_rls_context(session, SystemGuild(staff.id))
    session.add(IntakeBinding(stream=IntakeStream.support, project_id=project.id))
    await session.commit()
    await set_rls_context(session, Unattributed())


async def test_help_requests_need_somewhere_to_go(client, session, owner):
    """Switching the entitlement on offers a form. Refused while the deployment
    has bound no support stream: the form would have nowhere to send what
    somebody writes in it."""
    guild = await create_guild(session)

    response = await client.patch(
        f"{GUILDS}/{guild.id}",
        json={"support_enabled": True},
        headers=owner.headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == GuildMessages.SUPPORT_INTAKE_NOT_CONFIGURED
    assert (await community_plan(session, guild.id))["help_requests"] is False


async def test_help_requests_switch_on_once_a_stream_is_bound(client, session, owner):
    """With somewhere to receive them, the same call goes through."""
    guild = await create_guild(session)
    await _bind_support_stream(session)

    response = await client.patch(
        f"{GUILDS}/{guild.id}",
        json={"support_enabled": True},
        headers=owner.headers,
    )

    assert response.status_code == 200, response.text
    assert (await community_plan(session, guild.id))["help_requests"] is True


async def test_the_community_list_says_whether_help_has_somewhere_to_go(
    client, session, acting_user
):
    """The switch is held until a support stream is bound, and the operator
    flipping it reads that from the list they flip it on — not from the intake
    settings, which are the owner's."""
    operator = await acting_user("operator")

    before = await client.get(GUILDS, headers=operator.headers)
    await _bind_support_stream(session)
    after = await client.get(GUILDS, headers=operator.headers)

    assert before.status_code == after.status_code == 200, before.text
    assert before.json()["support_bound"] is False
    assert after.json()["support_bound"] is True


async def test_help_requests_can_always_be_switched_off(client, session, owner):
    """A deployment that has stopped staffing help stops offering it, whatever
    became of the binding in the meantime."""
    guild = await create_guild(session)
    await guild_administration(session, guild, support_enabled=True)

    response = await client.patch(
        f"{GUILDS}/{guild.id}",
        json={"support_enabled": False},
        headers=owner.headers,
    )

    assert response.status_code == 200, response.text
    assert (await community_plan(session, guild.id))["help_requests"] is False


INTERFACE = "/api/v1/settings/interface"

_COLOURS = {"light_accent_color": "#123456", "dark_accent_color": "#abcdef"}


async def test_cookie_consent_starts_off(client, owner):
    """A deployment nobody arrives at uninvited is not asked to explain itself
    to arrivals. An owner running a public front door turns it on."""
    response = await client.get("/api/v1/config")

    assert response.status_code == 200, response.text
    assert response.json()["cookie_consent_enabled"] is False


async def test_an_owner_turns_cookie_consent_on_and_off(client, owner):
    on = await client.put(
        INTERFACE,
        json={**_COLOURS, "cookie_consent_enabled": True},
        headers=owner.headers,
    )
    assert on.status_code == 200, on.text
    assert on.json()["cookie_consent_enabled"] is True

    off = await client.put(
        INTERFACE,
        json={**_COLOURS, "cookie_consent_enabled": False},
        headers=owner.headers,
    )
    assert off.status_code == 200, off.text
    assert off.json()["cookie_consent_enabled"] is False


async def test_saving_a_colour_leaves_cookie_consent_alone(client, owner):
    """The two live on one page and one payload; they are still two decisions,
    so the colour form must not answer the other one by omission."""
    await client.put(
        INTERFACE,
        json={**_COLOURS, "cookie_consent_enabled": True},
        headers=owner.headers,
    )

    response = await client.put(INTERFACE, json=_COLOURS, headers=owner.headers)

    assert response.status_code == 200, response.text
    assert response.json()["cookie_consent_enabled"] is True


async def test_cookie_consent_is_owner_only(client, operator):
    response = await client.put(
        INTERFACE,
        json={**_COLOURS, "cookie_consent_enabled": True},
        headers=operator.headers,
    )

    assert response.status_code == 403


# --- Operator dashboard: the billing insights page ---

_INSIGHTS = "/api/v1/settings/billing/insights-handoff"
_CONTRACTS = "/api/v1/settings/billing/contracts-handoff"
_DIRECTORY = "/api/v1/settings/billing/directory-handoff"
_CONTROL = "/api/v1/settings/billing/control-handoff"


@pytest.mark.parametrize(
    "path,audience,who",
    [
        (_INSIGHTS, "initiative:billing-insights", "operator"),
        (_CONTRACTS, "initiative:billing-contracts", "operator"),
        (_DIRECTORY, "initiative:billing-directory", "owner"),
        (_CONTROL, "initiative:billing-control", "owner"),
    ],
)
async def test_the_insights_handoff_names_a_person_and_no_community(
    client: AsyncClient,
    operator,
    owner,
    monkeypatch,
    handoff_signing_key,
    path,
    audience,
    who,
) -> None:
    """EdDSA under the portal's key, each door its own audience, and nothing
    about any community or grant — none of these pages is about one."""
    import jwt

    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")
    acting = owner if who == "owner" else operator

    resp = await client.post(path, headers=acting.headers)

    assert resp.status_code == 200, resp.text
    token = resp.json()["handoff_token"]
    payload = jwt.decode(
        token,
        handoff_signing_key,
        algorithms=["EdDSA"],
        audience=audience,
        issuer="initiative",
    )
    assert payload["sub"].startswith("ubil_")
    for absent in ("guild_ref", "guild_id", "community_ref", "grant_id", "user_id"):
        assert absent not in payload


@pytest.mark.parametrize(
    "billing_url,signing,expected,detail",
    [
        pytest.param(None, True, 404, "BILLING_PORTAL_NOT_CONFIGURED", id="no-portal"),
        pytest.param(
            "https://billing.example.com",
            False,
            503,
            "BILLING_PORTAL_SIGNING_NOT_CONFIGURED",
            id="no-signing-key",
        ),
    ],
)
async def test_the_insights_button_says_what_the_deployment_is_missing(
    client: AsyncClient, operator, monkeypatch, billing_url, signing, expected, detail
) -> None:
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", billing_url)
    if not signing:
        monkeypatch.setattr(app_settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)

    resp = await client.post(_INSIGHTS, headers=operator.headers)

    assert resp.status_code == expected
    assert resp.json()["detail"] == detail


@pytest.mark.parametrize("signing", [True, False])
async def test_the_app_config_says_whether_insights_can_open(
    client: AsyncClient, monkeypatch, handoff_signing_key, signing
) -> None:
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "BILLING_URL", "https://billing.example.com")
    if not signing:
        monkeypatch.setattr(app_settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)

    resp = await client.get("/api/v1/config")

    assert resp.status_code == 200
    assert resp.json()["billing"]["insights"] is signing
    assert resp.json()["billing"]["contracts"] is signing
    assert resp.json()["billing"]["directory"] is signing
    assert resp.json()["billing"]["control"] is signing
