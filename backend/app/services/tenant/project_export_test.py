"""Round-trip and feature tests for project export/import services.

The most valuable test is a full round-trip: export a populated project,
import the envelope into a different initiative in the same guild, and
verify the new project has equivalent tags, statuses, properties, tasks,
checklists, assignees, and property values.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.user_display import handle_of
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.project import Project
from app.models.tenant.metadata import (
    MetadataDefinition,
    MetadataType,
    MetadataValue,
)
from app.models.tenant.tag import Tag
from app.models.tenant.tool_layout import ToolLayout
from app.schemas.tenant.import_envelopes import CURRENT_SCHEMA_VERSION
from app.models.tenant.task import Task, TaskAssignee, TaskStatusCategory
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.tenant import project_export as export_service
from app.services.tenant import project_import as import_service
from app.services.tenant.project_grants import get_project_hydrated
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant import ownership as ownership_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_types as task_types_service
from app.services.tenant.task_types import get_default_type
from app.testing import (
    assign_tag,
    checklist_items,
    create_guild,
    create_guild_membership,
    create_guild_plugin,
    create_initiative,
    create_initiative_member,
    create_project,
    create_property_definition,
    create_property_value,
    create_user,
    route_as,
    route_session_to_guild,
)


async def _seed_populated_project(session: AsyncSession):
    """Build a project with statuses, tags, a property definition, and a
    task that exercises a checklist, assignees, tags, and property values."""
    owner = await create_user(session, email="owner@example.com")
    assignee = await create_user(session, email="alice@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=owner, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=assignee, guild=guild, role=CommunityRole.member
    )
    initiative = await create_initiative(
        session, guild, owner, name="Source Initiative"
    )
    await create_initiative_member(session, initiative, assignee, role_name="member")

    project = await create_project(
        session, initiative, owner, name="Source Project", icon="🚀"
    )

    # Statuses
    statuses = await task_statuses_service.ensure_default_statuses(
        session, project.id, locale="en"
    )
    todo_status = next(s for s in statuses if s.category == TaskStatusCategory.todo)

    # Project-level tag
    tag = Tag(name="blocker", color="#FF0000")
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    await assign_tag(session, project, tag)

    # Property definition (select)
    severity = await create_property_definition(
        session,
        initiative,
        name="Severity",
        type=MetadataType.select,
        options=[{"value": "low", "label": "Low"}, {"value": "high", "label": "High"}],
    )

    # Task
    task = Task(
        project_id=project.id,
        task_status_id=todo_status.id,
        task_type_id=(await get_default_type(session, project.id)).id,
        title="Fix the thing",
        description="Important",
        position=1024.0,
        series_id=4242,
        due_date=datetime(2026, 10, 7, 9, tzinfo=timezone.utc),
        recurrence="RRULE:FREQ=WEEKLY\nRDATE:20261007T090000Z",
        recurrence_anchor=datetime(2026, 10, 5, 9, tzinfo=timezone.utc),
        recurrence_carry={
            "title": "Fix it once",
            "tag_ids": [tag.id],
            "assignee_ids": [assignee.id],
            # Kept back from a this-only change of type: the project's own row.
            "task_type_id": next(
                t.id
                for t in await task_types_service.list_types(session, project.id)
                if t.name == "Bug"
            ),
        },
        checklist=[
            *checklist_items("step 1"),
            *checklist_items("step 2", done=True),
        ],
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    await assign_tag(session, task, tag)
    session.add(
        TaskAssignee(
            task_id=task.id,
            user_id=assignee.id,
        )
    )
    await session.commit()
    await create_property_value(session, task, severity, value_text="high")

    return owner, assignee, guild, initiative, project


async def test_round_trip_into_different_initiative(session: AsyncSession):
    (
        owner,
        assignee,
        guild,
        source_initiative,
        source_project,
    ) = await _seed_populated_project(session)

    # Build the export envelope
    envelope = await export_service.build_project_export(
        session,
        await get_project_hydrated(session, source_project.id),
        exported_by_handle=handle_of(owner),
    )

    assert envelope.schema_version == CURRENT_SCHEMA_VERSION
    assert envelope.project.name == "Source Project"
    assert envelope.project.icon == "🚀"
    assert {s.name for s in envelope.task_statuses} >= {
        "Backlog",
        "To-do",
        "In progress",
        "Done",
    } or len(envelope.task_statuses) >= 1
    assert {t.name for t in envelope.tags} == {"blocker"}
    assert {p.name for p in envelope.property_definitions} == {"Severity"}
    assert len(envelope.tasks) == 1
    exported_task = envelope.tasks[0]
    assert exported_task.title == "Fix the thing"
    assert [t.name for t in exported_task.tags] == ["blocker"]
    assert [t.color for t in exported_task.tags] == ["#FF0000"]
    assert exported_task.assignee_handles == [handle_of(assignee)]
    assert {i.text for i in exported_task.checklist} == {"step 1", "step 2"}
    assert exported_task.properties[0].property_name == "Severity"
    assert exported_task.properties[0].value_text == "high"
    assert exported_task.series == 4242
    assert exported_task.recurrence_anchor == datetime(
        2026, 10, 5, 9, tzinfo=timezone.utc
    )
    assert exported_task.recurrence_carry == {
        "title": "Fix it once",
        "tags": [{"name": "blocker", "color": "#FF0000"}],
        "assignee_handles": [handle_of(assignee)],
        "type_name": "Bug",
    }

    # Target initiative in the same guild — assignee is a member of both
    target_initiative = await create_initiative(
        session, guild, owner, name="Target Initiative"
    )
    await create_initiative_member(
        session, target_initiative, assignee, role_name="member"
    )

    # Import, as the importer's request would: through the seam.
    await route_as(session, user_id=owner.id, guild_id=guild.id)
    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )

    assert result.created["tasks"] == 1
    assert result.unmatched_handles == []
    assert result.created["tags"] + result.matched["tags"] == 1
    assert result.created["properties"] == 1
    assert result.matched["assignees"] == 1

    # Verify the new project lives in target initiative with full graph
    stmt = (
        select(Project)
        .where(Project.id == result.entity_id)
        .options(
            selectinload(Project.grants),
            selectinload(Project.task_statuses),
            selectinload(Project.tasks).selectinload(Task.assignees),
        )
    )
    new_project = (await session.exec(stmt)).one()
    assert new_project.initiative_id == target_initiative.id
    assert new_project.name == "Source Project"
    assert new_project.icon == "🚀"
    assert ownership_service.owner_user_id_of(new_project) == owner.id
    assert len(new_project.tasks) == 1
    new_task = new_project.tasks[0]
    assert new_task.title == "Fix the thing"
    # Its series is named after the first task of it the import made.
    assert new_task.series_id == new_task.id
    assert new_task.recurrence_anchor == datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    from app.services.tenant.task_series import next_dates

    dates = await next_dates(
        session, new_task, now=new_task.due_date, user_timezone="UTC"
    )
    assert dates is not None
    assert dates[1] == datetime(2026, 10, 12, 9, tzinfo=timezone.utc)
    await tags_service.annotate_tags(session, [new_task])
    assert new_task.recurrence_carry == {
        "title": "Fix it once",
        "tag_ids": [tag.id for tag in new_task.tags],
        "assignee_ids": [assignee.id],
        "task_type_id": next(
            t.id
            for t in await task_types_service.list_types(session, new_task.project_id)
            if t.name == "Bug"
        ),
    }
    assert {i["text"] for i in new_task.checklist} == {"step 1", "step 2"}
    assert [handle_of(u) for u in new_task.assignees] == [handle_of(assignee)]
    await tags_service.annotate_tags(session, [new_task])
    assert {t.name for t in new_task.tags} == {"blocker"}
    pv = (
        await session.exec(
            select(MetadataValue)
            .where(
                MetadataValue.entity_type == "task",
                MetadataValue.entity_id == new_task.id,
            )
            .options(selectinload(MetadataValue.definition))
        )
    ).one()
    assert pv.value_text == "high"
    assert pv.definition.name == "Severity"
    assert pv.definition.initiative_id == target_initiative.id


async def test_a_project_brings_its_layouts(session: AsyncSession):
    owner, assignee, guild, source_initiative, project = await _seed_populated_project(
        session
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, project.id, locale="en"
    )
    todo, done = (
        next(s for s in statuses if s.category == category)
        for category in (TaskStatusCategory.todo, TaskStatusCategory.done)
    )
    # Not the default: a page and a filter name the type they were made for.
    bug = next(
        t
        for t in await task_types_service.list_types(session, project.id)
        if t.name == "Bug"
    )
    severity = (
        await session.exec(
            select(MetadataDefinition).where(MetadataDefinition.name == "Severity")
        )
    ).one()
    # Named by a layout and by no value.
    stage = await create_property_definition(
        session, source_initiative, name="Stage", type=MetadataType.text
    )
    lead = await create_property_definition(
        session, source_initiative, name="Lead", type=MetadataType.user_reference
    )
    tag = (await session.exec(select(Tag))).one()
    plugin = await create_guild_plugin(
        session,
        guild,
        owner,
        definition={
            "fields": [
                {"key": "build", "name": "Build", "kind": "text", "on": ["task"]}
            ],
            "parts": [
                {
                    "id": "panel",
                    "name": "Panel",
                    "on": ["task"],
                    "tree": {"type": "stack"},
                }
            ],
        },
    )
    build = {"type": "field", "props": {"field": f"plugin:{plugin.id}:build"}}
    panel = {"type": "plugin", "props": {"plugin": plugin.id, "part": "panel"}}
    title = {"type": "field", "props": {"field": "title"}}
    await route_session_to_guild(session, guild.id)
    for kind, definition in {
        "board": {
            "card": {
                "type": "card",
                "children": [
                    title,
                    {"type": "field", "props": {"field": f"property:{stage.id}"}},
                    build,
                ],
            },
            "presets": [
                {
                    "slug": "mine",
                    "filters": {
                        "status_ids": [todo.id],
                        "type_ids": [bug.id],
                        "assignees": ["me", str(assignee.id)],
                        "tag_ids": [tag.id],
                        "properties": [
                            {"property_id": lead.id, "op": "eq", "value": assignee.id}
                        ],
                    },
                }
            ],
            "limits": [{"status_id": todo.id, "limit": 3}],
        },
        "table": {
            "columns": ["title", f"property:{stage.id}"],
            "groupings": [
                {"field": "task_status_id", "hidden": [str(done.id)]},
                {"field": f"property:{severity.id}", "hidden": ["low"]},
                {"field": "assignee_ids", "hidden": [str(assignee.id)]},
                {"field": f"property:{lead.id}", "hidden": [str(assignee.id)]},
                {"field": "task_type_id", "hidden": [str(bug.id)]},
            ],
            "group_by": f"property:{severity.id}",
        },
        "task": {
            "side": [
                {"type": "field", "props": {"field": f"property:{severity.id}"}},
                panel,
            ]
        },
        "default": {"kind": "board"},
    }.items():
        session.add(
            ToolLayout(
                initiative_id=source_initiative.id,
                tool="project",
                tool_id=project.id,
                kind=kind,
                task_type_id=bug.id if kind == "task" else None,
                definition=definition,
            )
        )
    await session.commit()

    envelope = await export_service.build_project_export(
        session, await get_project_hydrated(session, project.id)
    )

    # Statuses and properties by their place in the envelope; nothing of the
    # community's people, tags or plug-ins.
    exported = {layout.kind: layout.definition for layout in envelope.layouts}
    place = {p.name: n for n, p in enumerate(envelope.property_definitions, start=1)}
    todo_place = 1 + [s.name for s in envelope.task_statuses].index(todo.name)
    bug_place = 1 + [t.name for t in envelope.task_types].index("Bug")
    assert set(place) == {"Severity", "Stage", "Lead"}
    assert exported["board"]["card"]["children"] == [
        title,
        {"type": "field", "props": {"field": f"property:{place['Stage']}"}},
    ]
    assert exported["board"]["presets"][0]["filters"] == {
        "status_ids": [todo_place],
        "type_ids": [bug_place],
        "assignees": ["me"],
        "tag_ids": [],
        "properties": [],
    }
    assert exported["board"]["limits"] == [{"status_id": todo_place, "limit": 3}]
    # Nor the people a person property names.
    assert exported["table"]["groupings"][2:] == [
        {"field": "assignee_ids", "hidden": []},
        {"field": f"property:{place['Lead']}", "hidden": []},
        {"field": "task_type_id", "hidden": [str(bug_place)]},
    ]
    # A task page names its type as a filter does.
    assert [
        layout.task_type for layout in envelope.layouts if layout.kind == "task"
    ] == [bug_place]
    assert exported["task"]["side"] == [
        {"type": "field", "props": {"field": f"property:{place['Severity']}"}}
    ]

    target_initiative = await create_initiative(
        session, guild, owner, name="Target Initiative"
    )
    await route_session_to_guild(session, guild.id)
    session.add(
        PluginPlacement(install_id=plugin.id, initiative_id=target_initiative.id)
    )
    await session.commit()
    await route_as(session, user_id=owner.id, guild_id=guild.id)
    result = await import_service.import_project(
        session, envelope=envelope, target_initiative=target_initiative, importer=owner
    )
    await session.commit()

    await route_session_to_guild(session, guild.id)
    rows = await session.exec(
        select(ToolLayout).where(ToolLayout.tool_id == result.entity_id)
    )
    imported_rows = rows.all()
    imported = {row.kind: row.definition for row in imported_rows}
    new_bug = next(
        t.id
        for t in await task_types_service.list_types(session, result.entity_id)
        if t.name == "Bug"
    )
    new_statuses = {
        s.name: s.id
        for s in await task_statuses_service.ensure_default_statuses(
            session, result.entity_id, locale="en"
        )
    }
    new_properties = {
        p.name: p.id
        for p in (
            await session.exec(
                select(MetadataDefinition).where(
                    MetadataDefinition.initiative_id == target_initiative.id
                )
            )
        ).all()
    }
    new_build = {"type": "field", "props": {"field": f"plugin:{plugin.id}:build"}}
    # The new project's own statuses and the initiative's own properties, and
    # the plug-in placed there shown as it would be on any saved layout.
    assert imported["board"]["card"]["children"] == [
        title,
        {"type": "field", "props": {"field": f"property:{new_properties['Stage']}"}},
        new_build,
    ]
    assert imported["board"]["presets"][0]["filters"]["status_ids"] == [
        new_statuses[todo.name]
    ]
    assert imported["board"]["presets"][0]["filters"]["type_ids"] == [new_bug]
    assert imported["table"]["groupings"][-1] == {
        "field": "task_type_id",
        "hidden": [str(new_bug)],
    }
    assert [row.task_type_id for row in imported_rows if row.kind == "task"] == [
        new_bug
    ]
    assert imported["board"]["limits"] == [
        {"status_id": new_statuses[todo.name], "limit": 3}
    ]
    assert imported["table"]["groupings"][0] == {
        "field": "task_status_id",
        "hidden": [str(new_statuses[done.name])],
    }
    assert imported["table"]["group_by"] == f"property:{new_properties['Severity']}"
    assert imported["task"]["side"] == [
        {"type": "field", "props": {"field": f"property:{new_properties['Severity']}"}},
        new_build,
        panel,
    ]
    assert imported["default"] == {"kind": "board"}


async def test_an_envelope_holds_one_layout_of_each_kind_as_read(
    session: AsyncSession,
):
    owner, _assignee, _guild, _initiative, project = await _seed_populated_project(
        session
    )
    body = (
        await export_service.build_project_export(
            session, await get_project_hydrated(session, project.id)
        )
    ).model_dump(mode="json")
    board = {
        "kind": "board",
        "definition": {"limits": [{"status_id": "1", "limit": 2}]},
    }

    # What is remapped is what was checked: the id as a number.
    [layout] = ProjectExportEnvelope.model_validate(
        {**body, "layouts": [board]}
    ).layouts
    assert layout.definition == {"limits": [{"status_id": 1, "limit": 2}]}
    with pytest.raises(ValidationError):
        ProjectExportEnvelope.model_validate({**body, "layouts": [board, board]})


async def test_an_envelope_holds_a_task_page_for_each_type(session: AsyncSession):
    owner, _assignee, guild, _initiative, project = await _seed_populated_project(
        session
    )
    body = (
        await export_service.build_project_export(
            session, await get_project_hydrated(session, project.id)
        )
    ).model_dump(mode="json")
    page = {"main": [{"type": "comments"}]}
    bug_place = 1 + [t["name"] for t in body["task_types"]].index("Bug")

    # One page per type, and one with no type at all.
    layouts = ProjectExportEnvelope.model_validate(
        {
            **body,
            "layouts": [
                {"kind": "task", "definition": page},
                {"kind": "task", "task_type": bug_place, "definition": page},
            ],
        }
    ).layouts
    assert [layout.task_type for layout in layouts] == [None, bug_place]
    for refused in (
        [{"kind": "board", "task_type": bug_place, "definition": {}}],
        [{"kind": "task", "task_type": bug_place, "definition": page}] * 2,
    ):
        with pytest.raises(ValidationError):
            ProjectExportEnvelope.model_validate({**body, "layouts": refused})

    # A page that names no type is the default type's, as a marketplace
    # project's are; one naming a type the file does not list is left out.
    envelope = ProjectExportEnvelope.model_validate(
        {
            **body,
            "layouts": [
                {"kind": "task", "definition": page},
                {"kind": "task", "task_type": 99, "definition": page},
            ],
        }
    )
    target = await create_initiative(session, guild, owner, name="Target")
    await route_as(session, user_id=owner.id, guild_id=guild.id)
    result = await import_service.import_project(
        session, envelope=envelope, target_initiative=target, importer=owner
    )
    await session.commit()

    await route_session_to_guild(session, guild.id)
    rows = (
        await session.exec(
            select(ToolLayout).where(ToolLayout.tool_id == result.entity_id)
        )
    ).all()
    default = await get_default_type(session, result.entity_id)
    assert [(row.kind, row.task_type_id, row.definition) for row in rows] == [
        ("task", default.id, page)
    ]


async def test_property_type_collision_renames(session: AsyncSession):
    (
        owner,
        assignee,
        guild,
        source_initiative,
        source_project,
    ) = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(
        session, await get_project_hydrated(session, source_project.id)
    )

    target_initiative = await create_initiative(session, guild, owner, name="Target")
    # Pre-create a property in target with the same name but different type
    existing_prop = await create_property_definition(
        session,
        target_initiative,
        name="Severity",
        type=MetadataType.text,
    )

    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )

    assert result.renamed_property_count == 1

    # Original definition unchanged
    refreshed = await session.get(MetadataDefinition, existing_prop.id)
    assert refreshed.type == MetadataType.text

    # Renamed definition exists with the original type
    stmt = select(MetadataDefinition).where(
        MetadataDefinition.initiative_id == target_initiative.id,
        MetadataDefinition.name == "Severity_select",
    )
    renamed = (await session.exec(stmt)).one_or_none()
    assert renamed is not None
    assert renamed.type == MetadataType.select


async def test_property_options_mismatch_renames(session: AsyncSession):
    """Same name + type but different option values → treat as collision
    and rename. Reusing the existing definition would silently store
    values that aren't valid options on the target side."""
    (
        owner,
        assignee,
        guild,
        source_initiative,
        source_project,
    ) = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(
        session, await get_project_hydrated(session, source_project.id)
    )

    target_initiative = await create_initiative(session, guild, owner, name="Target")
    # Same name, same type (select), but completely different options
    existing_prop = await create_property_definition(
        session,
        target_initiative,
        name="Severity",
        type=MetadataType.select,
        options=[
            {"value": "critical", "label": "Critical"},
            {"value": "minor", "label": "Minor"},
        ],
    )

    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )
    assert result.renamed_property_count == 1

    # Original target definition unchanged
    refreshed = await session.get(MetadataDefinition, existing_prop.id)
    assert refreshed.options == [
        {"value": "critical", "label": "Critical"},
        {"value": "minor", "label": "Minor"},
    ]

    # Renamed import lives alongside it with the source's options
    stmt = select(MetadataDefinition).where(
        MetadataDefinition.initiative_id == target_initiative.id,
        MetadataDefinition.name == "Severity_select",
    )
    renamed = (await session.exec(stmt)).one_or_none()
    assert renamed is not None
    assert {o["value"] for o in (renamed.options or [])} == {"low", "high"}


