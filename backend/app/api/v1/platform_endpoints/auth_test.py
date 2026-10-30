"""
Integration tests for authentication endpoints.

Tests the auth API endpoints including:
- User registration
- Login/token generation
- Bootstrap status
- Email verification
- Password reset
"""

import secrets
import uuid
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.email_i18n import email_t
from app.core.encryption import (
    decrypt_token,
    hash_email,
)
from app.core.messages import OidcMessages
from app.core.security import (
    REFRESH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_upload_token,
    get_password_hash,
    verify_upload_token,
)
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.auth_session import AuthSession
from app.models.platform.federated_identity import FederatedIdentity
from app.models.platform.user_email import UserEmail
from app.services.auth import addresses
from app.services.platform import email_outbox
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.models.platform.federated_identity_secret import FederatedIdentitySecret
from app.models.platform.user import User, UserStatus
from app.services.auth.oidc.flow_state import s256
from app.services.auth.oidc.provider import OidcClientConfig, OidcProvider
from app.services.auth.platform_provider import PLATFORM_OIDC_SLUG
from app.testing.captcha import captcha_switched_on
from app.testing.factories import (
    create_auth_provider,
    create_federated_identity,
    create_user,
    get_auth_headers,
    get_auth_token,
)
from app.testing.oidc import (
    CLIENT_ID as OIDC_CLIENT_ID,
    ISSUER as OIDC_ISSUER,
    OTHER_KEY,
    FakeIdp,
    mint_id_token,
)

APP_ORIGIN = {"Origin": "https://studio.beyonders.initiative"}


async def test_bootstrap_status_no_users(client: AsyncClient):
    """Test bootstrap status when no users exist."""
    response = await client.get("/api/v1/auth/bootstrap")

    assert response.status_code == 200
    data = response.json()
    assert data["has_users"] is False
    assert "public_registration_enabled" in data


async def test_bootstrap_status_with_users(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Registration reads as open only where somebody may register without an
    invite, which turning community creation off closes too. The demo
    deployment says so."""
    await create_user(session)

    response = await client.get("/api/v1/auth/bootstrap")
    assert response.json() == {
        "has_users": True,
        "public_registration_enabled": True,
        "demo": False,
    }

    monkeypatch.setattr(settings, "DISABLE_GUILD_CREATION", True)
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    response = await client.get("/api/v1/auth/bootstrap")
    assert response.json()["public_registration_enabled"] is False
    assert response.json()["demo"] is True


async def test_register_first_user(client: AsyncClient, session: AsyncSession):
    """The first registered user becomes owner, and a registration that names
    no community creates none."""
    from app.models.platform.guild import GuildMembership

    user_data = {
        "email": "first@example.com",
        "username": "first",
        "password": "securepassword123",
    }

    response = await client.post("/api/v1/auth/register", json=user_data)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "first@example.com"
    assert data["status"] == "active"
    assert data["role"] == "owner"  # First user bootstraps as owner
    held = await session.exec(
        select(GuildMembership).where(GuildMembership.user_id == data["id"])
    )
    assert held.all() == []


async def test_register_with_a_community_makes_it(
    client: AsyncClient, session: AsyncSession
):
    """A registration that names a community makes it, with the new account as
    its superadmin; one that also carries an invite is refused."""
    from app.models.platform.guild import Guild, GuildMembership, CommunityRole

    await create_user(session)
    community = {"name": "Book Club", "description": "Monthly reads"}
    response = await client.post(
        "/api/v1/auth/register?invite_code=anything",
        json={
            "email": "both@example.com",
            "username": "both",
            "password": "securepassword123",
            "community": community,
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "REGISTRATION_INVITE_OR_COMMUNITY"

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "founder@example.com",
            "username": "founder",
            "password": "securepassword123",
            "community": community,
        },
    )
    assert response.status_code == 201
    held = (
        await session.exec(
            select(Guild, GuildMembership.role)
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .where(GuildMembership.user_id == response.json()["id"])
        )
    ).all()
    assert [(g.name, g.description, role) for g, role in held] == [
        ("Book Club", "Monthly reads", CommunityRole.superadmin)
    ]


def _register_born(client: AsyncClient, name: str, birthdate: date, country=None):
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": f"{name}@example.com",
            "username": name,
            "password": "securepassword123",
            "birthdate": birthdate.isoformat(),
        },
        headers={"CF-IPCountry": country} if country else {},
    )


async def test_register_answers_the_age_question(client: AsyncClient, monkeypatch):
    """A birthdate given at sign-up answers the directory's age question; under
    16 but old enough for an account where they are is recorded on the account
    rather than refusing it."""
    monkeypatch.setattr(settings, "CLIENT_COUNTRY_HEADER", "CF-IPCountry")
    today = date.today()

    def register(name: str, birthdate: date):
        return _register_born(client, name, birthdate, "US")

    adult = await register("adult", date(today.year - 30, 1, 1))
    assert adult.status_code == 201
    assert adult.json()["age_confirmed_at"] is not None
    # The date is kept beside the answer, and only said to be there.
    assert adult.json()["birthdate_on_file"] is True
    assert str(today.year - 30) not in adult.text

    minor = await register("minor", date(today.year - 14, 1, 1))
    assert minor.status_code == 201
    assert minor.json()["age_confirmed_at"] is None
    assert minor.json()["age_below_minimum_at"] is not None
    assert minor.json()["birthdate_on_file"] is True

    # Two days on, so no time zone the suite runs in reads it as today.
    unborn = await register("unborn", today + timedelta(days=2))
    assert unborn.status_code == 422
    assert unborn.json()["detail"] == "USER_AGE_INVALID_BIRTHDATE"


@pytest.mark.parametrize(
    ("years", "country"),
    [(12, "US"), (15, "DE"), (15, None), (15, "XX")],
    ids=["under the US minimum", "under the German minimum", "no header", "unknown"],
)
async def test_register_refuses_anyone_under_the_minimum_where_they_are(
    client: AsyncClient, session: AsyncSession, monkeypatch, years, country
):
    """No account is made; where the country is not known, the highest
    minimum applies."""
    monkeypatch.setattr(settings, "CLIENT_COUNTRY_HEADER", "CF-IPCountry")
    today = date.today()

    response = await _register_born(
        client, "young", date(today.year - years, 1, 1), country
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "USER_AGE_BELOW_ACCOUNT_MINIMUM"
    assert await addresses.account_holding(session, "young@example.com") is None


async def test_register_asks_no_age_where_the_deployment_does_not_check(
    client: AsyncClient, session: AsyncSession
):
    await rules.put(session, "community_directory_enabled", False)
    await rules.put(session, "community_age_gate_enabled", False)
    await session.commit()
    today = date.today()

    response = await _register_born(client, "young", date(today.year - 10, 1, 1))

    assert response.status_code == 201
    # Nothing is owed, so no birthdate screen stands in front of the app.
    no_date = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "nodate@example.com",
            "username": "nodate",
            "password": "securepassword123",
        },
    )
    assert no_date.json()["birthdate_on_file"] is False
    assert no_date.json()["birthdate_required"] is False


async def test_register_with_invite_blocked_when_guild_full(
    client: AsyncClient, session: AsyncSession
):
    """Signing up via an invite into a guild at its user cap is refused (403).

    End-to-end: a brand-new account is created and then its invite redemption
    trips the cap, so the whole registration is rejected."""
    from app.services.platform import guilds as guild_service
    from app.testing.factories import create_guild

    guild = await create_guild(session, name="Full Guild", max_users=1)
    seat = await create_user(session, email="reg-seat@example.com")
    # Minted while the seat is still free, redeemed after it is taken —
    # minting itself is capacity-gated, so the order here is the scenario.
    invite, invite_code = await guild_service.create_guild_invite(
        session, guild_id=guild.id, created_by=seat.id, max_uses=5
    )
    await guild_service.ensure_membership(session, guild_id=guild.id, user_id=seat.id)
    await session.commit()

    response = await client.post(
        f"/api/v1/auth/register?invite_code={invite_code}",
        json={
            "email": "reg-newuser@example.com",
            "username": "reg-newuser",
            "password": "password1234",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_USER_LIMIT_REACHED"


async def test_register_with_a_bound_invite_joins_on_confirming(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """With mail on, the address is not proved at sign-up, so an invite bound
    to it waits: confirming the address joins the guild. The binding is still
    checked when the account is made. A letter an operator sends again
    replaces the first once it is delivered, and still carries the invite."""
    from app.models.platform.guild import GuildMembership
    from app.models.platform.user import UserRole
    from app.models.platform.user_token import UserTokenPurpose
    from app.services.platform import user_tokens
    from app.services import email as email_service
    from app.services.platform import guilds as guild_service
    from app.testing.factories import create_guild

    settings_row = await app_settings_service.get_app_settings(session)
    settings_row.smtp_host = "smtp.example.com"
    settings_row.smtp_from_address = "noreply@example.com"
    session.add(settings_row)
    letters: list[str] = []

    async def _capture(session_, user, token):
        letters.append(token)

    monkeypatch.setattr(email_service, "send_verification_email", _capture)
    admin = await create_user(session, email="bound-admin@example.com")
    guild = await create_guild(session, creator=admin)
    invite, invite_code = await guild_service.create_guild_invite(
        session,
        guild_id=guild.id,
        created_by=admin.id,
        invitee_email="bound-invitee@example.com",
    )
    await session.commit()
    guild_id, code = guild.id, invite_code

    def _register(email: str, username: str):
        return client.post(
            f"/api/v1/auth/register?invite_code={code}",
            json={"email": email, "username": username, "password": "password1234"},
        )

    elsewhere = await _register("someone-else@example.com", "elsewhere")
    assert elsewhere.status_code == 400
    assert elsewhere.json()["detail"] == "INVITE_EMAIL_MISMATCH"

    made = await _register("bound-invitee@example.com", "boundinvitee")
    assert made.status_code == 201, made.text
    user_id = made.json()["id"]

    async def _memberships() -> list[int]:
        session.expire_all()
        return list(
            (
                await session.exec(
                    select(GuildMembership.guild_id).where(
                        GuildMembership.user_id == user_id
                    )
                )
            ).all()
        )

    # Neither the invited guild nor one of its own until the address is proved.
    assert await _memberships() == []

    operator_headers = get_auth_headers(
        await create_user(session, role=UserRole.operator)
    )
    resend_path = f"/api/v1/operator/users/{user_id}/verification-email"

    async def _undelivered(session_, user, token):
        raise RuntimeError("Failed to send email")

    monkeypatch.setattr(email_service, "send_verification_email", _undelivered)
    failed = await client.post(resend_path, headers=operator_headers)
    assert failed.status_code == 502
    assert failed.json()["detail"] == "SETTINGS_EMAIL_SEND_FAILED"
    assert await user_tokens.get_valid_token(
        session, token=letters[0], purpose=UserTokenPurpose.email_verification
    )

    monkeypatch.setattr(email_service, "send_verification_email", _capture)
    resent = await client.post(resend_path, headers=operator_headers)
    assert resent.status_code == 200, resent.text
    first, second = letters
    replaced = await client.post(
        "/api/v1/auth/verification/confirm", json={"token": first}
    )
    assert replaced.json()["detail"] == "INVALID_OR_EXPIRED_TOKEN"

    confirmed = await client.post(
        "/api/v1/auth/verification/confirm", json={"token": second}
    )
    assert confirmed.status_code == 200, confirmed.text
    assert await _memberships() == [guild_id]
    assert await addresses.holds_address(
        session, user_id=user_id, email="bound-invitee@example.com"
    )
    again = await client.post(resend_path, headers=operator_headers)
    assert again.status_code == 409
    assert again.json()["detail"] == "OPERATOR_NOTHING_TO_VERIFY"


async def test_register_duplicate_email(client: AsyncClient, session: AsyncSession):
    """Test that registration fails for duplicate email."""
    await create_user(session, email="existing@example.com")

    user_data = {
        "email": "existing@example.com",
        "username": "existing",
        "password": "password1234",
    }

    response = await client.post("/api/v1/auth/register", json=user_data)

    assert response.status_code == 400
    assert response.json()["detail"] == "EMAIL_ALREADY_REGISTERED"


async def test_closed_registration_says_nothing_about_the_address(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Where registration needs an invite, a held address and a free one are
    refused the same way: whether one is held is only told to somebody the
    deployment would register."""
    from app.core import config as cfg

    monkeypatch.setattr(cfg.settings, "ENABLE_PUBLIC_REGISTRATION", False)
    await create_user(session, email="held-closed@example.com")

    answers = []
    for email in ("held-closed@example.com", "free-closed@example.com"):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "username": "closed",
                "password": "password1234",
            },
        )
        answers.append((response.status_code, response.json()["detail"]))

    assert answers == [(403, "REGISTRATION_REQUIRES_INVITE")] * 2


