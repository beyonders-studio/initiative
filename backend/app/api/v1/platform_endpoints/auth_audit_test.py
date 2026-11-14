"""Authentication reaches the audit log.

The pipeline already existed — a versioned envelope, a tier, a shipper-ready
index — and carried five moderation events and nothing from auth. These pin the
sign-in family to it: what is recorded, what is deliberately not, and that the
detail says which way somebody got in.
"""

from __future__ import annotations

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.auth_test import (
    _enable_platform_oidc,
    _run_oidc_flow,
    _wire_fake_idp,
)
from app.core.audit_events import AuditCategory, AuditEventType
from app.models.platform.user import UserStatus
from app.testing import emitted
from app.testing.factories import create_user, get_auth_headers

PASSWORD = "testpassword123"


async def _sign_in(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


async def test_a_sign_in_is_recorded_with_its_method(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await create_user(session, email="signin-audit@example.com")
    user_id = user.id
    capfd.readouterr()
    assert (await _sign_in(client, "signin-audit@example.com")).status_code == 200

    rows = emitted(capfd, AuditEventType.AUTH_SIGNED_IN)
    assert [r["actor_user_id"] for r in rows] == [user_id]
    assert rows[0]["detail"] == {"method": "password"}
    assert rows[0]["tier"] == AuditEventType.AUTH_SIGNED_IN.tier


async def test_a_sign_in_that_never_opened_a_session_is_not_recorded(
    client: AsyncClient, session: AsyncSession, monkeypatch, capfd
):
    """The record is staged beside the session write, so a failure takes both.
    Nothing signed in, so there is nothing to write down."""
    await create_user(session, email="nostore-audit@example.com")

    async def _boom(*args, **kwargs):
        raise RuntimeError("session store down")

    monkeypatch.setattr("app.services.auth.sessions.create_session", _boom)
    capfd.readouterr()
    refused = await _sign_in(client, "nostore-audit@example.com")
    assert refused.status_code == 503

    assert emitted(capfd, AuditEventType.AUTH_SIGNED_IN) == []


async def test_a_refused_sign_in_is_recorded_with_its_reason(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await create_user(session, email="badpass-audit@example.com")
    user_id = user.id
    capfd.readouterr()
    response = await _sign_in(client, "badpass-audit@example.com", "not-the-password")
    assert response.status_code == 400

    rows = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    # The account is what the attempt was against, not who made it: the
    # request is unauthenticated, so there is no actor to name.
    assert [r["actor_user_id"] for r in rows] == [None]
    assert [r["target_user_id"] for r in rows] == [user_id]
    assert rows[0]["detail"]["reason"] == "bad_password"
    # A refusal changed nothing, so it is not a write.
    assert rows[0]["is_write"] is False


async def test_an_inactive_account_is_recorded_separately_from_a_wrong_password(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await create_user(
        session, email="inactive-audit@example.com", status=UserStatus.deactivated
    )
    user_id = user.id
    capfd.readouterr()
    assert (await _sign_in(client, "inactive-audit@example.com")).status_code == 400

    rows = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert [r["actor_user_id"] for r in rows] == [None]
    assert [r["target_user_id"] for r in rows] == [user_id]
    assert rows[0]["detail"]["reason"] == "inactive"


async def test_password_endpoints_finalize_unknown_account_refusals_without_identity(
    client: AsyncClient, capfd
):
    """Every refusal lands the same identity-free audit write and commit."""
    capfd.readouterr()
    login_response = await _sign_in(client, "nobody-at-all@example.com")
    device_response = await client.post(
        "/api/v1/auth/token",
        data={"username": "still-nobody@example.com", "password": PASSWORD},
        headers={"Origin": "https://studio.beyonders.initiative"},
    )
    assert login_response.status_code == device_response.status_code == 400

    new_rows = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert len(new_rows) == 2
    assert [row["actor_user_id"] for row in new_rows] == [None, None]
    assert [row["target_user_id"] for row in new_rows] == [None, None]
    assert [row["target"] for row in new_rows] == [None, None]
    assert [row["detail"] for row in new_rows] == [
        {"method": "password", "reason": "bad_password"},
        {"method": "password", "reason": "bad_password"},
    ]


async def test_signing_out_is_recorded(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await create_user(session, email="signout-audit@example.com")
    user_id = user.id
    capfd.readouterr()
    response = await client.post("/api/v1/auth/logout", headers=get_auth_headers(user))
    assert response.status_code == 204

    rows = emitted(capfd, AuditEventType.AUTH_SIGNED_OUT)
    assert [r["actor_user_id"] for r in rows] == [user_id]


async def test_changing_a_password_is_recorded_with_how(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await create_user(session, email="pwchange-audit@example.com")
    user_id = user.id
    capfd.readouterr()
    response = await client.patch(
        "/api/v1/me",
        headers=get_auth_headers(user),
        json={"current_password": PASSWORD, "password": "a-new-longer-secret-1"},
    )
    assert response.status_code == 200

    rows = emitted(capfd, AuditEventType.AUTH_PASSWORD_CHANGED)
    assert [r["actor_user_id"] for r in rows] == [user_id]
    assert rows[0]["detail"] == {"via": "self_service"}


async def test_a_reset_is_recorded_as_a_reset(
    client: AsyncClient, session: AsyncSession, capfd
):
    from app.models.platform.user_token import UserTokenPurpose
    from app.services.platform import user_tokens

    user = await create_user(session, email="pwreset-audit@example.com")
    token = await user_tokens.create_token(
        session, user_id=user.id, purpose=UserTokenPurpose.password_reset
    )
    capfd.readouterr()
    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "another-longer-secret-1"},
    )
    assert response.status_code == 200

    rows = emitted(capfd, AuditEventType.AUTH_PASSWORD_CHANGED)
    assert [r["detail"]["via"] for r in rows] == ["reset"]


async def test_every_auth_event_is_filed_under_authentication():
    """Downstream groups by category, so a new member filed under the wrong one
    disappears from the view it belongs to."""
    auth_events = [e for e in AuditEventType if e.value.startswith("auth.")]
    assert auth_events
    for event_type in auth_events:
        assert event_type.category is AuditCategory.AUTHENTICATION


async def test_a_replayed_refresh_token_is_recorded_against_its_owner(
    client: AsyncClient, session: AsyncSession, capfd
):
    """The rejection kills the whole chain, so the record has to be able to say
    whose chain it was — there is no issued session to read it from, which is
    why ``RotationResult`` carries the id."""
    from app.core.security import REFRESH_COOKIE_NAME

    user = await create_user(session, email="replay-audit@example.com")
    user_id = user.id
    signed_in = await _sign_in(client, "replay-audit@example.com")
    assert signed_in.status_code == 200
    spent = client.cookies.get(REFRESH_COOKIE_NAME)
    assert spent

    # Spend it once — which rotates the cookie — then put the spent one back.
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200
    capfd.readouterr()
    client.cookies.set(REFRESH_COOKIE_NAME, spent)
    replayed = await client.post("/api/v1/auth/refresh")
    assert replayed.status_code == 401

    rows = emitted(capfd, AuditEventType.AUTH_REFRESH_REUSE_DETECTED)
    # The endpoint is authorised by the cookie alone and has just rejected it,
    # so the owner of the chain is the target, not the one who presented it.
    assert [r["actor_user_id"] for r in rows] == [None]
    assert [r["target_user_id"] for r in rows] == [user_id]


async def test_an_oidc_sign_in_records_its_provider_and_whether_it_stepped_up(
    client: AsyncClient, session: AsyncSession, monkeypatch, capfd
):
    from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG
    from app.testing.oidc import FakeIdp

    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)
    capfd.readouterr()

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "oidc-audit@example.com",
            "username": "oidc-audit",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)

    rows = emitted(capfd, AuditEventType.AUTH_SIGNED_IN)
    assert [r["detail"] for r in rows] == [
        {"method": "oidc", "provider": PLATFORM_OIDC_SLUG, "step_up": False}
    ]
    assert rows[0]["actor_user_id"] is not None


async def test_an_oidc_sign_in_records_what_the_idp_asserted_about_it(
    client: AsyncClient, session: AsyncSession, monkeypatch, capfd
):
    """The methods and context class the provider named ride the record, so a
    reviewer reading the log can tell a second factor was used and when."""
    from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG
    from app.testing.oidc import FakeIdp

    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)
    capfd.readouterr()

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "oidc-amr@example.com",
            "username": "oidc-amr",
            "email_verified": True,
            "amr": ["pwd", "mfa"],
            "acr": "phr",
            "auth_time": 1757600000,
        },
    )
    assert response.status_code in (302, 307)

    rows = emitted(capfd, AuditEventType.AUTH_SIGNED_IN)
    assert [r["detail"] for r in rows] == [
        {
            "method": "oidc",
            "provider": PLATFORM_OIDC_SLUG,
            "step_up": False,
            "auth_time": 1757600000,
            "amr": ["pwd", "mfa"],
            "acr": "phr",
        }
    ]