async def test_property_options_label_only_difference_matches(session: AsyncSession):
    """Labels are cosmetic; same value set with different labels still
    counts as a match (no rename, no new definition)."""
    (
        owner,
        assignee,
        guild,
        source_initiative,
        source_project,
    ) = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(
        session, await get_project_hydrated(session, source_project.id)
    )

    target_initiative = await create_initiative(session, guild, owner, name="Target")
    await create_property_definition(
        session,
        target_initiative,
        name="Severity",
        type=MetadataType.select,
        options=[
            {"value": "low", "label": "LOW PRIORITY"},
            {"value": "high", "label": "HIGH PRIORITY"},
        ],
    )

    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )
    assert result.renamed_property_count == 0
    assert result.matched["properties"] == 1


async def test_unmatched_assignees_reported(session: AsyncSession):
    (
        owner,
        assignee,
        guild,
        source_initiative,
        source_project,
    ) = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(
        session, await get_project_hydrated(session, source_project.id)
    )

    # Target initiative has *no* members other than the owner — alice isn't a member here
    target_initiative = await create_initiative(session, guild, owner, name="Target")

    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target_initiative,
        importer=owner,
    )
    assert result.matched["assignees"] == 0
    assert result.unmatched_handles == [handle_of(assignee)]


async def test_a_thread_survives_the_round_trip(session: AsyncSession):
    """A reply is exported naming the comment it answers, and restored
    under the copy of that comment."""
    from app.models.tenant.comment import Comment
    from app.testing import create_comment

    owner, assignee, guild, initiative, project = await _seed_populated_project(session)
    task = (await session.exec(select(Task).where(Task.project_id == project.id))).one()
    question = await create_comment(session, owner, task=task, content="Question")
    await create_comment(
        session,
        assignee,
        task=task,
        content="Answer",
        parent_comment_id=question.id,
    )

    envelope = await export_service.build_project_export(
        session,
        await get_project_hydrated(session, project.id),
        exported_by_handle=handle_of(owner),
    )
    exported = {c.body: c for c in envelope.tasks[0].comments}
    assert exported["Answer"].reply_to_ref == exported["Question"].external_ref

    target = await create_initiative(session, guild, owner, name="Target Initiative")
    result = await import_service.import_project(
        session, envelope=envelope, target_initiative=target, importer=owner
    )
    new_task = (
        await session.exec(select(Task).where(Task.project_id == result.entity_id))
    ).one()
    restored = {
        c.content: c
        for c in (
            await session.exec(select(Comment).where(Comment.task_id == new_task.id))
        ).all()
    }
    assert restored["Question"].parent_comment_id is None
    assert restored["Answer"].parent_comment_id == restored["Question"].id


