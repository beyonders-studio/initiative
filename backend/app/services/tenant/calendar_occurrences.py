"""One occurrence of a repeating event, changed on its own.

An override is an ordinary event row in its series' calendar, naming the series
(``series_id``) and the start it has there (``original_start``). It is made the
first time an occurrence changes alone, from the series as it stands: its
fields, attendees and their answers, tags and properties. What it changed is
listed in ``overridden_fields``; everything else follows the series, so a
change to the series is written to its overrides too (``follow``).

Skipped and extra starts are the series' ``EXDATE`` and ``RDATE`` lines. A
split ("this and following") ends the series before an occurrence and starts a
new one there, and the overrides from that occurrence on move with it.

An answer is for one event, so a repeating one is answered an occurrence at a
time. Every answer lives in ``calendar_event_answers``, keyed by the event, or
for an occurrence by its series and its start there (``answer_key``), whether
or not it has a row of its own. Only the person it names writes what it says;
moving an event moves its answers, which its editors may do.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import (
    ColumnElement,
    delete as sa_delete,
    exists,
    func,
    update as sa_update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.messages import CalendarEventMessages
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAnswer,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.services.tenant import calendar_events as events_service
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service

#: What an occurrence can change alone, as ``overridden_fields`` names it.
SCALARS = ("title", "description", "location")
TIMES = ("start_at", "end_at", "all_day")
LISTS = ("attendees", "tags", "properties")

_TAGS = tags_service.EXTRA_TAG_LINKS["calendar_event"]


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def mark(override: CalendarEvent, fields: Iterable[str]) -> None:
    """Record that the override changed ``fields`` (a time is all three)."""
    changed = set(override.overridden_fields) | set(fields)
    if changed & set(TIMES):
        changed |= set(TIMES)
    override.overridden_fields = sorted(changed)


def unmark(override: CalendarEvent, fields: Iterable[str]) -> None:
    """Let the override follow its series in ``fields`` again."""
    dropped = set(fields)
    if dropped & set(TIMES):
        dropped |= set(TIMES)
    override.overridden_fields = sorted(set(override.overridden_fields) - dropped)


def differences(override: CalendarEvent, series: CalendarEvent) -> set[str]:
    """What the override says differently from its series: a field, or its
    times (another start or length than its occurrence's, or all day when the
    series isn't)."""
    found = {
        name for name in SCALARS if getattr(override, name) != getattr(series, name)
    }
    if (
        override.all_day != series.all_day
        or override.original_start is None
        or override.start_at != override.original_start
        or override.end_at - override.start_at != series.end_at - series.start_at
    ):
        found |= set(TIMES)
    return found


async def remark(session: AsyncSession, override: CalendarEvent) -> None:
    """Record what the override now changes: the fields it differs from its
    series in. What it already owns it keeps, even where the series comes to
    say the same; only a change for the series hands it back (``unmark``)."""
    series = await session.get(CalendarEvent, override.series_id)
    if series is None:
        return
    mark(override, differences(override, series))
    session.add(override)


async def overrides(
    session: AsyncSession, series: CalendarEvent
) -> list[CalendarEvent]:
    """The series' live overrides."""
    return list(
        (
            await session.exec(
                select(CalendarEvent).where(CalendarEvent.series_id == series.id)
            )
        ).all()
    )


def has_plain_from(
    series: CalendarEvent, at: datetime, changed: Iterable[datetime]
) -> bool:
    """Whether the series has an occurrence from ``at`` on without a row of
    its own: one more start than there are rows is enough to know."""
    if not series.recurrence:
        return False
    own = {_utc(value) for value in changed if _utc(value) >= _utc(at)}
    starts = recurrence.starting(
        series.recurrence, series.start_at, series.recurrence_shift, at, len(own) + 1
    )
    return any(start not in own for start in starts)


def answer_key(event: CalendarEvent) -> tuple[int, datetime | None]:
    """Where ``event``'s answers are kept: its series and its start there for
    an occurrence with a row of its own, else the event itself."""
    if event.series_id is not None and event.original_start is not None:
        return event.series_id, _utc(event.original_start)
    return int(event.id), None  # type: ignore[arg-type]


def _at(event_id: int, start: datetime | None) -> ColumnElement[bool]:
    return (CalendarEventAnswer.calendar_event_id == event_id) & (
        CalendarEventAnswer.occurrence_start.is_not_distinct_from(start)  # type: ignore[union-attr]
    )


def answered(user_id: ColumnElement[int], answer: RSVPStatus) -> ColumnElement[bool]:
    """Whether the person in ``user_id`` gave ``answer`` to the ``CalendarEvent``
    row of the query it is used in."""
    return exists().where(
        CalendarEventAnswer.user_id == user_id,
        CalendarEventAnswer.calendar_event_id
        == func.coalesce(CalendarEvent.series_id, CalendarEvent.id),
        CalendarEventAnswer.occurrence_start.is_not_distinct_from(  # type: ignore[union-attr]
            CalendarEvent.original_start
        ),
        CalendarEventAnswer.rsvp_status == answer,
    )


async def answers_on(
    session: AsyncSession, event: CalendarEvent
) -> dict[int, RSVPStatus]:
    """The answers given to ``event``, by person."""
    return await answers_at(session, *answer_key(event))


async def answers_of(
    session: AsyncSession, events: Iterable[CalendarEvent]
) -> dict[int, dict[int, RSVPStatus]]:
    """The answers given to each event, by event id and person, in one read."""
    keys = {int(event.id): answer_key(event) for event in events}  # type: ignore[arg-type]
    if not keys:
        return {}
    rows = await session.exec(
        select(CalendarEventAnswer).where(
            CalendarEventAnswer.calendar_event_id.in_(
                sorted({event_id for event_id, _ in keys.values()})
            )
        )
    )
    kept: dict[tuple[int, datetime | None], dict[int, RSVPStatus]] = {}
    for row in rows.all():
        start = _utc(row.occurrence_start) if row.occurrence_start else None
        kept.setdefault((row.calendar_event_id, start), {})[row.user_id] = (
            row.rsvp_status
        )
    return {event_id: kept.get(key, {}) for event_id, key in keys.items()}


async def answers_at(
    session: AsyncSession, event_id: int, start: datetime | None
) -> dict[int, RSVPStatus]:
    """The answers kept at one key, by person."""
    rows = await session.exec(select(CalendarEventAnswer).where(_at(event_id, start)))
    return {row.user_id: row.rsvp_status for row in rows.all()}


async def attendees_of(
    session: AsyncSession, event_ids: Iterable[int]
) -> dict[int, RSVPStatus]:
    """Everyone attending any of the events, with an answer: declined only
    where they declined all of them."""
    found: dict[int, RSVPStatus] = {}
    rows = await session.exec(
        select(CalendarEventAttendee.user_id, CalendarEventAnswer.rsvp_status)
        .join(
            CalendarEvent, CalendarEvent.id == CalendarEventAttendee.calendar_event_id
        )
        .outerjoin(
            CalendarEventAnswer,
            (CalendarEventAnswer.user_id == CalendarEventAttendee.user_id)
            & (
                CalendarEventAnswer.calendar_event_id
                == func.coalesce(CalendarEvent.series_id, CalendarEvent.id)
            )
            & CalendarEventAnswer.occurrence_start.is_not_distinct_from(  # type: ignore[union-attr]
                CalendarEvent.original_start
            ),
        )
        .where(CalendarEvent.id.in_(sorted(set(event_ids))))
    )
    for user_id, answer in rows.all():
        if found.get(user_id) in (None, RSVPStatus.declined):
            found[user_id] = RSVPStatus(answer) if answer else RSVPStatus.pending
    return found


async def changed_starts(
    session: AsyncSession, series_ids: Iterable[int]
) -> dict[int, set[datetime]]:
    """Each series' occurrences that have a row of their own, by start: the
    series leaves those out and the row stands in."""
    ids = sorted(set(series_ids))
    if not ids:
        return {}
    found: dict[int, set[datetime]] = {}
    rows = await session.exec(
        select(CalendarEvent.series_id, CalendarEvent.original_start).where(
            CalendarEvent.series_id.in_(ids)
        )
    )
    for series_id, start in rows.all():
        if series_id is not None and start is not None:
            found.setdefault(series_id, set()).add(_utc(start))
    return found


def require_occurrence(series: CalendarEvent, at: datetime | None) -> datetime:
    """``at`` as one of the series' starts, or 422."""
    if at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CalendarEventMessages.OCCURRENCE_REQUIRED,
        )
    at = _utc(at)
    if not series.recurrence or not recurrence.occurs(
        series.recurrence, series.start_at, series.recurrence_shift, at
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=CalendarEventMessages.NOT_AN_OCCURRENCE,
        )
    return at


