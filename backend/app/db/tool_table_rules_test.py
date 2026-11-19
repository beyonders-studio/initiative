"""A tool plug-in's table carries what a built-in tool's carries: the CHECKs
and triggers ``tool_table_rules`` renders for every tool table are the ones
each built-in tool's table has from its migrations."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tool_set import BUILTIN_TOOLS
from app.db.guild_ddl import tool_table_rules

pytestmark = pytest.mark.always

_RULES = (
    "SELECT conname::text, pg_get_constraintdef(oid) FROM pg_constraint"
    " WHERE conrelid = to_regclass(:t) AND contype = 'c'"
    " AND conname::text ~ '_(created|deleted)_by(_kind)?$'"
)
_TRIGGERS = (
    "SELECT tgname::text, pg_get_triggerdef(oid) FROM pg_trigger"
    " WHERE tgrelid = to_regclass(:t) AND tgfoid IN"
    " ('public.fn_set_author'::regproc,"
    " 'public.fn_install_owns_what_it_creates'::regproc)"
)


async def _read(session: AsyncSession, schema: str, table: str) -> set[tuple]:
    found: set[tuple] = set()
    for query in (_RULES, _TRIGGERS):
        rows = await session.exec(sa.text(query), params={"t": f"{schema}.{table}"})
        found |= {
            (name, definition.replace(f"{schema}.", "")) for name, definition in rows
        }
    return found


async def test_every_built_in_tool_table_carries_what_the_render_gives(
    session: AsyncSession,
):
    """Each built-in tool's own table and item tables, made bare beside the
    template and given the render, read back as the template's do."""
    await session.exec(sa.text("CREATE SCHEMA tool_rules_scratch"))
    await session.exec(sa.text("SET LOCAL search_path = tool_rules_scratch, public"))
    for tool in BUILTIN_TOOLS:
        for table in (tool.table, *tool.items):
            name = table.name
            await session.exec(
                sa.text(f"CREATE TABLE {name} (LIKE guild_template.{name})")
            )
            checks, triggers = tool_table_rules(
                name, table.c.keys(), tool.kind if table is tool.table else None
            )
            for check, expression in checks.items():
                await session.exec(
                    sa.text(
                        f"ALTER TABLE {name} ADD CONSTRAINT {check} CHECK ({expression})"
                    )
                )
            for trigger in triggers:
                await session.exec(sa.text(trigger))
            rendered = await _read(session, "tool_rules_scratch", name)
            assert rendered == await _read(session, "guild_template", name), name
    await session.rollback()
