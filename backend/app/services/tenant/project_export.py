"""Build a self-contained JSON export for a single project.

The output is a :class:`ProjectExportEnvelope` that references tags, task
statuses, properties, and users by string keys (name / handle) rather than
integer IDs so it can be imported on a different Initiative instance.

Tasks carry what was said on them and what they point at: comments (as
text plus the author's handle and display name — never an id), and the edges
between tasks, named by ``external_ref`` so the far end resolves after both
ends have been restored. Both are optional fields, so an older reader that
does not know them ignores them and the version does not move.

A mention in a description or a comment names its person the same way: the
``@[Name](id)`` the app stores is written as ``@<handle>`` and the handle is
listed in ``mention_handles``, so the restore links it to whoever that handle
is there (``import_engine.mentions``). A reference to another thing —
``#task[Title](41)`` — is written with the ref it had in place of its id,
``#task[Title](task:41)``, and the restore points it at whatever that became
(``import_engine.references``).

Out of scope (see plan): files, attachments, project-role permissions,
bookmarks, recents, queues. Those would extend the schema under a future
``schema_version`` bump.
"""

from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.core.relationships import RelationshipType, decode_node_id, node_id
from app.core.search import SearchEntityType
from app.core.user_display import display_name, handle_of
from app.schemas.tenant.import_envelopes import EnvelopePropertyValue
from app.services.export.property_values import (
    exported_properties,
    portable_summaries,
)
from app.core.version import get_version
from app.models.tenant.comment import Comment, in_thread
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.project import Project
from app.models.tenant.metadata import MetadataDefinition, MetadataType
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.tag import Tag
from app.models.tenant.task import Task, TaskStatus
from app.schemas.tenant.project_export import (
    ProjectExportComment,
    ProjectExportEnvelope,
    ProjectExportLayout,
    ProjectExportProject,
    ProjectExportPropertyDefinition,
    ProjectExportChecklistItem,
    ProjectExportTag,
    ProjectExportTask,
    ProjectExportTaskLink,
    ProjectExportTaskStatus,
    ProjectExportTaskType,
)
from app.services.import_engine.mentions import (
    detach_markdown_mentions,
    load_mention_handles,
    markdown_mention_ids,
)
from app.services.import_engine.references import detach_markdown_references
from app.core.tools import Tool
from app.services.import_engine.common import load_initiative_properties
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_types as task_types_service
from app.services.tenant import tool_layouts as tool_layouts_service


