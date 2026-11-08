"""Wrong passwords and codes, counted per account.

Five wrong answers within fifteen minutes lock the account's password and codes.
The first lock within a day lasts fifteen minutes, the second an hour, and the
third and every one after it four hours. Every lock ends on its own; a password
reset from the emailed link, or a moderator, ends it sooner. Passkeys and
sessions already open are not affected.

Every function here stages its writes on the caller's system-engine session;
the caller commits. The one exception is the count kept by address
(``app.core.rate_limit``), which is not in the database: :func:`lift` starts it
over at once.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.clock import utcnow
from app.core.rate_limit import SIGN_IN_FAILURES
from app.models.platform.sign_in_lock import SignInLock
from app.services import audit as audit_service
from app.services.auth import addresses

logger = logging.getLogger(__name__)

LOCK_AFTER_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
#: How long the first, second and each later lock within ``LOCK_WINDOW`` lasts.
LOCK_FOR = (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=4))
LOCK_WINDOW = timedelta(hours=24)


class Outcome(enum.Enum):
    counted = "counted"
    locked = "locked"


@dataclass(frozen=True)
class Failure:
    """What one wrong answer did."""

    outcome: Outcome
    #: How long the lock this answer placed lasts; None when it placed none.
    lock_for: timedelta | None = None


async def _row_for_update(session: AsyncSession, user_id: int) -> SignInLock:
    """The account's row, created if missing, locked for this transaction."""
    # The re-read below replaces the loaded row, so anything staged on it goes
    # to the database first.
    await session.flush()
    await session.exec(
        pg_insert(SignInLock)
        .values(user_id=user_id, failures=0, locks=0)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    result = await session.exec(
        select(SignInLock)
        .where(SignInLock.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.one()


def _is_closed(row: SignInLock | None, now: datetime) -> bool:
    if row is None:
        return False
    return row.locked_until is not None and row.locked_until > now


async def is_locked(session: AsyncSession, user_id: int) -> bool:
    """Whether password and codes are refused for this account right now."""
    return _is_closed(await session.get(SignInLock, user_id), utcnow())


async def record_failure(session: AsyncSession, user_id: int) -> Failure:
    """Count one wrong answer, and place a lock if it is due."""
    now = utcnow()
    row = await _row_for_update(session, user_id)
    if _is_closed(row, now):
        # Refused before anything was checked; nothing more to count.
        return Failure(Outcome.counted)

    if row.first_failure_at is None or now - row.first_failure_at > FAILURE_WINDOW:
        row.failures = 0
        row.first_failure_at = now
    row.failures += 1

    if row.failures < LOCK_AFTER_FAILURES:
        session.add(row)
        return Failure(Outcome.counted)

    row.failures = 0
    row.first_failure_at = None
    if row.first_lock_at is None or now - row.first_lock_at > LOCK_WINDOW:
        row.locks = 0
        row.first_lock_at = now
    row.locks += 1

    lock_for = LOCK_FOR[min(row.locks, len(LOCK_FOR)) - 1]
    row.locked_until = now + lock_for
    session.add(row)

    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_SIGN_IN_LOCKED,
        actor_user_id=None,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"locks": row.locks, "minutes": int(lock_for.total_seconds()) // 60},
    )
    return Failure(Outcome.locked, lock_for=lock_for)


async def record_success(session: AsyncSession, user_id: int) -> None:
    """Start the count over: the account's holder has just signed in.

    Locks already placed still count toward the length of the next one.
    """
    row = await session.get(SignInLock, user_id)
    if row is None or row.failures == 0:
        return
    row.failures = 0
    row.first_failure_at = None
    session.add(row)


async def lift(session: AsyncSession, user_id: int) -> bool:
    """Clear everything counted against the account, and any lock. True if it
    was locked.

    The count kept by address starts over too, for each address the account
    signs in with. It refuses in the same words as the lock, so lifting one and
    not the other would leave the account refused for the rest of its window.
    """
    was_closed = _is_closed(await session.get(SignInLock, user_id), utcnow())
    await session.exec(delete(SignInLock).where(SignInLock.user_id == user_id))
    for address in await addresses.proven_addresses(session, user_id=user_id):
        try:
            await SIGN_IN_FAILURES.clear(address)
        except Exception:
            # The count lapses at the end of its window anyway; the lift and
            # whatever the caller commits with it go ahead without it.
            logger.warning(
                "Could not start an address's sign-in count over", exc_info=True
            )
    return was_closed


async def closed(
    session: AsyncSession, user_ids: Sequence[int]
) -> dict[int, SignInLock]:
    """The rows of those of these accounts whose password and codes are turned
    off right now."""
    if not user_ids:
        return {}
    result = await session.exec(
        select(SignInLock).where(
            SignInLock.user_id.in_(user_ids)  # type: ignore[attr-defined]
        )
    )
    now = utcnow()
    return {row.user_id: row for row in result.all() if _is_closed(row, now)}
