"""Tests for the scheduled event-reminder dispatcher.

The minute pass runs these sweeps on system sessions of its own; these tests
drive each one through the same runner and assert against committed rows (the
test harness commits real data and truncates between tests).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import re

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import usernames
from app.db.session import set_rls_context
from app.models.tenant.calendar_event import (
    CalendarEvent,
    CalendarEventAnswer,
    CalendarEventAttendee,
    RSVPStatus,
)
from app.models.tenant.event_reminder_dispatch import EventReminderDispatch
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskPriority,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
from app.models.platform.user import User
from app.services.platform import email_outbox
from app.services.platform import push_config
from app.services.notifications import (
    ASSIGNMENT_ITEM_RETENTION,
    ASSIGNMENT_MAX_WINDOW,
    ASSIGNMENT_QUIET_PERIOD,
    notify,
)
from app.services.notifications import (
    ASSIGNMENT_DIGEST,
    REACTION_DIGEST,
    digest_gc_scan,
    digest_scan,
    event_when,
    overdue_scan,
    reminder_scan,
)
from app.services.guild_sweeps import Scan, each_guild
from app.models.platform.guild import Guild, CommunityRole
from app.testing import (
    guild_of,
    create_calendar,
    create_calendar_event,
    create_comment,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_task,
    create_user,
    drain_notices,
    set_notification_prefs,
)
from app.testing import route_as
from app.db.request_context import Platform, SystemGuild, Unattributed


async def _sweep(scan: Scan | None) -> None:
    """One pass of ``scan`` over every community, as the minute pass runs it."""
    await each_guild([], name="test", scans=[scan] if scan else [])


async def _dispatch(session: AsyncSession) -> None:
    """Run the reminder pass, leaving the test session unrouted."""
    await set_rls_context(session, Unattributed())
    await _sweep(await reminder_scan(now=datetime.now(timezone.utc)))
    await drain_notices()


async def _events_initiative(session: AsyncSession, creator):
    guild = await create_guild(session)
    initiative = await create_initiative(session, guild, creator, name="Reminders")
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    calendar = await create_calendar(session, initiative, creator)
    return guild, initiative, calendar


async def _add_attendee(session, initiative, event, user, *, rsvp=RSVPStatus.pending):
    session.add(CalendarEventAttendee(calendar_event_id=event.id, user_id=user.id))
    if rsvp is not RSVPStatus.pending:
        session.add(
            CalendarEventAnswer(
                calendar_event_id=event.id, user_id=user.id, rsvp_status=rsvp
            )
        )
    await session.commit()
    # Reminders are gathered in the attendee's own context, so they must be a
    # guild + initiative member to see the event under RLS (as the real app
    # enforces — you can only attend events in initiatives you belong to).
    guild = await session.get(Guild, guild_of(event))
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.member
    )
    await create_initiative_member(session, initiative, user, role_name="member")


async def _reminders_for(session: AsyncSession, user_id: int) -> list[Notification]:
    # The bell is read on the platform context, so read it back there.
    await set_rls_context(session, Unattributed())
    result = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == NotificationType.event_reminder,
        )
    )
    return list(result.all())


def _unsaved_event(
    *, title: str, start_at: datetime, end_at: datetime, all_day: bool
) -> CalendarEvent:
    """In-memory event for the pure-unit formatting tests (never persisted)."""
    return CalendarEvent(
        calendar_id=1,
        created_by=1,
        title=title,
        start_at=start_at,
        end_at=end_at,
        all_day=all_day,
    )


def _unsaved_user(tz: str) -> User:
    """In-memory recipient for the pure-unit formatting tests (never persisted)."""
    return User(
        username=usernames.random_name(),
        discriminator=usernames.random_discriminator(),
        hashed_password="x",
        timezone=tz,
    )


def test_format_event_when_localizes_to_recipient_timezone():
    """A timed event renders in the recipient's IANA timezone with its abbrev."""
    event = _unsaved_event(
        title="Sync",
        start_at=datetime(2026, 7, 1, 21, 30, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc),
        all_day=False,
    )
    la = _unsaved_user("America/Los_Angeles")
    assert event_when(event, la) == "Wed, Jul 1, 2026 at 2:30 PM PDT"

    utc_user = _unsaved_user("UTC")
    assert event_when(event, utc_user) == "Wed, Jul 1, 2026 at 9:30 PM UTC"


def test_format_event_when_all_day_omits_time_and_zone():
    """All-day events show just the date, regardless of recipient timezone."""
    event = _unsaved_event(
        title="Holiday",
        start_at=datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 23, 59, tzinfo=timezone.utc),
        all_day=True,
    )
    assert event_when(event, _unsaved_user("Asia/Tokyo")) == "Wed, Jul 1, 2026"


def test_format_event_when_falls_back_on_bad_timezone():
    """An unrecognized timezone string falls back to UTC instead of raising."""
    event = _unsaved_event(
        title="Sync",
        start_at=datetime(2026, 7, 1, 21, 30, tzinfo=timezone.utc),
        end_at=datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc),
        all_day=False,
    )
    assert event_when(event, _unsaved_user("Not/AZone")) == (
        "Wed, Jul 1, 2026 at 9:30 PM UTC"
    )