async def _copy_lists(
    session: AsyncSession,
    source: CalendarEvent,
    target: CalendarEvent,
    lists: Iterable[str] = LISTS,
) -> None:
    """Give ``target`` the source's attendees, tags or property values,
    replacing its own. What attendees answered stays where it is kept."""
    lists = set(lists)
    if "attendees" in lists:
        await events_service.set_event_attendees(
            session,
            target,
            [attendee.user_id for attendee in source.attendees],
            calendar=source.calendar,
            carried=True,
        )
    if "tags" in lists:
        await tags_service.replace_entity_tags(session, _TAGS, target.id, [])
        await tags_service.copy_entity_tags(session, _TAGS, {source.id: target.id})
    if "properties" in lists:
        await properties_service.copy_values(
            session, type(source), {source.id: target.id}
        )
    await session.flush()


async def occurrence(
    session: AsyncSession, series: CalendarEvent, at: datetime
) -> CalendarEvent:
    """The override for the series' occurrence at ``at``, made from the series
    the first time it is asked for. The occurrence's answers stay keyed by the
    series and ``at``, so they are its row's from the start."""
    at = require_occurrence(series, at)
    existing = (
        await session.exec(
            select_including_deleted(CalendarEvent).where(
                CalendarEvent.series_id == series.id,
                CalendarEvent.original_start == at,
            )
        )
    ).one_or_none()
    if existing is not None:
        if existing.deleted_at is not None:
            from app.services.tenant.soft_delete import restore_entity

            await restore_entity(session, existing)
        return existing

    override = CalendarEvent(
        calendar_id=series.calendar_id,
        title=series.title,
        description=series.description,
        location=series.location,
        start_at=at,
        end_at=at + (series.end_at - series.start_at),
        all_day=series.all_day,
        rsvp_open=series.rsvp_open,
        series_id=series.id,
        original_start=at,
        created_by=series.created_by,
    )
    session.add(override)
    await session.flush()
    await _copy_lists(session, series, override)
    return override


