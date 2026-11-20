"""Migration 20261118_0613 moves each tool's switch from its column on
``initiatives`` to an ``initiative_rules`` row. Loaded by path and run on one
guild the test builds: down, which puts the columns back from the rows, then
up again, which writes the rows from the columns and drops them. The later
revisions that reshape what it writes are taken off around it."""

from __future__ import annotations

from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from alembic import op
from app.core.tools import Tool
from app.testing import create_guild, create_initiative, create_user
from app.testing.later_revisions import load_revision, step_newest


async def _rows(session, sql: str, **params: Any) -> list[tuple]:
    result = await (await session.connection()).execute(text(sql), params)
    return [tuple(row) for row in result.all()]


def _runner(schema: str, forward: bool):
    migration = load_revision("20261118_0613_each_tools_switch_is_a_rule")

    def apply(sync_session) -> None:
        bind = sync_session.connection()
        bind.execute(
            text("SELECT set_config('search_path', :sp, true)"),
            {"sp": f"{schema}, public"},
        )
        with Operations.context(MigrationContext.configure(bind)):
            if forward:
                migration._upgrade()
                step_newest(forward=True, after=migration.revision)
            else:
                step_newest(forward=False, after=migration.revision)
                # Today's admits no key of a tool that has left, such as
                # Counters' switch, which this revision writes; a start
                # renders it again.
                op.drop_constraint(
                    "ck_initiative_rules_key", "initiative_rules", if_exists=True
                )
                migration._downgrade()

    return apply


async def _switch_rows(session, s: str, initiative_id: int) -> dict[str, bool]:
    return dict(
        await _rows(
            session,
            f"SELECT key, enabled FROM {s}.initiative_rules "
            "WHERE initiative_id = :i AND initiative_role_id IS NULL "
            "AND install_id IS NULL",
            i=initiative_id,
        )
    )


async def test_each_switch_column_becomes_its_row_and_back(session) -> None:
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    schema = f"guild_{guild.id}"
    s = f'"{schema}"'
    initiative = await create_initiative(
        session, guild, owner, tools={Tool.post: False, Tool.wiki: False}
    )
    other = await create_initiative(session, guild, owner)
    await session.commit()
    columns = [tool.view_permission for tool in Tool]

    # Down: each column takes its row's value, and the rows go.
    await session.run_sync(_runner(schema, forward=False))
    await session.commit()
    (row,) = await _rows(
        session,
        f"SELECT {', '.join(columns)} FROM {s}.initiatives WHERE id = :i",
        i=initiative.id,
    )
    assert dict(zip(columns, row, strict=True)) == {
        key: key not in ("posts_enabled", "wikis_enabled") for key in columns
    }
    assert await _switch_rows(session, s, initiative.id) == {}

    # As an older release left it: one initiative with calendars off and
    # projects off, the other with everything on.
    await (await session.connection()).execute(
        text(
            f"UPDATE {s}.initiatives SET calendars_enabled = false, "
            "projects_enabled = false WHERE id = :i"
        ),
        {"i": other.id},
    )
    await session.commit()

    # Up: a row per tool from the column, on or off, and the columns go.
    await session.run_sync(_runner(schema, forward=True))
    await session.commit()
    assert await _switch_rows(session, s, initiative.id) == {
        key: key not in ("posts_enabled", "wikis_enabled") for key in columns
    }
    assert await _switch_rows(session, s, other.id) == {
        key: key not in ("calendars_enabled", "projects_enabled") for key in columns
    }
    assert (
        await _rows(
            session,
            "SELECT attname FROM pg_attribute WHERE attrelid = CAST(:t AS regclass) "
            "AND attname LIKE '%\\_enabled' AND NOT attisdropped",
            t=f"{schema}.initiatives",
        )
        == []
    )
