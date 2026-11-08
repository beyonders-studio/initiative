"""Wrong answers add up to a timed lock, each longer than the last within a day."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.sign_in_lock import SignInLock
from app.services.auth import sign_in_locks
from app.services.auth.sign_in_locks import Outcome
from app.testing import create_user

START = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def clock(monkeypatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(sign_in_locks, "utcnow", lambda: clock.now)
    return clock


async def _fail(session: AsyncSession, user_id: int, times: int = 1):
    failure = None
    for _ in range(times):
        failure = await sign_in_locks.record_failure(session, user_id)
        await session.commit()
    return failure


async def test_four_wrong_answers_do_not_lock(session: AsyncSession, clock):
    user = await create_user(session)
    failure = await _fail(session, user.id, times=4)
    assert failure.outcome is Outcome.counted
    assert not await sign_in_locks.is_locked(session, user.id)


async def test_the_fifth_locks_for_fifteen_minutes(session: AsyncSession, clock):
    user = await create_user(session)
    await _fail(session, user.id, times=4)
    failure = await _fail(session, user.id)

    assert failure == sign_in_locks.Failure(
        Outcome.locked, lock_for=timedelta(minutes=15)
    )
    assert await sign_in_locks.is_locked(session, user.id)

    clock.advance(timedelta(minutes=15, seconds=1))
    assert not await sign_in_locks.is_locked(session, user.id)


async def test_failures_outside_the_window_start_over(session: AsyncSession, clock):
    user = await create_user(session)
    await _fail(session, user.id, times=4)
    clock.advance(timedelta(minutes=16))
    failure = await _fail(session, user.id)
    assert failure.outcome is Outcome.counted
    assert not await sign_in_locks.is_locked(session, user.id)


async def test_signing_in_starts_the_count_over(session: AsyncSession, clock):
    user = await create_user(session)
    await _fail(session, user.id, times=4)
    await sign_in_locks.record_success(session, user.id)
    await session.commit()
    failure = await _fail(session, user.id, times=4)
    assert failure.outcome is Outcome.counted


async def test_answers_while_locked_are_not_counted(session: AsyncSession, clock):
    user = await create_user(session)
    await _fail(session, user.id, times=5)
    await _fail(session, user.id, times=5)

    row = await session.get(SignInLock, user.id)
    assert row is not None
    await session.refresh(row)
    assert row.locks == 1


async def test_each_lock_in_a_day_lasts_longer_up_to_four_hours(
    session: AsyncSession, clock
):
    user = await create_user(session)
    for length in (
        timedelta(minutes=15),
        timedelta(hours=1),
        timedelta(hours=4),
        timedelta(hours=4),
    ):
        failure = await _fail(session, user.id, times=5)
        assert failure.outcome is Outcome.locked
        assert failure.lock_for == length

        # Every lock ends on its own, at the cap as well.
        clock.advance(length - timedelta(seconds=1))
        assert await sign_in_locks.is_locked(session, user.id)
        clock.advance(timedelta(seconds=2))
        assert not await sign_in_locks.is_locked(session, user.id)


async def test_lifting_ends_the_lock_and_starts_the_counts_over(
    session: AsyncSession, clock
):
    user = await create_user(session)
    await _fail(session, user.id, times=5)
    clock.advance(timedelta(minutes=16))
    await _fail(session, user.id, times=5)

    assert await sign_in_locks.lift(session, user.id)
    await session.commit()
    assert not await sign_in_locks.is_locked(session, user.id)
    assert not await sign_in_locks.lift(session, user.id)

    failure = await _fail(session, user.id, times=5)
    assert failure.lock_for == timedelta(minutes=15)


async def test_locks_start_over_a_day_after_the_first(session: AsyncSession, clock):
    user = await create_user(session)
    lengths = []
    for _ in range(3):
        failure = await _fail(session, user.id, times=5)
        lengths.append(failure.lock_for)
        clock.advance(timedelta(hours=13))
    assert lengths == [timedelta(minutes=15), timedelta(hours=1), timedelta(minutes=15)]
    assert not await sign_in_locks.is_locked(session, user.id)


async def test_closed_names_only_locked_accounts(session: AsyncSession, clock):
    locked = await create_user(session)
    counting = await create_user(session)
    await _fail(session, locked.id, times=5)
    await _fail(session, counting.id, times=2)

    rows = await sign_in_locks.closed(session, [locked.id, counting.id])
    assert set(rows) == {locked.id}
    assert rows[locked.id].locked_until == START + timedelta(minutes=15)


async def test_failures_in_one_transaction_add_up(session: AsyncSession, clock):
    user = await create_user(session)
    for _ in range(4):
        await sign_in_locks.record_failure(session, user.id)
    failure = await sign_in_locks.record_failure(session, user.id)
    assert failure.outcome is Outcome.locked
