"""``initiative-calendar`` importer: one envelope holds a whole calendar —
the calendar row (the shareable container) and its tags, plus its events. The importer
becomes the calendar's owner; events apply in per-event savepoints (the ICS
import's partial-success pattern) so a malformed event fails alone, never the
batch.

Attendees resolve by handle against the target initiative's members; the
matched keep their RSVP, the unmatched are reported. Linked file titles
in the envelope are informational and dropped."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.db.session import routed_guild_id
from app.core.search import SearchEntityType
from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.calendar import DEFAULT_CALENDAR_COLOR, Calendar
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAnswer,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.initiative import Initiative, PermissionKey
from app.schemas.tenant.import_envelopes import (
    CalendarEnvelope,
    EventEnvelopeItem,
)
from app.services.import_engine.common import (
    handle_key,
    load_initiative_member_handles,
    parse_datetime,
    unique_name_in_initiative,
)
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.import_engine.context import ImportContext
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.import_engine.people import (
    PeopleMap,
    bring_in_named,
    initiative_member_id,
)
from app.services.tenant import calendar_occurrences
from app.services.tenant.named_people import Governing

if TYPE_CHECKING:
    from app.schemas.tenant.backup_export import ManifestPerson


class CalendarImporter(NamesPeopleInPassing):
    envelope_type = tool_envelope_type(Tool.calendar)
    permission = PermissionKey.create_calendars

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(CalendarEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        envelope: CalendarEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        return len(envelope.events) + 1

    def people(self, validated: BaseModel) -> list["ManifestPerson"]:
        """Everyone a person property or a mention names, and every attendee:
        the people step says who each of them is here."""
        from app.schemas.tenant.backup_export import ManifestPerson

        envelope: CalendarEnvelope = validated  # ty: ignore[invalid-assignment] — validate() returned this model
        listed = {handle_key(p.handle): p for p in super().people(validated)}
        for event in envelope.events:
            for attendee in event.attendees:
                if attendee.handle:
                    listed.setdefault(
                        handle_key(attendee.handle),
                        ManifestPerson(
                            handle=attendee.handle, name=None, comment_count=0
                        ),
                    )
        return sorted(listed.values(), key=lambda p: p.handle.lower())

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: CalendarEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_id = routed_guild_id(session)
        member_handles = await load_initiative_member_handles(
            session, initiative_id=target_initiative.id
        )

        calendar = Calendar(
            name=await unique_name_in_initiative(
                session, Calendar, target_initiative.id, env.name
            ),
            description=env.description,
            color=env.color or DEFAULT_CALENDAR_COLOR,
            initiative_id=target_initiative.id,
            created_by=importer.id,
        )
        session.add(calendar)
        await session.flush()

        await grant_ownership(
            session,
            tool=Tool.calendar,
            entity_id=calendar.id,
            target_initiative=target_initiative,
            importer=importer,
        )

        tags = TagRestore(session)
        await tags.attach(calendar, env.tags)
        props = PropertyRestore(
            session,
            initiative_id=target_initiative.id,
            context=context,
            member_handles=member_handles,
        )
        await props.attach(calendar, env.properties)

        created = 0
        failed = 0
        tags_created = tags.created
        tags_matched = tags.matched
        props_created = props.created
        props_matched = props.matched
        attendees_matched = 0
        unmatched_handles: set[str] = set(props.unmatched)
        named_handles: dict[int, str] = dict(props.named)
        warnings: list[str] = []

        # A repeating event's new id by the name it came with, for the
        # occurrences of it with rows of their own, which come after it.
        series_ids: dict[str, int] = {}
        for item in sorted(env.events, key=lambda item: item.series_ref is not None):
            try:
                async with session.begin_nested():
                    counts = await self._apply_event(
                        session,
                        item=item,
                        series_ids=series_ids,
                        calendar_id=calendar.id,
                        initiative_id=target_initiative.id,
                        guild_id=guild_id,
                        importer=importer,
                        member_handles=member_handles,
                        unmatched_handles=unmatched_handles,
                        named_handles=named_handles,
                        context=context,
                    )
            except Exception:
                failed += 1
                warnings.append(f"event_failed:{item.title[:80]}")
                continue
            created += 1
            tags_created += counts["tags_created"]
            tags_matched += counts["tags_matched"]
            props_created += counts["props_created"]
            props_matched += counts["props_matched"]
            attendees_matched += counts["attendees_matched"]

        await session.flush()
        gone = await bring_in_named(
            session,
            Governing.of(Tool.calendar, calendar),
            initiative_id=target_initiative.id,
        )
        unmatched_handles.update(named_handles[user_id] for user_id in gone)
        return EnvelopeImportResult(
            entity_id=calendar.id,
            entity_title=calendar.name,
            created={
                Tool.calendar.plural: 1,
                "events": created,
                "tags": tags_created,
                "properties": props_created,
            },
            matched={
                "tags": tags_matched,
                "properties": props_matched,
                "attendees": attendees_matched,
            },
            failed={"events": failed} if failed else {},
            unmatched_handles=sorted(unmatched_handles),
            warnings=warnings,
        )

    async def _apply_event(
        self,
        session: AsyncSession,
        *,
        item: EventEnvelopeItem,
        calendar_id: int,
        initiative_id: int,
        guild_id: int,
        importer: User,
        member_handles: dict[str, int],
        unmatched_handles: set[str],
        named_handles: dict[int, str],
        series_ids: dict[str, int],
        context: ImportContext | None = None,
    ) -> dict[str, int]:
        start_at = parse_datetime(item.start_at)
        end_at = parse_datetime(item.end_at)
        if start_at is None or end_at is None:
            raise ValueError("unparseable event times")
        if item.all_day:
            # An all-day event is its UTC dates. An export taken before that
            # carries its creator's local midnight, whose date is the nearest
            # UTC midnight; a newer one is already on it.
            start_at = _nearest_midnight(start_at)
            end_at = _nearest_midnight(end_at + timedelta(seconds=1)) - timedelta(
                seconds=1
            )
        repeat, shift = recurrence.imported(
            item.recurrence,
            kind="event",
            start=start_at,
            tz=importer.timezone,
            shift=item.recurrence_shift,
            all_day=item.all_day,
        )
        event = CalendarEvent(
            calendar_id=calendar_id,
            title=item.title,
            description=item.description,
            location=item.location,
            start_at=start_at,
            end_at=end_at,
            all_day=item.all_day,
            recurrence=repeat,
            recurrence_shift=shift,
            created_by=importer.id,
            # When the event was written down, not when it happens. Absent
            # leaves the model default: the moment of the import.
            **_created_at(item),
        )
        original = parse_datetime(item.original_start) if item.original_start else None
        if item.series_ref in series_ids and original is not None:
            series = await session.get(CalendarEvent, series_ids[item.series_ref])
            event.series_id = series_ids[item.series_ref]
            event.original_start = original
            if series is not None:
                # What it says differently stays its own, and so do the
                # attendees, tags and properties it came with.
                event.overridden_fields = sorted(
                    calendar_occurrences.differences(event, series)
                    | set(calendar_occurrences.LISTS)
                )
        session.add(event)
        await session.flush()
        if item.external_ref and event.recurrence and event.id is not None:
            series_ids[item.external_ref] = event.id

        # An event is something other entries point at — a sprint with its
        # tasks in it — so it joins the job's ref map like a task does. The
        # edges themselves are written by the deferred pass, because the
        # tasks naming this sprint are in a different envelope.
        if context is not None:
            context.links.register(
                item.external_ref, SearchEntityType.calendar_event, event.id
            )

        attendees_matched = 0
        seen_user_ids: set[int] = set()
        for attendee in item.attendees:
            if not attendee.handle:
                continue
            uid = initiative_member_id(
                attendee.handle,
                people=context.people if context is not None else PeopleMap(),
                member_handles=member_handles,
            )
            if uid is None:
                unmatched_handles.add(attendee.handle)
                continue
            if uid in seen_user_ids:
                continue
            seen_user_ids.add(uid)
            named_handles.setdefault(uid, attendee.handle)
            try:
                rsvp = RSVPStatus(attendee.rsvp)
            except ValueError:
                rsvp = RSVPStatus.pending
            session.add(CalendarEventAttendee(calendar_event_id=event.id, user_id=uid))
            if rsvp is not RSVPStatus.pending:
                event_id, start = calendar_occurrences.answer_key(event)
                session.add(
                    CalendarEventAnswer(
                        calendar_event_id=event_id,
                        user_id=uid,
                        occurrence_start=start,
                        rsvp_status=rsvp,
                    )
                )
            attendees_matched += 1

        # Its own restore: what the event's savepoint rolls back goes with it.
        tags = TagRestore(session)
        await tags.attach(event, item.tags)

        props = PropertyRestore(
            session,
            initiative_id=initiative_id,
            context=context,
            member_handles=member_handles,
        )
        await props.attach(event, item.properties)
        unmatched_handles.update(props.unmatched)
        for user_id, handle in props.named.items():
            named_handles.setdefault(user_id, handle)

        return {
            "tags_created": tags.created,
            "tags_matched": tags.matched,
            "props_created": props.created,
            "props_matched": props.matched,
            "attendees_matched": attendees_matched,
        }


def _created_at(item: EventEnvelopeItem) -> dict[str, datetime]:
    """The event's own creation time, where the envelope carried a readable
    one. Returned as kwargs so an absent or unparseable stamp falls through
    to the model default rather than overwriting it."""
    parsed = parse_datetime(item.created_at)
    return {"created_at": parsed} if parsed is not None else {}


def _nearest_midnight(value: datetime) -> datetime:
    return datetime.combine(
        (value.astimezone(timezone.utc) + timedelta(hours=12)).date(),
        time(),
        timezone.utc,
    )