def _rsvp_closed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=CalendarEventMessages.RSVP_CLOSED,
    )


async def _keep(
    session: AsyncSession,
    event_id: int,
    start: datetime | None,
    user_id: int,
    answer: RSVPStatus,
) -> None:
    row = pg_insert(CalendarEventAnswer).values(
        calendar_event_id=event_id,
        user_id=user_id,
        occurrence_start=start,
        rsvp_status=answer,
    )
    await session.exec(
        row.on_conflict_do_update(
            constraint="uq_calendar_event_answers_key",
            set_={"rsvp_status": row.excluded.rsvp_status},
        )
    )


async def _invited(session: AsyncSession, event_id: int, user_id: int) -> bool:
    return (
        await session.exec(
            select(
                exists().where(
                    CalendarEventAttendee.calendar_event_id == event_id,
                    CalendarEventAttendee.user_id == user_id,
                )
            )
        )
    ).one()


async def _join(session: AsyncSession, event: CalendarEvent, user_id: int) -> None:
    """Put ``user_id`` on the event's list, if they are not on it."""
    await session.exec(
        pg_insert(CalendarEventAttendee)
        .values(
            calendar_event_id=event.id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["calendar_event_id", "user_id"])
    )


async def answer_on(
    session: AsyncSession,
    event: CalendarEvent,
    user_id: int,
    answer: RSVPStatus,
    *,
    join: bool = True,
) -> None:
    """``user_id``'s answer to the event, putting them on its list when
    ``join``; without it, only someone already on the list answers."""
    if join:
        await _join(session, event, user_id)
    elif not await _invited(session, int(event.id), user_id):  # type: ignore[arg-type]
        raise _rsvp_closed()
    await _keep(session, *answer_key(event), user_id, answer)


