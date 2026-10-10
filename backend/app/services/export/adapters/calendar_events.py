"""Calendar-events source adapter: "export events" is "list events, but render".

Queries through ``guild_calendar_event_conditions`` — the same scope, sharing
and property filters as the calendar-entries view, executed under the
caller's RLS session (that query IS the authorization) — and renders every
matching event into one
iCalendar file. Anyone who can see a calendar's events can export them, the
way anyone who can see a project's tasks can export those.

``params`` is the calendar page's own selector: ``{"initiative_id", "scope",
"calendar_ids", "exclude_calendar_ids", "property_filters", "start_after",
"start_before"}``. It is what an ExportJob row persists,
and what the worker replays here at render time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.db.session import require_guild_context
from app.models.platform.user import User
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.services.tenant import calendar_occurrences as occurrences_service
from app.services.export.adapters._common import require_may_leave
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.tenant.ical_service import files_for_events, event_export_dict


class CalendarEventsAdapter:
    source = "events"
    template_id = "data-table"
    formats = ("ics",)

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        conditions = await _conditions(session, user, params)
        counted = await session.scalar(
            select(func.count()).select_from(
                select(CalendarEvent.id).where(*conditions).subquery()
            )
        )
        return counted or 0

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        dicts, reach = await event_dicts(session, user, params)
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(RenderItem(key="events", data={"layout": "ical", "events": dicts}),),
            initiative_ids=reach,
        )


async def event_dicts(
    session: AsyncSession, user: User, params: dict[str, Any]
) -> tuple[list[dict], frozenset[int]]:
    """The events ``params`` selects, as export dicts, and the initiatives they
    sit in — refused when one of those keeps its content in. Shared with the
    calendar's subscription feed, which is this export of one calendar, served
    on every fetch."""
    events = await _query(session, user, params)
    reach = await require_may_leave(session, await _reach(session, events))
    files = await files_for_events(session, events)
    answers = await occurrences_service.answers_of(session, events)
    return [
        event_export_dict(event, files.get(event.id, []), answers.get(event.id))
        for event in events
    ], reach


async def _reach(session: AsyncSession, events: list[CalendarEvent]) -> frozenset[int]:
    """The initiatives the events' calendars sit in. A guild calendar sits in
    none."""
    calendar_ids = {event.calendar_id for event in events}
    if not calendar_ids:
        return frozenset()
    rows = await session.exec(
        select(Calendar.initiative_id).where(
            Calendar.id.in_(calendar_ids), Calendar.initiative_id.is_not(None)
        )
    )
    return frozenset(rows)


def _filters(params: dict[str, Any]) -> dict[str, Any]:
    """The calendar page's selector, as the shared event query takes it."""
    return dict(
        initiative_id=params.get("initiative_id"),
        guild_scope=params.get("scope") == "community",
        calendar_ids=params.get("calendar_ids"),
        exclude_calendar_ids=params.get("exclude_calendar_ids"),
        property_filters=params.get("property_filters"),
        start_after=_instant(params.get("start_after")),
        start_before=_instant(params.get("start_before")),
        tz=params.get("tz"),
        whole_series=True,
    )


async def _conditions(session: AsyncSession, user: User, params: dict[str, Any]):
    from app.services.tenant.calendar_events import (
        guild_calendar_event_conditions,
    )

    return await guild_calendar_event_conditions(
        session, user, require_guild_context(session), **_filters(params)
    )


async def _query(
    session: AsyncSession, user: User, params: dict[str, Any]
) -> list[CalendarEvent]:
    from app.services.tenant.calendar_events import (
        query_guild_calendar_events,
    )

    return await query_guild_calendar_events(
        session, user, require_guild_context(session), **_filters(params)
    )


def _instant(value: str | None) -> datetime | None:
    """A window bound from the job's params, which hold it as ISO text."""
    if value is None:
        return None
    try:
        instant = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    # A bound without a zone is read as UTC, as the calendar's own window is.
    return instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc)
