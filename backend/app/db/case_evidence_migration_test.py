"""Migration 20261105_0578 names a case's evidence by the case's task.

Run on a community the test builds, in one transaction rolled back at the end:
a case with a file attached, the revision stepped down so the file names the
case row as an older release kept it, and up again. The file names the case's
task, then its case, then its task again.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.intake import IntakeStream
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.tenant.evidence import Evidence
from app.models.tenant.intake import IntakeCase
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
    make_operations_community,
)

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261105_0578_a_cases_evidence_names_its_task.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(migration: ModuleType, forward: bool):
    def apply(sync_session) -> None:
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            (migration.upgrade if forward else migration.downgrade)()

    return apply


async def test_a_cases_evidence_moves_from_its_case_to_its_task(session) -> None:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)
    # A first task with no case, so the case's row and its task differ in id.
    await create_task(session, project)
    task = await create_task(session, project)
    await make_operations_community(session, guild.id)
    now = datetime.now(timezone.utc)
    await set_rls_context(session, SystemGuild(guild.id))
    case = IntakeCase(
        stream=IntakeStream.support,
        task_id=task.id,
        opened_at=now,
        last_seen_at=now,
        noted_at=now,
    )
    session.add(case)
    await session.flush()
    session.add(
        Evidence(
            case_task_id=task.id,
            origin_guild_id=guild.id,
            origin_id=uuid.uuid4(),
            storage_key="evidence-test.iev",
            size_bytes=1,
            content_type="text/plain",
            display_name="a.txt",
            sha256="0" * 64,
            wrapped_dek=b"sealed",
            kek_version=1,
        )
    )
    await session.commit()
    case_id, task_id = int(case.id), int(task.id)
    await set_rls_context(session, Unattributed())
    assert case_id != task_id
    migration = _load()

    async def named(column: str) -> int:
        result = await (await session.connection()).execute(
            text(f'SELECT {column} FROM "guild_{guild.id}".evidence')
        )
        return result.scalar_one()

    try:
        await session.run_sync(_step(migration, False))
        assert await named("case_id") == case_id

        await session.run_sync(_step(migration, True))
        assert await named("case_task_id") == task_id
    finally:
        await session.rollback()
