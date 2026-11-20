"""Enrolling a factor, and signing in against it."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from httpx2 import AsyncClient, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.login_methods import LoginMethod
from app.core.security import get_password_hash
from app.models.platform.user import User, UserStatus
from app.services.auth import totp as totp_service
from app.testing import (
    create_user,
    get_auth_headers,
    get_auth_token,
    signed_in_headers,
)

PASSWORD = "correct-horse-battery-staple"


def _next_code(secret: str) -> str:
    """The code for the interval after this one.

    Confirming an enrolment takes the interval its code came from, so a sign-in
    in the same thirty seconds cannot present that code again — which is the
    rule working, not a problem to route around. One interval ahead is inside
    the drift a clock is allowed and is still ahead of the recorded one.
    """
    at = datetime.now(UTC) + timedelta(seconds=totp_service.TOTP_PERIOD)
    return pyotp.TOTP(secret).at(at)


async def _account(session: AsyncSession, email: str) -> User:
    return await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(PASSWORD),
        status=UserStatus.active,
        email_verified=True,
    )


async def _sign_in(
    client: AsyncClient, email: str, password: str = PASSWORD
) -> Response:
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


async def _enrol(
    client: AsyncClient, session: AsyncSession, email: str
) -> tuple[User, str, list[str]]:
    """Enrol and confirm, returning (user, secret, recovery codes)."""
    user = await _account(session, email)
    headers = get_auth_headers(user)
    started = await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": PASSWORD},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    confirmed = await client.post(
        "/api/v1/auth/totp/confirm",
        json={"code": pyotp.TOTP(secret).now()},
        headers=headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    return user, secret, confirmed.json()["codes"]


async def test_enrolling_hands_over_a_seed_and_a_uri(
    client: AsyncClient, session: AsyncSession
):
    """The URI carries what an authenticator reads. Started and abandoned
    costs the account nothing — the sign-in is unchanged."""
    user = await _account(session, "enrol@example.com")
    response = await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": PASSWORD},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["secret"]
    uri = body["otpauth_uri"]
    assert uri.startswith("otpauth://totp/")
    assert f"secret={body['secret']}" in uri
    for part in ("issuer=", "digits=6", "period=30"):
        assert part in uri

    signed_in = await _sign_in(client, "enrol@example.com")
    assert signed_in.status_code == 200
    assert "access_token" in signed_in.json()


async def test_enrolling_re_checks_the_password(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "enrol-pw@example.com")
    response = await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": "not-it"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"


async def test_confirming_returns_the_recovery_codes_and_status_reports_them(
    client: AsyncClient, session: AsyncSession
):
    user, _secret, codes = await _enrol(client, session, "status@example.com")
    assert len(codes) == totp_service.RECOVERY_CODE_COUNT

    response = await client.get("/api/v1/auth/totp", headers=get_auth_headers(user))
    assert response.status_code == 200
    body = response.json()
    assert body["enrolled"] is True
    assert body["confirmed_at"]
    assert body["recovery_codes_remaining"] == totp_service.RECOVERY_CODE_COUNT


async def test_signing_in_asks_for_the_code(client: AsyncClient, session: AsyncSession):
    """The password answers with a challenge rather than a session. A wrong
    code leaves the challenge standing; the right one finishes the sign-in
    and spends it."""
    _user, secret, _codes = await _enrol(client, session, "signin@example.com")
    response = await _sign_in(client, "signin@example.com")

    assert response.status_code == 401
    body = response.json()
    assert body["detail"] == "TOTP_REQUIRED"
    assert body["challenge"]
    assert "access_token" not in body
    challenge = body["challenge"]

    refused = await _wrong_code(client, challenge)
    assert refused.status_code == 400
    assert refused.json()["detail"] == "TOTP_INVALID"

    code = _next_code(secret)
    accepted = await client.post(
        "/api/v1/auth/token/totp", json={"challenge": challenge, "code": code}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["access_token"]
    # A browser keeps its refresh token in a cookie, not the body.
    assert accepted.json()["refresh_token"] is None

    again = await client.post(
        "/api/v1/auth/token/totp", json={"challenge": challenge, "code": code}
    )
    assert again.status_code == 400
    assert again.json()["detail"] == "TOTP_CHALLENGE_INVALID"


async def test_a_recovery_code_finishes_it_too(
    client: AsyncClient, session: AsyncSession
):
    _user, _secret, codes = await _enrol(client, session, "recover@example.com")
    challenge = (await _sign_in(client, "recover@example.com")).json()["challenge"]

    response = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": challenge, "recovery_code": codes[0]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


async def _wrong_code(client: AsyncClient, challenge: str) -> Response:
    return await client.post(
        "/api/v1/auth/token/totp", json={"challenge": challenge, "code": "000000"}
    )


async def test_five_wrong_codes_lock_the_password_too(
    client: AsyncClient, session: AsyncSession
):
    _user, _secret, _codes = await _enrol(client, session, "fivecodes@example.com")
    challenge = (await _sign_in(client, "fivecodes@example.com")).json()["challenge"]
    for _ in range(5):
        assert (await _wrong_code(client, challenge)).status_code == 400

    locked = await _sign_in(client, "fivecodes@example.com")
    assert locked.status_code == 429
    assert locked.json() == {"detail": "SIGN_IN_LOCKED"}


async def test_the_right_password_does_not_start_the_count_over(
    client: AsyncClient, session: AsyncSession
):
    """Only a session opening does: the password alone is half a sign-in here."""
    _user, secret, _codes = await _enrol(client, session, "halfway@example.com")
    first = (await _sign_in(client, "halfway@example.com")).json()["challenge"]
    for _ in range(4):
        assert (await _wrong_code(client, first)).status_code == 400

    second = (await _sign_in(client, "halfway@example.com")).json()["challenge"]
    assert (await _wrong_code(client, second)).status_code == 400

    refused = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": second, "code": _next_code(secret)},
    )
    assert refused.status_code == 429
    assert refused.json() == {"detail": "SIGN_IN_LOCKED"}


async def test_a_challenge_nobody_issued_is_refused(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": "not-a-challenge", "code": "000000"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "TOTP_CHALLENGE_INVALID"


async def test_removing_it_asks_for_the_password_and_the_factor(
    client: AsyncClient, session: AsyncSession
):
    user, secret, _codes = await _enrol(client, session, "remove@example.com")
    headers = await signed_in_headers(session, user, amr=["hwk"])

    no_factor = await client.post(
        "/api/v1/auth/totp/disable",
        json={"current_password": PASSWORD, "code": "000000"},
        headers=headers,
    )
    assert no_factor.status_code == 400
    assert no_factor.json()["detail"] == "TOTP_INVALID"

    removed = await client.post(
        "/api/v1/auth/totp/disable",
        json={"current_password": PASSWORD, "code": _next_code(secret)},
        headers=headers,
    )
    assert removed.status_code == 200

    # And the sign-in stops asking.
    response = await _sign_in(client, "remove@example.com")
    assert response.status_code == 200


async def test_regenerating_retires_the_previous_codes(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    from app.core.email_i18n import email_t
    from app.services.platform import email_outbox

    user, _secret, codes = await _enrol(client, session, "regen@example.com")
    headers = get_auth_headers(user)
    letters: list[str] = []

    async def _letter(user, pieces, **_) -> None:
        letters.append(pieces.subject)

    monkeypatch.setattr(email_outbox, "enqueue_account_letter", _letter)

    fresh = await client.post(
        "/api/v1/auth/recovery-codes/regenerate",
        json={"current_password": PASSWORD},
        headers=headers,
    )
    assert fresh.status_code == 200
    assert set(fresh.json()["codes"]).isdisjoint(codes)
    # Its holder is told, with the way to say it wasn't them.
    assert letters == [
        email_t("secondFactor.recoveryRegenerated.subject", "en", escape=False)
    ]

    challenge = (await _sign_in(client, "regen@example.com")).json()["challenge"]
    stale = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": challenge, "recovery_code": codes[0]},
    )
    assert stale.status_code == 400
    assert stale.json()["detail"] == "RECOVERY_CODE_INVALID"


async def test_support_can_clear_a_lost_factor(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The lost-phone path: somebody with the run of platform accounts takes
    the factor off, and the account signs in with its password again."""
    user, _secret, _codes = await _enrol(client, session, "lostphone@example.com")
    staff = await acting_user("support")

    async def roster_says_enrolled() -> bool:
        roster = await client.get(
            "/api/v1/operator/users",
            params={"search": user.username},
            headers=staff.headers,
        )
        assert roster.status_code == 200, roster.text
        (row,) = [r for r in roster.json()["items"] if r["id"] == user.id]
        return row["second_factor_enrolled"]

    # The roster is where staff find it to clear.
    assert await roster_says_enrolled()

    response = await client.delete(
        f"/api/v1/operator/users/{user.id}/second-factor", headers=staff.headers
    )
    assert response.status_code == 204, response.text
    assert not await roster_says_enrolled()

    signed_in = await _sign_in(client, "lostphone@example.com")
    assert signed_in.status_code == 200
    assert signed_in.json()["access_token"]