async def build_project_export(
    session: AsyncSession,
    project: Project,
    *,
    exported_by_handle: Optional[str] = None,
    source_instance_url: Optional[str] = None,
    source_guild_id: Optional[int] = None,
) -> ProjectExportEnvelope:
    """Serialize ``project`` and its tasks to an envelope.

    ``project`` is the row the export loaded and authorized, with its task
    statuses (``project_grants.get_project_hydrated``); its tasks are read
    here.
    """
    project_tasks = list(
        await session.exec(
            select(Task)
            .where(Task.project_id == project.id)
            .options(selectinload(Task.assignees))
            .order_by(Task.position, Task.id)
        )
    )
    await tags_service.annotate_tags(session, [project])
    await metadata_service.annotate_properties(session, [project])
    await tags_service.annotate_tags(session, project_tasks)
    await metadata_service.annotate_properties(session, project_tasks)

    task_ids = [task.id for task in project_tasks if task.id is not None]
    comments_by_task = await _load_comments(session, task_ids)
    links_by_task = await _load_links(session, task_ids)
    # Everybody a description or a comment mentions, read once for the whole
    # project rather than once per body.
    mention_handles = await load_mention_handles(
        session,
        set().union(
            *(markdown_mention_ids(task.description) for task in project_tasks),
            *(
                markdown_mention_ids(comment.body)
                for comments in comments_by_task.values()
                for comment in comments
            ),
        ),
    )
    for comments in comments_by_task.values():
        for comment in comments:
            body, comment.mention_handles = detach_markdown_mentions(
                comment.body, mention_handles
            )
            comment.body = detach_markdown_references(body) or ""

    # Project-level tag set
    project_tags: list[ProjectExportTag] = []
    seen_tag_names: set[str] = set()
    for tag in project.tags or []:
        if tag.name in seen_tag_names:
            continue
        seen_tag_names.add(tag.name)
        project_tags.append(ProjectExportTag(name=tag.name, color=tag.color))

    # Per-project task statuses
    statuses_sorted = sorted(project.task_statuses or [], key=lambda s: s.position)
    statuses = [
        ProjectExportTaskStatus(
            name=s.name,
            category=s.category,
            position=s.position,
            color=s.color,
            icon=s.icon,
            is_default=s.is_default,
        )
        for s in statuses_sorted
    ]

    # Tasks (and gather property-definition references along the way, from
    # the project's own values first)
    tasks: list[ProjectExportTask] = []
    referenced_property_ids = {
        summary.property_id for summary in portable_summaries(project)
    }
    status_names = {s.id: s.name for s in statuses_sorted}
    project_types = await task_types_service.list_types(session, project.id)
    type_names = {t.id: t.name for t in project_types}
    for task in project_tasks:
        referenced_property_ids.update(
            summary.property_id for summary in portable_summaries(task)
        )
        properties = [
            EnvelopePropertyValue(**value) for value in exported_properties(task)
        ]

        checklist = [
            ProjectExportChecklistItem(
                text=item.get("text", ""), done=bool(item.get("done"))
            )
            for item in (task.checklist or [])
            if item.get("text")
        ]

        task_tags: list[ProjectExportTag] = []
        seen_task_tags: set[str] = set()
        for tag in task.tags or []:
            if tag.name not in seen_task_tags:
                seen_task_tags.add(tag.name)
                task_tags.append(ProjectExportTag(name=tag.name, color=tag.color))

        assignee_handles = [handle_of(u) for u in (task.assignees or [])]
        assignee_names = [display_name(u) for u in (task.assignees or [])]

        status_name = status_names.get(task.task_status_id) or _fallback_status_name(
            statuses_sorted
        )

        description, described = detach_markdown_mentions(
            task.description, mention_handles
        )
        carry, carry_described = await _portable_carry(
            session, task.recurrence_carry, mention_handles, type_names
        )
        tasks.append(
            ProjectExportTask(
                title=task.title,
                description=detach_markdown_references(description),
                priority=task.priority,
                start_date=task.start_date,
                due_date=task.due_date,
                recurrence=task.recurrence,
                recurrence_shift=task.recurrence_shift,
                recurrence_anchor=task.recurrence_anchor,
                recurrence_anchor_count=task.recurrence_anchor_count,
                recurrence_strategy=task.recurrence_strategy,
                recurrence_occurrence_count=task.recurrence_occurrence_count,
                recurrence_limit=task.recurrence_limit,
                series=task.series_id,
                recurrence_carry=carry,
                position=task.position,
                archived_at=task.archived_at,
                completed_at=task.completed_at,
                status_name=status_name,
                type_name=type_names.get(task.task_type_id),
                tags=task_tags,
                assignee_handles=assignee_handles,
                assignee_names=assignee_names,
                checklist=checklist,
                properties=properties,
                created_at=task.created_at,
                updated_at=task.updated_at,
                external_ref=task_ref(task.id),
                links=links_by_task.get(task.id, []),
                comments=comments_by_task.get(task.id, []),
                mention_handles=list(dict.fromkeys(described + carry_described)),
            )
        )

    # The initiative's properties and the project's own metadata are what a
    # layout can name besides those a value names. Each one exported is
    # written at its place in the envelope, which is how a layout names it.
    definitions = {
        **{
            definition.id: definition
            for definition in (
                await load_initiative_properties(
                    session, initiative_id=project.initiative_id
                )
            ).values()
        },
        **{
            definition.id: definition
            for definition in await session.exec(
                select(MetadataDefinition)
                .where(MetadataDefinition.project_id == project.id)
                .order_by(MetadataDefinition.position, MetadataDefinition.id)
            )
        },
        **await metadata_service.load_definitions_by_ids(
            session, referenced_property_ids
        ),
    }
    property_places: dict[int, int] = {}

    def property_place(property_id: int) -> Optional[int]:
        if property_id not in definitions:
            return None
        return property_places.setdefault(property_id, len(property_places) + 1)

    for property_id in sorted(referenced_property_ids):
        property_place(property_id)
    # The project's metadata goes with it whether or not anything holds it.
    for property_id, definition in definitions.items():
        if definition.project_id is not None:
            property_place(property_id)
    status_places = {s.id: place for place, s in enumerate(statuses_sorted, start=1)}
    type_places = {t.id: place for place, t in enumerate(project_types, start=1)}
    people = frozenset(
        property_id
        for property_id, definition in definitions.items()
        if definition.type == MetadataType.user_reference
    )
    layout_rows = await tool_layouts_service.list_rows(
        session,
        tool_layouts_service.Target(Tool.project, project.id, project.initiative_id),
    )
    layouts = [
        ProjectExportLayout(
            kind=row.kind,
            task_type=(
                type_places.get(row.task_type_id)
                if row.task_type_id is not None
                else None
            ),
            definition=tool_layouts_service.remapped_definition(
                row.definition,
                tool_layouts_service.Remap(
                    statuses=status_places.get,
                    properties=property_place,
                    community=False,
                    people=people,
                    types=type_places.get,
                ),
            ),
        )
        for row in sorted(
            layout_rows,
            key=lambda row: (row.kind, type_places.get(row.task_type_id or 0, 0)),
        )
    ]
    property_definitions = [
        ProjectExportPropertyDefinition(
            name=definitions[property_id].name,
            type=definitions[property_id].type,
            position=definitions[property_id].position,
            color=definitions[property_id].color,
            options=definitions[property_id].options,
            currency=definitions[property_id].currency,
            project=definitions[property_id].project_id is not None,
        )
        for property_id in property_places
    ]

    return ProjectExportEnvelope(
        app_version=get_version(),
        exported_at=datetime.now(timezone.utc),
        exported_by_handle=exported_by_handle,
        source_instance_url=source_instance_url,
        source_guild_id=source_guild_id,
        project=ProjectExportProject(
            name=project.name,
            icon=project.icon,
            description=project.description,
            is_template=project.is_template,
            archived_at=project.archived_at,
            start_date=project.start_date,
            end_date=project.end_date,
            properties=[
                EnvelopePropertyValue(**value) for value in exported_properties(project)
            ],
        ),
        tags=project_tags,
        task_statuses=statuses,
        task_types=[
            ProjectExportTaskType(
                name=t.name,
                position=t.position,
                is_default=t.is_default,
                color=t.color,
                icon=t.icon,
                layout_preset=t.layout_preset,
                starting_values=t.starting_values,
            )
            for t in project_types
        ],
        property_definitions=property_definitions,
        tasks=tasks,
        layouts=layouts,
    )


