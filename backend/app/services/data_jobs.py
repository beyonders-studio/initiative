"""The dispatcher imports and exports share.

A data job is a ``DataJob`` row in its community's own schema, an import or
an export, that a background visit claims and runs. The claim is visited
by the ``data_jobs`` timer that queuing or ending a job arms at once, and again
once the job's slot is free. Every API process does this, so the claim is
decided in the database: under a transaction-scoped
advisory lock on the community, so two processes never claim in the same
community at once, a community with a job already active gets no second one,
and the oldest queued job goes first.

Each job needs a slot of some kind (an import fetches or applies; an export
renders), and a process runs at most so many of each kind at once. A claimed
job runs as a task of its own, on a system session of its own, and tells its
creator how it ended.

The ``stale_jobs`` timer sweeps a community for jobs whose row has gone quiet,
which nobody is running any more. What happens to one depends on the job type, so
the sweep is the worker's. Jobs this process is running are left out of it:
they are known to be alive.

The ``data_job_expiry`` timer deletes a job's file at its deadline, whichever
way the job runs (:func:`expire_files`).

Bookkeeping runs on the system engine, routed into the community with
``guild_id`` alone; the policies' system leg names that login. Notifications
are written from the unrouted system context, since the shared notifications
table is in no community's schema.
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import audit_context
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.core.config import settings
from app.db.session import set_rls_context
from app.models.platform.notification import NotificationType
from app.models.tenant.data_job import (
    HOLDS_FILE,
    DataJob,
    DataJobDirection,
    DataJobStatus,
)
from app.services import sweep_timers
from app.services.guild_sweeps import Scope, each_guild
from app.services.platform import notice_outbox
from app.db.request_context import SystemGuild, Unattributed

logger = logging.getLogger(__name__)

#: Who to tell, what to tell them, and the notification's data.
JobOutcome = tuple[int, NotificationType, dict[str, Any]]

Heartbeat = Callable[[], Awaitable[None]]

#: ``(session, *, guild_id, now, own)``: deal with one community's quiet rows,
#: leaving alone ``own``, the ids of the jobs this process is running there.
#: Returns the notifications to send.
Sweep = Callable[..., Awaitable[list[JobOutcome]]]

#: ``(session, job, *, guild_id, kind)``: run one claimed job to the end and
#: record how it ended. Returns the notification to send, if there is one.
Runner = Callable[..., Awaitable[JobOutcome | None]]


#: The statuses of an import that is over, which needs no secret however it
#: ended.
IMPORT_OVER = (
    DataJobStatus.done,
    DataJobStatus.failed,
    DataJobStatus.cancelled,
    DataJobStatus.expired,
)

#: Every dispatcher, for :func:`cancel_running_jobs`.
_dispatchers: weakref.WeakSet[Dispatcher] = weakref.WeakSet()


@dataclass(eq=False)
class Dispatcher:
    """Claims and runs the data jobs of one direction.

    ``kind_of`` says which kind of slot a queued job needs, ``start_status``
    what a claimed job of that kind moves to, and ``slots`` how many jobs of a
    kind this process runs at once (read on every claim, so a changed limit
    applies to the next one). ``active`` is every status a job holds while it
    runs; a community with a job in one of them is not claimed from.
    """

    #: Names the job type in task names and log lines.
    name: str
    direction: DataJobDirection
    #: The advisory-lock namespace this job type claims under.
    lock_namespace: LockNamespace
    active: tuple[DataJobStatus, ...]
    kinds: tuple[str, ...]
    kind_of: Callable[[DataJob], str]
    start_status: Callable[[str], DataJobStatus]
    slots: Callable[[str], int]
    sweep: Sweep
    run: Runner
    #: The jobs this process is running, by ``(guild_id, job_id)``, with the
    #: kind of slot each holds. A job being claimed holds its slot with no
    #: task yet.
    running: dict[tuple[int, int], tuple[str, asyncio.Task[None] | None]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        _dispatchers.add(self)

    def free_slot(self, kind: str) -> bool:
        held = sum(1 for slot, _task in self.running.values() if slot == kind)
        return held < self.slots(kind)

    def own_job_ids(self, guild_id: int) -> list[int]:
        return [job_id for (guild, job_id) in self.running if guild == guild_id]

    async def process(self) -> None:
        """Run passes until one starts nothing, waiting for each pass's jobs.
        Everything queued is dealt with by the time this returns."""
        while True:
            started = await self.dispatch()
            if not started:
                return
            await asyncio.gather(*started)

    async def dispatch(self) -> list[asyncio.Task[None]]:
        """One pass over every active community: sweep, then claim. Returns
        the tasks it started; each runs, records its outcome and notifies on
        its own."""
        started: list[asyncio.Task[None]] = []

        async def start(session: AsyncSession, guild_id: int) -> None:
            task = await self.claim(session, guild_id)
            if task is not None:
                started.append(task)

        await each_guild(
            [(Scope.ACTIVE, self.sweep_stale), (Scope.ACTIVE, start)], name=self.name
        )
        return started

    async def sweep_stale(self, session: AsyncSession, guild_id: int) -> None:
        """Deal with the community's quiet rows, and tell their creators."""
        outcomes = await self.sweep(
            session,
            guild_id=guild_id,
            now=datetime.now(timezone.utc),
            own=self.own_job_ids(guild_id),
        )
        await session.commit()
        await notify(session, outcomes)

    async def claim(
        self, session: AsyncSession, guild_id: int
    ) -> asyncio.Task[None] | None:
        """Start the community's next queued job, when a slot can take it.
        Returns the task it started."""
        if not any(self.free_slot(kind) for kind in self.kinds):
            return None
        claimed = await self._claim(
            session, guild_id=guild_id, now=datetime.now(timezone.utc)
        )
        if claimed is None:
            return None
        job_id, kind = claimed
        key = (guild_id, job_id)
        task = asyncio.create_task(
            self._run(guild_id, job_id, kind),
            name=f"{self.name}-{guild_id}-{job_id}",
        )
        self.running[key] = (kind, task)
        task.add_done_callback(lambda _task, key=key: self.running.pop(key, None))
        return task

    async def cancel_running(self) -> None:
        """Stop every job this process is running, for shutdown. What becomes
        of a stopped job is the sweep's decision, once its row goes quiet."""
        tasks = [task for _kind, task in list(self.running.values()) if task]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def _claim(
        self, session: AsyncSession, *, guild_id: int, now: datetime
    ) -> tuple[int, str] | None:
        """Claim the community's oldest queued job, when it has no job active
        and a slot of the right kind is free.

        Decided under a lock on the community, so two passes, on two
        processes, cannot each claim one. The claim is committed before the
        job starts, so a crash leaves a quiet row for the sweep rather than a
        queued one that looks untouched.
        """
        await advisory_lock(session, self.lock_namespace, guild_id)
        active = (
            await session.exec(
                select(func.count())
                .select_from(DataJob)
                .where(
                    DataJob.direction == self.direction,
                    col(DataJob.status).in_(self.active),
                )
            )
        ).one()
        job = (
            None
            if active
            else (
                await session.exec(
                    select(DataJob)
                    .where(
                        DataJob.direction == self.direction,
                        DataJob.status == DataJobStatus.queued,
                    )
                    .order_by(col(DataJob.created_at).asc())
                    .limit(1)
                    .with_for_update()
                )
            ).first()
        )
        if job is None:
            await session.commit()
            return None
        kind = self.kind_of(job)
        if not self.free_slot(kind):
            await session.commit()
            return None
        # The slot is held from here, so a claim in another cohort's visit
        # running alongside this one finds it taken.
        assert job.id is not None
        key = (guild_id, job.id)
        self.running[key] = (kind, None)
        try:
            job.status = self.start_status(kind)
            job.updated_at = now
            session.add(job)
            await session.commit()
        except BaseException:
            self.running.pop(key, None)
            raise
        return key[1], kind

    async def _run(self, guild_id: int, job_id: int, kind: str) -> None:
        """One claimed job, start to finish, on a session of its own. Once it
        ends, the community's next queued job may start."""
        with audit_context.job(self.name, guild_id=guild_id):
            try:
                async with cohorts.system_session(guild_id) as session:
                    await set_rls_context(session, SystemGuild(guild_id))
                    job = (
                        await session.exec(
                            select(DataJob).where(
                                DataJob.id == job_id,
                                DataJob.direction == self.direction,
                            )
                        )
                    ).one_or_none()
                    if job is None:
                        return
                    # End the read here rather than holding it open for as long
                    # as the job runs.
                    await session.commit()
                    outcome = await self.run(session, job, guild_id=guild_id, kind=kind)
                    if outcome is not None:
                        await notify(session, [outcome])
            except Exception:
                logger.exception("%s job task failed id=%s", self.name, job_id)
            finally:
                # Out of the slot before the wake, so this process can claim
                # again.
                self.running.pop((guild_id, job_id), None)
        sweep_timers.wake("data_jobs", guild_id)