async def test_a_status_with_no_look_gets_its_categorys(session: AsyncSession):
    """Another tool's columns arrive with a name and a category only; each
    looks like its category rather than every one like the backlog."""
    from app.models.tenant.task import TaskStatus
    from app.schemas.tenant.project_export import ProjectExportEnvelope
    from app.services.tenant.task_statuses import defaults_for_category

    owner, _assignee, guild, _initiative, _project = await _seed_populated_project(
        session
    )
    envelope = ProjectExportEnvelope.model_validate(
        {
            "app_version": "0.0.0-test",
            "exported_at": "2026-07-15T00:00:00+00:00",
            "project": {"name": "From elsewhere"},
            "tags": [],
            "property_definitions": [],
            "layouts": [],
            "tasks": [],
            "task_statuses": [
                {"name": c.value, "category": c.value, "position": i}
                for i, c in enumerate(TaskStatusCategory)
            ],
        }
    )
    target = await create_initiative(session, guild, owner, name="Target Initiative")
    result = await import_service.import_project(
        session, envelope=envelope, target_initiative=target, importer=owner
    )
    rows = (
        await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == result.entity_id)
        )
    ).all()
    assert {r.category: (r.color, r.icon) for r in rows} == {
        c: defaults_for_category(c) for c in TaskStatusCategory
    }


