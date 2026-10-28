from datetime import datetime, timezone
from typing import Annotated, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    SessionDep,
    UserSessionDep,
    plugin_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.core import recurrence
from app.core.messages import ChecklistMessages, QueryMessages, TaskMessages
from app.db.query import build_paginated_response, paginated_query
from app.db.session import routed_guild_id
from app.models.platform.user import User
from app.models.tenant.comment import Comment
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.ai_generation import (
    GenerateChecklistResponse,
    GenerateDescriptionResponse,
)
from app.schemas.query import DateBucket, GroupRead, GroupsResponse
from app.schemas.recurrence import OccurrenceScope, validate_task_recurrence
from app.schemas.platform.access_grant import AccessGrantRead
from app.schemas.tenant.task import (
    ChecklistItem,
    ChecklistItemToggle,
    CaseEvidenceRead,
    CaseMessageRead,
    ColumnFillRead,
    TaskCaseRead,
    TaskCreate,
    TaskListResponse,
    TaskMoveRequest,
    TaskRead,
    TaskReorderRequest,
    TaskUpdate,
)
from app.schemas.platform.user import UserPublic
from app.services import ai_generation as ai_generation_service
from app.services import notifications as notifications_service
from app.services.fields.grouping import GroupingError, group_rows
from app.services.tenant import archive as archive_service
from app.services.tenant import attachments as attachments_service
from app.services.tenant import column_limits
from app.services.tenant import overwrites
from app.services.tenant import required_fields
from app.services.tenant import cases as cases_service
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant import task_hierarchy
from app.services.tenant import task_creation as task_creation_service
from app.core.tools import KINDS, Tool
from app.services.tenant import named_people
from app.services.tenant import descriptions as descriptions_service
from app.services.tenant import task_queries
from app.services.tenant import task_series
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant import task_types as task_types_service
from app.services.tenant.soft_delete import trash
from app.services.tenant.task_completion import sync_completed_at

router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call. A task is the project's, so it
#: answers to the projects scopes.
ProjectsRead = Annotated[ActorContext, Depends(plugin_scope("projects:read"))]
ProjectsWrite = Annotated[ActorContext, Depends(plugin_scope("projects:write"))]


# Cross-guild "my tasks" aggregates (My Tasks / Created Tasks pages). Mounted
# under /api/v1/me; user-scoped (no guild context), routes per member guild
# itself via gather_across_guilds.
me_router = APIRouter()


# Positions are stored as NUMERIC(20, 10); two stored values differ by at least
# 1e-10. When repeated midpoint inserts squeeze neighbors closer than this, the
# next midpoint can no longer fit between them, so we renumber the whole group.
_MIN_POSITION_GAP = 1e-9


async def _rebalance_if_needed(
    session: SessionDep, project_id: int, moved_positions: dict[int, float]
) -> dict[int, float]:
    """Renumber a project's tasks to evenly spaced integers when two positions have
    collided to within ``_MIN_POSITION_GAP`` (precision exhaustion from repeated
    drag-reorder midpoint inserts).

    Positions are a single project-wide ordering (the list view sorts by them and
    kanban columns are filtered slices of that order), so the rebalance spans the
    whole project rather than a single status group.

    A collision can only be introduced next to a task we just moved, so the common
    case (no exhaustion) is settled with a cheap existence query per moved task
    instead of loading the whole project. Only on a near-collision do we scan and
    renumber.

    Sets only ``position`` on the touched tasks — never ``updated_at`` — so tasks
    that were merely renumbered (not explicitly moved) don't churn. Returns a map
    of task id -> new position for every task it changed (empty when no rebalance
    was necessary).
    """
    # The session runs with autoflush off, so push the just-applied positions to
    # the DB before the neighbor check evaluates them in SQL (otherwise it reads
    # stale values and reports phantom collisions).
    await session.flush()

    collision = False
    for moved_id, position in moved_positions.items():
        neighbor = await session.exec(
            select(Task.id)
            .where(
                Task.project_id == project_id,
                Task.id != moved_id,
                func.abs(Task.position - position) < _MIN_POSITION_GAP,
            )
            .limit(1)
        )
        if neighbor.first() is not None:
            collision = True
            break
    if not collision:
        return {}

    stmt = (
        select(Task)
        .where(Task.project_id == project_id)
        .order_by(Task.position.asc(), Task.id.asc())
    )
    result = await session.exec(stmt)
    ordered = result.all()

    changed: dict[int, float] = {}
    for index, task in enumerate(ordered, start=1):
        new_position = float(index)
        if task.position != new_position:
            task.position = new_position
            session.add(task)
            changed[task.id] = new_position  # ty: ignore[invalid-assignment] — persisted row, id is set
    return changed


def _touch_project(project: Project, now: datetime) -> None:
    """Bump a project's updated_at so task activity surfaces in 'sort by updated'."""
    project.updated_at = now


#: A task has no sharing of its own: it is reached through its project, at the
#: project's level. Which tool that is comes from the registry entry the
#: ``tasks`` policy is rendered from, so the routes and the policy cannot
#: disagree about a task's parent.
_GOVERNING = resource_access.governing_tool("tasks")


