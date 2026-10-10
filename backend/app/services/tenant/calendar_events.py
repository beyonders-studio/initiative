"""Calendar event service layer — the loader, the queries every event read
shares, and attendees.

Events hold no grants of their own: access derives from the parent calendar's
DAC (``resource_type='calendar'``), the way tasks inherit project access. The
loaders here eager-load the parent calendar with what the permission engine
needs.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, time, timedelta, timezone
from typing import Any, List, Optional

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, and_, exists, or_
from sqlalchemy import delete as sa_delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import aliased, selectinload
from sqlmodel import select

from app.core import recurrence
from app.core.messages import CalendarEventMessages
from app.core.user_input_validators import resolve_zone
from app.db.guild_standing import GuildContext
from app.db.session import require_guild_context
from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAnswer,
    CalendarEventAttendee,
)
from app.core.tools import Tool
from app.schemas.tenant.calendar_event import (
    CalendarEventSummary,
    serialize_calendar_event_summary,
)
from app.services import permissions as permissions_service
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.services.tenant import calendar_occurrences as occurrences_service
from app.services.tenant import named_people
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant.tool_listing import initiative_switch_clause


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def event_loader_options() -> tuple:
    """Eager-load what serializing an event reads — its attendees, and its
    calendar with the grants and level its ``can`` needs — so serialization
    never triggers an async lazy-load."""
    return (
        selectinload(CalendarEvent.attendees).selectinload(CalendarEventAttendee.user),
        selectinload(CalendarEvent.calendar).selectinload(Calendar.grants),
        selectinload(CalendarEvent.calendar).selectinload(Calendar.initiative),
        selectinload(CalendarEvent.calendar).undefer(Calendar.actions),
    )


async def get_event(
    session: AsyncSession,
    event_id: int,
    *,
    populate_existing: bool = False,
) -> CalendarEvent | None:
    """Fetch a calendar event with all relationships loaded."""
    stmt = (
        select(CalendarEvent)
        .where(CalendarEvent.id == event_id)
        .options(*event_loader_options())
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    event = result.one_or_none()
    if event is not None:
        await tags_service.annotate_tags(session, [event])
        await properties_service.annotate_properties(session, [event])
    return event


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------


#: How far a window's bound moves inward to find its day without a zone.
_NO_ZONE_INWARD = timedelta(hours=12)


def _window_day(bound: datetime, inward: timedelta, tz: Optional[str]) -> datetime:
    """The day a window's bound falls on, as the UTC midnight all-day events
    are stored at.

    A calendar asks from its first day's midnight to its last day's 23:59:59,
    in ``tz``, the viewer's zone. Without one, those days are the UTC dates of
    the bounds moved twelve hours inward, which holds within twelve hours of
    UTC."""
    local = bound.astimezone(resolve_zone(tz)) if tz else bound + inward
    return datetime.combine(local.date(), time(), timezone.utc)


def starts_in_window(
    start_after: Optional[datetime],
    start_before: Optional[datetime],
    tz: Optional[str] = None,
) -> list[ColumnElement[bool]]:
    """An event starts in the window: a timed one by its instant, an all-day
    one by its date, a UTC date the same for every viewer (``_window_day``).
    A repeating event may, when it began by the window's end and has not ended
    before its start; ``occurrences`` says when."""
    once: list[ColumnElement[bool]] = [CalendarEvent.recurrence.is_(None)]
    repeating: list[ColumnElement[bool]] = [CalendarEvent.recurrence.isnot(None)]
    if start_after is not None:
        first = _window_day(start_after, _NO_ZONE_INWARD, tz)
        once.append(
            or_(
                and_(
                    CalendarEvent.all_day.is_(False),
                    CalendarEvent.start_at >= start_after,
                ),
                and_(CalendarEvent.all_day.is_(True), CalendarEvent.start_at >= first),
            )
        )
        repeating.append(
            or_(
                CalendarEvent.recurrence_until.is_(None),
                and_(
                    CalendarEvent.all_day.is_(False),
                    CalendarEvent.recurrence_until >= start_after,
                ),
                and_(
                    CalendarEvent.all_day.is_(True),
                    CalendarEvent.recurrence_until >= first,
                ),
            )
        )
    if start_before is not None:
        last = _window_day(start_before, -_NO_ZONE_INWARD, tz)
        before = or_(
            and_(
                CalendarEvent.all_day.is_(False),
                CalendarEvent.start_at <= start_before,
            ),
            and_(CalendarEvent.all_day.is_(True), CalendarEvent.start_at <= last),
        )
        once.append(before)
        repeating.append(before)
    if len(once) == 1:
        return []
    return [or_(and_(*once), and_(*repeating))]


def series_in_window(
    start_after: Optional[datetime],
    start_before: Optional[datetime],
    tz: Optional[str] = None,
) -> list[ColumnElement[bool]]:
    """:func:`starts_in_window`, for an export: a repeating event travels
    whole, so its changed occurrences come with it wherever they now fall."""
    window = starts_in_window(start_after, start_before, tz)
    if not window:
        return []
    series = select(CalendarEvent.id).where(*window).correlate(None)
    return [or_(*window, CalendarEvent.series_id.in_(series))]


def occurrences(
    events: Sequence[CalendarEventSummary],
    start_after: datetime,
    start_before: datetime,
    tz: Optional[str] = None,
    changed: Mapping[int, set[datetime]] | None = None,
    budget: int = recurrence.MAX_EXPANDED,
) -> list[CalendarEventSummary]:
    """The events starting in the window, a repeating one once for each of
    its occurrences there, ordered by start.

    An occurrence is the series' summary at that start, with the series'
    length, and ``original_start`` naming it. One with a row of its own
    (``changed``, by series id) is left out: the row stands in for it.

    A window whose repeats hold more than ``budget`` occurrences is refused,
    for a shorter one."""
    first = _window_day(start_after, _NO_ZONE_INWARD, tz)
    last = _window_day(start_before, -_NO_ZONE_INWARD, tz)
    found: list[CalendarEventSummary] = []
    expanded = 0
    for event in events:
        if not event.recurrence:
            found.append(event)
            continue
        lower, upper = (first, last) if event.all_day else (start_after, start_before)
        try:
            starts = recurrence.between(
                event.recurrence,
                event.start_at,
                event.recurrence_shift,
                lower,
                upper,
                at_most=budget - expanded + 1,
            )
        except ValueError:
            # Unreadable, so drawn once, where it starts.
            found.append(event)
            continue
        expanded += len(starts)
        if expanded > budget:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=CalendarEventMessages.WINDOW_TOO_FULL,
            )
        length = event.end_at - event.start_at
        own = (changed or {}).get(event.id, set())
        found.extend(
            event.model_copy(
                update={
                    "start_at": start,
                    "end_at": start + length,
                    "original_start": start,
                }
            )
            for start in starts
            if start not in own
        )
    found.sort(key=lambda event: (event.start_at, event.community_id, event.id))
    return found


# ---------------------------------------------------------------------------
# Event queries
# ---------------------------------------------------------------------------


async def _exec_events(session, stmt) -> list[CalendarEvent]:
    """Run a CalendarEvent select, de-duplicate, and carry each row's tags.

    Every select of events goes through here, so this is the one place that
    has to remember them — and it costs the page two queries, not one per row.
    """
    result = await session.exec(stmt)
    events = list(result.unique().all())
    await tags_service.annotate_tags(session, events)
    await properties_service.annotate_properties(session, events)
    return events


async def guild_calendar_event_conditions(
    session: AsyncSession,
    current_user: User,
    guild_context: GuildContext,
    *,
    initiative_id: Optional[int] = None,
    guild_scope: bool = False,
    calendar_ids: Optional[List[int]] = None,
    exclude_calendar_ids: Optional[List[int]] = None,
    start_after: Optional[datetime] = None,
    start_before: Optional[datetime] = None,
    tz: Optional[str] = None,
    property_filters: Optional[str] = None,
    whole_series: bool = False,
) -> list:
    """The WHERE every guild calendar-event read shares: the ``calendar-entries``
    aggregate fetches by it and the calendar export fetches and counts by it,
    so access is identical. The guild scope, feature gate, window, property
    filters and the sharing gate.

    ``whole_series`` is an export's window (:func:`series_in_window`).

    ``guild_scope`` narrows to the guild's own calendars — the ones belonging to
    no initiative. It is the calendar plug-in's whole surface, and stating it here
    is what keeps that surface from having to name its calendars one by one: a
    list of ids is a page of them, and events on whatever fell off the end would
    simply not be drawn.
    """
    if guild_scope:
        calendars = Calendar.initiative_id.is_(None)
    else:
        # Every calendar whose tool is on, guild calendars among them. Narrowed
        # to one initiative they are excluded: a guild calendar belongs to no
        # initiative, so its events never appear in an initiative's view.
        calendars = initiative_switch_clause(
            Tool.calendar, Calendar, guild_level_rows=True
        )
        if initiative_id is not None:
            calendars = and_(calendars, Calendar.initiative_id == initiative_id)
    conditions: list = [
        CalendarEvent.calendar_id.in_(select(Calendar.id).where(calendars))
    ]

    if calendar_ids:
        conditions.append(CalendarEvent.calendar_id.in_(tuple(set(calendar_ids))))
    if exclude_calendar_ids:
        conditions.append(
            CalendarEvent.calendar_id.not_in(tuple(set(exclude_calendar_ids)))
        )

    window = series_in_window if whole_series else starts_in_window
    conditions += window(start_after, start_before, tz)

    conditions += await properties_service.property_filter_clauses(
        session, "calendar_event", property_filters, names_people=True
    )

    # An event is reached through its calendar, so the sharing gate applies to
    # the calendar the event names.
    conditions.append(
        permissions_service.listing_scope_clause(
            Tool.calendar,
            CalendarEvent.calendar_id,
            current_user.id,
            context=guild_context,
            initiative_id=initiative_id,
        )
    )

    return conditions


async def query_guild_calendar_events(
    session: AsyncSession,
    current_user: User,
    guild_context: GuildContext,
    **filters: Any,
) -> list[CalendarEvent]:
    """Every event :func:`guild_calendar_event_conditions` admits, by start."""
    conditions = await guild_calendar_event_conditions(
        session, current_user, guild_context, **filters
    )
    return await _exec_events(
        session,
        select(CalendarEvent)
        .where(*conditions)
        .options(*event_loader_options())
        .order_by(CalendarEvent.start_at.asc(), CalendarEvent.id.asc()),
    )


async def query_my_calendar_events(
    session: AsyncSession,
    current_user: User,
    *,
    guild_ids: Optional[List[int]] = None,
    start_after: datetime,
    start_before: datetime,
    tz: Optional[str] = None,
) -> list[CalendarEventSummary]:
    """Shared cross-guild calendar-event query for the ``/me/calendar-entries``
    aggregate: each repeating event is expanded into its occurrences in the
    window (``occurrences``), inside the guild whose rows say which have one of
    their own.

    Schema-per-guild: events live in per-guild schemas, so no single query can
    span guilds. Visit each of the user's
    guild schemas (routed to the user's own RLS context, so guild isolation +
    DAC still hold) and merge, sorted by ``(start_at, guild_id, id)``. Each
    event is serialized inside the guild it was read from, so the summary
    carries that guild and the level the reader holds there. The guilds share
    one ``recurrence.MAX_EXPANDED`` budget of occurrences.
    """
    budget = recurrence.MAX_EXPANDED

    async def _fetch(guild_session, guild_id):  # type: ignore[no-untyped-def]
        nonlocal budget
        context = require_guild_context(guild_session)
        # Guild calendars included: this is the user's own calendar view, one of
        # the two places their events show (the plug-in's page is the other).
        # The sharing gate is the per-guild list's, read from the standing the
        # gather established for this guild.
        stmt = (
            select(CalendarEvent)
            .join(Calendar, Calendar.id == CalendarEvent.calendar_id)
            .where(
                initiative_switch_clause(
                    Tool.calendar, Calendar, guild_level_rows=True
                ),
                *starts_in_window(start_after, start_before, tz),
                permissions_service.granted_scope_clause(
                    Tool.calendar,
                    CalendarEvent.calendar_id,
                    current_user.id,
                    context=context,
                ),
            )
            .options(*event_loader_options())
        )
        # Serialized here, while the session is still routed into THIS guild:
        # the summary names the guild and computes the reader's level from the
        # role held there, and both would read the last guild visited if it
        # waited for the merge.
        events = await _exec_events(guild_session, stmt)
        summaries = [
            serialize_calendar_event_summary(
                event, context=context, user_id=current_user.id, guild_id=guild_id
            )
            for event in events
        ]
        found = occurrences(
            summaries,
            start_after,
            start_before,
            tz,
            await occurrences_service.changed_starts(
                guild_session, [e.id for e in events if e.recurrence]
            ),
            budget,
        )
        budget -= sum(1 for event in found if event.recurrence)
        return found

    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )
    events = await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    # Merge-sort across guilds (per-schema SQL can't order across schemas).
    events.sort(key=lambda e: (e.start_at, e.community_id, e.id))
    return events


# ---------------------------------------------------------------------------
# Attendee helpers
# ---------------------------------------------------------------------------


def _answers_given_to(event: CalendarEvent) -> ColumnElement[bool]:
    """The answers kept for ``event``: an occurrence's own, or a series'
    except where an occurrence's own row still lists the person."""
    event_id, start = occurrences_service.answer_key(event)
    if start is not None:
        return and_(
            CalendarEventAnswer.calendar_event_id == event_id,
            CalendarEventAnswer.occurrence_start == start,
        )
    own = aliased(CalendarEvent)
    return and_(
        CalendarEventAnswer.calendar_event_id == event_id,
        ~exists().where(
            own.series_id == event_id,
            own.original_start == CalendarEventAnswer.occurrence_start,
            CalendarEventAttendee.calendar_event_id == own.id,
            CalendarEventAttendee.user_id == CalendarEventAnswer.user_id,
        ),
    )