async def test_register_normalizes_email(client: AsyncClient):
    """Test that email is normalized during registration."""
    user_data = {
        "email": "  TEST@EXAMPLE.COM  ",
        "username": "test",
        "password": "password1234",
    }

    response = await client.post("/api/v1/auth/register", json=user_data)

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "test@example.com"


async def test_register_persists_browser_timezone(
    client: AsyncClient, session: AsyncSession
):
    """The SPA forwards ``Intl.DateTimeFormat().resolvedOptions().timeZone``
    on registration so the new account's wall clock matches the user's
    actual zone instead of the model default ``"UTC"``."""
    from sqlmodel import select

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "tz-user@example.com",
            "username": "tz-user",
            "password": "password1234",
            "timezone": "America/Los_Angeles",
        },
    )
    assert response.status_code == 201
    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("tz-user@example.com"))
        )
    ).one()
    assert user.timezone == "America/Los_Angeles"


async def test_register_rejects_invalid_timezone(client: AsyncClient):
    """Bogus IANA names from a hand-crafted request are rejected with the
    same error code the self-update path uses, so the SPA's existing
    ``getErrorMessage`` mapping picks it up."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "bad-tz@example.com",
            "username": "bad-tz",
            "password": "password1234",
            "timezone": "Mars/Olympus_Mons",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "UNKNOWN_TIMEZONE"


async def test_register_without_timezone_keeps_utc_default(
    client: AsyncClient, session: AsyncSession
):
    """Non-SPA callers (curl, integration scripts) that omit the field
    still hit the model default — keeps the change non-breaking."""
    from sqlmodel import select

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "no-tz@example.com",
            "username": "no-tz",
            "password": "password1234",
        },
    )
    assert response.status_code == 201
    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("no-tz@example.com"))
        )
    ).one()
    assert user.timezone == "UTC"


# --- Captcha gate ----------------------------------------------------


async def test_register_requires_captcha_token_when_configured(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """When the deployment has CAPTCHA_PROVIDER set, the second-and-later
    user must include a token — bot signups can't slip through by just
    omitting the field. The bootstrap user already exists in this test
    so the first-user skip doesn't apply."""
    await create_user(session)  # exhaust the bootstrap-first-user skip

    with captcha_switched_on():
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "needs-captcha@example.com",
                "username": "needs-captcha",
                "password": "password1234",
            },
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "CAPTCHA_REQUIRED"


async def test_register_skips_captcha_for_bootstrap_first_user(
    client: AsyncClient, monkeypatch
):
    """Fresh deployments shouldn't be locked out by a captcha config
    the operator may not have wired up yet — the first user always
    bypasses the check."""
    with captcha_switched_on():
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "bootstrap@example.com",
                "username": "bootstrap",
                "password": "password1234",
            },
        )
    assert response.status_code == 201


async def test_register_no_captcha_required_when_provider_unset(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """OSS deployments leave the captcha vars unset — registration must
    work as before, with no field required."""
    from app.core.config import settings as app_settings

    await create_user(session)  # second-user path
    monkeypatch.setattr(app_settings, "CAPTCHA_PROVIDER", None)
    monkeypatch.setattr(app_settings, "CAPTCHA_SITE_KEY", None)
    monkeypatch.setattr(app_settings, "CAPTCHA_SECRET_KEY", None)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "no-captcha@example.com",
            "username": "no-captcha",
            "password": "password1234",
        },
    )
    assert response.status_code == 201


async def test_register_with_valid_captcha_token_succeeds(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Happy path: valid token from the provider → registration completes.
    The provider call is stubbed at the verifier-service layer so this
    test doesn't need network access."""
    from app.services import captcha as captcha_service

    await create_user(session)  # second-user path

    async def _ok(*_args, **_kwargs):
        return None

    monkeypatch.setattr(captcha_service, "verify_or_raise", _ok)

    with captcha_switched_on():
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "good-token@example.com",
                "username": "good-token",
                "password": "password1234",
                "captcha_token": "stub-valid-token",
            },
        )
    assert response.status_code == 201


async def test_login_success(client: AsyncClient, session: AsyncSession):
    """Test successful login returns access token."""
    # Create user with known password
    password = "testpassword123"
    await create_user(
        session,
        email="login@example.com",
        hashed_password=get_password_hash(password),
        status=UserStatus.active,
        email_verified=True,
    )

    # Attempt login
    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "login@example.com",
            "password": password,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


async def test_login_wrong_password(client: AsyncClient, session: AsyncSession):
    """Test that login fails with wrong password."""
    password = "correct_password"
    await create_user(
        session,
        email="test@example.com",
        hashed_password=get_password_hash(password),
        status=UserStatus.active,
        email_verified=True,
    )

    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "test@example.com",
            "password": "wrong_password",
        },
    )

    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()


@pytest.mark.parametrize("origin", [None, APP_ORIGIN])
async def test_password_token_refusal_does_not_reveal_account_resolution(
    client: AsyncClient, session: AsyncSession, origin: dict[str, str] | None
) -> None:
    """Known, unknown, and non-password accounts have one public refusal shape,
    from a browser and from the app alike."""
    endpoint = "app" if origin else "browser"
    await create_user(session, email=f"known-{endpoint}@example.com")
    # Built through the factory rather than by hand: an account is more than
    # its row now that addresses are resolved separately, and a test that
    # assembles one itself asserts against a shape it invented.
    await create_user(
        session,
        email=f"sso-{endpoint}@example.com",
        hashed_password=None,
    )

    async def refuse(email: str):
        return await client.post(
            "/api/v1/auth/token",
            data={"username": email, "password": "wrong-password"},
            headers=origin,
        )

    responses = [
        await refuse(f"known-{endpoint}@example.com"),
        await refuse(f"missing-{endpoint}@example.com"),
        await refuse(f"sso-{endpoint}@example.com"),
    ]
    fingerprints = [
        (response.status_code, response.json(), response.headers.get("set-cookie"))
        for response in responses
    ]
    assert fingerprints == [
        (400, {"detail": "INCORRECT_CREDENTIALS"}, None),
        (400, {"detail": "INCORRECT_CREDENTIALS"}, None),
        (400, {"detail": "INCORRECT_CREDENTIALS"}, None),
    ]


@pytest.fixture
def two_per_address(client, monkeypatch):
    """The limiter on, with each address allowed two refusals and two letters.

    Narrow enough that each test stays inside the per-client route limits, so
    what it meets is the address allowance alone. Takes ``client`` for the
    reason ``rate_limit_of_one_per_minute`` does.
    """
    from limits import parse

    from app.core import rate_limit

    monkeypatch.setattr(rate_limit.limiter, "enabled", True)
    monkeypatch.setattr(rate_limit.SIGN_IN_FAILURES, "limit", parse("2/hour"))
    monkeypatch.setattr(rate_limit.MAIL_SENDS, "limit", parse("2/hour"))
    rate_limit.limiter.reset()
    yield
    rate_limit.limiter.reset()


async def _sign_in(client: AsyncClient, email: str, password: str) -> httpx.Response:
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


async def test_address_out_of_refusals_refuses_the_right_password(
    client: AsyncClient, session: AsyncSession, two_per_address
) -> None:
    for email in ("held@example.com", "other@example.com"):
        await create_user(
            session,
            email=email,
            hashed_password=get_password_hash("right-password"),
            status=UserStatus.active,
            email_verified=True,
        )

    assert (await _sign_in(client, "held@example.com", "wrong")).status_code == 400
    assert (await _sign_in(client, "held@example.com", "wrong")).status_code == 400
    refused = await _sign_in(client, "held@example.com", "right-password")
    assert refused.status_code == 429
    assert refused.json() == {"detail": "SIGN_IN_LOCKED"}

    # Another address from the same client has its own allowance.
    other = await _sign_in(client, "other@example.com", "right-password")
    assert other.status_code == 200