async def _writable_series(
    session: AsyncSession,
    task: Task,
    current_user: Optional[User],
    context: ActorContext,
) -> list[Task]:
    """Every other task of the task's series, once the caller may change each."""
    series = await task_series.others(session, task)
    for project in {member.project_id: member.project for member in series}.values():
        resource_access.authorize(
            _GOVERNING, project, current_user, context=context, access="write"
        )
    return series


async def _response(session: SessionDep, task_id: int) -> Task:
    """The task as a ``TaskRead`` reads it, after a change has committed."""
    task = await task_queries.load_task(session, task_id)
    if task is None:
        raise KINDS["task"].not_found(status.HTTP_500_INTERNAL_SERVER_ERROR)
    return task


@me_router.get("/tasks", response_model=TaskListResponse)
async def list_my_tasks(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    conditions: Optional[str] = Query(default=None),
    created: bool = Query(
        default=False,
        description="The tasks you created instead of the ones assigned to you",
    ),
    include_archived: bool = Query(default=False, description="Include archived tasks"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sorting: Optional[str] = Query(default=None),
    tz: Optional[str] = Query(default=None),
) -> TaskListResponse:
    """Tasks assigned to the current user across every guild they belong to,
    or with ``created`` the tasks they created.

    An optional ``guild_ids`` conditions entry narrows to a subset of guilds.
    """
    q = await task_queries.parse_task_list_query(
        session, conditions, sorting, tz, across_guilds_for=current_user
    )
    items, total_count, actual_page = await task_queries.list_global_tasks(
        session,
        current_user,
        q,
        created=created,
        include_archived=include_archived,
        page=page,
        page_size=page_size,
    )
    return TaskListResponse(
        **build_paginated_response(
            items=items,
            total_count=total_count,
            page=actual_page,
            page_size=page_size,
            sorting=sorting,
        )
    )


@router.get("/", response_model=TaskListResponse)
async def list_tasks(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
    conditions: Optional[str] = Query(
        default=None,
        description=(
            "JSON list of filter conditions, AND-ed together. Each object: "
            '{"field": "<column>", "op": "<operator>", "value": <val>}. '
            "Any Task column is valid plus virtual fields: "
            "status_category, assignee_ids, tag_ids, initiative_ids. "
            'An object with a "conditions" key is an AND/OR group: '
            '{"logic": "or", "conditions": [...]}.'
        ),
    ),
    include_archived: bool = Query(default=False, description="Include archived tasks"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
    sorting: Optional[str] = Query(
        default=None,
        description='JSON list of sort fields: [{"field": "due_date", "dir": "desc"}]',
    ),
    tz: Optional[str] = Query(
        default=None,
        description="IANA timezone name (e.g. America/Los_Angeles) for date_group calculation",
    ),
) -> TaskListResponse:
    q = await task_queries.parse_task_list_query(session, conditions, sorting, tz)
    if current_user is None:
        task_queries.refuse_person_filters(q)

    # Guild-scoped list. Cross-guild "my tasks" aggregates live under
    # /me/tasks (see list_my_tasks above).
    build = await task_queries.guild_task_query_builder(
        session,
        current_user,
        guild_context,
        q=q,
        include_archived=include_archived,
    )
    if build is None:
        return TaskListResponse(
            **build_paginated_response(
                items=[],
                total_count=0,
                page=1,
                page_size=page_size,
                sorting=sorting,
            )
        )

    count_stmt = select(func.count()).select_from(build(select(Task.id)).subquery())
    statement = task_queries.list_row_statement(build, q)
    rows, total_count, actual_page = await paginated_query(
        session, statement, count_stmt, page, page_size
    )
    items = await task_queries.list_reads(session, rows, routed_guild_id(session))
    return TaskListResponse(
        **build_paginated_response(
            items=items,
            total_count=total_count,
            page=actual_page,
            page_size=page_size,
            sorting=sorting,
        )
    )


@router.post("/", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    task = await _insert_task(task_in, session, current_user, guild_context)
    await required_fields.refuse_missing(session, guild_context, task)
    await session.commit()
    return await _response(session, task.id)


async def _insert_task(
    task_in: TaskCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    """A new task, with all it was sent, in the session's transaction: what
    :func:`create_task` commits, and what a promoted checklist line becomes."""
    project = await resource_access.load_authorized(
        session,
        _GOVERNING,
        task_in.project_id,
        current_user,
        guild_context,
        access="write",
    )

    task_data = task_in.model_dump(
        exclude={
            "assignee_ids",
            "task_status_id",
            "task_type_id",
            "tag_ids",
            "properties",
            "checklist",
            "tz",
            "parent_task_id",
        }
    )
    # What the task's type starts a task with, where it was left empty.
    task_type = await task_creation_service.resolve_type_row(
        session, project_id=project.id, task_type_id=task_in.task_type_id
    )
    starting_lines = task_creation_service.start_from_type(
        task_type, task_data, sent=task_in.model_fields_set
    )
    checklist = (
        checklist_service.normalize(task_in.checklist)
        if "checklist" in task_in.model_fields_set
        else task_creation_service.starting_checklist(starting_lines)
    )
    if task_data.get("recurrence"):
        task_data["recurrence"], task_data["recurrence_shift"] = recurrence.stored(
            task_data["recurrence"],
            task_data.get("due_date") or task_data.get("start_date"),
            task_in.tz,
            kind="task",
        )

    task_data.pop("project_id", None)
    task = await task_creation_service.create_task_row(
        session,
        project=project,
        task_status_id=task_in.task_status_id,
        task_type_id=task_type.id,
        **task_data,
        created_by=guild_context.user_id,
        checklist=checklist,
    )
    await column_limits.refuse_full_columns(session, guild_context, project.id, [task])
    await task_creation_service.set_task_assignees(
        session, task, task_in.assignee_ids, project=project
    )
    if task.assignees:
        assigned_by = await notifications_service.author_of(
            session, guild_context, current_user
        )
        await notifications_service.notify_assigned(
            session,
            task,
            [assignee.id for assignee in task.assignees],
            assigned_by=assigned_by,
            project_name=project.name,
        )

    # Attach tags and custom properties in the same transaction. Both services
    # mutate the session without committing; a raised HTTPException (invalid
    # tag/property) rolls back so no orphan task is persisted.
    try:
        if task_in.tag_ids:
            await tags_service.set_entity_tags(
                session,
                tags_service.TAG_LINKS["task"],
                guild_id=guild_context.guild_id,
                entity_id=task.id,
                tag_ids=task_in.tag_ids,
            )
    except (HTTPException, CodedError):
        await session.rollback()
        raise

    if task.description:
        await descriptions_service.description_saved(
            session,
            task,
            previous=None,
            author=current_user,
        )
    await attachments_service.claim_uploads(session, task)

    if task_in.parent_task_id is not None:
        await task_hierarchy.set_parent(
            session, task, task_in.parent_task_id, user_id=guild_context.user_id
        )

    _touch_project(project, datetime.now(timezone.utc))
    await metadata_service.write_on_create(session, task, task_in.properties)
    return task


@router.get("/groups", response_model=GroupsResponse)
async def list_task_groups(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
    group_by: str = Query(
        max_length=64,
        description=(
            "The field the list is grouped by, as the field catalog's "
            "``groupings`` name it, or ``property:<id>``"
        ),
    ),
    bucket: Optional[DateBucket] = Query(
        default=None, description="For a date: the bucket of the calendar it groups by"
    ),
    conditions: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
    tz: Optional[str] = Query(default=None),
) -> GroupsResponse:
    """The groups of the task list these filters answer with, in the order the
    list shows them, and the groups each task is in."""
    q = await task_queries.parse_task_list_query(session, conditions, None, tz)
    if current_user is None:
        task_queries.refuse_person_filters(q)
    build = await task_queries.guild_task_query_builder(
        session, current_user, guild_context, q=q, include_archived=include_archived
    )
    ids = list(await session.exec(build(select(Task.id)))) if build else []
    try:
        grouping = await group_rows(
            session, "tasks", group_by, ids, bucket=bucket, tz=q.tz
        )
    except GroupingError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=QueryMessages.INVALID_GROUPING,
        )
    return GroupsResponse(
        groups=[GroupRead(key=g.key, label=g.label) for g in grouping.listed()],
        rows={
            row_id: [group.key for group in held]
            for row_id, held in grouping.groups.items()
            if held
        },
    )


@router.get("/column-limits", response_model=List[ColumnFillRead])
async def list_column_limits(
    session: ActorSessionDep,
    guild_context: ProjectsRead,
    project_id: Annotated[List[int], Query(min_length=1, max_length=100)],
) -> List[ColumnFillRead]:
    """Each limited board column of the named projects the reader can open:
    its limit, and how many open tasks it holds. A project with no limits, or
    one the reader can't open, has none."""
    return await column_limits.fills(session, project_id)


@router.get("/{task_id}", response_model=TaskRead)
async def read_task(
    task_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
    include_deleted: IncludeDeletedDep = False,
) -> Task:
    task = await task_queries.load_task(session, task_id)
    if task is None:
        raise KINDS["task"].not_found()
    resource_access.authorize(
        _GOVERNING, task.project, current_user, context=guild_context
    )
    return task


@router.get("/{task_id}/case", response_model=TaskCaseRead)
async def read_task_case(
    task_id: int,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
) -> TaskCaseRead:
    """How an operations case was filed: its stream, who filed it, and what
    the stream allows with them. 404 for a task no stream opened."""
    await resource_access.load_child(session, Task, task_id, access="read")
    case = await cases_service.read_case(session, task_id)
    if case is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_A_CASE
        )
    return TaskCaseRead(
        stream=case.stream,
        opened_at=case.opened_at,
        filer=(
            UserPublic.model_validate(case.filer, from_attributes=True)
            if case.filer is not None
            else None
        ),
        filer_subject=case.filer_subject,
        topic=case.topic,
        subject_community_id=case.subject_guild_id,
        resource_type=case.resource_type,
        resource_id=case.resource_id,
        conversation=case.conversation,
        awaiting_filer_status_id=case.awaiting_filer_status_id,
        active_status_id=case.active_status_id,
        messages=[
            CaseMessageRead(
                id=message.id,
                author=(
                    UserPublic.model_validate(message.author, from_attributes=True)
                    if message.author is not None
                    else None
                ),
                from_requester=(
                    case.filer is not None and message.created_by == case.filer.id
                ),
                content=message.content,
                created_at=message.created_at,
            )
            for message in case.messages
        ],
        evidence=[
            CaseEvidenceRead(
                id=item.id,
                display_name=item.display_name,
                content_type=item.content_type,
                size_bytes=item.size_bytes,
                created_at=item.created_at,
                comment_id=item.comment_id,
                from_requester=(
                    case.filer is not None and item.created_by == case.filer.id
                ),
            )
            for item in case.evidence
        ],
        grants=await _case_grants(guild_context.guild_id, task_id),
    )


@router.post("/{task_id}/case/take", response_model=TaskRead)
async def take_task_case(
    task_id: int,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Task:
    """Take an operations case: the caller is assigned beside whoever already
    has it, and a case still waiting to be picked up moves to the status its
    stream calls active. 404 for a task no stream opened."""
    task = await resource_access.load_child(session, Task, task_id, access="write")
    if await cases_service.take(session, task, current_user.id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TaskMessages.NOT_A_CASE
        )
    _touch_project(task.project, datetime.now(timezone.utc))
    await session.commit()
    return await _response(session, task.id)


async def _case_grants(guild_id: int, task_id: int) -> list[AccessGrantRead]:
    """The access grants asked for case ``task_id``, where this community is
    the operations community the grants' cases are in. Read on the system
    engine: grants are shared rows, and the reader of a case is not the
    approver of its grants."""
    from sqlmodel import select

    from app.db.session import SystemSessionLocal
    from app.models.platform.access_grant import AccessGrant
    from app.services.platform import access_grants as access_grants_service
    from app.services.platform.intake import configured_operations_guild_id

    if await configured_operations_guild_id() != guild_id:
        return []
    async with SystemSessionLocal() as system:
        grants = (
            await system.exec(
                select(AccessGrant)
                .where(AccessGrant.case_task_id == task_id)
                .order_by(AccessGrant.requested_at.desc(), AccessGrant.id.desc())
            )
        ).all()
        return await access_grants_service.to_read(list(grants), system_session=system)


@router.patch("/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: int,
    task_in: TaskUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    task = await resource_access.load_child(session, Task, task_id, access="write")
    previous_type = task.task_type_id
    required = await required_fields.required_of(session, guild_context, task)
    let_go = await _apply_update(
        task_in, task, task.project, session, current_user, guild_context
    )
    # A task given another type meets what that type's page requires; any
    # other edit only keeps what it held.
    if task.task_type_id != previous_type:
        await required_fields.refuse_missing(session, guild_context, task)
    else:
        await required_fields.refuse_emptied(session, required)
    await session.commit()
    # A picture taken out of the description goes once the edit has landed.
    released_images = await attachments_service.release_unshown(
        guild_context.guild_id, let_go, pasted_only=True
    )
    attachments_service.delete_blobs(guild_context.guild_id, released_images)
    return await _response(session, task.id)


async def _apply_update(
    task_in: TaskUpdate,
    task: Task,
    project: Project,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> set[str]:
    """Write ``task_in`` to ``task``, in ``project``, in the session's
    transaction: what an update commits, and what a move sends with the task.
    The uploads its description let go of, to release once it lands."""
    update_data = task_in.model_dump(exclude_unset=True)
    if update_data.get("recurrence", task.recurrence) is None:
        update_data.setdefault("recurrence_limit", None)
    try:
        validate_task_recurrence(
            rule=update_data.get("recurrence", task.recurrence),
            strategy=update_data.get("recurrence_strategy") or task.recurrence_strategy,
            limit=update_data.get("recurrence_limit", task.recurrence_limit),
            due=update_data.get("due_date", task.due_date),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=TaskMessages.INVALID_RECURRENCE_LIMIT
        ) from exc
    if "description_base" in update_data:
        await overwrites.refuse_written_over(
            session, task, "description", update_data.pop("description_base")
        )
    assignee_ids = update_data.pop("assignee_ids", None)
    adding = update_data.pop("add_assignee_ids", None)
    removing = update_data.pop("remove_assignee_ids", None)
    relative = adding is not None or removing is not None
    if relative:
        # What the task's series compares and carries; the task itself is
        # written as the change (below).
        current = [assignee.id for assignee in task.assignees]
        taken_off = set(removing or [])
        assignee_ids = [
            person
            for person in dict.fromkeys([*current, *(adding or [])])
            if person not in taken_off
        ]
    tag_ids = update_data.pop("tag_ids", None)
    update_data.pop("properties", None)
    update_data.pop("merge_properties", None)
    checklist_sent = update_data.pop("checklist", None) is not None
    picked_in = update_data.pop("tz", None)
    scope = update_data.pop("scope", None)
    parent_sent = "parent_task_id" in update_data
    parent_task_id = update_data.pop("parent_task_id", None)
    before = (
        await task_series.values_of(session, task)
        if task.recurrence or task.series_id
        else None
    )
    previous_start = task.due_date or task.start_date
    previous_repeat = (task.recurrence, task.recurrence_shift, task.recurrence_strategy)
    previous_description = task.description
    previous_status_category = task.task_status.category if task.task_status else None
    new_status_id = update_data.pop("task_status_id", None)
    status_category = update_data.pop("status_category", None)
    new_type_id = update_data.pop("task_type_id", None)
    if new_type_id is not None and new_type_id != task.task_type_id:
        task.task_type_id = await task_creation_service.resolve_type(
            session, project_id=task.project_id, task_type_id=new_type_id
        )

    if (
        new_status_id is None
        and status_category is not None
        and status_category != previous_status_category
    ):
        landing = task_statuses_service.first_by_category_preference(
            await task_statuses_service.list_statuses(session, task.project_id),
            task_statuses_service.CATEGORY_FALLBACK[status_category],
        )
        if landing is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.STATUS_NOT_FOUND,
            )
        new_status_id = landing.id

    if new_status_id is not None and new_status_id != task.task_status_id:
        selected_status = await task_statuses_service.get_project_status(
            session,
            status_id=new_status_id,
            project_id=task.project_id,
        )
        if selected_status is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.STATUS_NOT_FOUND,
            )
        task.task_status_id = selected_status.id  # ty: ignore[invalid-assignment] — persisted row, id is set
        task.task_status = selected_status
        await column_limits.refuse_full_columns(
            session, guild_context, task.project_id, [task]
        )

    for field, value in update_data.items():
        if field == "recurrence" or (field == "recurrence_strategy" and value is None):
            continue
        setattr(task, field, value)
    task_series.repeat_edited(
        task,
        update_data.get("recurrence", ...),
        previous_start=previous_start,
        tz=picked_in,
        scope=scope,
    )
    if {"recurrence", "recurrence_limit", "due_date"}.intersection(update_data):
        try:
            await task_series.reschedule_hourly(
                session,
                task,
                user_timezone=current_user.timezone
                if current_user is not None
                else None,
                due_sent="due_date" in update_data,
                rule_changed=bool(
                    {"recurrence", "recurrence_limit"}.intersection(update_data)
                ),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=TaskMessages.INVALID_RECURRENCE_LIMIT
            ) from exc
    if checklist_sent:
        task.checklist = checklist_service.normalize(
            task_in.checklist or [], existing=task.checklist
        )
    series: list[Task] = []
    if before is not None:
        after, moved = task_series.edited(
            task, before, scope=scope, assignee_ids=assignee_ids, tag_ids=tag_ids
        )
    start = task.due_date or task.start_date
    if previous_repeat != (
        task.recurrence,
        task.recurrence_shift,
        task.recurrence_strategy,
    ) or (start != previous_start and scope != "this"):
        task.recurrence_anchor, task.recurrence_anchor_count = (
            task_series.anchor_from_dates(task)
        )
    if before is not None:
        if scope == "all":
            series = await _writable_series(session, task, current_user, guild_context)
    now = datetime.now(timezone.utc)
    task.updated_at = now
    sync_completed_at(
        task, task.task_status.category if task.task_status else None, now=now
    )

    new_assignee_ids: list[int] = []
    if relative:
        # Who this request put on the task, rather than whoever is on it now
        # and wasn't when it was read: another change may have added them.
        new_assignee_ids = await task_creation_service.change_task_assignees(
            session,
            task,
            add=adding or [],
            remove=removing or [],
            project=project,
        )
    elif assignee_ids is not None:
        existing_assignee_ids = {assignee.id for assignee in task.assignees}
        await task_creation_service.set_task_assignees(
            session, task, assignee_ids, project=project
        )
        new_assignee_ids = [
            assignee.id
            for assignee in task.assignees
            if assignee.id not in existing_assignee_ids
        ]

    if new_assignee_ids:
        assigned_by = await notifications_service.author_of(
            session, guild_context, current_user
        )
        await notifications_service.notify_assigned(
            session,
            task,
            new_assignee_ids,
            assigned_by=assigned_by,
            project_name=project.name,
        )

    # Replace tags/properties when the client sent them (PATCH semantics:
    # absent/None = leave unchanged; a list = replace-all). Both services
    # mutate the session without committing; roll back on validation errors.
    try:
        if tag_ids is not None:
            await tags_service.set_entity_tags(
                session,
                tags_service.TAG_LINKS["task"],
                guild_id=guild_context.guild_id,
                entity_id=task.id,
                tag_ids=tag_ids,
            )
        await metadata_service.write_on_update(
            session, task, task_in.properties, merge=task_in.merge_properties
        )
        if parent_sent:
            await task_hierarchy.set_parent(
                session, task, parent_task_id, user_id=guild_context.user_id
            )
    except (HTTPException, CodedError):
        await session.rollback()
        raise
    if series:
        await task_series.apply_to_others(
            session,
            series,
            after,
            moved,
            now=now,
            author_id=current_user.id if current_user is not None else None,
        )
    # Once the task has everything this edit gives it, so a completion's next
    # task is copied from what was saved.
    await task_series.advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=previous_status_category,
        now=now,
        # An installed plug-in has no zone of its own; a rolling recurrence it
        # completes counts days in UTC.
        user_timezone=current_user.timezone if current_user is not None else None,
    )

    let_go: set[str] = set()
    if task.description != previous_description:
        await descriptions_service.description_saved(
            session,
            task,
            previous=previous_description,
            author=current_user,
        )
        # An installed plug-in does not manage the community's uploads; a picture
        # its edit took out of the description stays for a person to clear.
        if current_user is not None:
            let_go = attachments_service.upload_urls_in_markdown(
                previous_description
            ) - attachments_service.upload_urls_in_markdown(task.description)
    await attachments_service.claim_uploads(session, task)
    _touch_project(project, now)
    return let_go


@router.post("/{task_id}/move", response_model=TaskRead)
async def move_task(
    task_id: int,
    move_in: TaskMoveRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    task = await resource_access.load_child(session, Task, task_id, access="write")
    if task.project_id == move_in.target_project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TaskMessages.ALREADY_IN_PROJECT,
        )

    target_project = await resource_access.load_authorized(
        session,
        _GOVERNING,
        move_in.target_project_id,
        current_user,
        guild_context,
        access="write",
    )
    if target_project.is_template:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TaskMessages.CANNOT_MOVE_TO_TEMPLATE,
        )
    await resource_access.require_may_move(session, task, target_project)

    default_status = await task_statuses_service.get_default_status(
        session, target_project.id
    )
    now = datetime.now(timezone.utc)
    source_project = task.project
    # Its project's metadata goes onto the destination's of the same name and
    # type, and the rest is dropped.
    carried = await metadata_service.lift_project_values(
        session, task, target_project.id
    )
    task.project_id = target_project.id
    task.task_type_id = await task_types_service.type_for_move(
        session, task.task_type_id, target_project.id
    )
    task.task_status_id = default_status.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    task.task_status = default_status
    task.position = 0
    task.updated_at = now
    sync_completed_at(task, default_status.category, now=now)
    session.add(task)
    await column_limits.refuse_full_columns(
        session, guild_context, target_project.id, [task]
    )

    # If the move crosses initiative boundaries, drop property values —
    # their definitions belong to the old initiative and can't resolve in
    # the new one.
    if source_project.initiative_id != target_project.initiative_id:
        await metadata_service.drop_values(session, "task", [task.id], moved=True)
    await session.flush()
    session.add_all(carried)
    # Only those who can open the destination stay assigned.
    await task_creation_service.set_task_assignees(
        session,
        task,
        [assignee.id for assignee in task.assignees],
        project=target_project,
        carried=True,
    )
    # The files the task and its conversation show are kept for the
    # destination's initiative.
    comments = await session.exec(select(Comment).where(Comment.task_id == task.id))
    await attachments_service.claim_uploads(
        session, task, *comments.all(), carried=True
    )
    # What the move is sent with is written once the task is there, and then
    # the task meets what its page in the destination requires.
    let_go = (
        await _apply_update(
            move_in.changes, task, target_project, session, current_user, guild_context
        )
        if move_in.changes is not None
        else set()
    )
    await required_fields.refuse_missing(session, guild_context, task)

    _touch_project(source_project, now)
    _touch_project(target_project, now)
    await session.commit()
    released_images = await attachments_service.release_unshown(
        guild_context.guild_id, let_go, pasted_only=True
    )
    attachments_service.delete_blobs(guild_context.guild_id, released_images)
    return await _response(session, task.id)


@router.post(
    "/{task_id}/duplicate", response_model=TaskRead, status_code=status.HTTP_201_CREATED
)
async def duplicate_task(
    task_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    """Copy the task beside itself, at the end of its project, as
    "<title> (Copy)", with its assignees, tags, links and properties; its
    checklist starts unticked."""
    task = await resource_access.load_child(session, Task, task_id, access="write")
    # The copy stays in the project, whose sharing is already committed, so
    # who it may name is asked of the copy's own assignees alone.
    keep = await named_people.readers(
        session,
        named_people.Governing.of(Tool.project, task.project),
        {assignee.id for assignee in task.assignees},
    )
    (copy,) = await task_creation_service.copy_tasks(
        session, [task], task.project, assignees=keep
    )
    await column_limits.refuse_full_columns(
        session, guild_context, task.project_id, [copy]
    )
    _touch_project(task.project, datetime.now(timezone.utc))
    await session.commit()
    return await _response(session, copy.id)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    scope: Optional[OccurrenceScope] = Query(default=None),
) -> None:
    """Trash the task. For a repeating one, ``this`` skips it so the series
    goes on (trashing it when the series has no more), ``following`` (the
    default) trashes it and so ends the repeat, and ``all`` trashes every
    other task of the series too."""
    task = await resource_access.load_child(session, Task, task_id, access="write")
    project = task.project
    now = datetime.now(timezone.utc)
    skipped = (
        scope == "this"
        and bool(task.recurrence)
        and await task_series.skip(
            session, task, now=now, user_timezone=current_user.timezone
        )
    )
    if not skipped:
        series = (
            await _writable_series(session, task, current_user, guild_context)
            if scope == "all"
            else []
        )
        for doomed in [task, *series]:
            await trash(session, doomed, deleted_by_user_id=current_user.id)
    _touch_project(project, now)
    await session.commit()


@router.post("/{task_id}/skip", response_model=TaskRead)
async def skip_task(
    task_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    """Move a repeating task on to its next occurrence without completing it."""
    task = await resource_access.load_child(session, Task, task_id, access="write")
    if not task.recurrence:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=TaskMessages.NOT_REPEATING,
        )
    now = datetime.now(timezone.utc)
    if not await task_series.skip(
        session,
        task,
        now=now,
        # An installed plug-in has no zone of its own; a rolling repeat it skips
        # counts days in UTC.
        user_timezone=current_user.timezone if current_user is not None else None,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=TaskMessages.NO_LATER_OCCURRENCE,
        )
    _touch_project(task.project, now)
    await session.commit()
    return await _response(session, task.id)


@router.post("/reorder", response_model=List[TaskRead])
async def reorder_tasks(
    reorder_in: TaskReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Sequence[Task]:
    if not reorder_in.items:
        return []

    project = await resource_access.load_authorized(
        session,
        _GOVERNING,
        reorder_in.project_id,
        current_user,
        guild_context,
        access="write",
    )

    task_ids = [item.id for item in reorder_in.items]
    tasks_stmt = (
        select(Task)
        .where(Task.id.in_(tuple(task_ids)))
        .options(selectinload(Task.assignees), selectinload(Task.task_status))
    )
    tasks_result = await session.exec(tasks_stmt)
    tasks = tasks_result.all()
    task_map = {task.id: task for task in tasks}

    missing_ids = set(task_ids) - set(task_map.keys())
    if missing_ids:
        raise KINDS["task"].not_found()

    now = datetime.now(timezone.utc)
    status_cache: dict[int, TaskStatus] = {}
    entering = [
        task_map[item.id]
        for item in reorder_in.items
        if item.task_status_id != task_map[item.id].task_status_id
    ]
    for item in reorder_in.items:
        task = task_map[item.id]
        previous_status_category = (
            task.task_status.category if task.task_status else None
        )
        if task.project_id != reorder_in.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskMessages.PROJECT_MISMATCH,
            )

        if item.task_status_id != task.task_status_id:
            status_obj = status_cache.get(item.task_status_id)
            if status_obj is None:
                status_obj = await task_statuses_service.get_project_status(
                    session,
                    status_id=item.task_status_id,
                    project_id=reorder_in.project_id,
                )
                if status_obj is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=TaskMessages.STATUS_NOT_FOUND,
                    )
                status_cache[item.task_status_id] = status_obj
            task.task_status_id = status_obj.id  # ty: ignore[invalid-assignment] — persisted row, id is set
            task.task_status = status_obj

        task.position = item.position
        task.updated_at = now
        sync_completed_at(
            task, task.task_status.category if task.task_status else None, now=now
        )
        session.add(task)
        await task_series.advance_recurrence_if_needed(
            session,
            task,
            previous_status_category=previous_status_category,
            now=now,
            user_timezone=current_user.timezone,
        )

    await column_limits.refuse_full_columns(
        session, guild_context, reorder_in.project_id, entering
    )

    # Renumber the project's tasks if any moved task collided with a neighbor;
    # collects ids the rebalance touched so they're returned to the client
    # alongside the explicitly-moved tasks (rebalanced tasks keep updated_at).
    moved_positions = {item.id: item.position for item in reorder_in.items}
    rebalanced_ids = set(
        await _rebalance_if_needed(session, reorder_in.project_id, moved_positions)
    )

    _touch_project(project, now)
    await session.commit()
    return await task_queries.load_tasks(session, list(set(task_ids) | rebalanced_ids))


