"""Put a task row in a project, and name who works on it.

Creating a task has an endpoint-shaped half (who is allowed to, which
assignees to notify, which tags and properties to attach) and a row-shaped
half: find the end of the list, make sure the project has its statuses, decide
which status the task starts in, and build the row. This module is the second
half, shared by the task endpoint and the intake writer, together with the
pieces every task change reaches for: replacing a task's assignees, rolling a
recurring task forward to its next occurrence when it is completed (from the
task routes and from a status change that moves tasks between columns), and
copying tasks (``copy_tasks``), on their own or with their project.

Nothing here commits, so a caller can compose it into a larger transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Sequence
from typing import Any, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.messages import TaskMessages
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.session import require_actor_context
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.services import notifications as notifications_service
from app.services.tenant import relationships
from app.services.tenant import named_people
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant import task_completion
from app.services.tenant import task_description as task_description_service
from app.services.tenant import task_series
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant.names import copy_name
from app.services.tenant.task_completion import sync_completed_at


async def next_position(session: AsyncSession, project_id: int) -> float:
    """The position that puts a new task at the end of the project."""
    result = await session.exec(
        select(func.max(Task.position)).where(Task.project_id == project_id)
    )
    return (result.one_or_none() or 0) + 1


async def resolve_start_status(
    session: AsyncSession,
    *,
    project_id: int,
    task_status_id: Optional[int] = None,
) -> TaskStatus:
    """The status a new task starts in, seeding the project's defaults first.

    A named status must belong to this project; anything else is a 400 rather
    than a silent fall back to the default, so a caller naming another
    project's status learns it instead of filing into the wrong column.

    Seeding here is the same safety net the endpoint has always had: the read
    path deliberately never seeds — a read-only grantee routes into a
    SELECT-only role and could not — so the first write is where a project that
    somehow arrived without its defaults gets them.
    """
    await task_statuses_service.ensure_default_statuses(session, project_id)

    if task_status_id is not None:
        selected = await task_statuses_service.get_project_status(
            session, status_id=task_status_id, project_id=project_id
        )
        if selected is None:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.STATUS_NOT_FOUND,
            )
        return selected

    return await task_statuses_service.get_default_status(session, project_id)


async def create_task_row(
    session: AsyncSession,
    *,
    project: Project,
    task_status_id: Optional[int] = None,
    now: Optional[datetime] = None,
    **fields: Any,
) -> Task:
    """Build, add and flush one task at the end of ``project``.

    ``fields`` are the task's own columns — title, description, priority, due
    date and the rest; the caller owns validating them. Assignees, tags and
    property values are attached by the caller afterwards, because each is a
    service of its own with its own failure modes.

    The caller is responsible for access control: this writes the row it is
    asked for.
    """
    selected_status = await resolve_start_status(
        session, project_id=project.id, task_status_id=task_status_id
    )
    task = Task(
        **fields,
        project_id=project.id,
        position=await next_position(session, project.id),
        task_status_id=selected_status.id,
    )
    sync_completed_at(
        task, selected_status.category, now=now or datetime.now(timezone.utc)
    )
    session.add(task)
    await session.flush()
    return task


async def set_task_assignees(
    session: AsyncSession,
    task: Task,
    assignee_ids: list[int] | None,
    *,
    project: Project,
    carried: bool = False,
) -> None:
    """Replace the task's assignees. Everyone named must be able to open the
    project; ``carried`` is a copy made from existing assignees (a duplicate, a
    recurrence, a move), which keeps those who still can rather than refusing."""
    unique_ids = list(dict.fromkeys(assignee_ids or []))
    governing = named_people.Governing.of(Tool.project, project)
    if carried:
        keep = await named_people.readers(session, governing, unique_ids)
        unique_ids = [user_id for user_id in unique_ids if user_id in keep]
    else:
        await named_people.require_readers(session, governing, unique_ids)

    # Read the current set before replacing it, so anyone dropped can have
    # their un-sent digest item withdrawn. An explicit query rather than
    # ``task.assignees`` — on a freshly flushed task that relationship is not
    # loaded yet, and touching it would fire a lazy load.
    previous_ids = set(
        (
            await session.exec(
                select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
            )
        ).all()
    )

    delete_stmt = delete(TaskAssignee).where(TaskAssignee.task_id == task.id)
    await session.exec(delete_stmt)

    if unique_ids:
        session.add_all(
            [TaskAssignee(task_id=task.id, user_id=user_id) for user_id in unique_ids]
        )

    await notifications_service.dequeue_task_assignment_events(
        session, task_id=task.id, user_ids=sorted(previous_ids - set(unique_ids))
    )

    await session.flush()
    await session.refresh(task, attribute_names=["assignees"])


async def advance_recurrence_if_needed(
    session: AsyncSession,
    task: Task,
    *,
    previous_status_category: TaskStatusCategory | None,
    now: datetime,
    user_timezone: str | None,
) -> bool:
    current_category = task.task_status.category if task.task_status else None
    if (
        previous_status_category == TaskStatusCategory.done
        or current_category != TaskStatusCategory.done
        or not task.recurrence
        or task.due_date is None
    ):
        return False

    try:
        dates = task_series.next_dates(task, now=now, user_timezone=user_timezone)
    except ValueError:
        return False
    if dates is None:
        task.recurrence = None
        return False
    new_start, next_due = dates

    # An edit of just this task leaves the next one with what it changed from.
    values = task_series.carried(task)
    task.series_id = task.series_id or task.id
    default_status = await task_statuses_service.get_default_status(
        session, task.project_id
    )
    new_task = Task(
        project_id=task.project_id,
        task_status_id=default_status.id,
        title=values.get("title", task.title),
        description=values.get("description", task.description),
        priority=values.get("priority", task.priority),
        start_date=new_start,
        due_date=next_due,
        recurrence=task.recurrence,
        recurrence_shift=task.recurrence_shift,
        recurrence_strategy=task.recurrence_strategy or "fixed",
        position=await next_position(session, task.project_id),
        recurrence_occurrence_count=task.recurrence_occurrence_count + 1,
        series_id=task.series_id,
        created_by=task.created_by,
        checklist=checklist_service.cloned(task.checklist),
    )
    sync_completed_at(new_task, default_status.category, now=now)
    session.add(new_task)
    await session.flush()
    assignee_ids = values.get(
        "assignee_ids", [assignee.id for assignee in task.assignees]
    )
    project = await session.get(Project, task.project_id)
    if project is None:  # the task was just read inside it
        raise RuntimeError("a recurring task's project is gone")
    await set_task_assignees(
        session, new_task, assignee_ids, project=project, carried=True
    )
    if "tag_ids" in values:
        await task_series.retag(session, new_task.id, values["tag_ids"])
    else:
        await tags_service.copy_entity_tags(
            session,
            tags_service.TAG_LINKS["task"],
            {task.id: new_task.id},
        )
    if new_task.description:
        await task_description_service.record_references(
            session, new_task, author_id=task.created_by
        )
    await session.flush()
    # Reload through a select rather than ``session.refresh``: refresh takes no
    # loader options, so the assignees would come back unloaded and the
    # serializer would have to emit IO from sync context. ``populate_existing``
    # applies the freshly loaded rows to the identity-mapped instance.
    await session.exec(
        select(Task)
        .where(Task.id == new_task.id)
        .options(
            selectinload(Task.assignees),
        )
        .execution_options(populate_existing=True)
    )
    await tags_service.annotate_tags(session, [new_task])
    await properties_service.annotate_properties(session, [new_task])

    task.recurrence = None
    task.recurrence_strategy = "fixed"
    task.recurrence_carry = None
    task.updated_at = now
    session.add(task)
    return True


def _date_shift(
    template: Project,
    new_project: Project,
    template_tasks: list[Task],
) -> timedelta | None:
    """Offset to move template task dates onto the new project's schedule.

    Task dates in a template are relative: a task due three weeks after the
    template's start should land three weeks after the new project's start.
    Anchors on the projects' start dates when the new project has one,
    otherwise on their end dates. A template without an explicit start/end
    falls back to its earliest/latest task date. Returns None when there is
    nothing to anchor on, in which case dates are copied as-is.
    """
    task_dates = [
        value.date()
        for task in template_tasks
        for value in (task.start_date, task.due_date)
        if value is not None
    ]
    if new_project.start_date is not None:
        anchor = template.start_date or (min(task_dates) if task_dates else None)
        if anchor is not None:
            return new_project.start_date - anchor
    if new_project.end_date is not None:
        anchor = template.end_date or (max(task_dates) if task_dates else None)
        if anchor is not None:
            return new_project.end_date - anchor
    return None


async def copy_project_tasks(
    session: AsyncSession,
    source: Project,
    target: Project,
    *,
    status_mapping: dict[int, int],
    fallback_status_ids: dict[TaskStatusCategory, int],
) -> list[Task]:
    """Copy every task of ``source`` into ``target``, a copy of it whose
    statuses ``status_mapping`` maps, keeping titles and order; returns the
    copies. Dates move onto the target's schedule (:func:`_date_shift`), and
    checklists keep their ticks only from a template, which is copied as
    written."""
    tasks = (
        await session.exec(
            select(Task)
            .options(selectinload(Task.assignees), selectinload(Task.task_status))
            .where(Task.project_id == source.id)
            .order_by(Task.position.asc(), Task.id.asc())
        )
    ).all()
    if not tasks:
        return []

    def status_of(task: Task) -> int | None:
        mapped = (
            status_mapping.get(task.task_status_id) if task.task_status_id else None
        )
        if mapped is None and task.task_status is not None:
            mapped = fallback_status_ids.get(task.task_status.category)
        if mapped is None and fallback_status_ids:
            mapped = next(iter(fallback_status_ids.values()))
        return mapped

    return await copy_tasks(
        session,
        tasks,
        target,
        status_of=status_of,
        date_shift=_date_shift(source, target, list(tasks)),
        keep_done=source.is_template,
    )


async def copy_tasks(
    session: AsyncSession,
    sources: Sequence[Task],
    target: Project,
    *,
    status_of: Callable[[Task], int | None] | None = None,
    date_shift: timedelta | None = None,
    keep_done: bool = False,
    assignees: set[int] | None = None,
) -> list[Task]:
    """Copy ``sources``, loaded with their assignees, into ``target``; returns
    the copies in the same order. The assignees come along (only those in
    ``assignees`` when it is given; otherwise all, for the caller to sweep with
    ``named_people.sweep`` once ``target``'s sharing is readable), with the
    tags, the links (a link between two of the sources joins
    their copies) and, inside one initiative, the property values.

    ``status_of`` gives each copy its status in another project. Without it
    the copies go beside their sources: the same status, named
    "<title> (Copy)", at the end of the list. Checklists start unticked unless
    ``keep_done``.
    """
    beside = status_of is None
    now = datetime.now(timezone.utc)
    categories = await task_completion.status_categories(session, target.id)
    end = await next_position(session, target.id) if beside else 0
    copies: list[Task] = []
    for index, source in enumerate(sources):
        status_id = source.task_status_id if status_of is None else status_of(source)
        start_date, due_date, repeat = (
            source.start_date,
            source.due_date,
            source.recurrence,
        )
        if date_shift is not None:
            shift = date_shift
            if repeat and (due_date or start_date):
                # A series moves on its own rule, from its due date or its
                # start without one, and its dates move with its start.
                start = due_date or start_date
                series = recurrence.moved(
                    repeat, start, source.recurrence_shift, date_shift
                )
                repeat, shift = series.text, series.start - start
            start_date = start_date + shift if start_date else None
            due_date = due_date + shift if due_date else None
        copy = Task(
            project_id=target.id,
            title=copy_name(source.title) if beside else source.title,
            description=source.description,
            task_status_id=status_id,
            priority=source.priority,
            start_date=start_date,
            due_date=due_date,
            recurrence=repeat,
            recurrence_shift=source.recurrence_shift,
            recurrence_strategy=source.recurrence_strategy,
            position=end + index if beside else source.position,
            checklist=checklist_service.cloned(source.checklist, keep_done=keep_done),
        )
        # A copy in a done column is complete from the moment it exists:
        # stamped now, since the copy is not what finished when its source did.
        task_completion.sync_completed_at(copy, categories.get(status_id), now=now)
        session.add(copy)
        copies.append(copy)
    await session.flush()

    author_id = require_actor_context(session).user_id
    for source, copy in zip(sources, copies):
        session.add_all(
            TaskAssignee(task_id=copy.id, user_id=assignee.id)
            for assignee in source.assignees
            if assignees is None or assignee.id in assignees
        )
        if copy.description:
            await task_description_service.record_references(
                session, copy, author_id=author_id
            )
    copied_ids = {s.id: c.id for s, c in zip(sources, copies)}
    await tags_service.copy_entity_tags(
        session, tags_service.TAG_LINKS["task"], copied_ids
    )
    origin = await session.get(Project, sources[0].project_id) if sources else None
    if origin is not None and origin.initiative_id == target.initiative_id:
        await properties_service.copy_values(session, Task, copied_ids)
    await relationships.copy_links(session, SearchEntityType.task, copied_ids)
    return copies
