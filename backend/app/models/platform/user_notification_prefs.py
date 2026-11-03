"""What one account wants to be told about, and how.

One row per account, holding a sparse settings document. Deliberately not
columns on ``public.users``: that table is read whole by the platform tiers, and
what somebody has chosen to hear about is their own business — the same
reasoning that keeps ``user_dm_settings`` off it.

Sparse means a key exists only where a default has been overridden, so an
account that has never opened the settings page stores ``{}`` and still gets
every default from ``app.core.notification_categories``. A community joined
tomorrow needs no write.

Shape::

    {
      "categories": {"comments": {"in_app": false, "email": false}},
      "quiet_hours": {"start": "22:00", "end": "07:00"},
      "guilds": {
        "7": {"level": "personal", "categories": {"reactions": {"push": false}}}
      },
      "email": {"cadence": "daily", "at": "08:00", "weekday": 1,
                "personal_instant": true},
      "pause": {"since": "2026-09-19T17:00:00+00:00",
                "until": "2026-10-03T07:00:00+00:00"},
      "away": {"respect": true},
      "digests": {"overdue": {"cadence": "daily", "at": "18:00", "weekday": 1}}
    }

A document rather than a row per setting: fifteen categories times three
channels is a fixed grid the registry already enumerates, and resolving one
value is then a dict lookup on a row the fan-out has already loaded rather than
a query per recipient.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class EmailCadence(str, Enum):
    """How often email is allowed to arrive.

    One value for the whole account rather than one per category: the category
    grid says *whether* something is worth an email and the community dial says
    how much a community may say, so a third per-category axis would be a
    fifteen-row schedule nobody would fill in. This says when the account reads
    its mail, which is one fact about a person.

    There is deliberately no ``never``. Two controls already switch email off,
    and standing down for a while is a pause, which has an end date.
    """

    #: As it happens. The default, and what every account had before this
    #: existed.
    instant = "instant"
    #: At most one message an hour, on the hour. Fixed boundaries rather than a
    #: rolling window, so the next one is knowable without reading when the
    #: last went.
    hourly = "hourly"
    #: One message a day, at a chosen time in the account's own timezone.
    daily = "daily"
    #: One message a week, on a chosen day and time.
    weekly = "weekly"


class DigestCadence(str, Enum):
    """How often one digest goes out. Each digest keeps its own, apart from
    the email's: a summary is read at a time of day, which is not when the
    rest of the mail arrives."""

    daily = "daily"
    weekly = "weekly"


class UserNotificationPrefs(SQLModel, table=True):
    __tablename__ = "user_notification_prefs"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    prefs: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
