from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import delete, select, update

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContextDep,
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    plugin_scope,
)
from app.core.messages import InitiativeMessages, TaskStatusMessages
from app.db import gucs
from app.db.guild_standing import InstallContext
from app.db.session import raise_flag
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.tenant.task_status import (
    InitiativeTaskStatusRead,
    TaskStatusCreate,
    TaskStatusDeleteRequest,
    TaskStatusRead,
    TaskStatusReorderRequest,
    TaskStatusUpdate,
)
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import task_completion, task_series
from app.services.tenant import task_statuses as task_statuses_service

router = APIRouter(
    prefix="/projects/{project_id}/task-statuses",
    tags=["task-statuses"],
    route_class=ActorRoute,
)
# Status columns belong to a project, but a caller working at initiative level
# (a board filter, an automation choosing a target column) wants the set across
# the whole initiative rather than one delegated request per project.
initiative_router = APIRouter(
    prefix="/initiatives/{initiative_id}/task-statuses",
    tags=["task-statuses"],
    route_class=ActorRoute,
)

#: The routes an installed plug-in may call. A status column is its project's, so
#: it answers to the projects scopes.
ProjectsRead = Annotated[ActorContext, Depends(plugin_scope("projects:read"))]


def _sorted(statuses: list[TaskStatus]) -> list[TaskStatus]:
    return sorted(statuses, key=lambda status: (status.position, status.id or 0))


def _resequence(statuses: list[TaskStatus]) -> None:
    for index, item in enumerate(statuses):
        item.position = index


def _ensure_default(statuses: list[TaskStatus]) -> None:
    if any(status.is_default for status in statuses):
        return
    preferred = task_statuses_service.first_by_category_preference(statuses)
    if preferred is not None:
        preferred.is_default = True
        return
    if statuses:
        statuses[0].is_default = True


async def _load_status_or_404(
    session: SessionDep, project_id: int, status_id: int
) -> TaskStatus:
    stmt = select(TaskStatus).where(
        TaskStatus.project_id == project_id, TaskStatus.id == status_id
    )
    result = await session.exec(stmt)
    status_obj = result.one_or_none()
    if status_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TaskStatusMessages.NOT_FOUND
        )
    return status_obj


async def _ensure_not_only_status(
    session: SessionDep,
    *,
    project_id: int,
) -> None:
    """A board needs somewhere to put a task, so the last column stays.

    Which categories a project keeps is its own business — a team that never
    blocks on anything can drop every ``todo`` column — but a project with no
    statuses at all has nowhere to create a task.

    Takes the project row for the rest of the transaction, so two deletes
    racing on the same project take it in turn and the second counts what the
    first left rather than what it started with.
    """
    await session.exec(
        select(Project.id).where(Project.id == project_id).with_for_update()
    )
    stmt = select(func.count(TaskStatus.id)).where(TaskStatus.project_id == project_id)
    result = await session.exec(stmt)
    if (result.one() or 0) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TaskStatusMessages.CANNOT_REMOVE_LAST,
        )


async def _pick_fallback_status(
    session: SessionDep,
    *,
    project_id: int,
    excluding: TaskStatus,
) -> TaskStatus | None:
    """Where a deleted column's tasks go when the caller names no destination.

    The project's own default column, the entry column for its categories, or
    failing both the first column on the board.
    """
    statuses = [
        status_obj
        for status_obj in await task_statuses_service.list_statuses(session, project_id)
        if status_obj.id != excluding.id
    ]
    if not statuses:
        return None
    marked_default = next(
        (status_obj for status_obj in statuses if status_obj.is_default), None
    )
    if marked_default is not None:
        return marked_default
    return task_statuses_service.first_by_category_preference(statuses) or statuses[0]


@router.get("/", response_model=list[TaskStatusRead])
async def list_task_statuses(
    project_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
) -> Sequence[TaskStatus]:
    await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        current_user,
        guild_context,
    )
    return await task_statuses_service.list_statuses(session, project_id)


