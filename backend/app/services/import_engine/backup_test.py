"""Backup jobs made by the shared service, with a bundle exported from a
factory-made community: dates move from an anchor, and an initiative keeps its
join policy."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import select

from app.core.config import settings
from app.models.platform.guild import CommunityRole
from app.models.tenant.export_job import ExportJobStatus
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import Initiative, InitiativeJoinPolicy
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.services.export import worker as export_worker
from app.services.import_engine import worker as import_worker
from app.services.import_engine.backup import stage_backup_job
from app.testing import create_task, route_session_to_guild

DUE_IN = timedelta(days=2)


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


@pytest.fixture
async def exported(client, acting_user, session, tmp_path):
    """A community whose initiative takes requests to join and holds a task
    due ``DUE_IN`` from now, exported as a backup zip."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    a.initiative.join_policy = InitiativeJoinPolicy.request.value
    session.add(a.initiative)
    due = datetime.now(timezone.utc).replace(microsecond=0) + DUE_IN
    await create_task(session, a.project, title="Proof the dough", due_date=due)

    queued = await client.get(a.g("/exports/community"), headers=a.headers)
    assert queued.status_code == 202, queued.text
    await export_worker.process_export_jobs()
    job_id = queued.json()["id"]
    job = await client.get(a.g(f"/exports/jobs/{job_id}"), headers=a.headers)
    assert job.json()["status"] == ExportJobStatus.done.value
    download = await client.get(
        a.g(f"/exports/jobs/{job_id}/download"), headers=a.headers
    )
    bundle = tmp_path / "bakery.zip"
    bundle.write_bytes(download.content)
    return a, due, bundle


async def _restore(session, a, bundle: Path, anchor: datetime | None) -> Initiative:
    """The bundle restored by a queued job, and the initiative it made."""
    guild_id = a.guild.id
    await route_session_to_guild(session, guild_id)
    job = await stage_backup_job(
        session,
        guild_id=guild_id,
        user=a.user,
        payload=bundle,
        status=ImportJobStatus.queued,
        anchor=anchor,
    )
    await session.commit()
    job_id = job.id
    await import_worker.process_import_jobs()

    session.expire_all()
    await route_session_to_guild(session, guild_id)
    job = await session.get(ImportJob, job_id)
    assert job is not None and job.status == ImportJobStatus.done, job.error
    (restored,) = job.result["initiatives"]
    initiative = await session.get(Initiative, restored["initiative_id"])
    assert initiative is not None
    return initiative


async def _restored_due_date(session, initiative: Initiative) -> datetime:
    (due,) = await session.exec(
        select(Task.due_date)
        .join(Project, Project.id == Task.project_id)
        .where(Project.initiative_id == initiative.id)
    )
    return due


async def test_an_anchored_backup_lands_its_dates_as_far_from_now(exported, session):
    a, due, bundle = exported

    initiative = await _restore(
        session, a, bundle, anchor=datetime.now(timezone.utc) - timedelta(days=30)
    )

    # Due two days after the anchor, so two days from now.
    assert (await _restored_due_date(session, initiative)).date() == (
        due + timedelta(days=30)
    ).date()


async def test_a_backup_restores_its_dates_and_join_policy_as_they_were(
    exported, session
):
    a, due, bundle = exported

    initiative = await _restore(session, a, bundle, anchor=None)

    assert await _restored_due_date(session, initiative) == due
    assert initiative.join_policy == InitiativeJoinPolicy.request.value
