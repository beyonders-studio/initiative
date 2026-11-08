"""Enrolling a factor, and which codes it takes."""

from datetime import UTC, datetime, timedelta

import pyotp
import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.mfa_recovery_code import MfaRecoveryCode
from app.models.platform.user_totp_secret import UserTotpSecret
from app.services.auth import totp as totp_service
from app.testing import create_user

#: A fixed moment, so a test that reasons about 30-second intervals never
#: straddles one.
FIXED_NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(totp_service, "utcnow", lambda: FIXED_NOW)
    return FIXED_NOW


def _code_at(secret: str, *, offset_steps: int = 0, at: datetime = FIXED_NOW) -> str:
    totp = pyotp.TOTP(
        secret, digits=totp_service.TOTP_DIGITS, interval=totp_service.TOTP_PERIOD
    )
    step = int(at.timestamp()) // totp_service.TOTP_PERIOD + offset_steps
    return totp.at(step * totp_service.TOTP_PERIOD)


async def _enrol(session: AsyncSession, frozen) -> tuple[int, str]:
    user = await create_user(session)
    assert user.id is not None
    enrolment = await totp_service.begin_enrolment(
        session, user_id=user.id, account="someone@example.com", issuer="Initiative"
    )
    await session.commit()
    return user.id, enrolment.secret


async def test_a_started_enrolment_is_not_yet_asked_for(session: AsyncSession, frozen):
    """A factor nobody has proved asks nothing of the sign-in."""
    user_id, _secret = await _enrol(session, frozen)
    assert await totp_service.is_enrolled(session, user_id=user_id) is False


async def test_confirming_takes_a_code_the_authenticator_made(
    session: AsyncSession, frozen
):
    user_id, secret = await _enrol(session, frozen)

    assert (
        await totp_service.confirm_enrolment(session, user_id=user_id, code="000000")
        is False
    )
    assert (
        await totp_service.confirm_enrolment(
            session, user_id=user_id, code=_code_at(secret)
        )
        is True
    )
    await session.commit()
    assert await totp_service.is_enrolled(session, user_id=user_id) is True


async def test_a_code_is_taken_once(session: AsyncSession, frozen):
    """The interval an accepted code came from is recorded, so the same code
    read a second time is not accepted."""
    user_id, secret = await _enrol(session, frozen)
    code = _code_at(secret)
    await totp_service.confirm_enrolment(session, user_id=user_id, code=code)
    await session.commit()

    assert await totp_service.verify_code(session, user_id=user_id, code=code) is False


async def test_a_later_code_is_taken_after_an_earlier_one(
    session: AsyncSession, frozen, monkeypatch
):
    user_id, secret = await _enrol(session, frozen)
    await totp_service.confirm_enrolment(
        session, user_id=user_id, code=_code_at(secret)
    )
    await session.commit()

    later = FIXED_NOW + timedelta(seconds=totp_service.TOTP_PERIOD)
    monkeypatch.setattr(totp_service, "utcnow", lambda: later)
    assert (
        await totp_service.verify_code(
            session, user_id=user_id, code=_code_at(secret, at=later)
        )
        is True
    )


@pytest.mark.parametrize("offset", [-1, 1])
async def test_clocks_may_disagree_by_one_interval(
    session: AsyncSession, frozen, offset
):
    user_id, secret = await _enrol(session, frozen)
    assert (
        await totp_service.confirm_enrolment(
            session, user_id=user_id, code=_code_at(secret, offset_steps=offset)
        )
        is True
    )


@pytest.mark.parametrize("offset", [-2, 2])
async def test_but_not_by_two(session: AsyncSession, frozen, offset):
    user_id, secret = await _enrol(session, frozen)
    assert (
        await totp_service.confirm_enrolment(
            session, user_id=user_id, code=_code_at(secret, offset_steps=offset)
        )
        is False
    )


