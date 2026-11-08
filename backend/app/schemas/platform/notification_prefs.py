"""What the settings page reads and writes.

The registry travels with the response, so the page renders whatever categories
this build has rather than carrying its own copy of the list. Adding a category
is then one entry in ``app.core.notification_categories`` and four locale files.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from app.core.notification_categories import (
    CategoryGroup,
    Channel,
    NotificationCategory,
)
from app.models.platform.user_notification_prefs import DigestCadence, EmailCadence
from app.services.platform.notification_prefs import (
    DEFAULT_DIGEST_CLOCK,
    DEFAULT_DIGEST_WEEKDAY,
    MAX_PAUSE_DAYS,
)
from app.schemas.base import SanitizedBaseModel


def _valid_clock(value: str) -> str:
    hour, _, minute = value.partition(":")
    if not (hour.isdigit() and minute.isdigit()):
        raise ValueError("expected HH:MM")
    if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
        raise ValueError("expected HH:MM")
    return f"{int(hour):02d}:{int(minute):02d}"


class QuietHours(SanitizedBaseModel):
    """A nightly window, in the account's own timezone. Wraps midnight."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _clock(cls, value: str) -> str:
        return _valid_clock(value)


class EmailSchedule(SanitizedBaseModel):
    """When this account reads its mail."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    cadence: EmailCadence = EmailCadence.instant
    #: HH:MM in the account's own timezone, for the daily and weekly slots.
    at: str = DEFAULT_DIGEST_CLOCK
    #: ISO weekday, Monday is 1.
    weekday: int = Field(default=DEFAULT_DIGEST_WEEKDAY, ge=1, le=7)
    #: Whether what another person addressed to this account skips the queue.
    personal_instant: bool = True

    @field_validator("at")
    @classmethod
    def _clock(cls, value: str) -> str:
        return _valid_clock(value)


class DigestSchedule(SanitizedBaseModel):
    """When one digest goes out."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    cadence: DigestCadence = DigestCadence.daily
    #: HH:MM in the account's own timezone.
    at: str
    #: ISO weekday, Monday is 1, for a weekly digest.
    weekday: int = Field(default=DEFAULT_DIGEST_WEEKDAY, ge=1, le=7)

    @field_validator("at")
    @classmethod
    def _clock(cls, value: str) -> str:
        return _valid_clock(value)


class PauseRead(SanitizedBaseModel):
    """A stand-down in force, as the settings page shows it."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    since: datetime
    until: datetime


class NotificationCategoryRead(SanitizedBaseModel):
    """One row of the settings grid, described by the backend."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    category: NotificationCategory
    group: CategoryGroup
    #: Addressed to this account by another person: what email sends straight
    #: away, and what the inbox's Mentions filter shows.
    personal: bool
    #: Whether muting a community reaches it.
    community_scoped: bool = Field(
        validation_alias=AliasChoices("community_scoped", "guild_scoped")
    )
    #: Whether each community can switch this row off on its own.
    per_community: bool
    #: Channels the account may switch off. A channel absent from this renders
    #: as on and disabled; a row with none is not shown.
    mutable_channels: list[Channel]
    defaults: dict[Channel, bool]


class CommunityNotificationSettings(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    community_name: str = Field(
        validation_alias=AliasChoices("community_name", "guild_name")
    )
    #: Nothing from this community at all, a direct mention included.
    muted: bool = False
    #: The rows switched off in this community only, on every channel.
    off: list[NotificationCategory] = Field(default_factory=list)


class NotificationPreferencesRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The registry, so the page has no list of its own.
    categories: list[NotificationCategoryRead]
    #: Account-wide overrides. Sparse — absent means the registry default.
    settings: dict[str, dict[str, bool]] = Field(default_factory=dict)
    quiet_hours: Optional[QuietHours] = None
    #: When email goes out. Always present — an account that has chosen nothing
    #: reads its own defaults here rather than the page carrying a copy.
    email: EmailSchedule = Field(default_factory=EmailSchedule)
    #: When each digest goes out, for every digest category. Always present,
    #: for the same reason ``email`` is.
    digests: dict[NotificationCategory, DigestSchedule] = Field(default_factory=dict)
    #: The stand-down in force, or None. A lapsed one reads as None.
    pause: Optional[PauseRead] = None
    #: Whether to hold off while the account is plainly already looking.
    respect_presence: bool = True
    communities: list[CommunityNotificationSettings] = Field(
        default_factory=list, validation_alias=AliasChoices("communities", "guilds")
    )


class NotificationChannelSet(SanitizedBaseModel):
    """One switch being moved, for the whole account."""

    category: NotificationCategory
    channel: Channel
    enabled: bool


class CommunityRowSet(SanitizedBaseModel):
    """One row switched on or off in one community, on every channel."""

    community_id: int
    category: NotificationCategory
    enabled: bool


class CommunityMuteSet(SanitizedBaseModel):
    community_id: int
    muted: bool


class NotificationPreferencesUpdate(SanitizedBaseModel):
    """A partial write: only what moved.

    Whole-document writes would make two open settings tabs clobber each other,
    and a single switch is what the page actually sends.
    """

    channels: list[NotificationChannelSet] = Field(default_factory=list)
    rows: list[CommunityRowSet] = Field(default_factory=list)
    mutes: list[CommunityMuteSet] = Field(default_factory=list)
    quiet_hours: Optional[QuietHours] = None
    #: Explicit, because ``quiet_hours: null`` is indistinguishable from
    #: "not mentioned" in a partial write.
    clear_quiet_hours: bool = False
    email: Optional[EmailSchedule] = None
    #: Digests whose schedule moved, each stored whole.
    digests: dict[NotificationCategory, DigestSchedule] = Field(default_factory=dict)
    #: When a stand-down begins. Omitted means now, which is the ordinary case;
    #: a date is how somebody books next week's holiday before they go.
    pause_from: Optional[datetime] = None
    #: When it ends. Every pause has one: permanent silence is what the
    #: category grid and the community mute are for, and both are visible on
    #: the page that owns them.
    pause_until: Optional[datetime] = None
    #: Explicit, for the same reason ``clear_quiet_hours`` is. This is what
    #: "Resume" sends, and it releases everything the pause was holding.
    clear_pause: bool = False
    respect_presence: Optional[bool] = None

    @field_validator("pause_from", "pause_until")
    @classmethod
    def _aware(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @model_validator(mode="after")
    def _a_real_window(self) -> "NotificationPreferencesUpdate":
        if self.pause_until is None:
            if self.pause_from is not None:
                raise ValueError("a pause needs an end date")
            return self
        now = datetime.now(timezone.utc)
        start = self.pause_from or now
        if self.pause_until <= start:
            raise ValueError("a pause must end after it begins")
        if self.pause_until <= now:
            raise ValueError("a pause must end in the future")
        if self.pause_until - now > timedelta(days=MAX_PAUSE_DAYS):
            raise ValueError(f"a pause may not run beyond {MAX_PAUSE_DAYS} days")
        return self