async def cancel_running_jobs() -> None:
    """Stop every data job this process is running, for shutdown."""
    for dispatcher in list(_dispatchers):
        await dispatcher.cancel_running()


async def notify(session: AsyncSession, outcomes: list[JobOutcome]) -> None:
    """Tell each job's creator how it ended."""
    if not outcomes:
        return
    # From the UNROUTED system context: the guild routing carries no user
    # GUC, so the shared notifications table's own-row policies would refuse
    # the insert there.
    await set_rls_context(session, Unattributed())
    await notice_outbox.enqueue(
        session,
        [
            notice_outbox.row(
                user_id, data.get("community_id"), notification_type, data
            )
            for user_id, notification_type, data in outcomes
        ],
    )
    await session.commit()


async def find(
    session: AsyncSession,
    job_id: int,
    direction: DataJobDirection,
    *,
    for_update: bool = False,
) -> DataJob | None:
    """The job ``job_id`` when it goes ``direction``; ``None`` for one the
    caller cannot see, or one going the other way."""
    query = select(DataJob).where(DataJob.id == job_id, DataJob.direction == direction)
    if for_update:
        query = query.with_for_update()
    return (await session.exec(query)).first()


def holds_file() -> Any:
    """Rows whose job still holds its file (:data:`HOLDS_FILE`)."""
    return or_(
        *(
            and_(DataJob.direction == direction, col(DataJob.status).in_(statuses))
            for direction, statuses in HOLDS_FILE.items()
        )
    )


