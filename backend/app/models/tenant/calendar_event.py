from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

from app.core import recurrence
from app.models.tenant._mixins import CreatedByMixin, HoldMixin, SoftDeleteMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.calendar import Calendar
    from app.models.platform.user_profile_view import MemberProfile


class CalendarEvent(HoldMixin, CreatedByMixin, SoftDeleteMixin, table=True):
    """Event inside a calendar (Google Calendar-like).

    Events carry no grants of their own: access derives entirely from the
    parent calendar's DAC, the same way tasks inherit project access.
    """

    __tablename__ = "calendar_events"
    __table_args__ = (
        UniqueConstraint(
            "series_id", "original_start", name="uq_calendar_events_occurrence"
        ),
    )
    _display_field = "title"

    id: Optional[int] = Field(default=None, primary_key=True)
    calendar_id: int = Field(foreign_key="calendars.id", nullable=False, index=True)
    title: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    location: Optional[str] = Field(default=None, max_length=500)
    start_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    end_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    all_day: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Whether anyone who can read the event may answer it and so join it, or
    # only those already on its list. An occurrence follows its series.
    rsvp_open: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    # RFC 5545 recurrence lines as picked (``app.core.recurrence``).
    recurrence: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    # Minutes from the start's UTC time to where the repeat was picked: whole
    # days for a rule of days, the offset for a rule of hours.
    recurrence_shift: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    # No occurrence starts after this; null when the series never ends.
    # Written from ``recurrence`` on every save (see the listener below).
    recurrence_until: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # One occurrence of a repeating event, changed on its own: the series it
    # belongs to and the start it has there. Goes with its series to the bin.
    series_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("calendar_events.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    original_start: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # What the occurrence changed; everything else follows the series.
    overridden_fields: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    calendar: Optional["Calendar"] = Relationship(back_populates="events")
    # Set on an override built before its series has an id (an import), so
    # the flush writes ``series_id``; never loaded.
    series: Optional["CalendarEvent"] = Relationship(
        sa_relationship_kwargs={"remote_side": "CalendarEvent.id", "lazy": "noload"}
    )
    creator: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(CalendarEvent.created_by) == MemberProfile.id",
            "viewonly": True,
        },
    )
    attendees: List["CalendarEventAttendee"] = Relationship(
        back_populates="calendar_event",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class RSVPStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"
    tentative = "tentative"


@event.listens_for(CalendarEvent, "before_insert")
@event.listens_for(CalendarEvent, "before_update")
def _write_recurrence_until(_mapper, _connection, row: CalendarEvent) -> None:
    row.recurrence_until = (
        recurrence.last_start(row.recurrence, row.start_at, row.recurrence_shift)
        if row.recurrence
        else None
    )


class CalendarEventAttendee(SQLModel, table=True):
    """Someone invited to a calendar event. What they answered is theirs, in
    ``calendar_event_answers``; the invitation is the event's editors'."""

    __tablename__ = "calendar_event_attendees"

    calendar_event_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("calendar_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    calendar_event: Optional[CalendarEvent] = Relationship(back_populates="attendees")
    user: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "foreign(CalendarEventAttendee.user_id) == MemberProfile.id"
            ),
            "viewonly": True,
        }
    )


class CalendarEventAnswer(SQLModel, table=True):
    """One person's answer to an event: to an event that doesn't repeat, keyed
    by the event alone, or to one occurrence of a series, keyed by the series
    and the occurrence's start there. An occurrence with a row of its own is
    still answered by its series and start, so making that row moves nothing.

    Only the person it names, an import or the system engine writes what it
    says; the event's editors may move it with the event or clear it."""

    __tablename__ = "calendar_event_answers"
    __table_args__ = (
        UniqueConstraint(
            "calendar_event_id",
            "user_id",
            "occurrence_start",
            name="uq_calendar_event_answers_key",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    calendar_event_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("calendar_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    user_id: int = Field(index=True)
    occurrence_start: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    rsvp_status: RSVPStatus = Field(
        sa_column=Column(
            SQLEnum(RSVPStatus, name="rsvp_status", create_type=True),
            nullable=False,
        ),
    )
