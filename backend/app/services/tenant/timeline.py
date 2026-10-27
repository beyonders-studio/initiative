"""Grouping a tool's rows into the periods a timeline rail scrolls.

One aggregate, written once, taking the two things that differ per tool: the
expression that dates a row, and the conditions that decide which rows this
reader may count. Everything else — the month truncation, the reader's own time
zone, the order, the anchor a jump lands on — is the same question whatever the
rows are.

The conditions are the caller's because they are the part that must not be
shared. A board's rows are gated by sharing and publication, a calendar's by
something else; passing them in means each tool answers for its own rows
through its own gates, and this never becomes a route that can see across
tools.
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Date, DateTime, cast, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.user_input_validators import resolve_zone
from app.schemas.tenant.timeline import TimelineBucket


async def month_buckets(
    session: AsyncSession,
    *,
    date_expr: Any,
    conditions: Sequence[Any],
    tz: str | None = None,
) -> list[TimelineBucket]:
    """Rows grouped by the month they fall in, newest month first.

    ``date_expr`` is whatever dates a row for this tool — a board uses the same
    ``board_time()`` its feed is ordered by, so the rail and the feed cannot
    disagree about which month a notice is in.

    The month boundary is cut in ``tz``, bound as a parameter rather than
    written into the SQL: a month is a boundary in somebody's day, and a reader
    in Auckland should not find a notice they posted this morning filed under
    last month. A request that names no zone, or a zone that is not one, gets
    UTC.

    ``anchor`` is the newest instant in each month rather than the month's own
    end, and ``anchor_oldest`` the oldest. They are what a jump asks for, and
    taking them from the data means the client never has to work out when a
    month begins or ends somewhere else — nor which of the two a list reads
    from, which is a question about that list's own direction.

    A row dated by a day (a ``date`` column) is in that day's month wherever
    it is read, so ``tz`` does not apply; its anchors are the day's start in
    UTC.
    """
    if isinstance(date_expr.type, Date):
        month = func.date_trunc("month", date_expr)
        newest = func.timezone("UTC", cast(func.max(date_expr), DateTime))
        oldest = func.timezone("UTC", cast(func.min(date_expr), DateTime))
    else:
        zone = resolve_zone(tz).key
        # ``timezone(zone, ts)`` renders the instant as local wall time, which
        # is what a month boundary is drawn against.
        month = func.date_trunc("month", func.timezone(zone, date_expr))
        newest, oldest = func.max(date_expr), func.min(date_expr)

    rows = (
        await session.exec(
            select(
                func.to_char(month, "YYYY-MM").label("period"),
                func.count().label("count"),
                newest.label("anchor"),
                oldest.label("anchor_oldest"),
            )
            .where(*conditions)
            .group_by(month)
            .order_by(month.desc())
        )
    ).all()

    return [
        TimelineBucket(
            period=period, count=count, anchor=anchor, anchor_oldest=anchor_oldest
        )
        for period, count, anchor, anchor_oldest in rows
    ]
