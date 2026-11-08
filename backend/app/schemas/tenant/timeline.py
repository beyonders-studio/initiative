"""The shape a tool's history takes when it is drawn as a timeline.

Deliberately not the post schema's. A timeline is a rail of periods with a
count and a place to jump to, and nothing about that is a notice — a
calendar's months and a project's activity could each hand back this same
list. What is NOT shared is the query behind it: every tool scopes its own
rows through its own gates, and a generic "give me any tool's dates" endpoint
would be one place to get that wrong for all of them at once.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field

from app.schemas.base import SanitizedBaseModel


class TimelineBucket(SanitizedBaseModel):
    """One period on the rail."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The period, as ``YYYY-MM``. A string rather than a date because it names
    #: a month, not a day in one, and the client groups and labels by it.
    period: str
    #: How many rows fall in it — what gives the rail its sense of density, so
    #: a busy month reads differently from a quiet one.
    count: int
    #: The newest instant in the period, and the oldest. Between them they are
    #: what a jump anchors on, and which one it uses is the direction the list
    #: is read in: a list newest-first asks for "at or before ``anchor``" and
    #: walks back, one oldest-first asks for "at or after ``anchor_oldest``"
    #: and walks forward. Either way the period's own first row lands at the
    #: top, and the client never has to work out where a month ends in the
    #: reader's time zone.
    #:
    #: A list that only reads one way (a board) uses only its own end.
    anchor: datetime
    anchor_oldest: datetime


class TimelineResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Newest period first, matching the order of the feed the rail scrolls.
    buckets: list[TimelineBucket] = Field(default_factory=list)
