"""How many open tasks a project's board columns may hold, and the check that
holds a person to it.

A limit is the project's board layout's (``ListLayoutDefinition.limits``): a
status and how many open tasks its column takes. A column at its limit takes
no more from a person: the UI stops them first, and the routes a person puts a
task into a status through refuse what it would not. MCP calls and plug-ins
acting for a member are that member. A plug-in acting as itself, an
automation, and the project's own machinery (repeating tasks, imports,
copies) are not held to it, and nothing moves out of a column past its limit.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import TaskMessages
from app.core.tools import Tool
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.guild_standing import ActorContext, by_a_person
from app.db.session import routed_guild_id
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.models.tenant.tool_layout import ToolLayout
from app.schemas.tenant.task import ColumnFillRead


async def limits_of(session: AsyncSession, project_id: int) -> dict[int, int]:
    """Each limited column of the project's board, by its status."""
    definition = (
        await session.exec(
            select(ToolLayout.definition).where(
                ToolLayout.tool == Tool.project.value,
                ToolLayout.tool_id == project_id,
                ToolLayout.kind == "board",
            )
        )
    ).first()
    return {
        int(entry["status_id"]): int(entry["limit"])
        for entry in (definition or {}).get("limits") or ()
    }


async def open_counts(
    session: AsyncSession,
    project_ids: Sequence[int],
    statuses: Sequence[int],
    *,
    excluding: Sequence[int] = (),
) -> dict[int, int]:
    """How many open (not archived, not trashed) tasks each of ``statuses``
    of ``project_ids`` holds, less ``excluding``."""
    query = (
        select(Task.task_status_id, func.count())
        .where(
            col(Task.project_id).in_(project_ids),
            Task.archived_at.is_(None),
            Task.task_status_id.in_(statuses),
        )
        .group_by(Task.task_status_id)
    )
    if excluding:
        query = query.where(Task.id.not_in(excluding))
    return {status_id: count for status_id, count in (await session.exec(query)).all()}


async def fills(
    session: AsyncSession, project_ids: Sequence[int]
) -> list[ColumnFillRead]:
    """Each limited column of the boards of ``project_ids`` the reader can
    open: its limit, and how many open tasks it holds whatever the reader's
    filters show."""
    boards = (
        await session.exec(
            select(ToolLayout.tool_id, ToolLayout.definition)
            .join(Project, col(Project.id) == ToolLayout.tool_id)
            .where(
                ToolLayout.tool == Tool.project.value,
                ToolLayout.kind == "board",
                col(ToolLayout.tool_id).in_(project_ids),
            )
        )
    ).all()
    limits = {
        int(entry["status_id"]): (project_id, int(entry["limit"]))
        for project_id, definition in boards
        for entry in (definition or {}).get("limits") or ()
    }
    if not limits:
        return []
    held = await open_counts(
        session, sorted({project_id for project_id, _ in limits.values()}), list(limits)
    )
    return [
        ColumnFillRead(
            project_id=project_id,
            status_id=status_id,
            limit=limit,
            count=held.get(status_id, 0),
        )
        for status_id, (project_id, limit) in sorted(limits.items())
    ]


async def refuse_full_columns(
    session: AsyncSession,
    context: ActorContext,
    project_id: int,
    entering: Sequence[Task],
) -> None:
    """Refuse a person's write that puts ``entering`` (each already in the
    status it is going to) into a column of the project at its limit.

    Called before the write commits. Changes to one column take turns, so two
    people dropping into its last place at once cannot both get in. What a
    column holds is its other open tasks, so a task already in it, or one
    taken out of it, is never counted against a move."""
    if not entering or not by_a_person(context):
        return
    limits = await limits_of(session, project_id)
    into = Counter(
        task.task_status_id for task in entering if task.task_status_id in limits
    )
    if not into:
        return
    guild_id = routed_guild_id(session)
    for status_id in sorted(into):
        await advisory_lock(
            session, LockNamespace.COLUMN_LIMIT, f"{guild_id}:{status_id}"
        )
    held = await open_counts(
        session,
        [project_id],
        list(into),
        excluding=[task.id for task in entering if task.id is not None],
    )
    if any(
        held.get(status_id, 0) + n > limits[status_id] for status_id, n in into.items()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TaskMessages.STATUS_AT_LIMIT,
        )
