from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel


class EventReminderDispatch(SQLModel, table=True):
    """Dedup ledger for scheduled calendar-event reminders.

    Background-only (written by the event-reminder sweep via the admin
    session, never exposed through the API, so no RLS policy is needed —
    same stance as ``BatchedNotice``). The unique key includes
    ``event_start_at`` so rescheduling an event to a new time re-arms its
    reminder rather than being suppressed by an earlier dispatch.
    """

    __tablename__ = "event_reminder_dispatches"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "user_id",
            "event_start_at",
            name="uq_event_reminder_dispatch",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("calendar_events.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
    )
    event_start_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    sent_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
