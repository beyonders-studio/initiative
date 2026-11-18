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
from typing import Any

from sqlalchemy import and_, delete, update
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import COMMENT_TARGETS, KINDS
from app.db.base import MODELS_BY_TABLE
from app.db.query import ids_in
from app.db.soft_delete_filter import SOFT_DELETE_MODELS, select_including_deleted
from app.models.tenant.comment import Comment


@dataclass(frozen=True)
class Edge:
    """One way a row is filed under another: a foreign key on ``model``, or,
    for a comment, the ``(subject_type, subject_id)`` pair it names its subject
    by, where ``kind`` is the parent's kind and ``column`` the id."""

    #: The model at the other end: the child, read downwards; the parent, read
    #: upwards.
    model: type
    column: str
    kind: str | None = None

    def under(self, child: Any, parent_ids: Sequence[int]) -> Any:
        """``child`` rows filed under any of these parents."""
        tie = ids_in(getattr(child, self.column), parent_ids)
        return tie if self.kind is None else and_(child.subject_type == self.kind, tie)

    def ties(self, child: Any, parent: Any) -> Any:
        """``child`` filed under ``parent``, as a join condition."""
        tie = parent.id == getattr(child, self.column)
        return tie if self.kind is None else and_(child.subject_type == self.kind, tie)


#: parent model -> [edge to a child]
Tree = Mapping[type, Sequence[Edge]]

#: model -> ids, for one level of a walk.
Level = dict[type, list[int]]

#: A subtree deeper than this is a cycle in the data, not a tree.
_MAX_DEPTH = 256


def _derive_children() -> dict[type, list[Edge]]:
    tree: dict[type, list[Edge]] = {}
    for child in SOFT_DELETE_MODELS:
        for column in child.__table__.columns:
            for fk in column.foreign_keys:
                parent = MODELS_BY_TABLE.get(fk.column.table.name)
                if (
                    parent not in SOFT_DELETE_MODELS
                    or (fk.ondelete or "").upper() == "SET NULL"
                ):
                    continue
                tree.setdefault(parent, []).append(Edge(child, column.name))
    # A comment names what it is said on by kind, not by a key, so it is filed
    # under every kind that takes comments.
    for kind in COMMENT_TARGETS:
        parent = MODELS_BY_TABLE[KINDS[kind].table]
        tree.setdefault(parent, []).append(Edge(Comment, "subject_id", kind))
    return tree


#: parent model -> [edge to a child]: what a trashed row takes with it.
CASCADE_CHILDREN: dict[type, list[Edge]] = _derive_children()

#: child model -> [edge to a parent]: the same edges read upwards.
CASCADE_PARENTS: dict[type, list[Edge]] = {}
for _parent, _children in CASCADE_CHILDREN.items():
    for _edge in _children:
        CASCADE_PARENTS.setdefault(_edge.model, []).append(
            Edge(_parent, _edge.column, _edge.kind)
        )


def parents_first(models: Iterable[type]) -> tuple[type, ...]:
    """``models`` ordered so every parent comes before its children.

    A table's edge to itself (a reply under a comment, a page under a page) is
    no constraint on the order. Ties keep the order they were given in.
    """
    pending = list(models)
    placed: list[type] = []
    while pending:
        for model in pending:
            parents = {
                edge.model
                for edge in CASCADE_PARENTS.get(model, ())
                if edge.model is not model
            }
            if not parents & set(pending):
                placed.append(model)
                pending.remove(model)
                break
        else:  # pragma: no cover — the tables' keys would have to form a loop
            raise RuntimeError(f"cascade tree has a cycle among {pending}")
    return tuple(placed)


def group_by_model(rows: Iterable[SQLModel]) -> Level:
    level: Level = {}
    for row in rows:
        level.setdefault(type(row), []).append(row.id)  # type: ignore[attr-defined]
    return level


def _keep_deepest(levels: list[Level]) -> list[Level]:
    """Drop every row from all but the deepest level it was reached at.

    A reply is filed under its comment and also names the thing the thread is
    on, so it is reached twice. Its deepest level is the one that is below all
    of its parents, which is the one every direction of write needs.
    """
    seen: set[tuple[type, int]] = set()
    kept: list[Level] = []
    for level in reversed(levels):
        narrowed: Level = {}
        for model, ids in level.items():
            fresh = [i for i in ids if (model, i) not in seen]
            seen.update((model, i) for i in fresh)
            if fresh:
                narrowed[model] = fresh
        kept.append(narrowed)
    kept.reverse()
    return [level for level in kept if level]


async def subtree_levels(
    session: AsyncSession,
    roots: Iterable[SQLModel],
    *,
    tree: Tree = CASCADE_CHILDREN,
    where: Callable[[type], Any] | None = None,
) -> list[Level]:
    """The roots and everything under them, grouped by depth — roots first.

    ``where(model)`` narrows which children are followed (the ones still live,
    the ones stamped by one particular trashing, …); without it every child is,
    in the bin or not. Each row appears once, at the deepest level it sits.
    """
    levels: list[Level] = []
    frontier = group_by_model(roots)
    while frontier:
        if len(levels) >= _MAX_DEPTH:
            raise RuntimeError("cascade tree is deeper than any real one could be")
        levels.append(frontier)
        found: dict[type, dict[int, None]] = {}
        for parent_model, parent_ids in frontier.items():
            for edge in tree.get(parent_model, ()):
                child_model = edge.model
                stmt = select_including_deleted(child_model.id).where(  # type: ignore[attr-defined]
                    edge.under(child_model, parent_ids)
                )
                if where is not None:
                    stmt = stmt.where(where(child_model))
                for child_id in (await session.exec(stmt)).all():
                    found.setdefault(child_model, {})[child_id] = None
        frontier = {model: list(ids) for model, ids in found.items()}
    return _keep_deepest(levels)


async def set_columns(
    session: AsyncSession, model: type, ids: Sequence[int], values: dict[str, Any]
) -> None:
    """One UPDATE for every row of ``model`` named, kept in step with any of
    them the session already holds."""
    await session.exec(
        update(model)  # type: ignore[call-overload]
        .where(ids_in(model.id, ids))  # type: ignore[attr-defined]
        .values(**values)
        .execution_options(synchronize_session="fetch")
    )


async def delete_rows(session: AsyncSession, model: type, ids: Sequence[int]) -> None:
    """Delete these rows of ``model``. What hangs off them outside the trash
    goes with them at the database (``ON DELETE CASCADE``), in the same
    statement."""
    await session.exec(
        delete(model)  # type: ignore[call-overload]
        .where(ids_in(model.id, ids))  # type: ignore[attr-defined]
        .execution_options(synchronize_session="fetch")
    )
