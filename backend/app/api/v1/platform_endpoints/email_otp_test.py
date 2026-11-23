"""Signing in with a one-time code sent to an address."""

from datetime import UTC

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import decode_session_token
from app.services.platform import rules
from app.testing import captcha_switched_on, create_user

SEND_URL = "/api/v1/auth/email-otp/send"
VERIFY_URL = "/api/v1/auth/email-otp/verify"


async def _permit(session: AsyncSession, *, mail: bool = True) -> None:
    """A deployment offering the emailed code, able to send."""
    from app.core.login_methods import LoginMethod
    from app.services.platform import app_settings as app_settings_service

    row = await app_settings_service.get_app_settings(session)
    if mail:
        row.smtp_host = "smtp.example.com"
        row.smtp_from_address = "noreply@example.com"
    session.add(row)
    await rules.put(session, "login_methods", frozenset(LoginMethod))
    await session.commit()


def _catch_codes(monkeypatch) -> list[tuple[str, str]]:
    """Every code the routes post, as (address, code)."""
    from app.services import email as email_service

    caught: list[tuple[str, str]] = []

    async def _capture(session_, user, *, email, code, minutes):
        caught.append((email, code))

    monkeypatch.setattr(email_service, "send_sign_in_code_email", _capture)
    return caught


async def _ask(
    client: AsyncClient, address: str, *, headers: dict[str, str] | None = None
) -> str:
    response = await client.post(SEND_URL, json={"email": address}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["challenge"]


@pytest.mark.parametrize("password", [True, False], ids=["password", "keyless"])
async def test_a_code_signs_the_account_in_once(
    client: AsyncClient, session: AsyncSession, monkeypatch, password: bool
):
    """A six-digit code signs in an account at a proved address, whether or
    not it holds a password, and retires nothing it held. The code answers
    once."""
    from sqlalchemy import select

    from app.models.platform.user import User
    from app.services.auth.email_otp import CODE_DIGITS

    await _permit(session)
    caught = _catch_codes(monkeypatch)
    overrides = {} if password else {"hashed_password": None}
    account = await create_user(session, email="reader@example.com", **overrides)
    account_id, held = account.id, account.hashed_password

    handle = await _ask(client, "reader@example.com")
    assert [address for address, _ in caught] == ["reader@example.com"]
    code = caught[0][1]
    assert len(code) == CODE_DIGITS and code.isdigit()

    signed_in = await client.post(VERIFY_URL, json={"challenge": handle, "code": code})

    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["access_token"]
    session.expire_all()
    after = (await session.exec(select(User).where(User.id == account_id))).scalar_one()
    assert after.hashed_password == held

    again = await client.post(VERIFY_URL, json={"challenge": handle, "code": code})
    assert again.status_code == 400
    assert again.json()["detail"] == "EMAIL_OTP_INVALID"


async def test_asking_reads_the_same_whether_or_not_the_address_is_known(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The whole point of the door: a held address, one whose account cannot
    sign in, an unheld one, and one a closed deployment will not sign up all
    get one response with a handle. Each gets the letter that fits it: an
    account that may sign in a code (a suspended one signs in to be told it
    is in time out), the unheld address a sign-up code, and the rest
    nothing."""
    from app.models.platform.user import UserStatus

    await _permit(session)
    caught = _catch_codes(monkeypatch)
    sign_ups = _catch_sign_ups(monkeypatch)
    await create_user(session, email="known@example.com")
    await create_user(session, email="halted@example.com", status=UserStatus.suspended)
    await create_user(
        session, email="paused@example.com", status=UserStatus.deactivated
    )

    answers = [
        await client.post(SEND_URL, json={"email": address})
        for address in (
            "known@example.com",
            "halted@example.com",
            "paused@example.com",
            "fresh@example.com",
        )
    ]
    # Somebody is already here, so the deployment's registration setting
    # applies rather than the first account's bootstrap.
    await rules.put(session, "public_registration_enabled", False)
    await session.commit()
    answers.append(await client.post(SEND_URL, json={"email": "closed@example.com"}))

    bodies = [r.json() for r in answers]
    assert {r.status_code for r in answers} == {200}
    assert {b["status"] for b in bodies} == {"sent"}
    assert all(b.keys() == bodies[0].keys() for b in bodies)
    assert all(b["challenge"] for b in bodies)
    assert [address for address, _ in caught] == [
        "known@example.com",
        "halted@example.com",
    ]
    assert [address for address, _ in sign_ups] == ["fresh@example.com"]


async def test_a_wrong_code_spends_an_attempt(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Five wrong codes end the challenge, and the right one no longer
    answers it."""
    await _permit(session)
    caught = _catch_codes(monkeypatch)
    await create_user(session, email="attempts@example.com")
    handle = await _ask(client, "attempts@example.com")
    real = caught[0][1]
    wrong = "000000" if real != "000000" else "111111"

    for _ in range(5):
        refused = await client.post(
            VERIFY_URL, json={"challenge": handle, "code": wrong}
        )
        assert refused.status_code == 400

    spent = await client.post(VERIFY_URL, json={"challenge": handle, "code": real})
    assert spent.status_code == 400
    assert spent.json()["detail"] == "EMAIL_OTP_INVALID"


async def test_a_code_without_its_handle_opens_nothing(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Both halves, or neither: the code is stored against the handle it was
    issued with, so it answers for that challenge and no other."""
    await _permit(session)
    caught = _catch_codes(monkeypatch)
    await create_user(session, email="one@example.com")
    await create_user(session, email="two@example.com")

    await _ask(client, "one@example.com")
    other_handle = await _ask(client, "two@example.com")

    crossed = await client.post(
        VERIFY_URL, json={"challenge": other_handle, "code": caught[0][1]}
    )
    assert crossed.status_code == 400
    assert crossed.json()["detail"] == "EMAIL_OTP_INVALID"


async def test_an_expired_code_opens_nothing(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    from datetime import datetime, timedelta

    from sqlalchemy import update

    from app.models.platform.auth_challenge import AuthChallenge

    await _permit(session)
    caught = _catch_codes(monkeypatch)
    await create_user(session, email="late@example.com")
    handle = await _ask(client, "late@example.com")

    await session.exec(
        update(AuthChallenge).values(
            expires_at=datetime.now(UTC) - timedelta(seconds=1)
        )
    )
    await session.commit()

    refused = await client.post(
        VERIFY_URL, json={"challenge": handle, "code": caught[0][1]}
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "EMAIL_OTP_INVALID"


async def test_the_routes_close_when_the_method_is_withdrawn(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The checkbox closes the route, not only the form that reaches it."""
    _catch_codes(monkeypatch)
    await create_user(session, email="closed@example.com")

    send = await client.post(SEND_URL, json={"email": "closed@example.com"})
    verify = await client.post(
        VERIFY_URL, json={"challenge": "anything", "code": "000000"}
    )

    assert send.status_code == 403
    assert send.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"
    assert verify.status_code == 403


async def test_a_code_cannot_be_asked_for_without_a_mail_server(
    client: AsyncClient, session: AsyncSession
):
    """The method can only be permitted with mail configured, but an operator
    can clear the settings afterwards; the route says so rather than opening a
    challenge nothing will answer."""
    await _permit(session, mail=False)
    await create_user(session, email="nomail@example.com")

    refused = await client.post(SEND_URL, json={"email": "nomail@example.com"})

    assert refused.status_code == 400
    assert refused.json()["detail"] == "EMAIL_OTP_CANNOT_SEND"


async def test_a_second_factor_is_still_asked_for(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The code proved the address; an account holding a factor presents it
    the same way a password sign-in does."""
    import pyotp

    from app.services.auth import totp as totp_service

    await _permit(session)
    caught = _catch_codes(monkeypatch)
    holder = await create_user(session, email="factored@example.com")
    enrolment = await totp_service.begin_enrolment(
        session, user_id=holder.id, account="factored@example.com", issuer="Initiative"
    )
    assert await totp_service.confirm_enrolment(
        session, user_id=holder.id, code=pyotp.TOTP(enrolment.secret).now()
    )
    recovery = await totp_service.issue_recovery_codes(session, user_id=holder.id)
    await session.commit()

    handle = await _ask(client, "factored@example.com")
    answered = await client.post(
        VERIFY_URL, json={"challenge": handle, "code": caught[0][1]}
    )

    assert answered.status_code == 401
    assert answered.json()["detail"] == "TOTP_REQUIRED"
    assert answered.json()["challenge"]

    # The session it opens records what both legs proved: the code, not a
    # password nobody presented.
    finished = await client.post(
        "/api/v1/auth/token/totp",
        json={"challenge": answered.json()["challenge"], "recovery_code": recovery[0]},
    )
    assert finished.status_code == 200, finished.text
    claims = decode_session_token(finished.json()["access_token"])
    assert "otp" in claims["amr"] and "mfa" in claims["amr"]
    assert "pwd" not in claims["amr"]


async def test_proving_an_address_for_the_first_time_retires_what_came_before(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """An account sitting on an address nobody had proved keeps its handle and
    its content; the password it was carrying does not survive the proof."""
    from sqlalchemy import select

    from app.models.platform.user import User

    await _permit(session)
    caught = _catch_codes(monkeypatch)
    account = await create_user(
        session, email="unproved@example.com", email_verified=False
    )
    account_id = account.id
    assert account.hashed_password

    handle = await _ask(client, "unproved@example.com")
    signed_in = await client.post(
        VERIFY_URL, json={"challenge": handle, "code": caught[0][1]}
    )
    assert signed_in.status_code == 200, signed_in.text

    session.expire_all()
    after = (await session.exec(select(User).where(User.id == account_id))).scalar_one()
    assert after.hashed_password is None
    assert after.password_set_at is None


# ---------------------------------------------------------------------------
# The same door makes an account
# ---------------------------------------------------------------------------

REGISTER_URL = "/api/v1/auth/email-otp/register"


async def _sign_up_to_ticket(
    client: AsyncClient,
    caught,
    address: str,
    *,
    headers: dict[str, str] | None = None,
) -> str:
    """Ask at an unheld address, answer the code, and take the ticket."""
    handle = await _ask(client, address, headers=headers)
    answered = await client.post(
        VERIFY_URL, json={"challenge": handle, "code": caught[-1][1]}, headers=headers
    )
    assert answered.status_code == 202, answered.text
    return answered.json()["registration_ticket"]


def _catch_sign_ups(monkeypatch) -> list[tuple[str, str]]:
    from app.services import email as email_service

    caught: list[tuple[str, str]] = []

    async def _capture(session_, *, email, code, minutes, locale):
        caught.append((email, code))

    monkeypatch.setattr(email_service, "send_sign_up_code_email", _capture)
    return caught


async def test_an_unheld_address_is_offered_a_sign_up(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The code sent to an unheld address answers with a ticket rather than a
    session. The ticket makes the account once and signs it in; the account
    has no password, and the address the code arrived at starts out proved."""
    from sqlalchemy import select

    from app.core.encryption import hash_email
    from app.models.platform.user import User
    from app.models.platform.user_email import UserEmail

    await _permit(session)
    _catch_codes(monkeypatch)
    caught = _catch_sign_ups(monkeypatch)

    handle = await _ask(client, "arrival@example.com")
    assert [address for address, _ in caught] == ["arrival@example.com"]
    answered = await client.post(
        VERIFY_URL, json={"challenge": handle, "code": caught[0][1]}
    )
    assert answered.status_code == 202, answered.text
    assert "access_token" not in answered.json()
    ticket = answered.json()["registration_ticket"]

    made = await client.post(
        REGISTER_URL, json={"registration_ticket": ticket, "username": "arrival"}
    )

    assert made.status_code == 201, made.text
    assert made.json()["access_token"]
    # A browser keeps its refresh token in a cookie, not the body.
    assert not made.json().get("refresh_token")
    account = (
        await session.exec(select(User).where(User.username == "arrival"))
    ).scalar_one()
    assert account.hashed_password is None
    row = (
        await session.exec(
            select(UserEmail).where(
                UserEmail.email_hash == hash_email("arrival@example.com")
            )
        )
    ).scalar_one()
    assert row.verified_at is not None

    again = await client.post(
        REGISTER_URL, json={"registration_ticket": ticket, "username": "twiceagain"}
    )
    assert again.status_code == 400
    assert again.json()["detail"] == "EMAIL_OTP_INVALID"


async def test_the_app_signing_up_keeps_its_session(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The app keeps its refresh token itself, so the sign-up hands it one."""
    await _permit(session)
    _catch_codes(monkeypatch)
    caught = _catch_sign_ups(monkeypatch)
    app = {"Origin": "https://studio.beyonders.initiative"}
    ticket = await _sign_up_to_ticket(
        client, caught, "app-arrival@example.com", headers=app
    )

    made = await client.post(
        REGISTER_URL,
        json={"registration_ticket": ticket, "username": "apparrival"},
        headers=app,
    )

    assert made.status_code == 201, made.text
    assert made.json()["refresh_token"]


async def test_a_code_for_an_address_no_sign_up_follows_opens_nothing(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The challenge stands so the answer reads the same, and answers to it
    are refused like any other pair that names nothing."""

    await _permit(session)
    _catch_codes(monkeypatch)
    _catch_sign_ups(monkeypatch)
    await create_user(session, email="resident@example.com")
    await rules.put(session, "public_registration_enabled", False)
    await session.commit()

    handle = await _ask(client, "shutout@example.com")
    refused = await client.post(
        VERIFY_URL, json={"challenge": handle, "code": "000000"}
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == "EMAIL_OTP_INVALID"


async def test_registering_needs_the_method_permitted(
    client: AsyncClient, session: AsyncSession
):
    refused = await client.post(
        REGISTER_URL, json={"registration_ticket": "anything", "username": "nobody"}
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"


async def test_a_sign_in_code_is_not_a_registration_ticket(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The two are different purposes, so one cannot be spent as the other."""
    await _permit(session)
    caught = _catch_codes(monkeypatch)
    _catch_sign_ups(monkeypatch)
    await create_user(session, email="holder@example.com")
    handle = await _ask(client, "holder@example.com")
    assert caught

    refused = await client.post(
        REGISTER_URL, json={"registration_ticket": handle, "username": "mixedup"}
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "EMAIL_OTP_INVALID"


async def test_the_send_asks_for_the_captcha_where_one_is_configured(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The token is what the card has to carry, so the refusal is pinned here.

    Asking is the step that posts mail to an address nobody has proved, and
    the captcha answers for the request rather than for the address — so it
    is checked before the address is looked at.
    """
    await _permit(session)

    with captcha_switched_on():
        refused = await client.post(SEND_URL, json={"email": "reader@example.com"})

    assert refused.status_code == 400
    assert refused.json()["detail"] == "CAPTCHA_REQUIRED"


async def test_the_send_takes_the_token_the_card_carries(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """With the token present the route answers as it does anywhere else."""
    from app.services import captcha as captcha_service

    await _permit(session)
    caught = _catch_codes(monkeypatch)
    await create_user(session, email="reader@example.com")

    async def _accept(token, *, remote_ip):
        assert token == "solved"

    monkeypatch.setattr(captcha_service, "verify_or_raise", _accept)

    with captcha_switched_on():
        sent = await client.post(
            SEND_URL, json={"email": "reader@example.com", "captcha_token": "solved"}
        )

    assert sent.status_code == 200, sent.text
    assert [address for address, _ in caught] == ["reader@example.com"]


# ── Confirming a session already open ──────────────────────────────────────

STEP_UP_SEND_URL = "/api/v1/auth/step-up/email-otp/send"
STEP_UP_VERIFY_URL = "/api/v1/auth/step-up/email-otp/verify"
REGENERATE_URL = "/api/v1/auth/recovery-codes/regenerate"


async def _stale_session_headers(session: AsyncSession, user) -> dict[str, str]:
    """A session signed into long enough ago that it no longer confirms."""
    from datetime import datetime, timedelta

    from app.services.auth import sessions as session_service
    from app.testing import get_auth_token

    issued = await session_service.create_session(
        session, user_id=user.id, amr=["otp"], satisfied_providers=[]
    )
    issued.session.created_at = datetime.now(UTC) - timedelta(minutes=11)
    session.add(issued.session)
    await session.commit()
    return {
        "Authorization": "Bearer "
        + get_auth_token(user, session_id=issued.session.id, amr=["otp"])
    }


async def test_an_emailed_code_confirms_the_session_already_open(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A change that wants a recent sign-in takes the code instead of a
    sign-out and back in."""
    await _permit(session)
    caught = _catch_codes(monkeypatch)
    user = await create_user(session, email="confirm@example.com", hashed_password=None)
    headers = await _stale_session_headers(session, user)

    refused = await client.post(REGENERATE_URL, headers=headers, json={})
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == "RECENT_PROOF_REQUIRED"

    sent = await client.post(STEP_UP_SEND_URL, headers=headers)
    assert sent.status_code == 200, sent.text
    assert [address for address, _ in caught] == ["confirm@example.com"]

    wrong = await client.post(
        STEP_UP_VERIFY_URL,
        headers=headers,
        json={"challenge": sent.json()["challenge"], "code": "not-it"},
    )
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "EMAIL_OTP_INVALID"

    confirmed = await client.post(
        STEP_UP_VERIFY_URL,
        headers=headers,
        json={"challenge": sent.json()["challenge"], "code": caught[0][1]},
    )
    assert confirmed.status_code == 200, confirmed.text
    fresh = {"Authorization": f"Bearer {confirmed.json()['access_token']}"}
    # The wrong code before it no longer counts toward a lock.
    from app.models.platform.sign_in_lock import SignInLock

    user_id = user.id
    session.expire_all()
    assert (await session.get(SignInLock, user_id)).failures == 0

    answered = await client.post(REGENERATE_URL, headers=fresh, json={})
    assert answered.status_code == 200, answered.text


async def test_a_sign_in_code_does_not_confirm_a_session(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The two are asked for against different purposes, so a handle from
    the sign-in page answers nothing here."""
    await _permit(session)
    caught = _catch_codes(monkeypatch)
    user = await create_user(session, email="apart@example.com", hashed_password=None)
    handle = await _ask(client, "apart@example.com")

    refused = await client.post(
        STEP_UP_VERIFY_URL,
        headers=await _stale_session_headers(session, user),
        json={"challenge": handle, "code": caught[0][1]},
    )

    assert refused.status_code == 400
    assert refused.json()["detail"] == "EMAIL_OTP_INVALID"


async def test_a_confirming_code_goes_only_to_a_proved_address(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    await _permit(session)
    caught = _catch_codes(monkeypatch)
    user = await create_user(
        session,
        email="unproved@example.com",
        hashed_password=None,
        email_verified=False,
    )

    refused = await client.post(
        STEP_UP_SEND_URL, headers=await _stale_session_headers(session, user)
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "EMAIL_OTP_NO_PROVED_ADDRESS"
    assert caught == []
