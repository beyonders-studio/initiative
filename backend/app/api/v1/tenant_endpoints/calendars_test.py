"""Tests for the calendar container endpoints — CRUD, sharing, and the
authorization gates (initiative isolation, role create gate, feature gate,
DAC levels, guild-admin override)."""

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.api_key import UserApiKey
from app.models.platform.guild import CommunityRole
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    strip_non_owner_grants,
    create_calendar,
    create_calendar_event,
    create_guild_plugin,
    route_session_to_guild,
    create_initiative,
    create_guild_calendar,
    create_resource_grant,
)

CALENDAR_PLUGIN = {
    "plugin_kind": "tool_instance",
    "tool": "calendar",
    "default_name": "Community calendar",
}


async def _install_calendar_plugin(session, guild, creator):
    """The guild calendar plug-in, which is what holds a guild's calendars."""
    return await create_guild_plugin(
        session,
        guild,
        creator,
        definition=CALENDAR_PLUGIN,
        name="Community calendar",
        plugin_kind="tool_instance",
    )


async def _calendars_enabled(session: AsyncSession, initiative) -> None:
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_calendar(client: AsyncClient, acting_user, session):
    """A PM creates a calendar: creator owner grant + the default
    all-initiative-members read grant."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _calendars_enabled(session, a.initiative)

    response = await client.post(
        a.g("/calendars/"),
        headers=a.headers,
        json={
            "name": "Raid Nights",
            "description": "Weekly schedule",
            "color": "#7c3aed",
            "initiative_id": a.initiative.id,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Raid Nights"
    assert data["description"] == "Weekly schedule"
    assert data["color"] == "#7c3aed"
    assert data["initiative_id"] == a.initiative.id
    assert data["created_by"] == a.user.id
    assert data["can"]["delete"] is True
    grant_shapes = {
        (g["level"], g["all_initiative_members"], g["user_id"]) for g in data["grants"]
    }
    assert ("owner", False, a.user.id) in grant_shapes
    assert ("read", True, None) in grant_shapes


async def test_create_calendar_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    """calendars_enabled is the initiative's tool gate — off means 403 even
    for a guild admin."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    # The factory switches every tool on, so a test about one being OFF
    # turns it off.
    a.initiative.calendars_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/calendars/"),
        headers=a.headers,
        json={"name": "Too Soon", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CALENDARS_NOT_ENABLED"


async def test_create_calendar_non_pm_forbidden(
    client: AsyncClient, acting_user, session
):
    """A plain member lacks create_calendars — the role permission gate."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _calendars_enabled(session, admin.initiative)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    response = await client.post(
        member.g("/calendars/"),
        headers=member.headers,
        json={"name": "Forbidden", "initiative_id": admin.initiative.id},
    )

    assert response.status_code == 403


async def test_get_calendar(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _calendars_enabled(session, a.initiative)
    calendar = await create_calendar(session, a.initiative, a.user, name="Mine")

    response = await client.get(a.g(f"/calendars/{calendar.id}"), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == calendar.id
    assert data["can"]["delete"] is True


async def test_list_calendars_dac_filtered(client: AsyncClient, acting_user, session):
    """The list applies calendar sharing, and it spans initiatives — so it
    answers what has been shared with the reader, a guild admin included.
    Naming the initiative is what asks about their standing in it, and that
    still answers with all of its calendars."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)
    shared = await create_calendar(session, a.initiative, a.user, name="Shared")
    secret = await create_calendar(session, a.initiative, a.user, name="Secret")
    await strip_non_owner_grants(session, secret, a.user.id)

    member_list = await client.get(member.g("/calendars/"), headers=member.headers)
    assert member_list.status_code == 200
    member_names = {c["name"] for c in member_list.json()["items"]}
    assert shared.name in member_names
    assert secret.name not in member_names

    admin_list = await client.get(admin.g("/calendars/"), headers=admin.headers)
    admin_names = {c["name"] for c in admin_list.json()["items"]}
    assert secret.name not in admin_names

    within = await client.get(
        admin.g(f"/calendars/?initiative_id={a.initiative.id}"),
        headers=admin.headers,
    )
    assert within.status_code == 200, within.text
    assert {shared.name, secret.name} <= {c["name"] for c in within.json()["items"]}


async def test_calendar_404_outside_initiative(
    client: AsyncClient, acting_user, session
):
    """The hard isolation boundary: a guild member NOT in the initiative gets
    404 (RLS hides the row), not 403."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    calendar = await create_calendar(session, a.initiative, a.user, name="Cleared")
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    response = await client.get(
        outsider.g(f"/calendars/{calendar.id}"), headers=outsider.headers
    )

    assert response.status_code == 404


async def test_update_calendar_requires_write(
    client: AsyncClient, acting_user, session
):
    """Rename needs write: the default all-members read grant is not enough."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    calendar = await create_calendar(session, a.initiative, a.user, name="Before")

    denied = await client.patch(
        reader.g(f"/calendars/{calendar.id}"),
        headers=reader.headers,
        json={"name": "Hijacked"},
    )
    assert denied.status_code == 403

    renamed = await client.patch(
        a.g(f"/calendars/{calendar.id}"),
        headers=a.headers,
        json={"name": "After", "color": "#16a34a"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "After"
    assert renamed.json()["color"] == "#16a34a"

    # A required field is omitted to keep it, never nulled.
    for field in ("name", "color"):
        response = await client.patch(
            a.g(f"/calendars/{calendar.id}"), headers=a.headers, json={field: None}
        )
        assert response.status_code == 422, field
        assert "FIELD_CANNOT_BE_NULL" in response.text, field


async def test_delete_calendar_owner_only_and_cascades(
    client: AsyncClient, acting_user, session
):
    """Delete is owner (or guild admin); the soft delete cascades to the
    calendar's events."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    writer = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    calendar = await create_calendar(session, a.initiative, a.user, name="Doomed")
    event = await create_calendar_event(session, calendar, a.user, title="Going too")
    # Upgrade the writer to write (still not owner).
    grants = await client.put(
        a.g(f"/calendars/{calendar.id}/grants"),
        headers=a.headers,
        json=[
            {"all_initiative_members": True, "level": "read"},
            {"user_id": writer.user.id, "level": "write"},
        ],
    )
    assert grants.status_code == 200

    denied = await client.delete(
        writer.g(f"/calendars/{calendar.id}"), headers=writer.headers
    )
    assert denied.status_code == 403

    deleted = await client.delete(a.g(f"/calendars/{calendar.id}"), headers=a.headers)
    assert deleted.status_code == 204

    gone = await client.get(a.g(f"/calendars/{calendar.id}"), headers=a.headers)
    assert gone.status_code == 404

    # The event is soft-deleted with its calendar.
    await route_session_to_guild(session, a.guild.id)
    row = (
        await session.exec(
            select(CalendarEvent)
            .where(CalendarEvent.id == event.id)
            .execution_options(include_deleted=True)
        )
    ).one()
    assert row.deleted_at is not None


async def test_guild_admin_can_delete_any_calendar(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    calendar = await create_calendar(session, a.initiative, a.user, name="Anyone's")
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)

    response = await client.delete(
        admin.g(f"/calendars/{calendar.id}"), headers=admin.headers
    )

    assert response.status_code == 204


async def test_calendar_counts_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Grouped counts mirror the list: DAC-visible calendars in calendars-enabled
    initiatives, and never a guild calendar — the sidebar rows the counts sit on
    are initiative rows, and a guild calendar belongs to none of them."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _calendars_enabled(session, admin.initiative)
    disabled_initiative = await create_initiative(
        session, admin.guild, admin.user, calendars_enabled=False
    )

    await create_calendar(session, admin.initiative, admin.user, name="Team")
    await create_calendar(session, disabled_initiative, admin.user, name="Hidden")
    await create_guild_calendar(session, admin.guild, admin.user)

    response = await client.get(
        admin.g("/tools/counts/by-initiative"), headers=admin.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["calendar"] == {str(admin.initiative.id): 1}


# ---------------------------------------------------------------------------
# Guild calendars — the ones the calendar plug-in holds
# ---------------------------------------------------------------------------


async def test_a_guild_calendar_is_the_admin_s_and_the_install_owns_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """No initiative means no initiative gate: a guild calendar is the guild
    admin's to make. The calendar plug-in's install owns it, which is what makes it
    one of the plug-in's artifacts and what uninstalling trashes."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    plugin = await _install_calendar_plugin(session, admin.guild, admin.user)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    refused = await client.post(
        member.g("/calendars/"), headers=member.headers, json={"name": "Holidays"}
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "COMMUNITY_ADMIN_REQUIRED"

    response = await client.post(
        admin.g("/calendars/"),
        headers=admin.headers,
        json={"name": "Holidays", "color": "#22c55e"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["initiative_id"] is None
    assert body["can"]["delete"] is True

    await route_session_to_guild(session, admin.guild.id)
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "calendar",
                ResourceGrant.resource_id == body["id"],
            )
        )
    ).all()
    # The install owns it, and the default sharing reads as the whole guild.
    assert {
        (g.plugin_install_id, g.user_id, str(g.level), g.all_initiative_members)
        for g in grants
    } == {(plugin.id, None, "owner", False), (None, None, "read", True)}
    assert all(g.initiative_id is None for g in grants)

    listed = await client.get(admin.g(f"/plugins/{plugin.id}"), headers=admin.headers)
    assert listed.json()["artifacts"] == [{"type": "calendar", "id": body["id"]}]


async def test_a_write_grant_writes_a_guild_calendar_s_events(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The admin decides who writes what a guild calendar holds. Changing the
    calendar itself — renaming it, archiving it — stays the admin's."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    plugin = await _install_calendar_plugin(session, admin.guild, admin.user)
    calendar = await create_guild_calendar(
        session, admin.guild, admin.user, plugin=plugin
    )
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await create_resource_grant(
        session, calendar, level=ResourceAccessLevel.write, user=member.user
    )

    renamed = await client.patch(
        member.g(f"/calendars/{calendar.id}"),
        headers=member.headers,
        json={"name": "Mine now"},
    )
    assert renamed.status_code == 403
    assert renamed.json()["detail"] == "CALENDAR_WRITE_ACCESS_REQUIRED"

    archived = await client.post(
        member.g(f"/archive/calendar/{calendar.id}"), headers=member.headers
    )
    assert archived.status_code == 403

    event = await client.post(
        member.g("/calendar-events/"),
        headers=member.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Club night",
            "start_at": "2026-07-01T19:00:00Z",
            "end_at": "2026-07-01T22:00:00Z",
            "all_day": False,
        },
    )
    assert event.status_code == 201, event.text


async def test_a_guild_calendar_needs_the_plugin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Without the plug-in there is no entry that reaches a guild calendar, so one
    is refused rather than created where nothing links to it."""
    a = await acting_user(guild_role=CommunityRole.admin)

    response = await client.post(
        a.g("/calendars/"), headers=a.headers, json={"name": "Holidays"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "CALENDAR_COMMUNITY_PLUGIN_REQUIRED"


async def test_guild_scope_lists_only_the_guild_s_own(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``scope=community`` is the calendar plug-in's own list: guild calendars, and no
    initiative's."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _calendars_enabled(session, a.initiative)
    await create_calendar(session, a.initiative, a.user, name="Team")
    guild_calendar = await create_guild_calendar(
        session, a.guild, a.user, name="Holidays"
    )

    response = await client.get(
        a.g("/calendars/"), headers=a.headers, params={"scope": "community"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["id"] for c in body["items"]] == [guild_calendar.id]
    assert body["total_count"] == 1


async def test_a_guild_calendar_is_hidden_when_it_is_not_shared(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Guild scope clears the initiative gate, not the sharing one: what a
    member made privately stays theirs.

    A guild calendar is refused rather than hidden — the initiative gate, which
    is what turns a refusal into a 404 for initiative content, has nothing to
    say about a row belonging to no initiative. Sharing is the whole of the
    answer here.
    """
    a = await acting_user(guild_role=CommunityRole.member)
    owner = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    calendar = await create_guild_calendar(
        session, a.guild, owner.user, name="Mine", shared_with_everyone=False
    )

    response = await client.get(
        a.g("/calendars/"), headers=a.headers, params={"scope": "community"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []

    assert (
        await client.get(a.g(f"/calendars/{calendar.id}"), headers=a.headers)
    ).status_code == 403


async def test_a_copy_has_its_series_its_changed_occurrences_and_invitees(
    client: AsyncClient, acting_user, session
):
    """An occurrence changed on its own follows its series' copy, and an
    invitee comes along with their answer starting over."""
    from datetime import timedelta

    from app.models.tenant.calendar_event import (
        CalendarEventAnswer,
        CalendarEventAttendee,
        RSVPStatus,
    )
    from app.testing import route_session_to_guild

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _calendars_enabled(session, a.initiative)
    calendar = await create_calendar(session, a.initiative, a.user)
    weekly = await create_calendar_event(
        session, calendar, a.user, title="Standup", recurrence="RRULE:FREQ=WEEKLY"
    )
    week_two = weekly.start_at + timedelta(days=7)
    await create_calendar_event(
        session,
        calendar,
        a.user,
        title="Standup, moved",
        series_id=weekly.id,
        original_start=week_two,
        start_at=week_two + timedelta(hours=2),
        end_at=week_two + timedelta(hours=3),
        overridden_fields=["title", "start_at", "end_at"],
    )
    session.add(CalendarEventAttendee(calendar_event_id=weekly.id, user_id=a.user.id))
    session.add(
        CalendarEventAnswer(
            calendar_event_id=weekly.id,
            user_id=a.user.id,
            rsvp_status=RSVPStatus.accepted,
        )
    )
    await session.commit()

    response = await client.post(
        a.g(f"/calendars/{calendar.id}/duplicate"), headers=a.headers
    )

    assert response.status_code == 201, response.text
    await route_session_to_guild(session, a.guild.id)
    events = (
        await session.exec(
            select(CalendarEvent).where(
                CalendarEvent.calendar_id == response.json()["id"]
            )
        )
    ).all()
    (series,) = [e for e in events if e.series_id is None]
    (moved,) = [e for e in events if e.series_id is not None]
    assert (series.title, series.recurrence) == ("Standup", "RRULE:FREQ=WEEKLY")
    assert (moved.series_id, moved.title, moved.original_start) == (
        series.id,
        "Standup, moved",
        week_two,
    )
    invited = (
        await session.exec(
            select(CalendarEventAttendee.user_id).where(
                CalendarEventAttendee.calendar_event_id == series.id
            )
        )
    ).all()
    assert invited == [a.user.id]
    # The copy invites them again; what they answered was to the original.
    answered = await session.exec(
        select(CalendarEventAnswer).where(
            CalendarEventAnswer.calendar_event_id == series.id
        )
    )
    assert answered.all() == []


async def test_a_copy_elsewhere_lets_go_of_invitees_who_cannot_read_it(
    client: AsyncClient, acting_user, session
):
    from app.models.tenant.calendar_event import CalendarEventAttendee
    from app.testing import route_session_to_guild

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    b = await acting_user(
        guild_role=CommunityRole.member, guild=a.guild, initiative=a.initiative
    )
    await _calendars_enabled(session, a.initiative)
    elsewhere = await create_initiative(
        session, a.guild, a.user, calendars_enabled=True
    )
    calendar = await create_calendar(session, a.initiative, a.user)
    event = await create_calendar_event(session, calendar, a.user)
    session.add_all(
        CalendarEventAttendee(calendar_event_id=event.id, user_id=user.id)
        for user in (a.user, b.user)
    )
    await session.commit()

    response = await client.post(
        a.g(f"/calendars/{calendar.id}/duplicate"),
        headers=a.headers,
        json={"target_initiative_id": elsewhere.id},
    )

    assert response.status_code == 201, response.text
    await route_session_to_guild(session, a.guild.id)
    invited = (
        await session.exec(
            select(CalendarEventAttendee.user_id)
            .join(CalendarEvent)
            .where(CalendarEvent.calendar_id == response.json()["id"])
        )
    ).all()
    assert invited == [a.user.id]


async def test_a_copy_of_the_communitys_calendar_names_its_initiative(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _calendars_enabled(session, a.initiative)
    calendar = await create_guild_calendar(session, a.guild, a.user)
    path = a.g(f"/calendars/{calendar.id}/duplicate")

    nowhere = await client.post(path, headers=a.headers)
    placed = await client.post(
        path, headers=a.headers, json={"target_initiative_id": a.initiative.id}
    )

    assert nowhere.status_code == 404
    assert nowhere.json()["detail"] == "INITIATIVE_NOT_FOUND"
    assert placed.status_code == 201, placed.text
    assert placed.json()["initiative_id"] == a.initiative.id


# ---------------------------------------------------------------------------
# Subscription feed
# ---------------------------------------------------------------------------


async def _feed_link(client: AsyncClient, actor, calendar) -> str:
    """A subscription link's token, made as the calendar page makes it."""
    created = await client.post(
        "/api/v1/me/api-keys",
        headers=actor.headers,
        json={
            "name": calendar.name,
            "community_id": actor.guild.id,
            "resource_type": "calendar",
            "resource_id": calendar.id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["api_key"]["read_only"] is True
    return created.json()["secret"]


def _feed(actor, calendar_id: int, token: str) -> str:
    return actor.g(f"/calendars/{calendar_id}/feed.ics") + f"?token={token}"


async def _member_with_calendar(session, acting_user):
    """An admin's calendar, shared with the initiative, one event on it, and a
    member who reads it."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    await _calendars_enabled(session, admin.initiative)
    calendar = await create_calendar(session, admin.initiative, admin.user)
    await create_calendar_event(session, calendar, admin.user, title="Standup")
    return admin, member, calendar


async def test_a_feed_link_serves_its_calendar_and_nothing_else(
    client: AsyncClient, acting_user, session
):
    admin, member, calendar = await _member_with_calendar(session, acting_user)
    other = await create_calendar(session, admin.initiative, admin.user)
    token = await _feed_link(client, member, calendar)

    served = await client.get(_feed(member, calendar.id, token))
    assert served.status_code == 200, served.text
    assert served.headers["content-type"].startswith("text/calendar")
    assert "SUMMARY:Standup" in served.text
    unchanged = await client.get(
        _feed(member, calendar.id, token),
        headers={"If-None-Match": f'"other", W/{served.headers["ETag"]}'},
    )
    assert unchanged.status_code == 304

    # The calendar it names, by its feed, and nothing else: not another
    # calendar's feed, not the same id in another community, and not the API.
    elsewhere = f"/api/v1/c/{admin.guild.id + 1}/calendars/{calendar.id}/feed.ics"
    for refused in (
        await client.get(_feed(member, other.id, token)),
        await client.get(f"{elsewhere}?token={token}"),
        await client.get(
            member.g(f"/calendars/{calendar.id}"),
            headers={"Authorization": f"Bearer {token}"},
        ),
    ):
        assert refused.status_code == 403
        assert refused.json()["detail"] == "USER_API_KEY_RESOURCE_ONLY"

    # A key that names no calendar is not a feed link.
    plain = await client.post(
        "/api/v1/me/api-keys", headers=member.headers, json={"name": "k"}
    )
    assert (
        await client.get(_feed(member, calendar.id, plain.json()["secret"]))
    ).status_code == 403

    # A new link replaces the old one.
    await _feed_link(client, member, calendar)
    assert (await client.get(_feed(member, calendar.id, token))).status_code == 401


async def test_a_feed_follows_the_readers_access_on_every_fetch(
    client: AsyncClient, acting_user, session
):
    admin, member, calendar = await _member_with_calendar(session, acting_user)
    token = await _feed_link(client, member, calendar)
    admin_token = await _feed_link(client, admin, calendar)

    # Kept in: refused, as the calendar page's export is.
    admin.initiative.keep_content_in = True
    session.add(admin.initiative)
    await session.commit()
    kept = await client.get(_feed(admin, calendar.id, admin_token))
    assert kept.status_code == 403
    assert kept.json()["detail"] == "INITIATIVE_CONTENT_KEPT_IN"
    admin.initiative.keep_content_in = False
    session.add(admin.initiative)
    await session.commit()

    # No longer shared with them.
    await strip_non_owner_grants(session, calendar, admin.user.id)
    assert (await client.get(_feed(member, calendar.id, token))).status_code == 403

    # Out of the community: refused, and the link is gone with them.
    removed = await client.delete(
        admin.g(f"/users/{member.user.id}"), headers=admin.headers
    )
    assert removed.status_code == 204, removed.text
    assert (await client.get(_feed(member, calendar.id, token))).status_code == 401
    assert (
        await session.exec(
            select(UserApiKey).where(UserApiKey.user_id == member.user.id)
        )
    ).all() == []


async def test_a_feeds_rate_limit_counts_each_person(
    client: AsyncClient, acting_user, session, rate_limit_of_one_per_minute
):
    """Calendar apps fetch from a few addresses of their own, so the limit
    counts the person a link names rather than the address asking."""
    admin, member, calendar = await _member_with_calendar(session, acting_user)
    token = await _feed_link(client, member, calendar)
    admin_token = await _feed_link(client, admin, calendar)

    for _ in range(30):
        assert (await client.get(_feed(member, calendar.id, token))).status_code == 200
    assert (await client.get(_feed(member, calendar.id, token))).status_code == 429
    assert (await client.get(_feed(admin, calendar.id, admin_token))).status_code == 200
