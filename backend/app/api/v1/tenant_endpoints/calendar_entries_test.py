"""Integration tests for the calendar-entries aggregate endpoints.

``GET /c/{community_id}/calendar-entries`` and ``GET /me/calendar-entries`` return a
union of calendar events + task markers over a date window. They must be a union
*under the existing gates* — the same events/tasks the separate list endpoints
would return for the same actor, never more.
"""

from datetime import UTC, datetime, timedelta

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.messages import CalendarEventMessages
from app.models.platform.guild import CommunityRole
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_guild_calendar,
    create_post,
    create_post_poll,
    create_project,
    create_task,
    get_auth_headers,
)
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
WINDOW_START = (NOW - timedelta(days=30)).isoformat()
WINDOW_END = (NOW + timedelta(days=30)).isoformat()


async def _enable_events(session: AsyncSession, initiative, creator):
    """Enable the calendars tool and return a calendar to hang events off."""
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    return await create_calendar(session, initiative, creator)


# ---------------------------------------------------------------------------
# Guild endpoint
# ---------------------------------------------------------------------------


async def test_guild_entries_unions_events_and_task_markers(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    calendar = await _enable_events(session, a.initiative, a.user)

    event = await create_calendar_event(
        session, calendar, a.user, title="Standup", start_at=NOW
    )
    task = await create_task(
        session, a.project, title="Ship it", due_date=NOW, assignees=[a.user]
    )
    # Another initiative's task, which the reader also sees, is not this one's.
    elsewhere = await create_initiative(session, a.guild, a.user, name="Elsewhere")
    await create_task(
        session,
        await create_project(session, elsewhere, a.user),
        due_date=NOW,
        assignees=[a.user],
    )

    response = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {e["id"] for e in body["events"]} == {event.id}
    assert {t["id"] for t in body["tasks"]} == {task.id}


async def test_guild_entries_give_each_occurrence_of_a_repeat(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """A weekly event that began before the window is there once a week, and
    one that ended before it is not. A repeating task stays where it is, and its
    next occurrences in the window come with it, up to its end. A window whose
    repeats hold more occurrences than a read expands is refused."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    calendar = await _enable_events(session, a.initiative, a.user)
    weekly = await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=NOW - timedelta(days=60),
        end_at=NOW - timedelta(days=60, minutes=-30),
        recurrence="RRULE:FREQ=WEEKLY",
    )
    await create_calendar_event(
        session,
        calendar,
        a.user,
        start_at=NOW - timedelta(days=60),
        recurrence="RRULE:FREQ=WEEKLY;COUNT=3",
    )
    task = await create_task(
        session,
        a.project,
        due_date=NOW - timedelta(days=45),
        recurrence="RRULE:FREQ=WEEKLY;COUNT=5",
        assignees=[a.user],
    )

    response = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    starts = [NOW + timedelta(days=days) for days in (-25, -18, -11, -4, 3, 10, 17, 24)]
    assert [
        (
            e["id"],
            datetime.fromisoformat(e["start_at"]),
            datetime.fromisoformat(e["end_at"]) - datetime.fromisoformat(e["start_at"]),
            datetime.fromisoformat(e["original_start"]),
        )
        for e in body["events"]
    ] == [(weekly.id, start, timedelta(minutes=30), start) for start in starts]
    assert body["tasks"] == []
    assert [
        (t["id"], datetime.fromisoformat(t["due_date"]))
        for t in body["task_occurrences"]
    ] == [
        (task.id, NOW - timedelta(days=24)),
        (task.id, NOW - timedelta(days=17)),
    ]

    params = {
        "initiative_id": a.initiative.id,
        "start_after": WINDOW_START,
        "start_before": WINDOW_END,
    }
    # Exactly eight events or two tasks fit; one fewer must refuse the window.
    for leg, key, budget in (
        ({}, "events", 8),
        ({"include_events": False}, "task_occurrences", 2),
    ):
        monkeypatch.setattr(recurrence, "MAX_EXPANDED", budget)
        accepted = await client.get(
            a.g("/calendar-entries/"), headers=a.headers, params={**params, **leg}
        )
        assert accepted.status_code == 200, accepted.text
        assert len(accepted.json()[key]) == budget

        monkeypatch.setattr(recurrence, "MAX_EXPANDED", budget - 1)
        refused = await client.get(
            a.g("/calendar-entries/"), headers=a.headers, params={**params, **leg}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == CalendarEventMessages.WINDOW_TOO_FULL


async def test_guild_entries_include_flags_skip_legs(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    calendar = await _enable_events(session, a.initiative, a.user)
    await create_calendar_event(session, calendar, a.user, start_at=NOW)
    await create_task(session, a.project, due_date=NOW, assignees=[a.user])

    only_tasks = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "include_events": "false",
        },
    )
    assert only_tasks.status_code == 200
    assert only_tasks.json()["events"] == []
    assert len(only_tasks.json()["tasks"]) == 1

    only_events = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "include_tasks": "false",
        },
    )
    assert only_events.status_code == 200
    assert len(only_events.json()["events"]) == 1
    assert only_events.json()["tasks"] == []
    # Projects and polls are asked for by name.
    assert only_events.json()["projects"] == []
    assert only_events.json()["polls"] == []

    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()
    ending = await create_project(session, a.initiative, a.user, end_date=NOW.date())
    await create_project(
        session, a.initiative, a.user, start_date=(NOW + timedelta(days=60)).date()
    )
    closing = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, closing, closes_at=NOW + timedelta(days=1))
    later = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, later, closes_at=NOW + timedelta(days=60))
    # A draft's poll is not coming up for anybody yet.
    draft = await create_post(
        session, a.initiative, a.user, published_at=None, scheduled_for=NOW
    )
    await create_post_poll(session, draft, closes_at=NOW + timedelta(days=1))

    dated = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "include_projects": "true",
            "include_polls": "true",
        },
    )
    assert dated.status_code == 200, dated.text
    assert [p["id"] for p in dated.json()["projects"]] == [ending.id]
    assert dated.json()["projects"][0]["end_date"] == NOW.date().isoformat()
    assert [p["id"] for p in dated.json()["polls"]] == [closing.id]
    assert dated.json()["polls"][0]["poll"]["closes_at"] is not None


async def test_guild_entries_hidden_from_non_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild member who is not in the initiative sees neither its events
    (DAC: no grant) nor its tasks (initiative-member RLS) — the aggregate must
    not widen visibility beyond the per-resource list endpoints."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    calendar = await _enable_events(session, owner.initiative, owner.user)
    event = await create_calendar_event(session, calendar, owner.user, start_at=NOW)
    task = await create_task(
        session, owner.project, due_date=NOW, assignees=[owner.user]
    )

    # Second guild member, deliberately NOT added to the initiative.
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    response = await client.get(
        outsider.g("/calendar-entries/"),
        headers=outsider.headers,
        params={"start_after": WINDOW_START, "start_before": WINDOW_END},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert event.id not in {e["id"] for e in body["events"]}
    assert task.id not in {t["id"] for t in body["tasks"]}


async def test_guild_entries_leave_out_an_initiative_the_reader_is_not_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Both legs of the aggregate answer the same question.

    Events and task markers sit side by side on one calendar, and it spans
    initiatives — so both follow what has been shared with the reader, a guild
    admin included. A response where one leg reached further than the other
    would be a calendar of markers for work whose events are absent.
    """
    member = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    calendar = await _enable_events(session, member.initiative, member.user)
    event = await create_calendar_event(session, calendar, member.user, start_at=NOW)
    task = await create_task(
        session, member.project, due_date=NOW, assignees=[member.user]
    )

    admin = await acting_user(guild_role=CommunityRole.admin, guild=member.guild)

    response = await client.get(
        admin.g("/calendar-entries/"),
        headers=admin.headers,
        params={"start_after": WINDOW_START, "start_before": WINDOW_END},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert event.id not in {e["id"] for e in body["events"]}
    assert task.id not in {t["id"] for t in body["tasks"]}


async def test_guild_entries_windows_tasks_by_params(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """start_after/start_before bound the task leg even when the caller sends no
    matching date filter in `conditions` — the window is a first-class param, so
    an out-of-window task is excluded and the query never runs unbounded."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    in_window = await create_task(
        session, a.project, title="In window", due_date=NOW, assignees=[a.user]
    )
    out_window = await create_task(
        session,
        a.project,
        title="Out of window",
        due_date=NOW + timedelta(days=400),
        assignees=[a.user],
    )

    response = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "include_events": "false",
        },
    )
    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["tasks"]}
    assert in_window.id in task_ids
    assert out_window.id not in task_ids

    # The window is required, may not run backwards, and is bounded.
    missing = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "start_after": WINDOW_START},
    )
    assert missing.status_code == 422
    for start, end in (
        (WINDOW_END, WINDOW_START),
        (WINDOW_START, (NOW + timedelta(days=400)).isoformat()),
    ):
        refused = await client.get(
            a.g("/calendar-entries/"),
            headers=a.headers,
            params={"start_after": start, "start_before": end},
        )
        assert refused.status_code == 422
        assert refused.json()["detail"] == CalendarEventMessages.WINDOW_INVALID


# ---------------------------------------------------------------------------
# Cross-guild /me endpoint
# ---------------------------------------------------------------------------


async def _guild_with_project(session, user, *, name):
    guild = await create_guild(session, creator=user, name=name)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user, name=f"{name} Init")
    calendar = await _enable_events(session, initiative, user)
    project = await create_project(session, initiative, user, name=f"{name} Project")
    return guild, initiative, project, calendar


async def test_guild_scope_returns_every_guild_calendar_s_events(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``scope=community`` asks by kind, so the answer does not depend on the caller
    first assembling a list of calendar ids — a list which would be one page of
    them, with everything after it silently undrawn."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    initiative_calendar = await _enable_events(session, a.initiative, a.user)
    await create_calendar_event(
        session, initiative_calendar, a.user, title="Standup", start_at=NOW
    )
    # Every task is in an initiative's project, so none is the community's.
    await create_task(session, a.project, due_date=NOW, assignees=[a.user])

    titles = []
    for index in range(3):
        calendar = await create_guild_calendar(
            session, a.guild, a.user, name=f"Guild {index}"
        )
        title = f"Guild event {index}"
        titles.append(title)
        await create_calendar_event(
            session, calendar, a.user, title=title, start_at=NOW
        )

    response = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "scope": "community",
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
        },
    )
    assert response.status_code == 200, response.text
    assert sorted(e["title"] for e in response.json()["events"]) == sorted(titles)
    assert response.json()["tasks"] == []


async def test_me_entries_aggregate_across_guilds(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """Entries from every guild, narrowed by ``guild_ids``; the guilds share
    one budget of repeating occurrences."""
    user = await create_user(session, email="cal-me@example.com")
    g1, _i1, p1, cal1 = await _guild_with_project(session, user, name="Alpha")
    g2, _i2, p2, cal2 = await _guild_with_project(session, user, name="Beta")

    weekly = "RRULE:FREQ=WEEKLY"
    event1 = await create_calendar_event(
        session, cal1, user, start_at=NOW, recurrence=weekly
    )
    event2 = await create_calendar_event(
        session, cal2, user, start_at=NOW, recurrence=weekly
    )
    task1 = await create_task(session, p1, due_date=NOW, assignees=[user])
    task2 = await create_task(session, p2, due_date=NOW, assignees=[user])

    headers = get_auth_headers(user)
    response = await client.get(
        "/api/v1/me/calendar-entries",
        headers=headers,
        params={"start_after": WINDOW_START, "start_before": WINDOW_END},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # IDs are per-guild-schema sequences, so a row is only unique as
    # (guild_id, id) once merged across guilds.
    event_keys = {(e["community_id"], e["id"]) for e in body["events"]}
    task_keys = {(t["community_id"], t["id"]) for t in body["tasks"]}
    assert {(g1.id, event1.id), (g2.id, event2.id)} <= event_keys
    assert {(g1.id, task1.id), (g2.id, task2.id)} <= task_keys

    # guild_ids narrows to a single guild.
    narrowed = await client.get(
        "/api/v1/me/calendar-entries",
        headers=headers,
        params={
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "community_ids": [g1.id],
        },
    )
    assert narrowed.status_code == 200, narrowed.text
    nbody = narrowed.json()
    narrowed_event_keys = {(e["community_id"], e["id"]) for e in nbody["events"]}
    assert (g1.id, event1.id) in narrowed_event_keys
    assert (g2.id, event2.id) not in narrowed_event_keys

    # Five per guild: ten fit exactly; nine or zero left for the second refuse.
    for budget in (10, 9, 5):
        monkeypatch.setattr(recurrence, "MAX_EXPANDED", budget)
        bounded = await client.get(
            "/api/v1/me/calendar-entries",
            headers=headers,
            params={"start_after": WINDOW_START, "start_before": WINDOW_END},
        )
        if budget == 10:
            assert bounded.status_code == 200, bounded.text
            assert len(bounded.json()["events"]) == 10
        else:
            assert bounded.status_code == 422, bounded.text
            assert bounded.json()["detail"] == CalendarEventMessages.WINDOW_TOO_FULL


async def test_me_entries_windows_tasks_by_params(
    client: AsyncClient, session: AsyncSession
):
    """The cross-guild task path applies only extracted scalar filters, so the
    calendar window can only travel as start_after/start_before — assert it
    excludes an out-of-window task rather than returning every assigned task."""
    user = await create_user(session, email="cal-me-window@example.com")
    _g, _i, project, _cal = await _guild_with_project(session, user, name="Gamma")

    in_window = await create_task(session, project, due_date=NOW, assignees=[user])
    out_window = await create_task(
        session, project, due_date=NOW + timedelta(days=400), assignees=[user]
    )

    headers = get_auth_headers(user)
    response = await client.get(
        "/api/v1/me/calendar-entries",
        headers=headers,
        params={
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "include_events": "false",
        },
    )
    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["tasks"]}
    assert in_window.id in task_ids
    assert out_window.id not in task_ids

    missing = await client.get("/api/v1/me/calendar-entries", headers=headers)
    assert missing.status_code == 422
    too_wide = await client.get(
        "/api/v1/me/calendar-entries",
        headers=headers,
        params={
            "start_after": WINDOW_START,
            "start_before": (NOW + timedelta(days=400)).isoformat(),
        },
    )
    assert too_wide.status_code == 422
    assert too_wide.json()["detail"] == CalendarEventMessages.WINDOW_INVALID
