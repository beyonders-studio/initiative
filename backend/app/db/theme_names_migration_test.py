"""Migration 20261110_0605 moves accounts wearing a renamed color theme to its
new id, leaves every other theme alone, and its downgrade moves them back.

Loaded by path and run as ``gantt_layout_migration_test`` runs its revision."""

from __future__ import annotations

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.db.tool_layouts_migration_test import _load
from app.testing import create_user

_BEFORE = ("displacer", "strahd", "aboleth", "kobold", "orc")
_AFTER = ("catppuccin", "dracula", "monokai", "kobold", "orc")


async def test_renamed_themes_move_and_move_back(session) -> None:
    users = [await create_user(session, color_theme=theme) for theme in _BEFORE]
    migration = _load("20261110_0605_themes_take_their_own_names")

    async def run(step) -> tuple[str, ...]:
        def apply(sync_session) -> None:
            with Operations.context(
                MigrationContext.configure(sync_session.connection())
            ):
                step()

        await session.run_sync(apply)
        connection = await session.connection()
        rows = await connection.execute(
            text("SELECT id, color_theme FROM public.users WHERE id = ANY(:ids)"),
            {"ids": [user.id for user in users]},
        )
        themes = {row.id: row.color_theme for row in rows}
        return tuple(themes[user.id] for user in users)

    assert await run(migration.upgrade) == _AFTER
    assert await run(migration.downgrade) == _BEFORE
