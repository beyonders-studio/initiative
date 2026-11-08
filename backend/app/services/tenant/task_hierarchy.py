"""A task's place in a tree of tasks: the task it is part of, and its parts.

A subtask is a whole task with a live ``part_of`` edge to another task
(:mod:`app.core.relationships`). Nothing else stores the tree: this module reads
the edges as one — each task's parent, and how far its parts have got — and
writes a task's parent as the edge.

A task can be part of several things, since an edge records whatever it is
given. As a tree it has one parent: its earliest live ``part_of`` edge to a
task, which is the one the project's Gantt nests it under.

Everything here reads through the routed session, so a parent or a part the
reader cannot open is not there: the relationships policy clears both ends.
"""

from __future__ import annotations

import re

from typing import Any, Iterable, Optional

from fastapi import HTTPException, status
from sqlalchemy import literal, null, text, union_all
from sqlalchemy.orm import aliased
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import TaskMessages
from app.core.relationships import RelationshipType, node_id
from app.core.search import SearchEntityType
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task
from app.schemas.base import MAX_TITLE_LENGTH, RESERVED_SIGILS
from app.schemas.tenant.task import ChecklistProgress, TaskParentSummary
from app.services.tenant import relationships as relationships_service

_TASK = SearchEntityType.task.value


def _part_of_edges():
    """The live ``part_of`` edges from one task to another."""
    edge = EntityRelationship
    return (
        edge.source_type == _TASK,
        edge.target_type == _TASK,
        edge.relationship_type == RelationshipType.part_of.value,
        edge.removed_at.is_(None),  # type: ignore[union-attr]
    )


async def _parents(
    session: AsyncSession, ids: Iterable[int]
) -> dict[int, tuple[int, str, float]]:
    """Each of ``ids``' parent as ``(id, title, position)``, where it has one."""
    wanted = tuple(dict.fromkeys(ids))
    if not wanted:
        return {}
    edge = EntityRelationship
    rows = await session.exec(
        select(edge.source_id, Task.id, Task.title, Task.position)
        .join(Task, Task.id == edge.target_id)
        .where(
            *_part_of_edges(),
            edge.source_id.in_(wanted),  # type: ignore[attr-defined]
            Task.deleted_at.is_(None),  # type: ignore[union-attr]
        )
        .order_by(edge.source_id, edge.id)
    )
    parents: dict[int, tuple[int, str, float]] = {}
    for task_id, parent_id, title, position in rows.all():
        parents.setdefault(task_id, (parent_id, title, position))
    return parents