async def test_event_reminder_fires_once_within_lead_window(
    session: AsyncSession,
):
    creator = await create_user(session, email="organizer@example.com")
    attendee = await create_user(
        session, email="attendee@example.com", event_reminder_minutes_before=15
    )
    guild, initiative, calendar = await _events_initiative(session, creator)
    # Starts in 10 min; with a 15-min lead the reminder is already due.
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session,
        calendar,
        creator,
        title="Standup",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee)

    await _dispatch(session)
    assert len(await _reminders_for(session, attendee.id)) == 1

    # Dedup: a second pass must not create another reminder.
    await _dispatch(session)
    assert len(await _reminders_for(session, attendee.id)) == 1

    # The dispatch ledger is guild-scoped; read it under the guild's context.
    await route_as(session, user_id=attendee.id, guild_id=guild.id)
    dispatches = await session.exec(
        select(EventReminderDispatch).where(
            EventReminderDispatch.user_id == attendee.id
        )
    )
    assert len(list(dispatches.all())) == 1


async def test_event_reminder_fires_for_each_occurrence_of_a_repeat(
    session: AsyncSession,
):
    """A daily event that began last week reminds of today's occurrence, but
    not somebody who declined just that one."""
    creator = await create_user(session)
    attendee = await create_user(session, event_reminder_minutes_before=15)
    away = await create_user(session, event_reminder_minutes_before=15)
    _guild, initiative, calendar = await _events_initiative(session, creator)
    upcoming = (datetime.now(timezone.utc) + timedelta(minutes=10)).replace(
        microsecond=0
    )
    event = await create_calendar_event(
        session,
        calendar,
        creator,
        start_at=upcoming - timedelta(days=7),
        end_at=upcoming - timedelta(days=7, minutes=-30),
        recurrence="RRULE:FREQ=DAILY",
    )
    await _add_attendee(session, initiative, event, attendee)
    await _add_attendee(session, initiative, event, away)
    session.add(
        CalendarEventAnswer(
            calendar_event_id=event.id,
            user_id=away.id,
            occurrence_start=upcoming,
            rsvp_status=RSVPStatus.declined,
        )
    )
    await session.commit()

    await _dispatch(session)
    await _dispatch(session)
    assert await _reminders_for(session, away.id) == []
    reminders = await _reminders_for(session, attendee.id)
    assert [
        (reminder.data["start_at"], reminder.data["target_path"])
        for reminder in reminders
    ] == [
        (
            upcoming.isoformat(),
            f"/go/calendar-event/{event.id}?"
            + urlencode({"occurrence": f"{upcoming:%Y-%m-%dT%H:%M:%SZ}"}),
        )
    ]


async def test_event_reminder_skipped_when_lead_time_off(session: AsyncSession):
    creator = await create_user(session, email="organizer2@example.com")
    attendee = await create_user(session, email="attendee2@example.com")
    # Turn reminders off via an UPDATE (mirrors the API; an explicit None on
    # INSERT would fall back to the column's server_default).
    attendee.event_reminder_minutes_before = None
    session.add(attendee)
    await session.commit()
    _, initiative, calendar = await _events_initiative(session, creator)
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session,
        calendar,
        creator,
        title="Sync",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee)

    await _dispatch(session)
    assert await _reminders_for(session, attendee.id) == []


async def test_event_reminder_not_due_when_outside_lead_window(session: AsyncSession):
    creator = await create_user(session, email="organizer3@example.com")
    attendee = await create_user(
        session, email="attendee3@example.com", event_reminder_minutes_before=15
    )
    _, initiative, calendar = await _events_initiative(session, creator)
    # Starts in 2 hours; a 15-min lead means the reminder is not yet due.
    start_at = datetime.now(timezone.utc) + timedelta(hours=2)
    event = await create_calendar_event(
        session,
        calendar,
        creator,
        title="Later",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee)

    await _dispatch(session)
    assert await _reminders_for(session, attendee.id) == []


async def test_event_reminder_at_time_of_event_fires_at_start(session: AsyncSession):
    creator = await create_user(session, email="organizer5@example.com")
    attendee = await create_user(
        session, email="attendee5@example.com", event_reminder_minutes_before=0
    )
    _, initiative, calendar = await _events_initiative(session, creator)
    # Just started (within the grace window); a 0-minute lead is due now.
    start_at = datetime.now(timezone.utc) - timedelta(seconds=30)
    event = await create_calendar_event(
        session,
        calendar,
        creator,
        title="Now",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee)

    await _dispatch(session)
    assert len(await _reminders_for(session, attendee.id)) == 1


async def test_event_reminder_skips_declined_attendees(session: AsyncSession):
    creator = await create_user(session, email="organizer4@example.com")
    attendee = await create_user(
        session, email="attendee4@example.com", event_reminder_minutes_before=15
    )
    _, initiative, calendar = await _events_initiative(session, creator)
    start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = await create_calendar_event(
        session,
        calendar,
        creator,
        title="Optional",
        start_at=start_at,
        end_at=start_at + timedelta(minutes=30),
    )
    await _add_attendee(session, initiative, event, attendee, rsvp=RSVPStatus.declined)

    await _dispatch(session)
    assert await _reminders_for(session, attendee.id) == []


async def test_a_community_notice_carries_its_guild(
    session: AsyncSession,
):
    """The initiative_added notification must carry its guild so the merged
    cross-guild inbox can resolve/navigate it after schema-per-guild."""
    creator = await create_user(session, email="ini-creator@example.com")
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild, creator, name="Onboarding")
    member = await create_user(session, email="ini-member@example.com")

    await set_rls_context(session, SystemGuild(guild.id))
    await notify(
        session,
        NotificationType.initiative_added,
        [member.id],
        about=None,
        key="initiative.added",
        values={"initiative": initiative.name},
        data={"initiative_id": initiative.id, "target_path": f"/i/{initiative.id}"},
    )
    await session.commit()
    await drain_notices()
    await set_rls_context(session, Unattributed())

    notifs = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == member.id,
                Notification.type == NotificationType.initiative_added,
            )
        )
    ).all()
    assert len(notifs) == 1
    data = notifs[0].data
    assert data["community_id"] == guild.id
    assert data["target_path"] == f"/i/{initiative.id}"
    assert f"community_id={guild.id}" in data["smart_link"]


