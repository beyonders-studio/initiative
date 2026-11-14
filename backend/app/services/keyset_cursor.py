"""Cursors for lists read newest first, a page at a time.

A cursor is ``<iso8601>|<id>``: the sort key of the last row of the page before.
The id breaks ties, so two rows written in the same instant cannot hide each
other at a page boundary. The next page is the rows whose
``(created_at, id)`` sorts below it.
"""

from datetime import datetime


def encode(created_at: datetime, row_id: int) -> str:
    return f"{created_at.isoformat()}|{row_id}"


def decode(cursor: str | None) -> tuple[datetime, int] | None:
    """Where the previous page ended, or None to start at the top.

    A cursor that does not parse is treated as no cursor: a malformed one
    should start the list again, not fail it.
    """
    if not cursor:
        return None
    stamp, _, raw_id = cursor.partition("|")
    try:
        return datetime.fromisoformat(stamp), int(raw_id)
    except ValueError, TypeError:
        return None
