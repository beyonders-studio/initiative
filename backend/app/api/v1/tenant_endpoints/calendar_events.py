"""Calendar event endpoints — CRUD, attendees and tags.

Events live inside a calendar and carry no grants of their own: read access is
read on the parent calendar, and every write is write on the parent calendar —
exactly the way tasks inherit project access. Sharing is managed on the
calendar (``PUT /calendars/{id}/grants``), never per event.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, List, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import recurrence
from app.services.tenant import attachments as attachments_service
from sqlmodel import select

from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    plugin_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.core.identity_boundary import PersonId
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.core.messages import CalendarEventMessages
from app.schemas.tenant.calendar_event import (
    CalendarEventCreate,
    CalendarEventUpdate,
    CalendarEventRead,
    CalendarEventRSVPUpdate,
    OccurrenceRequest,
    serialize_calendar_event,
)
from app.schemas.recurrence import OccurrenceScope
from app.schemas.tenant.ical import (
    ICalImportError,
    ICalImportProblem,
    ICalImportRequest,
    ICalImportResult,
    ICalParseRequest,
    ICalParseResult,
)
from app.api import resource_access, tool_copy
from app.core.tools import Tool
from app.services import permissions as permissions_service
from app.services.permissions import Action
from app.services.tenant import calendar_events as events_service
from app.services.tenant import calendar_occurrences as occurrences_service
from app.services.tenant import ical_service
from app.services import notifications as notifications_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service

router = APIRouter(route_class=ActorRoute)
logger = logging.getLogger(__name__)

#: The routes an installed plug-in may call. An event answers to its calendar, so
#: they name the calendars scopes.
CalendarsRead = Annotated[ActorContext, Depends(plugin_scope("calendars:read"))]
CalendarsWrite = Annotated[ActorContext, Depends(plugin_scope("calendars:write"))]


#: The widest date window a calendar read may ask for: the year view plus
#: margin for time-zone offsets.
MAX_CALENDAR_WINDOW = timedelta(days=400)


@dataclass(frozen=True)
class CalendarWindow:
    start_after: datetime
    start_before: datetime


def calendar_window(
    start_after: datetime = Query(),
    start_before: datetime = Query(),
) -> CalendarWindow:
    """The date window a calendar read covers, required and bounded.

    A bound without a zone is read as UTC. The window must not end before it
    starts, nor span more than ``MAX_CALENDAR_WINDOW``.
    """
    if start_after.tzinfo is None:
        start_after = start_after.replace(tzinfo=timezone.utc)
    if start_before.tzinfo is None:
        start_before = start_before.replace(tzinfo=timezone.utc)
    if not timedelta(0) <= start_before - start_after <= MAX_CALENDAR_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CalendarEventMessages.WINDOW_INVALID,
        )
    return CalendarWindow(start_after=start_after, start_before=start_before)


CalendarWindowDep = Annotated[CalendarWindow, Depends(calendar_window)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_writable_calendar(
    session: ActorSessionDep,
    calendar_id: int,
    user: User | None,
    guild_context: ActorContext,
) -> Calendar:
    """Load a calendar the request may write events into — the gate for
    creating or moving events into it."""
    return await resource_access.load_authorized(
        session,
        Tool.calendar,
        calendar_id,
        user,
        guild_context,
        action=Action.contribute,
    )


async def _refetch_event(session: ActorSessionDep, event_id: int) -> CalendarEvent:
    return await resource_access.reload_child(session, CalendarEvent, event_id)


async def _notify_about_event(
    session: AsyncSession,
    notification_type: NotificationType,
    user_ids: list[int | None],
    event: CalendarEvent,
    *,
    key: str,
    actor: "User | notifications_service.PluginAuthor",
    role: str,
    data: dict[str, Any] | None = None,
    values: dict[str, str] | None = None,
    at: datetime | None = None,
) -> None:
    """Tell ``user_ids`` something about ``event``, naming whoever did it in
    ``role`` (organizer, editor, …): the person, or an installed plug-in by its
    name. The time is each reader's own, and ``at`` names one occurrence."""
    name = await notifications_service.actor_name(session, actor)
    await notifications_service.notify(
        session,
        notification_type,
        user_ids,
        about=("calendar_event", cast(int, event.id)),
        key=key,
        values={
            "event": event.title,
            role: name,
            "when": lambda reader: notifications_service.event_when(event, reader, at),
            **(values or {}),
        },
        data={
            "event_id": event.id,
            "start_at": (at or event.start_at).isoformat(),
            f"{role}_name": name,
            **(data or {}),
        },
        actor=actor,
    )