async def set_event_attendees(
    session: AsyncSession,
    event: CalendarEvent,
    user_ids: list[int],
    *,
    calendar: Calendar,
    carried: bool = False,
) -> None:
    """Make ``user_ids`` the event's attendees.

    Everyone named must be able to open ``calendar``; ``carried`` is the
    existing list following the event somewhere new, which keeps those who
    still can rather than refusing. Someone already attending keeps their
    answer, and someone taken off the list takes theirs with them: an
    occurrence's, or a series' every one but those whose own row still lists
    them.
    """
    wanted = list(dict.fromkeys(user_ids))
    governing = named_people.Governing.of(Tool.calendar, calendar)
    if carried:
        keep = await named_people.readers(session, governing, wanted)
        wanted = [user_id for user_id in wanted if user_id in keep]
    else:
        await named_people.require_readers(session, governing, wanted)

    removed = (
        await session.exec(
            sa_delete(CalendarEventAttendee)
            .where(
                CalendarEventAttendee.calendar_event_id == event.id,
                CalendarEventAttendee.user_id.not_in(wanted),
            )
            .returning(CalendarEventAttendee.user_id)
        )
    ).all()
    if removed:
        await session.exec(
            sa_delete(CalendarEventAnswer).where(
                CalendarEventAnswer.user_id.in_([user_id for (user_id,) in removed]),
                _answers_given_to(event),
            )
        )
    if wanted:
        now = datetime.now(timezone.utc)
        await session.exec(
            pg_insert(CalendarEventAttendee)
            .values(
                [
                    {
                        "calendar_event_id": event.id,
                        "user_id": user_id,
                        "created_at": now,
                    }
                    for user_id in wanted
                ]
            )
            .on_conflict_do_nothing(index_elements=["calendar_event_id", "user_id"])
        )
