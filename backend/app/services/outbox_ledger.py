"""How a queue table's rows are claimed, held and tried again.

The email outbox, the notice outbox and the webhook delivery ledger are each a
table of work that a worker takes, attempts, and settles or backs off. They
share the rules here:

* **A claim is a lease.** A pass holds what it took for :data:`LEASE`; a row
  whose pass never finished is taken again once the lease has run out.
* **A recipient is served by one pass at a time.** The outboxes claim by
  recipient, and a recipient with a row another pass holds waits for it, so
  one person's rows go out in the order they were written.
* **A failure waits longer each time.** The wait is chosen in the statement
  that counts the failure, so two passes racing there cannot both read a stale
  count.
* **A schedule lists every wait.** Each is waited once; a row that fails again
  after the last is given up.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Interval,
    Table,
    Update,
    case,
    func,
    literal,
    literal_column,
    null,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import array
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.notice_outbox import NoticeOutboxItem

#: How long a claim holds its rows before another pass may take them back.
LEASE = timedelta(minutes=5)

#: The waits between attempts, in seconds: after the first failure, the
#: second, and so on.
BACKOFF_SECONDS: tuple[int, ...] = (5, 30, 120, 600, 1800, 3600)


def _due(
    table: Table, *, now: datetime, still_open: Sequence[ColumnElement[bool]]
) -> tuple[ColumnElement[bool], ...]:
    """Rows that may be taken now: due, open, and held by no live claim."""
    return (
        table.c.deliver_after <= now,
        or_(table.c.claimed_at.is_(None), table.c.claimed_at < now - LEASE),
        *still_open,
    )


async def due_recipients[RowT: (EmailOutboxItem, NoticeOutboxItem)](
    session: AsyncSession,
    model: type[RowT],
    *,
    now: datetime,
    limit: int,
    still_open: Sequence[ColumnElement[bool]] = (),
) -> list[int]:
    """Up to ``limit`` recipients with rows due, lowest id first, leaving out
    any recipient another pass is still serving.

    ``still_open`` narrows the table to the rows not yet settled, for a queue
    that keeps settled rows.
    """
    table: Table = model.__table__
    held = select(table.c.user_id).where(table.c.claimed_at >= now - LEASE, *still_open)
    rows = await session.exec(
        select(table.c.user_id)
        .where(*_due(table, now=now, still_open=still_open))
        .where(table.c.user_id.not_in(held))
        .distinct()
        .order_by(table.c.user_id)
        .limit(limit)
    )
    return list(rows.scalars().all())


async def claim[RowT: (EmailOutboxItem, NoticeOutboxItem)](
    session: AsyncSession,
    model: type[RowT],
    user_ids: Sequence[int],
    *,
    now: datetime,
    still_open: Sequence[ColumnElement[bool]] = (),
) -> list[RowT]:
    """Take every due row of these recipients, in the order they were written.

    The claim and the read are one statement, and a pass racing this one
    waits on the rows and then finds them taken. The rows come back detached
    from ``session``, so what the worker does with them is not written back.
    """
    if not user_ids:
        return []
    table: Table = model.__table__
    claimed = await session.exec(
        update(model)
        .where(
            table.c.user_id.in_(list(user_ids)),
            *_due(table, now=now, still_open=still_open),
        )
        .values(claimed_at=now)
        .returning(model)
        .execution_options(synchronize_session=False)
    )
    rows = sorted(claimed.scalars().all(), key=lambda row: row.id or 0)
    for row in rows:
        session.expunge(row)
    return rows


def given_up(
    attempts: ColumnElement[int], schedule: Sequence[int] = BACKOFF_SECONDS
) -> ColumnElement[bool]:
    """Whether the failure being counted comes after the schedule's last wait."""
    return attempts + 1 > len(schedule)


def back_off(
    table: Table,
    where: ColumnElement[bool],
    *,
    now: datetime,
    schedule: Sequence[int] = BACKOFF_SECONDS,
    due: str = "deliver_after",
    lease: str | None = "claimed_at",
    spent: str | None = None,
) -> Update:
    """Count a failure on the rows ``where`` selects and put them back, due
    after the next wait in ``schedule`` (the last one, once past it).

    ``due`` names the column a row waits on and ``lease`` the claim it
    gives up. ``spent`` names the column stamped on a row that has had every
    wait: one left out keeps the row retrying at the last step.
    """
    attempts = table.c.attempts
    # Postgres arrays count from 1, and ``attempts`` in a SET expression is
    # the count before this failure, so ``attempts + 1`` is this failure's step.
    wait = array(list(schedule))[func.least(attempts + 1, len(schedule))]
    at = literal(now, DateTime(timezone=True))
    values: dict[str, object] = {
        "attempts": attempts + 1,
        due: at + wait * literal_column("INTERVAL '1 second'", Interval),
    }
    if lease is not None:
        values[lease] = null()
    if spent is not None:
        values[spent] = case((given_up(attempts, schedule), at), else_=null())
    return update(table).where(where).values(values)
