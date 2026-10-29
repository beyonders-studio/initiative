"""Giving the password up, and getting one back with a recovery code.

What these cover is the surface either side of the change: what an account has
to hold before it may let its password go, what happens to the sessions and the
device it was done from, and the one answer every refused recovery gets.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient, Response
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.login_methods import LoginMethod
from app.core.audit_events import AuditEventType
from app.core.messages import PasswordMessages
from app.core.security import (
    REFRESH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    get_password_hash,
)
from app.models.platform.auth_session import AuthSession
from app.models.platform.guild import CommunityRole
from app.models.platform.mfa_recovery_code import MfaRecoveryCode
from app.models.platform.sign_in_lock import SignInLock
from app.models.platform.user import User, UserStatus
from app.models.platform.user_email import UserEmail
from app.models.platform.user_passkey import UserPasskey
from app.services.platform import email_outbox
from app.services.auth import addresses
from app.services.auth import sessions as session_service
from app.services.auth import sign_in_locks
from app.services.auth import totp as totp_service
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.services.platform import user_tokens
from app.testing import (
    create_guild,
    create_guild_membership,
    create_user,
    emitted,
    get_auth_headers,
    get_auth_token,
)


PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "a-different-horse-entirely"

REMOVE = "/api/v1/auth/password/remove"
RECOVER = "/api/v1/auth/password/recover"


async def _account(
    session: AsyncSession,
    email: str,
    *,
    password: str | None = PASSWORD,
    status: UserStatus = UserStatus.active,
) -> User:
    return await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(password) if password else None,
        status=status,
        email_verified=True,
    )


async def _seed_passkey(
    session: AsyncSession, user: User, *, credential_id: str = "way-in"
) -> UserPasskey:
    """A registered credential, written straight in.

    The ceremony belongs to the library and is covered where it is run; what
    matters here is only that the account holds one.
    """
    row = UserPasskey(
        user_id=user.id,
        credential_id=f"{credential_id}-{user.id}".encode(),
        public_key=b"public-key-bytes",
        rp_id="localhost",
        sign_count=0,
        transports=["internal"],
        name="Laptop",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def _withdraw_passkeys(session: AsyncSession) -> None:
    """Leave the deployment permitting the other three."""
    await rules.put(
        session,
        "login_methods",
        frozenset({LoginMethod.password, LoginMethod.sso, LoginMethod.totp}),
    )
    await session.commit()


async def _issue_codes(session: AsyncSession, user: User) -> list[str]:
    codes = await totp_service.issue_recovery_codes(session, user_id=user.id)
    await session.commit()
    return codes


async def _another_session(session: AsyncSession, user: User) -> AuthSession:
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
    )
    await session.commit()
    return issued.session


async def _proof_headers(
    session: AsyncSession, user: User, *, minutes_ago: float = 0.0
) -> dict[str, str]:
    """Headers naming a real session row, opened ``minutes_ago`` minutes back."""
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["webauthn"], satisfied_providers=[]
    )
    row = issued.session
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    session.add(row)
    await session.commit()
    return {
        "Authorization": "Bearer "
        + get_auth_token(user, session_id=row.id, amr=["webauthn"])
    }


async def _rotated_headers(
    session: AsyncSession, user: User, *, minutes_ago: float
) -> dict[str, str]:
    """Headers naming the row a refresh minted, on a chain that began
    ``minutes_ago`` minutes back."""
    issued = await session_service.create_session(
        session, user_id=user.id, amr=["webauthn"], satisfied_providers=[]
    )
    issued.session.created_at = datetime.now(timezone.utc) - timedelta(
        minutes=minutes_ago
    )
    session.add(issued.session)
    await session.commit()
    rotated = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token
    )
    await session.commit()
    return {
        "Authorization": "Bearer "
        + get_auth_token(user, session_id=rotated.issued.session.id, amr=["webauthn"])
    }


async def _sign_in(
    client: AsyncClient, email: str, password: str = PASSWORD
) -> Response:
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


def _events(
    written: list[dict], user_id: int, event_type: AuditEventType
) -> list[dict]:
    """Every record of one kind naming this account, as actor or as target.

    A refused recovery is unauthenticated, so the account it named is the
    target rather than the actor; a change the account made itself is the
    other way round.
    """
    return [
        envelope
        for envelope in written
        if envelope["event_type"] == event_type.value
        and user_id in (envelope["actor_user_id"], envelope["target_user_id"])
    ]


# ---------------------------------------------------------------------------
# Giving the password up
# ---------------------------------------------------------------------------


async def test_the_only_way_in_stays(client: AsyncClient, session: AsyncSession):
    """An account with nothing else to sign in with keeps its password."""
    user = await _account(session, "pl-only@example.com")

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PASSWORD_IS_LAST_METHOD"


async def test_removing_re_checks_the_password(
    client: AsyncClient, session: AsyncSession
):
    """Wrong answers count against the account, as they do at sign-in: once it
    is locked, the right password is refused too."""
    user = await _account(session, "pl-wrongpw@example.com")
    await _seed_passkey(session, user)

    for _ in range(sign_in_locks.LOCK_AFTER_FAILURES):
        response = await client.post(
            REMOVE, json={"current_password": "not-it"}, headers=get_auth_headers(user)
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 429
    assert response.json()["detail"] == "SIGN_IN_LOCKED"


async def test_the_right_password_starts_the_count_over(
    client: AsyncClient, session: AsyncSession
):
    """As a sign-in does: wrong answers either side of a right one do not add
    up to a lock."""
    user = await _account(session, "pl-recount@example.com")

    async def begin(password: str) -> Response:
        return await client.post(
            "/api/v1/auth/passkeys/register/begin",
            headers=get_auth_headers(user),
            json={"current_password": password, "name": "Laptop"},
        )

    for _ in range(2):
        for _ in range(sign_in_locks.LOCK_AFTER_FAILURES - 1):
            response = await begin("not-it")
            assert response.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"
        response = await begin(PASSWORD)
        assert response.status_code == 200, response.text


async def test_the_allowance_is_the_account_s_not_the_address_s(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Two accounts behind one address: one running out leaves the other its
    own allowance."""
    from app.core.rate_limit import limiter

    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(limiter, "_default_limits", [])
    limiter.reset()
    spent = await _account(session, "pl-spent@example.com")
    neighbour = await _account(session, "pl-neighbour@example.com")

    try:
        for _ in range(5):
            response = await client.post(
                REMOVE,
                json={"current_password": PASSWORD},
                headers=get_auth_headers(spent),
            )
            assert response.status_code == 409
        response = await client.post(
            REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(spent)
        )
        assert response.status_code == 429

        response = await client.post(
            REMOVE,
            json={"current_password": PASSWORD},
            headers=get_auth_headers(neighbour),
        )
        assert response.status_code == 409
    finally:
        limiter.reset()