async def _notify_invited(
    session: ActorSessionDep,
    event: CalendarEvent,
    user_ids: list[int],
    current_user: User | None,
    guild_context: ActorContext,
) -> None:
    """Tell each of ``user_ids`` they were invited to ``event``."""
    await _notify_about_event(
        session,
        NotificationType.event_invitation,
        list(user_ids),
        event,
        key="event.invitation",
        actor=await notifications_service.author_of(
            session, guild_context, current_user
        ),
        role="organizer",
    )


# ---------------------------------------------------------------------------
# iCal import
# ---------------------------------------------------------------------------


@router.post("/import/parse", response_model=ICalParseResult)
async def parse_ical_file(
    current_user: Annotated[User, Depends(get_current_active_user)],
    body: ICalParseRequest,
    _guild_context: GuildContextDep,
) -> ICalParseResult:
    """Parse an .ics file and return a preview of found events."""
    try:
        result = ical_service.parse_ical(body.ics_content, body.tz)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CalendarEventMessages.ICAL_PARSE_FAILED,
        )
    if result.event_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CalendarEventMessages.ICAL_NO_EVENTS,
        )
    return result


@router.post("/import", response_model=ICalImportResult)
async def import_ical_events(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    body: ICalImportRequest,
) -> ICalImportResult:
    """Import events from an .ics file into a calendar. Requires write access
    on the target calendar."""
    calendar = await _get_writable_calendar(
        session, body.calendar_id, current_user, guild_context
    )

    try:
        events, errors, skipped = ical_service.build_calendar_events(
            content=body.ics_content,
            calendar_id=calendar.id,
            guild_id=guild_context.guild_id,
            created_by=current_user.id,
            tz=body.tz,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=CalendarEventMessages.ICAL_PARSE_FAILED,
        )

    created = 0
    for event in events:
        try:
            async with session.begin_nested():
                session.add(event)
                await session.flush()
            created += 1
        except Exception:
            logger.exception("iCal import could not save event %r", event.title)
            errors.append(
                ICalImportError(problem=ICalImportProblem.not_saved, title=event.title)
            )

    if created > 0:
        await session.commit()

    return ICalImportResult(
        events_created=created,
        events_failed=len(events) - created + skipped,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def _serialized_event(
    session: AsyncSession,
    event: CalendarEvent,
    *,
    context: ActorContext,
    occurrence: datetime | None = None,
) -> CalendarEventRead:
    """``occurrence`` shows that one's answers in place of the series'."""
    return serialize_calendar_event(
        event,
        context=context,
        user_id=context.user_id,
        answers=(
            await occurrences_service.answers_for(session, event.id, occurrence)
            if occurrence is not None
            else await occurrences_service.answers_on(session, event)
        ),
    )


async def _event_committed(
    session: AsyncSession,
    event_id: int,
    *,
    context: ActorContext,
    occurrence: datetime | None = None,
) -> CalendarEventRead:
    """Commit a write, and answer with the event re-read after it."""
    await session.commit()
    return await _serialized_event(
        session,
        await _refetch_event(session, event_id),
        context=context,
        occurrence=occurrence,
    )


@router.get("/{event_id}", response_model=CalendarEventRead)
async def read_calendar_event(
    event_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsRead,
    include_deleted: IncludeDeletedDep = False,
    occurrence: Optional[datetime] = Query(
        default=None,
        description="One occurrence of a repeating event, whose answers to show.",
    ),
) -> CalendarEventRead:
    event = await resource_access.load_child(session, CalendarEvent, event_id)
    return await _serialized_event(
        session,
        event,
        context=guild_context,
        occurrence=occurrence if event.recurrence else None,
    )


@router.post("/", response_model=CalendarEventRead, status_code=status.HTTP_201_CREATED)
async def create_calendar_event(
    event_in: CalendarEventCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarEventRead:
    """Create a calendar event. Requires write access on the calendar.

    The attendees it names are invited by whoever created it: the person, or
    an installed plug-in by its name. An installed plug-in's event has no creator.
    """
    calendar = await _get_writable_calendar(
        session, event_in.calendar_id, current_user, guild_context
    )

    # An all-day event's days are UTC dates, whatever zone it was made in.
    repeat, shift = (
        recurrence.stored(
            event_in.recurrence,
            event_in.start_at,
            None if event_in.all_day else event_in.tz,
            kind="event",
        )
        if event_in.recurrence
        else (None, 0)
    )
    event = CalendarEvent(
        calendar_id=event_in.calendar_id,
        created_by=guild_context.user_id,
        title=event_in.title.strip(),
        description=event_in.description,
        location=event_in.location,
        start_at=event_in.start_at,
        end_at=event_in.end_at,
        all_day=event_in.all_day,
        rsvp_open=event_in.rsvp_open,
        recurrence=repeat,
        recurrence_shift=shift,
    )
    session.add(event)
    await session.flush()

    if event_in.attendee_ids:
        await events_service.set_event_attendees(
            session, event, event_in.attendee_ids, calendar=calendar
        )
    if event_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.EXTRA_TAG_LINKS["calendar_event"],
            guild_id=guild_context.guild_id,
            entity_id=event.id,
            tag_ids=event_in.tag_ids,
        )

    await _notify_invited(
        session, event, event_in.attendee_ids or [], current_user, guild_context
    )

    await attachments_service.claim_uploads(session, event)
    await properties_service.write_on_create(session, event, event_in.properties)
    return await _event_committed(session, event.id, context=guild_context)


@router.post(
    "/{event_id}/duplicate",
    response_model=CalendarEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_calendar_event(
    event_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
    occurrence: Optional[datetime] = Query(
        default=None,
        description="One date of a repeating event, copied as an event of its own.",
    ),
) -> CalendarEventRead:
    """Copy the event beside itself as "<title> (Copy)", with its invitees,
    who are invited to it as to a new event, its tags, links and properties. A
    repeating event comes with its occurrences changed on their own; one
    changed occurrence, or the ``occurrence`` named, is copied as an event of
    its own."""
    event = await resource_access.load_child(
        session, CalendarEvent, event_id, action=Action.contribute
    )
    copy = await tool_copy.duplicate_event(session, event, event.calendar, occurrence)
    invited = (
        await session.exec(
            select(CalendarEventAttendee.user_id).where(
                CalendarEventAttendee.calendar_event_id == copy.id
            )
        )
    ).all()
    await _notify_invited(session, copy, list(invited), current_user, guild_context)
    return await _event_committed(session, copy.id, context=guild_context)


@router.patch("/{event_id}", response_model=CalendarEventRead)
async def update_calendar_event(
    event_id: int,
    event_in: CalendarEventUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarEventRead:
    """Update a calendar event. Requires write access on the calendar (and on
    the target calendar when moving the event).

    For a repeating event, ``scope`` says which occurrences: ``this`` one
    (named by ``occurrence``) becomes a row of its own, ``following`` ends the
    series before it and starts a new one there, and ``all`` changes the
    series, its times moving every occurrence by as much as they move the one
    named. Changing an occurrence that has a row of its own changes that row,
    unless the scope says otherwise."""
    event = await resource_access.load_child(
        session, CalendarEvent, event_id, action=Action.contribute
    )
    changes = event_in.model_dump(
        exclude_unset=True, exclude={"scope", "occurrence", "tz"}
    )
    scope, at = event_in.scope, event_in.occurrence
    alone = {"recurrence", "calendar_id", "rsvp_open"}

    if event.series_id is not None:
        if scope in (None, "this"):
            if alone & set(changes):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=CalendarEventMessages.OCCURRENCE_FOLLOWS_SERIES,
                )
            return await _apply_update(
                session, event, changes, event_in, current_user, guild_context
            )
        # From this occurrence on, or every one: its series, from its start,
        # and the fields changed follow the series again here.
        occurrences_service.unmark(event, changes)
        session.add(event)
        at = event.original_start
        event = await resource_access.load_child(
            session, CalendarEvent, event.series_id, action=Action.contribute
        )

    if event.recurrence and scope == "this":
        if alone & set(changes):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=CalendarEventMessages.OCCURRENCE_FOLLOWS_SERIES,
            )
        made = await occurrences_service.occurrence(
            session, event, occurrences_service.require_occurrence(event, at)
        )
        await session.flush()
        target = await _refetch_event(session, made.id)
        return await _apply_update(
            session, target, changes, event_in, current_user, guild_context
        )

    if event.recurrence and scope == "following":
        at = occurrences_service.require_occurrence(event, at)
        if at != event.start_at.astimezone(timezone.utc):
            rest = await occurrences_service.split(session, event, at)
            event = await _refetch_event(session, rest.id)
        # The times sent are this occurrence's, which starts the new series.
        return await _apply_update(
            session, event, changes, event_in, current_user, guild_context
        )

    if event.recurrence and at is not None and {"start_at", "end_at"} & set(changes):
        # Every occurrence moves as the one named does.
        at = occurrences_service.require_occurrence(event, at)
        length = event.end_at - event.start_at
        new_start = changes.get("start_at") or at
        new_end = changes.get("end_at") or new_start + length
        changes["start_at"] = event.start_at + (new_start - at)
        changes["end_at"] = changes["start_at"] + (new_end - new_start)
    return await _apply_update(
        session, event, changes, event_in, current_user, guild_context
    )


async def _apply_update(
    session: AsyncSession,
    event: CalendarEvent,
    update_data: dict,
    event_in: CalendarEventUpdate,
    current_user: User | None,
    guild_context: ActorContext,
) -> CalendarEventRead:
    """Write ``update_data`` to one event row, and to a series' overrides
    what they follow of it."""
    # Snapshot fields that drive the "updated"/"rescheduled" notification before
    # the in-place mutation below.
    old_title = event.title
    old_rsvp_open = event.rsvp_open
    old_location = event.location
    old_all_day = event.all_day
    old_start = event.start_at
    old_end = event.end_at
    old_description = event.description
    old_shift = event.recurrence_shift
    old_recurrence = event.recurrence
    old_calendar = event.calendar_id

    updated = False

    if "calendar_id" in update_data and update_data["calendar_id"] != event.calendar_id:
        # Moving between calendars needs write on the destination too.
        destination = await _get_writable_calendar(
            session, update_data["calendar_id"], current_user, guild_context
        )
        # And the move may not cross the guild/initiative line in either
        # direction: an event carries its attendees, property values and
        # links, all of which belong to one side of it.
        if (destination.initiative_id is None) != (
            event.calendar.initiative_id is None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=CalendarEventMessages.CANNOT_CROSS_SCOPE,
            )
        await resource_access.require_may_move(session, event, destination)
        # Into another initiative, drop property values — their definitions
        # belong to the old initiative and can't resolve in the new one. The
        # series' overrides move with it, so theirs go too. Done before the
        # move, while the values still resolve.
        if destination.initiative_id != event.calendar.initiative_id:
            overrides = await occurrences_service.overrides(session, event)
            await properties_service.drop_values(
                session, "calendar_event", [e.id for e in (event, *overrides)]
            )
            # With their own values gone, the overrides follow the series'.
            for override in overrides:
                occurrences_service.unmark(override, ["properties"])
                session.add(override)
        event.calendar_id = update_data["calendar_id"]
        # Only those who can open the destination stay on the list.
        await events_service.set_event_attendees(
            session,
            event,
            [attendee.user_id for attendee in event.attendees],
            calendar=destination,
            carried=True,
        )
        updated = True

    previous_start, previous_all_day = event.start_at, event.all_day
    for field in (
        "title",
        "description",
        "location",
        "start_at",
        "end_at",
        "all_day",
        "rsvp_open",
    ):
        if field in update_data:
            value = update_data[field]
            setattr(event, field, value.strip() if field == "title" else value)
            updated = True

    # An all-day event's days are UTC dates, whatever zone it was made in.
    picked_in = "UTC" if event.all_day else event_in.tz
    if "recurrence" in update_data:
        event.recurrence, event.recurrence_shift = (
            recurrence.stored(
                update_data["recurrence"], event.start_at, picked_in, kind="event"
            )
            if update_data["recurrence"]
            else (None, 0)
        )
        if event.recurrence:
            # A rule written without skipped or extra starts keeps them.
            event.recurrence = recurrence.kept_exceptions(
                event.recurrence, old_recurrence
            )
        updated = True
    elif event.recurrence and (
        event.start_at != previous_start or event.all_day != previous_all_day
    ):
        # The repeat moves with its start, its days kept as they were picked.
        event.recurrence, event.recurrence_shift = recurrence.restarted(
            event.recurrence,
            event.recurrence_shift,
            previous_start,
            event.start_at,
            picked_in,
        )

    if update_data.get("tag_ids") is not None:
        await tags_service.set_entity_tags(
            session,
            tags_service.EXTRA_TAG_LINKS["calendar_event"],
            guild_id=guild_context.guild_id,
            entity_id=event.id,
            tag_ids=update_data["tag_ids"],
        )
        await session.flush()
        # An occurrence's own tags stay its own; a series' reach its
        # occurrences that kept the series' tags.
        await _followed(session, event, "tags")
        updated = True
    if event_in.properties is not None:
        await properties_service.write_on_update(session, event, event_in.properties)
        await session.flush()
        # The same for its properties.
        await _followed(session, event, "properties")
        updated = True

    # Validate dates after applying partial updates
    if updated:
        if event.end_at < event.start_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=CalendarEventMessages.ENDS_BEFORE_START,
            )
        event.updated_at = datetime.now(timezone.utc)
        session.add(event)
        if event.series_id is not None:
            # What this occurrence now says differently from its series.
            await occurrences_service.remark(session, event)

        time_changed = event.start_at != old_start or event.end_at != old_end
        if event.series_id is None and (old_recurrence or event.recurrence):
            # What the series' overrides follow of it.
            if (
                time_changed
                or event.all_day != old_all_day
                or event.recurrence != old_recurrence
            ):
                await occurrences_service.rehome(
                    session,
                    event,
                    old_shift=old_shift,
                    old_start=old_start,
                    deleted_by=guild_context.user_id,
                )
            changed = {
                name
                for name, before in (
                    ("title", old_title),
                    ("description", old_description),
                    ("location", old_location),
                    ("rsvp_open", old_rsvp_open),
                )
                if getattr(event, name) != before
            }
            if time_changed or event.all_day != old_all_day:
                changed |= set(occurrences_service.TIMES)
            if event.calendar_id != old_calendar:
                changed.add("attendees")
            await occurrences_service.follow(session, event, changed)

        # Notify attendees only on meaningful changes (skip pure color/tag edits).
        meaningful_change = (
            time_changed
            or event.title != old_title
            or event.location != old_location
            or event.all_day != old_all_day
        )
        if meaningful_change:
            # Skip anyone who declined — a declined attendee isn't coming, so
            # reschedules/edits are noise (mirrors the reminder pass, which
            # also skips declined RSVPs).
            answers = await occurrences_service.answers_on(session, event)
            notify_ids: list[int | None] = [
                attendee.user_id
                for attendee in event.attendees
                if answers.get(attendee.user_id) != RSVPStatus.declined
            ]
            await _notify_about_event(
                session,
                NotificationType.event_updated,
                notify_ids,
                event,
                key="event.rescheduled" if time_changed else "event.updated",
                actor=await notifications_service.author_of(
                    session, guild_context, current_user
                ),
                role="editor",
                data={"time_changed": time_changed},
            )

        # A move that writes nothing a file shows from carries the event's own.
        await attachments_service.claim_uploads(
            session,
            event,
            carried="calendar_id" in update_data
            and not attachments_service.shows_files(CalendarEvent, update_data),
        )
    session.add(event)
    return await _event_committed(session, event.id, context=guild_context)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar_event(
    event_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    scope: Optional[OccurrenceScope] = Query(default=None),
    occurrence: Optional[datetime] = Query(default=None),
) -> None:
    """Soft-delete a calendar event. Requires write access on the calendar.

    For a repeating event, ``scope`` says which occurrences: ``this`` one
    (named by ``occurrence``) is skipped, ``following`` ends the series before
    it, and ``all`` bins the series with every occurrence of it. Deleting an
    occurrence that has a row of its own skips it, unless the scope says
    otherwise."""
    from app.services.tenant.soft_delete import trash

    event = await resource_access.load_child(
        session, CalendarEvent, event_id, action=Action.contribute
    )
    # Whose attendees hear of it: an occurrence's own row's, or the event's.
    told = event
    if event.series_id is not None:
        at = event.original_start
        event = await resource_access.load_child(
            session, CalendarEvent, event.series_id, action=Action.contribute
        )
        scope = scope or "this"
    else:
        at = occurrence
    if scope in ("following", "all") and event.recurrence:
        # Everyone attending an occurrence that goes: each one's own row from
        # the one named on (every one, for all), and the series' attendees if
        # any occurrence that goes has no row of its own.
        since = (
            event.start_at
            if scope == "all" or at is None
            else at.astimezone(timezone.utc)
        )
        rows = [
            override
            for override in await occurrences_service.overrides(session, event)
            if override.original_start is not None
        ]
        told_ids = [
            override.id
            for override in rows
            if cast(datetime, override.original_start).astimezone(timezone.utc)
            >= since.astimezone(timezone.utc)
        ]
        if occurrences_service.has_plain_from(
            event, since, [cast(datetime, override.original_start) for override in rows]
        ):
            told_ids.append(event.id)
    else:
        told_ids = [told.id]
    # A declined attendee already isn't attending, so skip the cancellation
    # notice for them (consistent with update/reminder notifications).
    cancel_ids: list[int | None] = [
        user_id
        for user_id, answer in (
            await occurrences_service.attendees_of(session, told_ids)
        ).items()
        if answer != RSVPStatus.declined
    ]

    async def tell(when: datetime | None = None) -> None:
        await _notify_about_event(
            session,
            NotificationType.event_cancelled,
            cancel_ids,
            event,
            key="event.cancelled",
            actor=current_user,
            role="canceller",
            at=when,
        )

    if event.recurrence and scope == "this":
        at = occurrences_service.require_occurrence(event, at)
        await occurrences_service.skip(session, event, at, deleted_by=current_user.id)
        await tell(at)
        await session.commit()
        return
    if event.recurrence and scope == "following":
        at = occurrences_service.require_occurrence(event, at)
        if await occurrences_service.end_before(
            session, event, at, deleted_by=current_user.id
        ):
            # Named by the first occurrence that no longer happens.
            await tell(at)
            await session.commit()
            return
    await tell()
    await trash(
        session,
        event,
        deleted_by_user_id=current_user.id,
    )
    await session.commit()


