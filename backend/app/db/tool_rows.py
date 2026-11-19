"""The rows of a tool plug-in's tables, which no model maps.

A built-in tool's rows are its models' instances. A tool plug-in's tables are
Core tables (``app.db.plugin_tools``), so the universal operations (archive,
trash, comments, sharing) read one of their rows as a :class:`ToolRow`: its
table, its columns, and what the request may do to the tool it is in, which
the schema's ``resource_actions`` answers in the SELECT that reads it, as it
does for a model's ``actions``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy import Integer, String, Table
from sqlalchemy.dialects.postgresql import ARRAY

from app.core.tool_set import ToolRecord, ToolSet
from app.db import gucs
from app.db.authorization import standing_arg
from app.db.initiative_rls import governing_walk, paths_for


@dataclass(frozen=True)
class ToolRow:
    """One row of a table no model maps, its columns read as attributes."""

    table: Table
    values: Mapping[str, Any]
    #: What the request may do to the tool the row is in.
    actions: frozenset[str] = frozenset()
    #: The columns of that tool's own row: the row's own, for a tool's row.
    tool: Mapping[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        try:
            return self.values[name]
        except KeyError:
            raise AttributeError(name) from None


def table_of(row: Any) -> Table:
    """The table ``row`` is kept in: a tool plug-in's row's own, or its
    model's."""
    return row.table if isinstance(row, ToolRow) else row.__table__


@dataclass(frozen=True)
class Located:
    """Where a kind of an installed tool keeps its rows."""

    kind: str
    #: The tool it is or lives in, whose sharing governs it.
    tool: ToolRecord
    table: Table
    #: ``(column, table)`` from a row of :attr:`table` up to the tool's own;
    #: none for the tool's own table.
    hops: tuple[tuple[str, str], ...]


def locate(tools: ToolSet, kind: str) -> Located | None:
    """The table ``kind`` keeps its rows in, where an installed tool of
    ``tools`` has it: the tool's own, or one of its items'."""
    for tool in tools.installed:
        tables = {tool.kind: tool.table.name} | {
            child.value: child.table for child in tool.children
        }
        if kind in tables:
            walk = governing_walk(tables[kind], paths_for(tools))
            return Located(
                kind, tool, tools.tables[tables[kind]], walk[1] if walk else ()
            )
    return None


def _actions(kind: str, tool: sa.FromClause) -> sa.ColumnElement[Any]:
    """What the request may do to a row of ``tool``, the kind's own table."""
    return sa.func.resource_actions(
        kind,
        tool.c.id,
        sa.literal_column(gucs.USER_ID.sql, Integer),
        tool.c.initiative_id,
        tool.c.archived_at,
        tool.c.deleted_at,
        standing_arg(),
        type_=ARRAY(String),
    )


def select_rows(located: Located, tools: ToolSet) -> sa.Select[Any]:
    """The rows of ``located``'s table, each with what the request may do to
    the tool it is in and that tool's own row."""
    table = located.table
    joined: sa.FromClause = table
    here: sa.FromClause = table
    for i, (column, parent) in enumerate(located.hops):
        up = tools.tables[parent].alias(f"tool_hop_{i}")
        joined = joined.join(up, up.c.id == here.c[column])
        here = up
    tool = [] if here is table else [c.label(f"_tool_{c.name}") for c in here.c]
    return sa.select(
        table, *tool, _actions(located.tool.kind, here).label("_actions")
    ).select_from(joined)


def row_of(table: Table, found: Any) -> ToolRow:
    """A :class:`ToolRow` from a row :func:`select_rows` read."""
    mapping = found._mapping
    values = {column.name: mapping[column] for column in table.columns}
    tool = {
        key.removeprefix("_tool_"): value
        for key, value in mapping.items()
        if isinstance(key, str) and key.startswith("_tool_")
    }
    return ToolRow(table, values, frozenset(mapping["_actions"] or ()), tool or values)


async def load_row(
    session: Any,
    located: Located,
    tools: ToolSet,
    row_id: int,
    *,
    for_update: bool = False,
) -> ToolRow | None:
    """One row of ``located``'s table, trashed or not, or None where the
    request does not read it."""
    statement = select_rows(located, tools).where(located.table.c.id == row_id)
    if for_update:
        statement = statement.with_for_update(of=located.table)
    found = (await session.exec(statement)).first()
    return None if found is None else row_of(located.table, found)