async def _overdue_task_in_new_guild(
    session: AsyncSession,
    user: User,
    *,
    label: str,
    is_template: bool = False,
    project_archived: bool = False,
    task_archived: bool = False,
):
    """Give ``user`` an overdue task assigned to them in a brand-new guild, so a
    user in several guilds has overdue work spread across guild schemas."""
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user, name=label)
    project = await create_project(
        session,
        initiative,
        user,
        name=f"{label} Project",
        is_template=is_template,
        archived_at=datetime.now(timezone.utc) if project_archived else None,
    )
    status = TaskStatus(
        project_id=project.id,
        name="Todo",
        category=TaskStatusCategory.todo,
        position=0,
        is_default=True,
    )
    session.add(status)
    await session.commit()
    await session.refresh(status)
    task = Task(
        project_id=project.id,
        task_status_id=status.id,
        title=f"{label} overdue",
        priority=TaskPriority.medium,
        due_date=datetime.now(timezone.utc) - timedelta(days=1),
        archived_at=datetime.now(timezone.utc) if task_archived else None,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    session.add(
        TaskAssignee(
            task_id=task.id,
            user_id=user.id,
        )
    )
    await session.commit()
    return guild


def _titles(body: str) -> set[str]:
    """What a rendered message names in bold — the task and project titles
    among them. The digests build their lists by wrapping each in <strong>, so
    this is how a test sees what reached the recipient now that the message is
    composed rather than handed over as rows."""
    return set(re.findall(r"<strong>([^<]+)</strong>", body))


async def test_overdue_digest_gathers_tasks_across_user_guilds(
    session: AsyncSession, monkeypatch
):
    """The overdue digest must collect a user's overdue tasks from EVERY guild
    they belong to. Under schema-per-guild each guild's tasks live in its own
    schema, so a single public-scoped scan (the old behaviour) would miss all
    but the routed guild — this asserts both guilds' tasks reach the email."""
    user = await create_user(
        session,
        email="multi-overdue@example.com",
        timezone="UTC",
    )
    # The scheduled clock is a preference now; midnight is always past.
    await set_notification_prefs(session, user, {"email": {"at": "00:00"}})
    await _overdue_task_in_new_guild(session, user, label="Alpha")
    await _overdue_task_in_new_guild(session, user, label="Beta")

    captured: dict = {}

    async def _capture_email(sess, recipient, **kwargs):
        captured["user_id"] = recipient.id
        captured["titles"] = _titles(kwargs["pieces"].body)
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)

    await set_rls_context(session, Unattributed())
    await _sweep(overdue_scan(now=datetime.now(timezone.utc)))

    assert captured.get("user_id") == user.id
    assert {"Alpha overdue", "Beta overdue"} <= captured["titles"]


def _push_on(monkeypatch) -> None:
    """Resolve push as configured, so a sweep's push is queued at all."""
    monkeypatch.setattr(
        push_config,
        "ensure_push_config_fresh",
        AsyncMock(return_value=SimpleNamespace(enabled=True)),
    )


async def _queued_pushes(session: AsyncSession) -> list[NoticeOutboxItem]:
    """The pushes the sweeps handed the notice worker, oldest first."""
    return list(
        (
            await session.exec(
                select(NoticeOutboxItem)
                .where(NoticeOutboxItem.kind == "push")
                .order_by(NoticeOutboxItem.id)
            )
        ).all()
    )


async def test_overdue_digest_pushes_alongside_email(
    session: AsyncSession, monkeypatch
):
    """Push and email are the same digest on two channels: a user opted into
    both must get both, and the push must carry a tappable deep link."""
    user = await create_user(
        session,
        email="overdue-both@example.com",
        timezone="UTC",
    )
    # The scheduled clock is a preference now; midnight is always past.
    await set_notification_prefs(session, user, {"email": {"at": "00:00"}})
    await _overdue_task_in_new_guild(session, user, label="Alpha")

    emails: list[int] = []

    async def _capture_email(sess, recipient, **kwargs):
        emails.append(recipient.id)
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)
    _push_on(monkeypatch)

    await set_rls_context(session, Unattributed())
    await _sweep(overdue_scan(now=datetime.now(timezone.utc)))

    assert emails == [user.id]
    [push] = await _queued_pushes(session)
    assert push.user_id == user.id
    assert push.type == NotificationType.overdue_tasks.value
    assert "Alpha overdue" in (push.push_body or "")
    # The digest spans guilds, so the tap lands on the cross-guild My Tasks
    # list — no guild_id, which is what tells the app not to switch guilds.
    assert push.push_data == {
        "type": NotificationType.overdue_tasks.value,
        "count": "1",
        "target_path": "/",
    }