class ArchiveDoneResponse(BaseModel):
    archived_count: int


@router.post("/archive-done", response_model=ArchiveDoneResponse)
async def archive_done_tasks(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    project_id: int = Query(..., description="Project to archive done tasks from"),
    task_status_id: Optional[int] = Query(
        default=None, description="Specific done status to archive (optional)"
    ),
) -> ArchiveDoneResponse:
    """Archive every live task in a 'done' status of a project, as archiving
    each one would, under one stamp."""
    project = await resource_access.load_authorized(
        session, _GOVERNING, project_id, current_user, guild_context, access="write"
    )
    statement = (
        select(Task)
        .join(Task.task_status)
        .where(
            Task.project_id == project_id,
            Task.archived_at.is_(None),
            TaskStatus.category == TaskStatusCategory.done,
        )
    )
    if task_status_id is not None:
        statement = statement.where(Task.task_status_id == task_status_id)
    tasks = (await session.exec(statement)).all()
    if not tasks:
        return ArchiveDoneResponse(archived_count=0)

    _touch_project(project, await archive_service.archive_entities(session, tasks))
    await session.commit()
    return ArchiveDoneResponse(archived_count=len(tasks))


@router.patch(
    "/{task_id}/checklist/{item_id}",
    response_model=List[ChecklistItem],
)
async def toggle_checklist_item(
    task_id: int,
    item_id: str,
    toggle_in: ChecklistItemToggle,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> List[ChecklistItem]:
    """Tick or untick one checklist item.

    Adding, renaming, reordering and deleting go through ``PATCH /tasks/{id}``
    with the whole list. A tick gets its own route because it is the write
    several people make to the same task at once: it names one item and rewrites
    only that item, so two ticks on different items both land.
    """
    task = await resource_access.load_child(session, Task, task_id, access="write")
    now = datetime.now(timezone.utc)
    result = await session.exec(
        checklist_service.toggle_statement(),
        params=checklist_service.toggle_params(
            task_id=task.id,
            item_id=item_id,
            done=toggle_in.done,
            now=now,
        ),
    )
    row = result.one_or_none()
    if row is None:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ChecklistMessages.ITEM_NOT_FOUND,
        )

    _touch_project(task.project, now)
    await session.commit()
    # The statement wrote behind the ORM's back, so the loaded row is stale.
    session.expire(task)
    return checklist_service.read(row[0])


