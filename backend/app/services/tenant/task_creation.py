"""Put a task row in a project, and name who works on it.

Creating a task has an endpoint-shaped half (who is allowed to, which
assignees to notify, which tags and properties to attach) and a row-shaped
half: find the end of the list, make sure the project has its statuses, decide
which status the task starts in, and build the row. This module is the second
half, shared by the task endpoint and the intake writer, together with the
pieces every task change reaches for: replacing a task's assignees and copying
tasks (``copy_tasks``), on their own or with their project. A repeating task's
next task is made in ``task_series``.

Nothing here commits, so a caller can compose it into a larger transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Sequence
from typing import Any, Optional

from fastapi import HTTPException, status as http_status
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.core.messages import TaskMessages
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db.session import require_actor_context
from app.models.tenant.project import Project
from app.models.tenant.task import (
    RecurrenceStrategy,
    Task,
    TaskAssignee,
    TaskStatus,
    TaskStatusCategory,
    TaskType,
)
from app.schemas.recurrence import validate_task_recurrence
from app.schemas.tenant.task import ChecklistItemInput
from app.services import notifications as notifications_service
from app.services.tenant import relationships
from app.services.tenant import named_people
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant import task_completion
from app.services.tenant import descriptions as descriptions_service
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant import task_types as task_types_service
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
    await task_statuses_service.ensure_default_statuses(
        session, project_id, locale=task_statuses_service.REPAIR_LOCALE
    )

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


async def resolve_type_row(
    session: AsyncSession,
    *,
    project_id: int,
    task_type_id: Optional[int] = None,
) -> TaskType:
    """The type a task is: the one named, which must be this project's, or
    the project's default."""
    if task_type_id is None:
        return await task_types_service.get_default_type(session, project_id)
    found = await task_types_service.get_project_type(session, task_type_id, project_id)
    if found is None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=TaskMessages.TYPE_NOT_FOUND,
        )
    return found


async def resolve_type(
    session: AsyncSession,
    *,
    project_id: int,
    task_type_id: Optional[int] = None,
) -> int:
    """:func:`resolve_type_row`'s id."""
    found = await resolve_type_row(
        session, project_id=project_id, task_type_id=task_type_id
    )
    assert found.id is not None
    return found.id


def start_from_type(
    task_type: TaskType,
    fields: dict[str, Any],
    *,
    sent: set[str],
) -> list[str]:
    """Fill ``fields`` (a new task's columns) with what its type starts a task
    with, for each one whoever made it did not send (``sent`` names those it
    did; one sent empty stays empty), and return the checklist lines it starts
    with. A repeat starts only on a task with a date to count from, and only
    one the task can have."""
    starting = task_types_service.starting_values_of(task_type)
    if starting is None:
        return []
    if starting.description and "description" not in sent:
        fields["description"] = starting.description
    if starting.priority is not None and "priority" not in sent:
        fields["priority"] = starting.priority
    if (
        starting.recurrence
        and "recurrence" not in sent
        and (fields.get("due_date") or fields.get("start_date"))
    ):
        strategy = (
            fields.get("recurrence_strategy")
            if "recurrence_strategy" in sent or starting.recurrence_strategy is None
            else starting.recurrence_strategy
        )
        try:
            validate_task_recurrence(
                rule=starting.recurrence,
                strategy=strategy or RecurrenceStrategy.fixed,
                limit=fields.get("recurrence_limit"),
                due=fields.get("due_date"),
            )
        except ValueError:
            pass
        else:
            fields["recurrence"] = starting.recurrence
            if strategy is not None:
                fields["recurrence_strategy"] = strategy
    return list(starting.checklist)


def starting_checklist(lines: list[str]) -> list[dict[str, Any]]:
    """The stored checklist :func:`start_from_type`'s lines start a task with."""
    return checklist_service.normalize(
        [ChecklistItemInput(text=line) for line in lines]
    )