async def test_address_allowance_is_shared_and_ignores_whether_anyone_holds_it(
    client: AsyncClient, two_per_address
) -> None:
    """The browser and the app draw on one allowance, and an address nobody
    holds runs out the same way as one somebody does."""
    await _sign_in(client, "Nobody@Example.com ", "wrong")
    await _sign_in(client, "nobody@example.com", "wrong")

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "nobody@example.com", "password": "wrong"},
        headers=APP_ORIGIN,
    )
    assert response.status_code == 429
    assert response.json() == {"detail": "SIGN_IN_LOCKED"}


async def test_one_network_address_is_not_one_allowance(
    client: AsyncClient, two_per_address
) -> None:
    """Everybody in an office signs in from one network address, so wrong
    passwords are counted by account and by address typed in, never by the
    network they came from."""
    for n in range(6):
        response = await _sign_in(client, f"person{n}@example.com", "wrong")
        assert response.status_code == 400, response.text
        app_response = await client.post(
            "/api/v1/auth/token",
            data={"username": f"phone{n}@example.com", "password": "wrong"},
            headers=APP_ORIGIN,
        )
        assert app_response.status_code == 400, app_response.text


async def test_signing_in_starts_the_address_count_over(
    client: AsyncClient, session: AsyncSession, two_per_address
) -> None:
    await create_user(
        session,
        email="typo@example.com",
        hashed_password=get_password_hash("right-password"),
        status=UserStatus.active,
        email_verified=True,
    )

    assert (await _sign_in(client, "typo@example.com", "wrong")).status_code == 400
    assert (
        await _sign_in(client, "typo@example.com", "right-password")
    ).status_code == 200
    assert (await _sign_in(client, "typo@example.com", "wrong")).status_code == 400
    assert (
        await _sign_in(client, "typo@example.com", "right-password")
    ).status_code == 200


@pytest.mark.parametrize("recovery", ["reset", "support"])
async def test_lifting_a_lock_starts_the_address_count_over(
    client: AsyncClient,
    session: AsyncSession,
    two_per_address,
    recovery: str,
) -> None:
    """The refusal tells them to reset their password, and support's unlock
    says the account is open again, so either has to let them in, whichever of
    the two counts was refusing them."""
    from app.models.platform.user import UserRole
    from app.models.platform.user_token import UserTokenPurpose
    from app.services.auth import sign_in_locks
    from app.services.platform import user_tokens

    user = await create_user(
        session,
        email="Reset@Example.com",
        hashed_password=get_password_hash("right-password"),
        status=UserStatus.active,
        email_verified=True,
    )
    user_id = user.id
    for _ in range(2):
        await _sign_in(client, "reset@example.com", "wrong")
    for _ in range(sign_in_locks.LOCK_AFTER_FAILURES):
        await sign_in_locks.record_failure(session, user_id)
    await session.commit()
    assert (
        await _sign_in(client, "reset@example.com", "right-password")
    ).status_code == 429

    if recovery == "reset":
        password = "brand-new-secret-123"
        reset_token = await user_tokens.create_token(
            session, user_id=user_id, purpose=UserTokenPurpose.password_reset
        )
        lifted = await client.post(
            "/api/v1/auth/password/reset",
            json={"token": reset_token, "password": password},
        )
    else:
        password = "right-password"
        support = await create_user(session, role=UserRole.support)
        lifted = await client.delete(
            f"/api/v1/operator/users/{user_id}/sign-in-lock",
            headers=get_auth_headers(support),
        )
    assert lifted.status_code == 200, lifted.text
    signed_in = await _sign_in(client, "reset@example.com", password)
    assert signed_in.status_code == 200, signed_in.text


async def test_an_address_is_sent_no_more_letters_than_its_allowance(
    client: AsyncClient, session: AsyncSession, two_per_address
) -> None:
    """Counted by the address typed in, held or not, and not by the client:
    the same client can still ask for a letter to another address."""
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    row.smtp_host = "smtp.example.com"
    row.smtp_from_address = "noreply@example.com"
    session.add(row)
    await session.commit()

    async def _forgot(email: str) -> httpx.Response:
        return await client.post("/api/v1/auth/password/forgot", json={"email": email})

    for _ in range(2):
        assert (await _forgot("Nobody@Example.com")).status_code == 200
    refused = await _forgot("nobody@example.com")
    assert refused.status_code == 429
    assert refused.json()["detail"] == "RATE_LIMITED"
    assert (await _forgot("somebody-else@example.com")).status_code == 200


