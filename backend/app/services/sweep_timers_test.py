"""Sweep timers: the write arms them, the worker visits only what is due."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import cast

import asyncpg
import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from conftest import TEST_DATABASE_URL
from app.core import metrics
from app.core.config import settings
from app.db import cohorts, timers
from app.models.platform.guild import CommunityRole, CommunityStatus, Guild
from app.models.platform.community_timer import CommunityTimer
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.post import Post
from app.models.tenant.task import TaskStatus, TaskStatusCategory
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.tenant.personal_item import PersonalItem
from app.models.tenant.webhook_subscription import WebhookSubscription
from app.models.platform.user_notification_prefs import DigestCadence
from app.services import notifications, sweep_timers
from app.services.guild_sweeps import Scan, Scope
from app.services.platform import notify_bus
from app.services.platform.notification_prefs import DigestSchedule, digest_slot
from app.services.tenant import outbox_poller, personal_items, post_publication
from app.services.tenant.expiry import Expiring
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_guild,
    create_guild_plugin,
    create_marketplace_listing,
    create_initiative,
    create_post,
    create_project,
    create_task,
    create_user,
    route_session_to_guild,
    route_system,
)


async def _community(session: AsyncSession, **guild):
    author = await create_user(session)
    community = await create_guild(session, creator=author, **guild)
    initiative = await create_initiative(session, community, author)
    return author, initiative, cast(int, community.id)


async def _scheduled(session, initiative, author, *, due_in: timedelta) -> int:
    """A notice waiting for its time, written the way a factory writes: on a
    session routed to no community, which arms nothing."""
    post = await create_post(
        session,
        initiative,
        author,
        published_at=None,
        scheduled_for=datetime.now(timezone.utc) + due_in,
    )
    return cast(int, post.id)


async def _timers(
    session: AsyncSession, kind: str | None = None
) -> list[tuple[int, str, datetime]]:
    rows = await session.exec(
        text(
            "SELECT community_id, kind, due_at FROM public.community_timers"
            " ORDER BY due_at"
        )
    )
    return [tuple(row) for row in rows.all() if kind in (None, row.kind)]  # type: ignore[misc]


async def _as_community(community_id: int, *statements) -> None:
    """Run ``statements`` routed into the community the way its sweeps and
    requests are, and commit."""
    async with cohorts.system_session(community_id) as routed:
        await route_system(routed, guild_id=community_id)
        for statement in statements:
            await routed.exec(statement)
        await routed.commit()


async def _due_now(session: AsyncSession, community_id: int, kind: str) -> None:
    """A timer that has come due, however it was armed."""
    await session.exec(
        text(
            "INSERT INTO public.community_timers (community_id, kind, due_at)"
            " VALUES (:community, :kind, now())"
        ).bindparams(community=community_id, kind=kind)
    )
    await session.commit()


def _reschedule(post_id: int, at: datetime):
    return update(Post).where(Post.id == post_id).values(scheduled_for=at)  # type: ignore[arg-type]


async def test_a_routed_write_arms_its_timer_once(session: AsyncSession):
    """Only a write routed into the community arms, the earliest timer wins,
    and a later one adds nothing while it waits."""
    author, initiative, community_id = await _community(session)
    first = await _scheduled(session, initiative, author, due_in=timedelta(hours=2))
    second = await _scheduled(session, initiative, author, due_in=timedelta(hours=3))
    assert await _timers(session) == []

    soon = datetime.now(timezone.utc) + timedelta(hours=1)
    await _as_community(community_id, _reschedule(first, soon))
    await _as_community(community_id, _reschedule(second, soon + timedelta(hours=1)))
    assert await _timers(session) == [(community_id, "posts", soon)]

    sooner = soon - timedelta(minutes=30)
    await _as_community(community_id, _reschedule(second, sooner))
    assert [due for _c, _k, due in await _timers(session)] == [sooner, soon]


async def test_a_timer_due_at_once_wakes_the_worker(session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL_LISTEN", TEST_DATABASE_URL)
    _author, _initiative, community_id = await _community(session)
    woken = asyncio.Event()
    listener = await asyncpg.connect(dsn=notify_bus._dsn())
    try:
        await listener.add_listener(timers.WAKE_CHANNEL, lambda *_: woken.set())

        await _as_community(
            community_id, text("SELECT public.arm_timer('posts', now())")
        )

        await asyncio.wait_for(woken.wait(), timeout=10)
    finally:
        await listener.close()


async def test_work_brought_back_arms_its_sweep(session: AsyncSession):
    """A done status reopened, and updates switched back on."""
    author, initiative, community_id = await _community(session)
    project = await create_project(session, initiative, author)
    await create_task(session, project, status_category=TaskStatusCategory.done)
    plugin = await create_guild_plugin(
        session,
        await session.get(Guild, community_id),
        author,
        definition={
            "plugin_kind": "service",
            "service": {"public_id": "tests.reopen", "protocol": 1},
        },
        auto_update=False,
    )

    await _as_community(
        community_id,
        update(TaskStatus).values(category=TaskStatusCategory.todo),
        update(GuildPlugin)
        .where(GuildPlugin.id == plugin.id)  # type: ignore[arg-type]
        .values(auto_update=True),
    )

    assert {kind for _c, kind, _due in await _timers(session)} >= {
        "overdue",
        "plugin_updates",
    }


async def test_a_change_arms_the_upkeep_and_the_webhook_backstop(
    session: AsyncSession,
):
    author, initiative, community_id = await _community(session)
    post = await create_post(session, initiative, author)

    await _as_community(
        community_id,
        update(Post).where(Post.id == post.id).values(name="Renamed"),  # type: ignore[arg-type]
    )

    assert {kind for _c, kind, _due in await _timers(session)} == {
        "webhooks",
        "subscriptions",
        "expiry",
        "engagement",
        sweep_timers.RECONCILE,
    }


async def test_the_worker_runs_what_is_due_and_arms_the_next(session: AsyncSession):
    author, initiative, community_id = await _community(session)
    due = await _scheduled(session, initiative, author, due_in=timedelta(hours=1))
    later = datetime.now(timezone.utc) + timedelta(hours=3)
    pending = await _scheduled(session, initiative, author, due_in=timedelta(hours=3))
    await _as_community(
        community_id,
        _reschedule(due, datetime.now(timezone.utc) - timedelta(minutes=1)),
        _reschedule(pending, later),
    )

    await sweep_timers.process_due_timers()

    await route_session_to_guild(session, community_id)
    published = (
        await session.exec(select(Post.id).where(Post.published_at.is_not(None)))  # type: ignore[union-attr]
    ).all()
    assert published == [due]
    # Publishing is a change of its own, which arms the community's upkeep.
    assert await _timers(session, "posts") == [(community_id, "posts", later)]


async def test_a_community_that_cannot_take_the_sweep_keeps_its_timer(
    session: AsyncSession,
):
    """Suspended, its posts wait; the timer comes back each lease until it
    returns."""
    author, initiative, community_id = await _community(
        session, status=CommunityStatus.suspended.value
    )
    post_id = await _scheduled(
        session, initiative, author, due_in=-timedelta(minutes=1)
    )
    await _due_now(session, community_id, "posts")

    await sweep_timers.process_due_timers()

    [(_c, kind, due)] = await _timers(session)
    assert kind == "posts" and due > datetime.now(timezone.utc)
    await route_session_to_guild(session, community_id)
    assert (await session.get(Post, post_id)).published_at is None  # type: ignore[union-attr]


async def test_a_sweep_that_calls_out_runs_in_its_own_lane(
    session: AsyncSession, monkeypatch
):
    """The database-only lane leaves a webhook timer alone, so a slow target
    never holds it up; the outward lane runs it."""
    _author, _initiative, community_id = await _community(session)
    await _due_now(session, community_id, "webhooks")
    drained: list[int] = []

    async def drain(_session, guild_id, **_kwargs):
        drained.append(guild_id)

    monkeypatch.setattr(outbox_poller, "drain_guild", drain)
    sweep_timers.sweeps.cache_clear()
    try:
        await sweep_timers.process_due_timers()
        assert drained == []
        [(_c, _k, due)] = await _timers(session, "webhooks")
        assert due <= datetime.now(timezone.utc)

        await sweep_timers.process_due_timers(outward=True)
        assert drained == [community_id]
    finally:
        sweep_timers.sweeps.cache_clear()


async def test_a_failed_visit_keeps_its_timer(session: AsyncSession, monkeypatch):
    author, initiative, community_id = await _community(session)
    await _scheduled(session, initiative, author, due_in=-timedelta(minutes=1))
    await _due_now(session, community_id, "posts")

    async def fails(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(post_publication, "publish_due_posts", fails)
    await sweep_timers.process_due_timers()

    [(_c, kind, due)] = await _timers(session)
    assert kind == "posts" and due > datetime.now(timezone.utc)


async def test_a_failed_send_keeps_its_timer(session: AsyncSession, monkeypatch):
    """A scan whose visits answer the next time still sends in its finish; a
    finish that fails leaves the timer to its lease."""
    _author, _initiative, community_id = await _community(session)
    await _due_now(session, community_id, "reminders")

    async def found(_session, _guild_id):
        return None

    async def fails():
        raise RuntimeError("down")

    async def scan(*, now):
        return Scan(Scope.LIVE, found, fails)

    monkeypatch.setattr(notifications, "reminder_scan", scan)
    await sweep_timers.process_due_timers()

    [(_c, _k, due)] = await _timers(session, "reminders")
    assert due > datetime.now(timezone.utc)


async def test_a_next_timer_that_fails_to_save_keeps_the_claimed_one(
    session: AsyncSession, monkeypatch
):
    _author, _initiative, community_id = await _community(session)
    await _due_now(session, community_id, "reminders")

    async def found(_session, _guild_id):
        return datetime.now(timezone.utc) + timedelta(hours=1)

    async def sent():
        return None

    async def scan(*, now):
        return Scan(Scope.LIVE, found, sent)

    async def fails(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(notifications, "reminder_scan", scan)
    monkeypatch.setattr(sweep_timers, "_arm_next", fails)
    await sweep_timers.process_due_timers()

    [(_c, _k, due)] = await _timers(session, "reminders")
    assert due > datetime.now(timezone.utc)


async def test_arming_skips_a_community_that_is_gone(session: AsyncSession):
    """A community can be purged between being named and being armed (a wake
    still waiting, a catalog change): it is skipped, and the rest are armed."""
    _author, _initiative, community_id = await _community(session)
    gone = community_id + 1000

    await sweep_timers.arm_in("data_jobs", [community_id, gone])
    sweep_timers.wake("data_jobs", gone)
    await sweep_timers.process_due_timers()

    assert {c for c, _k, _d in await _timers(session, "data_jobs")} <= {community_id}


async def test_reconcile_arms_what_no_write_did_and_counts_it(session: AsyncSession):
    author, initiative, community_id = await _community(session)
    await _scheduled(session, initiative, author, due_in=timedelta(hours=2))
    await _due_now(session, community_id, sweep_timers.RECONCILE)
    repairs = metrics.sweep_timer_repairs.labels("posts")._value.get()

    await sweep_timers.process_due_timers()

    [(_c, _k, posts)] = await _timers(session, "posts")
    assert posts > datetime.now(timezone.utc) + timedelta(hours=1)
    [(_c, _k, again)] = await _timers(session, sweep_timers.RECONCILE)
    assert again > datetime.now(timezone.utc) + timedelta(hours=23)
    assert metrics.sweep_timer_repairs.labels("posts")._value.get() == repairs + 1


async def test_reconcile_arms_the_hooks_for_a_status_no_plugin_was_told(
    session: AsyncSession,
):
    """A community's plug-in hooks are kept in ``public``, which its own role
    cannot read: the reconcile asks the sweep's ``due_outside``. An enabled
    install whose plug-in was never told the community's status arms
    ``plugin_hooks``, whatever path changed the status."""
    from app.services.marketplace import plugin_installs
    from app.services.marketplace.registration_lookup import invalidate_registrations
    from app.testing import create_plugin_service_registration

    author, _initiative, community_id = await _community(session)
    install = await create_guild_plugin(
        session,
        await session.get(Guild, community_id),
        author,
        definition={"plugin_kind": "service", "service": {"public_id": "tests.told"}},
        listing_uid="TESTAPP0000081",
    )
    await create_plugin_service_registration(
        session, public_id="tests.told", listing_uid="TESTAPP0000081"
    )
    await session.commit()
    invalidate_registrations()
    await plugin_installs.record(community_id, install)
    await _due_now(session, community_id, sweep_timers.RECONCILE)
    repairs = metrics.sweep_timer_repairs.labels("plugin_hooks")._value.get()

    await sweep_timers.process_due_timers()

    assert [kind for _c, kind, _d in await _timers(session, "plugin_hooks")] == [
        "plugin_hooks"
    ]
    assert metrics.sweep_timer_repairs.labels("plugin_hooks")._value.get() == (
        repairs + 1
    )


async def test_a_community_arms_its_own_timers_and_reads_none(session: AsyncSession):
    _author, _initiative, community_id = await _community(session)
    _other_author, _other, other_id = await _community(session)
    due = datetime.now(timezone.utc)

    async with cohorts.system_session(community_id) as routed:
        await route_system(routed, guild_id=community_id)
        for statement, refused in (
            (
                text(
                    "INSERT INTO public.community_timers (community_id, kind, due_at)"
                    " VALUES (:community, 'posts', :due)"
                ).bindparams(community=other_id, due=due),
                "row-level security",
            ),
            (text("SELECT * FROM public.community_timers"), "permission denied"),
        ):
            with pytest.raises(DBAPIError, match=refused):
                await routed.exec(statement)
            await routed.rollback()
            await route_system(routed, guild_id=community_id)


def test_a_timer_names_the_community_the_sweep_and_the_time_and_nothing_else():
    """What the work is, the visit reads from the community's own schema."""
    assert set(CommunityTimer.__table__.columns.keys()) == {  # type: ignore[attr-defined]
        "id",
        "community_id",
        "kind",
        "due_at",
    }


