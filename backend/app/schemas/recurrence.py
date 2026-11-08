"""Repeat rules on the wire: RFC 5545 lines as picked (``app.core.recurrence``)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from app.core import recurrence
from app.schemas.base import SanitizedBaseModel


def _task_rule(value: str) -> str:
    return recurrence.normalize(value, kind="task")


def _event_rule(value: str) -> str:
    return recurrence.normalize(value, kind="event")


_DESCRIPTION = (
    "RFC 5545 recurrence lines: one RRULE, and optional EXDATE and RDATE "
    "lines in UTC. The rule's days are as picked in the request's tz, or UTC "
    "days without one. POST /recurrence/preview lists its next starts."
)

#: Which occurrences of a repeating event or task a change is for: this one, it
#: and every later one, or the whole series.
OccurrenceScope = Literal["this", "following", "all"]


def validate_task_recurrence(
    *, rule: str | None, strategy: str, limit: int | None, due: datetime | None
) -> None:
    """Validate fields together, also after merging a PATCH with its row."""
    hourly = rule is not None and recurrence.parse(rule).rule.get("FREQ") == ["HOURLY"]
    if (hourly and (strategy != "rolling" or due is None)) or (
        limit is not None and (not hourly or strategy != "rolling")
    ):
        raise ValueError("INVALID_RECURRENCE_LIMIT")


TaskRule = Annotated[
    str,
    Field(max_length=recurrence.MAX_LENGTH, description=_DESCRIPTION),
    AfterValidator(_task_rule),
]
EventRule = Annotated[
    str,
    Field(max_length=recurrence.MAX_LENGTH, description=_DESCRIPTION),
    AfterValidator(_event_rule),
]


class RecurrencePreviewRequest(SanitizedBaseModel):
    rule: str = Field(max_length=recurrence.MAX_LENGTH)
    #: The series start: an event's start, a task's due date.
    start: datetime
    #: The zone the rule's days were picked in; UTC without one, and for an
    #: all-day event, whose days are UTC dates.
    tz: str | None = Field(default=None, max_length=64)
    kind: Literal["task", "event"]
    #: A stored rule's own shift, to preview it as it runs; without one, the
    #: shift is taken in ``tz``.
    shift: int | None = Field(default=None, ge=-1440, le=1440)
    count: int = Field(default=5, ge=1, le=20)


class RecurrencePreview(SanitizedBaseModel):
    #: The rule as it is stored.
    rule: str
    #: The shift stored beside it (``app.core.recurrence``).
    shift: int
    #: The next starts, from the series start.
    occurrences: list[datetime]