@router.post("/", response_model=TaskStatusRead, status_code=status.HTTP_201_CREATED)
async def create_task_status(
    project_id: int,
    status_in: TaskStatusCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TaskStatus:
    project = await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        current_user,
        guild_context,
        access="write",
    )

    statuses = await task_statuses_service.list_statuses(session, project.id)
    insert_at = status_in.position if status_in.position is not None else len(statuses)
    insert_at = max(0, min(insert_at, len(statuses)))
    default_color, default_icon = task_statuses_service.defaults_for_category(
        status_in.category
    )
    new_status = TaskStatus(
        project_id=project.id,
        name=status_in.name,
        category=status_in.category,
        is_default=status_in.is_default,
        position=insert_at,
        color=status_in.color or default_color,
        icon=status_in.icon or default_icon,
    )
    statuses.insert(insert_at, new_status)
    if status_in.is_default:
        for status_obj in statuses:
            if status_obj is not new_status:
                status_obj.is_default = False
    _resequence(statuses)
    _ensure_default(statuses)
    session.add(new_status)
    await session.commit()
    await session.refresh(new_status)
    return new_status


@router.patch("/{status_id}", response_model=TaskStatusRead)
async def update_task_status(
    project_id: int,
    status_id: int,
    status_in: TaskStatusUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TaskStatus:
    await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        current_user,
        guild_context,
        access="write",
    )

    target = await _load_status_or_404(session, project_id, status_id)
    statuses = await task_statuses_service.list_statuses(session, project_id)
    update_data = status_in.model_dump(exclude_unset=True)

    new_category = update_data.get("category")
    if new_category and new_category != target.category:
        target.category = new_category
        # Recategorising a column moves every task in it across the done
        # boundary without any task row being written, so realign their
        # completion timestamps here. The archived and trashed tasks in the
        # column cross with it: the column is what changed, not them.
        await raise_flag(session, gucs.RESTRUCTURING)
        await task_completion.resync_status_tasks(
            session,
            status_id=target.id,
            category=new_category,
            now=datetime.now(UTC),
        )
    if "name" in update_data and update_data["name"] is not None:
        target.name = update_data["name"]
    if update_data.get("color") is not None:
        target.color = update_data["color"]
    if update_data.get("icon") is not None:
        target.icon = update_data["icon"]

    if update_data.get("is_default"):
        for status_obj in statuses:
            status_obj.is_default = status_obj.id == target.id
    elif update_data.get("is_default") is False:
        target.is_default = False

    if update_data.get("position") is not None:
        current_list = [status for status in statuses if status.id != target.id]
        insert_at = max(0, min(update_data["position"], len(current_list)))
        current_list.insert(insert_at, target)
        _resequence(current_list)
        _ensure_default(current_list)
    else:
        _resequence(statuses)
        _ensure_default(statuses)
    await session.commit()
    await session.refresh(target)
    return target


@router.post("/reorder", response_model=list[TaskStatusRead])
async def reorder_task_statuses(
    project_id: int,
    reorder_in: TaskStatusReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Sequence[TaskStatus]:
    project = await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        current_user,
        guild_context,
        access="write",
    )

    if not reorder_in.items:
        return await task_statuses_service.list_statuses(session, project.id)

    statuses = await task_statuses_service.list_statuses(session, project.id)
    status_map = {status.id: status for status in statuses}
    seen: set[int] = set()
    ordered: list[TaskStatus] = []
    for item in sorted(reorder_in.items, key=lambda entry: entry.position):
        if item.id in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskStatusMessages.DUPLICATE_ID,
            )
        status_obj = status_map.get(item.id)
        if status_obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=TaskStatusMessages.NOT_FOUND,
            )
        ordered.append(status_obj)
        seen.add(item.id)
    remaining = [status for status in statuses if status.id not in seen]
    combined = ordered + remaining
    _resequence(combined)
    _ensure_default(combined)
    await session.commit()
    return await task_statuses_service.list_statuses(session, project.id)