@pytest.mark.parametrize("proved", [True, False], ids=["proved", "unproved"])
async def test_claiming_an_existing_account_by_verified_email_is_recorded(
    client: AsyncClient, session: AsyncSession, monkeypatch, capfd, proved
):
    """The link is what makes every later sign-in resolve by subject, so the
    moment an identity provider claims an existing account is worth a record.
    Where the account had not proved the address, the provider's word is its
    first proof, what the account held before it is retired, and the account's
    open connections are rechecked once that commits."""

    from sqlmodel import select

    from app.core.security import get_password_hash
    from app.db import post_commit
    from app.models.platform.mfa_recovery_code import MfaRecoveryCode
    from app.models.platform.user import User
    from app.models.platform.user_passkey import UserPasskey
    from app.services import content_sockets
    from app.services.auth import addresses
    from app.services.auth import totp as totp_service
    from app.testing.oidc import FakeIdp

    rechecked: list[int] = []

    async def _recheck(user_id: int) -> None:
        rechecked.append(user_id)

    monkeypatch.setattr(content_sockets.sockets, "revoke_user_everywhere", _recheck)
    await _enable_platform_oidc(session)
    existing = await create_user(
        session,
        email="claimed-audit@example.com",
        email_verified=proved,
        hashed_password=get_password_hash("set-before-proof"),
    )
    existing_id = existing.id
    session.add(
        UserPasskey(
            user_id=existing_id,
            credential_id=b"set-before-proof",
            public_key=b"key",
            rp_id="localhost",
            name="Laptop",
        )
    )
    await totp_service.issue_recovery_codes(session, user_id=existing_id)
    await session.commit()
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)
    from app.services.platform import email_outbox

    letters: list[str] = []

    async def _letter(user, pieces, **_) -> None:
        letters.append(pieces.subject)

    monkeypatch.setattr(email_outbox, "enqueue_account_letter", _letter)
    capfd.readouterr()

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "claimed-audit@example.com",
            "username": "claimed-audit",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)
    await post_commit.settle_all()

    events = emitted(capfd)
    rows = [r for r in events if r["event_type"] == "auth.identity_linked"]
    assert [r["actor_user_id"] for r in rows] == [existing_id]
    assert rows[0]["detail"]["matched_by"] == "verified_email"
    # Its holder is told of the new way in, with the way to say it wasn't them.
    from app.core.email_i18n import email_t

    assert email_t("identity.linked.subject", "en", escape=False) in letters
    retired = [r for r in events if r["event_type"] == "auth.credentials_retired"]
    assert len(retired) == (0 if proved else 1)
    assert (existing_id in rechecked) is not proved
    session.expire_all()
    row = await session.get(User, existing_id)
    assert row is not None
    assert (row.hashed_password is not None) is proved
    kept = (
        await session.exec(
            select(UserPasskey).where(UserPasskey.user_id == existing_id)
        )
    ).all()
    codes = (
        await session.exec(
            select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == existing_id)
        )
    ).all()
    assert (len(kept), bool(codes)) == ((1, True) if proved else (0, False))
    # Either way the account now holds the address as proved.
    assert await addresses.holds_address(
        session, user_id=existing_id, email="claimed-audit@example.com"
    )
