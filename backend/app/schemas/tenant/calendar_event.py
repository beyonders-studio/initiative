from __future__ import annotations

from datetime import datetime
from typing import Any, List, Mapping, Optional, TYPE_CHECKING

from pydantic import (
    AliasChoices,
    ConfigDict,
    Field,
    PrivateAttr,
    model_validator,
)

from app.core import recurrence
from app.core.identity_boundary import GuildId, PersonId
from app.schemas.base import MentionStr, SanitizedBaseModel, TitleStr, reject_null
from app.schemas.recurrence import EventRule, OccurrenceScope

from app.models.tenant.calendar_event import RSVPStatus
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertySummary,
    annotated_properties,
)
from app.schemas.tenant.archive import ContentCan
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import from_row
from app.schemas.platform.user import PluginPerson, PersonShape, UserPublic
from app.core.user_display import display_name

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.calendar_event import CalendarEvent


# ---------------------------------------------------------------------------
# Attendee schemas
# ---------------------------------------------------------------------------


class CalendarEventAttendeeRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    user_id: PersonId
    user: Optional[UserPublic] = None
    rsvp_status: RSVPStatus
    created_at: datetime


class CalendarEventRSVPUpdate(SanitizedBaseModel):
    rsvp_status: RSVPStatus
    #: An answer is for one event: on a repeating one, the occurrence it is
    #: for, by its start in the series. An occurrence with a row of its own is
    #: answered on that row.
    occurrence: Optional[datetime] = None


class OccurrenceRequest(SanitizedBaseModel):
    #: The occurrence, by its start in the series, or the extra start to add.
    start: datetime


# ---------------------------------------------------------------------------
# Calendar event schemas
# ---------------------------------------------------------------------------