async def test_overdue_digest_pushes_when_email_opted_out(
    session: AsyncSession, monkeypatch
):
    """Turning the email off must not silence the push — the two toggles are
    independent, and the day's send is still stamped so it fires once."""
    user = await create_user(
        session,
        email="overdue-push-only@example.com",
        timezone="UTC",
    )
    # The scheduled clock is a preference now; midnight is always past. One
    # call, because the document is written whole: a second would replace it.
    await set_notification_prefs(
        session,
        user,
        {
            "email": {"at": "00:00"},
            "categories": {"due_dates": {"email": False}},
        },
    )
    await _overdue_task_in_new_guild(session, user, label="Alpha")

    async def _fail_email(sess, recipient, **kwargs):  # pragma: no cover
        raise AssertionError("email must not be sent to an opted-out user")

    monkeypatch.setattr(email_outbox, "enqueue", _fail_email)
    _push_on(monkeypatch)

    now = datetime.now(timezone.utc)
    await set_rls_context(session, Unattributed())
    await _sweep(overdue_scan(now=now))
    assert len(await _queued_pushes(session)) == 1

    # Second pass the same day is a no-op (the stamp landed on the push alone).
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    await _sweep(overdue_scan(now=now + timedelta(minutes=5)))
    assert len(await _queued_pushes(session)) == 1

    refreshed = (
        await session.exec(select(User).where(User.id == user.id))
    ).one_or_none()
    assert refreshed.last_overdue_notification_at is not None


async def test_overdue_digest_skips_push_when_opted_out(
    session: AsyncSession, monkeypatch
):
    """A user who wants only the email gets only the email."""
    user = await create_user(
        session,
        email="overdue-email-only@example.com",
        timezone="UTC",
    )
    # The scheduled clock is a preference now; midnight is always past. One
    # call, because the document is written whole: a second would replace it.
    await set_notification_prefs(
        session,
        user,
        {
            "email": {"at": "00:00"},
            "categories": {"due_dates": {"push": False}},
        },
    )
    await _overdue_task_in_new_guild(session, user, label="Alpha")

    async def _capture_email(sess, recipient, **kwargs):
        return False

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)
    _push_on(monkeypatch)

    await set_rls_context(session, Unattributed())
    await _sweep(overdue_scan(now=datetime.now(timezone.utc)))

    assert await _queued_pushes(session) == []
    # With no mail server either, nothing went, so the day is handed back.
    session.expunge_all()
    refreshed = (await session.exec(select(User).where(User.id == user.id))).one()
    assert refreshed.last_overdue_notification_at is None


async def test_overdue_digest_skips_template_projects(
    session: AsyncSession, monkeypatch
):
    """Tasks living in a template project are blueprints, not work — their due
    dates must never reach the digest (email or push)."""
    user = await create_user(
        session,
        email="template-overdue@example.com",
        timezone="UTC",
    )
    # The scheduled clock is a preference now; midnight is always past.
    await set_notification_prefs(session, user, {"email": {"at": "00:00"}})
    await _overdue_task_in_new_guild(session, user, label="Real")
    await _overdue_task_in_new_guild(session, user, label="Template", is_template=True)

    captured: dict = {}

    async def _capture_email(sess, recipient, **kwargs):
        captured["titles"] = _titles(kwargs["pieces"].body)
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)
    _push_on(monkeypatch)

    await set_rls_context(session, Unattributed())
    await _sweep(overdue_scan(now=datetime.now(timezone.utc)))

    assert {"Real overdue"} <= captured["titles"]
    [push] = await _queued_pushes(session)
    assert "Template overdue" not in (push.push_body or "")


async def test_overdue_digest_skips_archived_projects_and_tasks(
    session: AsyncSession, monkeypatch
):
    """Archiving is how a user says work is off their plate — an archived
    project, or an archived task in a live project, is not a deadline the
    digest should still be chasing."""
    user = await create_user(
        session,
        email="archived-overdue@example.com",
        timezone="UTC",
    )
    # The scheduled clock is a preference now; midnight is always past.
    await set_notification_prefs(session, user, {"email": {"at": "00:00"}})
    await _overdue_task_in_new_guild(session, user, label="Live")
    await _overdue_task_in_new_guild(
        session, user, label="ArchivedProject", project_archived=True
    )
    await _overdue_task_in_new_guild(
        session, user, label="ArchivedTask", task_archived=True
    )

    captured: dict = {}

    async def _capture_email(sess, recipient, **kwargs):
        captured["titles"] = _titles(kwargs["pieces"].body)
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)
    _push_on(monkeypatch)

    await set_rls_context(session, Unattributed())
    await _sweep(overdue_scan(now=datetime.now(timezone.utc)))

    assert {"Live overdue"} <= captured["titles"]
    [push] = await _queued_pushes(session)
    assert "ArchivedProject overdue" not in (push.push_body or "")
    assert "ArchivedTask overdue" not in (push.push_body or "")


