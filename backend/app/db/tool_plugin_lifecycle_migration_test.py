"""Migration 20261118_0617, down and up again: ``plugin_installs`` takes the
stamp of a community's uninstall and the guild floors their reads of a tool
plug-in's state. Run as a revision runs, on the provisioning login that owns
the table, in one transaction rolled back at the end.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.testing.later_revisions import load_revision
from app.testing.tool_plugins import provisioning_login


class _RolledBack(Exception):
    """Leaves the revision's transaction rolled back."""


def _step(migration: ModuleType, forward: bool):
    def apply(connection: Any) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            (migration.upgrade if forward else migration.downgrade)()

    return apply


async def _state(conn: AsyncConnection) -> tuple:
    """Whether the install index has the stamp, and whether the guild floor
    reads an install's status."""
    return (
        await conn.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = 'plugin_installs'"
                " AND column_name = 'uninstalled_at'"
            )
        ),
        await conn.scalar(
            text(
                "SELECT has_column_privilege('app_guild_base_ro',"
                " 'public.plugin_installs', 'status', 'SELECT')"
            )
        ),
    )


async def test_down_and_up_again() -> None:
    uninstalls = load_revision("20261118_0617_a_community_uninstalls_a_tool_plugin")
    with pytest.raises(_RolledBack):
        async with provisioning_login() as conn:
            assert await _state(conn) == (1, True)

            await conn.run_sync(_step(uninstalls, forward=False))
            assert await _state(conn) == (0, False)

            await conn.run_sync(_step(uninstalls, forward=True))
            assert await _state(conn) == (1, True)
            raise _RolledBack