@router.post(
    "/{task_id}/checklist/{item_id}/promote",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
)
async def promote_checklist_item(
    task_id: int,
    item_id: str,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> Task:
    """Make one checklist item a task of its own, part of this one.

    The new task is in the same project, titled with the item's words (in a
    done column if the item was ticked), and the item leaves the checklist:
    the task is where the work is tracked from now on. A line that names
    people or things, or runs past a title's length, keeps its whole words in
    the new task's description.
    """
    parent = await resource_access.load_child(session, Task, task_id, access="write")
    required = await required_fields.required_of(session, guild_context, parent)
    item = next(
        (each for each in parent.checklist or [] if each.get("id") == item_id), None
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ChecklistMessages.ITEM_NOT_FOUND,
        )
    line = str(item.get("text", ""))
    title, shortened = task_hierarchy.title_from_line(line)
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ChecklistMessages.ITEM_UNTITLED,
        )
    landing = None
    if item.get("done"):
        landing = task_statuses_service.first_by_category_preference(
            await task_statuses_service.list_statuses(session, parent.project_id),
            task_statuses_service.CATEGORY_FALLBACK[TaskStatusCategory.done],
        )
    task_in = TaskCreate(
        title=title,
        description=line if shortened else None,
        project_id=parent.project_id,
        task_status_id=landing.id if landing else None,
        parent_task_id=parent.id,
    )
    task = await _insert_task(task_in, session, current_user, guild_context)

    now = datetime.now(timezone.utc)
    removed = await session.exec(
        checklist_service.remove_statement(),
        params=checklist_service.remove_params(task_id=parent.id, item=item, now=now),
    )
    if removed.one_or_none() is None:
        # Ticked, reworded or removed since it was read: the task made from it
        # would say something the list no longer does.
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ChecklistMessages.ITEM_CHANGED,
        )
    # The statement wrote behind the ORM's back, so the loaded row is stale.
    await session.refresh(parent, ["checklist"])
    await required_fields.refuse_emptied(session, required)
    await session.commit()
    session.expire(parent)
    return await _response(session, task.id)


