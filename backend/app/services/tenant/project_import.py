"""Import a previously-exported project envelope into the target instance.

See plan & ``project_export.py`` for the format. The algorithm:

1. Refuse an envelope with no task statuses.
2. Resolve the target initiative + its guild + member handles.
3. Create the ``Project`` (importer is owner; rename on collision).
4. Bulk-create per-project task statuses; build ``name → id`` map.
5. Upsert tags by name; build ``name → id`` map; attach
   to project via ``project_tags``.
6. Upsert property definitions by ``(initiative_id, name)``. On type
   collision, create a new definition named ``<name>_<type>`` instead
   of mutating the target's existing one.
7. Insert each task; resolve status / tag / assignee / property refs
   via the maps; insert property values.
8. Store its layouts, their statuses and properties the new ones, and show
   the plug-ins placed in the initiative on them.
9. Return the counts as an :class:`EnvelopeImportResult`, like every
   importer's apply.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import recurrence
from app.schemas.recurrence import validate_task_recurrence
from app.core.messages import ImportEngineMessages, ProjectExportMessages
from app.core.search import SearchEntityType
from app.models.tenant.comment import Comment
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.property import PropertyType

from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskStatus,
    TaskStatusCategory,
    TaskType,
)
from app.models.platform.user import User
from app.schemas.tenant.project_export import (
    ProjectExportComment,
    ProjectExportEnvelope,
    ProjectExportTag,
    ProjectExportTask,
)
from app.schemas.tenant.task import mint_checklist_item_id
from app.schemas.tenant.task_type import TaskTypeStartingValues
from app.services.import_engine.context import ImportContext
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)
from app.services.import_engine.importers._base import (
    PropertyRestore,
    TagRestore,
    grant_ownership,
)
from app.services.import_engine.links import links_to_pages
from app.services.import_engine.mentions import place_markdown_mentions
from app.services.import_engine.references import (
    has_source_references,
    note_or_settle,
)
from app.services.import_engine.people import (
    PeopleMap,
    initiative_member_id,
    bring_in_named,
)
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant import task_completion
from app.services.tenant import tool_layouts as tool_layouts_service
from app.services.tenant.task_statuses import defaults_for_category
from app.services.tenant import task_types as task_types_service
from app.core.task_types import LAYOUT_SHAPES, MAX_TASK_TYPES
from app.services.import_engine.common import (
    load_initiative_member_handles,
    handle_key,
    unique_name_in_initiative,
)
from app.core.tools import TYPED_DETAILS, Tool
from app.services.tenant.named_people import Governing


async def import_project(
    session: AsyncSession,
    *,
    envelope: ProjectExportEnvelope,
    target_initiative: Initiative,
    importer: User,
    context: ImportContext | None = None,
) -> EnvelopeImportResult:
    """Materialize ``envelope`` as a new project under ``target_initiative``.

    Caller is responsible for permission checks (the user must be allowed
    to create projects in the target initiative) AND for committing — this
    function only flushes, so the import engine can compose it inside a
    larger transaction (per-chunk backup commits). RLS context must
    already point at the target guild.

    ``context`` is what the job knows and this envelope does not: the link
    collector, which each task registers itself with under the
    ``external_ref`` its envelope gave so the deferred pass can resolve the
    links it asserts — nothing resolves here, because the far end is usually
    in an entry that has not been applied yet — and the people map, which
    says which account each handle in it turned out to be.
    """
    if not envelope.task_statuses:
        raise ImportEngineError(ProjectExportMessages.NO_TASK_STATUSES)

    initiative_member_handles = await load_initiative_member_handles(
        session, initiative_id=target_initiative.id
    )
    # The same roster read the other way round. Assignment is gated on
    # membership however the handle was resolved, and a mapped account is
    # known by its id rather than by a handle to look up.

    # 1. Project row (rename on collision)
    project = Project(
        name=await unique_name_in_initiative(
            session, Project, target_initiative.id, envelope.project.name
        ),
        icon=envelope.project.icon,
        description=envelope.project.description,
        is_template=envelope.project.is_template,
        archived_at=envelope.project.archived_at,
        start_date=envelope.project.start_date,
        end_date=envelope.project.end_date,
        initiative_id=target_initiative.id,
    )
    session.add(project)
    await session.flush()  # populate project.id

    await grant_ownership(
        session,
        tool=Tool.project,
        entity_id=project.id,
        target_initiative=target_initiative,
        importer=importer,
    )

    # 2. Task statuses → name → id map
    status_name_to_id: dict[str, int] = {}
    status_id_to_category: dict[int, TaskStatusCategory] = {}
    # Each status by its place in the envelope, which is how a layout names it.
    status_by_place: dict[int, int] = {}
    default_status_id: int | None = None
    for s in envelope.task_statuses:
        default_color, default_icon = defaults_for_category(s.category)
        status_row = TaskStatus(
            project_id=project.id,
            name=s.name,
            category=s.category,
            position=s.position,
            color=s.color or default_color,
            icon=s.icon or default_icon,
            is_default=s.is_default,
        )
        session.add(status_row)
        await session.flush()
        status_name_to_id[s.name] = status_row.id  # ty: ignore[invalid-assignment] — persisted row, id is set
        status_id_to_category[status_row.id] = s.category  # ty: ignore[invalid-assignment] — persisted row, id is set
        status_by_place[len(status_by_place) + 1] = status_row.id  # ty: ignore[invalid-assignment] — persisted row, id is set
        if s.is_default and default_status_id is None:
            default_status_id = status_row.id
    if default_status_id is None:
        # First backlog-category status, else the first one
        default_status_id = next(
            (
                status_name_to_id[s.name]
                for s in envelope.task_statuses
                if s.category == TaskStatusCategory.backlog
            ),
            status_name_to_id[envelope.task_statuses[0].name],
        )

    # 2b. Task types → lowercased name → id map. An export taken before types
    # existed gives the project the ones a new project starts with, in the
    # importer's language.
    type_name_to_id = await _restore_types(session, project.id, envelope, importer)
    default_type_id = next(iter(type_name_to_id.values()))
    for task_type in await task_types_service.list_types(session, project.id):
        if task_type.is_default:
            default_type_id = task_type.id
    # A layout names a type by its place in the envelope, as it does a status.
    type_by_place = {
        place: type_name_to_id[entry.name.strip().lower()]
        for place, entry in enumerate(envelope.task_types, start=1)
        if entry.name.strip().lower() in type_name_to_id
    }

    # 3. Tags, attached to the project
    tags = TagRestore(session)
    await tags.attach(project, envelope.tags)

    # 4. Property definitions, then the project's own values. A property
    # unticked on the review is left out, with its values.
    props = PropertyRestore(
        session,
        initiative_id=target_initiative.id,
        context=context,
        member_handles=initiative_member_handles,
    )
    await props.declare(envelope.property_definitions)
    await props.attach(project, envelope.project.properties)

    # 5. Its tasks
    unmatched_handles: set[str] = set()
    named_handles: dict[int, str] = {}
    assignee_match_count = 0
    comment_count = 0
    series_ids: dict[int, int] = {}
    for t in envelope.tasks:
        matched, comments_made = await _import_task(
            session,
            envelope_task=t,
            project_id=project.id,
            importer_id=importer.id,
            importer_zone=importer.timezone,
            status_name_to_id=status_name_to_id,
            status_id_to_category=status_id_to_category,
            default_status_id=default_status_id,
            type_name_to_id=type_name_to_id,
            default_type_id=default_type_id,
            tags=tags,
            props=props,
            initiative_member_handles=initiative_member_handles,
            unmatched_handle_sink=unmatched_handles,
            named_handle_sink=named_handles,
            series_ids=series_ids,
            context=context,
        )
        assignee_match_count += matched
        comment_count += comments_made

    await session.flush()
    # 6. Its layouts, naming the statuses and properties it now has, with the
    # plug-ins placed here shown on them as they are on every saved layout.
    if envelope.layouts:
        property_by_place = {
            place: props.bound_id(declared.name, declared.type)
            for place, declared in enumerate(envelope.property_definitions, start=1)
        }
        remap = tool_layouts_service.Remap(
            statuses=status_by_place.get,
            properties=property_by_place.get,
            community=False,
            people=frozenset(
                place
                for place, declared in enumerate(envelope.property_definitions, start=1)
                if declared.type == PropertyType.user_reference
            ),
            types=type_by_place.get,
        )
        target = tool_layouts_service.Target(
            Tool.project, project.id, target_initiative.id
        )
        await tool_layouts_service.restore_layouts(
            session,
            target,
            (
                tool_layouts_service.Restored(
                    layout.kind,
                    tool_layouts_service.remapped_definition(layout.definition, remap),
                    task_type_id=(
                        None
                        if layout.kind != TYPED_DETAILS[Tool.project]
                        # A type the envelope does not list leaves its page
                        # out, drawn as its type's shape.
                        else type_by_place.get(layout.task_type)
                        if layout.task_type is not None
                        else default_type_id
                    ),
                )
                for layout in envelope.layouts
            ),
        )
        await guild_plugins_service.show_placed_on(session, target)
    # One pass lets in everyone the project now names, assignees and person
    # values alike.
    named_handles.update(props.named)
    unmatched_handles |= props.unmatched
    gone = await bring_in_named(
        session,
        Governing.of(Tool.project, project),
        initiative_id=target_initiative.id,
    )
    unmatched_handles.update(named_handles[user_id] for user_id in gone)

    return EnvelopeImportResult(
        entity_id=project.id,
        entity_title=project.name,
        created={
            Tool.project.plural: 1,
            "tasks": len(envelope.tasks),
            "tags": tags.created,
            "properties": props.created,
            "comments": comment_count,
        },
        matched={
            "tags": tags.matched,
            "properties": props.matched,
            "assignees": assignee_match_count,
        },
        renamed_property_count=len(props.renamed),
        unmatched_handles=sorted(unmatched_handles),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _starting_values(raw: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """A type's starting values as the column holds them, held to what a write
    of them would be; ones that are not start nothing."""
    if not raw:
        return None
    try:
        values = TaskTypeStartingValues.model_validate(raw)
    except ValidationError:
        return None
    return task_types_service.stored_starting_values(values)


async def _restore_types(
    session: AsyncSession,
    project_id: int,
    envelope: ProjectExportEnvelope,
    importer: User,
) -> dict[str, int]:
    """The project's task types from the envelope, or the ones a new project
    starts with when it carries none; each by its lowercased name. A name the
    envelope repeats is one type, and a shape this build does not draw is the
    plain one."""
    if not envelope.task_types:
        created = await task_types_service.ensure_default_types(
            session, project_id, locale=importer.locale
        )
        return {t.name.lower(): t.id for t in created}  # ty: ignore[invalid-return-type] — persisted rows, ids are set
    rows: list[TaskType] = []
    seen: set[str] = set()
    for entry in sorted(envelope.task_types, key=lambda t: t.position)[:MAX_TASK_TYPES]:
        name = entry.name.strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        rows.append(
            TaskType(
                project_id=project_id,
                name=name,
                is_default=entry.is_default,
                color=entry.color or "#94A3B8",
                icon=entry.icon or "square-check",
                layout_preset=(
                    entry.layout_preset
                    if entry.layout_preset in LAYOUT_SHAPES
                    else "plain"
                ),
                starting_values=_starting_values(entry.starting_values),
            )
        )
    task_types_service.resequence(rows)
    task_types_service.ensure_one_default(rows)
    session.add_all(rows)
    await session.flush()
    return {t.name.lower(): t.id for t in rows}  # ty: ignore[invalid-return-type] — persisted rows, ids are set


async def _import_task(
    session: AsyncSession,
    *,
    envelope_task: ProjectExportTask,
    project_id: int,
    importer_id: int,
    importer_zone: str | None,
    status_name_to_id: dict[str, int],
    status_id_to_category: dict[int, TaskStatusCategory],
    default_status_id: int,
    type_name_to_id: dict[str, int],
    default_type_id: int,
    tags: TagRestore,
    props: PropertyRestore,
    initiative_member_handles: dict[str, int],
    unmatched_handle_sink: set[str],
    named_handle_sink: dict[int, str],
    series_ids: dict[int, int],
    context: ImportContext | None = None,
) -> tuple[int, int]:
    """Insert one task, its checklist, tags, assignees, property values and
    comments. Returns (assignees matched & linked, comments written).
    """
    status_id = status_name_to_id.get(envelope_task.status_name) or default_status_id

    repeat, shift = recurrence.imported(
        envelope_task.recurrence,
        kind="task",
        start=envelope_task.due_date or envelope_task.start_date,
        tz=importer_zone,
        shift=envelope_task.recurrence_shift,
    )
    try:
        validate_task_recurrence(
            rule=repeat,
            strategy=envelope_task.recurrence_strategy,
            limit=envelope_task.recurrence_limit,
            due=envelope_task.due_date,
        )
    except ValueError as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_ENVELOPE) from exc
    task = Task(
        project_id=project_id,
        task_status_id=status_id,
        task_type_id=type_name_to_id.get(
            (envelope_task.type_name or "").strip().lower(), default_type_id
        ),
        title=envelope_task.title,
        description=place_markdown_mentions(
            envelope_task.description,
            envelope_task.mention_handles,
            context=context,
            initiative_member_handles=initiative_member_handles,
        ),
        priority=envelope_task.priority,
        start_date=envelope_task.start_date,
        due_date=envelope_task.due_date,
        recurrence=repeat,
        recurrence_shift=shift,
        recurrence_anchor=envelope_task.recurrence_anchor,
        recurrence_anchor_count=envelope_task.recurrence_anchor_count,
        recurrence_strategy=envelope_task.recurrence_strategy,
        recurrence_occurrence_count=envelope_task.recurrence_occurrence_count,
        recurrence_limit=envelope_task.recurrence_limit,
        position=envelope_task.position,
        archived_at=envelope_task.archived_at,
        completed_at=envelope_task.completed_at,
        created_by=importer_id,
        # When the work was written down, where the envelope says so. An
        # envelope that carries neither leaves the model's own default — the
        # moment of the import, which is the only time this row can honestly
        # claim. ``None`` would be a lie of a different kind: the column is
        # NOT NULL and every reader treats it as "when this appeared".
        **_timestamps(envelope_task),
        checklist=[
            {
                "id": mint_checklist_item_id(),
                "text": item.text,
                "done": item.done,
            }
            for item in envelope_task.checklist
        ],
    )
    # A restore keeps the completion time the envelope carries; envelopes taken
    # before the field existed carry none, so it's derived from the restored
    # status instead. Either way the timestamp ends up agreeing with the status.
    task_completion.sync_completed_at(
        task,
        status_id_to_category.get(status_id),
        now=datetime.now(timezone.utc),
    )
    session.add(task)
    await session.flush()
    # A series is named by its first task here, so the ones after it join it.
    if envelope_task.series is not None:
        task.series_id = series_ids.setdefault(envelope_task.series, task.id)

    # A task can carry tags the project itself does not.
    await tags.attach(task, envelope_task.tags)

    # What an edit of just this task kept back, its tags and assignees named
    # back into this community.
    if envelope_task.recurrence_carry:
        carry = dict(envelope_task.recurrence_carry)
        if carry.get("description"):
            # Linked to people here now, its references placed with the
            # task's own description once everything has been written.
            carry["description"] = note_or_settle(
                context,
                SearchEntityType.task,
                task.id,
                place_markdown_mentions(
                    carry["description"],
                    envelope_task.mention_handles,
                    context=context,
                    initiative_member_handles=initiative_member_handles,
                ),
            )
        if "tags" in carry:
            carried_tags = [ProjectExportTag(**tag) for tag in carry.pop("tags")]
            carry["tag_ids"] = sorted(
                {await tags.resolve(tag.name, tag.color) for tag in carried_tags}
            )
        if "assignee_handles" in carry:
            carried: set[int] = set()
            for handle in carry.pop("assignee_handles"):
                uid = initiative_member_id(
                    handle,
                    people=context.people if context is not None else PeopleMap(),
                    member_handles=initiative_member_handles,
                )
                if uid is not None:
                    carried.add(uid)
                    # Brought into the initiative with the task's own assignees.
                    named_handle_sink.setdefault(uid, handle)
            carry["assignee_ids"] = sorted(carried)
        # A type by its name, as the task's own is; an id is another project's.
        carry.pop("task_type_id", None)
        carried_type = type_name_to_id.get(
            str(carry.pop("type_name", "") or "").strip().lower()
        )
        if carried_type is not None:
            carry["task_type_id"] = carried_type
        task.recurrence_carry = carry

    if envelope_task.recurrence_anchor is None and task.recurrence:
        # Older envelopes have no phase metadata. Match their effective
        # continuation, including a date kept back by a this-only edit.
        from app.services.tenant.task_series import anchor_from_dates

        task.recurrence_anchor, task.recurrence_anchor_count = anchor_from_dates(task)

    # Assignees: the account a person mapped the handle to, else a member
    # whose handle is the same string (see ``people.initiative_member_id``).
    # Misses are dropped and counted; who is named is settled once the project
    # is written (``people.bring_in_named``).
    seen_user_ids: set[int] = set()
    for handle in envelope_task.assignee_handles:
        uid = initiative_member_id(
            handle,
            people=context.people if context is not None else PeopleMap(),
            member_handles=initiative_member_handles,
        )
        if uid is None:
            unmatched_handle_sink.add(handle)
            continue
        if uid in seen_user_ids:
            continue
        seen_user_ids.add(uid)
        named_handle_sink.setdefault(uid, handle)
        session.add(
            TaskAssignee(
                task_id=task.id,
                user_id=uid,
            )
        )

    await props.attach(task, envelope_task.properties)

    if context is not None and links_to_pages(task.description):
        context.links.note_body(SearchEntityType.task, task.id)
    # An exported description names other things by the refs they had; they
    # are placed once every entry of the job has been written.
    task.description = note_or_settle(
        context, SearchEntityType.task, task.id, task.description
    )

    # What this task was called at the source, and what it says it points at.
    # Both are handed to the job's collector and resolved once every entry has
    # been applied — see ``import_engine.links``.
    if context is not None:
        context.links.register(
            envelope_task.external_ref, SearchEntityType.task, task.id
        )
        for link in envelope_task.links:
            context.links.link(
                envelope_task.external_ref, link.type, link.target_external_ref
            )

    # A reply hangs under the comment it answers. The envelope lists comments
    # oldest first, so a parent is written before its replies; only a comment
    # something answers is flushed for its id. A reply whose parent did not
    # come across (restricted at the source, or empty) stands on its own.
    answered = {
        c.reply_to_ref for c in envelope_task.comments if c.reply_to_ref is not None
    }
    written: dict[str, int] = {}
    comment_count = 0
    for envelope_comment in envelope_task.comments:
        body = (envelope_comment.body or "").strip()
        if not body:
            continue
        author_id, source_name = _comment_author(
            envelope_comment,
            context=context,
            initiative_member_handles=initiative_member_handles,
            importer_id=importer_id,
        )
        comment = Comment(
            task_id=task.id,
            content=place_markdown_mentions(
                body,
                envelope_comment.mention_handles,
                context=context,
                initiative_member_handles=initiative_member_handles,
            ),
            created_by=author_id,
            imported_author_name=source_name,
            parent_comment_id=written.get(envelope_comment.reply_to_ref or ""),
            created_at=envelope_comment.created_at or datetime.now(timezone.utc),
        )
        session.add(comment)
        if context is not None and links_to_pages(comment.content):
            await session.flush()
            context.links.note_body(SearchEntityType.comment, comment.id)
        if has_source_references(comment.content):
            await session.flush()
            comment.content = note_or_settle(
                context, SearchEntityType.comment, comment.id, comment.content
            )
        ref = envelope_comment.external_ref
        if ref is not None and ref in answered and ref not in written:
            await session.flush()
            written[ref] = comment.id  # ty: ignore[invalid-assignment] — persisted row, id is set
        comment_count += 1

    return len(seen_user_ids), comment_count


def _timestamps(envelope_task: ProjectExportTask) -> dict[str, datetime]:
    """The creation/update times to write, if the envelope carried any.

    Returned as kwargs rather than values so an absent field falls through to
    the model's own default instead of overwriting it with None.
    """
    stamps: dict[str, datetime] = {}
    if envelope_task.created_at is not None:
        stamps["created_at"] = envelope_task.created_at
    if envelope_task.updated_at is not None:
        stamps["updated_at"] = envelope_task.updated_at
    return stamps


def _comment_author(
    envelope_comment: ProjectExportComment,
    *,
    context: ImportContext | None,
    initiative_member_handles: dict[str, int],
    importer_id: int,
) -> tuple[int, str | None]:
    """Who this comment belongs to here, and whose name to show if nobody.

    Three answers, in the order they are worth anything:

    1. **The account a person mapped this handle to**, in the import wizard's
       people step. This is the only thing that moves authorship, and it moves
       it because somebody read the name and said who it was.
    2. **A member of the target initiative whose handle is the same string.**
       Exact only, and only inside the initiative the comment is landing in —
       a handle is one identifier, and a restore into the community it came
       from is the case this covers.
    3. **Nobody.** The row names the import that wrote it, because every
       guild-content row names what wrote it, and the source's own answer
       rides beside it as ``imported_author_name`` — a name, not an account,
       so the comment shows no avatar and links to no profile.

    What is deliberately missing is a fourth: a near match. A display name
    that looks similar is how one person's words end up under another
    person's face, and telling those two apart is the whole reason the
    wizard asks.
    """
    handle = envelope_comment.author_handle
    mapped = context.people.user_id(handle) if context is not None else None
    if mapped is not None:
        return mapped, None
    if handle:
        member = initiative_member_handles.get(handle_key(handle))
        if member is not None:
            return member, None
    source_name = (
        envelope_comment.author_name or envelope_comment.author_handle or ""
    ).strip()
    return importer_id, source_name[:200] or None