async def answer_occurrence(
    session: AsyncSession,
    series: CalendarEvent,
    at: datetime | None,
    user_id: int,
    answer: RSVPStatus,
    *,
    join: bool = True,
) -> None:
    """``user_id``'s answer for one occurrence. One with a row of its own is
    answered as that row is; without ``join``, only someone on the
    occurrence's list answers, or who already answered it while it was open."""
    at = require_occurrence(series, at)
    override = (
        await session.exec(
            select(CalendarEvent).where(
                CalendarEvent.series_id == series.id,
                CalendarEvent.original_start == at,
            )
        )
    ).one_or_none()
    if override is not None:
        await answer_on(session, override, user_id, answer, join=join)
        return
    if not join and not (
        await _invited(session, int(series.id), user_id)  # type: ignore[arg-type]
        or user_id in await answers_at(session, int(series.id), at)  # type: ignore[arg-type]
    ):
        raise _rsvp_closed()
    await _keep(session, int(series.id), at, user_id, answer)  # type: ignore[arg-type]


async def answers_for(
    session: AsyncSession, series_id: int, at: datetime
) -> dict[int, RSVPStatus]:
    """One occurrence's answers."""
    return await answers_at(session, series_id, _utc(at))


async def follow(
    session: AsyncSession, series: CalendarEvent, fields: Iterable[str]
) -> None:
    """Write the series' ``fields`` to its overrides that didn't change them."""
    fields = set(fields)
    if not fields:
        return
    length = series.end_at - series.start_at
    for override in await overrides(session, series):
        free = fields - set(override.overridden_fields)
        for name in free & set(SCALARS):
            setattr(override, name, getattr(series, name))
        if free & set(TIMES):
            override.start_at = override.original_start or override.start_at
            override.end_at = override.start_at + length
            override.all_day = series.all_day
        override.calendar_id = series.calendar_id
        override.rsvp_open = series.rsvp_open
        session.add(override)
        if lists := free & set(LISTS):
            await _copy_lists(session, series, override, lists)


async def followed(session: AsyncSession, event: CalendarEvent, field: str) -> None:
    """After a list changed on ``event``: an occurrence's own row now holds its
    own, and a series' overrides that didn't change it follow."""
    if event.series_id is not None:
        mark(event, [field])
        session.add(event)
    elif event.recurrence:
        await follow(session, event, [field])


async def rehome(
    session: AsyncSession,
    series: CalendarEvent,
    *,
    old_shift: int,
    old_start: datetime,
    deleted_by: int | None,
) -> int:
    """Overrides and kept answers of a series whose start or rule changed:
    moved with the start (``recurrence.rehomed``), and binned where the series
    no longer has that occurrence. Returns how many overrides were binned."""
    from app.services.tenant.soft_delete import trash

    binned = 0
    length = series.end_at - series.start_at
    moved = series.start_at != old_start

    def rehomed(value: datetime) -> datetime:
        if not moved or not series.recurrence:
            return value
        return recurrence.rehomed(
            series.recurrence,
            value,
            old_shift,
            series.recurrence_shift,
            old_start,
            series.start_at,
        )

    def occurs(value: datetime) -> bool:
        return bool(series.recurrence) and recurrence.occurs(
            series.recurrence or "", series.start_at, series.recurrence_shift, value
        )

    for override in await overrides(session, series):
        if override.original_start is None:
            continue
        start = rehomed(override.original_start)
        if not occurs(start):
            await trash(session, override, deleted_by_user_id=deleted_by)
            binned += 1
            continue
        override.original_start = start
        if not set(TIMES) & set(override.overridden_fields):
            override.start_at, override.end_at = start, start + length
        session.add(override)
    # Answers given to an occurrence go where it went, or with it.
    for answer in (
        await session.exec(
            select(CalendarEventAnswer).where(
                CalendarEventAnswer.calendar_event_id == series.id,
                CalendarEventAnswer.occurrence_start.is_not(None),  # type: ignore[union-attr]
            )
        )
    ).all():
        start = rehomed(answer.occurrence_start)  # type: ignore[arg-type]
        if occurs(start):
            answer.occurrence_start = start
            session.add(answer)
        else:
            await session.delete(answer)
        await session.flush()
    return binned