async def _scoped_list_target(
    session: AsyncSession,
    event: CalendarEvent,
    field: str,
    scope: Optional[OccurrenceScope],
    at: Optional[datetime],
) -> CalendarEvent:
    """The row a list change (attendees) is written to, as an update's scope
    picks it: the occurrence's own row, a new series from it, or the series."""
    if event.series_id is not None:
        if scope in (None, "this"):
            return event
        occurrences_service.unmark(event, [field])
        session.add(event)
        at = event.original_start
        event = await resource_access.load_child(
            session, CalendarEvent, event.series_id, action=Action.contribute
        )
    if event.recurrence and scope == "this":
        target = await occurrences_service.occurrence(
            session, event, occurrences_service.require_occurrence(event, at)
        )
        return await _refetch_event(session, target.id)
    if event.recurrence and scope == "following":
        at = occurrences_service.require_occurrence(event, at)
        if at != event.start_at.astimezone(timezone.utc):
            rest = await occurrences_service.split(session, event, at)
            return await _refetch_event(session, rest.id)
    return event


async def _followed(session: AsyncSession, event: CalendarEvent, field: str) -> None:
    """After a list changed on ``event``: an occurrence's own row now holds its
    own, and a series' overrides that didn't change it follow."""
    if event.series_id is None and event.recurrence:
        event = await _refetch_event(session, event.id)
    await occurrences_service.followed(session, event, field)


