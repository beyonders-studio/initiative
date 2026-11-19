"""What is inside what, for the lifecycles that take a whole subtree with them.

Trashing, restoring, purging and archiving all act on a row *and everything
filed under it*. The tree they walk is not written down anywhere: it is read off
the foreign keys between the soft-deletable tables, so a table that joins the
trash can with a key to its parent joins the cascade in the same change, and the
four lifecycles cannot disagree about it. A comment names what it is said on as
a pair rather than a key, so it is filed under every kind that takes comments
(``COMMENT_TARGETS``).

A key that lets go on delete (``SET NULL``) is a pointer rather than ownership —
a collection's cover file, a wiki's home page — so it is not an edge: the thing
it points at is filed under the same parent already.

The walk goes a level at a time, one query per edge per level rather than one
per row, and each level is written with one statement per table. Callers pick
the direction: a stamp goes deepest-first, a restore shallowest-first, because a
trashed or archived row freezes everything under it at the database (see
``app.db.frozen``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

from sqlalchemy import Table, and_, delete, select, update
from sqlalchemy.sql import FromClause
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tool_set import BUILTIN_TOOLS, ToolSet
from app.core.tools import TRASHABLE_EXTRAS, plural_of
from app.db.base import MODELS_BY_TABLE
from app.db.query import ids_in
from app.db.session import routed_tools
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tool_rows import table_of


@dataclass(frozen=True)
class Edge:
    """One way a row is filed under another: a foreign key on ``table``, or,
    for a comment, the ``(subject_type, subject_id)`` pair it names its subject
    by, where ``kind`` is the parent's kind and ``column`` the id."""

    #: The table at the other end: the child, read downwards; the parent,
    #: read upwards.
    table: Table
    column: str
    kind: str | None = None

    def under(self, child: FromClause, parent_ids: Sequence[int]) -> Any:
        """``child`` rows filed under any of these parents."""
        tie = ids_in(child.c[self.column], parent_ids)
        return (
            tie if self.kind is None else and_(child.c.subject_type == self.kind, tie)
        )

    def ties(self, child: FromClause, parent: FromClause) -> Any:
        """``child`` filed under ``parent``, as a join condition."""
        tie = parent.c.id == child.c[self.column]
        return (
            tie if self.kind is None else and_(child.c.subject_type == self.kind, tie)
        )


#: parent table -> [edge to a child]
Tree = Mapping[Table, Sequence[Edge]]

#: table -> ids, for one level of a walk.
Level = dict[Table, list[int]]

#: A subtree deeper than this is a cycle in the data, not a tree.
_MAX_DEPTH = 256


def binned_tables(tools: ToolSet) -> tuple[Table, ...]:
    """Every table with the trash in a community with ``tools``: the models'
    and the installed tools' that carry its column."""
    return (
        *(SQLModel.metadata.tables[name] for name in SOFT_DELETE_TABLES),
        *(table for table in tools.installed_tables if "deleted_at" in table.c),
    )


def trash_kinds(tools: ToolSet) -> dict[str, Table]:
    """What the trash calls the rows of each table with the trash, in a
    community with ``tools``: the kind it keeps, or what else the trash holds
    (a comment, an initiative)."""
    from app.db.initiative_rls import content_kind_tables

    named = content_kind_tables(tools) | {e: plural_of(e) for e in TRASHABLE_EXTRAS}
    return {
        kind: tools.tables[name]
        for kind, name in named.items()
        if "deleted_at" in tools.tables[name].c
    }


@cache
def cascade_children(tools: ToolSet) -> dict[Table, list[Edge]]:
    """parent table -> [edge to a child]: what a trashed row takes with it,
    in a community with ``tools``."""
    from app.db.initiative_rls import comment_parents

    binned = binned_tables(tools)
    tree: dict[Table, list[Edge]] = {}
    for child in binned:
        for column in child.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table
                if parent not in binned or (fk.ondelete or "").upper() == "SET NULL":
                    continue
                tree.setdefault(parent, []).append(Edge(child, column.name))
    # A comment names what it is said on by kind, not by a key, so it is filed
    # under every kind that takes comments.
    comments = tools.tables["comments"]
    parents = comment_parents(tools)
    for kind in tools.comment_targets:
        parent = tools.tables[parents[kind].table]
        tree.setdefault(parent, []).append(Edge(comments, "subject_id", kind))
    return tree


@cache
def cascade_parents(tools: ToolSet) -> dict[Table, list[Edge]]:
    """child table -> [edge to a parent]: the same edges read upwards."""
    parents: dict[Table, list[Edge]] = {}
    for parent, children in cascade_children(tools).items():
        for edge in children:
            parents.setdefault(edge.table, []).append(
                Edge(parent, edge.column, edge.kind)
            )
    return parents


