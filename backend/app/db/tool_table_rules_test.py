"""The CHECKs and triggers ``tool_table_rules`` renders for a tool plug-in's
tables are the ones every built-in tool table has from its migrations."""

import pytest
import sqlalchemy as sa
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tool_set import BUILTIN_TOOLS
from app.db.guild_ddl import tool_table_rules

pytestmark = pytest.mark.always

#: A table's author CHECKs and triggers, by name.
_RULES = """
SELECT conname::text, pg_get_constraintdef(oid) FROM pg_constraint
 WHERE conrelid = to_regclass(:t) AND conname::text ~ '_(created|deleted)_by(_kind)?$'
UNION SELECT tgname::text, pg_get_triggerdef(oid) FROM pg_trigger
 WHERE tgrelid = to_regclass(:t) AND tgfoid IN ('public.fn_set_author'::regproc,
   'public.fn_install_owns_what_it_creates'::regproc)"""


async def _rules(session: AsyncSession, schema: str, table: str) -> set[tuple]:
    rows = await session.exec(sa.text(_RULES), params={"t": f"{schema}.{table}"})
    return {(name, rule.replace(f"{schema}.", "")) for name, rule in rows}


async def test_every_built_in_tool_table_carries_what_the_render_gives(
    session: AsyncSession,
):
    """Each built-in tool table, made bare beside the template and given the
    render, reads back as the template's does."""
    await session.exec(sa.text("CREATE SCHEMA scratch"))
    await session.exec(sa.text("SET LOCAL search_path = scratch, public"))
    for tool in BUILTIN_TOOLS:
        for table in (tool.table, *tool.items):
            name, own = table.name, tool.kind if table is tool.table else None
            await session.exec(
                sa.text(f"CREATE TABLE {name} (LIKE guild_template.{name})")
            )
            checks, triggers = tool_table_rules(name, table.c.keys(), own)
            for check, expression in checks.items():
                await session.exec(
                    sa.text(
                        f"ALTER TABLE {name} ADD CONSTRAINT {check} CHECK ({expression})"
                    )
                )
            for trigger in triggers:
                await session.exec(sa.text(trigger))
            rendered = await _rules(session, "scratch", name)
            assert rendered == await _rules(session, "guild_template", name), name
    await session.rollback()