async def test_five_wrong_passwords_lock_the_account(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Counted by account whatever the client, so with the per-client limits
    off (as the suite runs) the account lock is what refuses. A reset from the
    emailed link ends the lock at once."""
    from app.models.platform.user_token import UserTokenPurpose
    from app.services.platform import user_tokens

    user = await create_user(
        session,
        email="five@example.com",
        hashed_password=get_password_hash("right-password"),
        status=UserStatus.active,
        email_verified=True,
    )
    user_id = user.id
    for _ in range(5):
        assert (await _sign_in(client, "five@example.com", "wrong")).status_code == 400

    refused = await _sign_in(client, "five@example.com", "right-password")
    assert refused.status_code == 429
    assert refused.json() == {"detail": "SIGN_IN_LOCKED"}

    app_refused = await client.post(
        "/api/v1/auth/token",
        data={"username": "five@example.com", "password": "right-password"},
        headers=APP_ORIGIN,
    )
    assert app_refused.status_code == 429

    reset_token = await user_tokens.create_token(
        session, user_id=user_id, purpose=UserTokenPurpose.password_reset
    )
    reset = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": reset_token, "password": "brand-new-secret-123"},
    )
    assert reset.status_code == 200, reset.text
    signed_in = await _sign_in(client, "five@example.com", "brand-new-secret-123")
    assert signed_in.status_code == 200, signed_in.text


async def test_login_refused_for_account_without_password(
    client: AsyncClient, session: AsyncSession
):
    """An SSO-only account (NULL hashed_password) can never password-login —
    any password yields the same incorrect-credentials refusal, with no 500
    from verifying against a missing hash."""
    await create_user(
        session,
        email="sso-only@example.com",
        hashed_password=None,
        status=UserStatus.active,
        email_verified=True,
    )

    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "sso-only@example.com",
            "password": "anything-at-all",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "INCORRECT_CREDENTIALS"


async def test_login_inactive_user(client: AsyncClient, session: AsyncSession):
    """Test that inactive users cannot login."""
    password = "testpassword"
    await create_user(
        session,
        email="inactive@example.com",
        hashed_password=get_password_hash(password),
        status=UserStatus.deactivated,  # Deactivated user
        email_verified=True,
    )

    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "inactive@example.com",
            "password": password,
        },
    )

    assert response.status_code == 400
    assert "inactive" in response.json()["detail"].lower()


async def test_login_unverified_email(client: AsyncClient, session: AsyncSession):
    """Test that users with unverified emails cannot login."""
    password = "testpassword"
    await create_user(
        session,
        email="unverified@example.com",
        hashed_password=get_password_hash(password),
        status=UserStatus.active,
        email_verified=False,  # Email not verified
    )

    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "unverified@example.com",
            "password": password,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "EMAIL_NOT_VERIFIED"


async def test_login_nonexistent_user(client: AsyncClient):
    """Test that login fails for nonexistent user."""
    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "nonexistent@example.com",
            "password": "anypassword",
        },
    )

    assert response.status_code == 400
    assert "incorrect" in response.json()["detail"].lower()


async def test_login_email_case_insensitive(client: AsyncClient, session: AsyncSession):
    """Test that login email is case-insensitive."""
    password = "testpassword"
    await create_user(
        session,
        email="test@example.com",
        hashed_password=get_password_hash(password),
        status=UserStatus.active,
        email_verified=True,
    )

    # Login with uppercase email
    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "TEST@EXAMPLE.COM",  # uppercase
            "password": password,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


async def test_login_rehashes_legacy_bcrypt_password(
    client: AsyncClient, session: AsyncSession
):
    """A user whose stored hash predates the argon2 migration should still
    log in successfully, and the hash should be rewritten as argon2id on
    the way out so the bcrypt verify path eventually disappears for active
    users.
    """
    import bcrypt as _bcrypt

    password = "legacy-bcrypt-password"
    legacy_hash = _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode(
        "utf-8"
    )
    assert legacy_hash.startswith("$2"), "test setup expected a real bcrypt hash"

    user = await create_user(
        session,
        email="legacy@example.com",
        hashed_password=legacy_hash,
        status=UserStatus.active,
        email_verified=True,
    )
    await session.refresh(user)

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "legacy@example.com", "password": password},
    )
    assert response.status_code == 200

    await session.refresh(user)
    assert user.hashed_password.startswith("$argon2"), (
        "expected legacy bcrypt hash to be rewritten as argon2id after a successful login"
    )

    # Second login must verify against the new argon2 hash.
    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "legacy@example.com", "password": password},
    )
    assert response.status_code == 200


async def test_malformed_jwt_returns_401(client: AsyncClient):
    """A garbage bearer token should be rejected as 401 Unauthorized with
    a WWW-Authenticate challenge, not 403. The SPA's 401 interceptor
    depends on this distinction to auto-redirect expired sessions to
    /welcome."""
    headers = {"Authorization": "Bearer not.a.valid.jwt"}
    response = await client.get("/api/v1/me", headers=headers)

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


async def test_expired_jwt_returns_401(client: AsyncClient, session: AsyncSession):
    """An expired JWT (the common case when the access token lifetime
    elapses mid-session) must return 401, not 403. Regression guard
    for the 403 -> 401 fix in get_current_user."""
    user = await create_user(session)
    expired_token = get_auth_token(user, expires_in=timedelta(seconds=-1))
    response = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


async def test_stale_token_version_returns_401(
    client: AsyncClient, session: AsyncSession
):
    """A JWT issued before a token_version bump (e.g. after logout or
    password change) must return 401 so the SPA auto-redirects instead
    of leaving a stale session in place."""
    user = await create_user(session)
    stale_token = get_auth_token(user)
    # Bump the version out-of-band to simulate a logout happening in
    # another tab.
    user.token_version += 1
    session.add(user)
    await session.commit()

    response = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {stale_token}"},
    )
    assert response.status_code == 401


async def test_new_access_token_authenticates(
    client: AsyncClient, session: AsyncSession
):
    """Dual-verify: a new-model access token (aud initiative:access) is accepted
    on the session path alongside legacy JWTs — the accept-before-issue half of
    the cutover."""
    user = await create_user(session)
    token = get_auth_token(user)

    response = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == user.id


async def test_new_access_token_stale_version_returns_401(
    client: AsyncClient, session: AsyncSession
):
    """The new token still carries ``ver``, so a token_version bump (logout /
    password change) revokes it exactly like a legacy token."""
    user = await create_user(session)
    token = get_auth_token(user)
    user.token_version += 1
    session.add(user)
    await session.commit()

    response = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


async def test_scoped_upload_token_rejected_on_session_path(
    client: AsyncClient, session: AsyncSession
):
    """Security regression: a scoped upload token carries a different aud and
    must never be honored as a session credential — dual-verify preserves this."""
    user = await create_user(session)
    upload_token, _ = create_upload_token(user_id=user.id)

    response = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {upload_token}"},
    )
    assert response.status_code == 401


async def test_upload_token_copies_session_satisfied_providers(
    client: AsyncClient, session: AsyncSession
):
    """POST /auth/upload-token mirrors the minting session's ``sat`` claim into
    the scoped token, so native media loads and the collaboration handover pass
    a policy-gated guild exactly when the session itself would — and a legacy
    session mints an empty (fail-closed) set."""
    user = await create_user(session)

    satisfied = await client.post(
        "/api/v1/auth/upload-token",
        headers={
            "Authorization": "Bearer "
            + get_auth_token(
                user,
                satisfied_providers=[7, 3],
                asserted_claims={7: {"hd": ["acme.com"]}},
                amr=["oidc:corp"],
            )
        },
    )
    assert satisfied.status_code == 200, satisfied.text
    upload = verify_upload_token(satisfied.json()["upload_token"])
    assert upload.satisfied == frozenset({3, 7})
    # And what those providers asserted, so a community narrowing one reads
    # this token the way it reads that session.
    assert upload.claims == {"7": {"hd": ["acme.com"]}}

    # A session that satisfied no provider hands the upload token an empty set
    # rather than leaving the claim off.
    unsatisfied = await client.post(
        "/api/v1/auth/upload-token", headers=get_auth_headers(user)
    )
    upload = verify_upload_token(unsatisfied.json()["upload_token"])
    assert upload.satisfied == frozenset()
    assert upload.claims == {}


async def test_logout_leaves_the_account_signed_in_elsewhere(
    client: AsyncClient, session: AsyncSession
):
    """Signing out is per device.

    ``token_version`` is the account-wide switch, so a sign-out must not touch
    it — bumping it rejected the access token every other device was holding,
    which is how signing out on a phone signed out the laptop.
    """
    user = await create_user(session)
    initial_version = user.token_version
    another_device = get_auth_token(user)

    response = await client.post("/api/v1/auth/logout", headers=get_auth_headers(user))
    assert response.status_code == 204

    await session.refresh(user)
    assert user.token_version == initial_version

    elsewhere = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {another_device}"},
    )
    assert elsewhere.status_code == 200


async def test_logout_revokes_only_the_signing_out_session(
    client: AsyncClient, session: AsyncSession
):
    """Two sign-ins on one account, one of them signs out: the other still
    rotates, and the one that asked cannot."""
    _, password = await _make_login_user(session, "twodevices@example.com")
    first = await _login(client, "twodevices@example.com", password)
    elsewhere = first.cookies.get("refresh_token")

    client.cookies.clear()
    second = await _login(client, "twodevices@example.com", password)
    signing_out = second.cookies.get("refresh_token")

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204

    client.cookies.clear()
    client.cookies.set("refresh_token", elsewhere, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200

    client.cookies.clear()
    client.cookies.set("refresh_token", signing_out, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_revokes_the_refresh_token_presented_in_the_body(
    client: AsyncClient, session: AsyncSession
):
    """A native client keeps its refresh token in secure storage and has no
    cookie to send, so it names the session it is ending in the body.

    The credential here carries a ``sid`` that names no row, so the revocation
    can only have come from the body.
    """
    user, password = await _make_login_user(session, "native-logout@example.com")
    login = await _login(client, "native-logout@example.com", password)
    presented = login.cookies.get("refresh_token")
    client.cookies.clear()

    logout = await client.post(
        "/api/v1/auth/logout",
        headers=get_auth_headers(user),
        json={"refresh_token": presented},
    )
    assert logout.status_code == 204

    client.cookies.set("refresh_token", presented, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_ignores_a_refresh_token_belonging_to_someone_else(
    client: AsyncClient, session: AsyncSession
):
    """The body names the caller's own session or nothing at all."""
    _, password = await _make_login_user(session, "bystander@example.com")
    login = await _login(client, "bystander@example.com", password)
    bystander = login.cookies.get("refresh_token")
    client.cookies.clear()

    other = await create_user(session)
    logout = await client.post(
        "/api/v1/auth/logout",
        headers=get_auth_headers(other),
        json={"refresh_token": bystander},
    )
    assert logout.status_code == 204

    client.cookies.set("refresh_token", bystander, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200


async def test_logout_clears_session_cookie(client: AsyncClient, session: AsyncSession):
    """The logout response must set an expired session_token cookie so
    browsers using HttpOnly cookie auth (the web default) actually
    forget the session."""
    user = await create_user(session)
    response = await client.post("/api/v1/auth/logout", headers=get_auth_headers(user))
    assert response.status_code == 204
    set_cookie = response.headers.get("set-cookie", "")
    assert "session_token=" in set_cookie
    # Starlette's delete_cookie sets Max-Age=0 and an expires in the
    # past. Accept either marker so the assertion is robust.
    assert "Max-Age=0" in set_cookie or "1970" in set_cookie


# --- OIDC login/callback (relying-party flow) --------------------------------
#
# End-to-end against a fake IdP: real signed id_tokens, real discovery/JWKS/
# token/userinfo endpoints behind an httpx.MockTransport, the real settings→
# provider reconcile, and the real identity-resolution ladder underneath.


def _wire_fake_idp(monkeypatch, idp: FakeIdp) -> None:
    """Point the (single) provider-client builder at the fake IdP's transport.

    Same client configuration the real builder derives from the resolved
    registry row, but every OIDC HTTP call (discovery, JWKS, token, userinfo)
    is routed through the fake — skipping the module-level discovery/JWKS
    caches keeps tests isolated from each other.
    """
    import app.api.v1.platform_endpoints.auth as auth_module

    async def _builder(system_session, row):
        return OidcProvider(
            OidcClientConfig(
                issuer=row.issuer,
                client_id=row.client_id,
                redirect_uri=auth_module.provider_callback_url(row.slug),
                client_secret="s3cret",
                scopes=row.scopes or "openid",
                provider_slug=auth_module._provider_state_key(row),
            ),
            client_factory=idp.client_factory(),
        )

    monkeypatch.setattr(auth_module, "_build_row_oidc_provider", _builder)


async def _enable_platform_oidc(session: AsyncSession, **overrides) -> None:
    """Configure a live platform OIDC provider — a registry row with the
    platform slug plus its client secret (the row is the source of truth)."""
    from app.services.auth.platform_provider import upsert_platform_provider

    values = {
        "enabled": True,
        "issuer": OIDC_ISSUER,
        "client_id": OIDC_CLIENT_ID,
        "client_secret": "s3cret",
        "scopes": ["openid", "email", "profile"],
        "provider_name": "Test IdP",
    }
    values.update(overrides)
    await upsert_platform_provider(session, **values)


async def _begin_login(
    client: AsyncClient, login_params: dict | None = None
) -> tuple[str, str]:
    """GET /oidc/login and return the (state, nonce) sent to the IdP."""
    response = await client.get(
        "/api/v1/auth/oidc/login", params=login_params or {}, follow_redirects=False
    )
    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith(f"{OIDC_ISSUER}/authorize?")
    query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    return query["state"], query["nonce"]


async def _run_oidc_flow(
    client: AsyncClient,
    idp: FakeIdp,
    *,
    id_token_claims: dict | None = None,
    login_params: dict | None = None,
):
    """The full login → IdP → callback round trip; returns the callback response."""
    state, nonce = await _begin_login(client, login_params)
    idp.token_response = httpx.Response(
        200,
        json={
            "access_token": "at-1",
            "refresh_token": "rt-1",
            "id_token": mint_id_token(nonce=nonce, **(id_token_claims or {})),
            "token_type": "Bearer",
        },
    )
    return await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )


async def _federated_identities(session: AsyncSession) -> list[FederatedIdentity]:
    return list((await session.exec(select(FederatedIdentity))).all())


async def test_oidc_login_requires_configured_platform_posture(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """No OIDC config → 404; configured → the flow starts. Configuration is
    the whole of what an operator-global login needs."""
    response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert response.status_code == 404
    assert response.json()["detail"] == "OIDC_NOT_ENABLED"

    await _enable_platform_oidc(session)
    _wire_fake_idp(monkeypatch, FakeIdp())
    response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert response.status_code in (302, 307)


async def test_oidc_callback_gated_like_login(
    client: AsyncClient, session: AsyncSession
):
    """The callback resolves its provider the same way the login does, so an
    unconfigured instance 404s on both."""
    response = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert response.status_code == 404


async def test_oidc_login_redirects_to_idp_with_pkce(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    await _enable_platform_oidc(session)
    _wire_fake_idp(monkeypatch, FakeIdp())

    response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith(f"{OIDC_ISSUER}/authorize?")
    query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    assert query["client_id"] == OIDC_CLIENT_ID
    assert query["response_type"] == "code"
    assert query["code_challenge_method"] == "S256"
    assert query["nonce"]
    assert query["state"]


async def test_oidc_login_rejects_non_https_authorization_endpoint(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A discovery doc whose authorization_endpoint isn't https must not be
    used as a redirect target — discovery refuses it and the endpoint surfaces
    a clean 500 (CodeQL py/url-redirection)."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    idp.discovery_doc["authorization_endpoint"] = "http://evil.example.com/auth"
    _wire_fake_idp(monkeypatch, idp)

    response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert response.status_code == 500
    assert response.json()["detail"] == "OIDC_METADATA_INCOMPLETE"


async def test_oidc_login_rejects_incomplete_discovery(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    del idp.discovery_doc["authorization_endpoint"]
    _wire_fake_idp(monkeypatch, idp)

    response = await client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert response.status_code == 500
    assert response.json()["detail"] == "OIDC_METADATA_INCOMPLETE"


async def test_oidc_callback_provisions_new_user_and_sets_cookie(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Happy path: a verified id_token provisions the unknown user, links the
    federated identity, and issues the web session cookie."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "new@example.com",
            "username": "new",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)
    assert response.headers["location"].endswith("/oidc/callback")
    assert SESSION_COOKIE_NAME in response.cookies

    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("new@example.com"))
        )
    ).one()
    assert await addresses.has_proven_address(session, user_id=user.id)
    # SSO-only account: no password hash — the identity link carries the
    # subject, sync stamp, and (companion) refresh token.
    assert user.hashed_password is None
    identities = await _federated_identities(session)
    assert [(i.user_id, i.subject) for i in identities] == [(user.id, "idp-subject-1")]
    identity = identities[0]
    assert identity.last_synced_at is not None
    secret = await session.get(FederatedIdentitySecret, identity.id)
    assert secret is not None
    assert decrypt_token(secret.refresh_token_encrypted) == "rt-1"


async def test_oidc_callback_establishes_refresh_session(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The web callback opens a server-side session recording which provider
    satisfied the login (amr/sat), mints the new-model access token from it,
    and issues the rotating refresh cookie — parity with password login."""
    import jwt as pyjwt

    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "sso-session@example.com",
            "username": "sso-session",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)
    assert response.cookies.get(REFRESH_COOKIE_NAME)
    assert SESSION_COOKIE_NAME in response.cookies

    provider = (
        await session.exec(
            select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
        )
    ).one()
    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("sso-session@example.com"))
        )
    ).one()
    auth_session = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user.id))
    ).one()
    assert auth_session.amr == [f"oidc:{PLATFORM_OIDC_SLUG}"]
    assert auth_session.satisfied_providers == [provider.id]

    # The cookie carries the new-model access token minted from that session.
    claims = pyjwt.decode(
        response.cookies[SESSION_COOKIE_NAME], options={"verify_signature": False}
    )
    assert claims["sid"] == str(auth_session.id)
    assert claims["amr"] == [f"oidc:{PLATFORM_OIDC_SLUG}"]
    assert claims["sat"] == [provider.id]


async def test_an_oidc_sign_in_keeps_what_the_idp_said_about_it(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The id_token's own account of the authentication — which methods, which
    context class, when — is kept against the provider that performed it.

    Its own vocabulary joins the session's ``amr`` too; the markers a rule
    reads (``mfa``, ``hwk``, ``swk``) do so only where the operator has said
    this provider's word counts, which nobody has here."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "sso-assurance@example.com",
            "username": "sso-assurance",
            "email_verified": True,
            "amr": ["pwd", "mfa"],
            "acr": "phr",
            "auth_time": 1757600000,
        },
    )
    assert response.status_code in (302, 307)

    provider = (
        await session.exec(
            select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
        )
    ).one()
    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("sso-assurance@example.com"))
        )
    ).one()
    auth_session = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user.id))
    ).one()
    assert auth_session.provider_auth == {
        str(provider.id): {
            "auth_time": 1757600000,
            "amr": ["pwd", "mfa"],
            "acr": "phr",
        }
    }
    # The session gains the provider's own vocabulary and the marker naming
    # it — but not ``mfa``, which this provider has not been said to be worth
    # reading for. The record above keeps it either way.
    assert auth_session.amr == [f"oidc:{PLATFORM_OIDC_SLUG}", "pwd"]

    import jwt as pyjwt

    claims = pyjwt.decode(
        response.cookies[SESSION_COOKIE_NAME], options={"verify_signature": False}
    )
    assert claims["satd"] == auth_session.provider_auth


async def test_a_provider_whose_word_counts_contributes_its_factor(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Where the operator has said this provider reports a second factor
    honestly, the marker it names reaches the session and answers a rule that
    asks for one."""
    await _enable_platform_oidc(session)
    provider = (
        await session.exec(
            select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
        )
    ).one()
    provider.asserts_second_factor = True
    session.add(provider)
    await session.commit()
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "sso-counted@example.com",
            "username": "sso-counted",
            "email_verified": True,
            "amr": ["pwd", "mfa"],
        },
    )
    assert response.status_code in (302, 307)

    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("sso-counted@example.com"))
        )
    ).one()
    auth_session = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user.id))
    ).one()

    assert auth_session.amr == ["mfa", f"oidc:{PLATFORM_OIDC_SLUG}", "pwd"]