async def _assignment_item_in_new_guild(
    session: AsyncSession, user: User, *, label: str
):
    """Queue a task-assignment digest item for ``user`` in a brand-new guild."""
    # A prior call left the session in a guild-member context; reset so the new
    # guild INSERT into public.guilds isn't RLS-denied.
    await set_rls_context(session, Unattributed())
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user, name=label)
    project = await create_project(session, initiative, user, name=f"{label} Project")
    status = TaskStatus(
        project_id=project.id,
        name="Todo",
        category=TaskStatusCategory.todo,
        position=0,
        is_default=True,
    )
    session.add(status)
    await session.commit()
    await session.refresh(status)
    task = Task(
        project_id=project.id,
        task_status_id=status.id,
        title=f"{label} task",
        priority=TaskPriority.medium,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    # digest items have no guild_id column, so route by search_path before insert.
    await route_as(session, user_id=user.id, guild_id=guild.id)
    session.add(
        TaskAssignmentDigestItem(
            user_id=user.id,
            task_id=task.id,
            project_id=project.id,
            task_title=task.title,
            project_name=project.name,
            assigned_by_name="Assigner",
        )
    )
    await session.commit()
    return guild


async def test_assignment_digest_gathers_items_across_user_guilds(
    session: AsyncSession, monkeypatch
):
    """The task-assignment digest must collect a user's pending items from every
    guild they belong to and mark them processed in each schema — a single
    public-scoped scan (the old behaviour) would see none of them."""
    user = await create_user(
        session, email="multi-digest@example.com"
    )  # opted in by default
    guild_a = await _assignment_item_in_new_guild(session, user, label="Alpha")
    guild_b = await _assignment_item_in_new_guild(session, user, label="Beta")

    captured: dict = {}

    async def _capture_email(sess, recipient, **kwargs):
        captured["user_id"] = recipient.id
        captured["titles"] = _titles(kwargs["pieces"].body)
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)

    await set_rls_context(session, Unattributed())
    # Past the quiet period, so the items have settled and the digest is due.
    await _sweep(
        digest_scan(
            ASSIGNMENT_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )

    assert captured.get("user_id") == user.id
    assert {"Alpha task", "Beta task"} <= captured["titles"]

    # Items were marked processed in each guild's own schema.
    for guild_id in (guild_a.id, guild_b.id):
        await route_as(session, user_id=user.id, guild_id=guild_id)
        pending = (
            await session.exec(
                select(TaskAssignmentDigestItem).where(
                    TaskAssignmentDigestItem.processed_at.is_(None)
                )
            )
        ).all()
        assert pending == [], f"guild {guild_id} items not marked processed"


async def test_assignment_digest_waits_for_the_flurry_to_end(
    session: AsyncSession, monkeypatch
):
    """The whole point of a digest: it must not fire on the first item while
    more are still landing. The old behaviour emailed immediately and then
    locked out for an hour, so a burst arrived as one mail plus a long delay."""
    user = await create_user(session, email="debounce@example.com")
    await _assignment_item_in_new_guild(session, user, label="Alpha")

    sent: list[int] = []

    async def _capture_email(sess, recipient, **kwargs):
        sent.append(kwargs["pieces"].body.count("<li>"))
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)

    # Item just landed — still accumulating, nothing goes out.
    await set_rls_context(session, Unattributed())
    await _sweep(digest_scan(ASSIGNMENT_DIGEST, now=datetime.now(timezone.utc)))
    assert sent == []

    # A second item lands, and the quiet period restarts from it: the run at
    # what would have been the first item's deadline must still hold.
    await _assignment_item_in_new_guild(session, user, label="Beta")
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            ASSIGNMENT_DIGEST,
            now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD / 2,
        )
    )
    assert sent == []

    # Once it has been quiet, both items ship together.
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            ASSIGNMENT_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )
    assert sent == [2]


async def test_assignment_digest_caps_a_steady_trickle(
    session: AsyncSession, monkeypatch
):
    """A trickle that never goes quiet must not defer the digest forever —
    the max window is what stops the quiet period from being gamed."""
    user = await create_user(session, email="trickle@example.com")
    await _assignment_item_in_new_guild(session, user, label="Alpha")

    sent: list[int] = []

    async def _capture_email(sess, recipient, **kwargs):
        sent.append(kwargs["pieces"].body.count("<li>"))
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)

    # An item that landed a moment ago would normally hold the digest, but the
    # window opened long enough ago that it ships regardless.
    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            ASSIGNMENT_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_MAX_WINDOW
        )
    )
    assert sent == [1]


async def test_assignment_digest_sends_both_channels_together(
    session: AsyncSession, monkeypatch
):
    """Email and push now ship from the same pass on the same trigger, so the
    two channels can't tell different stories about the same assignments."""
    user = await create_user(session, email="digest-both@example.com")
    await _assignment_item_in_new_guild(session, user, label="Alpha")
    await _assignment_item_in_new_guild(session, user, label="Beta")

    emails: list[int] = []

    async def _capture_email(sess, recipient, **kwargs):
        emails.append(kwargs["pieces"].body.count("<li>"))
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)
    _push_on(monkeypatch)

    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            ASSIGNMENT_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )

    assert emails == [2]
    [push] = await _queued_pushes(session)
    # A multi-task digest spans guilds, so it lands on My Tasks.
    assert push.push_data == {
        "type": NotificationType.task_assignment.value,
        "count": "2",
        "target_path": "/",
    }


async def test_assignment_digest_of_one_deep_links_to_the_task(
    session: AsyncSession, monkeypatch
):
    """A digest of one has an unambiguous destination, so it keeps the deep
    link the old per-task push had."""
    user = await create_user(session, email="digest-one@example.com")
    guild = await _assignment_item_in_new_guild(session, user, label="Alpha")

    async def _capture_email(sess, recipient, **kwargs):
        return False

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)
    _push_on(monkeypatch)

    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            ASSIGNMENT_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )

    [push] = await _queued_pushes(session)
    assert push.push_data is not None
    assert push.push_data["community_id"] == str(guild.id)
    assert push.push_data["target_path"].startswith("/go/task/")