#: Edge kinds a task envelope carries. ``tagged_with`` is already the task's
#: ``tags`` and ``references`` is derived from bodies on save rather than
#: asserted, so neither is something a restore should re-assert from here.
_EXPORTED_LINK_TYPES: tuple[RelationshipType, ...] = (
    RelationshipType.depends_on,
    RelationshipType.part_of,
    RelationshipType.related_to,
    RelationshipType.attached,
)

#: Far ends worth naming: the kinds whose importer registers a ref, so a link
#: to one can actually be resolved on the other side. A link to anything else
#: would be written only to be counted as unresolved.
_LINKABLE_TARGETS: frozenset[SearchEntityType] = frozenset(
    {SearchEntityType.task, SearchEntityType.calendar_event}
)


def task_ref(task_id: int | None) -> str | None:
    """The name a task answers to across one import.

    Derived from the source id rather than stored, because it has to be the
    same string wherever the task is named — a project envelope writing its
    own tasks, and another project's envelope pointing at one of them in the
    same backup.
    """
    return f"task:{task_id}" if task_id is not None else None


def _entity_ref(kind: SearchEntityType, entity_id: int) -> str:
    return f"{kind.value}:{entity_id}"


async def _load_comments(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, list[ProjectExportComment]]:
    """What was said on each of these tasks, oldest first.

    Authors cross as a handle and a display name and never as an id — the
    rule every envelope follows for people. Trashed comments do not cross at
    all: a restore is not where somebody's deleted words come back.
    """
    if not task_ids:
        return {}
    rows = (
        await session.exec(
            select(Comment)
            .where(
                Comment.task_id.in_(task_ids),
                Comment.deleted_at.is_(None),
                in_thread(),
            )
            .options(selectinload(Comment.author))
            .order_by(Comment.created_at.asc(), Comment.id.asc())
        )
    ).all()
    by_task: dict[int, list[ProjectExportComment]] = {}
    for row in rows:
        author = getattr(row, "author", None)
        by_task.setdefault(row.task_id, []).append(
            ProjectExportComment(
                author_handle=handle_of(author) if author is not None else None,
                author_name=display_name(author) if author is not None else None,
                body=row.content,
                created_at=row.created_at,
                external_ref=f"comment:{row.id}",
                reply_to_ref=(
                    f"comment:{row.parent_comment_id}"
                    if row.parent_comment_id is not None
                    else None
                ),
            )
        )
    return by_task


