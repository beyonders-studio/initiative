"""The tools a community's database rules are rendered from.

Every renderer that writes a community's rules (its row security, its gate
functions, its freeze and search triggers, its plug-in grants and its registry
CHECKs) reads a :class:`ToolSet` handed to it, rather than the ``Tool`` enum.
A record holds what those renderers read about one tool: its names, its
record (:class:`~app.core.tools.ToolSpec`), its tables as SQLAlchemy tables,
the kinds that live inside it and its permission keys.

:data:`BUILTIN_TOOLS` is the set every community has, in enum order: one
record per :data:`~app.core.tools.TOOL_SPECS` entry, its tables taken from the
model metadata.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property

from sqlalchemy import Table
from sqlmodel import SQLModel

import app.db.base  # noqa: F401  # every model on the metadata
from app.core.plugin_scopes import tool_resource
from app.core.tools import KINDS, Kind, Tool, ToolRefusals, ToolSpec


@dataclass(frozen=True, eq=False)
class ToolRecord(ToolRefusals):
    """One tool, as the renderers read it, and as the refusals about it name
    it."""

    #: Its kind, as a row names it (``resource_grants.resource_type``).
    kind: str
    #: The spelling every derived name uses (its table, its admin surface).
    plural: str
    spec: ToolSpec
    #: Its own table.
    table: Table
    #: The tables inside it whose rows are read and written as their parent in
    #: the tool is (``ToolSpec.item_tables``).
    items: tuple[Table, ...]
    #: The kinds that live inside it.
    children: tuple[Kind, ...]
    #: Its switch in each initiative, and the role key gating viewing it.
    view_permission: str
    #: The role key gating creating it.
    create_permission: str
    #: The resource its plug-in scopes name.
    scope: str
    #: The install whose tool this is, for a tool plug-in's: its switch and
    #: role rows are that install's (``initiative_rules.install_id``). None
    #: for a built-in tool.
    install_id: int | None = None

    @property
    def value(self) -> str:
        """Its kind, as a refusal names it."""
        return self.kind


@dataclass(frozen=True, eq=False)
class ToolSet:
    """The tools of one community, in the order the renderers list them."""

    records: tuple[ToolRecord, ...]
    #: What the community's installed tool plug-ins are
    #: (``app.db.plugin_tools.installed_digest``); None for the built-in
    #: tools alone.
    digest: str | None = None

    def __iter__(self) -> Iterator[ToolRecord]:
        return iter(self.records)

    @cached_property
    def by_kind(self) -> dict[str, ToolRecord]:
        return {record.kind: record for record in self.records}

    @cached_property
    def by_table(self) -> dict[str, ToolRecord]:
        """Each tool by the name of its own table."""
        return {record.table.name: record for record in self.records}

    @cached_property
    def _columns(self) -> dict[str, frozenset[str]]:
        return {
            table.name: frozenset(table.c.keys())
            for record in self.records
            for table in (record.table, *record.items)
        }

    @cached_property
    def installed_tables(self) -> tuple[Table, ...]:
        """The installed tools' tables, each tool's own before its items."""
        return tuple(
            table
            for record in self.installed
            for table in (record.table, *record.items)
        )

    @cached_property
    def tables(self) -> dict[str, Table]:
        """Every table of the community by name: the models', then the
        installed tools'."""
        return {
            **SQLModel.metadata.tables,
            **{table.name: table for table in self.installed_tables},
        }

    def tables_carrying(self, column: str) -> frozenset[str]:
        """Every tool's own table and item table that has ``column``: what a
        rule derived from a mixin reads of a tool built from no model."""
        return frozenset(
            table for table, columns in self._columns.items() if column in columns
        )

    @cached_property
    def installed(self) -> tuple[ToolRecord, ...]:
        """The tools an installed tool plug-in brings."""
        return tuple(record for record in self.records if record.install_id is not None)

    @cached_property
    def child_kinds(self) -> tuple[Kind, ...]:
        """Every kind inside a tool: the built-in ones in the order
        :data:`~app.core.tools.KINDS` declares them, then the rest."""
        order = {kind: i for i, kind in enumerate(KINDS)}
        return tuple(
            sorted(
                (kind for record in self.records for kind in record.children),
                key=lambda kind: order.get(kind.value, len(order)),
            )
        )

    @cached_property
    def content_kinds(self) -> tuple[str, ...]:
        """Every tool, then everything that lives inside one."""
        return tuple(r.kind for r in self.records) + tuple(
            kind.value for kind in self.child_kinds
        )

    @cached_property
    def kind_codes(self) -> dict[str, int]:
        """Every tool's kind and every kind inside one, and its code."""
        return {r.kind: r.spec.code for r in self.records} | {
            kind.value: kind.code for kind in self.child_kinds
        }

    @cached_property
    def comment_targets(self) -> tuple[str, ...]:
        """What a comment may be said on: the kinds inside a tool that take
        comments, then every tool."""
        return tuple(k.value for k in self.child_kinds if k.commentable) + tuple(
            r.kind for r in self.records
        )


def _builtin(tool: Tool) -> ToolRecord:
    tables = SQLModel.metadata.tables
    return ToolRecord(
        kind=tool.value,
        plural=tool.plural,
        spec=tool.spec,
        table=tables[tool.plural],
        items=tuple(tables[name] for name in tool.spec.item_tables),
        children=tuple(kind for kind in KINDS.values() if kind.parent is tool),
        view_permission=tool.view_permission,
        create_permission=tool.create_permission,
        scope=tool_resource(tool).value,
    )


#: The tools every community has.
BUILTIN_TOOLS = ToolSet(tuple(_builtin(tool) for tool in Tool))