# AI Generation endpoints
@router.post("/{task_id}/ai/checklist", response_model=GenerateChecklistResponse)
async def generate_task_checklist(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> GenerateChecklistResponse:
    """Suggest checklist steps for a task."""
    task = await resource_access.load_child(session, Task, task_id, access="write")
    project = task.project

    await ai_generation_service.record_request(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        purpose="checklist",
        target_type="task",
        target_id=task.id,
        initiative_id=project.initiative_id,
    )

    items, context = await ai_generation_service.generate_checklist(
        session, current_user, guild_context.guild_id, task
    )
    return GenerateChecklistResponse(
        items=items,
        comments_read=context.comments_read,
        comments_total=context.comments_total,
    )


@router.post("/{task_id}/ai/description", response_model=GenerateDescriptionResponse)
async def generate_task_description(
    task_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> GenerateDescriptionResponse:
    """Generate AI-powered description for a task."""
    task = await resource_access.load_child(session, Task, task_id, access="write")
    project = task.project

    await ai_generation_service.record_request(
        session,
        user=current_user,
        guild_id=guild_context.guild_id,
        purpose="description",
        target_type="task",
        target_id=task.id,
        initiative_id=project.initiative_id,
    )

    description, context = await ai_generation_service.generate_description(
        session, current_user, guild_context.guild_id, task
    )
    return GenerateDescriptionResponse(
        description=description,
        comments_read=context.comments_read,
        comments_total=context.comments_total,
    )
