"""Export worker: claims queued export jobs, re-runs their query, renders.

The job row persists only the filter *selector*, so the worker re-executes
the source adapter's query at render time — under a session routed as the
job's CREATOR via ``establish_guild_access`` (the same resolve-and-apply
primitive the WebSocket path uses). That makes the snapshot's RLS query the
single authorization point and honors access revoked between request and
render (the job fails closed).

Jobs are claimed and run by the dispatcher exports share with imports
(``app.services.data_jobs``): a community renders one export at a time, a
process renders at most ``EXPORT_RENDER_SLOTS`` at once, and each render is a
task on its own system session. Bookkeeping (the sweep, the claim, status
flips) runs on the system engine routed into the community with ``guild_id``
alone; the policies' system leg names that login.

A render touches its row as it goes, once per artifact and at most every few
seconds, so a long export is told apart from a dead one. A ``running`` row
untouched for ``STALE_RUNNING`` that no job in this process owns has nobody
behind it, and goes back in the queue: in-flight state is only the row, and a
re-render by job id overwrites the same storage key, so starting again is
safe. A render that finds its row has been queued again, or claimed since,
stops without writing anything, so a job finishes and notifies once.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta, timezone

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.core.user_display import name_here
from app.db import cohorts
from app.db.advisory_locks import LockNamespace
from app.models.platform.notification import NotificationType
from app.models.platform.user import UserStatus
from app.models.tenant.data_job import DataJob, DataJobDirection, DataJobStatus
from app.services import data_jobs
from app.services.data_jobs import JobOutcome
from app.services.export import engine as export_engine
from app.services.platform import accounts as accounts_service
from app.services.export import limits as export_limits
from app.services.import_engine import atlassian
from app.services.import_engine.atlassian import throttled

logger = logging.getLogger(__name__)

# A ``running`` row untouched this long is a render nobody is doing any more;
# the sweep queues it again. A live render touches its row as it goes.
STALE_RUNNING = timedelta(minutes=15)

_ERROR_MAX_LEN = 500

_RENDER = "render"


class _Superseded(Exception):
    """The job's row was queued again, or claimed since, while this render
    ran: the render stops and leaves the row to whoever has it now."""


def _open_read_session(guild_id: int) -> AbstractAsyncContextManager[AsyncSession]:
    """A read-only session for rendering in ``guild_id``'s community: on the
    read replica when DATABASE_URL_QUERY names one, from the community's
    cohort. Resolved at call time, so the test harness's pools apply."""
    return cohorts.read_session(guild_id)


async def _sweep(
    session: AsyncSession, *, guild_id: int, now: datetime, own: list[int]
) -> list[JobOutcome]:
    """Queue abandoned renders again, or fail one that has been started over
    ``EXPORT_MAX_RESTARTS`` times already. Jobs this process is running
    (``own``) are left alone: they are known to be alive.

    Rows are locked as they are read, so a row a live render touches while
    the sweep waits for it is read again and no longer matches."""
    abandoned = list(
        await session.exec(
            select(DataJob)
            .where(
                DataJob.direction == DataJobDirection.export,
                DataJob.status == DataJobStatus.running,
                DataJob.updated_at < now - STALE_RUNNING,
                col(DataJob.id).not_in(own),
            )
            .with_for_update()
        )
    )
    outcomes: list[JobOutcome] = []
    for job in abandoned:
        if job.restarts >= export_limits.EXPORT_MAX_RESTARTS:
            logger.warning(
                "export render abandoned too often id=%s guild=%s source=%s",
                job.id,
                guild_id,
                job.source,
            )
            job.status = DataJobStatus.failed
            job.error = ExportMessages.EXPORT_RENDER_FAILED
            _forget_filters(job)
            outcomes.append(_outcome(job, guild_id))
        else:
            logger.warning(
                "export render re-queued id=%s guild=%s source=%s",
                job.id,
                guild_id,
                job.source,
            )
            job.status = DataJobStatus.queued
            job.restarts += 1
        job.updated_at = now
        session.add(job)
    if abandoned:
        await session.commit()
    return outcomes


async def _render(
    session: AsyncSession, job: DataJob, *, guild_id: int, kind: str
) -> JobOutcome | None:
    """Render a claimed job and record how it ended."""
    # The last ``updated_at`` this render wrote, starting with the claim's.
    # A row that says anything else has been queued again or claimed since.
    touched = job.updated_at

    async def still_ours() -> bool:
        await session.refresh(job, with_for_update=True)
        return job.status == DataJobStatus.running and job.updated_at == touched

    async def touch() -> None:
        nonlocal touched
        if not await still_ours():
            await session.commit()
            raise _Superseded
        touched = datetime.now(timezone.utc)
        job.updated_at = touched
        session.add(job)
        await session.commit()

    try:
        reach, location = await _execute(
            session, job, guild_id=guild_id, heartbeat=throttled(touch)
        )
    except _Superseded:
        logger.info("export render superseded id=%s guild=%s", job.id, guild_id)
        return None
    except Exception as exc:  # fail closed: no partial artifact is served
        logger.exception(
            "export job failed id=%s guild=%s source=%s",
            job.id,
            guild_id,
            job.source,
        )
        # Whatever failed may have been a heartbeat's write; start clean.
        await session.rollback()
        if not await still_ours():
            await session.commit()
            return None
        job.status = DataJobStatus.failed
        job.error = _error_code(exc)
    else:
        if not await still_ours():
            await session.commit()
            logger.info("export render superseded id=%s guild=%s", job.id, guild_id)
            return None
        job.status = DataJobStatus.done
        job.file_ref = location.artifact_ref
        job.destination_ref = location.destination_ref
        job.initiative_ids = sorted(reach)
        job.error = None
        # Only an artifact the app holds has a GC deadline. A delivered
        # archive sits in the operator's destination under whatever
        # retention they keep there, and is not ours to sweep up.
        job.expires_at = (
            datetime.now(timezone.utc)
            + timedelta(hours=export_limits.EXPORT_ARTIFACT_TTL_HOURS)
            if location.artifact_ref
            else None
        )
    _forget_filters(job)
    job.updated_at = datetime.now(timezone.utc)
    session.add(job)
    await session.commit()
    return _outcome(job, guild_id)


