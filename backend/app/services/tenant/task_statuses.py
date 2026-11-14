from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import func
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.models.tenant.project import Project
from app.models.tenant.task import TaskStatus, TaskStatusCategory
from app.schemas.tenant.task_status import InitiativeTaskStatusRead

# To Do and Backlog share the slate now that To Do is the column new projects
# open with. The circle is what tells them apart: solid for the work you have
# agreed to, dashed for the work still only an idea.
CATEGORY_DEFAULTS: dict[TaskStatusCategory, tuple[str, str]] = {
    TaskStatusCategory.backlog: ("#94A3B8", "circle-dashed"),
    TaskStatusCategory.todo: ("#94A3B8", "circle"),
    TaskStatusCategory.in_progress: ("#60A5FA", "circle-play"),
    TaskStatusCategory.done: ("#34D399", "circle-check"),
}


def defaults_for_category(category: TaskStatusCategory) -> tuple[str, str]:
    return CATEGORY_DEFAULTS[category]


def _seeded(
    key: str, category: TaskStatusCategory, position: int, *, is_default: bool = False
) -> dict:
    color, icon = CATEGORY_DEFAULTS[category]
    return {
        "key": key,
        "category": category,
        "position": position,
        "is_default": is_default,
        "color": color,
        "icon": icon,
    }


# Three columns, because three is what a board needs to be useful. Blocked
# left with relations, which say what a task is waiting on rather than parking
# it in a status; Backlog left because most people read it as To Do anyway. The
# ``backlog`` category stays available for projects that already use it, and for
# anyone who wants to add the column back.
#: Each is named from the ``projects`` catalogue
#: (``taskStatuses.defaults.<key>``) in the language of whoever makes the project.
DEFAULT_TASK_STATUSES: Sequence[dict] = (
    _seeded("todo", TaskStatusCategory.todo, 0, is_default=True),
    _seeded("inProgress", TaskStatusCategory.in_progress, 1),
    _seeded("done", TaskStatusCategory.done, 2),
)

#: The language a project is given its statuses in when it is found without
#: any rather than made: a repair, where nobody's language is known.
REPAIR_LOCALE = "en"


def default_name(key: str, locale: str) -> str:
    """One of the starting statuses' names, in ``locale`` (English for a
    language the app does not speak)."""
    return translate(f"taskStatuses.defaults.{key}", locale, namespace="projects")


# Where an unmarked project's default lands when no status carries the flag.
# Backlog leads because only a project seeded before this change has one, and
# there it is the entry column — reaching for ``todo`` first would find that
# project's Blocked and start work in it. A project seeded since has no backlog
# column at all, so the preference falls straight through to its To Do.
_DEFAULT_CATEGORY_PREFERENCE: Sequence[TaskStatusCategory] = (
    TaskStatusCategory.backlog,
    TaskStatusCategory.todo,
)

#: Where a task moved to a category lands when its project has no column of
#: that category: the nearest one before it, so "done" in a project with no
#: done column is the furthest the project goes.
CATEGORY_FALLBACK: dict[TaskStatusCategory, Sequence[TaskStatusCategory]] = {
    TaskStatusCategory.backlog: (TaskStatusCategory.backlog,),
    TaskStatusCategory.todo: (TaskStatusCategory.todo, TaskStatusCategory.backlog),
    TaskStatusCategory.in_progress: (
        TaskStatusCategory.in_progress,
        TaskStatusCategory.todo,
        TaskStatusCategory.backlog,
    ),
    TaskStatusCategory.done: (
        TaskStatusCategory.done,
        TaskStatusCategory.in_progress,
        TaskStatusCategory.todo,
        TaskStatusCategory.backlog,
    ),
}


def first_by_category_preference(
    statuses: Sequence[TaskStatus],
    preference: Sequence[TaskStatusCategory] = _DEFAULT_CATEGORY_PREFERENCE,
) -> TaskStatus | None:
    """The first status in ``preference`` order — by default, the column a
    project should treat as its entry column."""
    for category in preference:
        match = next((s for s in statuses if s.category == category), None)
        if match is not None:
            return match
    return None


def _sorted(statuses: Iterable[TaskStatus]) -> list[TaskStatus]:
    return sorted(statuses, key=lambda status: (status.position, status.id or 0))


async def list_statuses(session: AsyncSession, project_id: int) -> Sequence[TaskStatus]:
    stmt = (
        select(TaskStatus)
        .where(TaskStatus.project_id == project_id)
        .order_by(TaskStatus.position.asc(), TaskStatus.id.asc())
    )
    result = await session.exec(stmt)
    return result.all()


