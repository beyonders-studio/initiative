"""A challenge stands until it is spent, expires, or runs out of attempts."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.auth_challenge import AuthChallenge
from app.services.auth import challenges
from app.testing import create_user

FIXED_NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
PURPOSE = challenges.ChallengePurpose.sign_in


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(challenges, "utcnow", lambda: FIXED_NOW)
    return FIXED_NOW


async def _open(session: AsyncSession, user_id: int) -> challenges.IssuedChallenge:
    issued = await challenges.create(session, user_id=user_id, purpose=PURPOSE)
    await session.commit()
    return issued


async def _claim(session: AsyncSession, value: str):
    return await challenges.claim_attempt(session, value=value, purposes=[PURPOSE])


async def test_the_raw_value_is_not_what_is_stored(session: AsyncSession, frozen):
    user = await create_user(session)
    issued = await _open(session, user.id)
    assert issued.challenge.challenge_hash != issued.value.encode("utf-8")
    assert len(issued.challenge.challenge_hash) == 32


async def test_each_claim_takes_its_own_attempt(session: AsyncSession, frozen):
    """The count is raised by the statement that finds the row, rather than
    worked out first and written back, so two claims are two attempts."""
    user = await create_user(session)
    issued = await _open(session, user.id)
    challenge_id = issued.challenge.id

    assert await _claim(session, issued.value) is not None
    assert await _claim(session, issued.value) is not None
    await session.commit()

    session.expire_all()
    standing = await session.get(AuthChallenge, challenge_id)
    assert standing is not None
    assert standing.attempts == 2


async def test_they_go_when_what_they_rest_on_moves(session: AsyncSession, frozen):
    user = await create_user(session)
    first = await _open(session, user.id)
    second = await _open(session, user.id)

    assert await challenges.revoke_for_user(session, user_id=user.id) == 2
    await session.commit()

    for issued in (first, second):
        assert await _claim(session, issued.value) is None


async def test_one_account_s_challenges_are_left_alone(session: AsyncSession, frozen):
    mine = await create_user(session)
    theirs = await create_user(session)
    ours = await _open(session, mine.id)
    await _open(session, theirs.id)

    assert await challenges.revoke_for_user(session, user_id=theirs.id) == 1
    await session.commit()
    assert await _claim(session, ours.value) is not None


async def test_the_sweep_clears_what_nothing_can_use(
    session: AsyncSession, frozen, monkeypatch
):
    user = await create_user(session)
    issued = await _open(session, user.id)

    later = FIXED_NOW + challenges.CHALLENGE_TTL + timedelta(seconds=1)
    monkeypatch.setattr(challenges, "utcnow", lambda: later)
    assert await challenges.purge_expired(session) >= 1
    await session.commit()

    monkeypatch.setattr(challenges, "utcnow", lambda: FIXED_NOW)
    assert await _claim(session, issued.value) is None
