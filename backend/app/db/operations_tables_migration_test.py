"""Migration 20261105_0579 leaves the operations tables in the operations
community alone.

Run on communities the test builds, in one transaction rolled back at the end:
every one given the operations tables, as each had them before the revision,
and one of the others holding a binding. The revision takes them from the one
that holds nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.core.intake import IntakeStream
from app.db import operations_schema
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.db.tenancy import OPERATIONS_TABLES
from app.models.tenant.intake import IntakeBinding
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
    make_operations_community,
)

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261105_0579_operations_tables_live_in_one_community.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _upgrade(migration: ModuleType):
    def apply(sync_session) -> None:
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            migration.upgrade()

    return apply


async def _tables(session, guild_id: int) -> set[str]:
    found = set()
    for table in OPERATIONS_TABLES:
        result = await (await session.connection()).execute(
            text("SELECT to_regclass(:t) IS NOT NULL"),
            {"t": f'"guild_{guild_id}".{table}'},
        )
        if result.scalar():
            found.add(table)
    return found


async def test_only_a_community_with_operations_rows_keeps_their_tables(
    session,
) -> None:
    user = await create_user(session)
    operations = await create_guild(session, creator=user)
    empty = await create_guild(session, creator=user)
    former = await create_guild(session, creator=user)
    initiative = await create_initiative(session, former, user)
    project = await create_project(session, initiative, user)
    await make_operations_community(session, operations.id)
    for guild in (empty, former):
        await operations_schema.provision_operations(guild.id)
    await set_rls_context(session, SystemGuild(former.id))
    session.add(IntakeBinding(stream=IntakeStream.support, project_id=project.id))
    await session.commit()
    await set_rls_context(session, Unattributed())

    try:
        await session.run_sync(_upgrade(_load()))
        assert await _tables(session, operations.id) == OPERATIONS_TABLES
        assert await _tables(session, former.id) == OPERATIONS_TABLES
        assert await _tables(session, empty.id) == set()
    finally:
        await session.rollback()