async def test_legacy_envelope_keeps_carried_dates_and_consumed_count(session):
    owner, _, guild, _, project = await _seed_populated_project(session)
    envelope = await export_service.build_project_export(
        session,
        await get_project_hydrated(session, project.id),
        exported_by_handle=handle_of(owner),
    )
    old_task = envelope.tasks[0]
    old_task.recurrence_anchor = None
    old_task.recurrence_anchor_count = 0
    old_task.recurrence_occurrence_count = 2
    old_task.due_date = datetime(2026, 10, 9, 9, tzinfo=timezone.utc)
    old_task.recurrence_carry = {"due_date": "2026-10-07T09:00:00+00:00"}
    target = await create_initiative(session, guild, owner, name="Legacy restore")
    await route_as(session, user_id=owner.id, guild_id=guild.id)
    result = await import_service.import_project(
        session,
        envelope=envelope,
        target_initiative=target,
        importer=owner,
    )
    restored = (
        await session.exec(select(Task).where(Task.project_id == result.entity_id))
    ).one()
    assert restored.recurrence_anchor == datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
    assert restored.recurrence_anchor_count == 2
    from app.services.tenant.task_series import next_dates

    dates = await next_dates(
        session,
        restored,
        now=datetime(2026, 10, 10, tzinfo=timezone.utc),
        user_timezone="UTC",
    )
    assert dates is not None
    assert dates[1] == datetime(2026, 10, 14, 9, tzinfo=timezone.utc)


