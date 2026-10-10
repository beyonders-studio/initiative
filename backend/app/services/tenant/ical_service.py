"""iCal (.ics) import/export service.

Handles conversion between CalendarEvent models and iCalendar format. A stored
repeat is already RFC 5545 in UTC terms (``app.core.recurrence``), so export
writes it as it is, and import only moves a file's rule into UTC terms.
"""

import logging
import math
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import icalendar

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.relationships import Related
from app.core.user_input_validators import resolve_zone
from app.models.tenant.calendar_event import CalendarEvent, RSVPStatus
from app.schemas.tenant.ical import (
    ICalEventPreview,
    ICalImportError,
    ICalImportProblem,
    ICalParseResult,
)
from app.services.export.property_values import exported_properties
from app.services.tenant import calendar_occurrences
from app.core.user_display import display_name

logger = logging.getLogger(__name__)

# The last second of a day: an all-day event's end
_END_OF_DAY = time(23, 59, 59)

# RSVP status mapping: app -> iCal PARTSTAT
_RSVP_TO_PARTSTAT = {
    "pending": "NEEDS-ACTION",
    "accepted": "ACCEPTED",
    "declined": "DECLINED",
    "tentative": "TENTATIVE",
}


# ---------------------------------------------------------------------------
# Export: CalendarEvent -> iCal
# ---------------------------------------------------------------------------


def event_export_dict(
    event: CalendarEvent,
    files: "Sequence[Related]" = (),
    answers: Mapping[int, RSVPStatus] | None = None,
) -> dict:
    """One event's JSON-safe export record — the single intermediate both the
    ics renderer and the json envelope consume. Must stay JSON-serializable:
    ``RenderItem.data`` crosses the export engine's job boundary (persisted
    selectors are replayed by the worker), so no models or datetimes here.

    Attendees ride as display name + email + RSVP (informational — user ids
    are guild-local, an import can't rebind them); tags by name; linked
    files by name — handed in, because the edges live in their own table
    and a calendar export renders every event at once."""
    return {
        "id": event.id,
        # The name this event answers to across one import. An id is guild-
        # local and means nothing on the far side; this string is what a task
        # in another envelope points at when it says which sprint it was in.
        "external_ref": f"calendar_event:{event.id}",
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "start_at": event.start_at.isoformat(),
        "end_at": event.end_at.isoformat(),
        "all_day": bool(event.all_day),
        "recurrence": event.recurrence,
        "recurrence_shift": event.recurrence_shift,
        # An occurrence with a row of its own: its series and its start there.
        "series_id": event.series_id,
        "series_ref": f"calendar_event:{event.series_id}" if event.series_id else None,
        "original_start": event.original_start.isoformat()
        if event.original_start
        else None,
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
        "attendees": [
            {
                "name": display_name(attendee.user),
                # An address is never a guild's to hand out, so ATTENDEE
                # carries the participant without a reachable mailbox.
                "email": None,
                "rsvp": (answers or {}).get(attendee.user_id, RSVPStatus.pending).value,
            }
            for attendee in event.attendees or []
            if attendee.user is not None
        ],
        "tags": sorted(tag.name for tag in event.tags or []),
        "files": sorted(
            related.entity.name for related in files if related.entity is not None
        ),
        "properties": exported_properties(event),
    }


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def ical_from_export_dicts(events: List[dict]) -> bytes:
    """Serialize event export dicts (``event_export_dict`` shape) to iCal
    bytes — the render half of the split, callable from the export engine's
    worker replay where only JSON survives.

    Times are UTC and an all-day event's days are its UTC dates, as stored, so
    every client shows the file in its own zone."""
    cal = icalendar.Calendar()
    cal.add("prodid", "-//Initiative//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")

    for event in events:
        vevent = icalendar.Event()
        # An occurrence is its series' UID at the start it replaces.
        vevent.add(
            "uid", f"event-{event.get('series_id') or event.get('id')}@initiative"
        )
        if event.get("original_start"):
            original = _dt(event["original_start"]).astimezone(timezone.utc)
            vevent.add(
                "recurrence-id", original.date() if event.get("all_day") else original
            )
        vevent.add("summary", event.get("title") or "")

        start_at = _dt(event["start_at"]).astimezone(timezone.utc)
        end_at = _dt(event["end_at"]).astimezone(timezone.utc)
        if event.get("all_day"):
            # An all-day event runs to its last day's 23:59:59; DTEND is the
            # day after, exclusive.
            start_day = start_at.date()
            last_day = max((end_at - timedelta(seconds=1)).date(), start_day)
            vevent.add("dtstart", start_day)
            vevent.add("dtend", last_day + timedelta(days=1))
        else:
            # A repeat's days are where it was picked, so the start is written
            # in a fixed offset that puts it on that day.
            zone = _picked_zone(start_at, event.get("recurrence_shift") or 0)
            vevent.add("dtstart", start_at.astimezone(zone))
            vevent.add("dtend", end_at.astimezone(zone))

        if event.get("description"):
            vevent.add("description", event["description"])
        if event.get("location"):
            vevent.add("location", event["location"])

        if event.get("created_at"):
            vevent.add("created", _dt(event["created_at"]).astimezone(timezone.utc))
        if event.get("updated_at"):
            vevent.add(
                "last-modified", _dt(event["updated_at"]).astimezone(timezone.utc)
            )

        if event.get("recurrence"):
            repeat = recurrence.parse(event["recurrence"])
            vevent.add("rrule", repeat.rule)

            # A skipped or extra start takes the start's own type.
            def typed(value: date | datetime) -> date | datetime:
                if event.get("all_day"):
                    return value.date() if isinstance(value, datetime) else value
                if isinstance(value, datetime):
                    return value
                return datetime.combine(value, start_at.timetz())

            for value in repeat.exdates:
                vevent.add("exdate", typed(value))
            for value in repeat.rdates:
                vevent.add("rdate", typed(value))

        for attendee in event.get("attendees") or []:
            email = attendee.get("email")
            if not email:
                continue
            att = icalendar.vCalAddress(f"mailto:{email}")
            if attendee.get("name"):
                att.params["CN"] = icalendar.vText(attendee["name"])
            att.params["PARTSTAT"] = icalendar.vText(
                _RSVP_TO_PARTSTAT.get(attendee.get("rsvp"), "NEEDS-ACTION")
            )
            vevent.add("attendee", att, encode=0)

        cal.add_component(vevent)

    cal.add_missing_timezones()
    return cal.to_ical()