async def test_the_platform_provider_asserts_a_platform_identity(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A sign-in on the platform's own page asserts an address that belongs to
    no community: the route names none, so the per-community derivation has
    nothing to match."""
    from app.models.platform.user_email import UserEmail
    from app.models.platform.user_email_assertion import UserEmailAssertion

    await _enable_platform_oidc(session)
    user = await create_user(session, email="alice@personal.example.com")
    user_id = user.id
    identity_provider = (
        await session.exec(
            select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
        )
    ).one()
    provider_id = identity_provider.id
    await create_federated_identity(
        session, user, subject="idp-subject-1", provider=identity_provider
    )
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "alice@work.example.com",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)

    session.expire_all()
    rows = (
        await session.exec(select(UserEmail).where(UserEmail.user_id == user_id))
    ).all()
    work = {r.email_hash: r for r in rows}[hash_email("alice@work.example.com")]
    claim = (
        await session.exec(
            select(UserEmailAssertion).where(
                UserEmailAssertion.user_email_id == work.id
            )
        )
    ).one()
    # The assertion names the provider that made it and nothing else: an
    # address is claimed by a provider, not by a community. Which community a
    # sign-in entered is a fact about the route, and the platform's own route
    # names none.
    assert claim.provider_id == provider_id


async def test_a_silent_idp_leaves_the_token_the_shape_it_always_had(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An IdP that asserts none of it records none of it, and the access token
    carries no ``satd`` at all."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "sso-silent@example.com",
            "username": "sso-silent",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)

    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("sso-silent@example.com"))
        )
    ).one()
    auth_session = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user.id))
    ).one()
    assert auth_session.provider_auth == {}

    import jwt as pyjwt

    claims = pyjwt.decode(
        response.cookies[SESSION_COOKIE_NAME], options={"verify_signature": False}
    )
    assert "satd" not in claims


async def test_an_oidc_callback_that_cannot_open_a_session_says_so(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The provider authenticated them and the store could not record it. Back
    to the app with a code rather than a credential that cannot renew."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    async def _boom(*args, **kwargs):
        raise RuntimeError("session store down")

    monkeypatch.setattr("app.services.auth.sessions.create_session", _boom)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "sso-nostore@example.com",
            "username": "sso-nostore",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)
    assert "error=OIDC_SESSION_STORE_UNAVAILABLE" in response.headers["location"]
    assert response.cookies.get(REFRESH_COOKIE_NAME) is None
    assert SESSION_COOKIE_NAME not in response.cookies

    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("sso-nostore@example.com"))
        )
    ).one()
    rows = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user.id))
    ).all()
    assert rows == []


async def test_oidc_refresh_cookie_rotates_into_access_token(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The refresh cookie issued by the OIDC callback rotates into a fresh
    access token that authenticates, same as the password-login one."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "sso-rotate@example.com",
            "username": "sso-rotate",
            "email_verified": True,
        },
    )
    assert response.status_code in (302, 307)

    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    access_token = resp.json()["access_token"]

    me = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "sso-rotate@example.com"


async def test_provider_login_unknown_or_unready_slug_is_404(
    client: AsyncClient, session: AsyncSession
):
    """A slug with no registry row — or a row that is disabled or missing its
    client config — must not begin a login."""
    await _enable_platform_oidc(session)
    await create_auth_provider(session, slug="off", enabled=False)
    await create_auth_provider(session, slug="bare", issuer=None)

    for slug in ("nope", "off", "bare"):
        response = await client.get(
            f"/api/v1/auth/{slug}/login", follow_redirects=False
        )
        assert response.status_code == 404, slug
        assert response.json()["detail"] == "OIDC_NOT_ENABLED"


async def test_login_providers_listing(client: AsyncClient, session: AsyncSession):
    """/auth/providers lists the platform provider plus login-ready registry
    rows — and only those."""
    await _enable_platform_oidc(session)
    await create_auth_provider(session, slug="corp", display_name="Corp SSO")
    await create_auth_provider(session, slug="off", enabled=False)
    await create_auth_provider(session, slug="bare", issuer=None)

    response = await client.get("/api/v1/auth/providers")
    assert response.status_code == 200
    providers = response.json()["providers"]
    assert [(p["slug"], p["login_url"]) for p in providers] == [
        ("oidc", "/api/v1/auth/oidc/login"),
        ("corp", "/api/v1/auth/corp/login"),
    ]
    assert providers[0]["display_name"] == "Test IdP"
    assert providers[1]["kind"] == "oidc"
    # Registry ids ride along — the guild auth-policy picker stores them.
    corp_row = (
        await session.exec(select(AuthProvider).where(AuthProvider.slug == "corp"))
    ).one()
    assert providers[1]["id"] == corp_row.id


async def test_login_providers_listed_when_configured(
    client: AsyncClient, session: AsyncSession
):
    """The listing reflects configuration: an unconfigured instance offers
    none, and every login-ready operator-global row is offered."""
    response = await client.get("/api/v1/auth/providers")
    assert response.json()["providers"] == []  # nothing configured

    await _enable_platform_oidc(session)
    await create_auth_provider(session, slug="corp")
    response = await client.get("/api/v1/auth/providers")
    slugs = {p["slug"] for p in response.json()["providers"]}
    assert {"oidc", "corp"} <= slugs


async def test_oidc_next_returns_browser_to_requested_page(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A validated ``next`` path given to /login rides the flow and comes back
    on the frontend callback redirect, so a step-up returns the browser to the
    page it interrupted."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "stepup@example.com",
            "username": "stepup",
            "email_verified": True,
        },
        login_params={"next": "/c/5/projects/3"},
    )
    assert response.status_code in (302, 307)
    assert response.headers["location"].endswith(
        "/oidc/callback?next=%2Fc%2F5%2Fprojects%2F3"
    )


async def test_oidc_next_rejects_non_relative_paths(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Only a rooted relative path is carried: absolute URLs, protocol-relative
    forms, and unrooted strings never set the cookie — and such a cookie is
    dropped at the callback rather than echoed."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    for bad in ("https://evil.example/x", "//evil.example", "relative", "/a\\b"):
        response = await client.get(
            "/api/v1/auth/oidc/login",
            params={"next": bad},
            follow_redirects=False,
        )
        assert response.status_code in (302, 307)
        assert "oidc_next" not in response.cookies, bad

    # Cookie changed between login and callback: the callback re-validates
    # and redirects without any next parameter.
    client.cookies.set("oidc_next", "https://evil.example/x")
    response = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={
            "email": "tamper@example.com",
            "username": "tamper",
            "email_verified": True,
        },
    )
    assert response.headers["location"].endswith("/oidc/callback")


async def test_state_from_one_provider_rejected_by_another(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A flow state begun with one provider must not complete against another
    — the state carries the slug it was minted for."""
    await _enable_platform_oidc(session)
    await create_auth_provider(session, slug="corp")
    _wire_fake_idp(monkeypatch, FakeIdp())

    state, _nonce = await _begin_login(client)  # begun with the platform slug
    response = await client.get(
        "/api/v1/auth/corp/callback",
        params={"code": "code-1", "state": state},
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    assert "invalid_state" in response.headers["location"]
    assert "session_token" not in response.cookies


async def test_row_provider_full_login_flow(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """End-to-end against a registry-managed provider row: begin at the
    per-slug login URL, complete at its callback, and the provisioned identity
    and session belong to THAT provider (not the platform one)."""
    await _enable_platform_oidc(session)
    row = await create_auth_provider(session, slug="corp")
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    begin = await client.get("/api/v1/auth/corp/login", follow_redirects=False)
    assert begin.status_code in (302, 307)
    location = begin.headers["location"]
    assert location.startswith(f"{OIDC_ISSUER}/authorize?")
    query = {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}
    assert query["redirect_uri"].endswith("/api/v1/auth/corp/callback")

    idp.token_response = httpx.Response(
        200,
        json={
            "access_token": "at-corp",
            "refresh_token": "rt-corp",
            "id_token": mint_id_token(
                nonce=query["nonce"],
                email="corp-user@example.com",
                email_verified=True,
            ),
            "token_type": "Bearer",
        },
    )
    response = await client.get(
        "/api/v1/auth/corp/callback",
        params={"code": "code-corp", "state": query["state"]},
        follow_redirects=False,
    )
    assert response.status_code in (302, 307)
    assert SESSION_COOKIE_NAME in response.cookies

    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("corp-user@example.com"))
        )
    ).one()
    identity = (
        await session.exec(
            select(FederatedIdentity).where(FederatedIdentity.user_id == user.id)
        )
    ).one()
    assert identity.provider_id == row.id
    auth_session = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user.id))
    ).one()
    assert auth_session.amr == ["oidc:corp"]
    assert auth_session.satisfied_providers == [row.id]