async def test_beginning_again_replaces_an_unproved_enrolment(
    session: AsyncSession, frozen
):
    user_id, first = await _enrol(session, frozen)
    second = await totp_service.begin_enrolment(
        session, user_id=user_id, account="someone@example.com", issuer="Initiative"
    )
    await session.commit()

    assert second.secret != first
    assert (
        await totp_service.confirm_enrolment(
            session, user_id=user_id, code=_code_at(first)
        )
        is False
    )
    assert (
        await totp_service.confirm_enrolment(
            session, user_id=user_id, code=_code_at(second.secret)
        )
        is True
    )


async def test_the_uri_carries_what_an_authenticator_reads(
    session: AsyncSession, frozen
):
    _user_id, secret = await _enrol(session, frozen)
    uri = totp_service.otpauth_uri(
        secret, account="someone@example.com", issuer="Initiative"
    )
    assert uri.startswith("otpauth://totp/Initiative%3Asomeone%40example.com?")
    assert f"secret={secret}" in uri
    assert "issuer=Initiative" in uri
    assert "digits=6" in uri
    assert "period=30" in uri


async def test_disabling_leaves_no_seed_and_no_codes(session: AsyncSession, frozen):
    user_id, secret = await _enrol(session, frozen)
    await totp_service.confirm_enrolment(
        session, user_id=user_id, code=_code_at(secret)
    )
    await totp_service.issue_recovery_codes(session, user_id=user_id)
    await session.commit()

    assert await totp_service.disable(session, user_id=user_id) is True
    await session.commit()

    assert await totp_service.get_factor(session, user_id=user_id) is None
    assert (
        await session.exec(
            select(UserTotpSecret).where(UserTotpSecret.user_id == user_id)
        )
    ).first() is None
    assert (
        await session.exec(
            select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id)
        )
    ).all() == []


async def test_disabling_says_when_there_was_nothing_to_disable(
    session: AsyncSession, frozen
):
    user = await create_user(session)
    assert await totp_service.disable(session, user_id=user.id) is False


# --- Recovery codes --------------------------------------------------------


async def test_a_recovery_code_works_once(session: AsyncSession, frozen):
    user = await create_user(session)
    codes = await totp_service.issue_recovery_codes(session, user_id=user.id)
    await session.commit()

    assert len(codes) == totp_service.RECOVERY_CODE_COUNT
    assert len(set(codes)) == totp_service.RECOVERY_CODE_COUNT

    assert (
        await totp_service.consume_recovery_code(
            session, user_id=user.id, code=codes[0]
        )
        is True
    )
    await session.commit()
    assert (
        await totp_service.consume_recovery_code(
            session, user_id=user.id, code=codes[0]
        )
        is False
    )
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user.id)
        == totp_service.RECOVERY_CODE_COUNT - 1
    )


async def test_a_code_is_read_however_it_was_copied(session: AsyncSession, frozen):
    """Dashes and casing are how it is written down, not what it is."""
    user = await create_user(session)
    codes = await totp_service.issue_recovery_codes(session, user_id=user.id)
    await session.commit()

    typed = codes[0].replace("-", " ").upper()
    assert (
        await totp_service.consume_recovery_code(session, user_id=user.id, code=typed)
        is True
    )


async def test_one_account_s_code_is_not_another_s(session: AsyncSession, frozen):
    mine = await create_user(session)
    theirs = await create_user(session)
    codes = await totp_service.issue_recovery_codes(session, user_id=mine.id)
    await totp_service.issue_recovery_codes(session, user_id=theirs.id)
    await session.commit()

    assert (
        await totp_service.consume_recovery_code(
            session, user_id=theirs.id, code=codes[0]
        )
        is False
    )


async def test_issuing_again_retires_the_previous_set(session: AsyncSession, frozen):
    user = await create_user(session)
    first = await totp_service.issue_recovery_codes(session, user_id=user.id)
    await session.commit()
    await totp_service.issue_recovery_codes(session, user_id=user.id)
    await session.commit()

    assert (
        await totp_service.consume_recovery_code(
            session, user_id=user.id, code=first[0]
        )
        is False
    )
    assert (
        await totp_service.remaining_recovery_codes(session, user_id=user.id)
        == totp_service.RECOVERY_CODE_COUNT
    )
