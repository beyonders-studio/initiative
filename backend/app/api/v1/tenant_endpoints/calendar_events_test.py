"""Integration tests for calendar-event endpoints.

Events live inside a calendar (the shareable container) and carry no grants of
their own — read/write access is inherited from the parent calendar, the way
tasks inherit project access. These tests cover event creation (which requires
write on the target calendar), the attendee/RSVP notification flows, tag
serialization on the event summary, and the calendar-entries reads' DAC filter
(which keys off calendar sharing, not per-event grants).
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text

from app.db.schema_provisioning import guild_schema_name
from app.core.messages import (
    CalendarEventMessages,
    CommonMessages,
    PropertyMessages,
)
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.property import PropertyValue
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_guild_calendar,
    create_initiative,
    create_property_definition,
    create_property_value,
    create_resource_grant,
    create_tag,
    get_auth_headers,
    route_session_to_guild,
    drain_notices,
)


def _around_now(**params: Any) -> dict[str, Any]:
    """A calendar-entries read of the events around now, where the factory
    puts them, without task markers."""
    now = datetime.now(timezone.utc)
    return {
        "start_after": (now - timedelta(days=1)).isoformat(),
        "start_before": (now + timedelta(days=1)).isoformat(),
        "include_tasks": "false",
        **params,
    }


async def _drop_all_members_grant(session: AsyncSession, guild, calendar) -> None:
    """Strip the all-initiative-members read grant, leaving only the creator's
    owner grant — a calendar shared with nobody else."""
    schema = guild_schema_name(guild.id)
    await session.exec(text(f'SET search_path TO "{schema}", public'))
    await session.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == "calendar",
            ResourceGrant.resource_id == calendar.id,
            ResourceGrant.all_initiative_members == True,  # noqa: E712
        )
    )
    await session.exec(text("SET search_path TO public"))
    await session.commit()


async def _notifications_for(
    session: AsyncSession, user_id: int, ntype: NotificationType
) -> list[Notification]:
    await drain_notices()
    result = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == ntype,
        )
    )
    return list(result.all())


async def _enable_calendars(session: AsyncSession, initiative, creator):
    """Turn the calendars tool on and return a calendar owned by ``creator``.

    ``create_calendar`` seeds the creator-owner grant + an all-initiative-members
    read grant, mirroring the create endpoint's default sharing."""
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    return await create_calendar(session, initiative, creator)


async def _setup_organizer_and_attendee(session, acting_user):
    """Calendars-enabled initiative with an admin organizer and a member
    attendee, plus a calendar owned by the organizer.

    Returns ``(organizer, attendee, guild, initiative, calendar)`` where
    organizer and attendee are ``Actor`` instances (``.user``/``.headers``)."""
    organizer = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    attendee = await acting_user(
        guild_role=CommunityRole.member,
        guild=organizer.guild,
        initiative=organizer.initiative,
        initiative_role="member",
    )
    calendar = await _enable_calendars(session, organizer.initiative, organizer.user)
    return organizer, attendee, organizer.guild, organizer.initiative, calendar


async def _setup_event(session, acting_user):
    """admin user, guild, calendars-enabled initiative, calendar, event.

    Returns ``(actor, guild, initiative, calendar, event)``."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    calendar = await _enable_calendars(session, a.initiative, a.user)
    event = await create_calendar_event(session, calendar, a.user, title="E")
    return a, a.guild, a.initiative, calendar, event


async def test_event_summary_includes_tags(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, guild, initiative, calendar, event = await _setup_event(session, acting_user)

    tag = await create_tag(session, guild, name="Priority", color="#ff0000")

    # Events are content-level extras (like tasks), not tools, so their tags
    # are set by the event's own PATCH rather than the generic /tools route.
    assign = await client.patch(
        a.g(f"/calendar-events/{event.id}"),
        headers=a.headers,
        json={"tag_ids": [tag.id]},
    )
    assert assign.status_code == 200

    # The summary should embed the tag.
    response = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params=_around_now(initiative_id=initiative.id),
    )
    assert response.status_code == 200, response.text
    items = {item["id"]: item for item in response.json()["events"]}
    assert event.id in items
    tags = items[event.id]["tags"]
    assert [t["id"] for t in tags] == [tag.id]
    assert tags[0]["name"] == "Priority"


async def test_event_summary_tags_default_empty(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An event with no tags still serializes ``tags: []`` in the summary."""
    a, guild, initiative, calendar, event = await _setup_event(session, acting_user)

    response = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params=_around_now(initiative_id=initiative.id),
    )
    assert response.status_code == 200, response.text
    items = {item["id"]: item for item in response.json()["events"]}
    assert items[event.id]["tags"] == []


async def test_create_event_notifies_attendees_not_creator(
    client: AsyncClient, session: AsyncSession, acting_user
):
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Kickoff",
            "start_at": "2026-07-01T15:00:00Z",
            "end_at": "2026-07-01T16:00:00Z",
            "all_day": False,
            "attendee_ids": [attendee.user.id],
        },
    )
    assert response.status_code == 201

    invites = await _notifications_for(
        session, attendee.user.id, NotificationType.event_invitation
    )
    assert len(invites) == 1
    # The line carries the reference, not the title: the bell reads the
    # title back from the calendar when it renders.
    assert "event_title" not in invites[0].data
    assert invites[0].data["event_id"] == response.json()["id"]
    # The creator should not be notified about their own event.
    assert (
        await _notifications_for(
            session, organizer.user.id, NotificationType.event_invitation
        )
        == []
    )