async def test_assignment_digest_pushes_when_email_opted_out(
    session: AsyncSession, monkeypatch
):
    """Queueing is gated on either channel, so a push-only user still gets the
    digest — previously the queue row was written only for email."""
    user = await create_user(
        session,
        email="digest-push-only@example.com",
    )
    await set_notification_prefs(
        session, user, {"categories": {"assignments": {"email": False}}}
    )
    await _assignment_item_in_new_guild(session, user, label="Alpha")

    async def _fail_email(sess, recipient, **kwargs):  # pragma: no cover
        raise AssertionError("email must not be sent to an opted-out user")

    monkeypatch.setattr(email_outbox, "enqueue", _fail_email)
    _push_on(monkeypatch)

    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            ASSIGNMENT_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )

    assert len(await _queued_pushes(session)) == 1


async def test_assignment_digest_honours_a_preference_changed_mid_pass(
    session: AsyncSession, monkeypatch
):
    """The pass snapshots its candidates, then spends time routing through each
    guild. A channel switched off in that gap must not still be delivered to —
    the send has to read the reloaded row, not the snapshot."""
    user = await create_user(session, email="pref-race@example.com")
    await _assignment_item_in_new_guild(session, user, label="Alpha")

    async def _fail_email(sess, recipient, **kwargs):  # pragma: no cover
        raise AssertionError("email must not be sent after opting out")

    monkeypatch.setattr(email_outbox, "enqueue", _fail_email)
    _push_on(monkeypatch)

    # Turn the email off after the items were queued — as a request handled
    # while the worker is mid-gather would.
    session.expunge_all()
    await set_rls_context(session, Platform(user_id=user.id))
    fresh = (await session.exec(select(User).where(User.id == user.id))).one()
    await set_notification_prefs(
        session, fresh, {"categories": {"assignments": {"email": False}}}
    )

    session.expunge_all()
    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            ASSIGNMENT_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )

    # Push is still on, and still goes.
    assert len(await _queued_pushes(session)) == 1


async def test_assignment_gc_drops_items_past_retention(session: AsyncSession):
    """Digest items accumulated forever — nothing ever deleted them. The sweep
    clears anything past the retention window, sent or not, so an orphaned
    queue can't grow without bound either."""
    user = await create_user(session, email="digest-gc@example.com")
    guild = await _assignment_item_in_new_guild(session, user, label="Alpha")

    async def _row_count() -> int:
        session.expunge_all()
        await route_as(session, user_id=user.id, guild_id=guild.id)
        rows = (await session.exec(select(TaskAssignmentDigestItem))).all()
        return len(rows)

    assert await _row_count() == 1

    # Well inside the window: nothing is touched.
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    await _sweep(digest_gc_scan(now=datetime.now(timezone.utc)))
    assert await _row_count() == 1

    session.expunge_all()
    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_gc_scan(now=datetime.now(timezone.utc) + ASSIGNMENT_ITEM_RETENTION)
    )
    assert await _row_count() == 0


async def test_event_reminders_fire_across_a_users_guilds(session: AsyncSession):
    """A user attending due events in several guilds must get a reminder in each.
    Under schema-per-guild the events live in different schemas, so the old
    single public-scoped scan would only ever see the routed guild."""
    attendee = await create_user(
        session, email="multi-reminder@example.com", event_reminder_minutes_before=15
    )
    for label in ("Alpha", "Beta"):
        await set_rls_context(
            session, Unattributed()
        )  # permissive for the guild INSERT
        creator = await create_user(session, email=f"organizer-{label}@example.com")
        guild = await create_guild(session, creator=creator)
        initiative = await create_initiative(session, guild, creator, name=label)
        initiative.calendars_enabled = True
        session.add(initiative)
        await session.commit()
        await session.refresh(initiative)
        calendar = await create_calendar(session, initiative, creator)
        # Starts in 10 min; with the attendee's 15-min lead the reminder is due.
        start_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        event = await create_calendar_event(
            session,
            calendar,
            creator,
            title=f"{label} Standup",
            start_at=start_at,
            end_at=start_at + timedelta(minutes=30),
        )
        await _add_attendee(session, initiative, event, attendee)

    await _dispatch(session)

    # Count across guilds: notifications are shared, so read them on the
    # unrouted system engine.
    await set_rls_context(session, Unattributed())
    reminders = await _reminders_for(session, attendee.id)
    assert len(reminders) == 2


# ---------------------------------------------------------------------------
# Reaction digest
# ---------------------------------------------------------------------------


async def _reaction_item_in_new_guild(
    session: AsyncSession, user: User, *, label: str, emoji: str = "👍"
):
    """Queue a reaction digest item for ``user`` in a brand-new guild."""
    from app.models.tenant.reaction_digest import ReactionDigestItem

    # A prior call left the session in a guild-member context; reset so the new
    # guild INSERT into public.guilds isn't RLS-denied.
    await set_rls_context(session, Unattributed())
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, user, name=label)
    project = await create_project(session, initiative, user, name=f"{label} Project")
    task = await create_task(session, project)
    # A real comment: the queue row is gated through the thing that was
    # reacted to, so it cannot be queued against an id that resolves nowhere.
    comment = await create_comment(session, user, task=task, content=f"{label} thread")

    await route_as(session, user_id=user.id, guild_id=guild.id)
    session.add(
        ReactionDigestItem(
            user_id=user.id,
            reaction_id=None,
            target_type="comment",
            target_id=comment.id,
            emoji=emoji,
            target_path=f"/projects/{project.id}/tasks/{task.id}",
            context_title=f"{label} thread",
            reactor_name="reactor#0001",
        )
    )
    await session.commit()
    return guild


