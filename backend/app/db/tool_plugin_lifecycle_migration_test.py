"""Migrations 20261118_0617 and 20261118_0618, down and up again.

0617 gives ``plugin_installs`` the stamp of a community's uninstall and the
guild floors their reads of a tool plug-in's state; 0618 widens a layout's
target for a tool plug-in's kinds. Run in one transaction rolled back at the
end, on a community the test builds.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.db.schema_provisioning import guild_schema_name
from app.testing import create_guild

_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step(migration: ModuleType, forward: bool):
    def apply(sync_session) -> None:
        with Operations.context(MigrationContext.configure(sync_session.connection())):
            (migration.upgrade if forward else migration.downgrade)()

    return apply


async def _state(session, schema: str) -> tuple:
    """The layout target's width, whether the install index has the stamp,
    and whether the guild floor reads an install's status."""
    return (
        await session.scalar(
            text(
                "SELECT character_maximum_length FROM information_schema.columns"
                " WHERE table_schema = :s AND table_name = 'tool_layouts'"
                " AND column_name = 'tool'"
            ),
            {"s": schema},
        ),
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
    guild = await create_guild(session)
    schema = guild_schema_name(guild.id)
    uninstalls = _load("20261118_0617_a_community_uninstalls_a_tool_plugin")
    layouts = _load("20261118_0618_a_layout_names_a_tool_plugins_kind")
    assert await _state(session, schema) == (64, 1, True)

    await session.run_sync(_step(layouts, forward=False))
    await session.run_sync(_step(uninstalls, forward=False))
    assert await _state(session, schema) == (32, 0, False)

    await session.run_sync(_step(uninstalls, forward=True))
    await session.run_sync(_step(layouts, forward=True))
    assert await _state(session, schema) == (64, 1, True)
    await session.rollback()
