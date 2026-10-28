"""A project's task types: the ones it starts with, which is its default, and
where a task's type goes when the task moves.

Nothing here commits, so a caller can compose it into a larger transaction.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from pydantic import ValidationError
from sqlmodel import col, delete, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.core.task_type_gallery import (
    GALLERY,
    GALLERY_BY_KEY,
    GALLERY_GROUPS,
    GalleryType,
)
from app.core.task_types import DEFAULT_TASK_TYPES, MAX_TASK_TYPES
from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.models.tenant.task import TaskType
from app.schemas.tenant.task_type import (
    TaskTypeGalleryEntry,
    TaskTypeGalleryField,
    TaskTypeGalleryGroup,
    TaskTypeStartingValues,
)
from app.services.tenant.task_statuses import REPAIR_LOCALE


def default_name(key: str, locale: str) -> str:
    """One of the starting types' names, in ``locale`` (English for a
    language the app does not speak)."""
    return translate(f"taskTypes.defaults.{key}", locale, namespace="projects")


def _gallery_word(key: str, locale: str) -> str:
    return translate(f"taskTypes.gallery.{key}", locale, namespace="projects")


def starting_values_of(task_type: TaskType) -> Optional[TaskTypeStartingValues]:
    """What a new task of the type starts with, or None. A stored value this
    build no longer reads starts nothing rather than refusing the task."""
    if not task_type.starting_values:
        return None
    try:
        values = TaskTypeStartingValues.model_validate(task_type.starting_values)
    except ValidationError:
        return None
    return None if values.is_empty() else values


def stored_starting_values(
    values: Optional[TaskTypeStartingValues],
) -> Optional[dict[str, Any]]:
    """Starting values as the column holds them; None for nothing to start."""
    if values is None or values.is_empty():
        return None
    return values.model_dump(mode="json", exclude_none=True, exclude_defaults=True)


def gallery_starting_values(
    entry: GalleryType, locale: str
) -> Optional[TaskTypeStartingValues]:
    """What a gallery type starts a task with, its outline in ``locale``."""
    start = entry.start
    values = TaskTypeStartingValues(
        description=(
            _gallery_word(f"outlines.{start.outline}", locale)
            if start.outline
            else None
        ),
        priority=start.priority,
        recurrence=start.recurrence,
        recurrence_strategy=start.recurrence_strategy,
    )
    return None if values.is_empty() else values


def gallery(locale: str) -> list[TaskTypeGalleryGroup]:
    """The ready-made types, grouped, in ``locale``."""
    return [
        TaskTypeGalleryGroup(
            key=group,
            name=_gallery_word(f"groups.{group}", locale),
            entries=[
                TaskTypeGalleryEntry(
                    key=entry.key,
                    name=_gallery_word(f"types.{entry.key}.name", locale),
                    hint=_gallery_word(f"types.{entry.key}.hint", locale),
                    icon=entry.icon,
                    color=entry.color,
                    layout_preset=entry.shape,
                    fields=[
                        TaskTypeGalleryField(
                            name=_gallery_word(f"fields.{field.key}", locale),
                            type=field.type,
                        )
                        for field in entry.fields
                    ],
                    starting_values=gallery_starting_values(entry, locale),
                )
                for entry in GALLERY
                if entry.group == group
            ],
        )
        for group in GALLERY_GROUPS
    ]


async def gallery_fields(
    session: AsyncSession, initiative_id: int, entry: GalleryType, *, locale: str
) -> list[int]:
    """The initiative's properties for a gallery type's fields, in order: one
    of the same name and kind where it has one, a new one where it has none.
    A field whose name another kind of property already has is left out."""
    existing = list(
        (
            await session.exec(
                select(MetadataDefinition).where(
                    MetadataDefinition.of_initiative(initiative_id)
                )
            )
        ).all()
    )
    by_name = {definition.name.lower(): definition for definition in existing}
    position = max((d.position for d in existing), default=0.0)
    ids: list[int] = []
    for field in entry.fields:
        name = _gallery_word(f"fields.{field.key}", locale)
        found = by_name.get(name.lower())
        if found is None:
            position += 1
            found = MetadataDefinition(
                initiative_id=initiative_id,
                name=name,
                type=MetadataType(field.type),
                position=position,
            )
            session.add(found)
            await session.flush()
            by_name[name.lower()] = found
        elif found.type != MetadataType(field.type):
            continue
        assert found.id is not None
        ids.append(found.id)
    return ids


async def list_types(session: AsyncSession, project_id: int) -> list[TaskType]:
    result = await session.exec(
        select(TaskType)
        .where(TaskType.project_id == project_id)
        .order_by(col(TaskType.position).asc(), col(TaskType.id).asc())
    )
    return list(result.all())


async def ensure_default_types(
    session: AsyncSession, project_id: int, *, locale: str
) -> list[TaskType]:
    """The project's types, giving it the four it starts with if it has none,
    named in ``locale``: the language of whoever is making the project."""
    existing = await list_types(session, project_id)
    if existing:
        return existing
    created = [
        TaskType(
            project_id=project_id,
            name=default_name(spec.key, locale),
            position=position,
            is_default=position == 0,
            color=spec.color,
            icon=spec.icon,
            layout_preset=spec.shape,
            # Bug starts with an outline of a report, as the gallery's does.
            starting_values=stored_starting_values(
                gallery_starting_values(GALLERY_BY_KEY[spec.key], locale)
                if spec.key in GALLERY_BY_KEY
                else None
            ),
        )
        for position, spec in enumerate(DEFAULT_TASK_TYPES)
    ]
    session.add_all(created)
    await session.flush()
    return created


async def get_default_type(session: AsyncSession, project_id: int) -> TaskType:
    """What a new task in the project is unless it says otherwise. A project
    found with no types is given its starting ones, as it is its statuses: a
    repair, where nobody's language is known."""
    types = await ensure_default_types(session, project_id, locale=REPAIR_LOCALE)
    return next((t for t in types if t.is_default), types[0])