def _picked_zone(start: datetime, shift: int) -> tzinfo:
    """A fixed offset, in whole hours where it can be, whose date for ``start``
    is the one the repeat was picked on (``app.core.recurrence``)."""
    if shift == 0:
        return timezone.utc
    if shift % 1440 == 0:
        hours = (
            start - start.replace(hour=0, minute=0, second=0)
        ).total_seconds() / 3600
        offset = math.ceil(24 - hours) if shift > 0 else -(math.floor(hours) + 1)
        offset = max(-12, min(14, offset))  # the offsets Etc/GMT names
        return ZoneInfo(f"Etc/GMT{'-' if offset > 0 else '+'}{abs(offset)}")
    if shift % 60 == 0:
        return ZoneInfo(f"Etc/GMT{'-' if shift > 0 else '+'}{abs(shift) // 60}")
    return timezone(timedelta(minutes=shift))


async def files_for_events(
    session: "AsyncSession", events: List[CalendarEvent]
) -> "dict[int, list[Related]]":
    """Attached files for many events, in two queries.

    Here rather than at each caller: the builders above are synchronous and hold
    no session, and a calendar export renders every event a calendar has.

    Keyed by event id, which is unambiguous because this reads ONE guild's
    schema. A caller walking several guilds must not merge these dicts — ids
    repeat across schemas — and should carry each list with its event instead.
    """
    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.models.tenant.file import File
    from app.services.tenant import relationships

    return await relationships.related_for_many(
        session,
        SearchEntityType.calendar_event,
        [event.id for event in events if event.id is not None],
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.file,
        model=File,
    )


# ---------------------------------------------------------------------------
# Import: iCal -> parsed data
# ---------------------------------------------------------------------------


def _repeat(component, start: datetime, zone: tzinfo) -> tuple[Optional[str], int]:
    """A VEVENT's repeat and its shift, or none when it has none or uses parts
    an event can't repeat by (a minutely rule, say).

    The file's rule is kept as it is, its days picked in its start's own zone:
    the ``TZID``, UTC, or for a floating time the importer's ``zone``. Its end,
    skips and extra dates are moved to UTC."""
    rule = component.get("rrule")
    if rule is None or isinstance(rule, list):
        return None, 0
    picked_in = start.tzinfo or zone

    def utc(value: date | datetime) -> date | datetime:
        if not isinstance(value, datetime):
            return value
        aware = value if value.tzinfo else value.replace(tzinfo=picked_in)
        return aware.astimezone(timezone.utc)

    parts = {key.upper(): list(values) for key, values in rule.items()}
    if until := parts.get("UNTIL"):
        parts["UNTIL"] = [utc(until[0])]
    try:
        kept = recurrence.normalize(
            recurrence.Recurrence(
                parts,
                tuple(utc(value) for value in _dates(component.get("exdate"))),
                tuple(utc(value) for value in _dates(component.get("rdate"))),
            ).to_lines(),
            kind="event",
        )
    except ValueError:
        logger.info("iCal import kept an event without its repeat", exc_info=True)
        return None, 0
    return kept, recurrence.shift_for(kept, start, picked_in)


def _dates(prop) -> List[date | datetime]:
    lists = prop if isinstance(prop, list) else [prop] if prop else []
    return [value.dt for dates in lists for value in dates.dts]


