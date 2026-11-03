"""The export worker's own rules on the shared dispatcher: an abandoned render
is started over until it has been too often, a render that lost its row writes
nothing, and a build is cancelled when its heartbeat finds the row taken.
Claiming and slots are tested once, through imports; expiry in
``exports_test``."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.core.config import settings
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.data_job import DataJob, DataJobStatus
from app.services.export import engine as export_engine
from app.services.export import limits as export_limits
from app.services.export import worker as export_worker
from app.services.import_engine import atlassian
from app.testing import (
    create_export_job,
    create_task,
    route_session_to_guild,
    drain_notices,
)


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


async def _actor(acting_user, session):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task(session, a.project, title="Task")
    return a


async def _reload(session, guild_id: int, job_id: int) -> DataJob:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    job = await session.get(DataJob, job_id)
    assert job is not None
    return job


async def _notices(
    session,
    user_id: int,
    job_id: int,
    kind: NotificationType = NotificationType.export_ready,
) -> int:
    await drain_notices()
    rows = await session.exec(
        select(Notification).where(Notification.user_id == user_id)
    )
    return sum(
        1 for n in rows if n.type == kind and n.data.get("export_job_id") == job_id
    )


@pytest.mark.parametrize(
    ("restarts", "ends", "told"),
    [
        (0, "done", NotificationType.export_ready),
        (
            export_limits.EXPORT_MAX_RESTARTS,
            "failed",
            NotificationType.export_failed,
        ),
    ],
)
async def test_an_abandoned_render_is_started_over_until_it_has_been_too_often(
    acting_user, session, restarts, ends, told
):
    """A ``running`` row nobody has touched for the stale window is rendered
    again from the start, until it has been started over
    ``EXPORT_MAX_RESTARTS`` times; then it fails. Either way its creator hears
    once."""
    a = await _actor(acting_user, session)
    job = await create_export_job(
        session,
        a.guild,
        a.user,
        status=DataJobStatus.running,
        restarts=restarts,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )

    await export_worker.process_export_jobs()

    assert (await _reload(session, a.guild.id, job.id)).status == ends
    assert await _notices(session, a.user.id, job.id, told) == 1


async def test_a_render_that_lost_its_row_writes_nothing(
    acting_user, session, monkeypatch
):
    """A render whose row was queued again while it ran stops without
    recording an outcome; the next claim renders it, and the creator is told
    once."""
    a = await _actor(acting_user, session)
    job = await create_export_job(session, a.guild, a.user)
    real_execute = export_worker._execute
    calls = 0

    async def execute(bookkeeping, running, *, guild_id, heartbeat):
        nonlocal calls
        calls += 1
        if calls == 1:
            row = await _reload(session, guild_id, running.id)
            row.status = DataJobStatus.queued
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            await session.commit()
            return frozenset(), export_engine.ArtifactLocation(
                artifact_ref="exports/lost.pdf"
            )
        return await real_execute(
            bookkeeping, running, guild_id=guild_id, heartbeat=heartbeat
        )

    monkeypatch.setattr(export_worker, "_execute", execute)

    await export_worker.process_export_jobs()

    assert calls == 2
    done = await _reload(session, a.guild.id, job.id)
    assert done.status == "done"
    assert done.file_ref != "exports/lost.pdf"
    assert await _notices(session, a.user.id, job.id) == 1


async def test_a_build_stops_when_its_heartbeat_finds_the_row_taken(monkeypatch):
    """The heartbeat ticks while the adapter builds; one that raises cancels
    the build rather than letting it run on."""
    monkeypatch.setattr(atlassian, "HEARTBEAT_SECONDS", 0)
    built = asyncio.Event()

    async def build():
        await asyncio.sleep(3600)
        built.set()

    async def heartbeat() -> None:
        raise export_worker._Superseded

    with pytest.raises(export_worker._Superseded):
        await export_worker._beating(build(), heartbeat)
    assert not built.is_set()