#: The built-in tools' tree, downwards and upwards.
CASCADE_CHILDREN: dict[Table, list[Edge]] = cascade_children(BUILTIN_TOOLS)
CASCADE_PARENTS: dict[Table, list[Edge]] = cascade_parents(BUILTIN_TOOLS)


def parents_first(
    tables: Iterable[Table], tools: ToolSet = BUILTIN_TOOLS
) -> tuple[Table, ...]:
    """``tables`` ordered so every parent comes before its children.

    A table's edge to itself (a reply under a comment, a page under a page) is
    no constraint on the order. Ties keep the order they were given in.
    """
    upwards = cascade_parents(tools)
    pending = list(tables)
    placed: list[Table] = []
    while pending:
        for table in pending:
            parents = {
                edge.table for edge in upwards.get(table, ()) if edge.table is not table
            }
            if not parents & set(pending):
                placed.append(table)
                pending.remove(table)
                break
        else:  # pragma: no cover — the tables' keys would have to form a loop
            raise RuntimeError(f"cascade tree has a cycle among {pending}")
    return tuple(placed)


def group_by_table(rows: Iterable[Any]) -> Level:
    """Rows' ids by the table each is kept in: a model's instance's, or a
    tool plug-in's row's (``app.db.tool_rows``)."""
    level: Level = {}
    for row in rows:
        level.setdefault(table_of(row), []).append(row.id)
    return level


def _keep_deepest(levels: list[Level]) -> list[Level]:
    """Drop every row from all but the deepest level it was reached at.

    A reply is filed under its comment and also names the thing the thread is
    on, so it is reached twice. Its deepest level is the one that is below all
    of its parents, which is the one every direction of write needs.
    """
    seen: set[tuple[Table, int]] = set()
    kept: list[Level] = []
    for level in reversed(levels):
        narrowed: Level = {}
        for table, ids in level.items():
            fresh = [i for i in ids if (table, i) not in seen]
            seen.update((table, i) for i in fresh)
            if fresh:
                narrowed[table] = fresh
        kept.append(narrowed)
    kept.reverse()
    return [level for level in kept if level]


async def subtree_levels(
    session: AsyncSession,
    roots: Iterable[Any],
    *,
    tree: Tree | None = None,
    where: Callable[[Table], Any] | None = None,
) -> list[Level]:
    """The roots and everything under them, grouped by depth — roots first.

    ``tree`` is the community's (:func:`cascade_children`), the one the
    session is routed into when not given. ``where(table)`` narrows which
    children are followed (the ones still live, the ones stamped by one
    particular trashing, …); without it every child is, in the bin or not.
    Each row appears once, at the deepest level it sits.
    """
    if tree is None:
        tree = cascade_children(routed_tools(session))
    levels: list[Level] = []
    frontier = group_by_table(roots)
    while frontier:
        if len(levels) >= _MAX_DEPTH:
            raise RuntimeError("cascade tree is deeper than any real one could be")
        levels.append(frontier)
        found: dict[Table, dict[int, None]] = {}
        for parent, parent_ids in frontier.items():
            for edge in tree.get(parent, ()):
                child = edge.table
                stmt = (
                    select(child.c.id)
                    .where(edge.under(child, parent_ids))
                    .execution_options(include_deleted=True)
                )
                if where is not None:
                    stmt = stmt.where(where(child))
                for child_id in (await session.exec(stmt)).scalars().all():
                    found.setdefault(child, {})[child_id] = None
        frontier = {table: list(ids) for table, ids in found.items()}
    return _keep_deepest(levels)


def _synced(statement: Any, table: Table) -> Any:
    """``statement`` on ``table``, naming its model where it has one, so the
    session keeps the rows of it that it holds in step. A table no model maps
    has no rows in the session."""
    model = MODELS_BY_TABLE.get(table.name)
    if model is None:
        return statement(table)
    return statement(model).execution_options(synchronize_session="fetch")


async def set_columns(
    session: AsyncSession, table: Table, ids: Sequence[int], values: dict[str, Any]
) -> None:
    """One UPDATE for every row of ``table`` named, kept in step with any of
    them the session already holds."""
    await session.exec(
        _synced(update, table).where(ids_in(table.c.id, ids)).values(**values)
    )


async def delete_rows(session: AsyncSession, table: Table, ids: Sequence[int]) -> None:
    """Delete these rows of ``table``. What hangs off them outside the trash
    goes with them at the database (``ON DELETE CASCADE``), in the same
    statement."""
    await session.exec(_synced(delete, table).where(ids_in(table.c.id, ids)))
