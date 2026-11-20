"""Migration 20261118_0617, down and up again: ``plugin_installs`` takes the
stamp of a community's uninstall and the guild floors their reads of a tool
plug-in's state. Run in one transaction rolled back at the end.
"""

from __future__ import annotations

from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.testing.later_revisions import load_revision


def _step(migration: ModuleType, forward: bool):
    def apply(sync_session) -> None:
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            (migration.upgrade if forward else migration.downgrade)()

    return apply


async def _state(session) -> tuple:
    """Whether the install index has the stamp, and whether the guild floor
    reads an install's status."""
    return (
        await session.scalar(
            text(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_schema = 'public' AND table_name = 'plugin_installs'"
                " AND column_name = 'uninstalled_at'"
            )
        ),
        await session.scalar(
            text(
                "SELECT has_column_privilege('app_guild_base_ro',"
                " 'public.plugin_installs', 'status', 'SELECT')"
            )
        ),
    )


async def test_down_and_up_again(session) -> None:
    uninstalls = load_revision("20261118_0617_a_community_uninstalls_a_tool_plugin")
    assert await _state(session) == (1, True)

    await session.run_sync(_step(uninstalls, forward=False))
    assert await _state(session) == (0, False)

    await session.run_sync(_step(uninstalls, forward=True))
    assert await _state(session) == (1, True)
    await session.rollback()
