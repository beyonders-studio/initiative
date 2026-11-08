"""A project's task types: what kinds of task it holds, each with its own page.

Read with the project; changed by whoever may write its tasks, as its status
columns are. A project always keeps one type, and exactly one is its default.
Deleting a type moves its tasks to another first, the trashed and archived ones
included, and takes its page with it.
"""

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import col, select, update

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
    plugin_scope,
)
from app.core.errors import CodedError
from app.core.messages import TaskTypeMessages
from app.core.task_type_gallery import GALLERY_BY_KEY
from app.core.task_types import MAX_TASK_TYPES
from app.core.tools import Tool
from app.db import gucs
from app.db.session import raise_flag
from app.models.platform.user import User
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskType
from app.models.tenant.tool_layout import ToolLayout
from app.schemas.tenant.task_type import (
    TaskTypeCopyRequest,
    TaskTypeCreate,
    TaskTypeCreated,
    TaskTypeDeleteRequest,
    TaskTypeGalleryGroup,
    TaskTypeRead,
    TaskTypeReorderRequest,
    TaskTypeUpdate,
)
from app.services.tenant import task_types as task_types_service
from app.services.tenant import tool_layouts as tool_layouts_service

router = APIRouter(
    prefix="/projects/{project_id}/task-types",
    tags=["task-types"],
    route_class=ActorRoute,
)

#: A type is its project's, so it answers to the projects scopes.
ProjectsRead = Annotated[ActorContext, Depends(plugin_scope("projects:read"))]
CurrentUser = Annotated[User, Depends(get_current_active_user)]


async def _writable_project(
    session: RLSSessionDep,
    project_id: int,
    user: User,
    context: GuildContextDep,
) -> Project:
    """The project, once the caller may write its tasks; held for the rest of
    the transaction, so changes to one project's types take turns."""
    project = await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        user,
        context,
        access="write",
    )
    await session.exec(
        select(Project.id).where(Project.id == project_id).with_for_update()
    )
    return project


async def _load_or_404(
    session: RLSSessionDep, project_id: int, type_id: int
) -> TaskType:
    found = await task_types_service.get_project_type(session, type_id, project_id)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TaskTypeMessages.NOT_FOUND
        )
    return found


async def _require_free_name(
    session: RLSSessionDep, project_id: int, name: str, excluding: int | None = None
) -> None:
    if await task_types_service.name_taken(
        session, project_id, name, excluding=excluding
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=TaskTypeMessages.NAME_TAKEN
        )


@router.get("/", response_model=list[TaskTypeRead])
async def list_task_types(
    project_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
) -> Sequence[TaskType]:
    await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        current_user,
        guild_context,
    )
    return await task_types_service.list_types(session, project_id)


@router.get("/gallery", response_model=list[TaskTypeGalleryGroup])
async def list_task_type_gallery(
    project_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
) -> list[TaskTypeGalleryGroup]:
    """The ready-made types the project can add, grouped by what they are for,
    in the reader's language."""
    await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        project_id,
        current_user,
        guild_context,
    )
    return task_types_service.gallery(getattr(current_user, "locale", None) or "en")


