"""The import worker's own housekeeping: expiry reaches a community that is not
active, secrets go from jobs that are over, and the apply's session is drawn
from the community's cohort."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.db import cohorts
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, CommunityRole, CommunityStatus
from app.models.tenant.data_job import DataJob, DataJobStatus
from app.services import data_jobs
from app.services.guild_sweeps import Scope, each_guild
from app.services.import_engine import worker as import_worker
from app.services.storage import get_guild_storage
from app.testing import create_guild, create_import_job, route_session_to_guild
from app.db.request_context import SystemGuild


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


async def _reload(session, guild_id: int, job_id: int) -> DataJob:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    job = await session.get(DataJob, job_id)
    assert job is not None
    return job


async def test_gc_reaches_a_community_that_is_not_active(acting_user, session):
    """A staged payload past its deadline goes, with the job's secret, from a
    community that is not active too."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    key = "imports/gc-elsewhere.zip"
    get_guild_storage(a.guild.id).write(key, b"PK-fake", content_type="application/zip")
    job = await create_import_job(
        session,
        a.guild,
        a.user,
        status=DataJobStatus.staged,
        file_ref=key,
        secret_encrypted="sealed",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    guild = await session.get(Guild, a.guild.id)
    guild.status = CommunityStatus.read_only.value
    session.add(guild)
    await session.commit()

    await each_guild([(Scope.PROVISIONED, data_jobs.expire_files)], name="t")

    assert get_guild_storage(a.guild.id).open_readable(key) is None
    expired = await _reload(session, a.guild.id, job.id)
    assert (expired.status, expired.file_ref, expired.secret_encrypted) == (
        "expired",
        None,
        None,
    )


@pytest.mark.parametrize(
    ("status", "expires_in", "keeps_secret"),
    [
        (DataJobStatus.done, None, False),
        (DataJobStatus.failed, None, False),
        (DataJobStatus.cancelled, None, False),
        # A queued job before its deadline still needs its secret to start.
        (DataJobStatus.queued, timedelta(hours=1), True),
    ],
)
async def test_gc_clears_a_secret_only_from_a_job_that_is_over(
    acting_user, session, status, expires_in, keeps_secret
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    job = await create_import_job(
        session,
        a.guild,
        a.user,
        status=status,
        secret_encrypted="sealed",
        expires_at=datetime.now(timezone.utc) + expires_in if expires_in else None,
    )

    await each_guild([(Scope.PROVISIONED, data_jobs.expire_files)], name="t")

    after = await _reload(session, a.guild.id, job.id)
    assert after.status == status.value
    assert (after.secret_encrypted == "sealed") is keeps_secret


async def test_the_apply_session_comes_from_the_communitys_cohort(session):
    """Each community's apply runs on a session from its own cohort's system
    pool, which routes into it."""
    guilds = [await create_guild(session) for _ in range(3)]
    assert len({cohorts.cohort_of(g.id) for g in guilds}) > 1

    for guild in guilds:
        maker = cohorts.system_sessionmaker(guild.id)
        async with import_worker._open_user_session(guild.id) as user_session:
            assert user_session.bind is maker.kw["bind"]
            await set_rls_context(user_session, SystemGuild(guild.id))
            assert (await user_session.exec(text("SELECT 1"))).scalar_one() == 1