async def annotate(session: AsyncSession, tasks: list[Task]) -> None:
    """Set ``parent`` and ``subtask_progress`` on each of ``tasks``.

    One statement for both: the edges up from the tasks, to their parents, and
    the edges down to them, from their parts. An archived part is finished with
    rather than work still to do, so it counts towards neither number.
    """
    ids = tuple(task.id for task in tasks if task.id is not None)
    if not ids:
        return
    edge = EntityRelationship
    up = (
        select(
            edge.source_id.label("task_id"),
            literal(True).label("up"),
            edge.id.label("edge_id"),
            Task.id.label("other_id"),
            Task.title.label("title"),
            literal(False).label("done"),
        )
        .join(Task, Task.id == edge.target_id)
        .where(
            *_part_of_edges(),
            edge.source_id.in_(ids),  # type: ignore[attr-defined]
            Task.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    )
    down = (
        select(
            edge.target_id,
            literal(False),
            edge.id,
            Task.id,
            null(),
            Task.completed_at.isnot(None),  # type: ignore[union-attr]
        )
        .join(Task, Task.id == edge.source_id)
        .where(
            *_part_of_edges(),
            edge.target_id.in_(ids),  # type: ignore[attr-defined]
            Task.archived_at.is_(None),  # type: ignore[union-attr]
            Task.deleted_at.is_(None),  # type: ignore[union-attr]
        )
    )
    statement = union_all(up, down).subquery()
    rows = await session.exec(
        select(*statement.c).order_by(statement.c.task_id, statement.c.edge_id)
    )
    parents: dict[int, TaskParentSummary] = {}
    parts: dict[int, dict[int, bool]] = {}
    for task_id, is_up, _edge_id, other_id, title, done in rows.all():
        if is_up:
            parents.setdefault(task_id, TaskParentSummary(id=other_id, title=title))
        else:
            parts.setdefault(task_id, {})[other_id] = bool(done)
    for task in tasks:
        held = parts.get(task.id or 0)
        object.__setattr__(task, "parent", parents.get(task.id or 0))
        object.__setattr__(
            task,
            "subtask_progress",
            ChecklistProgress(completed=sum(held.values()), total=len(held))
            if held
            else None,
        )


#: Every node a node's parts reach, at any depth. ``UNION`` rather than
#: ``UNION ALL``, so a node already reached is not walked again and a loop the
#: edges record ends the walk; no depth bound, so a long chain is walked whole.
_PARTS_REACH = text(
    """
    WITH RECURSIVE reached(node) AS (
        SELECT CAST(:start AS bigint)
      UNION
        SELECT r.source_node
          FROM reached w
          JOIN relationships r
            ON r.target_node = w.node
           AND r.relationship_type = :rtype
           AND r.removed_at IS NULL
    )
    SELECT 1 FROM reached WHERE node = :other LIMIT 1
    """
)


async def _descends_from(session: AsyncSession, task_id: int, other_id: int) -> bool:
    """Whether ``other_id`` is one of ``task_id``'s parts, at any depth."""
    found = await session.exec(
        _PARTS_REACH.bindparams(
            start=node_id(SearchEntityType.task, task_id),
            other=node_id(SearchEntityType.task, other_id),
            rtype=RelationshipType.part_of.value,
        )
    )
    return found.first() is not None


async def set_parent(
    session: AsyncSession, task: Task, parent_id: Optional[int], *, user_id: int | None
) -> None:
    """Make ``parent_id`` the task ``task`` is part of, in place of the tasks
    it was part of; ``None`` takes it out of them.

    Linked as any link a person makes is (:func:`relationships.link`): the
    parent has to be a task the reader can open, in the same initiative, and
    neither may be archived. A tree has no loops, so a task cannot be put under
    itself or one of its own parts, though the edges could record it.
    """
    assert task.id is not None
    me = relationships_service.Endpoint(SearchEntityType.task, task.id)
    current = await relationships_service.list_for_entity(
        session,
        me,
        relationship_type=RelationshipType.part_of,
        other_kind=SearchEntityType.task,
        direction="outbound",
    )
    if parent_id is not None and all(row.target_id != parent_id for row in current):
        if parent_id == task.id or await _descends_from(session, task.id, parent_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.PARENT_IS_PART,
            )
        await relationships_service.link(
            session,
            relationships_service.Link(
                source=me,
                relationship_type=RelationshipType.part_of,
                target=relationships_service.Endpoint(SearchEntityType.task, parent_id),
            ),
            user_id=user_id,
        )
    for row in current:
        if row.target_id != parent_id:
            await relationships_service.remove(session, row, removed_by=user_id)


async def groups(session: AsyncSession, ids: list[int]) -> dict[int, list[Any]]:
    """The groups of a list grouped by parent: a subtask is listed under its
    parent, and a task with parts of its own leads its own group, so a board's
    band for a task holds the task and its parts together. A group is named
    after its task and ordered as the tasks are on the board."""
    # Local: the grouping module reads the field registry, which reads this.
    from app.services.fields.grouping import Group

    def group(task_id: int, title: str, position: float) -> Group:
        return Group(str(task_id), title, (position, title.casefold(), task_id))

    parents = await _parents(session, ids)
    found: dict[int, list[Any]] = {
        task_id: [group(*parent)] for task_id, parent in parents.items()
    }
    heads = [task_id for task_id in ids if task_id not in found]
    if heads:
        edge = EntityRelationship
        part = aliased(Task)
        with_parts = (
            select(edge.target_id)
            .join(part, part.id == edge.source_id)
            .where(
                *_part_of_edges(),
                part.archived_at.is_(None),  # type: ignore[union-attr]
                part.deleted_at.is_(None),  # type: ignore[union-attr]
            )
        )
        rows = await session.exec(
            select(Task.id, Task.title, Task.position).where(
                Task.id.in_(tuple(heads)),  # type: ignore[union-attr]
                Task.id.in_(with_parts),  # type: ignore[union-attr]
            )
        )
        for task_id, title, position in rows.all():
            found[task_id] = [group(task_id, title, position)]
    return found


#: A mention or a reference as text stores it: ``@[](42)``, ``@[Ada]()`` for
#: somebody with no account, ``#task[Fix it](12)``.
_STORED_LINK = re.compile(r"(?:@|#[\w-]*)\[[^\]]*\]\([^)]*\)")


def title_from_line(text: str) -> tuple[str, bool]:
    """A task title for a checklist line, and whether it says less than the
    line did: a title names no one and nothing (no ``@`` or ``#``) and fits on
    a line, where a checklist line may do both."""
    cleaned = _STORED_LINK.sub("", text)
    cleaned = "".join(ch for ch in cleaned if ch not in RESERVED_SIGILS)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > MAX_TITLE_LENGTH:
        cut = cleaned[: MAX_TITLE_LENGTH - 1]
        cleaned = (cut.rsplit(" ", 1)[0] or cut).rstrip() + "…"
    return cleaned, cleaned != text.strip()