async def test_clearing_a_factor_is_not_for_everybody(
    client: AsyncClient, session: AsyncSession, acting_user
):
    user, _secret, _codes = await _enrol(client, session, "notyours@example.com")
    bystander = await acting_user("moderator")

    response = await client.delete(
        f"/api/v1/operator/users/{user.id}/second-factor", headers=bystander.headers
    )
    assert response.status_code == 403

    # And the factor is still being asked for.
    assert (await _sign_in(client, "notyours@example.com")).status_code == 401


async def test_removing_it_leaves_this_session_signed_in(
    client: AsyncClient, session: AsyncSession
):
    """The change is made from a settings page, which should still be signed in
    when it finishes — every other session goes."""
    from app.models.platform.auth_session import AuthSession
    from app.services.auth import sessions as session_service
    from app.testing import get_auth_token

    user, secret, _codes = await _enrol(client, session, "keepme@example.com")
    mine = await session_service.create_session(
        session, user_id=user.id, amr=["hwk"], satisfied_providers=[]
    )
    elsewhere = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    mine_id, elsewhere_id = mine.session.id, elsewhere.session.id

    token = get_auth_token(user, session_id=mine_id, amr=["hwk"])
    removed = await client.post(
        "/api/v1/auth/totp/disable",
        json={"current_password": PASSWORD, "code": _next_code(secret)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert removed.status_code == 200, removed.text

    session.expire_all()
    assert (await session.get(AuthSession, mine_id)).revoked_at is None
    assert (await session.get(AuthSession, elsewhere_id)).revoked_at is not None


async def test_an_inactive_account_does_not_spend_its_code(
    client: AsyncClient, session: AsyncSession
):
    """Deactivated between the password and the code: the answer is refused,
    and the recovery code it offered is still good."""
    user, _secret, codes = await _enrol(client, session, "gone@example.com")
    challenge = (await _sign_in(client, "gone@example.com")).json()["challenge"]

    user.status = UserStatus.deactivated
    session.add(user)
    await session.commit()

    refused = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": challenge, "recovery_code": codes[0]},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "INACTIVE_USER"
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user.id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_an_account_with_both_still_supplies_its_password(
    client: AsyncClient, session: AsyncSession
):
    """Holding a federated identity is not the same as holding no password.
    An account with both is asked for the one it has."""
    from app.models.platform.federated_identity import FederatedIdentity
    from app.services.auth import identity as identity_service
    from app.testing import create_auth_provider

    user = await _account(session, "both@example.com")
    provider = await create_auth_provider(session, slug="corp-both")
    session.add(
        FederatedIdentity(
            user_id=user.id,
            provider_id=provider.id,
            subject="subject-both",
            email_verified=True,
        )
    )
    await session.commit()
    # The account really does hold both — which is the case the exemption used
    # to wave through.
    assert await identity_service.has_federated_identity(session, user_id=user.id)
    assert user.hashed_password is not None

    response = await client.post(
        "/api/v1/auth/totp/enroll",
        json={},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_REQUIRED"


@pytest.mark.parametrize("hashed_password", [None, "!"], ids=["none", "marker"])
async def test_an_account_with_no_password_is_not_asked_for_one(
    client: AsyncClient, session: AsyncSession, hashed_password: str | None
):
    """Provisioned through an identity provider: there is no hash to re-check,
    so a sign-in just made answers instead. A 0152 downgrade fills NULL hashes
    with ``'!'``, which nothing can verify, so it is no password either."""
    user = await create_user(
        session,
        email="sso-only@example.com",
        hashed_password=hashed_password,
        status=UserStatus.active,
        email_verified=True,
    )
    response = await client.post(
        "/api/v1/auth/totp/enroll",
        json={},
        headers=await _session_headers(session, user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["secret"]


async def test_the_app_is_asked_for_the_code_and_keeps_its_refresh_token(
    client: AsyncClient, session: AsyncSession
):
    """A proved factor is part of signing in from the app too. A browser reads
    its refresh token from a cookie it never sees; the app, which presents its
    own origin, is handed one."""
    _user, secret, _codes = await _enrol(client, session, "native@example.com")
    app = {"Origin": "https://studio.beyonders.initiative"}

    response = await client.post(
        "/api/v1/auth/token",
        data={
            "username": "native@example.com",
            "password": PASSWORD,
            "device_name": "Phone",
        },
        headers=app,
    )
    assert response.status_code == 401, response.text
    body = response.json()
    assert body["detail"] == "TOTP_REQUIRED"
    assert body["challenge"]
    assert "refresh_token" not in body

    answered = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": body["challenge"], "code": _next_code(secret)},
        headers=app,
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["access_token"]
    assert answered.json()["refresh_token"]


async def test_status_says_whether_a_password_will_be_asked_for(
    client: AsyncClient, session: AsyncSession
):
    """The form cannot work this out for itself: holding a federated identity
    is a different question from holding a password, and an account can have
    both. The marker a 0152 downgrade writes is not a password."""
    with_password = await _account(session, "haspw@example.com")
    without = await create_user(
        session,
        email="nopw@example.com",
        hashed_password=None,
        status=UserStatus.active,
        email_verified=True,
    )
    marker = await create_user(
        session,
        email="marker-status@example.com",
        hashed_password="!",
        status=UserStatus.active,
        email_verified=True,
    )

    for user, expected in ((with_password, True), (without, False), (marker, False)):
        response = await client.get("/api/v1/auth/totp", headers=get_auth_headers(user))
        assert response.status_code == 200, response.text
        assert response.json()["password_required"] is expected


async def _withdraw_totp(session: AsyncSession) -> None:
    """Leave the deployment permitting the two that can begin a session."""
    from app.services.platform import rules

    await rules.put(
        session, "login_methods", frozenset({LoginMethod.password, LoginMethod.sso})
    )
    await session.commit()


async def test_withdrawing_it_stops_the_factor_being_asked_for(
    client: AsyncClient, session: AsyncSession
):
    """The status says whether it is offered. Withdrawn, enrolment is refused;
    an enrolment already made is left alone — re-offering it asks for the
    code again — but while the deployment does not offer it, the sign-in does
    not ask."""
    user, _secret, _codes = await _enrol(client, session, "stillenrolled@example.com")
    headers = get_auth_headers(user)
    assert (await client.get("/api/v1/auth/totp", headers=headers)).json()[
        "offered"
    ] is True

    await _withdraw_totp(session)
    assert (await client.get("/api/v1/auth/totp", headers=headers)).json()[
        "offered"
    ] is False
    response = await client.post(
        "/api/v1/auth/totp/enroll",
        json={"current_password": PASSWORD},
        headers=headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "TOTP_NOT_PERMITTED"

    signed_in = await _sign_in(client, "stillenrolled@example.com")
    assert signed_in.status_code == 200
    assert signed_in.json()["access_token"]


async def _session_headers(session: AsyncSession, user):
    """A token naming a real session row, which is what the step-up upgrades."""
    from app.services.auth import sessions as session_service

    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    return {
        "Authorization": "Bearer "
        + get_auth_token(user, session_id=issued.session.id, amr=["pwd"])
    }


async def test_stepping_up_keeps_what_the_session_already_proved(
    client: AsyncClient, session: AsyncSession
):
    """A community asking for a factor refuses a session that never presented
    one, so the code goes against the live session rather than a sign-out and
    back in — and satisfying one community's requirement never un-satisfies
    another's."""
    from app.core.security import decode_session_token
    from app.services.auth import sessions as session_service

    user, secret, _codes = await _enrol(client, session, "keepsat@example.com")
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd", "oidc:corp"], satisfied_providers=[9]
    )
    await session.commit()

    # No refresh cookie: the app sends only its access token, and the session it
    # names is what has to be carried forward.
    response = await client.post(
        "/api/v1/auth/step-up/totp",
        json={"code": _next_code(secret)},
        headers={
            "Authorization": "Bearer "
            + get_auth_token(
                user,
                session_id=issued.session.id,
                amr=["pwd", "oidc:corp"],
                satisfied_providers=[9],
            )
        },
    )
    assert response.status_code == 200, response.text
    claims = decode_session_token(response.json()["access_token"])
    assert set(claims["amr"]) >= {"pwd", "oidc:corp", "otp", "mfa"}
    assert claims["sat"] == [9]


async def test_a_recovery_code_can_step_up_a_session(
    client: AsyncClient, session: AsyncSession
):
    """The step-up offers the same two answers the sign-in does — somebody
    whose phone is not to hand reaches the community with a recovery code."""
    from app.core.security import decode_session_token

    user, _secret, codes = await _enrol(client, session, "recoverystep@example.com")

    response = await client.post(
        "/api/v1/auth/step-up/totp",
        json={"recovery_code": codes[0]},
        headers=await _session_headers(session, user),
    )
    assert response.status_code == 200, response.text
    claims = decode_session_token(response.json()["access_token"])
    assert "mfa" in claims["amr"]
    # A recovery code is not the authenticator, and the session says so.
    assert "otp" not in claims["amr"]


async def test_a_wrong_code_does_not_upgrade_the_session(
    client: AsyncClient, session: AsyncSession
):
    """Wrong codes count against the account as they do at sign-in: a right
    code starts the count over, and enough wrong ones turn the right one away
    too."""
    from app.models.platform.sign_in_lock import SignInLock

    user, secret, _codes = await _enrol(client, session, "badstepup@example.com")
    user_id = user.id
    headers = await _session_headers(session, user)

    async def wrong(times: int) -> None:
        for _ in range(times):
            response = await client.post(
                "/api/v1/auth/step-up/totp", json={"code": "000000"}, headers=headers
            )
            assert response.status_code == 400
            assert response.json()["detail"] == "TOTP_INVALID"

    await wrong(4)
    stepped = await client.post(
        "/api/v1/auth/step-up/totp",
        json={"code": _next_code(secret)},
        headers=headers,
    )
    assert stepped.status_code == 200, stepped.text
    session.expire_all()
    row = await session.get(SignInLock, user_id)
    assert row is None or row.failures == 0

    headers = {
        "Authorization": f"Bearer {stepped.json()['access_token']}",
    }
    await wrong(5)
    locked = await client.post(
        "/api/v1/auth/step-up/totp",
        json={"code": _next_code(secret)},
        headers=headers,
    )
    assert locked.status_code == 429
    assert locked.json() == {"detail": "SIGN_IN_LOCKED"}


async def test_an_account_with_no_factor_cannot_step_up(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "nofactor@example.com")
    response = await client.post(
        "/api/v1/auth/step-up/totp",
        json={"code": "123456"},
        headers=await _session_headers(session, user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "TOTP_NOT_ENROLLED"


async def test_a_standing_credential_cannot_step_up(
    client: AsyncClient, session: AsyncSession
):
    """The step-up hands back an interactive session, so it is made by the
    person in one of their own — not by an API key acting for them."""
    user, secret, _codes = await _enrol(client, session, "apikey@example.com")

    response = await client.post(
        "/api/v1/auth/step-up/totp",
        json={"code": _next_code(secret)},
        headers=get_auth_headers(user),
    )
    assert response.status_code in (400, 403)
    assert response.json()["detail"] in (
        "SESSION_REQUIRED",
        "TOTP_INVALID",
    )


async def test_stepping_up_leaves_no_other_session_live(
    client: AsyncClient, session: AsyncSession
):
    """The chain goes, not just the one row — rotation can have left
    descendants, and the session the step-up issues is what replaces all of
    them.

    Stated as the property rather than as an interleaving, which a test cannot
    reach deterministically: after stepping up, the session it issued is the
    only live one for that account.
    """
    from sqlmodel import select

    from app.models.platform.auth_session import AuthSession
    from app.services.auth import sessions as session_service

    user, secret, _codes = await _enrol(client, session, "chain@example.com")
    first = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    rotated = await session_service.rotate_session(
        session, raw_refresh_token=first.refresh_token
    )
    await session.commit()
    child_id = rotated.issued.session.id
    first_id = first.session.id
    user_id = user.id

    response = await client.post(
        "/api/v1/auth/step-up/totp",
        json={"code": _next_code(secret)},
        headers={
            "Authorization": "Bearer "
            + get_auth_token(user, session_id=child_id, amr=["pwd"])
        },
    )
    assert response.status_code == 200, response.text

    session.expire_all()
    live = (
        await session.exec(
            select(AuthSession).where(
                AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
            )
        )
    ).all()
    assert len(live) == 1, f"expected one live session, found {len(live)}"
    assert live[0].id not in {first_id, child_id}


# ---------------------------------------------------------------------------
# An account that signs in without a password
# ---------------------------------------------------------------------------


async def _passwordless(session: AsyncSession, email: str) -> User:
    return await create_user(
        session,
        email=email,
        hashed_password=None,
        status=UserStatus.active,
        email_verified=True,
    )


async def test_the_status_reports_a_passwordless_account(
    client: AsyncClient, session: AsyncSession
):
    """The recovery set answers for the account there rather than for a factor,
    so it is reported whether or not the authenticator is enrolled."""
    user = await _passwordless(session, "sf-passwordless@example.com")
    await totp_service.issue_recovery_codes(session, user_id=user.id)
    await session.commit()

    response = await client.get("/api/v1/auth/totp", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passwordless"] is True
    assert body["enrolled"] is False
    assert body["recovery_codes_remaining"] == totp_service.RECOVERY_CODE_COUNT


async def test_a_passwordless_account_may_re_issue_its_codes(
    client: AsyncClient, session: AsyncSession
):
    user = await _passwordless(session, "sf-regenerate@example.com")
    first = await totp_service.issue_recovery_codes(session, user_id=user.id)
    await session.commit()

    # No password to re-check, so what it answers with is the sign-in.
    response = await client.post(
        "/api/v1/auth/recovery-codes/regenerate",
        json={},
        headers=await _session_headers(session, user),
    )
    assert response.status_code == 200, response.text
    codes = response.json()["codes"]
    assert len(codes) == totp_service.RECOVERY_CODE_COUNT
    assert set(codes).isdisjoint(first)


async def test_an_account_with_a_password_and_no_factor_has_nothing_to_re_issue(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "sf-regenerate-none@example.com")

    response = await client.post(
        "/api/v1/auth/recovery-codes/regenerate",
        json={"current_password": PASSWORD},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "TOTP_NOT_ENROLLED"


async def test_turning_it_off_from_a_new_sign_in_waits(
    client: AsyncClient, session: AsyncSession
):
    """Held, the factor stays. Made once due, it goes, and every other session
    goes with it but the one that asked. A factor confirmed after the request
    is not the one it asked about, and stays."""
    from app.models.platform.auth_session import AuthSession
    from app.services.auth import held_changes
    from app.services.auth import sessions as session_service
    from app.services.auth import totp as totp_service

    user, secret, codes = await _enrol(client, session, "held-off@example.com")
    user_id = user.id
    mine = await session_service.create_session(
        session, user_id=user_id, amr=["pwd"], satisfied_providers=[]
    )
    elsewhere = await session_service.create_session(
        session, user_id=user_id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    mine_id, elsewhere_id = mine.session.id, elsewhere.session.id
    headers = {"Authorization": f"Bearer {get_auth_token(user, session_id=mine_id)}"}

    held = await client.post(
        "/api/v1/auth/totp/disable",
        json={"current_password": PASSWORD, "code": _next_code(secret)},
        headers=headers,
    )
    assert held.status_code == 202, held.text
    assert held.json()["held"]["kind"] == "second_factor_off"
    assert await totp_service.is_enrolled(session, user_id=user_id)

    factor = await totp_service.get_factor(session, user_id=user_id)
    assert factor is not None
    factor.confirmed_at = datetime.now(UTC)
    session.add(factor)
    await session.commit()
    due = datetime.now(UTC) + held_changes.HOLD_FOR
    assert await held_changes.apply_due(session, now=due) == 0
    assert await totp_service.is_enrolled(session, user_id=user_id)

    held = await client.post(
        "/api/v1/auth/totp/disable",
        json={"current_password": PASSWORD, "recovery_code": codes[0]},
        headers=headers,
    )
    assert held.status_code == 202, held.text
    due = datetime.now(UTC) + held_changes.HOLD_FOR
    assert await held_changes.apply_due(session, now=due) == 1
    session.expire_all()
    assert not await totp_service.is_enrolled(session, user_id=user_id)
    assert (await session.get(AuthSession, mine_id)).revoked_at is None
    assert (await session.get(AuthSession, elsewhere_id)).revoked_at is not None