async def _load_links(
    session: AsyncSession, task_ids: list[int]
) -> dict[int, list[ProjectExportTaskLink]]:
    """The edges these tasks assert, from the task's side.

    Only edges *stored* with one of these tasks as the source are read, so an
    edge is written once rather than from both ends — a symmetric one is
    stored in node order, and the importer re-orders it on the way back in.

    Refs, not ids: the far end may be in another envelope of the same backup
    (a task in a different project, a sprint on a calendar), which resolves
    once everything has been applied, or outside it entirely, which is
    counted. Both are ordinary, and neither is knowable from here.
    """
    if not task_ids:
        return {}
    source_nodes = [node_id(SearchEntityType.task, task_id) for task_id in task_ids]
    rows = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_node.in_(source_nodes),
                EntityRelationship.relationship_type.in_(
                    [t.value for t in _EXPORTED_LINK_TYPES]
                ),
                EntityRelationship.removed_at.is_(None),
            )
        )
    ).all()
    by_task: dict[int, list[ProjectExportTaskLink]] = {}
    for row in rows:
        try:
            target_kind, target_id = decode_node_id(row.target_node)
        except ValueError:
            # A kind this build has no code for: nothing here can name it.
            continue
        if target_kind not in _LINKABLE_TARGETS:
            continue
        by_task.setdefault(row.source_id, []).append(
            ProjectExportTaskLink(
                type=RelationshipType(row.relationship_type),
                target_external_ref=_entity_ref(target_kind, target_id),
            )
        )
    return by_task


async def _portable_carry(
    session: AsyncSession,
    carry: dict[str, Any] | None,
    mention_handles: Mapping[int, str],
    type_names: Mapping[int, str],
) -> tuple[dict[str, Any] | None, list[str]]:
    """``recurrence_carry`` as the envelope names things: its description's
    mentions by handle and references by ref, its tags by name and colour, its
    assignees by handle and its type by name. Also the handles the description
    mentions."""
    if not carry:
        return None, []
    portable = {
        field: value
        for field, value in carry.items()
        if field not in {"tag_ids", "assignee_ids", "task_type_id"}
    }
    if carry.get("task_type_id") in type_names:
        portable["type_name"] = type_names[carry["task_type_id"]]
    described: list[str] = []
    if "description" in carry:
        description, described = detach_markdown_mentions(
            carry["description"], mention_handles
        )
        portable["description"] = detach_markdown_references(description)
    if "tag_ids" in carry:
        tags = await session.exec(select(Tag).where(Tag.id.in_(carry["tag_ids"])))
        portable["tags"] = [{"name": tag.name, "color": tag.color} for tag in tags]
    if "assignee_ids" in carry:
        people = await session.exec(
            select(MemberProfile).where(MemberProfile.id.in_(carry["assignee_ids"]))
        )
        portable["assignee_handles"] = [handle_of(person) for person in people]
    return portable, described


def _fallback_status_name(statuses_sorted: list[TaskStatus]) -> str:
    """Pick a status name to associate with a task whose status row is
    missing (defensive — shouldn't happen in normal operation)."""
    for s in statuses_sorted:
        if s.is_default:
            return s.name
    return statuses_sorted[0].name if statuses_sorted else "Backlog"
