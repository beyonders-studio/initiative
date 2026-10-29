"""The sweeps that run on timers, and the worker that runs them.

Each :class:`Sweep` says what it does in one community (its visit), when it
next has work there (``next_due``, read from the community's own schema), and
which writes give it work (its :class:`~app.db.timers.TimerSource` entries,
rendered into every community's schema as triggers by ``app.db.timers``).
Those triggers arm ``public.community_timers`` in the transaction that made
the work.

The worker claims timers that have come due, a batch at a time, across every
replica (``FOR UPDATE SKIP LOCKED``, so each timer is claimed once). Claiming
moves a timer :data:`LEASE` into the future: if the visit never finishes, the
timer comes due again. Each visit runs through the same runner as every other
sweep (``app.services.guild_sweeps.each_guild``), on the community's own
cohort and routing. After it, the sweep's next timer is armed from what the
community holds then, never sooner than ``every`` from now, which is the
cadence the sweep had before it ran on timers.

A timer may come early: the visit finds nothing and arms the next one. A
source must never arm one later than its work. A community whose status no
longer admits a sweep keeps that sweep's timer on its lease, so the work
resumes within a lease of the community coming back.

A timer armed to run at once wakes the worker on every process
(``app.db.timers.WAKE_CHANNEL``); otherwise it looks every :data:`TICK_SECONDS`.
Work a process learns of outside a write (a webhook hint, a retry, a freed
job slot) goes through :func:`wake`, which arms the community and runs the
worker.

A sweep whose visit calls a server outside the database (``calls_out``: a
webhook target, a plug-in's hook) runs in a lane of its own, a few visits at
once, so a slow or dead server never holds up the sweeps that only touch the
database.

Once a day each community's ``reconcile`` timer arms any sweep that has work
but no timer: a write no source covered, or a session that could not arm (a
filer, a migration). Each one it arms is counted
(``initiative_sweep_timer_repairs``), since it means a source is missing.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import cache, partial
from typing import Any

from sqlalchemy import case, delete, exists, func, literal, or_, text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import metrics
from app.db import cohorts
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.db.timers import TimerSource, on_insert, on_row
from app.models.tenant.timer_mark import TimerMark
from app.services.background_tasks import Loop
from app.services.guild_sweeps import Scan, Scope, Visit, each_guild

logger = logging.getLogger(__name__)

#: How far into the future claiming a timer moves it. A visit that never
#: finishes leaves its timer to come due again then.
LEASE = timedelta(minutes=5)

#: Timers claimed at once. A tick claims batch after batch until one comes
#: back short.
BATCH = 500

#: How often the worker looks for due timers.
TICK_SECONDS = 60

#: Outward visits run at once. Each holds a system connection while it waits
#: on the server it calls.
OUTWARD_AT_ONCE = 4

#: How long a woken worker lets further wakes gather before it looks.
WAKE_SETTLE_SECONDS = 1.0

#: How often each community is reconciled.
RECONCILE_EVERY = timedelta(days=1)

RECONCILE = "reconcile"

#: ``(now)``: a SELECT of one value, the earliest time the sweep could have
#: work in the routed community, or NULL when it has none. Read with the
#: trash filter off, so it states its own ``deleted_at`` conditions.
NextDue = Callable[[datetime], Any]


@dataclass(frozen=True)
class Sweep:
    """One sweep that runs community by community, on timers."""

    #: The timer kind: the sweep's name in ``community_timers``.
    kind: str
    scope: Scope
    #: The least time between two visits to one community: the cadence the
    #: sweep ran at before timers, so nothing runs more often than it did.
    every: timedelta
    next_due: NextDue
    #: The visit, or ``None`` when ``prepare`` makes it.
    visit: Visit | None = None
    #: Makes the visit, from what the tick shares (read once, before any
    #: community is visited); ``None`` when there is nothing to do this tick.
    #: A :class:`Scan` finishes once every community is visited, and answers
    #: each one's next due time unless ``answers`` says the visit does.
    prepare: Callable[[], Awaitable[Visit | Scan | None]] | None = None
    #: The visit returns the sweep's next due time itself (or ``None`` for no
    #: work), in place of ``next_due``.
    answers: bool = False
    #: The visit calls a server outside the database, so it runs in the
    #: outward lane.
    calls_out: bool = False
    #: The writes that give the sweep work.
    sources: tuple[TimerSource, ...] = ()
    #: ``(community, now)``: the sweep's next due time read outside the
    #: community's schema, for a sweep whose work is kept in ``public`` (where
    #: the community's role reads nothing). The reconcile asks this in place of
    #: ``next_due``, which such a sweep, answering its own, never has run.
    due_outside: Callable[[int, datetime], Awaitable[datetime | None]] | None = None


@cache
def sweeps() -> tuple[Sweep, ...]:
    """Every sweep that runs on timers, read once."""
    from app.core.intake import IntakeStream, meta
    from app.db.soft_delete_filter import SOFT_DELETE_MODELS
    from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee
    from app.models.tenant.content_hold import ContentHold
    from app.models.tenant.engagement_level import EngagementLevel
    from app.models.tenant.event_outbox import EventOutbox
    from app.models.tenant.evidence import Evidence
    from app.models.tenant.export_job import ExportJob, ExportJobStatus
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.models.tenant.import_job import ImportJob, ImportJobStatus
    from app.models.tenant.intake import IntakeCase
    from app.models.tenant.moderation import ModerationReport
    from app.models.tenant.personal_item import PersonalItem
    from app.models.tenant.reaction_digest import ReactionDigestItem
    from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
    from app.models.tenant.task_assignment_digest import TaskAssignmentDigestItem
    from app.models.tenant.upload import Upload
    from app.services import notifications, resumable
    from app.services.export import worker as export_worker
    from app.services.import_engine import worker as import_worker
    from app.services.marketplace import community_hooks, plugin_installs
    from app.services.platform import evidence, holds
    from app.services.tenant import (
        change_log,
        engagement_levels,
        expiry,
        outbox_poller,
        personal_items,
        plugin_hooks,
        plugin_schedules,
        plugin_updates,
        post_publication,
        subscription_notices,
        thumbnails,
        trash_purge,
    )
    from app.services.tenant.attachments import (
        PASTED_IMAGE_PREFIX,
        UNCLAIMED_PASTED_IMAGE_GRACE,
    )

    def least(*parts: Any) -> Any:
        """The earliest of several one-value SELECTs (NULLs ignored)."""
        return select(func.least(*(part.scalar_subquery() for part in parts)))

    def when_exists(condition: Any) -> Any:
        """``now()`` when ``condition`` holds, else NULL."""
        return select(func.now()).where(condition)

    hour, minute = timedelta(hours=1), timedelta(minutes=1)
    imports_pending = (
        ImportJobStatus.staged.value,
        ImportJobStatus.fetching.value,
        ImportJobStatus.queued.value,
    )
    imports_finished = tuple(
        status.value
        for status in ImportJobStatus
        if status.value not in (*imports_pending, ImportJobStatus.running.value)
    )
    change_log_sources = (
        on_insert(
            "event_outbox",
            after=change_log.RETENTION,
        ),
        on_insert("plugin_event_outbox", after=change_log.RETENTION),
    )
    digest_items = (TaskAssignmentDigestItem, ReactionDigestItem)
    case_keep = {
        stream.value: timedelta(days=meta(stream).retention_days)
        for stream in IntakeStream
    }
    shortest_case_keep = min(case_keep.values())
    report_keep = timedelta(days=meta(IntakeStream.moderation).retention_days)

    async def claim_jobs(session: AsyncSession, guild_id: int) -> None:
        await export_worker.jobs.claim(session, guild_id)
        await import_worker.jobs.claim(session, guild_id)

    async def sweep_stale_jobs(session: AsyncSession, guild_id: int) -> None:
        await export_worker.jobs.sweep_stale(session, guild_id)
        # Telling a job's creator leaves the session unrouted.
        await set_rls_context(session, SystemGuild(guild_id))
        await import_worker.jobs.sweep_stale(session, guild_id)

    async def publish_posts(session: AsyncSession, _guild_id: int) -> None:
        await post_publication.publish_due_posts(
            session, now=datetime.now(timezone.utc)
        )

    return (
        Sweep(
            kind="webhooks",
            scope=Scope.ACTIVE,
            every=minute,
            calls_out=True,
            visit=outbox_poller.drain_guild,
            # A subscribed community's new events wake it at once
            # (outbox_poller.hint); the outbox sources are the backstop should
            # that wake be lost. A community with no subscription answers that
            # visit with one read.
            next_due=outbox_poller.next_due,
            sources=(
                on_insert("event_outbox", after=minute),
                on_insert("plugin_event_outbox", after=minute),
                on_row(
                    "webhook_subscriptions",
                    "now()",
                    events="INSERT OR UPDATE OF active",
                    when="NEW.active",
                ),
            ),
        ),
        # Telling subscribers what changed: woken a minute after the writes
        # that give the webhooks work, so a burst of edits is one line.
        Sweep(
            kind="subscriptions",
            scope=Scope.ACTIVE,
            every=minute,
            visit=subscription_notices.tell_subscribers,
            next_due=subscription_notices.next_due,
            sources=(on_insert("event_outbox", after=minute),),
        ),
        Sweep(
            kind=plugin_installs.INDEX_SWEEP,
            scope=Scope.PROVISIONED,
            every=minute,
            visit=plugin_installs.reindex_community,
            answers=True,
            # Nothing is due once the index is written; the daily reconcile
            # writes it again.
            next_due=lambda _now: select(func.now()),
            sources=(
                on_row(
                    "guild_plugins",
                    "now()",
                    events=(
                        "INSERT OR UPDATE OF enabled, listing_uid, config, definition"
                        " OR DELETE"
                    ),
                ),
            ),
        ),
        Sweep(
            kind="plugin_deliveries",
            scope=Scope.ACTIVE,
            every=minute,
            calls_out=True,
            visit=plugin_hooks.run_due,
            answers=True,
            next_due=plugin_hooks.next_due,
            sources=(
                on_row(
                    "plugin_hook_deliveries",
                    "COALESCE({row}.taken_until, now())",
                    events="INSERT OR UPDATE OF taken_until",
                    when="NEW.body IS NOT NULL",
                ),
            ),
        ),
        Sweep(
            kind="plugin_schedules",
            scope=Scope.ACTIVE,
            every=minute,
            calls_out=True,
            visit=plugin_schedules.run_due,
            answers=True,
            next_due=lambda _now: plugin_schedules.next_due(),
            sources=(
                on_row(
                    "plugin_schedule_runs",
                    "GREATEST({row}.next_due_at, {row}.claimed_until)",
                    events="INSERT OR UPDATE OF next_due_at, claimed_until",
                ),
                # Switched back on: its schedules may be overdue already.
                on_row(
                    "guild_plugins",
                    "now()",
                    events="UPDATE OF enabled",
                    when="NEW.enabled AND NOT OLD.enabled",
                ),
            ),
        ),
        Sweep(
            kind="data_jobs",
            scope=Scope.ACTIVE,
            every=minute,
            visit=claim_jobs,
            # Armed at once by a job queued or ended, so it is claimed now.
            next_due=lambda _now: least(
                when_exists(
                    exists().where(ExportJob.status == ExportJobStatus.queued.value)
                    & ~exists().where(ExportJob.status == ExportJobStatus.running.value)
                ),
                when_exists(
                    exists().where(ImportJob.status == ImportJobStatus.queued.value)
                    & ~exists().where(
                        col(ImportJob.status).in_(
                            (
                                ImportJobStatus.fetching.value,
                                ImportJobStatus.running.value,
                            )
                        )
                    )
                ),
            ),
            sources=tuple(
                on_row(table, "now()", events="INSERT OR UPDATE OF status")
                for table in ("export_jobs", "import_jobs")
            ),
        ),
        Sweep(
            kind="posts",
            scope=Scope.ACTIVE,
            every=minute,
            visit=publish_posts,
            next_due=post_publication.next_due,
            sources=(
                on_row(
                    "posts",
                    "{row}.scheduled_for",
                    events=(
                        "INSERT OR UPDATE OF scheduled_for, published_at, deleted_at"
                    ),
                    when=(
                        "NEW.published_at IS NULL AND NEW.scheduled_for IS NOT NULL"
                        " AND NEW.deleted_at IS NULL"
                    ),
                ),
            ),
        ),
        Sweep(
            kind="stale_jobs",
            scope=Scope.ACTIVE,
            every=timedelta(minutes=5),
            visit=sweep_stale_jobs,
            # Heartbeats only push these later, so they arm nothing.
            next_due=lambda _now: least(
                select(
                    func.min(ExportJob.updated_at) + export_worker.STALE_RUNNING
                ).where(ExportJob.status == ExportJobStatus.running.value),
                select(
                    func.min(ImportJob.updated_at) + import_worker.STALE_RUNNING
                ).where(ImportJob.status == ImportJobStatus.running.value),
                select(
                    func.min(ImportJob.updated_at) + import_worker.STALE_FETCHING
                ).where(ImportJob.status == ImportJobStatus.fetching.value),
            ),
            sources=(
                on_row(
                    "export_jobs",
                    "now()",
                    after=export_worker.STALE_RUNNING,
                    events="INSERT OR UPDATE OF status",
                    when=f"NEW.status = '{ExportJobStatus.running.value}'",
                ),
                on_row(
                    "import_jobs",
                    "now()",
                    after=min(
                        import_worker.STALE_RUNNING, import_worker.STALE_FETCHING
                    ),
                    events="INSERT OR UPDATE OF status",
                    when=(
                        f"NEW.status IN ('{ImportJobStatus.running.value}',"
                        f" '{ImportJobStatus.fetching.value}')"
                    ),
                ),
            ),
        ),
        Sweep(
            kind="trash",
            scope=Scope.ACTIVE,
            every=hour,
            visit=trash_purge.purge_guild,
            next_due=lambda _now: least(
                *(
                    select(func.min(model.purge_at)).where(  # type: ignore[attr-defined]
                        model.purge_at.is_not(None)  # type: ignore[attr-defined]
                    )
                    for model in SOFT_DELETE_MODELS
                ),
                select(
                    func.min(Upload.created_at) + UNCLAIMED_PASTED_IMAGE_GRACE
                ).where(
                    col(Upload.filename).startswith(PASTED_IMAGE_PREFIX),
                    col(Upload.claimed_at).is_(None),
                ),
            ),
            sources=(
                *(
                    on_row(
                        str(model.__tablename__),
                        "{row}.purge_at",
                        events="INSERT OR UPDATE OF purge_at",
                        when="NEW.purge_at IS NOT NULL",
                    )
                    for model in SOFT_DELETE_MODELS
                ),
                on_row(
                    "uploads",
                    "{row}.created_at",
                    after=UNCLAIMED_PASTED_IMAGE_GRACE,
                    when=f"NEW.filename LIKE '{PASTED_IMAGE_PREFIX}%'",
                ),
            ),
        ),
        # Resumable uploads nobody finished or took.
        Sweep(
            kind="resumable_uploads",
            scope=Scope.PROVISIONED,
            every=hour,
            visit=resumable.expire,
            next_due=resumable.next_due,
            sources=(on_row("pending_uploads", "{row}.expires_at"),),
        ),
        # Uploaded pictures drawn smaller, as they arrive.
        Sweep(
            kind="thumbnails",
            scope=Scope.ACTIVE,
            every=minute,
            visit=thumbnails.draw_pending,
            next_due=thumbnails.next_due,
            sources=(
                on_row(
                    "file_versions",
                    "now()",
                    events="INSERT OR UPDATE OF thumbnail_state",
                    when="NEW.thumbnail_state = 'pending'",
                ),
            ),
        ),
        Sweep(
            kind="export_expiry",
            scope=Scope.PROVISIONED,
            every=hour,
            visit=export_worker.expire_artifacts,
            next_due=lambda _now: select(func.min(ExportJob.expires_at)).where(
                ExportJob.status == ExportJobStatus.done.value,
                col(ExportJob.expires_at).is_not(None),
            ),
            sources=(
                on_row(
                    "export_jobs",
                    "{row}.expires_at",
                    events="INSERT OR UPDATE OF expires_at, status",
                    when=(
                        f"NEW.status = '{ExportJobStatus.done.value}'"
                        " AND NEW.expires_at IS NOT NULL"
                    ),
                ),
            ),
        ),
        Sweep(
            kind="import_expiry",
            scope=Scope.PROVISIONED,
            every=hour,
            visit=import_worker.expire_payloads,
            next_due=lambda _now: least(
                select(func.min(ImportJob.expires_at)).where(
                    col(ImportJob.status).in_(imports_pending),
                    col(ImportJob.expires_at).is_not(None),
                ),
                when_exists(
                    exists().where(
                        col(ImportJob.status).in_(imports_finished),
                        col(ImportJob.secret_encrypted).is_not(None),
                    )
                ),
            ),
            sources=(
                on_row(
                    "import_jobs",
                    "{row}.expires_at",
                    events="INSERT OR UPDATE OF expires_at",
                    when="NEW.expires_at IS NOT NULL",
                ),
                on_row(
                    "import_jobs",
                    "now()",
                    events="UPDATE OF status",
                    when=(
                        f"NEW.status IN ({', '.join(repr(s) for s in imports_finished)})"
                        " AND NEW.secret_encrypted IS NOT NULL"
                    ),
                ),
            ),
        ),
        Sweep(
            kind="expiry",
            scope=Scope.PROVISIONED,
            every=hour,
            prepare=expiry.prepare,
            answers=True,
            next_due=expiry.next_due,
            sources=(
                *change_log_sources,
                on_insert("plugin_hook_deliveries", after=plugin_hooks.DELIVERY_TTL),
                # A new tab can push an old one past its person's limit, so a
                # view is looked at within the hour, as before timers.
                on_insert("personal_items", after=hour),
                on_row(
                    "event_reminder_dispatches",
                    "{row}.event_start_at",
                    after=notifications.EVENT_REMINDER_DISPATCH_RETENTION,
                ),
            ),
        ),
        Sweep(
            kind="engagement",
            scope=Scope.PROVISIONED,
            every=hour,
            prepare=engagement_levels.prepare,
            # Levels decay, so a community active this week is worked out
            # every hour, and one quiet all week is left alone.
            next_due=lambda now: when_exists(
                or_(
                    exists().where(
                        col(PersonalItem.viewed_at) > now - personal_items.WINDOW
                    ),
                    exists().where(
                        EventOutbox.occurred_at > now - change_log.RETENTION
                    ),
                    exists().where(EngagementLevel.level.is_not(None)),
                )
            ),
            sources=(
                on_insert("event_outbox", after=hour),
                on_insert("personal_items", after=hour),
            ),
        ),
        Sweep(
            kind="evidence",
            scope=Scope.ACTIVE,
            every=hour,
            visit=evidence.purge_due,
            # A case's evidence is kept from when its task closes, for its
            # stream's retention: any task closing arms the shortest, which is
            # never later.
            next_due=lambda _now: least(
                select(
                    func.min(
                        func.least(
                            Task.deleted_at,
                            case(
                                (
                                    TaskStatus.category == TaskStatusCategory.done,
                                    Task.completed_at,
                                ),
                            ),
                        )
                        + case(case_keep, value=IntakeCase.stream)
                    )
                )
                .select_from(IntakeCase)
                .join(Task, col(Task.id) == IntakeCase.task_id)
                .join(TaskStatus, col(TaskStatus.id) == Task.task_status_id)
                .where(col(IntakeCase.id).in_(select(Evidence.case_id))),
                select(func.min(ModerationReport.decided_at) + report_keep).where(
                    col(ModerationReport.id).in_(select(Evidence.report_id))
                ),
            ),
            sources=(
                on_row("evidence", "now()"),
                on_row(
                    "tasks",
                    "now()",
                    after=shortest_case_keep,
                    events="UPDATE OF completed_at, deleted_at",
                    when="NEW.completed_at IS NOT NULL OR NEW.deleted_at IS NOT NULL",
                ),
                on_row(
                    "moderation_reports",
                    "{row}.decided_at",
                    after=report_keep,
                    events="UPDATE OF decided_at",
                    when="NEW.decided_at IS NOT NULL",
                ),
            ),
        ),
        Sweep(
            kind="hold_reminders",
            scope=Scope.PROVISIONED,
            every=hour,
            visit=holds.remind_due,
            next_due=lambda _now: select(
                func.min(func.coalesce(ContentHold.reminded_at, ContentHold.placed_at))
                + holds.REMINDER_INTERVAL
            ).where(
                col(ContentHold.released_at).is_(None),
                col(ContentHold.case_task_id).is_not(None),
            ),
            sources=(
                on_row(
                    "content_holds", "{row}.placed_at", after=holds.REMINDER_INTERVAL
                ),
            ),
        ),
        Sweep(
            kind="digest_gc",
            scope=Scope.LIVE,
            every=hour,
            visit=notifications.expire_digest_items,
            next_due=lambda _now: least(
                *(
                    select(
                        func.min(item.created_at)
                        + notifications.ASSIGNMENT_ITEM_RETENTION
                    )
                    for item in digest_items
                )
            ),
            sources=tuple(
                on_insert(
                    str(item.__tablename__),
                    after=notifications.ASSIGNMENT_ITEM_RETENTION,
                )
                for item in digest_items
            ),
        ),
        *(
            Sweep(
                kind=spec.name.replace("-", "_"),
                scope=Scope.LIVE,
                every=minute,
                # A person's digest gathers from every community they are in;
                # the finish answers when each community's waiting items are
                # next due.
                prepare=partial(_digest, spec),
                next_due=lambda now, spec=spec: select(
                    func.min(spec.model.created_at) + spec.quiet_period
                ).where(
                    col(spec.model.processed_at).is_(None),
                    spec.model.created_at > now - timedelta(days=1),
                ),
                sources=(
                    on_insert(str(spec.model.__tablename__), after=spec.quiet_period),
                ),
            )
            for spec in (notifications.ASSIGNMENT_DIGEST, notifications.REACTION_DIGEST)
        ),
        Sweep(
            kind="reminders",
            scope=Scope.LIVE,
            every=minute,
            # The visit reads each attendee's lead, so it answers exactly.
            prepare=_reminders,
            answers=True,
            next_due=lambda now: least(
                select(func.min(CalendarEvent.start_at) - timedelta(days=1))
                .join(
                    CalendarEventAttendee,
                    col(CalendarEventAttendee.calendar_event_id) == CalendarEvent.id,
                )
                .where(
                    col(CalendarEvent.recurrence).is_(None),
                    col(CalendarEvent.deleted_at).is_(None),
                    CalendarEvent.start_at > now - notifications.EVENT_REMINDER_GRACE,
                ),
                when_exists(
                    exists()
                    .where(
                        col(CalendarEventAttendee.calendar_event_id) == CalendarEvent.id
                    )
                    .where(
                        col(CalendarEvent.recurrence).is_not(None),
                        col(CalendarEvent.deleted_at).is_(None),
                        or_(
                            col(CalendarEvent.recurrence_until).is_(None),
                            CalendarEvent.recurrence_until > now,
                        ),
                    )
                ),
            ),
            sources=(
                on_row(
                    "calendar_events",
                    "CASE WHEN {row}.recurrence IS NULL"
                    " THEN {row}.start_at - interval '1 day' ELSE now() END",
                    events=(
                        "INSERT OR UPDATE OF start_at, recurrence,"
                        " recurrence_until, deleted_at"
                    ),
                    when="NEW.deleted_at IS NULL",
                ),
                on_row("calendar_event_attendees", "now()"),
                on_row("calendar_event_answers", "now()", events="INSERT OR UPDATE"),
            ),
        ),
        Sweep(
            kind="task_reminders",
            scope=Scope.LIVE,
            every=minute,
            prepare=_task_reminders,
            answers=True,
            next_due=lambda _now: select(func.min(PersonalItem.remind_at)).where(
                col(PersonalItem.remind_at).is_not(None),
                col(PersonalItem.reminded_at).is_(None),
            ),
            sources=(
                on_row(
                    "personal_items",
                    "{row}.remind_at",
                    events="INSERT OR UPDATE OF remind_at, reminded_at",
                    when="NEW.remind_at IS NOT NULL AND NEW.reminded_at IS NULL",
                ),
            ),
        ),
        Sweep(
            kind="overdue",
            scope=Scope.LIVE,
            every=timedelta(minutes=5),
            # The finish answers each community's next digest time: the
            # soonest of its people with overdue work.
            prepare=_overdue,
            next_due=lambda _now: notifications.next_overdue(),
            sources=(
                on_row(
                    "tasks",
                    "{row}.due_date",
                    events="INSERT OR UPDATE OF due_date, task_status_id, archived_at",
                    when="NEW.due_date IS NOT NULL AND NEW.archived_at IS NULL",
                ),
                on_row("task_assignees", "now()"),
                on_row(
                    "projects",
                    "now()",
                    events="UPDATE OF archived_at, is_template",
                ),
                # A status moved out of done reopens its tasks.
                on_row("task_statuses", "now()", events="UPDATE OF category"),
            ),
        ),
        Sweep(
            kind="coming_up",
            scope=Scope.LIVE,
            every=timedelta(minutes=5),
            # The finish answers each community's next digest time: the
            # soonest of its people with something coming up.
            prepare=_coming_up,
            next_due=lambda now: least(
                notifications.coming_up_tasks(
                    func.min(Task.due_date) - notifications.COMING_UP_REACH,
                    after=now,
                    until=None,
                ),
                notifications.attending(
                    func.min(CalendarEvent.start_at) - notifications.COMING_UP_REACH,
                    after=now,
                    until=None,
                ),
            ),
            sources=(
                on_row(
                    "tasks",
                    "{row}.due_date - interval '8 days'",
                    events="INSERT OR UPDATE OF due_date, task_status_id, archived_at",
                    when="NEW.due_date IS NOT NULL AND NEW.archived_at IS NULL",
                ),
                on_row("task_assignees", "now()"),
                on_row(
                    "calendar_events",
                    "CASE WHEN {row}.recurrence IS NULL"
                    " THEN {row}.start_at - interval '8 days' ELSE now() END",
                    events=(
                        "INSERT OR UPDATE OF start_at, recurrence,"
                        " recurrence_until, deleted_at"
                    ),
                    when="NEW.deleted_at IS NULL",
                ),
                on_row("calendar_event_attendees", "now()"),
                on_row("calendar_event_answers", "now()", events="INSERT OR UPDATE"),
                on_row(
                    "projects",
                    "now()",
                    events="UPDATE OF archived_at, is_template",
                ),
                # A status moved out of done reopens its tasks.
                on_row("task_statuses", "now()", events="UPDATE OF category"),
            ),
        ),
        Sweep(
            kind="plugin_updates",
            scope=Scope.ACTIVE,
            every=hour,
            # Armed by a catalog change (watch_catalog). A visit leaves no
            # timer; the daily reconcile looks again where installs track.
            visit=plugin_updates.update_guild,
            answers=True,
            next_due=lambda _now: when_exists(
                exists().where(col(GuildPlugin.auto_update).is_(True))
            ),
            sources=(
                on_row(
                    "guild_plugins",
                    "now()",
                    events="UPDATE OF auto_update",
                    when="NEW.auto_update AND NOT OLD.auto_update",
                ),
            ),
        ),
        Sweep(
            kind=community_hooks.KIND,
            # A deleted or suspended community's plug-ins are still told.
            scope=Scope.PROVISIONED,
            every=timedelta(seconds=community_hooks.BACKOFF_SECONDS[0]),
            calls_out=True,
            # Armed for now by each hook written, and by a change of the
            # community's status (community_hooks.status_changed).
            visit=community_hooks.visit,
            answers=True,
            next_due=lambda _now: select(literal(None)),
            due_outside=community_hooks.due_outside,
        ),
        Sweep(
            kind=RECONCILE,
            scope=Scope.PROVISIONED,
            every=RECONCILE_EVERY,
            visit=reconcile,
            answers=True,
            next_due=lambda now: select(literal(now + RECONCILE_EVERY)),
            # A community's first change starts its daily reconcile; after
            # that each reconcile arms the next.
            sources=(on_insert("event_outbox", after=RECONCILE_EVERY),),
        ),
    )


async def _digest(spec: Any) -> Scan:
    from app.services import notifications

    return notifications.digest_scan(spec, now=datetime.now(timezone.utc))


async def _reminders() -> Scan:
    from app.services import notifications

    return await notifications.reminder_scan(now=datetime.now(timezone.utc))


async def _task_reminders() -> Scan:
    from app.services import notifications

    return notifications.task_reminder_scan(now=datetime.now(timezone.utc))


async def _overdue() -> Scan:
    from app.services import notifications

    return notifications.overdue_scan(now=datetime.now(timezone.utc))


async def _coming_up() -> Scan:
    from app.services import notifications

    return notifications.coming_up_scan(now=datetime.now(timezone.utc))


def _by_kind() -> dict[str, Sweep]:
    return {sweep.kind: sweep for sweep in sweeps()}


async def arm(session: AsyncSession, kind: str, due: datetime) -> None:
    """Arm ``kind`` in the routed community at ``due``, the way a write does."""
    await session.exec(
        text("SELECT public.arm_timer(:kind, :due)").bindparams(kind=kind, due=due)  # type: ignore[call-overload]
    )


async def _next_due(
    session: AsyncSession, sweep: Sweep, now: datetime
) -> datetime | None:
    return (
        await session.exec(sweep.next_due(now).execution_options(include_deleted=True))
    ).first()


async def _arm_next(
    session: AsyncSession, guild_id: int, sweep: Sweep, due: datetime | None
) -> None:
    """Arm the sweep's next timer in the community, never sooner than its
    cadence."""
    now = datetime.now(timezone.utc)
    # A visit may leave its session routed elsewhere (a data job's outcome is
    # written from the unrouted context).
    await set_rls_context(session, SystemGuild(guild_id))
    if due is not None:
        await arm(session, sweep.kind, max(due, now + sweep.every))
    await session.commit()


def _visit_and_rearm(
    sweep: Sweep,
    visit: Visit,
    ids: list[int],
    done: set[int],
    finishing: dict[int, list[int]] | None,
) -> Visit:
    """``visit``, then the sweep's next timer, then the claimed rows marked
    for deletion. With ``finishing`` (a scan's), the rows wait for the scan's
    finish, and so does the next timer unless the visit answers it."""

    async def run(session: AsyncSession, guild_id: int) -> None:
        # Taken: a write from here on arms afresh rather than counting on the
        # timer this visit is.
        await session.exec(delete(TimerMark).where(col(TimerMark.kind) == sweep.kind))
        await session.commit()
        answered = await visit(session, guild_id)
        await session.commit()
        if finishing is not None and not sweep.answers:
            finishing[guild_id] = ids
            return
        due = (
            answered
            if sweep.answers
            else await _next_due(session, sweep, datetime.now(timezone.utc))
        )
        await _arm_next(session, guild_id, sweep, due)  # type: ignore[arg-type]
        # Only once the next timer is saved.
        if finishing is None:
            done.update(ids)
        else:
            finishing[guild_id] = ids

    return run


async def _finish(
    sweep: Sweep, scan: Scan, finishing: dict[int, list[int]], done: set[int]
) -> None:
    """Finish ``scan``, then arm each visited community's next timer from what
    it answered. A finish that fails leaves the timers to their lease."""
    try:
        answers = await scan.finish() or {}
    except Exception:
        logger.exception("timers: finishing %s failed", sweep.kind)
        return
    for guild_id, ids in finishing.items():
        async with cohorts.system_session(guild_id) as session:
            await _arm_next(session, guild_id, sweep, answers.get(guild_id))
        done.update(ids)


async def arm_now(
    session: AsyncSession, kind: str, community_ids: Iterable[int]
) -> None:
    """Arm ``kind`` now in each of ``community_ids`` on ``session``, a system
    session, in its transaction: for work it writes in ``public`` for them. A
    community already due for it is left alone, and one that is gone (purged
    since it was named) is skipped."""
    ids = sorted(set(community_ids))
    if not ids:
        return
    await session.exec(
        text(
            "INSERT INTO public.community_timers (community_id, kind, due_at)"
            " SELECT c, :kind, now() FROM unnest(CAST(:ids AS integer[])) c"
            " WHERE EXISTS (SELECT 1 FROM public.guilds g WHERE g.id = c)"
            " AND NOT EXISTS (SELECT 1 FROM public.community_timers t"
            " WHERE t.community_id = c AND t.kind = :kind AND t.due_at <= now())"
        ).bindparams(kind=kind, ids=ids)  # type: ignore[call-overload]
    )


async def arm_in(kind: str, community_ids: Iterable[int]) -> None:
    """Arm ``kind`` now in each of ``community_ids``, from outside them: for
    work a change in ``public`` gives them (a catalog release, a person's
    reminder lead). A community already due for it is left alone."""
    ids = sorted(set(community_ids))
    if not ids:
        return
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        await arm_now(session, kind, ids)
        await session.commit()


def _outward() -> list[str]:
    return [sweep.kind for sweep in sweeps() if sweep.calls_out]


async def _claim(now: datetime, *, outward: bool) -> list[Any]:
    """Claim up to :data:`BATCH` due timers of the lane, moving each a lease
    ahead."""
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        rows = (
            await session.exec(
                text(
                    """
                    WITH due AS (
                        SELECT id, due_at FROM community_timers
                        WHERE due_at <= :now AND community_id IS NOT NULL
                          AND (kind = ANY(:outward_kinds)) = :outward
                        ORDER BY due_at
                        LIMIT :batch
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE community_timers t SET due_at = :lease
                    FROM due WHERE t.id = due.id
                    RETURNING t.id, t.community_id, t.kind, due.due_at
                    """
                ).bindparams(  # type: ignore[call-overload]
                    now=now,
                    batch=BATCH,
                    lease=now + LEASE,
                    outward_kinds=_outward(),
                    outward=outward,
                )
            )
        ).all()
        await session.commit()
    return list(rows)


async def _delete(ids: set[int]) -> None:
    if not ids:
        return
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        await session.exec(
            text("DELETE FROM community_timers WHERE id = ANY(:ids)").bindparams(  # type: ignore[call-overload]
                ids=sorted(ids)
            )
        )
        await session.commit()


async def _run(claimed: list[Any], now: datetime, *, outward: bool) -> None:
    """Visit each claimed timer's community for its sweep."""
    registry = _by_kind()
    taken: dict[int, dict[str, list[int]]] = {}
    for timer_id, community_id, kind, due_at in claimed:
        if kind in registry:
            metrics.sweep_timer_lag.labels(kind).observe(
                max(0.0, (now - due_at).total_seconds())
            )
        taken.setdefault(community_id, {}).setdefault(kind, []).append(timer_id)
    prepared: dict[str, Visit | Scan | None] = {}
    for kind in {kind for kinds in taken.values() for kind in kinds}:
        sweep = registry.get(kind)
        if sweep is not None and sweep.prepare is not None:
            prepared[kind] = await sweep.prepare()
    done: set[int] = set()
    plan: dict[int, list[tuple[Scope, Visit]]] = {}
    scans: dict[str, tuple[Scan, dict[int, list[int]]]] = {}
    for community_id, kinds in taken.items():
        for kind, ids in kinds.items():
            # A kind this version does not know is another version's: left to
            # its lease for a process that does.
            sweep = registry.get(kind)
            if sweep is None:
                continue
            made = prepared[kind] if sweep.prepare is not None else sweep.visit
            if made is None:
                # Nothing to do anywhere this tick, and nothing to arm.
                done.update(ids)
                continue
            finishing = None
            if isinstance(made, Scan):
                scan, finishing = scans.setdefault(kind, (made, {}))
                visit = scan.visit
            else:
                visit = made
            plan.setdefault(community_id, []).append(
                (sweep.scope, _visit_and_rearm(sweep, visit, ids, done, finishing))
            )
    # A community the pass did not visit for a sweep (its status does not
    # admit it now) keeps that timer on its lease.
    if outward:
        limit = asyncio.Semaphore(OUTWARD_AT_ONCE)

        async def visit(community_id: int) -> None:
            async with limit:
                await each_guild(
                    [],
                    name="timers-outward",
                    planned={community_id: plan[community_id]},
                )

        await asyncio.gather(*(visit(community_id) for community_id in plan))
    else:
        await each_guild([], name="timers", planned=plan)
    for kind, (scan, finishing) in scans.items():
        sweep = registry[kind]
        if sweep.answers:
            # What the visits found is sent here: a finish that fails leaves
            # the timers to their lease.
            try:
                await scan.finish()
            except Exception:
                logger.exception("timers: finishing %s failed", kind)
                continue
            for ids in finishing.values():
                done.update(ids)
        else:
            await _finish(sweep, scan, finishing, done)
    await _delete(done)


#: Communities :func:`wake` named since the worker last looked, by sweep.
_woken: dict[str, set[int]] = {}


def wake(kind: str, guild_id: int) -> None:
    """Run ``kind`` in the community soon, from this process. Returns at once."""
    _woken.setdefault(kind, set()).add(guild_id)
    (outward_loop if kind in _outward() else loop).wake()


async def hint(_payload: str) -> None:
    """A timer was armed to run at once. Registered on
    :data:`~app.db.timers.WAKE_CHANNEL`."""
    loop.wake()
    outward_loop.wake()


async def process_due_timers(*, outward: bool = False) -> None:
    """Run every timer of the lane that has come due, a batch at a time."""
    for kind in [kind for kind in _woken if (kind in _outward()) == outward]:
        await arm_in(kind, _woken.pop(kind))
    while True:
        now = datetime.now(timezone.utc)
        claimed = await _claim(now, outward=outward)
        if claimed:
            await _run(claimed, now, outward=outward)
        if len(claimed) < BATCH:
            return


async def _pending_kinds(guild_id: int) -> set[str]:
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        return set(
            (
                await session.exec(
                    text(
                        "SELECT DISTINCT kind FROM community_timers"
                        " WHERE community_id = :community"
                    ).bindparams(community=guild_id)  # type: ignore[call-overload]
                )
            ).scalars()
        )


async def reconcile(session: AsyncSession, guild_id: int) -> datetime:
    """Arm every sweep that has work in the community and no timer for it, and
    count each one: a write no source covered. Returns the next reconcile."""
    now = datetime.now(timezone.utc)
    pending = await _pending_kinds(guild_id)
    checked = [
        sweep
        for sweep in sweeps()
        if sweep.kind != RECONCILE and sweep.due_outside is None
    ]
    probe = select(
        *(sweep.next_due(now).scalar_subquery().label(sweep.kind) for sweep in checked)
    ).execution_options(include_deleted=True)
    row = list((await session.exec(probe)).one())
    # The sweeps whose work the community's own role cannot read.
    for sweep in sweeps():
        if sweep.due_outside is not None:
            checked.append(sweep)
            row.append(await sweep.due_outside(guild_id, now))
    for sweep, due in zip(checked, row):
        if due is None or sweep.kind in pending:
            continue
        await session.exec(delete(TimerMark).where(col(TimerMark.kind) == sweep.kind))
        await arm(session, sweep.kind, max(due, now))
        metrics.sweep_timer_repairs.labels(sweep.kind).inc()
        logger.warning("reconcile: armed %s with no timer", sweep.kind)
    await session.commit()
    return now + RECONCILE_EVERY


#: How often the catalog is looked at for changes.
CATALOG_WATCH_SECONDS = 60


async def watch_catalog() -> None:
    """Arm plug-in updates and schedules in each community with an install of
    a listing the catalog changed lately: a new version, an edited listing, a
    registration that went live or changed. Looks back two intervals, so a
    change between two looks is never missed; arming one already due adds
    nothing."""
    since = datetime.now(timezone.utc) - timedelta(seconds=2 * CATALOG_WATCH_SECONDS)
    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        changed = (
            (
                await session.exec(
                    text(
                        "SELECT DISTINCT i.guild_id FROM plugin_installs i"
                        " WHERE i.listing_uid IN ("
                        " SELECT l.uid FROM marketplace_listings l"
                        " WHERE l.updated_at > :since"
                        " UNION SELECT l.uid FROM marketplace_listing_versions v"
                        " JOIN marketplace_listings l ON l.id = v.listing_id"
                        " WHERE v.published_at > :since"
                        " UNION SELECT r.listing_uid FROM plugin_service_registrations r"
                        " WHERE r.updated_at > :since)"
                    ).bindparams(since=since)  # type: ignore[call-overload]
                )
            )
            .scalars()
            .all()
        )
    for kind in ("plugin_updates", "plugin_schedules"):
        await arm_in(kind, changed)


#: The worker's loop.
loop = Loop("timers", interval=TICK_SECONDS, settle=WAKE_SETTLE_SECONDS)
#: The outward lane's loop.
outward_loop = Loop("timers-outward", interval=TICK_SECONDS, settle=WAKE_SETTLE_SECONDS)
#: The catalog watch's loop.
catalog_loop = Loop("catalog-watch", interval=CATALOG_WATCH_SECONDS)
