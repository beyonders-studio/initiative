"""Calendars and calendar events as an installed plug-in calls them.

Each test installs a plug-in the way a community does (``install_plugin``: placed in
initiative A and not in B, granted scopes by the seat), seals an installation
token for it, and calls the calendar and event routes that name a scope: the
reads, create and update, and the event's attendee list.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import select

from app.core.messages import CalendarMessages, PluginMessages
from app.db import cohorts
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant._mixins import ActorKind
from app.models.tenant.calendar import Calendar
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.marketplace import plugin_refs
from app.services.tenant import subscription_notices
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_guild_calendar,
    create_guild_plugin,
    create_resource_grant,
    drain_notices,
    guild_of,
    guild_url,
    route_session_to_guild,
)
from app.testing.plugin_clients import (
    assert_names_nobody,
    install_headers,
    install_plugin,
    lift_person_and_guild_ids,
)


def _window() -> dict[str, str]:
    start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    return {
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=1)).isoformat(),
    }


async def _switch_on(session: Any, *initiatives: Any) -> None:
    """Turn calendars on in each of ``initiatives``."""
    await route_session_to_guild(session, guild_of(initiatives[0]))
    for initiative in initiatives:
        initiative.calendars_enabled = True
        session.add(initiative)
    await session.commit()


async def _member_of_a(acting_user: Any, installed: Any) -> Any:
    return await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


async def test_reads_the_calendars_and_events_open_to_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["calendars:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed, installed.unplaced)
    # Both are open to their initiative's members (the factory's default).
    in_a = await create_calendar(session, installed.placed, seat.user, name="A")
    in_b = await create_calendar(session, installed.unplaced, seat.user, name="B")
    event_a = await create_calendar_event(session, in_a, seat.user, title="In A")
    event_b = await create_calendar_event(session, in_b, seat.user, title="In B")
    community = await create_guild_calendar(session, installed.guild, seat.user)
    headers = install_headers(installed, ["calendars:read"])

    read = await client.get(
        guild_url(guild_id, f"/calendars/{in_a.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    assert read.json()["name"] == "A"
    assert read.json()["can"]["edit"] is False

    event = await client.get(
        guild_url(guild_id, f"/calendar-events/{event_a.id}"), headers=headers
    )
    assert event.status_code == 200, event.text
    assert event.json()["title"] == "In A"
    assert event.json()["can"]["edit"] is False

    for path in (
        f"/calendars/{in_b.id}",
        f"/calendar-events/{event_b.id}",
    ):
        response = await client.get(guild_url(guild_id, path), headers=headers)
        assert response.status_code == 404, (path, response.text)

    # A token narrowed to A reaches nothing that belongs to the community as
    # a whole.
    narrowed = install_headers(
        installed, ["calendars:read"], initiative_id=installed.placed.id
    )
    guild_level = await client.get(
        guild_url(guild_id, f"/calendars/{community.id}"), headers=narrowed
    )
    assert guild_level.status_code == 404, guild_level.text
    still_a = await client.get(
        guild_url(guild_id, f"/calendars/{in_a.id}"), headers=narrowed
    )
    assert still_a.status_code == 200, still_a.text


async def test_a_repeating_event_reads_its_next_start(
    client, session, acting_user, role_session
):
    """What a plug-in asking "is it soon?" needs of a weekly meeting: the start
    still to come, not the series' first."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=["calendars:read"]
    )
    await _switch_on(session, installed.placed)
    calendar = await create_calendar(session, installed.placed, installed.seat.user)
    first = datetime.now(UTC).replace(microsecond=0) - timedelta(days=20)
    weekly = await create_calendar_event(
        session,
        calendar,
        installed.seat.user,
        start_at=first,
        end_at=first + timedelta(hours=1),
        recurrence="RRULE:FREQ=WEEKLY",
    )
    once = await create_calendar_event(session, calendar, installed.seat.user)
    headers = install_headers(installed, ["calendars:read"])

    read = await client.get(
        guild_url(installed.guild.id, f"/calendar-events/{weekly.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    assert datetime.fromisoformat(read.json()["next_start"]) == first + timedelta(
        days=21
    )

    single = await client.get(
        guild_url(installed.guild.id, f"/calendar-events/{once.id}"), headers=headers
    )
    assert single.json()["next_start"] is None


async def test_changing_anything_needs_the_write_scope(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["calendars:read"]
    )
    seat = installed.seat
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    calendar = await create_calendar(session, installed.placed, seat.user)
    event = await create_calendar_event(session, calendar, seat.user)
    headers = install_headers(installed, ["calendars:read"])

    for method, path, body in (
        ("POST", "/calendars/", {"name": "New", "initiative_id": installed.placed.id}),
        ("PATCH", f"/calendars/{calendar.id}", {"name": "Renamed"}),
        (
            "POST",
            "/calendar-events/",
            {"calendar_id": calendar.id, "title": "New", **_window()},
        ),
        ("PATCH", f"/calendar-events/{event.id}", {"title": "Renamed"}),
        ("PUT", f"/calendar-events/{event.id}/attendees", []),
    ):
        response = await client.request(
            method, guild_url(guild_id, path), headers=headers, json=body
        )
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["detail"] == PluginMessages.SCOPE_REQUIRED


# ---------------------------------------------------------------------------
# Authorship and the boundary
# ---------------------------------------------------------------------------


async def test_what_it_creates_is_its_own_and_names_nobody(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session, acting_user, role_session, granted=["calendars:write"]
    )
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    headers = install_headers(installed, ["calendars:write"])

    created = await client.post(
        guild_url(guild_id, "/calendars/"),
        headers=headers,
        json={"name": "Made by the plug-in", "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    calendar = created.json()
    assert calendar["created_by"] is None
    assert isinstance(calendar["community_id"], str)
    assert calendar["can"]["delete"] is True
    assert_names_nobody(created.text, [installed.seat.user.id, guild_id])

    event_created = await client.post(
        guild_url(guild_id, "/calendar-events/"),
        headers=headers,
        json={"calendar_id": calendar["id"], "title": "Stand-up", **_window()},
    )
    assert event_created.status_code == 201, event_created.text
    event = event_created.json()
    assert event["created_by"] is None
    assert event["attendees"] == []
    assert event["can"]["edit"] is True
    assert_names_nobody(event_created.text, [installed.seat.user.id, guild_id])

    renamed = await client.patch(
        guild_url(guild_id, f"/calendars/{calendar['id']}"),
        headers=headers,
        json={"name": "Renamed by the plug-in"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Renamed by the plug-in"

    moved = await client.patch(
        guild_url(guild_id, f"/calendar-events/{event['id']}"),
        headers=headers,
        json={"title": "Retro"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["title"] == "Retro"

    await route_session_to_guild(session, guild_id)
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "calendar",
                ResourceGrant.resource_id == calendar["id"],
            )
        )
    ).all()
    assert [(g.level, g.plugin_install_id, g.user_id) for g in grants] == [
        (ResourceAccessLevel.owner, installed.plugin.id, None)
    ]
    stored_calendar = await session.get(Calendar, calendar["id"])
    assert stored_calendar is not None and (
        stored_calendar.created_by,
        stored_calendar.created_by_kind,
    ) == (installed.plugin.id, ActorKind.plugin)
    stored_event = await session.get(CalendarEvent, event["id"])
    assert stored_event is not None and (
        stored_event.created_by,
        stored_event.created_by_kind,
    ) == (installed.plugin.id, ActorKind.plugin)


async def test_it_shares_nothing_and_makes_no_community_calendar(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["calendars:write"]
    )
    guild_id = installed.guild.id
    await _switch_on(session, installed.placed)
    headers = install_headers(installed, ["calendars:write"])

    shared = await client.post(
        guild_url(guild_id, "/calendars/"),
        headers=headers,
        json={
            "name": "Shared",
            "initiative_id": installed.placed.id,
            "grants": [{"all_initiative_members": True, "level": "write"}],
        },
    )
    assert shared.status_code == 403, shared.text
    assert shared.json()["detail"] == PluginMessages.SHARING_NOT_AVAILABLE

    community = await client.post(
        guild_url(guild_id, "/calendars/"), headers=headers, json={"name": "Everyone"}
    )
    assert community.status_code == 403, community.text
    assert community.json()["detail"] == CalendarMessages.PLUGIN_INITIATIVE_REQUIRED


async def test_invites_attendees_by_reference_in_its_own_name(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["calendars:write", "members:read"],
    )
    seat = installed.seat
    guild_id = installed.guild.id
    attendee = await _member_of_a(acting_user, installed)
    await _switch_on(session, installed.placed)
    # Something the attendee made, which is how the install learns their
    # reference.
    theirs = await create_calendar(session, installed.placed, seat.user)
    their_event = await create_calendar_event(session, theirs, attendee.user)
    headers = install_headers(installed, ["calendars:write", "members:read"])

    read = await client.get(
        guild_url(guild_id, f"/calendar-events/{their_event.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    reference = read.json()["created_by"]
    assert isinstance(reference, str)

    calendar = await client.post(
        guild_url(guild_id, "/calendars/"),
        headers=headers,
        json={"name": "Plug-in calendar", "initiative_id": installed.placed.id},
    )
    assert calendar.status_code == 201, calendar.text
    # Open to the initiative, so the attendee can read what they are named on.
    await route_session_to_guild(session, guild_id)
    await create_resource_grant(
        session,
        await session.get(Calendar, calendar.json()["id"]),
        all_initiative_members=True,
    )
    created = await client.post(
        guild_url(guild_id, "/calendar-events/"),
        headers=headers,
        json={
            "calendar_id": calendar.json()["id"],
            "title": "Planning",
            **_window(),
        },
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    response = await client.put(
        guild_url(guild_id, f"/calendar-events/{event_id}/attendees"),
        headers=headers,
        json=[reference],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [a["user_id"] for a in body["attendees"]] == [reference]
    assert body["attendees"][0]["user"]["id"] == reference
    assert body["attendees"][0]["user"]["username"] == attendee.user.username
    assert_names_nobody(response.text, [seat.user.id, attendee.user.id, guild_id])

    await drain_notices()
    invitations = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == attendee.user.id,
                Notification.type == NotificationType.event_invitation,
            )
        )
    ).all()
    assert len(invitations) == 1
    assert invitations[0].data["organizer_name"] == installed.plugin.name
    assert invitations[0].data["event_id"] == event_id

    # Moving it is news to whoever is going, named for the plug-in, though it
    # is no person's change.
    async with cohorts.system_session(guild_id) as system:
        await subscription_notices.tell_subscribers(system, guild_id)
    moved = await client.patch(
        guild_url(guild_id, f"/calendar-events/{event_id}"),
        headers=headers,
        json={"title": "Planning (moved)", **_window()},
    )
    assert moved.status_code == 200, moved.text
    async with cohorts.system_session(guild_id) as system:
        await subscription_notices.tell_subscribers(system, guild_id)
    await drain_notices()
    (line,) = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == attendee.user.id,
                Notification.type == NotificationType.assigned_activity,
            )
        )
    ).all()
    assert line.data["entity_id"] == event_id
    assert line.data["commenters"] == [{"id": None, "name": installed.plugin.name}]


async def test_an_attendee_it_does_not_know_is_unprocessable(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["calendars:write", "members:read"],
    )
    seat = installed.seat
    guild_id = installed.guild.id
    attendee = await _member_of_a(acting_user, installed)
    await _switch_on(session, installed.placed)
    calendar = await create_calendar(session, installed.placed, seat.user)
    event = await create_calendar_event(session, calendar, seat.user)
    # Open to A's members for writing, so the refusals below are the
    # references' and nothing else's.
    await route_session_to_guild(session, guild_id)
    members_grant = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "calendar",
                ResourceGrant.resource_id == calendar.id,
                ResourceGrant.all_initiative_members == True,
            )
        )
    ).one()
    members_grant.level = ResourceAccessLevel.write
    session.add(members_grant)
    await session.commit()
    other = await create_guild_plugin(
        session,
        installed.guild,
        seat.user,
        definition={
            "plugin_kind": "service",
            "service": {"public_id": "tests.token-client-two", "protocol": 1},
        },
        listing_uid="TOKENCLIENT002",
    )
    foreign = await plugin_refs.ensure_plugin_ref(
        guild_id=guild_id,
        public_id=other.definition["service"]["public_id"],
        user_id=attendee.user.id,
    )
    headers = install_headers(installed, ["calendars:write", "members:read"])

    for attendees in ([attendee.user.id], [foreign], ["uplu_" + "x" * 32]):
        response = await client.put(
            guild_url(guild_id, f"/calendar-events/{event.id}/attendees"),
            headers=headers,
            json=attendees,
        )
        assert response.status_code == 422, (attendees, response.text)
        assert PluginMessages.REFERENCE_UNKNOWN in {
            error["msg"] for error in response.json()["detail"]
        }

    created = await client.post(
        guild_url(guild_id, "/calendar-events/"),
        headers=headers,
        json={
            "calendar_id": calendar.id,
            "title": "Named by row id",
            "attendee_ids": [attendee.user.id],
            **_window(),
        },
    )
    assert created.status_code == 422, created.text