async def _read_as_community(community_id: int, statement):
    async with cohorts.system_session(community_id) as routed:
        await route_system(routed, guild_id=community_id)
        return (await routed.exec(statement)).first()


async def test_a_webhook_backlog_keeps_the_drain_due(session: AsyncSession):
    """A change nobody has been sent yet is work, before any delivery row
    names it."""
    author, initiative, community_id = await _community(session)
    await create_post(session, initiative, author)
    now = datetime.now(timezone.utc)
    assert await _read_as_community(community_id, outbox_poller.next_due(now)) is None

    session.add(
        WebhookSubscription(
            initiative_id=None,
            created_by=author.id,
            target_url="https://example.test/hook",
            hmac_secret="secret",
            event_types=["posts.created"],
            active=True,
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()
    owed = await _read_as_community(community_id, outbox_poller.next_due(now))
    assert owed is not None and owed <= datetime.now(timezone.utc)


async def test_a_kept_tab_is_not_work_but_an_old_view_is(session: AsyncSession):
    author, initiative, community_id = await _community(session)
    project = await create_project(session, initiative, author)
    task = await create_task(session, project)
    project_id, task_id = project.id, task.id
    now = datetime.now(timezone.utc)
    old = now - personal_items.WINDOW - timedelta(days=1)
    await route_session_to_guild(session, community_id)
    session.add(
        PersonalItem(
            user_id=author.id,
            entity_type="project",
            entity_id=project_id,
            viewed_at=old,
            view_source="direct",
        )
    )
    await session.commit()

    async def next_due():
        async with cohorts.system_session(community_id) as routed:
            await route_system(routed, guild_id=community_id)
            return await personal_items.next_due(
                routed, Expiring(now=now, tab_limits={})
            )

    assert await next_due() is None
    await route_session_to_guild(session, community_id)
    session.add(
        PersonalItem(
            user_id=author.id,
            entity_type="task",
            entity_id=task_id,
            viewed_at=old,
            view_source="direct",
        )
    )
    await session.commit()
    assert await next_due() == old + personal_items.WINDOW


async def test_a_digest_is_armed_for_when_its_items_are_due(session: AsyncSession):
    """The finish answers each community's next due time: here, the end of
    the quiet period after the one item waiting."""
    author, initiative, community_id = await _community(session)
    project = await create_project(session, initiative, author)
    task = await create_task(session, project)
    await route_session_to_guild(session, community_id)
    item = TaskAssignmentDigestItem(
        user_id=author.id,
        task_id=task.id,
        project_id=project.id,
        task_title=task.title,
        project_name=project.name,
        assigned_by_name="Assigner",
    )
    session.add(item)
    await session.commit()
    due = item.created_at + notifications.ASSIGNMENT_DIGEST.quiet_period
    await _due_now(session, community_id, "task_digest")

    await sweep_timers.process_due_timers()

    [(_c, _k, armed)] = await _timers(session, "task_digest")
    assert abs((armed - due).total_seconds()) < 5


async def test_a_reminder_is_armed_for_its_lead(session: AsyncSession):
    author, initiative, community_id = await _community(session)
    calendar = await create_calendar(session, initiative, author)
    start = datetime.now(timezone.utc) + timedelta(hours=3)
    await create_calendar_event(
        session,
        calendar,
        author,
        attendees=[author],
        start_at=start,
        end_at=start + timedelta(hours=1),
    )
    await _due_now(session, community_id, "reminders")

    await sweep_timers.process_due_timers()

    [(_c, _k, armed)] = await _timers(session, "reminders")
    assert armed == start - timedelta(minutes=author.event_reminder_minutes_before)


async def test_nothing_ahead_arms_no_reminder(session: AsyncSession):
    _author, _initiative, community_id = await _community(session)
    await _due_now(session, community_id, "reminders")

    await sweep_timers.process_due_timers()

    assert await _timers(session, "reminders") == []


async def test_a_deadline_still_ahead_stays_armed(session: AsyncSession):
    """With nothing overdue yet, the overdue visit arms the next deadline."""
    author, initiative, community_id = await _community(session)
    project = await create_project(session, initiative, author)
    due = datetime.now(timezone.utc) + timedelta(hours=3)
    await create_task(session, project, assignees=[author], due_date=due)
    await _due_now(session, community_id, "overdue")

    await sweep_timers.process_due_timers()

    [(_c, _k, armed)] = await _timers(session, "overdue")
    assert abs((armed - due).total_seconds()) < 1


async def test_a_catalog_release_arms_the_communities_that_installed_it(
    session: AsyncSession,
):
    author, _initiative, community_id = await _community(session)
    community = await session.get(Guild, community_id)
    await create_guild_plugin(
        session,
        community,
        author,
        definition={
            "plugin_kind": "service",
            "service": {"public_id": "tests.release", "protocol": 1},
        },
    )
    await create_marketplace_listing(session, uid="TESTAPP0000001")

    await sweep_timers.watch_catalog()

    assert {kind for _c, kind, _due in await _timers(session)} >= {
        "plugin_updates",
        "plugin_schedules",
    }


@pytest.mark.parametrize(
    ("method", "path", "change", "kind"),
    [
        # Longer than the default lead of 15 minutes.
        ("PATCH", "/api/v1/me", {"event_reminder_minutes_before": 60}, "reminders"),
        ("PATCH", "/api/v1/me", {"timezone": "Pacific/Auckland"}, "overdue"),
        (
            "PUT",
            "/api/v1/me/notification-preferences",
            {"digests": {"overdue": {"cadence": "daily", "at": "07:00"}}},
            "overdue",
        ),
        (
            "PUT",
            "/api/v1/me/notification-preferences",
            {
                "channels": [
                    {"category": "coming_up", "channel": "email", "enabled": True}
                ]
            },
            "coming_up",
        ),
    ],
)
async def test_a_preference_that_brings_work_sooner_arms_it(
    client, acting_user, session: AsyncSession, method, path, change, kind
):
    a = await acting_user(guild_role=CommunityRole.member)

    response = await client.request(method, path, headers=a.headers, json=change)

    assert response.status_code == 200
    assert [community for community, *_ in await _timers(session, kind)] == [a.guild.id]


def test_a_weekly_digest_waits_for_its_day():
    schedule = DigestSchedule(cadence=DigestCadence.weekly, at="09:00", weekday=1)
    friday = datetime(2026, 10, 16, 9, tzinfo=timezone.utc)

    slot = digest_slot(schedule, tz_name="UTC", now=friday)

    assert not slot.on_today
    assert slot.following == datetime(2026, 10, 19, 9, tzinfo=timezone.utc)