def _extract_vevent(component, zone: tzinfo) -> Optional[dict]:
    """Extract event data from a VEVENT component. An all-day event keeps its
    dates as UTC dates, first midnight to last 23:59:59; a floating time is
    read in ``zone``, the importer's."""
    summary = str(component.get("summary", "Untitled Event"))
    dtstart = component.get("dtstart")
    dtend = component.get("dtend")

    if not dtstart:
        return None

    start_val = dtstart.dt
    end_val = dtend.dt if dtend else start_val
    all_day = isinstance(start_val, date) and not isinstance(start_val, datetime)

    if all_day:
        if isinstance(end_val, datetime):
            end_val = end_val.date()
        # DTEND is exclusive: the last day is the one before it.
        last_day = max(end_val - timedelta(days=1), start_val)
        start_dt = datetime.combine(start_val, time(), timezone.utc)
        end_dt = datetime.combine(last_day, _END_OF_DAY, timezone.utc)
    else:
        start_dt = start_val if start_val.tzinfo else start_val.replace(tzinfo=zone)
        end_dt = end_val if end_val.tzinfo else end_val.replace(tzinfo=zone)

    repeat, shift = _repeat(component, start_dt, zone)
    return {
        "summary": summary,
        "description": str(component.get("description", "")) or None,
        "location": str(component.get("location", "")) or None,
        "start_at": start_dt,
        "end_at": end_dt,
        "all_day": all_day,
        "recurrence": repeat,
        "recurrence_shift": shift,
    }


def parse_ical(content: str, tz: Optional[str] = None) -> ICalParseResult:
    """Parse an .ics string and return a preview of found events."""
    zone = resolve_zone(tz)
    cal = icalendar.Calendar.from_ical(content)
    events: List[ICalEventPreview] = []
    has_recurring = False

    for component in cal.walk():
        if component.name != "VEVENT":
            continue
        data = _extract_vevent(component, zone)
        if not data:
            continue
        has_rec = data["recurrence"] is not None
        if has_rec:
            has_recurring = True
        events.append(
            ICalEventPreview(
                summary=data["summary"],
                start_at=data["start_at"].isoformat(),
                end_at=data["end_at"].isoformat() if data["end_at"] else None,
                all_day=data["all_day"],
                has_recurrence=has_rec,
            )
        )

    return ICalParseResult(
        event_count=len(events),
        events=events,
        has_recurring=has_recurring,
    )


def build_calendar_events(
    content: str,
    calendar_id: int,
    guild_id: int,
    created_by: int,
    tz: Optional[str] = None,
) -> Tuple[List[CalendarEvent], List[ICalImportError], int]:
    """Parse .ics content and build CalendarEvent model instances attached to
    the target calendar.

    Returns (events, errors, skipped_count). Does NOT persist — caller handles that.
    """
    zone = resolve_zone(tz)
    cal = icalendar.Calendar.from_ical(content)
    events: List[CalendarEvent] = []
    errors: List[ICalImportError] = []
    skipped = 0
    # A repeating event by its UID, for the occurrences the file changed
    # (a VEVENT with its UID and a RECURRENCE-ID), which follow it.
    series: dict[str, CalendarEvent] = {}
    changed: List[Tuple[CalendarEvent, str, date | datetime]] = []

    components = [c for c in cal.walk() if c.name == "VEVENT"]
    # Each series before the occurrences that point at it.
    components.sort(key=lambda c: c.get("recurrence-id") is not None)
    for component in components:
        title = str(component.get("summary") or "") or None
        try:
            data = _extract_vevent(component, zone)
            if not data:
                errors.append(
                    ICalImportError(problem=ICalImportProblem.no_start, title=title)
                )
                skipped += 1
                continue

            event = CalendarEvent(
                calendar_id=calendar_id,
                title=data["summary"][:255],
                description=data["description"],
                location=data["location"][:500] if data["location"] else None,
                start_at=data["start_at"],
                end_at=data["end_at"],
                all_day=data["all_day"],
                recurrence=data["recurrence"],
                recurrence_shift=data["recurrence_shift"],
                created_by=created_by,
            )
            uid = str(component.get("uid") or "")
            if (original := component.get("recurrence-id")) is not None and uid:
                changed.append((event, uid, original.dt))
            elif event.recurrence and uid:
                series[uid] = event
            events.append(event)
        except Exception:
            logger.exception("iCal import could not read event %r", title)
            errors.append(
                ICalImportError(problem=ICalImportProblem.unreadable, title=title)
            )
            skipped += 1

    for event, uid, original in changed:
        if (parent := series.get(uid)) is None:
            continue  # its series isn't in the file: an event of its own
        if isinstance(original, datetime):
            at = original if original.tzinfo else original.replace(tzinfo=zone)
        else:
            at = datetime.combine(original, parent.start_at.timetz())
        event.series = parent
        event.original_start = at.astimezone(timezone.utc)
        # What the file says differently for this occurrence stays its own.
        event.overridden_fields = sorted(
            calendar_occurrences.differences(event, parent)
        )
    return events, errors, skipped