async def test_reaction_digest_gathers_across_guilds_and_marks_processed(
    session: AsyncSession, monkeypatch
):
    """The reaction digest runs on the same engine as the assignment digest,
    so it must show the same cross-guild behaviour: gather from every guild the
    user belongs to, send once, mark processed in each schema."""
    from app.models.tenant.reaction_digest import ReactionDigestItem

    user = await create_user(session, email="reaction-digest@example.com")
    guild_a = await _reaction_item_in_new_guild(session, user, label="Alpha")
    guild_b = await _reaction_item_in_new_guild(session, user, label="Beta", emoji="🎉")

    captured: dict = {}

    async def _capture_email(sess, recipient, **kwargs):
        captured["user_id"] = recipient.id
        captured["body"] = kwargs["pieces"].body
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)

    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            REACTION_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )

    assert captured.get("user_id") == user.id
    assert {"\U0001f44d", "\U0001f389"} <= set(captured["body"])

    for guild_id in (guild_a.id, guild_b.id):
        await route_as(session, user_id=user.id, guild_id=guild_id)
        pending = (
            await session.exec(
                select(ReactionDigestItem).where(
                    ReactionDigestItem.processed_at.is_(None)
                )
            )
        ).all()
        assert pending == [], f"guild {guild_id} items not marked processed"


async def test_reaction_digest_waits_for_the_flurry_to_end(
    session: AsyncSession, monkeypatch
):
    """Reactions arrive in bursts more than anything else in the app, so the
    quiet period matters most here."""
    user = await create_user(session, email="reaction-debounce@example.com")
    await _reaction_item_in_new_guild(session, user, label="Alpha")

    sent: list[int] = []

    async def _capture_email(sess, recipient, **kwargs):
        sent.append(kwargs["pieces"].body.count("<li>"))
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)

    await set_rls_context(session, Unattributed())
    await _sweep(digest_scan(REACTION_DIGEST, now=datetime.now(timezone.utc)))
    assert sent == []

    await _reaction_item_in_new_guild(session, user, label="Beta", emoji="🚀")
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            REACTION_DIGEST,
            now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD / 2,
        )
    )
    assert sent == []

    session.expunge_all()
    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            REACTION_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )
    assert sent == [2]


async def test_reaction_digest_respects_the_opt_out(session: AsyncSession, monkeypatch):
    """The reaction gate is its own: switching reactions off must not need the
    mention or assignment preferences touched, and must not silence them."""
    user = await create_user(
        session,
        email="reaction-optout@example.com",
    )
    await set_notification_prefs(
        session,
        user,
        {"categories": {"reactions": {"email": False, "push": False}}},
    )
    await _reaction_item_in_new_guild(session, user, label="Alpha")

    sent: list[int] = []

    async def _capture_email(sess, recipient, **kwargs):
        sent.append(kwargs["pieces"].body.count("<li>"))
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)
    _push_on(monkeypatch)

    await set_rls_context(session, Unattributed())
    await _sweep(
        digest_scan(
            REACTION_DIGEST, now=datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD
        )
    )
    assert sent == []
    assert await _queued_pushes(session) == []