def _forget_filters(job: DataJob) -> None:
    """Filters are one person's instruction for one render. Once it has ended,
    the row keeps none of them."""
    if job.params and "filters" in job.params:
        job.params = {k: v for k, v in job.params.items() if k != "filters"}


def _outcome(job: DataJob, guild_id: int) -> JobOutcome:
    """What the creator is told. They may have navigated away while the render
    ran — an inbox entry is how they reach the artifact afterwards. Data
    mirrors the other notification payloads: ids only plus what the bell
    displays."""
    return (
        job.created_by,
        NotificationType.export_ready
        if job.status == DataJobStatus.done
        else NotificationType.export_failed,
        {
            "community_id": guild_id,
            "export_job_id": job.id,
            "source": job.source,
            "format": job.format,
        },
    )


jobs = data_jobs.Dispatcher(
    name="export",
    direction=DataJobDirection.export,
    lock_namespace=LockNamespace.EXPORT_CLAIM,
    active=(DataJobStatus.running,),
    kinds=(_RENDER,),
    kind_of=lambda _job: _RENDER,
    start_status=lambda _kind: DataJobStatus.running,
    slots=lambda _kind: export_limits.EXPORT_RENDER_SLOTS,
    sweep=_sweep,
    run=_render,
)


async def process_export_jobs() -> None:
    """Run passes until one starts nothing, waiting for each pass's jobs.
    Everything queued is dealt with by the time this returns."""
    await jobs.process()


async def _execute(
    session: AsyncSession,
    job: DataJob,
    *,
    guild_id: int,
    heartbeat: data_jobs.Heartbeat,
) -> tuple[frozenset[int], export_engine.ArtifactLocation]:
    """Re-run the adapter query as the job's creator and render it out.
    Returns the initiatives the artifact holds, and where it was written."""
    from app.api.deps import establish_guild_access

    adapter = export_engine.get_adapter(job.source, job.format)

    # The session is routed into the guild here, which is not somewhere an
    # account may be read; the creator comes off the system engine instead.
    user = await accounts_service.load_one(job.created_by)
    if user is None or user.status != UserStatus.active:
        raise export_engine.ExportError(ExportMessages.EXPORT_CREATOR_INACTIVE)

    async def build() -> export_engine.RenderRequest:
        async with _open_read_session(guild_id) as user_session:
            # Resolve membership/PAM and route the session as the creator;
            # raises GuildAccessError (-> failed job) if their access is gone.
            # The job is user-attributed system work — its enqueueing request
            # already passed the guild auth-policy gate, so it carries the
            # system sentinel.
            await establish_guild_access(user_session, user, guild_id, on_behalf=True)
            request = await adapter.build(
                user_session,
                user=user,
                guild_id=guild_id,
                params=job.params or {},
                format=job.format,
            )
            # Load the guild brand while the routed session is still open (it
            # reads the shared guild row); the icon bytes ride on the request.
            from app.services.export.branding import apply_brand
            from app.services.export.stamp import stamp_export

            request = await apply_brand(request, user_session)
            return stamp_export(request, await name_here(user_session, user))

    request = await _beating(build(), heartbeat)

    assert job.id is not None
    return request.initiative_ids, await export_engine.render_to_storage(
        request,
        job_id=job.id,
        source=job.source,
        tz=(job.params or {}).get("tz"),
        heartbeat=heartbeat,
    )


async def _beating(
    work: Awaitable[export_engine.RenderRequest], heartbeat: data_jobs.Heartbeat
) -> export_engine.RenderRequest:
    """``work``, with ``heartbeat`` called every ``HEARTBEAT_SECONDS`` while it
    runs, so a long build keeps its row fresh. A heartbeat that
    raises (the row was taken over) cancels the work and raises."""

    async def beat() -> None:
        while True:
            await asyncio.sleep(atlassian.HEARTBEAT_SECONDS)
            await heartbeat()

    worker = asyncio.ensure_future(work)
    beater = asyncio.ensure_future(beat())
    try:
        await asyncio.wait({worker, beater}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (worker, beater):
            if not task.done():
                task.cancel()
        await asyncio.gather(worker, beater, return_exceptions=True)
    if not beater.cancelled():
        beater.result()
    return worker.result()


def _error_code(exc: Exception) -> str:
    """The job row must never accumulate content — store a short code, not an
    exception message that could echo query/user data."""
    if isinstance(exc, export_engine.ExportError):
        return exc.code[:_ERROR_MAX_LEN]
    from app.api.deps import GuildAccessError

    if isinstance(exc, GuildAccessError):
        return ExportMessages.EXPORT_ACCESS_REVOKED
    return ExportMessages.EXPORT_RENDER_FAILED