async def test_task_types_survive_the_round_trip(session: AsyncSession):
    """A project's types come back as they were, and each task as its type."""
    from app.models.tenant.task import TaskType

    owner, _assignee, guild, _initiative, project = await _seed_populated_project(
        session
    )
    types = await task_types_service.list_types(session, project.id)
    types[2].name = "Notion"
    types[2].is_default = True
    types[0].is_default = False
    session.add_all(types)
    session.add(
        TaskType(
            project_id=project.id,
            name="Chore",
            position=4,
            icon="repeat",
            color="#22C55E",
            layout_preset="repeat",
            starting_values={
                "recurrence": "RRULE:FREQ=WEEKLY",
                "checklist": ["Bins out"],
            },
        )
    )
    await session.commit()
    chore = (await task_types_service.list_types(session, project.id))[-1]
    task = (
        await session.exec(select(Task).where(Task.project_id == project.id))
    ).first()
    assert task is not None
    assert chore.id is not None
    task.task_type_id = chore.id
    session.add(task)
    await session.commit()

    hydrated = await get_project_hydrated(session, project.id)
    assert hydrated is not None
    envelope = await export_service.build_project_export(session, hydrated)
    assert [t.name for t in envelope.task_types] == [
        "Task",
        "Bug",
        "Notion",
        "Milestone",
        "Chore",
    ]
    target = await create_initiative(session, guild, owner, name="Target Initiative")
    result = await import_service.import_project(
        session, envelope=envelope, target_initiative=target, importer=owner
    )

    restored = await task_types_service.list_types(session, result.entity_id)
    assert [
        (t.name, t.is_default, t.icon, t.color, t.layout_preset) for t in restored
    ] == [
        ("Task", False, "square-check", "#94A3B8", "plain"),
        ("Bug", False, "bug", "#F87171", "fix"),
        ("Notion", True, "lightbulb", "#FBBF24", "discussion"),
        ("Milestone", False, "flag", "#A78BFA", "dates"),
        ("Chore", False, "repeat", "#22C55E", "repeat"),
    ]
    # What each starts a task with comes too: Chore's, and Bug's outline.
    assert restored[-1].starting_values == {
        "recurrence": "RRULE:FREQ=WEEKLY",
        "checklist": ["Bins out"],
    }
    assert restored[1].starting_values == types[1].starting_values
    copied = (
        await session.exec(select(Task).where(Task.project_id == result.entity_id))
    ).first()
    assert copied is not None
    assert copied.task_type_id == restored[-1].id