async def ensure_default_statuses(
    session: AsyncSession, project_id: int, *, locale: str
) -> list[TaskStatus]:
    """The project's statuses, giving it the three it starts with if it has
    none, named in ``locale``: the language of whoever is making the project."""
    existing = await list_statuses(session, project_id)
    if existing:
        return _sorted(existing)

    created: list[TaskStatus] = []
    for payload in DEFAULT_TASK_STATUSES:
        fields = {k: v for k, v in payload.items() if k != "key"}
        status = TaskStatus(
            project_id=project_id, name=default_name(payload["key"], locale), **fields
        )
        session.add(status)
        created.append(status)
    await session.flush()
    return _sorted(created)


async def get_default_status(session: AsyncSession, project_id: int) -> TaskStatus:
    statuses = await ensure_default_statuses(session, project_id, locale=REPAIR_LOCALE)
    for status in statuses:
        if status.is_default:
            return status
    preferred = first_by_category_preference(statuses)
    if preferred is not None:
        return preferred
    return statuses[0]


async def get_project_status(
    session: AsyncSession, status_id: int, project_id: int
) -> TaskStatus | None:
    stmt = select(TaskStatus).where(
        TaskStatus.id == status_id, TaskStatus.project_id == project_id
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def clone_statuses(
    session: AsyncSession,
    *,
    source_project_id: int,
    target_project_id: int,
) -> dict[int, int]:
    stmt = (
        select(TaskStatus)
        .where(TaskStatus.project_id == source_project_id)
        .order_by(TaskStatus.position.asc(), TaskStatus.id.asc())
    )
    result = await session.exec(stmt)
    source_statuses = result.all()
    if not source_statuses:
        return {}

    await session.exec(
        delete(TaskStatus).where(TaskStatus.project_id == target_project_id)
    )
    await session.flush()

    mapping: dict[int, int] = {}
    for source_status in source_statuses:
        clone = TaskStatus(
            project_id=target_project_id,
            name=source_status.name,
            position=source_status.position,
            category=source_status.category,
            is_default=source_status.is_default,
            color=source_status.color,
            icon=source_status.icon,
        )
        session.add(clone)
        await session.flush()
        mapping[source_status.id] = clone.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    return mapping


@dataclass
class _StatusGroup:
    """One ``(name, category)`` column being collected across projects."""

    color: str
    icon: str
    project_ids: set[int] = field(default_factory=set)


async def list_initiative_statuses(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int | None,
    guild_id: int,
) -> list[InitiativeTaskStatusRead]:
    """The distinct status columns across an initiative's readable projects.

    Visibility is the project listing's own rule — the sharing gate narrows
    the scan to the projects this request may read — so both the columns and
    the counts describe the caller's view of the initiative. The scan is
    confined to one initiative, so it also passes ``initiative_id`` and picks up
    the "Full access" override a guild-wide listing has to leave out. Archived
    projects and templates stay out, matching the default project list.
    """
    project_conditions = [
        Project.initiative_id == initiative_id,
        Project.archived_at.is_(None),
        Project.is_template.is_(False),
    ]

    total_stmt = select(func.count()).select_from(Project).where(*project_conditions)
    projects_total = int((await session.exec(total_stmt)).one())
    if not projects_total:
        return []

    rows_stmt = (
        select(
            TaskStatus.name,
            TaskStatus.category,
            TaskStatus.color,
            TaskStatus.icon,
            TaskStatus.project_id,
        )
        .join(Project, Project.id == TaskStatus.project_id)
        .where(*project_conditions)
        .order_by(TaskStatus.position.asc(), TaskStatus.name.asc(), TaskStatus.id.asc())
    )
    rows = (await session.exec(rows_stmt)).all()

    # Board order: the scan is ordered by position, so a column first seen at
    # position 1 is grouped — and emitted — before one first seen at position 2.
    grouped: dict[tuple[str, TaskStatusCategory], _StatusGroup] = {}
    for name, category, color, icon, project_id in rows:
        group = grouped.get((name, category))
        if group is None:
            group = _StatusGroup(color=color, icon=icon)
            grouped[(name, category)] = group
        group.project_ids.add(project_id)

    return [
        InitiativeTaskStatusRead(
            name=name,
            category=category,
            color=group.color,
            icon=group.icon,
            project_count=len(group.project_ids),
            projects_total=projects_total,
        )
        for (name, category), group in grouped.items()
    ]