async def test_oidc_callback_rejects_forged_state(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An unknown state is refused, and so is a genuine one presented by a
    browser other than the one the sign-in began in."""
    await _enable_platform_oidc(session)
    _wire_fake_idp(monkeypatch, FakeIdp())

    genuine, _nonce = await _begin_login(client)
    client.cookies.clear()
    for state in ("forged", genuine):
        response = await client.get(
            "/api/v1/auth/oidc/callback",
            params={"code": "code-1", "state": state},
            follow_redirects=False,
        )
        assert response.status_code in (302, 307)
        assert "invalid_state" in response.headers["location"]
        assert "session_token" not in response.cookies


async def test_oidc_callback_rejects_id_token_signed_by_wrong_key(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The endpoint-level proof that signature verification is live: a token
    minted with a key outside the provider's JWKS never becomes a session."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(client, idp, id_token_claims={"priv": OTHER_KEY})
    assert response.status_code in (302, 307)
    assert "id_token_rejected" in response.headers["location"]
    assert "session_token" not in response.cookies
    assert await _federated_identities(session) == []


@pytest.mark.parametrize(
    ("public_registration_enabled", "guild_creation_disabled"),
    [(False, False), (True, True)],
)
async def test_oidc_callback_blocks_new_user_when_registration_disabled(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch,
    public_registration_enabled: bool,
    guild_creation_disabled: bool,
):
    """OIDC callback must honor the same no-invite registration gate as /register."""
    from app.core import config as cfg

    monkeypatch.setattr(
        cfg.settings, "ENABLE_PUBLIC_REGISTRATION", public_registration_enabled
    )
    monkeypatch.setattr(cfg.settings, "DISABLE_GUILD_CREATION", guild_creation_disabled)
    # Must have at least one existing user so the bootstrap exception is off.
    await create_user(session)
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(
        client, idp, id_token_claims={"email": "brandnew@example.com"}
    )
    assert response.status_code in (302, 307)
    assert "OIDC_REGISTRATION_DISABLED" in response.headers["location"]
    assert "session_token" not in response.cookies
    assert (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("brandnew@example.com"))
        )
    ).one_or_none() is None


@pytest.mark.parametrize(
    "verified_claim",
    [
        pytest.param(False, id="email_verified_false"),
        pytest.param(None, id="email_verified_absent"),
    ],
)
async def test_oidc_callback_refuses_existing_account_when_email_unverified(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch,
    verified_claim,
):
    """An OIDC login must not link to / log into a pre-existing local
    account when the IdP does not assert ``email_verified is True`` for a
    matching email. A false claim (IdP allows unverified emails) and an absent
    claim (e.g. Azure AD) are both refused — fail closed."""
    existing = await create_user(
        session,
        email="victim@example.com",
        email_verified=False,
    )
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    claims = {"email": "victim@example.com", "name": "Attacker"}
    if verified_claim is not None:
        claims["email_verified"] = verified_claim
    response = await _run_oidc_flow(client, idp, id_token_claims=claims)

    assert response.status_code in (302, 307)
    assert "OIDC_EMAIL_UNVERIFIED" in response.headers["location"]
    # No session was issued and no link was written.
    assert "session_token" not in response.cookies
    assert await _federated_identities(session) == []
    # The account must not have been silently promoted to verified.
    await session.refresh(existing)
    assert not await addresses.has_proven_address(session, user_id=existing.id)


async def test_oidc_callback_links_existing_account_when_email_verified(
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch,
):
    """Counterpart: a matching email with ``email_verified=true`` logs
    into the existing account, promotes it to verified, and now writes the
    (provider, subject) link so later logins resolve by subject."""
    existing = await create_user(
        session,
        email="member@example.com",
        email_verified=False,
    )
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    claims = {
        "email": "member@example.com",
        "email_verified": True,
        "name": "Member",
    }
    response = await _run_oidc_flow(client, idp, id_token_claims=claims)

    assert response.status_code in (302, 307)
    assert "OIDC_EMAIL_UNVERIFIED" not in response.headers["location"]
    assert SESSION_COOKIE_NAME in response.cookies
    await session.refresh(existing)
    assert await addresses.has_proven_address(session, user_id=existing.id)
    identities = await _federated_identities(session)
    assert [(i.user_id, i.subject) for i in identities] == [
        (existing.id, "idp-subject-1")
    ]

    # The second login resolves through the link (and still issues a session).
    again = await _run_oidc_flow(client, idp, id_token_claims=claims)
    assert SESSION_COOKIE_NAME in again.cookies
    assert len(await _federated_identities(session)) == 1


async def test_a_provider_proving_an_added_address_tells_the_account(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An address the person added and had not proved is proved when their
    provider asserts it, and the account is told as the emailed link would."""
    user = await create_user(session, email="linked@example.com")
    user_id = user.id
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)
    first = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={"email": "linked@example.com", "email_verified": True},
    )
    assert SESSION_COOKIE_NAME in first.cookies
    addresses.record_address(
        session,
        user_id=user_id,
        email="work@example.com",
        source=addresses.SOURCE_ADDED,
        verified=False,
        is_primary=False,
    )
    await session.commit()

    told: list[str] = []

    async def _capture(user_, pieces, **_):
        told.append(pieces.subject)

    monkeypatch.setattr(email_outbox, "enqueue_account_letter", _capture)

    again = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={"email": "work@example.com", "email_verified": True},
    )
    assert SESSION_COOKIE_NAME in again.cookies
    assert told == [email_t("address.proved.subject", "en", escape=False)]


async def test_a_provider_adding_an_address_tells_the_account(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An address a provider proves on an account that already had a proved
    one is a new way in, and the account is told. The address an account is
    created with is not news."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)
    told: list[str] = []

    async def _capture(user_, pieces, **_):
        told.append(pieces.subject)

    monkeypatch.setattr(email_outbox, "enqueue_account_letter", _capture)

    created = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={"email": "made-here@example.com", "email_verified": True},
    )
    assert SESSION_COOKIE_NAME in created.cookies
    assert told == []

    proved = email_t("address.proved.subject", "en", escape=False)
    again = await _run_oidc_flow(
        client,
        idp,
        id_token_claims={"email": "asserted@example.com", "email_verified": True},
    )
    assert SESSION_COOKIE_NAME in again.cookies
    assert told == [proved]

    # Asserted unverified first, it is held unproved and says nothing; the
    # sign-in that later proves it tells the account.
    for verified, expected in ((False, [proved]), (True, [proved, proved])):
        later = await _run_oidc_flow(
            client,
            idp,
            id_token_claims={"email": "later@example.com", "email_verified": verified},
        )
        assert SESSION_COOKIE_NAME in later.cookies
        assert told == expected


async def test_oidc_callback_refuses_deactivated_account(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    existing = await create_user(session, email="gone@example.com")
    existing.status = UserStatus.deactivated
    session.add(existing)
    await session.commit()
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)

    claims = {"email": "gone@example.com", "email_verified": True}
    response = await _run_oidc_flow(client, idp, id_token_claims=claims)
    assert response.status_code in (302, 307)
    assert OidcMessages.ACCOUNT_INACTIVE in response.headers["location"]
    assert "session_token" not in response.cookies
    assert await _federated_identities(session) == []