async def _repeating_or_404(session: AsyncSession, event_id: int) -> CalendarEvent:
    event = await resource_access.load_child(
        session, CalendarEvent, event_id, action=Action.contribute
    )
    if not event.recurrence:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CalendarEventMessages.NOT_AN_OCCURRENCE,
        )
    return event


@router.post("/{event_id}/occurrences", response_model=CalendarEventRead)
async def open_occurrence(
    event_id: int,
    body: OccurrenceRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarEventRead:
    """The occurrence starting at ``start`` as a row of its own, made from the
    series the first time it is asked for, so it can change, carry its own
    attendees or be linked to alone. Requires write access on the calendar."""
    series = await _repeating_or_404(session, event_id)
    override = await occurrences_service.occurrence(session, series, body.start)
    return await _event_committed(session, override.id, context=guild_context)


@router.post("/{event_id}/occurrences/detach", response_model=CalendarEventRead)
async def detach_occurrence(
    event_id: int,
    body: OccurrenceRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarEventRead:
    """Copy the occurrence at ``start`` out into an event of its own, which
    the series then skips."""
    series = await _repeating_or_404(session, event_id)
    event = await occurrences_service.detach(session, series, body.start)
    return await _event_committed(session, event.id, context=guild_context)


@router.post("/{event_id}/occurrences/restore", response_model=CalendarEventRead)
async def restore_occurrence(
    event_id: int,
    body: OccurrenceRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarEventRead:
    """Bring back a skipped occurrence of the series."""
    series = await _repeating_or_404(session, event_id)
    await occurrences_service.bring_back(session, series, body.start)
    series.updated_at = datetime.now(timezone.utc)
    session.add(series)
    return await _event_committed(session, series.id, context=guild_context)


@router.post("/{event_id}/occurrences/add", response_model=CalendarEventRead)
async def add_occurrence(
    event_id: int,
    body: OccurrenceRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
) -> CalendarEventRead:
    """Give the series an extra occurrence at ``start``."""
    series = await _repeating_or_404(session, event_id)
    series.recurrence = recurrence.with_extra(
        series.recurrence or "", series.recurrence_shift, body.start
    )
    series.updated_at = datetime.now(timezone.utc)
    session.add(series)
    return await _event_committed(session, series.id, context=guild_context)


# ---------------------------------------------------------------------------
# Attendees
# ---------------------------------------------------------------------------


@router.put("/{event_id}/attendees", response_model=CalendarEventRead)
async def set_attendees(
    event_id: int,
    attendee_ids: List[PersonId],
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: CalendarsWrite,
    scope: Optional[OccurrenceScope] = Query(default=None),
    occurrence: Optional[datetime] = Query(default=None),
) -> CalendarEventRead:
    """Set attendees. Requires write access on the calendar.

    Everyone newly on the list is invited by whoever set it: the person, or an
    installed plug-in by its name. ``scope`` works as it does on an update.
    """
    event = await resource_access.load_child(
        session, CalendarEvent, event_id, action=Action.contribute
    )
    event = await _scoped_list_target(session, event, "attendees", scope, occurrence)
    old_ids = {a.user_id for a in event.attendees}
    await events_service.set_event_attendees(
        session, event, attendee_ids, calendar=event.calendar
    )

    await _notify_invited(
        session, event, list(set(attendee_ids) - old_ids), current_user, guild_context
    )
    await session.flush()
    await _followed(session, event, "attendees")
    return await _event_committed(session, event.id, context=guild_context)


@router.patch("/{event_id}/rsvp", response_model=CalendarEventRead)
async def update_rsvp(
    event_id: int,
    rsvp_in: CalendarEventRSVPUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> CalendarEventRead:
    """Update the current user's RSVP status. Read access on the calendar
    suffices — RSVPing is answering an invitation, not editing the event.

    On an event whose RSVP is open, answering puts the reader on its list.
    Closed, only someone already on it answers, besides those who may edit
    the event. An occurrence's own row carries its series' setting.

    An answer is for one event: a repeating event is answered one occurrence
    at a time, named by ``occurrence``."""
    event = await resource_access.load_child(session, CalendarEvent, event_id)
    answer = rsvp_in.rsvp_status
    join = event.rsvp_open or permissions_service.allows(
        event.calendar, Action.contribute
    )
    if event.recurrence:
        await occurrences_service.answer_occurrence(
            session, event, rsvp_in.occurrence, current_user.id, answer, join=join
        )
    else:
        await occurrences_service.answer_on(
            session, event, current_user.id, answer, join=join
        )

    await _notify_about_event(
        session,
        NotificationType.event_rsvp,
        [event.created_by],
        event,
        key="event.rsvp",
        actor=current_user,
        role="responder",
        data={"rsvp_status": RSVPStatus(rsvp_in.rsvp_status).value},
        values={"status": RSVPStatus(rsvp_in.rsvp_status).value},
    )

    return await _event_committed(
        session,
        event.id,
        context=guild_context,
        occurrence=rsvp_in.occurrence if event.recurrence else None,
    )