@router.delete("/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_status(
    project_id: int,
    status_id: int,
    delete_in: TaskStatusDeleteRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        current_user,
        guild_context,
        access="write",
    )

    target = await _load_status_or_404(session, project_id, status_id)
    await _ensure_not_only_status(session, project_id=project_id)

    # Every task in the column has to land somewhere, including the ones in
    # the trash: the active-row filter would hide those from this count, and
    # the foreign key would then refuse the delete on their behalf.
    stmt = (
        select(func.count(Task.id))
        .where(Task.task_status_id == target.id)
        .execution_options(include_deleted=True)
    )
    result = await session.exec(stmt)
    task_count = result.one() or 0

    if task_count:
        fallback_obj: TaskStatus | None = None
        if delete_in.fallback_status_id is not None:
            if delete_in.fallback_status_id == target.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=TaskStatusMessages.FALLBACK_MUST_DIFFER,
                )
            fallback_obj = await _load_status_or_404(
                session, project_id, delete_in.fallback_status_id
            )
        else:
            # Naming a destination is a courtesy, not a requirement: a column
            # nobody can empty is a column nobody can delete, and a project
            # whose only other statuses sit in other categories used to be
            # exactly that. Fall back to where the project puts a new task.
            fallback_obj = await _pick_fallback_status(
                session, project_id=project_id, excluding=target
            )
        if fallback_obj is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskStatusMessages.FALLBACK_REQUIRED,
            )

        # Recurrence opens the successor in the project's entry column. If the
        # column being retired is that entry, choose its replacement before any
        # successor is made so it never points back at the row being deleted.
        if target.is_default:
            target.is_default = False
            session.add(target)
            replacement_statuses = [
                status_obj
                for status_obj in await task_statuses_service.list_statuses(
                    session, project_id
                )
                if status_obj.id != target.id
            ]
            _ensure_default(replacement_statuses)
            await session.flush()

        # Archived and trashed tasks move with the live ones — the column is
        # going away, not them, and they keep their stamps — but a finished
        # recurring task is not started over on the way past Done.
        recurring_tasks: list[Task] = []
        if (
            target.category != TaskStatusCategory.done
            and fallback_obj.category == TaskStatusCategory.done
        ):
            recurring_tasks = list(
                await session.exec(
                    select(Task)
                    .where(
                        Task.task_status_id == target.id,
                        Task.recurrence.is_not(None),
                        Task.due_date.is_not(None),
                        Task.archived_at.is_(None),
                        Task.deleted_at.is_(None),
                    )
                    .options(
                        selectinload(Task.assignees),
                        selectinload(Task.task_status),
                    )
                )
            )
        await raise_flag(session, gucs.RESTRUCTURING)
        await session.exec(
            update(Task)
            .where(Task.task_status_id == target.id)
            .values(task_status_id=fallback_obj.id)
        )
        # The destination may sit on the other side of the done boundary from
        # the column being emptied, so realign the tasks that just landed in it.
        now = datetime.now(UTC)
        await task_completion.resync_status_tasks(
            session,
            status_id=fallback_obj.id,
            category=fallback_obj.category,
            now=now,
        )
        for task in recurring_tasks:
            task.task_status_id = fallback_obj.id  # ty: ignore[invalid-assignment] — persisted row, id is set
            task.task_status = fallback_obj
            await task_series.advance_recurrence_if_needed(
                session,
                task,
                previous_status_category=target.category,
                now=now,
                user_timezone=current_user.timezone,
            )

    await session.exec(delete(TaskStatus).where(TaskStatus.id == target.id))
    remaining = await task_statuses_service.list_statuses(session, project_id)
    _resequence(remaining)
    _ensure_default(remaining)
    await session.commit()


async def _require_initiative_reader(
    session: RLSSessionDep,
    initiative_id: int,
    current_user: User | None,
    guild_context: ActorContext,
) -> None:
    """Resolve the initiative in this guild and confirm the caller is in it.

    An installed plug-in is in the initiatives it is placed in; any other is not
    found, as an initiative it cannot reach reads everywhere else.
    """
    if (
        isinstance(guild_context, InstallContext)
        and initiative_id not in guild_context.member_initiatives
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    stmt = select(Initiative.id).where(
        Initiative.id == initiative_id,
    )
    if (await session.exec(stmt)).first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND
        )
    if current_user is None:
        return
    # A guild admin reads every initiative in their guild, and a PAM grantee
    # reads the guild for the life of the grant; neither holds a membership row.
    if guild_context.is_admin or guild_context.is_pam:
        return
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=current_user.id,
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_A_MEMBER,
        )


@initiative_router.get("/", response_model=list[InitiativeTaskStatusRead])
async def list_initiative_task_statuses(
    initiative_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
) -> list[InitiativeTaskStatusRead]:
    """The distinct status columns across the initiative's readable projects.

    One entry per ``(name, category)``, carrying how many of the caller's
    readable projects define it and how many such projects there are.
    """
    await _require_initiative_reader(
        session, initiative_id, current_user, guild_context
    )
    return await task_statuses_service.list_initiative_statuses(
        session,
        initiative_id=initiative_id,
        user_id=guild_context.user_id,
        guild_id=guild_context.guild_id,
    )
