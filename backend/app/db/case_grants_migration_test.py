"""Migration 20261031_0577 moves the link from an access grant to its case into
the operations community.

Run on guilds the test builds, in one transaction rolled back at the end:
grants linked where the links live now, the revision stepped down so each
grant names its case in ``public.access_grants`` as an older release kept it,
and up again. Each link comes back as it was; a grant whose case is no task in
the operations community does not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing import (
    create_access_grant,
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
    / "20261031_0577_a_grants_case_is_linked_where_the_case_is.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(_MIGRATION.stem, _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


def _step(migration: ModuleType, forward: bool):
    def apply(sync_session) -> None:
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            (migration.upgrade if forward else migration.downgrade)()

    return apply


async def test_the_links_move_into_the_operations_community(session) -> None:
    user = await create_user(session)
    operations = await create_guild(session, creator=user)
    target = await create_guild(session, creator=user)
    initiative = await create_initiative(session, operations, user)
    project = await create_project(session, initiative, user)
    case_id = (await create_task(session, project)).id
    await make_operations_community(session, operations.id)

    for purpose, level in (("content", "read"), ("settings", "admin")):
        await create_access_grant(
            session,
            user=user,
            guild=target,
            purpose=purpose,
            access_level=level,
            case_task_id=case_id,
        )
    caseless = (await create_access_grant(session, user=user, guild=target)).id
    held = (
        f'SELECT grant_id, task_id FROM "guild_{operations.id}".case_grants ORDER BY 1'
    )
    in_public = (
        "SELECT id, case_task_id FROM public.access_grants"
        " WHERE case_task_id IS NOT NULL ORDER BY 1"
    )
    migration = _load()

    try:
        links = await _rows(session, held)
        assert len(links) == 2

        await session.run_sync(_step(migration, False))
        assert await _rows(session, in_public) == links
        for guild in (operations, target):
            assert await _rows(
                session, f"SELECT to_regclass('guild_{guild.id}.case_grants')"
            ) == [(None,)]

        # A grant whose case has since gone.
        await (await session.connection()).execute(
            text("UPDATE public.access_grants SET case_task_id = :gone WHERE id = :g"),
            {"gone": case_id + 1_000, "g": caseless},
        )

        await session.run_sync(_step(migration, True))
        assert await _rows(session, held) == links
        assert await _rows(
            session, f'SELECT count(*) FROM "guild_{target.id}".case_grants'
        ) == [(0,)]
        assert await _rows(
            session,
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = 'access_grants'"
            " AND column_name = 'case_task_id'",
        ) == [(0,)]
    finally:
        await session.rollback()