async def create_task_row(
    session: AsyncSession,
    *,
    project: Project,
    task_status_id: Optional[int] = None,
    task_type_id: Optional[int] = None,
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
        task_type_id=await resolve_type(
            session, project_id=project.id, task_type_id=task_type_id
        ),
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


async def change_task_assignees(
    session: AsyncSession,
    task: Task,
    *,
    add: Sequence[int] = (),
    remove: Sequence[int] = (),
    project: Project,
) -> list[int]:
    """Put people on a task and take others off, leaving whoever else is on
    it. Written as the change rather than as a new list, so two changes made
    at once both land. Someone both added and removed is removed.

    Returns who this change put on the task: not anyone already on it, nor
    anyone another change put on it meanwhile."""
    removing = set(remove)
    adding = [user_id for user_id in dict.fromkeys(add) if user_id not in removing]
    governing = named_people.Governing.of(Tool.project, project)
    await named_people.require_readers(session, governing, adding)

    added: list[int] = []
    if adding:
        added = list(
            (
                await session.exec(
                    pg_insert(TaskAssignee)
                    .values(
                        [{"task_id": task.id, "user_id": user_id} for user_id in adding]
                    )
                    .on_conflict_do_nothing(index_elements=["task_id", "user_id"])
                    .returning(TaskAssignee.user_id)
                )
            )
            .scalars()
            .all()
        )
    if removing:
        removed = (
            (
                await session.exec(
                    delete(TaskAssignee)
                    .where(
                        TaskAssignee.task_id == task.id,
                        TaskAssignee.user_id.in_(sorted(removing)),
                    )
                    .returning(TaskAssignee.user_id)
                )
            )
            .scalars()
            .all()
        )
        await notifications_service.dequeue_task_assignment_events(
            session, task_id=task.id, user_ids=sorted(removed)
        )

    await session.flush()
    await session.refresh(task, attribute_names=["assignees"])
    return added


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
    type_mapping: dict[int, int],
    fallback_type_id: int,
) -> list[Task]:
    """Copy every task of ``source`` into ``target``, a copy of it whose
    statuses ``status_mapping`` maps and whose types ``type_mapping`` does,
    keeping titles and order; returns the copies. Dates move onto the target's schedule (:func:`_date_shift`), and
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
        type_of=lambda task: type_mapping.get(task.task_type_id, fallback_type_id),
        date_shift=_date_shift(source, target, list(tasks)),
        keep_done=source.is_template,
    )


async def copy_tasks(
    session: AsyncSession,
    sources: Sequence[Task],
    target: Project,
    *,
    status_of: Callable[[Task], int | None] | None = None,
    type_of: Callable[[Task], int] | None = None,
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

    ``status_of`` gives each copy its status in another project, and
    ``type_of`` its type; without them the copies keep their sources'. Without
    ``status_of``
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
        anchor = source.recurrence_anchor
        if date_shift is not None:
            shift = date_shift
            if repeat and (due_date or start_date):
                # A series moves on its own rule, from its due date or its
                # start without one, and its dates move with its start.
                start = anchor or due_date or start_date
                series = recurrence.moved(
                    repeat,
                    start,
                    source.recurrence_shift,
                    date_shift,
                    occurrences=[due_date or start_date],
                )
                repeat = series.text
                anchor = series.start
                original = due_date or start_date
                shift = series.occurrences[original] - original
            start_date = start_date + shift if start_date else None
            due_date = due_date + shift if due_date else None
        copy = Task(
            project_id=target.id,
            title=copy_name(source.title) if beside else source.title,
            description=source.description,
            task_status_id=status_id,
            task_type_id=source.task_type_id if type_of is None else type_of(source),
            priority=source.priority,
            start_date=start_date,
            due_date=due_date,
            recurrence=repeat,
            recurrence_shift=source.recurrence_shift,
            recurrence_anchor=anchor,
            recurrence_anchor_count=source.recurrence_anchor_count,
            recurrence_strategy=source.recurrence_strategy,
            recurrence_limit=source.recurrence_limit,
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
            await descriptions_service.record_references(
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