@router.post("/", response_model=TaskTypeCreated, status_code=status.HTTP_201_CREATED)
async def create_task_type(
    project_id: int,
    type_in: TaskTypeCreate,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> TaskTypeCreated:
    """Add a type, at the end unless a position is given. Started from another
    of the project's types, it takes that type's shape, colour, icon and
    starting values unless it names its own, and a copy of its page. Started
    from the gallery, it takes the gallery type's, and its fields: the
    initiative's properties of those names, made where it has none, which its
    page is then given (``field_ids``)."""
    project = await _writable_project(session, project_id, current_user, guild_context)
    types = await task_types_service.list_types(session, project.id)
    if len(types) >= MAX_TASK_TYPES:
        raise CodedError(
            TaskTypeMessages.LIMIT_REACHED, params={"max": str(MAX_TASK_TYPES)}
        )
    name = type_in.name.strip()
    await _require_free_name(session, project.id, name)
    source = (
        await _load_or_404(session, project.id, type_in.start_from_type_id)
        if type_in.start_from_type_id is not None
        else None
    )
    entry = GALLERY_BY_KEY.get(type_in.gallery_key or "")
    locale = current_user.locale or "en"
    starting = type_in.starting_values
    if "starting_values" not in type_in.model_fields_set:
        if source is not None:
            starting = task_types_service.starting_values_of(source)
        elif entry is not None:
            starting = task_types_service.gallery_starting_values(entry, locale)
    insert_at = max(
        0,
        min(
            type_in.position if type_in.position is not None else len(types), len(types)
        ),
    )
    look = source or entry
    created = TaskType(
        project_id=project.id,
        name=name,
        is_default=type_in.is_default,
        color=type_in.color or (look.color if look else "#94A3B8"),
        icon=type_in.icon or (look.icon if look else "square-check"),
        layout_preset=type_in.layout_preset
        or (source.layout_preset if source else entry.shape if entry else "plain"),
        starting_values=task_types_service.stored_starting_values(starting),
    )
    types.insert(insert_at, created)
    if created.is_default:
        for other in types:
            other.is_default = other is created
    task_types_service.resequence(types)
    task_types_service.ensure_one_default(types)
    session.add(created)
    await session.flush()
    if source is not None:
        page = (
            await session.exec(
                select(ToolLayout).where(ToolLayout.task_type_id == source.id)
            )
        ).one_or_none()
        if page is not None:
            session.add(
                ToolLayout(
                    initiative_id=page.initiative_id,
                    tool=Tool.project.value,
                    tool_id=project.id,
                    kind=page.kind,
                    task_type_id=created.id,
                    definition=page.definition,
                )
            )
    field_ids = (
        await task_types_service.gallery_fields(
            session, project.initiative_id, entry, locale=locale
        )
        if entry is not None
        else []
    )
    await session.commit()
    await session.refresh(created)
    return TaskTypeCreated.model_validate(
        {**TaskTypeRead.model_validate(created).model_dump(), "field_ids": field_ids}
    )


@router.post("/copy", response_model=list[TaskTypeRead])
async def copy_task_types(
    project_id: int,
    copy_in: TaskTypeCopyRequest,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> Sequence[TaskType]:
    """Copy types from another project the caller can read: each with its
    look, its starting values and its page, after this project's own. One
    whose name this project has is left out, and so is any past the limit;
    the response is the copies made. A page from another initiative leaves out
    the properties it placed, which are that initiative's."""
    project = await _writable_project(session, project_id, current_user, guild_context)
    source_project = await resource_access.load_authorized(
        session,
        resource_access.governing_tool("tasks"),
        copy_in.source_project_id,
        current_user,
        guild_context,
    )
    sources = await task_types_service.list_types(session, source_project.id)
    if copy_in.type_ids is not None:
        by_id = {t.id: t for t in sources}
        if any(type_id not in by_id for type_id in copy_in.type_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=TaskTypeMessages.NOT_FOUND,
            )
        wanted = set(copy_in.type_ids)
        sources = [t for t in sources if t.id in wanted]
    copies = await task_types_service.copy_types(
        session, sources, target_project_id=project.id
    )
    same_initiative = source_project.initiative_id == project.initiative_id
    pages = (
        await session.exec(
            select(ToolLayout).where(col(ToolLayout.task_type_id).in_(list(copies)))
        )
    ).all()
    for page in pages:
        assert page.task_type_id is not None
        session.add(
            ToolLayout(
                initiative_id=project.initiative_id,
                tool=Tool.project.value,
                tool_id=project.id,
                kind=page.kind,
                task_type_id=copies[page.task_type_id].id,
                definition=tool_layouts_service.remapped_definition(
                    page.definition,
                    tool_layouts_service.Remap(
                        statuses=lambda _id: None,
                        properties=None if same_initiative else lambda _id: None,
                    ),
                ),
            )
        )
    await session.commit()
    for copy in copies.values():
        await session.refresh(copy)
    return list(copies.values())


@router.patch("/{type_id}", response_model=TaskTypeRead)
async def update_task_type(
    project_id: int,
    type_id: int,
    type_in: TaskTypeUpdate,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> TaskType:
    await _writable_project(session, project_id, current_user, guild_context)
    target = await _load_or_404(session, project_id, type_id)
    types = await task_types_service.list_types(session, project_id)
    changes = type_in.model_dump(exclude_unset=True)
    if changes.get("name") is not None:
        name = changes["name"].strip()
        await _require_free_name(session, project_id, name, excluding=target.id)
        target.name = name
    for field in ("color", "icon", "layout_preset"):
        if changes.get(field) is not None:
            setattr(target, field, changes[field])
    if "starting_values" in changes:
        target.starting_values = task_types_service.stored_starting_values(
            type_in.starting_values
        )
    if changes.get("is_default"):
        for other in types:
            other.is_default = other.id == target.id
    elif changes.get("is_default") is False:
        target.is_default = False
    if changes.get("position") is not None:
        types = [other for other in types if other.id != target.id]
        types.insert(max(0, min(changes["position"], len(types))), target)
    task_types_service.resequence(types)
    task_types_service.ensure_one_default(types)
    await session.commit()
    await session.refresh(target)
    return target


@router.post("/reorder", response_model=list[TaskTypeRead])
async def reorder_task_types(
    project_id: int,
    reorder_in: TaskTypeReorderRequest,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> Sequence[TaskType]:
    await _writable_project(session, project_id, current_user, guild_context)
    types = await task_types_service.list_types(session, project_id)
    by_id = {task_type.id: task_type for task_type in types}
    ordered: list[TaskType] = []
    for item in sorted(reorder_in.items, key=lambda entry: entry.position):
        if any(task_type.id == item.id for task_type in ordered):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=TaskTypeMessages.DUPLICATE_ID,
            )
        if item.id not in by_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=TaskTypeMessages.NOT_FOUND,
            )
        ordered.append(by_id[item.id])
    combined = ordered + [t for t in types if t not in ordered]
    task_types_service.resequence(combined)
    task_types_service.ensure_one_default(combined)
    await session.commit()
    return await task_types_service.list_types(session, project_id)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_type(
    project_id: int,
    type_id: int,
    delete_in: TaskTypeDeleteRequest,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Delete a type, moving its tasks to another. Its page goes with it; the
    tasks keep everything they hold, and show it as their new type does."""
    await _writable_project(session, project_id, current_user, guild_context)
    target = await _load_or_404(session, project_id, type_id)
    others = [
        task_type
        for task_type in await task_types_service.list_types(session, project_id)
        if task_type.id != target.id
    ]
    if not others:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TaskTypeMessages.CANNOT_REMOVE_LAST,
        )
    if delete_in.fallback_type_id == target.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TaskTypeMessages.FALLBACK_MUST_DIFFER,
        )
    fallback = (
        await _load_or_404(session, project_id, delete_in.fallback_type_id)
        if delete_in.fallback_type_id is not None
        else next((t for t in others if t.is_default), others[0])
    )
    # Every task of the type has to land somewhere, including the ones in the
    # trash, which the active-row filter would hide.
    held = (
        await session.exec(
            select(func.count(Task.id))
            .where(Task.task_type_id == target.id)
            .execution_options(include_deleted=True)
        )
    ).one()
    if held:
        await raise_flag(session, gucs.RESTRUCTURING)
        await session.exec(
            update(Task)
            .where(Task.task_type_id == target.id)
            .values(task_type_id=fallback.id)
            .execution_options(include_deleted=True)
        )
    if target.is_default:
        fallback.is_default = True
    await session.delete(target)
    await session.flush()
    task_types_service.resequence(others)
    task_types_service.ensure_one_default(others)
    await session.commit()