async def split(
    session: AsyncSession, series: CalendarEvent, at: datetime
) -> CalendarEvent:
    """End the series before its occurrence ``at`` and start a new one there
    with the rest of it: its fields, attendees, tags and properties, and the
    overrides and answers from ``at`` on. The first part keeps its row, and so
    its links."""
    at = require_occurrence(series, at)
    head, tail = recurrence.split(
        series.recurrence or "", series.start_at, series.recurrence_shift, at
    )
    if head is None:
        return series
    rest = CalendarEvent(
        calendar_id=series.calendar_id,
        title=series.title,
        description=series.description,
        location=series.location,
        start_at=at,
        end_at=at + (series.end_at - series.start_at),
        all_day=series.all_day,
        rsvp_open=series.rsvp_open,
        recurrence=tail,
        recurrence_shift=series.recurrence_shift,
        created_by=series.created_by,
    )
    session.add(rest)
    await session.flush()
    await _copy_lists(session, series, rest)
    for override in await overrides(session, series):
        if override.original_start is not None and _utc(override.original_start) >= at:
            override.series_id = rest.id
            session.add(override)
    await session.exec(
        sa_update(CalendarEventAnswer)
        .where(
            CalendarEventAnswer.calendar_event_id == series.id,
            CalendarEventAnswer.occurrence_start >= at,  # type: ignore[operator]
        )
        .values(calendar_event_id=rest.id)
    )
    series.recurrence = head
    session.add(series)
    await session.flush()
    return rest


async def end_before(
    session: AsyncSession,
    series: CalendarEvent,
    at: datetime,
    *,
    deleted_by: int | None,
) -> bool:
    """Stop the series before its occurrence ``at``, binning the overrides
    from there on. False when ``at`` is its first, so nothing is left."""
    from app.services.tenant.soft_delete import trash

    at = require_occurrence(series, at)
    head, _tail = recurrence.split(
        series.recurrence or "", series.start_at, series.recurrence_shift, at
    )
    if head is None:
        return False
    for override in await overrides(session, series):
        if override.original_start is not None and _utc(override.original_start) >= at:
            await trash(session, override, deleted_by_user_id=deleted_by)
    await session.exec(
        sa_delete(CalendarEventAnswer).where(
            CalendarEventAnswer.calendar_event_id == series.id,
            CalendarEventAnswer.occurrence_start >= at,  # type: ignore[operator]
        )
    )
    series.recurrence = head
    session.add(series)
    return True


async def skip(
    session: AsyncSession,
    series: CalendarEvent,
    at: datetime,
    *,
    deleted_by: int | None,
) -> None:
    """Skip the series' occurrence at ``at``, binning its override."""
    from app.services.tenant.soft_delete import trash

    at = require_occurrence(series, at)
    for override in await overrides(session, series):
        if override.original_start is not None and _utc(override.original_start) == at:
            await trash(session, override, deleted_by_user_id=deleted_by)
    await session.exec(
        sa_delete(CalendarEventAnswer).where(
            CalendarEventAnswer.calendar_event_id == series.id,
            CalendarEventAnswer.occurrence_start == at,
        )
    )
    series.recurrence = recurrence.skipped(
        series.recurrence or "", series.recurrence_shift, at
    )
    session.add(series)


async def bring_back(
    session: AsyncSession, series: CalendarEvent, at: datetime
) -> None:
    """Un-skip the series' occurrence at ``at``, with its own row if skipping
    put one in the bin."""
    from app.services.tenant.soft_delete import restore_entity

    series.recurrence = recurrence.restored(
        series.recurrence or "", series.recurrence_shift, at
    )
    session.add(series)
    binned = (
        await session.exec(
            select_including_deleted(CalendarEvent).where(
                CalendarEvent.series_id == series.id,
                CalendarEvent.original_start == _utc(at),
                CalendarEvent.deleted_at.isnot(None),
            )
        )
    ).one_or_none()
    if binned is not None:
        await restore_entity(session, binned)


async def detach(
    session: AsyncSession, series: CalendarEvent, at: datetime
) -> CalendarEvent:
    """Copy the occurrence at ``at`` out into an event of its own, which the
    series then skips."""
    event = await occurrence(session, series, at)
    await session.exec(
        sa_update(CalendarEventAnswer)
        .where(_at(int(series.id), _utc(at)))  # type: ignore[arg-type]
        .values(calendar_event_id=event.id, occurrence_start=None)
    )
    event.series_id = None
    event.original_start = None
    event.overridden_fields = []
    session.add(event)
    series.recurrence = recurrence.skipped(
        series.recurrence or "", series.recurrence_shift, _utc(at)
    )
    session.add(series)
    await session.flush()
    return event