async def test_an_account_holding_none_has_nothing_to_remove(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-nopw@example.com", password=None)
    await _seed_passkey(session, user)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSWORD_NOT_HELD"


async def test_a_credential_the_deployment_withdrew_is_not_a_way_in(
    client: AsyncClient, session: AsyncSession
):
    """The account holds a passkey, but this deployment stopped accepting
    them — so the password is again all it has."""
    user = await _account(session, "pl-withdrawn@example.com")
    await _seed_passkey(session, user)
    await _withdraw_passkeys(session)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PASSWORD_IS_LAST_METHOD"


async def test_removing_keeps_this_device_signed_in(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await _account(session, "pl-remove@example.com")
    user_id = user.id
    version_before = user.token_version
    await _seed_passkey(session, user)
    elsewhere_id = (await _another_session(session, user)).id

    # A real sign-in, so the session this is done from is one the server wrote.
    assert (await _sign_in(client, "pl-remove@example.com")).status_code == 200
    capfd.readouterr()

    response = await client.post(REMOVE, json={"current_password": PASSWORD})
    assert response.status_code == 200, response.text
    assert len(response.json()["codes"]) == totp_service.RECOVERY_CODE_COUNT
    assert SESSION_COOKIE_NAME in response.cookies
    assert REFRESH_COOKIE_NAME in response.cookies

    # The caller carries on, on the cookies the answer set.
    mine = await client.get("/api/v1/me")
    assert mine.status_code == 200, mine.text
    assert mine.json()["id"] == user_id

    session.expire_all()
    account = await session.get(User, user_id)
    assert account is not None
    assert account.hashed_password is None
    assert account.password_set_at is None
    assert account.token_version == version_before + 1

    rows = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).all()
    live = [row for row in rows if row.revoked_at is None]
    assert len(live) == 1
    # What this device had already proved carries into the one that replaces it.
    assert live[0].amr == ["pwd"]
    assert live[0].id != elsewhere_id

    written = emitted(capfd)
    assert len(_events(written, user_id, AuditEventType.AUTH_PASSWORD_REMOVED)) == 1
    assert (
        len(_events(written, user_id, AuditEventType.AUTH_RECOVERY_CODES_ISSUED)) == 1
    )


async def test_an_account_that_already_holds_codes_keeps_them(
    client: AsyncClient, session: AsyncSession
):
    """The set is issued at the moment the account becomes passwordless only if
    it has none. One that is enrolled already has a set, and it is still good."""
    user = await _account(session, "pl-hascodes@example.com")
    user_id = user.id
    await _seed_passkey(session, user)
    await _issue_codes(session, user)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 200, response.text
    assert response.json()["codes"] == []

    session.expire_all()
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_the_letter_says_the_password_is_gone(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    sent: list[int] = []

    async def record(user, pieces, **_) -> None:
        sent.append(user.id)

    monkeypatch.setattr(email_outbox, "enqueue_account_letter", record)

    user = await _account(session, "pl-letter@example.com")
    await _seed_passkey(session, user)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 200, response.text
    assert sent == [user.id]


async def test_the_app_is_sent_to_a_browser_for_this(
    client: AsyncClient, session: AsyncSession
):
    """The answer hands back a replacement session in cookies, which the native
    app does not carry, so the route asks for a browser."""
    user = await _account(session, "pl-device@example.com")
    user_id = user.id
    await _seed_passkey(session, user)

    response = await client.post(
        REMOVE,
        json={"current_password": PASSWORD},
        headers={
            **get_auth_headers(user),
            "Origin": "https://studio.beyonders.initiative",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"

    session.expire_all()
    account = await session.get(User, user_id)
    assert account is not None
    assert account.hashed_password is not None


async def test_a_thin_set_is_replaced_on_the_way_out(
    client: AsyncClient, session: AsyncSession
):
    """A code is how a passwordless account gets a password back, so an account
    down to its last few leaves with a full set rather than those few."""
    user = await _account(session, "pl-thin@example.com")
    user_id = user.id
    await _seed_passkey(session, user)
    await _issue_codes(session, user)
    held = (
        await session.exec(
            select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id)
        )
    ).all()
    for row in held[totp_service.LOW_ON_RECOVERY_CODES - 1 :]:
        await session.delete(row)
    await session.commit()

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["codes"]) == totp_service.RECOVERY_CODE_COUNT

    session.expire_all()
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_a_session_that_cannot_be_opened_leaves_the_password(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The password goes in the same transaction as the session that replaces
    this device's, so neither lands without the other."""

    async def fail(*args, **kwargs):
        raise RuntimeError("no session store")

    monkeypatch.setattr(session_service, "create_session", fail)

    user = await _account(session, "pl-nosession@example.com")
    user_id = user.id
    hash_before = user.hashed_password
    await _seed_passkey(session, user)

    response = await client.post(
        REMOVE, json={"current_password": PASSWORD}, headers=get_auth_headers(user)
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "SESSION_STORE_UNAVAILABLE"

    session.expire_all()
    account = await session.get(User, user_id)
    assert account is not None
    assert account.hashed_password == hash_before


# ---------------------------------------------------------------------------
# Getting one back with a recovery code
# ---------------------------------------------------------------------------


async def test_an_account_holding_a_password_recovers_by_mail_instead(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-haspw@example.com")
    user_id = user.id
    codes = await _issue_codes(session, user)
    body = {
        "email": "pl-haspw@example.com",
        "recovery_code": codes[0],
        "password": NEW_PASSWORD,
    }

    response = await client.post(RECOVER, json=body)
    assert response.status_code == 400
    assert response.json()["detail"] == "RECOVERY_CODE_INVALID"

    # A locked account answers with the lock first.
    for _ in range(sign_in_locks.LOCK_AFTER_FAILURES):
        await sign_in_locks.record_failure(session, user_id)
    await session.commit()
    response = await client.post(RECOVER, json=body)
    assert response.status_code == 429
    assert response.json()["detail"] == "SIGN_IN_LOCKED"


async def test_an_address_nobody_holds_gets_the_same_answer(client: AsyncClient):
    response = await client.post(
        RECOVER,
        json={
            "email": "nobody@example.com",
            "recovery_code": "aaaaa-bbbbb-ccccc-ddddd",
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "RECOVERY_CODE_INVALID"


async def test_a_code_that_does_not_match_is_written_down(
    client: AsyncClient, session: AsyncSession, capfd
):
    user = await _account(session, "pl-badcode@example.com", password=None)
    user_id = user.id
    await _issue_codes(session, user)
    capfd.readouterr()

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-badcode@example.com",
            "recovery_code": "aaaaa-bbbbb-ccccc-ddddd",
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "RECOVERY_CODE_INVALID"

    refusals = _events(
        emitted(capfd), user_id, AuditEventType.AUTH_SECOND_FACTOR_FAILED
    )
    assert len(refusals) == 1
    assert refusals[0]["target_user_id"] == user_id
    assert refusals[0]["detail"] == {
        "method": "recovery_code",
        "during": "recover",
    }


async def test_an_account_that_is_not_active_cannot_recover(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(
        session,
        "pl-inactive@example.com",
        password=None,
        status=UserStatus.deactivated,
    )
    user_id = user.id
    codes = await _issue_codes(session, user)

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-inactive@example.com",
            "recovery_code": codes[0],
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "RECOVERY_CODE_INVALID"

    session.expire_all()
    # The code was not spent: nothing about the account changed.
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_the_policy_runs_before_the_code_is_spent(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pl-policy@example.com", password=None)
    user_id = user.id
    codes = await _issue_codes(session, user)

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-policy@example.com",
            "recovery_code": codes[0],
            "password": "short",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == PasswordMessages.TOO_SHORT

    session.expire_all()
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_a_recovery_that_does_not_land_leaves_the_account_as_it_was(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The password, the spent code and the retired sessions share one commit
    on the system engine. A write that does not land leaves all three."""

    async def fail(*args, **kwargs):
        raise RuntimeError("no system engine")

    monkeypatch.setattr(user_tokens, "revoke_user_sessions", fail)

    user = await _account(session, "pl-norecover@example.com", password=None)
    user_id = user.id
    stamp_before = user.updated_at
    codes = await _issue_codes(session, user)

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-norecover@example.com",
            "recovery_code": codes[0],
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "SESSION_STORE_UNAVAILABLE"

    session.expire_all()
    account = await session.get(User, user_id)
    assert account is not None
    assert account.hashed_password is None
    assert account.password_set_at is None
    # The stamp is staged with the password rather than written after it, so
    # it rolls back with everything else.
    assert account.updated_at == stamp_before
    # The code it presented is still good, so the same one works on the retry.
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT
    )


async def test_recovering_sets_the_password_and_clears_the_sessions(
    client: AsyncClient, session: AsyncSession, capfd
):
    """The code stands in for the password, as the mailed link does, so the
    wrong answers counted before it start over along with everything else."""
    user = await _account(session, "pl-recover@example.com", password=None)
    user_id = user.id
    codes = await _issue_codes(session, user)
    elsewhere_id = (await _another_session(session, user)).id
    await sign_in_locks.record_failure(session, user_id)
    await session.commit()
    capfd.readouterr()

    response = await client.post(
        RECOVER,
        json={
            "email": "pl-recover@example.com",
            "recovery_code": codes[0],
            "password": NEW_PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "reset"

    session.expire_all()
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user_id)
        == totp_service.RECOVERY_CODE_COUNT - 1
    )
    retired = await session.get(AuthSession, elsewhere_id)
    assert retired is not None
    assert retired.revoked_at is not None
    assert await session.get(SignInLock, user_id) is None

    written = emitted(capfd)
    used = _events(written, user_id, AuditEventType.AUTH_RECOVERY_CODE_USED)
    assert len(used) == 1
    assert used[0]["detail"]["remaining"] == (totp_service.RECOVERY_CODE_COUNT - 1)
    changed = _events(written, user_id, AuditEventType.AUTH_PASSWORD_CHANGED)
    assert len(changed) == 1
    assert changed[0]["detail"] == {"via": "recovery_code"}

    # No session was opened here; the password is what signs the account in.
    signed_in = await _sign_in(client, "pl-recover@example.com", NEW_PASSWORD)
    assert signed_in.status_code == 200, signed_in.text


# ---------------------------------------------------------------------------
# What stands in for the password an account does not hold
# ---------------------------------------------------------------------------
#
# The routes that re-check the password before changing how an account is
# signed into. An account holding one answers with it; one holding none answers
# with the sign-in itself, which has to be recent.


async def _delete_account(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    await _seed_passkey(session, user)
    return await client.post(
        "/api/v1/me/delete-account",
        headers=headers,
        json={
            "action": "soft_delete",
            "password": "",
            "confirmation_text": "DELETE MY ACCOUNT",
        },
    )


async def _delete_guild(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    await _seed_passkey(session, user)
    guild = await create_guild(session, name="Winding Down")
    # Deleting a community belongs to the seat, so this is what reaches the
    # recent-proof gate at all.
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.superadmin
    )
    return await client.request(
        "DELETE",
        f"/api/v1/communities/{guild.id}",
        headers=headers,
        json={"confirmation_text": "DELETE COMMUNITY WINDING DOWN"},
    )


async def _begin_registration(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    await _seed_passkey(session, user)
    return await client.post(
        "/api/v1/auth/passkeys/register/begin",
        headers=headers,
        json={"name": "Laptop"},
    )


async def _remove_passkey(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    row = await _seed_passkey(session, user, credential_id="one-of-two")
    await _seed_passkey(session, user, credential_id="two-of-two")
    return await client.post(
        f"/api/v1/auth/passkeys/{row.id}/remove", headers=headers, json={}
    )


async def _regenerate_codes(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    await _seed_passkey(session, user)
    return await client.post(
        "/api/v1/auth/recovery-codes/regenerate", headers=headers, json={}
    )


async def _enrol_a_factor(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    return await client.post("/api/v1/auth/totp/enroll", headers=headers, json={})


async def _set_a_password(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    await _seed_passkey(session, user)
    return await client.patch(
        "/api/v1/me", headers=headers, json={"password": NEW_PASSWORD}
    )


async def _turn_off_the_factor(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    from app.models.platform.user_totp import UserTotp

    session.add(UserTotp(user_id=user.id, confirmed_at=datetime.now(timezone.utc)))
    await session.commit()
    codes = await _issue_codes(session, user)
    return await client.post(
        "/api/v1/auth/totp/disable", headers=headers, json={"recovery_code": codes[0]}
    )


async def _spare_address(session: AsyncSession, user: User) -> UserEmail:
    row = addresses.record_address(
        session,
        user_id=user.id,
        email=f"spare-{user.id}@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()
    return row


async def _add_an_address(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    settings_row = await app_settings_service.get_app_settings(session)
    settings_row.smtp_host = "smtp.example.com"
    settings_row.smtp_from_address = "noreply@example.com"
    session.add(settings_row)
    await session.commit()
    return await client.post(
        "/api/v1/me/emails",
        headers=headers,
        json={"email": f"added-{user.id}@example.com"},
    )


async def _make_an_address_primary(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    spare = await _spare_address(session, user)
    return await client.put(
        f"/api/v1/me/emails/{spare.id}/primary", headers=headers, json={}
    )


async def _remove_an_address(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    spare = await _spare_address(session, user)
    return await client.post(
        f"/api/v1/me/emails/{spare.id}/remove", headers=headers, json={}
    )


# A sign-in just made is let through, and the changes that wait for a new
# sign-in are held (202) rather than made.
_GATED = [
    ("add-an-address", _add_an_address, 202),
    ("make-an-address-primary", _make_an_address_primary, 202),
    ("remove-an-address", _remove_an_address, 202),
    ("delete-account", _delete_account, 200),
    ("enrol-a-factor", _enrol_a_factor, 200),
    ("delete-guild", _delete_guild, 204),
    ("register-a-passkey", _begin_registration, 200),
    ("remove-a-passkey", _remove_passkey, 200),
    ("re-issue-the-codes", _regenerate_codes, 200),
    ("set-a-password", _set_a_password, 200),
    ("turn-off-the-factor", _turn_off_the_factor, 202),
]


@pytest.mark.parametrize("slug,route,_ok", _GATED, ids=[row[0] for row in _GATED])
async def test_a_sign_in_of_a_while_ago_no_longer_speaks_for_the_account(
    client: AsyncClient, session: AsyncSession, slug: str, route, _ok: int
):
    user = await _account(session, f"pl-stale-{slug}@example.com", password=None)
    headers = await _proof_headers(session, user, minutes_ago=11)

    response = await route(client, session, user, headers)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "RECENT_PROOF_REQUIRED"


@pytest.mark.parametrize("slug,route,ok", _GATED, ids=[row[0] for row in _GATED])
async def test_a_sign_in_just_made_speaks_for_the_account(
    client: AsyncClient, session: AsyncSession, slug: str, route, ok: int
):
    user = await _account(session, f"pl-fresh-{slug}@example.com", password=None)
    headers = await _proof_headers(session, user)

    response = await route(client, session, user, headers)
    assert response.status_code == ok, response.text


async def test_a_renewed_session_is_read_back_to_the_sign_in_it_began_at(
    client: AsyncClient, session: AsyncSession
):
    """A refresh mints a new row, and its age is not the account's proof — the
    chain is read back to the sign-in at its root."""
    user = await _account(session, "pl-rotated@example.com", password=None)
    headers = await _rotated_headers(session, user, minutes_ago=11)

    response = await _regenerate_codes(client, session, user, headers)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "RECENT_PROOF_REQUIRED"


async def _withdraw_passwords(session: AsyncSession) -> None:
    """Leave the deployment signing nobody in with a password."""
    await rules.put(
        session,
        "login_methods",
        frozenset({LoginMethod.sso, LoginMethod.totp, LoginMethod.passkey}),
    )
    await session.commit()


async def _remove_the_password(
    client: AsyncClient, session: AsyncSession, user: User, headers: dict[str, str]
) -> Response:
    await _seed_passkey(session, user)
    return await client.post(REMOVE, headers=headers, json={})


# Re-issuing codes asks a password holder to be enrolled first, which is not
# this question; giving the password up is asked of password holders only.
_GATED_FOR_A_HELD_PASSWORD = [
    row for row in _GATED if row[0] != "re-issue-the-codes"
] + [("remove-the-password", _remove_the_password, 200)]


@pytest.mark.parametrize(
    "slug,route,ok",
    _GATED_FOR_A_HELD_PASSWORD,
    ids=[row[0] for row in _GATED_FOR_A_HELD_PASSWORD],
)
async def test_a_password_nobody_signs_in_with_is_not_asked_for(
    client: AsyncClient, session: AsyncSession, slug: str, route, ok: int
):
    """Where the deployment takes no password, one the account still holds is
    not a way in, so a recent sign-in answers in its place — and one of a
    while ago does not."""
    await _withdraw_passwords(session)
    fresh = await _account(session, f"nopw-fresh-{slug}@example.com")
    fresh_id = fresh.id
    stale = await _account(session, f"nopw-stale-{slug}@example.com")

    answered = await route(client, session, fresh, await _proof_headers(session, fresh))
    refused = await route(
        client, session, stale, await _proof_headers(session, stale, minutes_ago=11)
    )

    assert answered.status_code == ok, answered.text
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == "RECENT_PROOF_REQUIRED"
    if slug == "set-a-password":
        # Nobody was asked for the password, so the new session claims none.
        live = (
            await session.exec(
                select(AuthSession.amr).where(
                    AuthSession.user_id == fresh_id, AuthSession.revoked_at.is_(None)
                )
            )
        ).all()
        assert live == [[]]


async def test_the_account_says_whether_its_password_is_asked_for(
    client: AsyncClient, session: AsyncSession
):
    """What the confirmation forms read to decide whether to show the field."""
    user = await _account(session, "pl-required@example.com")
    headers = get_auth_headers(user)

    before = await client.get("/api/v1/me", headers=headers)
    await _withdraw_passwords(session)
    after = await client.get("/api/v1/me", headers=headers)

    assert before.json()["password_required"] is True
    assert after.json()["has_password"] is True
    assert after.json()["password_required"] is False


async def test_an_account_holding_a_password_answers_with_it_instead(
    client: AsyncClient, session: AsyncSession
):
    """The age of the session is not asked about where there is a password to
    re-check."""
    user = await _account(session, "pl-haspw-gate@example.com")
    headers = await _proof_headers(session, user, minutes_ago=11)

    response = await client.post(
        "/api/v1/auth/passkeys/register/begin",
        headers=headers,
        json={"current_password": PASSWORD, "name": "Laptop"},
    )
    assert response.status_code == 200, response.text