class TestReactionBellRollup:
    """The payload arithmetic behind the rolled-up bell line, including what it
    makes of a line written before reactions rolled up at all."""

    def test_a_pre_rollup_line_counts_as_the_one_reaction_it_named(self):
        from app.services.notifications import (
            _rolled_up_count,
            _rolled_up_reactions,
        )

        legacy = {
            "emoji": "\N{THUMBS UP SIGN}",
            "reactor_name": "@ada",
            "reactor_id": 7,
        }
        assert _rolled_up_count(legacy) == 1
        assert _rolled_up_reactions(legacy) == [
            {
                "id": None,
                "emoji": "\N{THUMBS UP SIGN}",
                "reactor_id": 7,
                "reactor_name": "@ada",
            }
        ]

    def test_an_empty_payload_stands_for_nothing(self):
        from app.services.notifications import (
            _rolled_up_count,
            _rolled_up_reactions,
        )

        assert _rolled_up_count({}) == 0
        assert _rolled_up_reactions({}) == []

    def test_the_named_reactions_are_capped_but_the_counts_are_not(self):
        """The detail rolls off; what the sentence says must not. A line that
        forgot its oldest reactions still knows how big its crowd is."""
        from app.services.notifications import MAX_ROLLED_UP_REACTIONS
        from app.services.notifications import _reaction_line

        entries = [
            {
                "id": i,
                "emoji": "\N{PARTY POPPER}",
                "reactor_id": i,
                "reactor_name": f"@u{i}",
            }
            for i in range(MAX_ROLLED_UP_REACTIONS + 5)
        ]
        line = _reaction_line(
            entries,
            count=len(entries),
            reactor_ids=[entry["reactor_id"] for entry in entries],
            place={"target_path": "/go/task/1"},
            target_type="comment",
            target_id=1,
            guild_id=3,
        )
        assert line["count"] == MAX_ROLLED_UP_REACTIONS + 5
        assert line["reactor_count"] == MAX_ROLLED_UP_REACTIONS + 5
        assert len(line["reactions"]) == MAX_ROLLED_UP_REACTIONS
        # The cap drops the oldest, so the newest reactor is still the one named.
        assert line["reactor_id"] == entries[-1]["reactor_id"]

    def test_the_roster_keeps_growing_after_the_detail_rolls_off(self):
        """A cap on the roster would be a cap on the truth — the count would
        freeze on exactly the comment where the number matters most."""
        from app.services.notifications import MAX_ROLLED_UP_REACTIONS
        from app.services.notifications import _reaction_line

        crowd = list(range(MAX_ROLLED_UP_REACTIONS * 10))
        line = _reaction_line(
            [
                {
                    "id": i,
                    "emoji": "\N{PARTY POPPER}",
                    "reactor_id": i,
                    "reactor_name": f"@u{i}",
                }
                for i in crowd
            ],
            count=len(crowd),
            reactor_ids=crowd,
            place={"target_path": "/go/task/1"},
            target_type="comment",
            target_id=1,
            guild_id=3,
        )
        assert line["reactor_count"] == len(crowd)
        assert len(line["reactions"]) == MAX_ROLLED_UP_REACTIONS

    def test_a_pre_roster_line_reads_its_crowd_off_the_reactions_it_kept(self):
        from app.services.notifications import _rolled_up_reactor_ids

        assert _rolled_up_reactor_ids(
            {
                "reactions": [
                    {"id": 1, "emoji": "a", "reactor_id": 2, "reactor_name": "@bob"},
                    {"id": 2, "emoji": "b", "reactor_id": 2, "reactor_name": "@bob"},
                    {"id": 3, "emoji": "c", "reactor_id": 5, "reactor_name": "@ada"},
                ]
            }
        ) == [2, 5]
        # And one written before rollups at all still names its one reactor.
        assert _rolled_up_reactor_ids(
            {"emoji": "\N{THUMBS UP SIGN}", "reactor_id": 7, "reactor_name": "@ada"}
        ) == [7]

    def test_a_pre_rollup_gesture_is_matched_by_who_reacted_and_with_what(self):
        """Such a line carries no reaction id, so an un-react would never match
        it on id alone and the line would keep claiming the reaction stands."""
        from app.services.notifications import _matches_withdrawn

        legacy = {
            "id": None,
            "emoji": "\N{THUMBS UP SIGN}",
            "reactor_id": 7,
            "reactor_name": "@ada",
        }
        assert _matches_withdrawn(
            legacy, reaction_id=99, reactor_id=7, emoji="\N{THUMBS UP SIGN}"
        )
        assert not _matches_withdrawn(
            legacy, reaction_id=99, reactor_id=8, emoji="\N{THUMBS UP SIGN}"
        )
        assert not _matches_withdrawn(
            legacy, reaction_id=99, reactor_id=7, emoji="\N{PARTY POPPER}"
        )
        # A gesture that knows its own id is matched by it, and only by it.
        known = {**legacy, "id": 99}
        assert _matches_withdrawn(
            known, reaction_id=99, reactor_id=0, emoji="\N{PARTY POPPER}"
        )
        assert not _matches_withdrawn(
            known, reaction_id=98, reactor_id=7, emoji="\N{THUMBS UP SIGN}"
        )


async def test_withdrawal_keeps_a_reactor_whose_other_gesture_rolled_off(
    session: AsyncSession,
):
    """Roster membership is answered off the detail, so it can only be answered
    while the detail is complete. Past the cap, the absence of a reactor from
    what the line still remembers is not proof they have left it."""
    from app.models.platform.notification import NotificationType
    from app.services.notifications import (
        MAX_ROLLED_UP_REACTIONS,
        withdraw_reaction_event,
    )
    from app.services.platform import user_notifications

    author = await create_user(session, email="rollup-rolled-off@example.com")
    guild = await create_guild(session, creator=author)
    bob = 2
    # 25 gestures counted, only the newest 20 remembered: bob's first has
    # rolled off the detail, his second is the newest entry.
    kept = [
        {"id": 100 + i, "emoji": "\N{PARTY POPPER}", "reactor_id": 10 + i}
        for i in range(MAX_ROLLED_UP_REACTIONS - 1)
    ] + [{"id": 999, "emoji": "\N{THUMBS UP SIGN}", "reactor_id": bob}]
    roster = [bob] + [10 + i for i in range(24)]
    line = await user_notifications.create_notification(
        session,
        user_id=author.id,
        notification_type=NotificationType.comment_reaction,
        data={
            "community_id": guild.id,
            "target_type": "comment",
            "target_id": 5,
            "count": 25,
            "reactor_count": len(roster),
            "reactor_ids": roster,
            "reactions": kept,
        },
    )
    await session.flush()

    await withdraw_reaction_event(
        session,
        author_id=author.id,
        reaction_id=999,
        reactor_id=bob,
        emoji="\N{THUMBS UP SIGN}",
        target_type="comment",
        target_id=5,
        guild_id=guild.id,
    )
    await session.commit()
    await drain_notices()
    await session.refresh(line)

    assert line.data["count"] == 24
    # Bob keeps his place: the gesture that proves he is still here rolled off
    # the detail long ago, and the line must not read his absence from it as
    # him leaving.
    assert bob in line.data["reactor_ids"]
    assert line.data["reactor_count"] == 25


async def test_two_passes_at_once_send_one_digest(session: AsyncSession, monkeypatch):
    """Items are taken by the statement that reads them, so two passes sweeping
    at the same moment send one digest between them."""
    import asyncio

    user = await create_user(session, email="claimed-digest@example.com")
    await _assignment_item_in_new_guild(session, user, label="Gamma")
    sent: list[int] = []

    async def _capture_email(sess, recipient, **kwargs):
        sent.append(recipient.id)
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _capture_email)
    now = datetime.now(timezone.utc) + ASSIGNMENT_QUIET_PERIOD

    await asyncio.gather(
        _sweep(digest_scan(ASSIGNMENT_DIGEST, now=now)),
        _sweep(digest_scan(ASSIGNMENT_DIGEST, now=now)),
    )

    assert sent == [user.id]
