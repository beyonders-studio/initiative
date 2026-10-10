"""Calendar source adapter: iCalendar (ics) and an importable JSON envelope,
one file PER CALENDAR.

A calendar is the shareable container for its events, so each selected
calendar renders its own file: ``ics`` is a single multi-event VCALENDAR
(RRULE and ATTENDEE/PARTSTAT preserved), and ``json`` is one
``initiative-calendar`` envelope holding the calendar plus every event.

Selector: an explicit ``calendar_ids`` selection, or ``initiative_id`` (all
exportable calendars in that initiative), or neither — every calendar visible
to the creator across the guild. ``filters`` narrows it the way the calendar
list does, and its ``events`` range narrows each calendar's events
(``EventWindow``). Enumeration applies per-calendar sharing (the
DAC visible-ids subquery), so an export only ever contains calendars shared
with its creator.

Access rule: READ per calendar (exporting is a formatted read), enforced by
``ToolExportAdapter.fetch`` / ``list_calendar_ids_for_export`` at both count
and build time, under the caller's RLS session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.tenant.ical_service import files_for_events
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent, RSVPStatus
from app.services.tenant import calendar_occurrences as occurrences_service
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
    related_reach,
)
from app.core.user_input_validators import resolve_zone
from app.schemas.tenant.tag import annotated_tags
from app.services.export.contract import RenderItem
from app.services.export.filters import narrow, parse_filters
from app.services.export.property_values import exported_properties


class EventWindow(BaseModel):
    """The events a calendar's export carries: those starting in the range,
    a repeating one whole (``series_in_window``). Either end may be open."""

    model_config = ConfigDict(extra="forbid")

    start_after: AwareDatetime | None = None
    start_before: AwareDatetime | None = None


@dataclass(frozen=True)
class _Events:
    """Each calendar's events in the export, by calendar id, and the files
    attached to them, by event id."""

    by_calendar: dict[int, list[CalendarEvent]]
    files: dict[int, list]
    answers: dict[int, dict[int, RSVPStatus]]


class CalendarAdapter(ToolExportAdapter):
    tool = Tool.calendar
    formats = ("ics", "json")
    content_filters: ClassVar[dict[str, type[BaseModel]]] = {"events": EventWindow}

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        # Events are counted with ONE query either way, in the range the export
        # carries. The enumeration is already DAC-filtered, so nothing needs a
        # per-calendar fetch; an explicit id selection keeps its per-calendar
        # fetch+authorize, because the engine's contract is that count()
        # rejects an unauthorized selection BEFORE a job row exists.
        filters = parse_filters(self.tool, params.get("filters"))
        calendar_ids = (
            [
                calendar.id
                for calendar in await self.load(session, user, guild_id, params, format)
            ]
            if _is_selection(params)
            else await self._enumerate(session, user, guild_id, params, filters)
        )
        if not calendar_ids:
            return 0
        return (
            await session.exec(
                select(func.count())
                .select_from(CalendarEvent)
                .where(
                    CalendarEvent.calendar_id.in_(calendar_ids),
                    # The zone the render reads the range in (``BuildContext.now``).
                    *_window(filters, resolve_zone(params.get("tz")).key),
                )
            )
        ).one()

    async def _enumerate(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        filters: BaseModel | None,
    ) -> list[int]:
        """Every calendar the creator may export in the initiative (or the
        guild) that the calendar list's filters leave."""
        from app.services.tenant.calendars import list_calendar_ids_for_export

        return await narrow(
            session,
            user,
            self.tool,
            filters,
            await list_calendar_ids_for_export(
                session, initiative_id=_optional_int(params, "initiative_id")
            ),
        )

    async def load(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> list[Calendar]:
        """An explicit selection, or every calendar the creator may export in
        one initiative (or across the guild). A selection naming one they may
        not export is refused; the enumeration leaves those out instead, the
        way it leaves out calendars they cannot read at all."""
        if _is_selection(params):
            return await super().load(session, user, guild_id, params, format)
        from app.services.permissions import Action, allows

        filters = parse_filters(self.tool, params.get("filters"))
        calendars = [
            await self.fetch(session, user, guild_id, calendar_id, access="read")
            for calendar_id in await self._enumerate(
                session, user, guild_id, params, filters
            )
        ]
        return [calendar for calendar in calendars if allows(calendar, Action.export)]

    async def get_row(
        self, session: AsyncSession, calendar_id: int, /
    ) -> Calendar | None:
        from app.services.tenant.calendars import get_calendar

        return await get_calendar(session, calendar_id, with_events=True)

    def rows(self, calendar: Calendar, /) -> int:
        return len(calendar.events)

    async def prepare(
        self, session: AsyncSession, calendars: list[Calendar], ctx: BuildContext, /
    ) -> _Events:
        # Every event across every calendar, once: the builders below are
        # synchronous and hold no session.
        by_calendar = {calendar.id: list(calendar.events) for calendar in calendars}
        # The clock was read in the viewer's zone, which is the one their
        # range's days were picked in.
        window = _window(ctx.filters, getattr(ctx.now.tzinfo, "key", None))
        if window and by_calendar:
            kept = set(
                await session.exec(
                    select(CalendarEvent.id).where(
                        CalendarEvent.calendar_id.in_(list(by_calendar)), *window
                    )
                )
            )
            by_calendar = {
                calendar_id: [event for event in events if event.id in kept]
                for calendar_id, events in by_calendar.items()
            }
        everything = [event for events in by_calendar.values() for event in events]
        return _Events(
            by_calendar,
            await files_for_events(session, everything),
            await occurrences_service.answers_of(session, everything),
        )

    async def prepared_reach(
        self, session: AsyncSession, ctx: BuildContext, /
    ) -> set[int]:
        # Only the envelope names the attached files; an iCalendar file
        # does not.
        if ctx.format != "json":
            return set()
        return await related_reach(
            session,
            (related for items in ctx.prepared.files.values() for related in items),
        )

    def item(self, calendar: Calendar, ctx: BuildContext, /) -> RenderItem:
        return build_calendar_item(
            calendar,
            ctx.prepared.by_calendar[calendar.id],
            ctx.format,
            ctx.date,
            ctx.prepared.files,
            ctx.prepared.answers,
        )


def _is_selection(params: dict) -> bool:
    """Whether this request named the calendars it wants, rather than asking
    for everything the creator can reach."""
    return bool(params.get("calendar_ids") or params.get("calendar_id"))


def build_calendar_item(
    calendar: Calendar,
    events: list[CalendarEvent],
    format: str,
    date: str,
    files: dict[int, list],
    answers: dict[int, dict[int, RSVPStatus]],
) -> RenderItem:
    """One render item per calendar: an ``ics`` VCALENDAR or an importable
    ``initiative-calendar`` JSON envelope, both carrying the events given."""
    from app.services.tenant.ical_service import event_export_dict

    dicts = [
        event_export_dict(event, files.get(event.id, []), answers.get(event.id))
        for event in events
    ]
    if format == "json":
        # The envelope is importable machine data — stays canonical, never
        # localized (translating field keys / enum values breaks import).
        return RenderItem(
            key=envelope_key(Tool.calendar, calendar.name, date),
            data=_envelope(calendar, dicts),
        )
    stem = export_stem(calendar.name, date)
    return RenderItem(
        key=stem,
        data={"layout": "ical", "events": dicts},
        filename=f"{stem}.ics",
    )


def _envelope(calendar: Calendar, event_dicts: list[dict]) -> dict[str, Any]:
    return {
        "type": tool_envelope_type(Tool.calendar),
        "schema_version": 1,
        "name": calendar.name,
        "description": calendar.description,
        "color": calendar.color,
        "tags": sorted(tag.name for tag in annotated_tags(calendar)),
        "properties": exported_properties(calendar),
        "events": event_dicts,
    }


def _window(filters: BaseModel | None, tz: str | None) -> list:
    """The WHERE legs of the export's ``events`` range, its all-day days read
    in ``tz``; none without a range."""
    from app.services.tenant.calendar_events import series_in_window

    window = getattr(filters, "events", None)
    if window is None:
        return []
    return series_in_window(window.start_after, window.start_before, tz)


def _optional_int(params: dict, key: str) -> int | None:
    """Job params round-trip through JSON — validate, don't trust."""
    value = params.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        from app.core.messages import ExportMessages
        from app.services.export.engine import ExportError

        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