async def test_an_envelope_without_types_gets_the_starting_ones_in_the_importers_language(
    session: AsyncSession,
):
    owner, _assignee, guild, _initiative, _project = await _seed_populated_project(
        session
    )
    owner.locale = "es"
    session.add(owner)
    await session.commit()
    envelope = ProjectExportEnvelope.model_validate(
        {
            "app_version": "0.0.0-test",
            "exported_at": "2026-07-15T00:00:00+00:00",
            "project": {"name": "Antes de los tipos"},
            "tags": [],
            "property_definitions": [],
            "task_statuses": [{"name": "To Do", "category": "todo"}],
            "layouts": [],
            "tasks": [
                {
                    "title": "Algo",
                    "status_name": "To Do",
                    "type_name": "Bug",
                    "tags": [],
                    "assignee_handles": [],
                    "checklist": [],
                    "properties": [],
                }
            ],
        }
    )
    target = await create_initiative(session, guild, owner, name="Target Initiative")

    result = await import_service.import_project(
        session, envelope=envelope, target_initiative=target, importer=owner
    )

    restored = await task_types_service.list_types(session, result.entity_id)
    assert [t.name for t in restored] == ["Tarea", "Error", "Idea", "Hito"]
    task = (
        await session.exec(select(Task).where(Task.project_id == result.entity_id))
    ).one()
    # A type the project does not have is its default.
    assert task.task_type_id == restored[0].id