async def get_project_type(
    session: AsyncSession, type_id: int, project_id: int
) -> Optional[TaskType]:
    result = await session.exec(
        select(TaskType).where(
            TaskType.id == type_id, TaskType.project_id == project_id
        )
    )
    return result.one_or_none()


async def name_taken(
    session: AsyncSession,
    project_id: int,
    name: str,
    *,
    excluding: Optional[int] = None,
) -> bool:
    """Whether another of the project's types has this name, whatever its
    case."""
    stmt = select(TaskType.id).where(
        TaskType.project_id == project_id,
        func.lower(TaskType.name) == name.strip().lower(),
    )
    if excluding is not None:
        stmt = stmt.where(TaskType.id != excluding)
    return (await session.exec(stmt)).first() is not None


async def type_for_move(
    session: AsyncSession, task_type_id: int, destination_project_id: int
) -> int:
    """The type a task takes into another project: the one there with the same
    name, or that project's default."""
    name = (
        await session.exec(select(TaskType.name).where(TaskType.id == task_type_id))
    ).one_or_none()
    if name is not None:
        match = (
            await session.exec(
                select(TaskType.id).where(
                    TaskType.project_id == destination_project_id,
                    func.lower(TaskType.name) == name.lower(),
                )
            )
        ).first()
        if match is not None:
            return match
    default = await get_default_type(session, destination_project_id)
    assert default.id is not None
    return default.id


async def clone_types(
    session: AsyncSession, *, source_project_id: int, target_project_id: int
) -> dict[int, int]:
    """Give the target the source's types in place of its own; each source
    type's id mapped to its copy's."""
    source_types = await list_types(session, source_project_id)
    if not source_types:
        return {}
    await session.exec(
        delete(TaskType).where(col(TaskType.project_id) == target_project_id)
    )
    await session.flush()
    mapping: dict[int, int] = {}
    for source in source_types:
        clone = TaskType(
            project_id=target_project_id,
            name=source.name,
            position=source.position,
            is_default=source.is_default,
            color=source.color,
            icon=source.icon,
            layout_preset=source.layout_preset,
            starting_values=source.starting_values,
        )
        session.add(clone)
        await session.flush()
        assert source.id is not None and clone.id is not None
        mapping[source.id] = clone.id
    return mapping


async def copy_types(
    session: AsyncSession,
    sources: Iterable[TaskType],
    *,
    target_project_id: int,
) -> dict[int, TaskType]:
    """Add copies of ``sources`` to the target's types, after its own: each
    with its look and starting values, never the default. One whose name the
    target has is left out, and so is any past the limit. Each source type's
    id mapped to its copy."""
    types = await list_types(session, target_project_id)
    taken = {t.name.lower() for t in types}
    copies: dict[int, TaskType] = {}
    for source in sources:
        if len(types) >= MAX_TASK_TYPES:
            break
        if source.name.lower() in taken:
            continue
        copy = TaskType(
            project_id=target_project_id,
            name=source.name,
            position=len(types),
            is_default=False,
            color=source.color,
            icon=source.icon,
            layout_preset=source.layout_preset,
            starting_values=source.starting_values,
        )
        session.add(copy)
        types.append(copy)
        taken.add(source.name.lower())
        assert source.id is not None
        copies[source.id] = copy
    await session.flush()
    return copies


def resequence(types: list[TaskType]) -> None:
    for index, task_type in enumerate(types):
        task_type.position = index


def ensure_one_default(types: list[TaskType]) -> None:
    """Exactly one default: the first marked, or the first."""
    marked = [t for t in types if t.is_default]
    if not marked and types:
        types[0].is_default = True
    for extra in marked[1:]:
        extra.is_default = False