async def test_create_multi_day_timed_event_is_allowed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A timed (non-all-day) event may now span more than 24 hours / cross days."""
    (
        organizer,
        _attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Conference",
            "start_at": "2026-07-01T14:00:00Z",
            "end_at": "2026-07-03T16:00:00Z",
            "all_day": False,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["start_at"].startswith("2026-07-01")
    assert body["end_at"].startswith("2026-07-03")


async def test_one_occurrence_changes_alone(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Mondays at 09:00 UTC from 5 October. One occurrence is moved and
    renamed, and still follows the series where it didn't change; one is
    skipped and brought back; an attendee who can't edit the calendar declines
    one; and the series is renamed from a later one on, then deleted."""
    (
        organizer,
        attendee,
        _guild,
        _initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    standup = {
        "calendar_id": calendar.id,
        "title": "Standup",
        "start_at": "2026-10-05T09:00:00Z",
        "end_at": "2026-10-05T09:30:00Z",
        "recurrence": "FREQ=WEEKLY;BYDAY=MO",
        "attendee_ids": [attendee.user.id],
    }
    # Every seventh day from a Monday is never a Tuesday.
    never = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={**standup, "recurrence": "FREQ=DAILY;INTERVAL=7;BYDAY=TU"},
    )
    assert never.status_code == 422
    assert never.json()["detail"] == "RECURRENCE_INVALID"
    created = await client.post(
        organizer.g("/calendar-events/"), headers=organizer.headers, json=standup
    )
    assert created.status_code == 201, created.text
    series = created.json()["id"]
    second, third, fourth = (
        "2026-10-12T09:00:00Z",
        "2026-10-19T09:00:00Z",
        "2026-10-26T09:00:00Z",
    )

    def at(path: str) -> str:
        return organizer.g(f"/calendar-events/{series}{path}")

    async def month() -> list[tuple[str, str, str | None]]:
        entries = await client.get(
            organizer.g("/calendar-entries/"),
            headers=organizer.headers,
            params={
                "start_after": "2026-10-01T00:00:00Z",
                "start_before": "2026-11-01T00:00:00Z",
                "include_tasks": "false",
            },
        )
        assert entries.status_code == 200, entries.text
        return [
            (e["title"], e["start_at"], e["location"]) for e in entries.json()["events"]
        ]

    moved = await client.patch(
        at(""),
        headers=organizer.headers,
        json={
            "scope": "this",
            "occurrence": second,
            "title": "Standup (moved)",
            "start_at": "2026-10-12T10:00:00Z",
            "end_at": "2026-10-12T10:30:00Z",
        },
    )
    assert moved.status_code == 200, moved.text
    assert (
        moved.json()["series_id"],
        moved.json()["original_start"],
        moved.json()["overridden_fields"],
    ) == (series, second, ["all_day", "end_at", "start_at", "title"])
    override = moved.json()["id"]
    # A change to the series reaches the occurrence where it didn't change,
    # and saving it again with that value doesn't make the value its own.
    await client.patch(at(""), headers=organizer.headers, json={"location": "Room 2"})
    resaved = await client.patch(
        organizer.g(f"/calendar-events/{override}"),
        headers=organizer.headers,
        json={"title": "Standup (moved)", "location": "Room 2"},
    )
    assert resaved.json()["overridden_fields"] == [
        "all_day",
        "end_at",
        "start_at",
        "title",
    ]
    assert await month() == [
        ("Standup", "2026-10-05T09:00:00Z", "Room 2"),
        ("Standup (moved)", "2026-10-12T10:00:00Z", "Room 2"),
        ("Standup", third, "Room 2"),
        ("Standup", fourth, "Room 2"),
    ]

    # Deleting the moved one skips it, and tells its attendees; bringing it
    # back brings back what it changed.
    skipped = await client.delete(
        organizer.g(f"/calendar-events/{override}"), headers=organizer.headers
    )
    assert skipped.status_code == 204
    read = await client.get(at(""), headers=organizer.headers)
    assert read.json()["skipped_starts"] == [second]
    cancels = await _notifications_for(
        session, attendee.user.id, NotificationType.event_cancelled
    )
    assert [notice.data["start_at"] for notice in cancels] == [
        "2026-10-12T09:00:00+00:00"
    ]
    restored = await client.post(
        at("/occurrences/restore"), headers=organizer.headers, json={"start": second}
    )
    assert restored.json()["skipped_starts"] == []
    assert "Standup (moved)" in [title for title, _start, _location in await month()]

    # Answering takes read access, so one occurrence's answer needs no row.
    declined = await client.patch(
        attendee.g(f"/calendar-events/{series}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "declined", "occurrence": fourth},
    )
    assert declined.status_code == 200, declined.text
    # An answer is for one event, so a repeating one names its occurrence.
    unnamed = await client.patch(
        attendee.g(f"/calendar-events/{series}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "accepted"},
    )
    assert unnamed.json()["detail"] == "CALENDAR_EVENT_OCCURRENCE_REQUIRED"

    async def answer(event_id: int, occurrence: str | None = None) -> str:
        read = await client.get(
            organizer.g(f"/calendar-events/{event_id}"),
            headers=organizer.headers,
            params={"occurrence": occurrence} if occurrence else {},
        )
        return read.json()["attendees"][0]["rsvp_status"]

    assert (await answer(series, fourth), await answer(series)) == (
        "declined",
        "pending",
    )
    # One with a row of its own is answered, and read back, on that row.
    await client.patch(
        attendee.g(f"/calendar-events/{series}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "tentative", "occurrence": second},
    )
    assert (await answer(series, second), await answer(override)) == (
        "tentative",
        "tentative",
    )

    retro = await client.patch(
        at(""),
        headers=organizer.headers,
        json={"scope": "following", "occurrence": fourth, "title": "Retro"},
    )
    assert retro.status_code == 200, retro.text
    rest = retro.json()["id"]
    assert rest != series
    assert (await client.get(at(""), headers=organizer.headers)).json()[
        "recurrence"
    ] == "RRULE:FREQ=WEEKLY;UNTIL=20261026T085959Z;BYDAY=MO"
    assert [title for title, _start, _location in await month()] == [
        "Standup",
        "Standup (moved)",
        "Standup",
        "Retro",
    ]
    # The answer went with its occurrence.
    assert await answer(rest, fourth) == "declined"

    deleted = await client.delete(
        at(""), headers=organizer.headers, params={"scope": "all"}
    )
    assert deleted.status_code == 204
    assert [title for title, _start, _location in await month()] == ["Retro"]


async def test_a_cancellation_tells_who_was_coming_to_what_goes(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Twice, a week apart. The second has its own row, and the attendee
    declined it: ending the series there cancels only that one, so they are
    not told."""
    (
        organizer,
        attendee,
        _guild,
        _initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    created = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Standup",
            "start_at": "2026-10-05T09:00:00Z",
            "end_at": "2026-10-05T09:30:00Z",
            "recurrence": "FREQ=WEEKLY;COUNT=2",
            "attendee_ids": [attendee.user.id],
        },
    )
    series = created.json()["id"]
    second = "2026-10-12T09:00:00Z"
    opened = await client.post(
        organizer.g(f"/calendar-events/{series}/occurrences"),
        headers=organizer.headers,
        json={"start": second},
    )
    await client.patch(
        attendee.g(f"/calendar-events/{series}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "declined", "occurrence": second},
    )

    ended = await client.delete(
        organizer.g(f"/calendar-events/{opened.json()['id']}"),
        headers=organizer.headers,
        params={"scope": "following"},
    )
    assert ended.status_code == 204
    assert (
        await _notifications_for(
            session, attendee.user.id, NotificationType.event_cancelled
        )
        == []
    )


async def test_an_event_repeat_is_stored_as_picked(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A repeat is stored as picked, with the shift from the zone it was picked
    in and the latest start it can have; an all-day event's days are UTC dates,
    so its shift is none. The repeat moves with a start that moves, and an
    all-day event is found by its date."""
    (
        organizer,
        _attendee,
        guild,
        _initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    created = {}
    for title, extra, rule in (
        # Mondays at 00:30 in Berlin, which are Sundays in UTC.
        (
            "Standup",
            {"start_at": "2026-10-04T22:30:00Z"},
            "FREQ=WEEKLY;BYDAY=MO;COUNT=3",
        ),
        (
            "Market day",
            {"start_at": "2026-10-05T00:00:00Z", "all_day": True},
            "FREQ=WEEKLY;BYDAY=MO;COUNT=3",
        ),
    ):
        response = await client.post(
            organizer.g("/calendar-events/"),
            headers=organizer.headers,
            json={
                "calendar_id": calendar.id,
                "title": title,
                "end_at": "2026-10-05T23:59:59Z",
                "recurrence": rule,
                "tz": "Europe/Berlin",
                **extra,
            },
        )
        assert response.status_code == 201
        created[title] = response.json()
    weekly = "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=MO"
    assert {
        title: (event["recurrence"], event["recurrence_shift"])
        for title, event in created.items()
    } == {"Standup": (weekly, 1440), "Market day": (weekly, 0)}

    await route_session_to_guild(session, guild.id)
    standup = await session.get(CalendarEvent, created["Standup"]["id"])
    assert standup is not None
    assert standup.recurrence_until == datetime(
        2026, 10, 18, 22, 30, tzinfo=timezone.utc
    )

    # Moved to noon, still Mondays in Berlin, and now Mondays in UTC too.
    moved = await client.patch(
        organizer.g(f"/calendar-events/{created['Standup']['id']}"),
        headers=organizer.headers,
        json={
            "start_at": "2026-10-05T10:00:00Z",
            "end_at": "2026-10-05T11:00:00Z",
            "tz": "Europe/Berlin",
        },
    )
    assert (moved.json()["recurrence"], moved.json()["recurrence_shift"]) == (
        weekly,
        0,
    )

    # Monday asked for from Los Angeles begins after the all-day event's UTC
    # midnight, and from Auckland it ends before noon UTC; either way the event
    # is Monday's.
    listing = await client.get(
        organizer.g("/calendar-entries/"),
        headers=organizer.headers,
        params={
            "start_after": "2026-10-05T07:00:00Z",
            "start_before": "2026-10-06T06:59:59Z",
            "include_tasks": False,
        },
    )
    assert "Market day" in {event["title"] for event in listing.json()["events"]}
    entries = await client.get(
        organizer.g("/calendar-entries/"),
        headers=organizer.headers,
        params={
            "start_after": "2026-10-04T11:00:00Z",
            "start_before": "2026-10-05T10:59:59Z",
            "tz": "Pacific/Auckland",
            "include_events": True,
            "include_tasks": False,
        },
    )
    assert "Market day" in {event["title"] for event in entries.json()["events"]}


async def test_create_event_rejects_end_before_start(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """end_at before start_at is still rejected, on create and on an update
    that moves only one end."""
    (
        organizer,
        _attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Backwards",
            "start_at": "2026-07-03T16:00:00Z",
            "end_at": "2026-07-01T14:00:00Z",
            "all_day": False,
        },
    )
    assert response.status_code == 422

    event = await create_calendar_event(session, calendar, organizer.user)
    response = await client.patch(
        organizer.g(f"/calendar-events/{event.id}"),
        headers=organizer.headers,
        json={"end_at": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == CalendarEventMessages.ENDS_BEFORE_START

    # A required field is omitted to keep it, never nulled.
    for field in ("title", "start_at", "end_at", "all_day", "rsvp_open"):
        response = await client.patch(
            organizer.g(f"/calendar-events/{event.id}"),
            headers=organizer.headers,
            json={field: None},
        )
        assert response.status_code == 422, field
        assert "FIELD_CANNOT_BE_NULL" in response.text, field


async def test_create_event_requires_calendar_write(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A member with only read on the calendar can't create events in it."""
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)

    # The default all-members grant is read-only, so the member attendee has
    # read but not write.
    response = await client.post(
        attendee.g("/calendar-events/"),
        headers=attendee.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Sneaky",
            "start_at": "2026-07-01T15:00:00Z",
            "end_at": "2026-07-01T16:00:00Z",
            "all_day": False,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "CALENDAR_WRITE_ACCESS_REQUIRED"


async def test_move_event_between_calendars_requires_write_on_both(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Moving an event to another calendar (PATCH calendar_id) needs write on
    the destination too — a member with read-only there is refused."""
    a, guild, initiative, source, event = await _setup_event(session, acting_user)

    # A second calendar the actor (guild admin) owns → the move succeeds.
    dest = await create_calendar(session, initiative, a.user, name="Dest")
    moved = await client.patch(
        a.g(f"/calendar-events/{event.id}"),
        headers=a.headers,
        json={"calendar_id": dest.id},
    )
    assert moved.status_code == 200
    assert moved.json()["calendar_id"] == dest.id

    # A member with only read on the destination cannot move an event into it.
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=guild,
        initiative=initiative,
        initiative_role="member",
    )
    # Give the member write on the source so the block is clearly the
    # destination gate, not the source.
    grant = await client.put(
        a.g(f"/calendars/{source.id}/grants"),
        headers=a.headers,
        json=[
            {"all_initiative_members": True, "level": "read"},
            {"user_id": member.user.id, "level": "write"},
        ],
    )
    assert grant.status_code == 200
    member_event = await create_calendar_event(session, source, a.user, title="Mine")

    denied = await client.patch(
        member.g(f"/calendar-events/{member_event.id}"),
        headers=member.headers,
        json={"calendar_id": dest.id},
    )
    assert denied.status_code == 403


async def test_a_move_into_another_initiative_drops_property_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The definitions stay behind, so the values go with a move into another
    initiative, the series' overrides' too. A move inside the initiative keeps
    them. Values sent with the move reach every override, one that had its own
    included, since its own are gone."""
    a, guild, initiative, source, _ = await _setup_event(session, acting_user)
    start = datetime(2026, 10, 5, 18, tzinfo=timezone.utc)
    series = await create_calendar_event(
        session,
        source,
        a.user,
        start_at=start,
        end_at=start + timedelta(hours=1),
        recurrence="RRULE:FREQ=WEEKLY",
    )
    override = await create_calendar_event(
        session,
        source,
        a.user,
        start_at=start + timedelta(days=7, hours=1),
        end_at=start + timedelta(days=7, hours=2),
        series_id=series.id,
        original_start=start + timedelta(days=7),
        overridden_fields=["properties"],
    )
    definition = await create_property_definition(session, initiative, name="Table")
    for event in (series, override):
        await create_property_value(session, event, definition, value_text="3")
    nearby = await create_calendar(session, initiative, a.user, name="Nearby")
    other = await create_initiative(session, guild, a.user)
    elsewhere = await _enable_calendars(session, other, a.user)
    seat = await create_property_definition(session, other, name="Seat")

    async def holding_values(property_id: int | None) -> list[int]:
        await route_session_to_guild(session, guild.id)
        rows = await session.exec(
            select(PropertyValue.entity_id).where(
                PropertyValue.entity_type == "calendar_event",
                PropertyValue.entity_id.in_([series.id, override.id]),
                PropertyValue.property_id == property_id,
            )
        )
        return sorted(rows.all())

    kept = await client.patch(
        a.g(f"/calendar-events/{series.id}"),
        headers=a.headers,
        json={"calendar_id": nearby.id},
    )
    assert kept.status_code == 200
    assert await holding_values(definition.id) == sorted([series.id, override.id])

    # An initiative that keeps its content in keeps its events.
    initiative.keep_content_in = True
    session.add(initiative)
    await session.commit()
    kept_in = await client.patch(
        a.g(f"/calendar-events/{series.id}"),
        headers=a.headers,
        json={"calendar_id": elsewhere.id},
    )
    assert kept_in.json()["detail"] == "INITIATIVE_CONTENT_KEPT_IN", kept_in.text
    initiative.keep_content_in = False
    session.add(initiative)
    await session.commit()

    moved = await client.patch(
        a.g(f"/calendar-events/{series.id}"),
        headers=a.headers,
        json={
            "calendar_id": elsewhere.id,
            "properties": [{"property_id": seat.id, "value": "7"}],
        },
    )
    assert moved.status_code == 200, moved.text
    assert [p["property_id"] for p in moved.json()["properties"]] == [seat.id]
    assert await holding_values(definition.id) == []
    assert await holding_values(seat.id) == sorted([series.id, override.id])


async def test_update_event_time_notifies_attendees_as_rescheduled(
    client: AsyncClient, session: AsyncSession, acting_user
):
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(
        session, calendar, organizer.user, title="Review"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )

    response = await client.patch(
        organizer.g(f"/calendar-events/{event.id}"),
        headers=organizer.headers,
        json={"start_at": "2026-08-01T15:00:00Z", "end_at": "2026-08-01T16:00:00Z"},
    )
    assert response.status_code == 200

    updates = await _notifications_for(
        session, attendee.user.id, NotificationType.event_updated
    )
    assert len(updates) == 1
    assert updates[0].data["time_changed"] is True


async def test_delete_event_notifies_attendees(
    client: AsyncClient, session: AsyncSession, acting_user
):
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(
        session, calendar, organizer.user, title="Retro"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )

    response = await client.delete(
        organizer.g(f"/calendar-events/{event.id}"), headers=organizer.headers
    )
    assert response.status_code == 204

    cancels = await _notifications_for(
        session, attendee.user.id, NotificationType.event_cancelled
    )
    assert len(cancels) == 1


async def test_update_event_skips_declined_attendees(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An attendee who declined doesn't get reschedule/update notifications."""
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(
        session, calendar, organizer.user, title="Review"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )
    declined = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "declined"},
    )
    assert declined.status_code == 200

    response = await client.patch(
        organizer.g(f"/calendar-events/{event.id}"),
        headers=organizer.headers,
        json={"start_at": "2026-08-01T15:00:00Z", "end_at": "2026-08-01T16:00:00Z"},
    )
    assert response.status_code == 200

    updates = await _notifications_for(
        session, attendee.user.id, NotificationType.event_updated
    )
    assert updates == []


async def test_delete_event_skips_declined_attendees(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An attendee who declined doesn't get the cancellation notice."""
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(
        session, calendar, organizer.user, title="Retro"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )
    declined = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "declined"},
    )
    assert declined.status_code == 200

    response = await client.delete(
        organizer.g(f"/calendar-events/{event.id}"), headers=organizer.headers
    )
    assert response.status_code == 204

    cancels = await _notifications_for(
        session, attendee.user.id, NotificationType.event_cancelled
    )
    assert cancels == []


async def test_an_answer_is_its_members_to_give(
    client: AsyncClient, session: AsyncSession, acting_user, reading_as
):
    """In the database, someone who can edit the event and the community's
    admin can invite, and clear an answer, but neither gives one in another
    person's name nor changes what they said; the member changes their own."""
    from sqlalchemy.exc import DBAPIError

    (
        organizer,
        attendee,
        guild,
        _initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    editor = await acting_user(
        guild_role=CommunityRole.member,
        guild=guild,
        initiative=organizer.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, calendar, user=editor.user, level=ResourceAccessLevel.write
    )
    event = await create_calendar_event(session, calendar, organizer.user, title="Demo")
    invited = await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=editor.headers,
        json=[attendee.user.id],
    )
    assert invited.status_code == 200, invited.text
    answered = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "accepted"},
    )
    assert answered.status_code == 200, answered.text
    params = {"event": event.id, "member": attendee.user.id}
    change = text(
        "UPDATE calendar_event_answers SET rsvp_status = 'declined'"
        " WHERE calendar_event_id = :event AND user_id = :member"
    )
    clear = text(
        "DELETE FROM calendar_event_answers"
        " WHERE calendar_event_id = :event AND user_id = :member"
    )
    give = text(
        "INSERT INTO calendar_event_answers (calendar_event_id, user_id, rsvp_status)"
        " VALUES (:event, :member, 'declined')"
    )

    for other in (editor, organizer):
        asking = await reading_as(other.user.id, guild.id)
        with pytest.raises(DBAPIError, match="only its member changes an answer"):
            await asking.exec(change, params=params)
        await asking.rollback()
        assert (await asking.exec(clear, params=params)).rowcount == 1
        with pytest.raises(DBAPIError, match="row-level security"):
            await asking.exec(give, params=params)
        await asking.rollback()
    asking = await reading_as(attendee.user.id, guild.id)
    assert (await asking.exec(change, params=params)).rowcount == 1


async def test_rsvp_notifies_organizer(
    client: AsyncClient, session: AsyncSession, acting_user
):
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(session, calendar, organizer.user, title="Demo")
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )

    response = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "accepted"},
    )
    assert response.status_code == 200

    rsvps = await _notifications_for(
        session, organizer.user.id, NotificationType.event_rsvp
    )
    assert len(rsvps) == 1
    assert rsvps[0].data["rsvp_status"] == "accepted"

    async def reader():
        return await acting_user(
            guild_role=CommunityRole.member,
            guild=guild,
            initiative=initiative,
            initiative_role="member",
        )

    def answers(response) -> dict:
        return {a["user_id"]: a["rsvp_status"] for a in response.json()["attendees"]}

    # Open, a reader who was never invited answers and so joins.
    joiner = await reader()
    joined = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=joiner.headers,
        json={"rsvp_status": "tentative"},
    )
    assert joined.status_code == 200, joined.text
    assert answers(joined)[joiner.user.id] == "tentative"

    # Closed, those on the list still answer and anyone else is refused; an
    # editor still adds people.
    closed = await client.patch(
        organizer.g(f"/calendar-events/{event.id}"),
        headers=organizer.headers,
        json={"rsvp_open": False},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["rsvp_open"] is False
    newcomer = await reader()
    refused = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=newcomer.headers,
        json={"rsvp_status": "accepted"},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["detail"] == CalendarEventMessages.RSVP_CLOSED
    answered = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=joiner.headers,
        json={"rsvp_status": "declined"},
    )
    assert answered.status_code == 200, answered.text
    assert answers(answered)[joiner.user.id] == "declined"
    added = await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id, joiner.user.id, newcomer.user.id],
    )
    assert added.status_code == 200, added.text
    assert answers(added)[newcomer.user.id] == "pending"