async def test_oidc_callback_mobile_flow_hands_back_a_code(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The app's sign-in comes back as a one-time code bound to the challenge
    it began with. The verifier behind that challenge opens a session that
    records the provider and is a device's; any answer spends the code. A
    begin with no challenge, from an older app, is asked to update."""
    await _enable_platform_oidc(session)
    idp = FakeIdp()
    _wire_fake_idp(monkeypatch, idp)
    claims = {
        "email": "mobile@example.com",
        "username": "mobile",
        "email_verified": True,
    }

    async def code_for(verifier: str) -> str:
        response = await _run_oidc_flow(
            client,
            idp,
            id_token_claims=claims,
            login_params={
                "mobile": "true",
                "device_name": "Pixel",
                "code_challenge": s256(verifier),
            },
        )
        location = response.headers["location"]
        assert location.startswith("initiative://oidc/callback?")
        query = parse_qs(urlsplit(location).query)
        assert set(query) == {"code"}
        return query["code"][0]

    verifier = secrets.token_urlsafe(48)
    code = await code_for(verifier)
    wrong = await client.post(
        "/api/v1/auth/native/token",
        json={"code": code, "code_verifier": secrets.token_urlsafe(48)},
    )
    assert wrong.status_code == 401
    spent = await client.post(
        "/api/v1/auth/native/token", json={"code": code, "code_verifier": verifier}
    )
    assert spent.status_code == 401

    code = await code_for(verifier)
    redeemed = await client.post(
        "/api/v1/auth/native/token", json={"code": code, "code_verifier": verifier}
    )
    assert redeemed.status_code == 200
    assert redeemed.json()["refresh_token"]
    provider = (
        await session.exec(
            select(AuthProvider).where(AuthProvider.slug == PLATFORM_OIDC_SLUG)
        )
    ).one()
    auth_session = (await session.exec(select(AuthSession))).one()
    assert auth_session.satisfied_providers == [provider.id]
    assert auth_session.device_name == "Pixel"
    assert auth_session.install_id is not None

    legacy = await _run_oidc_flow(
        client,
        idp,
        id_token_claims=claims,
        login_params={"mobile": "true", "device_name": "Pixel"},
    )
    location = urlsplit(legacy.headers["location"])
    assert parse_qs(location.query) == {"error": ["NATIVE_APP_UPDATE_REQUIRED"]}


async def test_oidc_callback_enriches_missing_email_from_userinfo(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An IdP that keeps email out of the id_token (userinfo-only) still
    provisions with the real address — via verified-sub-matched enrichment."""
    await _enable_platform_oidc(session)
    idp = FakeIdp(
        userinfo_claims={
            "sub": "idp-subject-1",
            "email": "fromuserinfo@example.com",
            "username": "fromuserinfo",
            "email_verified": True,
        }
    )
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(client, idp, id_token_claims={"email": None})
    assert response.status_code in (302, 307)
    provisioned = await session.exec(
        select(User)
        .join(UserEmail, UserEmail.user_id == User.id)
        .where(UserEmail.email_hash == hash_email("fromuserinfo@example.com"))
    )
    assert provisioned.one_or_none() is not None


async def test_oidc_callback_ignores_userinfo_with_mismatched_sub(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A userinfo document for a different subject must not contribute claims
    (OIDC Core §5.3.2) — the login falls back to the synthetic address."""
    await _enable_platform_oidc(session)
    idp = FakeIdp(
        userinfo_claims={"sub": "someone-else", "email": "hijack@example.com"}
    )
    _wire_fake_idp(monkeypatch, idp)

    response = await _run_oidc_flow(client, idp, id_token_claims={"email": None})
    assert response.status_code in (302, 307)
    assert (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("hijack@example.com"))
        )
    ).one_or_none() is None
    # Provisioned off the subject instead — never off the mismatched userinfo.
    assert (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("idp-subject-1@oidc.local"))
        )
    ).one_or_none() is not None


# --- Password policy -------------------------------------------------


async def test_register_rejects_password_shorter_than_minimum(client: AsyncClient):
    """11-char passwords (the previous loose default in our own tests)
    must now be rejected. Locks down the new NIST-aligned 12-char floor."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "tooshort@example.com",
            "username": "tooshort",
            "password": "elevenchars",  # 11 chars
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "PASSWORD_TOO_SHORT"


async def test_register_rejects_breached_password(client: AsyncClient, monkeypatch):
    """A password that passes the length floor but appears in HIBP must
    be rejected with the BREACHED code, not silently accepted."""
    from app.services import hibp as hibp_module

    async def _breached(_pw: str) -> bool:
        return True

    monkeypatch.setattr(hibp_module, "is_password_breached", _breached)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "breached@example.com",
            "username": "breached",
            "password": "long-enough-but-pwned",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "PASSWORD_BREACHED"


async def test_register_accepts_compliant_password(client: AsyncClient):
    """Sanity check: a 12+ char password with HIBP disabled (default in
    tests) succeeds, so the policy gate isn't accidentally rejecting
    everything."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ok@example.com",
            "username": "ok-user",
            "password": "twelve-chars",  # exactly 12 chars
        },
    )
    assert response.status_code == 201


async def test_login_grandfathers_existing_short_password(
    client: AsyncClient, session: AsyncSession
):
    """Users whose hashes were written before the policy landed must keep
    logging in. The policy applies only to flows that *set* a new
    password — never to ``verify_password`` on the login path."""
    short_password = "shortpw"  # 7 chars — would fail the policy if applied
    await create_user(
        session,
        email="legacy-short@example.com",
        hashed_password=get_password_hash(short_password),
        status=UserStatus.active,
        email_verified=True,
    )

    response = await client.post(
        "/api/v1/auth/token",
        data={"username": "legacy-short@example.com", "password": short_password},
    )
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_password_reset_rejects_short_password(
    client: AsyncClient, session: AsyncSession
):
    """Password reset must run the same policy as registration. The
    reset token must NOT be consumed when the candidate fails — a
    failed attempt would otherwise burn the user's only reset link."""
    from app.models.platform.user_token import UserToken, UserTokenPurpose
    from app.services.platform import user_tokens

    user = await create_user(session, email="reset@example.com")
    token = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.password_reset,
    )

    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": token, "password": "elevenchars"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "PASSWORD_TOO_SHORT"

    # Reset token must still be redeemable — we failed before consuming it.
    # Tokens are stored hashed, so look the row up by its hash.
    from sqlmodel import select

    from app.services.platform.user_tokens import _hash_token

    fresh = (
        await session.exec(
            select(UserToken).where(UserToken.token == _hash_token(token))
        )
    ).one()
    assert fresh.consumed_at is None


async def test_password_reset_revokes_sessions_on_every_device(
    client: AsyncClient, session: AsyncSession
):
    """A successful forgot-password reset invalidates the user's outstanding
    JWT (token_version bump) and every session, the app's included."""
    from app.models.platform.user_token import UserTokenPurpose
    from app.services.auth import sessions as session_service
    from app.services.platform import user_tokens

    user = await create_user(session, email="reset-revoke@example.com")
    old_jwt = get_auth_token(user)
    phone = await session_service.create_session(
        session,
        user_id=user.id,
        amr=["pwd"],
        satisfied_providers=[],
        install_id=uuid.uuid4(),
    )
    phone_id = phone.session.id
    reset_token = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.password_reset,
    )

    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": reset_token, "password": "brand-new-secret-123"},
    )
    assert response.status_code == 200

    # Old JWT rejected (token_version bumped).
    post_jwt = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {old_jwt}"},
    )
    assert post_jwt.status_code == 401

    # The phone's session is ended too.
    session.expire_all()
    ended = await session.get(AuthSession, phone_id)
    assert ended is not None
    assert ended.revoked_at is not None


async def test_password_reset_tells_the_account(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A changed password is announced, as a changed passkey or factor is."""
    from app.models.platform.user_token import UserTokenPurpose
    from app.services.platform import user_tokens

    user = await create_user(session, email="reset-told@example.com")
    user_id = user.id
    reset_token = await user_tokens.create_token(
        session,
        user_id=user_id,
        purpose=UserTokenPurpose.password_reset,
    )

    told: list[int] = []

    async def _capture(user_, pieces, **_):
        told.append(user_.id)

    monkeypatch.setattr(email_outbox, "enqueue_account_letter", _capture)

    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": reset_token, "password": "brand-new-secret-123"},
    )
    assert response.status_code == 200, response.text
    assert told == [user_id]


async def test_register_rolls_back_when_guild_seed_fails(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A DB-side guild-seed failure mid-registration rolls back the whole
    registration — no orphaned user or guild rows — and returns 500.

    The seed failure here aborts the transaction, so registration must roll back
    before its cleanup queries run; otherwise they raise PendingRollbackError and
    the already-committed user + guild rows are stranded.
    """
    from sqlalchemy import text
    from sqlmodel import select

    from app.models.platform.guild import Guild
    from app.services.platform import guilds as guilds_service

    async def _boom(seed_session, *args, **kwargs):
        # Simulate a real DB failure: abort the transaction like a failing query
        # would, so the cleanup path MUST rollback before it can delete anything.
        await seed_session.exec(text("SELECT * FROM does_not_exist_xyz"))

    monkeypatch.setattr(guilds_service, "seed_guild_content", _boom)

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "seedfail@example.com",
            "username": "seedfail",
            "password": "securepassword123",
            "community": {"name": "Seed Fail"},
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "UNABLE_TO_CREATE_USER"

    # Neither the user nor its guild may survive a failed registration.
    users = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("seedfail@example.com"))
        )
    ).all()
    assert users == [], "user row must be rolled back when guild seeding fails"
    guilds = (await session.exec(select(Guild))).all()
    assert guilds == [], "guild row must be rolled back when guild seeding fails"


# --- New login model: refresh issuance + rotation ------------------------


async def _make_login_user(
    session: AsyncSession,
    email: str = "refresh@example.com",
    password: str = "testpassword123",
) -> tuple[User, str]:
    user = await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(password),
        status=UserStatus.active,
        email_verified=True,
    )
    return user, password


async def _login(client: AsyncClient, email: str, password: str):
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


async def test_login_sets_refresh_cookie(client: AsyncClient, session: AsyncSession):
    """Login additively issues a rotating refresh cookie (the legacy session
    cookie is still set too — this is additive-first)."""
    _, password = await _make_login_user(session, "cookie@example.com")
    resp = await _login(client, "cookie@example.com", password)

    assert resp.status_code == 200
    assert resp.cookies.get("refresh_token")
    assert resp.cookies.get("session_token")  # legacy cookie unchanged