async def expire_files(session: AsyncSession, guild_id: int) -> None:
    """Delete the community's job files past ``expires_at`` (through the
    storage backend, so local FS and S3 behave identically) and mark their
    jobs expired: an export's artifact, an import's payload left unconfirmed.
    Terminal imports keep their (small) result reports, and any secret an
    import that is over still holds is cleared.

    Visited in every community whose schema exists, whatever its status: a
    read-only or suspended community's files expire like anyone's. On a demo
    deployment a pitch's newest backup is kept: it is what its links copy."""
    from app.services.storage import get_guild_storage

    now = datetime.now(timezone.utc)
    jobs = list(
        await session.exec(
            select(DataJob).where(
                holds_file(),
                col(DataJob.expires_at).is_not(None),
                col(DataJob.expires_at) < now,
            )
        )
    )
    if jobs and settings.DEMO_MODE:
        from app.demo import pitches

        published = await pitches.published_export_id(session, guild_id)
        jobs = [job for job in jobs if job.id != published]
    storage = get_guild_storage(guild_id) if jobs else None
    for job in jobs:
        if job.file_ref and storage is not None:
            try:
                await asyncio.to_thread(storage.delete, job.file_ref)
            except Exception:
                # Expire the row anyway: a permanently failing delete (key
                # already gone, bucket misconfig) must not pin the job and
                # re-fail every pass.
                logger.exception(
                    "data job gc: file delete failed job=%s ref=%s guild=%s",
                    job.id,
                    job.file_ref,
                    guild_id,
                )
        job.status = DataJobStatus.expired
        job.file_ref = None
        job.secret_encrypted = None
        job.updated_at = now
        session.add(job)
    lent = list(
        await session.exec(
            select(DataJob).where(
                DataJob.direction == DataJobDirection.import_,
                col(DataJob.status).in_(IMPORT_OVER),
                col(DataJob.secret_encrypted).is_not(None),
            )
        )
    )
    for job in lent:
        job.secret_encrypted = None
        session.add(job)
    await session.commit()
