"""Keep ``Task.completed_at`` in step with the task's status category.

``completed_at`` is derived state: a task is complete exactly when its status
sits in the ``done`` category. The timestamp is stamped on the way in and
cleared on the way out, so ``completed_at IS NOT NULL`` and "the task's status
is done" always agree. Consumers (stats, digests, the My Tasks focus list) can
then trust the column instead of proxying completion with ``updated_at``.

Two kinds of writer have to route through here:

* anything that assigns ``Task.task_status_id`` — :func:`sync_completed_at`;
* the status edit that changes a ``TaskStatus.category``, which flips done-ness
  for every task sitting in it without touching a single task row —
  :func:`resync_status_tasks`.

The per-task rule is deliberately *state-derived* rather than edge-triggered:
it reads the category the task holds now, not the one it held before, so a
caller never has to thread the previous value through, and re-running it on an
unchanged task is a no-op. That is also what keeps a move between two different
``done`` statuses from resetting the original completion time.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory


def sync_completed_at(
    task: Task,
    category: TaskStatusCategory | None,
    *,
    now: datetime,
) -> None:
    """Align ``task.completed_at`` with ``category``, the category of the status
    the task holds *after* the caller's change.

    Call it on every path that creates a task or reassigns its status. Stamps
    ``now`` on entry to ``done``, clears on exit, and leaves an already-complete
    task's timestamp alone so done → done keeps the original completion time.
    """
    if category == TaskStatusCategory.done:
        if task.completed_at is None:
            task.completed_at = now
    elif task.completed_at is not None:
        task.completed_at = None


async def resync_status_tasks(
    session: AsyncSession,
    *,
    status_id: int,
    category: TaskStatusCategory,
    now: datetime,
) -> None:
    """Realign every task sitting in a status whose category just changed.

    Recategorising a column moves its tasks across the done boundary without
    any task row being written, so the set is fixed up in one statement. Tasks
    that already agree are left untouched, which preserves the completion time
    of anything that was already done.
    """
    if category == TaskStatusCategory.done:
        statement = (
            update(Task)
            .where(Task.task_status_id == status_id, Task.completed_at.is_(None))
            .values(completed_at=now)
        )
    else:
        statement = (
            update(Task)
            .where(Task.task_status_id == status_id, Task.completed_at.is_not(None))
            .values(completed_at=None)
        )
    await session.exec(statement)


async def status_categories(
    session: AsyncSession, project_id: int
) -> dict[int, TaskStatusCategory]:
    """``{status_id: category}`` for a project.

    Bulk creators (imports, template copies) resolve each new task's done-ness
    from this map rather than issuing a status lookup per task.
    """
    result = await session.exec(
        select(TaskStatus).where(TaskStatus.project_id == project_id)
    )
    return {row.id: row.category for row in result.all() if row.id is not None}