async def test_login_issues_session_access_token(
    client: AsyncClient, session: AsyncSession
):
    """Login mints the new-model access token: short-lived (AUTH_ACCESS_TTL),
    carrying the server-side session id and satisfied factors (sid/amr/sat)."""
    import jwt as pyjwt

    from app.core.config import settings as app_settings

    _, password = await _make_login_user(session, "newmodel@example.com")
    resp = await _login(client, "newmodel@example.com", password)
    assert resp.status_code == 200

    claims = pyjwt.decode(
        resp.json()["access_token"], options={"verify_signature": False}
    )
    assert claims["amr"] == ["pwd"]
    assert claims["sat"] == []
    assert claims["sid"]
    assert resp.cookies.get(REFRESH_COOKIE_NAME)
    set_cookies = resp.headers.get_list("set-cookie")
    expected_age = f"Max-Age={app_settings.AUTH_ACCESS_TTL_MINUTES * 60}"
    assert any(
        c.startswith(f"{SESSION_COOKIE_NAME}=") and expected_age in c
        for c in set_cookies
    ), set_cookies


async def test_a_login_that_cannot_open_a_session_is_refused(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A sign-in is the session. If the store cannot be written there is
    nothing to hand back, and the request says so rather than issuing a
    credential that cannot renew."""
    _, password = await _make_login_user(session, "nostore@example.com")

    async def _boom(*args, **kwargs):
        raise RuntimeError("session store down")

    monkeypatch.setattr("app.services.auth.sessions.create_session", _boom)

    resp = await _login(client, "nostore@example.com", password)
    assert resp.status_code == 503
    assert resp.json()["detail"] == "SESSION_STORE_UNAVAILABLE"
    assert resp.cookies.get(REFRESH_COOKIE_NAME) is None
    assert SESSION_COOKIE_NAME not in resp.cookies


async def test_refresh_rotates_and_new_token_authenticates(
    client: AsyncClient, session: AsyncSession
):
    """The refresh cookie rotates into a fresh access token that authenticates."""
    _, password = await _make_login_user(session, "rot@example.com")
    await _login(client, "rot@example.com", password)

    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    access_token = resp.json()["access_token"]
    assert resp.cookies.get("refresh_token")  # a new (rotated) refresh was set

    me = await client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "rot@example.com"


async def test_a_refresh_that_cannot_finish_leaves_the_cookie_usable(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A rotation spends the presented cookie and mints a replacement whose
    secret only the response carries, so the name the new token will use is
    minted in that same transaction. A failure therefore leaves the presented
    cookie live, and it rotates on the next attempt."""
    from app.api.v1.platform_endpoints import auth as auth_endpoints

    _, password = await _make_login_user(session, "stranded@example.com")
    login = await _login(client, "stranded@example.com", password)
    presented = login.cookies.get("refresh_token")

    async def _fails(*args, **kwargs):
        raise RuntimeError("no name for you")

    monkeypatch.setattr(
        auth_endpoints.subject_service, "subject_for_user", _fails, raising=True
    )
    with pytest.raises(RuntimeError):
        await client.post("/api/v1/auth/refresh")
    monkeypatch.undo()

    # The same cookie still rotates: the failed attempt spent nothing.
    client.cookies.clear()
    client.cookies.set("refresh_token", presented, path="/api/v1/auth")
    retry = await client.post("/api/v1/auth/refresh")
    assert retry.status_code == 200
    assert retry.cookies.get("refresh_token") != presented


async def test_refresh_without_cookie_returns_401(client: AsyncClient):
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "NOT_AUTHENTICATED"


async def test_refresh_with_invalid_cookie_returns_401(client: AsyncClient):
    client.cookies.set("refresh_token", "not-a-real-token", path="/api/v1/auth")
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "INVALID_REFRESH_TOKEN"
    # The rejection must actually clear the stale cookie so the browser stops
    # resending it — the delete header has to ride on the returned response, not
    # a raised exception (FastAPI drops the injected response's cookies on raise).
    set_cookies = resp.headers.get_list("set-cookie")
    assert any("refresh_token=" in c and "Max-Age=0" in c for c in set_cookies), (
        set_cookies
    )


async def test_reused_refresh_token_returns_401(
    client: AsyncClient, session: AsyncSession
):
    """Endpoint-level theft detection: replaying a spent refresh token is 401
    (and the service revokes the chain — covered in the service tests)."""
    _, password = await _make_login_user(session, "reuse@example.com")
    login = await _login(client, "reuse@example.com", password)
    first_refresh = login.cookies.get("refresh_token")

    # Spend it once (jar rotates to the new token).
    ok = await client.post("/api/v1/auth/refresh")
    assert ok.status_code == 200

    # Replay the original (now spent) token.
    client.cookies.clear()
    client.cookies.set("refresh_token", first_refresh, path="/api/v1/auth")
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401
    assert replay.json()["detail"] == "INVALID_REFRESH_TOKEN"


async def test_logout_revokes_refresh_session(
    client: AsyncClient, session: AsyncSession
):
    """Logout revokes the refresh session, so a captured refresh token can't
    rotate afterward — closing the gap where token_version only killed the
    access side."""
    _, password = await _make_login_user(session, "lo@example.com")
    login = await _login(client, "lo@example.com", password)
    captured = login.cookies.get("refresh_token")

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204

    client.cookies.clear()
    client.cookies.set("refresh_token", captured, path="/api/v1/auth")
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_logout_with_an_expired_access_token_still_ends_the_session(
    client: AsyncClient, session: AsyncSession
):
    """A client whose access token has run out signs out with the refresh
    token it holds, and that session stops renewing."""
    user, password = await _make_login_user(session, "expired-logout@example.com")
    login = await _login(client, "expired-logout@example.com", password)
    captured = login.cookies.get("refresh_token")
    expired = get_auth_token(user, expires_in=timedelta(seconds=-1))

    client.cookies.clear()
    client.cookies.set("refresh_token", captured, path="/api/v1/auth")
    logout = await client.post(
        "/api/v1/auth/logout", headers={"Authorization": f"Bearer {expired}"}
    )
    assert logout.status_code == 204

    client.cookies.clear()
    client.cookies.set("refresh_token", captured, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_logout_with_no_access_token_ends_only_the_presented_session(
    client: AsyncClient, session: AsyncSession
):
    """Signing out without an access token ends the session the refresh token
    names and leaves the account's other sign-ins renewing."""
    _, password = await _make_login_user(session, "bare-logout@example.com")
    first = await _login(client, "bare-logout@example.com", password)
    elsewhere = first.cookies.get("refresh_token")
    client.cookies.clear()
    second = await _login(client, "bare-logout@example.com", password)
    signing_out = second.cookies.get("refresh_token")

    client.cookies.clear()
    logout = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": signing_out}
    )
    assert logout.status_code == 204

    client.cookies.set("refresh_token", signing_out, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401

    client.cookies.clear()
    client.cookies.set("refresh_token", elsewhere, path="/api/v1/auth")
    assert (await client.post("/api/v1/auth/refresh")).status_code == 200


async def test_password_change_revokes_refresh_session(
    client: AsyncClient, session: AsyncSession
):
    """A credential change must invalidate refresh sessions too — otherwise a
    captured refresh token keeps minting valid access tokens (at the new
    token_version) right past the password change."""
    _, password = await _make_login_user(session, "pwchange@example.com")
    login = await _login(client, "pwchange@example.com", password)
    captured = login.cookies.get("refresh_token")

    change = await client.patch(
        "/api/v1/me",
        json={"password": "newpassword456", "current_password": password},
    )
    assert change.status_code == 200

    # The refresh token captured before the change can no longer rotate.
    client.cookies.clear()
    client.cookies.set("refresh_token", captured, path="/api/v1/auth")
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401


async def test_registering_records_when_the_password_was_set(
    client: AsyncClient, session: AsyncSession
):
    from sqlmodel import select

    from app.core.encryption import hash_email
    from app.models.platform.user import User

    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "stamped@example.com",
            "username": "stamped",
            "password": "a-perfectly-fine-secret-1",
        },
    )
    assert response.status_code == 201

    session.expire_all()
    user = (
        await session.exec(
            select(User)
            .join(UserEmail, UserEmail.user_id == User.id)
            .where(UserEmail.email_hash == hash_email("stamped@example.com"))
        )
    ).one()
    assert user.password_set_at is not None


async def test_password_reset_records_when_the_password_was_set(
    client: AsyncClient, session: AsyncSession
):
    """An account carrying a hash nobody set — the pre-0152 SSO case — becomes
    known the moment somebody actually sets one."""
    from app.models.platform.user_token import UserTokenPurpose
    from app.services.platform import user_tokens

    user = await create_user(session, email="reset-stamp@example.com")
    user.password_set_at = None
    session.add(user)
    await session.commit()
    user_id = user.id

    reset_token = await user_tokens.create_token(
        session, user_id=user_id, purpose=UserTokenPurpose.password_reset
    )
    response = await client.post(
        "/api/v1/auth/password/reset",
        json={"token": reset_token, "password": "brand-new-secret-123"},
    )
    assert response.status_code == 200

    session.expire_all()
    refreshed = await session.get(User, user_id)
    assert refreshed.password_set_at is not None


async def test_upload_token_carries_the_second_factor(
    client: AsyncClient, session: AsyncSession
):
    """An upload made in a community that asks for a second factor is made by
    somebody who presented one, so the scoped token copies the markers the way
    it copies the satisfied set beside it — narrowed to the ones a rule can be
    written against, so ``pwd`` and the provider's own vocabulary stay out."""
    user = await create_user(session)

    with_factor = await client.post(
        "/api/v1/auth/upload-token",
        headers={
            "Authorization": "Bearer " + get_auth_token(user, amr=["pwd", "otp", "mfa"])
        },
    )
    assert with_factor.status_code == 200, with_factor.text
    assert verify_upload_token(with_factor.json()["upload_token"]).markers == {"mfa"}

    with_a_key = await client.post(
        "/api/v1/auth/upload-token",
        headers={
            "Authorization": "Bearer " + get_auth_token(user, amr=["pwd", "hwk", "mfa"])
        },
    )
    assert verify_upload_token(with_a_key.json()["upload_token"]).markers == {
        "hwk",
        "mfa",
    }

    without = await client.post(
        "/api/v1/auth/upload-token",
        headers={"Authorization": "Bearer " + get_auth_token(user, amr=["pwd"])},
    )
    assert verify_upload_token(without.json()["upload_token"]).markers == frozenset()