async def test_guild_entries_filter_events_without_calendar_grant(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The per-guild read resolves an event through its calendar's sharing.

    Events carry no grants of their own, so calendar sharing is what decides.
    ``calendar_ids`` narrows the result; it is not how access is resolved.
    """
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    calendar = await _enable_calendars(session, admin.initiative, admin.user)
    event = await create_calendar_event(session, calendar, admin.user, title="NoGrant")
    await _drop_all_members_grant(session, admin.guild, calendar)

    path = admin.g("/calendar-entries/")
    resp = await client.get(
        path, params=_around_now(), headers=get_auth_headers(member.user)
    )
    assert resp.status_code == 200, resp.text
    assert event.id not in {item["id"] for item in resp.json()["events"]}

    # Naming the calendar narrows the result; it does not change the answer.
    resp = await client.get(
        path,
        params=_around_now(calendar_ids=[calendar.id]),
        headers=get_auth_headers(member.user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["events"] == []

    # The admin reaches it, as they do every calendar in their guild.
    resp = await client.get(
        path, params=_around_now(), headers=get_auth_headers(admin.user)
    )
    assert resp.status_code == 200, resp.text
    assert event.id in {item["id"] for item in resp.json()["events"]}


async def test_my_calendar_entries_filter_events_without_calendar_grant(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The cross-guild /me read applies the same calendar DAC filter as the
    per-guild read: a non-admin member doesn't see an event in a calendar they
    hold no grant for (even though they're an initiative member and RLS shows
    the row). Events inherit calendar access; they carry no grants of their own."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    guild = admin.guild
    initiative = admin.initiative
    calendar = await _enable_calendars(session, initiative, admin.user)
    event = await create_calendar_event(session, calendar, admin.user, title="NoGrant")

    await _drop_all_members_grant(session, guild, calendar)

    # Member: the ungranted event is hidden on /me.
    resp = await client.get(
        "/api/v1/me/calendar-entries",
        params=_around_now(),
        headers=get_auth_headers(member.user),
    )
    assert resp.status_code == 200, resp.text
    assert event.id not in {item["id"] for item in resp.json()["events"]}

    # Admin: sees it via the guild-admin bypass.
    resp = await client.get(
        "/api/v1/me/calendar-entries",
        params=_around_now(),
        headers=get_auth_headers(admin.user),
    )
    assert resp.status_code == 200, resp.text
    assert event.id in {item["id"] for item in resp.json()["events"]}


async def test_my_calendar_entries_leave_out_what_was_never_shared(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin's own calendar is what has been shared with them.

    The /me aggregate spans initiatives, so it answers what reaches the reader
    rather than what their standing could reach — an admin's authority over the
    initiative is untouched, and asking for it by name still returns the event.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)
    # `other` owns the initiative; the admin is NOT a member of it.
    other = await acting_user(
        guild_role=CommunityRole.member, guild=admin.guild, initiative=True
    )
    initiative = other.initiative
    calendar = await _enable_calendars(session, initiative, other.user)
    event = await create_calendar_event(session, calendar, other.user, title="Foreign")

    resp = await client.get(
        "/api/v1/me/calendar-entries",
        params=_around_now(),
        headers=get_auth_headers(admin.user),
    )
    assert resp.status_code == 200, resp.text
    assert event.id not in {item["id"] for item in resp.json()["events"]}

    # Named directly, the initiative answers in full — this moved navigation,
    # not authority.
    within = await client.get(
        admin.g("/calendar-entries/"),
        params=_around_now(initiative_id=initiative.id),
        headers=get_auth_headers(admin.user),
    )
    assert within.status_code == 200, within.text
    assert event.id in {item["id"] for item in within.json()["events"]}


async def _switch_calendars_on(session: AsyncSession, initiative) -> None:
    """Switch the calendar tool on for an initiative, without creating one.

    Off by default — and a guild calendar answers to this switch not at all,
    which is part of what the tests below check."""
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


class TestGuildCalendarEvents:
    """A guild calendar holds its own events and reaches into no initiative.

    Two questions, and they pull in opposite directions. Its events have to be
    *visible* — the plug-in's page and a member's own calendar are where they show,
    and until now every one of those queries required an initiative, so they
    showed nowhere at all. And its events must stay *out* of anything belonging
    to an initiative, which is the same NULL read the other way.

    The rest is what an event borrows from an initiative — its member list, its
    property definitions. A guild calendar has no initiative to borrow from, so
    those refuse rather than resolve to something else.
    """

    async def test_events_are_listed(self, client: AsyncClient, acting_user, session):
        a = await acting_user(guild_role=CommunityRole.admin)
        calendar = await create_guild_calendar(session, a.guild, a.user)
        await create_calendar_event(session, calendar, a.user, title="Club night")

        response = await client.get(
            a.g("/calendar-entries/"), headers=a.headers, params=_around_now()
        )
        assert response.status_code == 200, response.text
        assert [e["title"] for e in response.json()["events"]] == ["Club night"]

    async def test_a_member_in_no_initiative_sees_them(
        self, client: AsyncClient, acting_user, session
    ):
        """The point of the plug-in: someone in none of the guild's initiatives
        still has the guild's own calendar."""
        a = await acting_user(guild_role=CommunityRole.admin)
        calendar = await create_guild_calendar(session, a.guild, a.user)
        await create_calendar_event(session, calendar, a.user, title="Club night")
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.get(
            member.g("/calendar-entries/"),
            headers=member.headers,
            params=_around_now(),
        )
        assert response.status_code == 200, response.text
        assert [e["title"] for e in response.json()["events"]] == ["Club night"]

    async def test_they_stay_out_of_an_initiative(
        self, client: AsyncClient, acting_user, session
    ):
        """Asked for one initiative's events, a guild calendar has nothing to
        contribute — it belongs to no initiative."""
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _switch_calendars_on(session, a.initiative)
        guild_calendar = await create_guild_calendar(session, a.guild, a.user)
        await create_calendar_event(session, guild_calendar, a.user, title="Club night")
        own = await create_calendar(session, a.initiative, a.user)
        await create_calendar_event(session, own, a.user, title="Sprint review")

        response = await client.get(
            a.g("/calendar-entries/"),
            headers=a.headers,
            params=_around_now(initiative_id=a.initiative.id),
        )
        assert response.status_code == 200, response.text
        assert [e["title"] for e in response.json()["events"]] == ["Sprint review"]

    async def test_the_calendar_is_listed_but_not_under_an_initiative(
        self, client: AsyncClient, acting_user, session
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _switch_calendars_on(session, a.initiative)
        await create_guild_calendar(session, a.guild, a.user, name="Community calendar")
        await create_calendar(session, a.initiative, a.user, name="Team calendar")

        every = await client.get(a.g("/calendars/"), headers=a.headers)
        assert sorted(c["name"] for c in every.json()["items"]) == [
            "Community calendar",
            "Team calendar",
        ]

        scoped = await client.get(
            a.g("/calendars/"),
            headers=a.headers,
            params={"initiative_id": a.initiative.id},
        )
        assert [c["name"] for c in scoped.json()["items"]] == ["Team calendar"]

    async def test_anyone_in_the_guild_can_attend(
        self, client: AsyncClient, acting_user, session
    ):
        """An initiative calendar draws attendees from its initiative; a guild
        calendar has none, so the guild is who can attend — including a member
        who belongs to no initiative at all."""
        a = await acting_user(guild_role=CommunityRole.admin)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        calendar = await create_guild_calendar(session, a.guild, a.user)

        response = await client.post(
            a.g("/calendar-events/"),
            headers=a.headers,
            json={
                "calendar_id": calendar.id,
                "title": "Club night",
                "start_at": "2026-09-01T18:00:00Z",
                "end_at": "2026-09-01T20:00:00Z",
                "attendee_ids": [member.user.id],
            },
        )
        assert response.status_code == 201, response.text
        assert [at["user"]["id"] for at in response.json()["attendees"]] == [
            member.user.id
        ]

    async def test_someone_outside_the_guild_cannot_attend(
        self, client: AsyncClient, acting_user, session
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        stranger = await acting_user(guild_role=CommunityRole.admin)
        calendar = await create_guild_calendar(session, a.guild, a.user)

        response = await client.post(
            a.g("/calendar-events/"),
            headers=a.headers,
            json={
                "calendar_id": calendar.id,
                "title": "Club night",
                "start_at": "2026-09-01T18:00:00Z",
                "end_at": "2026-09-01T20:00:00Z",
                "attendee_ids": [stranger.user.id],
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == CommonMessages.PERSON_CANNOT_READ

    async def test_properties_are_refused(
        self, client: AsyncClient, acting_user, session
    ):
        """Property definitions belong to an initiative, so an event in no
        initiative holds none; clearing them is still a write it takes."""
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        definition = await create_property_definition(session, a.initiative)
        calendar = await create_guild_calendar(session, a.guild, a.user)
        event = await create_calendar_event(session, calendar, a.user)
        route = a.g(f"/properties/calendar_event/{event.id}")

        response = await client.put(
            route,
            headers=a.headers,
            json={"values": [{"property_id": definition.id, "value": "anything"}]},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == PropertyMessages.DEFINITION_NOT_FOUND

        cleared = await client.put(route, headers=a.headers, json={"values": []})
        assert cleared.status_code == 200, cleared.text
        assert cleared.json() == []

    async def test_an_event_cannot_move_across_the_scope_line(
        self, client: AsyncClient, acting_user, session
    ):
        """Both directions: an event carries its initiative attachments, so a
        move between a guild calendar and an initiative calendar is refused."""
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _switch_calendars_on(session, a.initiative)
        guild_calendar = await create_guild_calendar(session, a.guild, a.user)
        team_calendar = await create_calendar(session, a.initiative, a.user)
        guild_event = await create_calendar_event(session, guild_calendar, a.user)
        team_event = await create_calendar_event(session, team_calendar, a.user)

        out = await client.patch(
            a.g(f"/calendar-events/{guild_event.id}"),
            headers=a.headers,
            json={"calendar_id": team_calendar.id},
        )
        assert out.status_code == 400
        assert out.json()["detail"] == CalendarEventMessages.CANNOT_CROSS_SCOPE

        into = await client.patch(
            a.g(f"/calendar-events/{team_event.id}"),
            headers=a.headers,
            json={"calendar_id": guild_calendar.id},
        )
        assert into.status_code == 400
        assert into.json()["detail"] == CalendarEventMessages.CANNOT_CROSS_SCOPE


async def test_a_copied_series_takes_its_changed_occurrences_and_one_goes_alone(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A copied series' changed occurrences follow its new title unless they
    changed their own; a changed occurrence, or one date of the series, copied
    alone is an event of its own. Invitees come along, invited afresh."""
    from app.models.tenant.calendar_event import (
        CalendarEventAnswer,
        CalendarEventAttendee,
        RSVPStatus,
    )
    from app.testing import route_session_to_guild

    (
        organizer,
        attendee,
        _guild,
        _initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    start = datetime(2026, 10, 5, 10, tzinfo=timezone.utc)
    weekly = await create_calendar_event(
        session,
        calendar,
        organizer.user,
        title="Standup",
        recurrence="RRULE:FREQ=WEEKLY",
        start_at=start,
        end_at=start + timedelta(hours=1),
    )
    week = timedelta(days=7)
    moved, renamed = [
        await create_calendar_event(
            session,
            calendar,
            organizer.user,
            title=title,
            series_id=weekly.id,
            original_start=weekly.start_at + n * week,
            start_at=weekly.start_at + n * week + timedelta(hours=2),
            end_at=weekly.start_at + n * week + timedelta(hours=3),
            overridden_fields=fields,
        )
        for n, title, fields in (
            (1, "Standup", ["all_day", "end_at", "start_at"]),
            (2, "Retro", ["title"]),
        )
    ]
    session.add(
        CalendarEventAttendee(calendar_event_id=weekly.id, user_id=attendee.user.id)
    )
    session.add(
        CalendarEventAnswer(
            calendar_event_id=weekly.id,
            user_id=attendee.user.id,
            rsvp_status=RSVPStatus.accepted,
        )
    )
    await session.commit()

    series = await client.post(
        organizer.g(f"/calendar-events/{weekly.id}/duplicate"),
        headers=organizer.headers,
    )
    alone = await client.post(
        organizer.g(f"/calendar-events/{moved.id}/duplicate"),
        headers=organizer.headers,
    )
    week_four = weekly.start_at + 3 * week
    one_date = await client.post(
        organizer.g(f"/calendar-events/{weekly.id}/duplicate"),
        headers=organizer.headers,
        params={"occurrence": week_four.isoformat()},
    )

    assert series.status_code == 201, series.text
    assert alone.status_code == 201, alone.text
    series, alone = series.json(), alone.json()
    await route_session_to_guild(session, organizer.guild.id)
    assert (series["title"], series["recurrence"]) == (
        "Standup (Copy)",
        "RRULE:FREQ=WEEKLY",
    )
    assert [(a["user_id"], a["rsvp_status"]) for a in series["attendees"]] == [
        (attendee.user.id, "pending")
    ]
    changed = (
        await session.exec(
            select(CalendarEvent.title).where(CalendarEvent.series_id == series["id"])
        )
    ).all()
    assert sorted(changed) == ["Retro", "Standup (Copy)"]
    assert (alone["title"], alone["series_id"], alone["original_start"]) == (
        "Standup (Copy)",
        None,
        None,
    )
    assert datetime.fromisoformat(alone["start_at"]) == moved.start_at
    assert one_date.status_code == 201, one_date.text
    one_date = one_date.json()
    assert (one_date["recurrence"], one_date["series_id"]) == (None, None)
    assert datetime.fromisoformat(one_date["start_at"]) == week_four
    invites = await _notifications_for(
        session, attendee.user.id, NotificationType.event_invitation
    )
    assert {invite.data["event_id"] for invite in invites} == {
        series["id"],
        one_date["id"],
    }