class CalendarEventBase(SanitizedBaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[MentionStr] = None
    location: Optional[MentionStr] = Field(default=None, max_length=500)
    start_at: datetime
    end_at: datetime
    all_day: bool = False
    #: Whether anyone who can read the event may answer it and so join it.
    #: Closed, only those already on its list answer, and only someone who
    #: may edit it adds people. An occurrence follows its series.
    rsvp_open: bool = True
    recurrence: Optional[str] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "CalendarEventBase":
        if self.end_at < self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class CalendarEventCreate(CalendarEventBase, PropertiesOnCreate):
    title: TitleStr = Field(..., min_length=1, max_length=255)
    calendar_id: int
    recurrence: Optional[EventRule] = None
    #: The zone ``recurrence``'s days were picked in, and ``recurrence_shift``
    #: is taken from it; an all-day event's days are UTC dates already.
    #: Omitted, the rule's days are UTC days.
    tz: Optional[str] = Field(default=None, max_length=64)
    attendee_ids: Optional[List[PersonId]] = None
    tag_ids: Optional[List[int]] = None


class CalendarEventUpdate(PropertiesOnUpdate):
    title: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[MentionStr] = None
    location: Optional[MentionStr] = Field(default=None, max_length=500)
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    all_day: Optional[bool] = None
    rsvp_open: Optional[bool] = None
    recurrence: Optional[EventRule] = None
    #: The zone ``recurrence``'s days were picked in, and ``recurrence_shift``
    #: is taken from it; an all-day event's days are UTC dates already.
    #: Omitted, the rule's days are UTC days.
    tz: Optional[str] = Field(default=None, max_length=64)
    # Move the event to another calendar (requires write on both calendars).
    calendar_id: Optional[int] = None
    #: Replaces every tag on the event; omitted leaves them as they are.
    tag_ids: Optional[List[int]] = Field(default=None, max_length=100)
    #: For a repeating event: change one occurrence, it and every later one
    #: (a new series from there), or all of them. Omitted, the event's own row:
    #: the series, or an occurrence opened on its own.
    scope: Optional[OccurrenceScope] = None
    #: The occurrence, by its start in the series. Its new times for "all"
    #: move every occurrence by as much.
    occurrence: Optional[datetime] = None

    _required = reject_null(
        "title", "start_at", "end_at", "all_day", "rsvp_open", "calendar_id"
    )


class CalendarEventAttendeePreview(PersonShape):
    """Compact per-attendee snapshot for list responses.

    Carries the id + avatar fields the SPA needs to render tinted,
    image-backed avatars on the calendar list view. The full
    ``CalendarEventAttendeeRead`` (with RSVP status + timestamps) is
    still exposed on the detail endpoint.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    user_id: PersonId
    name: str
    avatar_url: Optional[str] = None
    #: The person ``name`` was drawn from, for an installed plug-in's response.
    _person: Optional[PluginPerson] = PrivateAttr(default=None)

    @classmethod
    def of(cls, user: Any) -> "CalendarEventAttendeePreview":
        """The preview of ``user``, an attendee's person row."""
        preview = cls(
            user_id=user.id, name=display_name(user), avatar_url=user.avatar_url
        )
        preview._person = PluginPerson.model_validate(user, from_attributes=True)
        return preview

    def plugin_person(self) -> PluginPerson:
        return self._person or PluginPerson(id=self.user_id)


class CalendarEventFields(CalendarEventBase):
    """What every read of an event carries."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    # See ``app.core.recurrence``: a rule's days are where the start moved by
    # this many minutes lands.
    recurrence_shift: int = 0
    #: The occurrence of a repeating event this is, by the start it has in the
    #: series; None for an event that does not repeat, and for the series
    #: itself.
    original_start: Optional[datetime] = None
    #: The series an occurrence with a row of its own belongs to.
    series_id: Optional[int] = None
    calendar_id: int
    # Derived from the parent calendar — kept on the summary so list views can
    # filter/group by initiative without another fetch. NULL when the parent is
    # a guild-level calendar.
    initiative_id: Optional[int] = None
    community_id: GuildId = Field(
        validation_alias=AliasChoices("community_id", "guild_id")
    )
    created_by: PersonId | None = None
    properties: List[PropertySummary] = Field(default_factory=list)
    tags: List[TagSummary] = Field(default_factory=list)
    #: What the caller may do to this event — its calendar's edit, since events
    #: hold no grants of their own.
    can: ContentCan = Field(default_factory=ContentCan)
    created_at: datetime
    updated_at: datetime


class CalendarEventSummary(CalendarEventFields):
    attendee_previews: List[CalendarEventAttendeePreview] = Field(default_factory=list)


class CalendarEventRead(CalendarEventFields):
    attendees: List[CalendarEventAttendeeRead] = Field(default_factory=list)
    #: What an occurrence changed; the rest follows its series.
    overridden_fields: List[str] = Field(default_factory=list)
    #: A series' skipped starts and extra starts.
    skipped_starts: List[datetime] = Field(default_factory=list)
    extra_starts: List[datetime] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _event_fields(
    event: "CalendarEvent", *, context: ActorContext, user_id: Optional[int]
) -> dict[str, Any]:
    """What every read of ``event`` works out rather than reads off it by name.
    Access is inherited from the parent calendar, eager-loaded with its level;
    an installed plug-in has no user id and is answered its own level, as
    ``client_access`` answers it on a calendar."""
    # Local import avoids a schema -> service import cycle.
    from app.db.guild_standing import InstallContext
    from app.services.permissions import Action, allows

    calendar = event.calendar
    reader = user_id is not None or isinstance(context, InstallContext)
    return {
        "initiative_id": calendar.initiative_id,
        "properties": annotated_properties(event),
        "tags": annotated_tags(event),
        "can": ContentCan(edit=reader and allows(calendar, Action.contribute)),
    }


def serialize_calendar_event_summary(
    event: "CalendarEvent",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
) -> CalendarEventSummary:
    return from_row(
        CalendarEventSummary,
        event,
        **_event_fields(event, context=context, user_id=user_id),
        guild_id=guild_id if guild_id is not None else context.guild_id,
        attendee_previews=[
            CalendarEventAttendeePreview.of(attendee.user)
            for attendee in event.attendees
            if attendee.user
        ],
    )


def serialize_calendar_event(
    event: "CalendarEvent",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    answers: Mapping[int, RSVPStatus],
) -> CalendarEventRead:
    """``answers`` are what was answered to the event, or to the one
    occurrence shown; someone with none is still to answer."""
    skipped, extra = (
        recurrence.exception_starts(
            event.recurrence, event.start_at, event.recurrence_shift
        )
        if event.recurrence
        else ([], [])
    )
    return from_row(
        CalendarEventRead,
        event,
        **_event_fields(event, context=context, user_id=user_id),
        guild_id=context.guild_id,
        attendees=[
            from_row(
                CalendarEventAttendeeRead,
                attendee,
                rsvp_status=answers.get(attendee.user_id, RSVPStatus.pending),
            )
            for attendee in event.attendees
        ],
        overridden_fields=list(event.overridden_fields or []),
        skipped_starts=skipped,
        extra_starts=extra,
    )
