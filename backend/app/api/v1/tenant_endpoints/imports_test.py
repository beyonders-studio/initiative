"""Tests for the import engine: envelopes, foreign files, Jira, backups."""

import io
import json
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy.orm import undefer

from app.models.platform.guild import CommunityRole
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.services.guild_sweeps import Scope, each_guild
from app.services.import_engine import worker as import_worker
from app.services.storage import get_guild_storage
from app.core.tools import CHILD_KINDS, KINDS, Tool
from app.testing.factories import (
    create_child_entity,
    create_tool_entity,
    assign_tag,
    guild_administration,
    create_calendar_event,
    create_counter_group,
    create_file,
    create_import_job,
    create_initiative,
    create_queue,
    create_tag,
    create_task,
    grant_role_permission,
    png_bytes,
    route_session_to_guild,
)
from app.services.import_engine import limits as import_limits
from app.schemas.tenant.tag import annotated_tags
from app.services.tenant import tags as tags_service
from app.db.request_context import SystemGuild
from app.testing import drain_notices


# ---------------------------------------------------------------------------
# Import engine: envelope imports + job lifecycle
# ---------------------------------------------------------------------------


async def _export_json(client, a, endpoint, params):
    resp = await client.get(
        a.g(endpoint), headers=a.headers, params={**params, "format": "json"}
    )
    assert resp.status_code == 200, resp.text
    return json.loads(resp.content)


async def _import_envelope(client, actor, envelope, initiative_id):
    return await client.post(
        actor.g("/imports/envelope"),
        headers=actor.headers,
        json={"initiative_id": initiative_id, "envelope": envelope},
    )


async def _second_initiative(session, a, **flags):
    initiative = await create_initiative(
        session, a.guild, a.user, name="Import Target", **flags
    )
    return initiative


async def test_envelope_import_roundtrips_queue(client, acting_user, session):
    """Export a queue as its envelope, import it into another initiative:
    items, rotation state, and the queue's tags survive; the importer gets an
    owner grant; tags match-or-create against the guild."""
    from sqlmodel import select

    from app.models.tenant.queue import Queue, QueueItem
    from app.models.tenant.resource_grant import ResourceGrant

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    queue = await create_queue(session, a.initiative, a.user, name="Turn Order")
    from app.models.tenant.queue import QueueItem as QI

    for i, label in enumerate(["Aria", "Brock"]):
        session.add(QI(queue_id=queue.id, label=label, position=float(i)))
    await assign_tag(session, queue, await create_tag(session, a.guild, name="Raid"))
    await session.commit()

    envelope = await _export_json(client, a, "/exports/queue", {"ids": [queue.id]})
    assert envelope["type"] == "initiative-queue"
    # A name listed again in another case is the same tag, attached once.
    envelope["tags"].append("raid")

    target = await _second_initiative(session, a, queues_enabled=True)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert result["created"]["queues"] == 1
    assert result["created"]["items"] == 2
    assert result["matched"]["tags"] == 1

    imported = (
        await session.exec(
            select(Queue).where(
                Queue.initiative_id == target.id, Queue.name == "Turn Order"
            )
        )
    ).one()
    items = list(
        await session.exec(select(QueueItem).where(QueueItem.queue_id == imported.id))
    )
    assert {i.label for i in items} == {"Aria", "Brock"}
    await tags_service.annotate_tags(session, [imported])
    assert [tag.name for tag in annotated_tags(imported)] == ["Raid"]
    grant = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "queue",
                ResourceGrant.resource_id == imported.id,
                ResourceGrant.user_id == a.user.id,
            )
        )
    ).one()
    assert str(grant.level) in ("owner", "ResourceAccessLevel.owner")


async def test_envelope_import_roundtrips_counter_group(client, acting_user, session):
    from sqlmodel import select

    from app.models.tenant.counter import Counter, CounterGroup

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    group = await create_counter_group(session, a.initiative, a.user, name="Party Gold")
    from app.models.tenant.counter import Counter as C
    from decimal import Decimal

    session.add(
        C(
            counter_group_id=group.id,
            name="GP",
            count=Decimal("42.5"),
            step=Decimal("1"),
            initial_count=Decimal("0"),
            position=Decimal("0"),
        )
    )
    await assign_tag(session, group, await create_tag(session, a.guild, name="Loot"))
    await session.commit()

    envelope = await _export_json(
        client, a, "/exports/counter_group", {"ids": [group.id]}
    )
    assert envelope["tags"] == ["Loot"]
    target = await _second_initiative(session, a, counter_groups_enabled=True)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text

    imported = (
        await session.exec(
            select(CounterGroup).where(
                CounterGroup.initiative_id == target.id,
                CounterGroup.name == "Party Gold",
            )
        )
    ).one()
    counter = (
        await session.exec(
            select(Counter).where(Counter.counter_group_id == imported.id)
        )
    ).one()
    assert counter.name == "GP"
    assert float(counter.count) == 42.5
    await tags_service.annotate_tags(session, [imported])
    assert [tag.name for tag in annotated_tags(imported)] == ["Loot"]


async def test_envelope_import_roundtrips_file_types(client, acting_user, session):
    """Native, spreadsheet, smart link, and whiteboard envelopes import with
    their content models restored (whiteboard unwrapped from the Excalidraw
    file shape, spreadsheet re-normalized)."""
    from sqlmodel import select

    from app.core.file_types import FileType

    from app.models.tenant.file import File

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    target = await _second_initiative(session, a)

    native = await create_file(
        session,
        a.initiative,
        a.user,
        name="Notes",
        content={"root": {"type": "root", "children": []}},
    )
    board = await create_file(
        session,
        a.initiative,
        a.user,
        name="Map",
        file_type=FileType.excalidraw,
        content={"elements": [{"type": "rectangle"}], "appState": {}, "files": {}},
    )
    link = await create_file(
        session,
        a.initiative,
        a.user,
        name="Spec",
        file_type=FileType.url,
        content={"url": "https://example.com/spec"},
    )

    for doc, doc_type in (
        (native, "lexical"),
        (board, "excalidraw"),
        (link, "url"),
    ):
        envelope = await _export_json(client, a, "/exports/file", {"ids": [doc.id]})
        resp = await _import_envelope(client, a, envelope, target.id)
        assert resp.status_code == 201, (doc_type, resp.text)

    imported = list(
        await session.exec(
            select(File)
            .where(File.initiative_id == target.id)
            .options(undefer(File.content))
        )
    )
    by_name = {d.name: d for d in imported}
    assert set(by_name) == {"Notes", "Map", "Spec"}
    assert by_name["Map"].content["elements"] == [{"type": "rectangle"}]
    assert "type" not in by_name["Map"].content  # unwrapped, not the file shape
    assert by_name["Spec"].content == {"url": "https://example.com/spec"}


async def test_envelope_import_roundtrips_calendar(client, acting_user, session):
    from datetime import timedelta

    from sqlmodel import select

    from app.models.tenant.calendar import Calendar
    from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee
    from app.testing.factories import create_calendar

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    a.initiative.calendars_enabled = True
    session.add(a.initiative)
    await session.commit()
    calendar = await create_calendar(session, a.initiative, a.user, name="Raid Nights")
    await assign_tag(
        session, calendar, await create_tag(session, a.guild, name="Raids"), commit=True
    )
    zero = await create_calendar_event(
        session, calendar, a.user, title="Session Zero", recurrence="RRULE:FREQ=WEEKLY"
    )
    await create_calendar_event(session, calendar, a.user, title="One-shot")
    # Its second week, changed alone, comes across as its second week.
    second = zero.start_at + timedelta(weeks=1)
    await create_calendar_event(
        session,
        calendar,
        a.user,
        title="Session Zero, again",
        start_at=second,
        end_at=second + timedelta(hours=1),
        series_id=zero.id,
        original_start=second,
    )

    envelope = await _export_json(
        client, a, "/exports/calendar", {"initiative_id": a.initiative.id}
    )
    assert envelope["type"] == "initiative-calendar"

    target = await _second_initiative(session, a, calendars_enabled=True)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    created = resp.json()["result"]["created"]
    assert created["calendars"] == 1
    assert created["events"] == 3

    imported_calendar = (
        await session.exec(select(Calendar).where(Calendar.initiative_id == target.id))
    ).one()
    assert imported_calendar.name == "Raid Nights"
    await tags_service.annotate_tags(session, [imported_calendar])
    assert [tag.name for tag in annotated_tags(imported_calendar)] == ["Raids"]
    imported = list(
        await session.exec(
            select(CalendarEvent).where(
                CalendarEvent.calendar_id == imported_calendar.id
            )
        )
    )
    by_title = {e.title: e for e in imported}
    assert set(by_title) == {"Session Zero", "One-shot", "Session Zero, again"}
    again = by_title["Session Zero, again"]
    assert (again.series_id, again.original_start, again.overridden_fields) == (
        by_title["Session Zero"].id,
        second,
        ["attendees", "properties", "tags", "title"],
    )
    # The exporter was the only attendee-resolvable member; attendee rows for
    # the creator resolve by email.
    attendees = list(
        await session.exec(
            select(CalendarEventAttendee).where(
                CalendarEventAttendee.calendar_event_id.in_([e.id for e in imported])
            )
        )
    )
    assert all(att.user_id == a.user.id for att in attendees)


async def _tool_with_a_row(session, a, tool):
    """A ``tool`` row in ``a``'s initiative and, where the tool holds rows that
    carry properties of their own, one of those."""
    row = await create_tool_entity(session, Tool(tool), a.initiative, a.user)
    inside = next((k for k in CHILD_KINDS if KINDS[k].parent is Tool(tool)), None)
    if inside is None:
        return row, None
    return row, await create_child_entity(session, inside, row, a.user)


@pytest.mark.parametrize(
    "tool",
    [
        "project",
        "queue",
        "counter_group",
        "calendar",
        "catalog",
        "wiki",
        "dashboard",
        "post",
    ],
)
async def test_a_tools_tags_and_properties_survive_export_and_import(
    client, acting_user, session, monkeypatch, tmp_path, tool
):
    """The tool row's tag comes back on the row the import makes, and so do a
    value on the tool row and one on a row inside it: matched by name into the
    target initiative, and a person value placed on the member its handle
    names."""
    from sqlmodel import select

    from app.api.v1.tenant_endpoints.exports_test import _all_tools_enabled
    from app.core.config import settings
    from app.models.tenant.property import (
        PropertyDefinition,
        PropertyType,
        PropertyValue,
    )
    from app.services.tenant.properties import PROPERTY_LINKS, link_for
    from app.testing.factories import create_property_definition, create_property_value

    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _all_tools_enabled(session, a.initiative)
    target = await _second_initiative(session, a)
    await _all_tools_enabled(session, target)
    stage = await create_property_definition(session, a.initiative, name="Stage")
    owner = await create_property_definition(
        session, a.initiative, name="Owner", type=PropertyType.user_reference
    )
    row, inner = await _tool_with_a_row(session, a, tool)
    await assign_tag(session, row, await create_tag(session, a.guild, name="Flagship"))
    await create_property_value(session, row, stage, value_text="Draft")
    # A row inside the tool keeps its own tag too, where its kind takes tags.
    inner_tagged = inner is not None and any(
        spec.entity is type(inner) for spec in tags_service.TAG_LINKS.values()
    )
    if inner is not None:
        await create_property_value(session, inner, owner, value_user_id=a.user.id)
    if inner_tagged:
        await assign_tag(
            session, inner, await create_tag(session, a.guild, name="Inner")
        )

    exported = await client.get(
        a.g(f"/exports/{tool}"),
        headers=a.headers,
        params={"ids": [row.id], "format": "json"},
    )
    assert exported.status_code == 200, exported.text
    if exported.headers["content-type"] == "application/zip":
        resp = await _import_archive(client, a, exported.content, target.id)
    else:
        resp = await _import_envelope(client, a, exported.json(), target.id)
    assert resp.status_code == 201, resp.text

    async def values(target_name, entity_id):
        return (
            await session.exec(
                select(
                    PropertyDefinition.name,
                    PropertyDefinition.initiative_id,
                    PropertyValue.value_text,
                    PropertyValue.value_user_id,
                )
                .join(PropertyDefinition)
                .where(
                    PropertyValue.entity_type == target_name,
                    PropertyValue.entity_id == entity_id,
                )
            )
        ).all()

    spec = PROPERTY_LINKS[tool]
    restored = (
        await session.exec(
            select(spec.model).where(spec.model.initiative_id == target.id)
        )
    ).one()
    await tags_service.annotate_tags(session, [restored])
    assert [tag.name for tag in annotated_tags(restored)] == ["Flagship"]
    assert await values(tool, restored.id) == [("Stage", target.id, "Draft", None)]
    if inner is not None:
        inner_spec = link_for(inner)
        restored_inner = (
            await session.exec(
                select(inner_spec.model).where(
                    getattr(inner_spec.model, inner_spec.via) == restored.id
                )
            )
        ).one()
        assert await values(inner_spec.target, restored_inner.id) == [
            ("Owner", target.id, None, a.user.id)
        ]
        if inner_tagged:
            await tags_service.annotate_tags(session, [restored_inner])
            assert [tag.name for tag in annotated_tags(restored_inner)] == ["Inner"]


async def test_a_renamed_property_is_one_definition_for_every_row(
    client, acting_user, session
):
    """A property whose name the target already uses for another type is
    renamed once, every imported row naming it shares that one, and importing
    again lands on it rather than renaming it again."""
    from sqlmodel import select

    from app.api.v1.tenant_endpoints.exports_test import _all_tools_enabled
    from app.models.tenant.property import (
        PropertyDefinition,
        PropertyType,
        PropertyValue,
    )
    from app.testing.factories import (
        create_property_definition,
        create_property_value,
        create_queue,
        create_queue_item,
    )

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _all_tools_enabled(session, a.initiative)
    target = await _second_initiative(session, a)
    await _all_tools_enabled(session, target)
    status = await create_property_definition(session, a.initiative, name="Status")
    await create_property_definition(
        session, target, name="Status", type=PropertyType.number
    )
    queue = await create_queue(session, a.initiative, a.user)
    for label in ("First", "Second"):
        item = await create_queue_item(session, queue, label=label)
        await create_property_value(session, item, status, value_text=label)

    envelope = await _export_json(client, a, "/exports/queue", {"ids": [queue.id]})
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text

    names = (
        await session.exec(
            select(PropertyDefinition.name)
            .join(PropertyValue)
            .where(
                PropertyValue.entity_type == "queue_item",
                PropertyDefinition.initiative_id == target.id,
            )
        )
    ).all()
    assert names == ["Status_text", "Status_text"]

    again = await _import_envelope(client, a, envelope, target.id)
    assert again.status_code == 201, again.text
    definitions = (
        await session.exec(
            select(PropertyDefinition.name).where(
                PropertyDefinition.initiative_id == target.id
            )
        )
    ).all()
    assert sorted(definitions) == ["Status", "Status_text"]


async def test_envelope_import_project_replaces_legacy_route(
    client, acting_user, session
):
    """The engine is the project import path now: the legacy POST
    /projects/import is gone (404), and the same envelope imports through
    /imports/envelope with tasks and statuses recreated."""
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task(session, a.project, title="Fell the tower")

    envelope = await _export_json(
        client, a, "/exports/project", {"ids": [a.project.id]}
    )
    assert envelope["type"] == "initiative-project"

    legacy = await client.post(
        a.g("/projects/import"),
        headers=a.headers,
        json={"initiative_id": a.initiative.id, "envelope": envelope},
    )
    assert legacy.status_code in (404, 405)

    target = await _second_initiative(session, a)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert result["created"]["tasks"] == 1

    project = (
        await session.exec(select(Project).where(Project.initiative_id == target.id))
    ).one()
    task = (await session.exec(select(Task).where(Task.project_id == project.id))).one()
    assert task.title == "Fell the tower"


async def test_envelope_import_authorization_gates(client, acting_user, session):
    """Unknown type 400; bad version 400; a link that isn't http(s) 400; tool
    switch off 400; a member without the create permission 403; an
    unreachable initiative 404."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    doc_envelope = {
        "type": "initiative-file",
        "schema_version": 1,
        "file_type": "url",
        "name": "Doc",
        "content": {"url": "https://example.com"},
        "tags": [],
        "properties": [],
    }

    unknown = await _import_envelope(
        client, a, {**doc_envelope, "type": "initiative-wands"}, a.initiative.id
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == "IMPORT_UNKNOWN_TYPE"

    future = await _import_envelope(
        client, a, {**doc_envelope, "schema_version": 99}, a.initiative.id
    )
    assert future.status_code == 400
    assert future.json()["detail"] == "IMPORT_SCHEMA_VERSION_UNSUPPORTED"

    not_a_link = await _import_envelope(
        client,
        a,
        {**doc_envelope, "content": {"url": "javascript:alert(1)"}},
        a.initiative.id,
    )
    assert not_a_link.status_code == 400
    assert not_a_link.json()["detail"] == "FILE_SMART_LINK_URL_INVALID"

    queue_envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Q",
        "items": [],
    }
    a.initiative.queues_enabled = False
    session.add(a.initiative)
    await session.commit()
    disabled = await _import_envelope(client, a, queue_envelope, a.initiative.id)
    assert disabled.status_code == 400
    assert disabled.json()["detail"] == "IMPORT_TOOL_DISABLED"

    # A plain member-role actor lacks create_files (defaults False).
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    denied = await _import_envelope(client, b, doc_envelope, a.initiative.id)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "IMPORT_PERMISSION_REQUIRED"

    # A guild member outside the initiative: the structural initiative row is
    # guild-visible (only content is initiative-hidden), so this is a clean
    # permission refusal, not a 404.
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    hidden = await _import_envelope(client, outsider, doc_envelope, a.initiative.id)
    assert hidden.status_code == 403


async def test_large_envelope_becomes_job_and_worker_applies_it(
    client, acting_user, session, monkeypatch, role_session
):
    """Above the inline threshold the payload is staged (the row holds no
    content) and the worker applies it as the creator, persists the result,
    deletes the payload, and notifies."""
    from sqlmodel import select

    from app.models.platform.notification import Notification, NotificationType
    from app.models.tenant.queue import Queue

    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Big Queue",
        "items": [{"label": f"Item {i}", "position": float(i)} for i in range(3)],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    job_id = body["id"]
    assert body["status"] == ImportJobStatus.queued.value
    assert body["params"] == {"initiative_id": a.initiative.id}
    # The row holds options only — the envelope content is staged in storage,
    # and the storage key itself is not exposed through the API.
    assert "items" not in json.dumps(body)
    assert "payload_ref" not in body

    await _run_import_worker(monkeypatch, role_session)

    status_resp = await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    job = status_resp.json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["created"]["queues"] == 1
    assert job["result"]["created"]["items"] == 3

    # The staged payload was deleted on the terminal transition.
    from app.testing import route_session_to_guild

    await route_session_to_guild(session, a.guild.id)
    row = await session.get(ImportJob, job_id)
    assert row is not None and row.payload_ref is None

    imported = (
        await session.exec(select(Queue).where(Queue.name == "Big Queue"))
    ).one()
    assert imported.created_by == a.user.id  # applied AS the creator

    await drain_notices()
    notifications = list(
        await session.exec(
            select(Notification).where(Notification.user_id == a.user.id)
        )
    )
    ready = [n for n in notifications if n.type == NotificationType.import_ready]
    assert len(ready) == 1
    assert ready[0].data["import_job_id"] == job_id


async def test_worker_fails_closed_on_revoked_permission(
    client, acting_user, session, monkeypatch, role_session
):
    """Create permission revoked between enqueue and apply → the job fails
    with IMPORT_PERMISSION_REQUIRED and nothing is created."""
    from sqlalchemy import delete as sa_delete
    from sqlmodel import select

    from app.models.tenant.initiative import InitiativeMember
    from app.models.tenant.queue import Queue

    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Doomed Queue",
        "items": [],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    await session.exec(
        sa_delete(InitiativeMember).where(
            InitiativeMember.initiative_id == a.initiative.id,
            InitiativeMember.user_id == a.user.id,
        )
    )
    await session.commit()

    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    # RLS hides the initiative from a non-member (404-shaped), or the
    # permission check refuses — both fail closed.
    assert job["error"] in ("IMPORT_PERMISSION_REQUIRED", "IMPORT_INVALID_PARAMS")
    assert (
        await session.exec(select(Queue).where(Queue.name == "Doomed Queue"))
    ).one_or_none() is None


async def test_stale_running_import_fails_closed_not_reapplied(
    acting_user, session, monkeypatch, role_session
):
    """A running row older than the stale threshold is FAILED, never re-run
    (an interrupted apply may have committed rows already)."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    job = await create_import_job(
        session,
        a.guild,
        a.user,
        source="initiative-queue",
        params={"initiative_id": a.initiative.id},
        payload_ref="imports/gone.json",
        status=ImportJobStatus.running,
        created_at=stale_time,
        updated_at=stale_time,
    )

    await _run_import_worker(monkeypatch, role_session)

    await session.refresh(job)
    assert job.status == ImportJobStatus.failed
    assert job.error == "IMPORT_INTERRUPTED"


async def test_import_job_cap_and_cancel(client, acting_user, session, monkeypatch):
    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 0)
    monkeypatch.setattr(import_limits, "IMPORT_MAX_ACTIVE_JOBS_PER_USER", 1)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Q",
        "items": [],
    }
    first = await _import_envelope(client, a, envelope, a.initiative.id)
    assert first.status_code == 202
    second = await _import_envelope(client, a, envelope, a.initiative.id)
    assert second.status_code == 429
    assert second.json()["detail"] == "IMPORT_JOB_LIMIT_REACHED"

    job_id = first.json()["id"]
    cancelled = await client.delete(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == ImportJobStatus.cancelled.value

    # Cancelling freed the cap slot.
    third = await _import_envelope(client, a, envelope, a.initiative.id)
    assert third.status_code == 202

    # A terminal job is not cancellable.
    not_again = await client.delete(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    assert not_again.status_code == 409


async def test_import_jobs_are_own_row_isolated(
    client, acting_user, session, monkeypatch
):
    """Another member sees neither the job nor its row (RLS, 404); a guild
    admin sees it via the admin leg."""
    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Mine",
        "items": [],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    job_id = resp.json()["id"]

    other = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)

    denied = await client.get(a.g(f"/imports/jobs/{job_id}"), headers=other.headers)
    assert denied.status_code == 404
    assert (await client.get(a.g("/imports/jobs"), headers=other.headers)).json() == []
    allowed = await client.get(a.g(f"/imports/jobs/{job_id}"), headers=admin.headers)
    assert allowed.status_code == 200


async def test_envelope_byte_bound_enforced_before_body_is_read(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """The byte bound lives in ASGI middleware, not the handler: an honest
    Content-Length is refused before any body is read, and a chunked
    (length-less) stream is cut off as soon as it exceeds the limit — the
    server never buffers more than the cap."""
    monkeypatch.setattr(import_limits, "IMPORT_MAX_ENVELOPE_BYTES", 1024)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    big_body = json.dumps(
        {
            "initiative_id": a.initiative.id,
            "envelope": {
                "type": "initiative-queue",
                "schema_version": 1,
                "name": "Q",
                "items": [],
                "padding": "x" * 4096,
            },
        }
    ).encode("utf-8")

    # Declared length over the cap: 413 straight from the header.
    declared = await client.post(
        a.g("/imports/envelope"),
        headers={**a.headers, "Content-Type": "application/json"},
        content=big_body,
    )
    assert declared.status_code == 413
    assert declared.json()["detail"] == "IMPORT_TOO_LARGE"

    # Chunked transfer (no Content-Length): the streaming backstop cuts the
    # request off mid-body instead of buffering it all.
    async def chunks():
        for i in range(0, len(big_body), 512):
            yield big_body[i : i + 512]

    chunked = await client.post(
        a.g("/imports/envelope"),
        headers={**a.headers, "Content-Type": "application/json"},
        content=chunks(),
    )
    assert chunked.status_code == 413
    assert chunked.json()["detail"] == "IMPORT_TOO_LARGE"

    # An under-cap request still works — the bound didn't break the route.
    ok = await _import_envelope(
        client,
        a,
        {"type": "initiative-queue", "schema_version": 1, "name": "Q", "items": []},
        a.initiative.id,
    )
    assert ok.status_code == 201


# ---------------------------------------------------------------------------
# Backup-zip imports
# ---------------------------------------------------------------------------


def _make_backup_zip(manifest: dict, members: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in (members or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _minimal_manifest(initiative_id=1, name="Restored", entries=None, assets=None):
    return {
        "type": "initiative-backup",
        "schema_version": 1,
        "app_version": "0.0.0-test",
        "exported_at": "2026-07-15T00:00:00+00:00",
        "exported_by_handle": "tester#0001",
        "source_instance_url": None,
        "guild": {"id": 999, "name": "Source Guild"},
        "include_uploads": bool(assets),
        "initiatives": [
            {
                "id": initiative_id,
                "name": name,
                "description": "from backup",
                "color": "#aabbcc",
                "tools": {
                    "project": "included",
                    "file": "included",
                    "queue": "included",
                    "counter_group": "disabled",
                    "calendar_event": "included",
                },
            }
        ],
        "entries": entries or [],
        "assets": assets or [],
        "skipped": [],
    }


def _queue_entry(initiative_id=1):
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Restored Queue",
        "items": [{"label": "Aria", "position": 1.0}],
    }
    entry = {
        "path": "initiatives/1-restored/queues/1-restored-queue.initiative-queue.json",
        "tool": "queue",
        "type": "initiative-queue",
        "schema_version": 1,
        "entity_id": 1,
        "title": "Restored Queue",
        "initiative_id": initiative_id,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    return entry, envelope


def _file_entry(key, *, entity_id=1, title="Handout", tags=()):
    """A manifest entry for an uploaded file whose blob is ``assets/<key>``."""
    return {
        "path": f"assets/{key}",
        "tool": "file",
        "type": "file",
        "schema_version": None,
        "entity_id": entity_id,
        "title": title,
        "initiative_id": 1,
        "tags": list(tags),
        "properties": [],
        "asset": f"assets/{key}",
    }


def _asset_record(
    key,
    *,
    size_bytes,
    content_type="application/pdf",
    original_filename=None,
    referenced_by=(),
):
    """A manifest's record of one file under ``assets/``."""
    return {
        "path": f"assets/{key}",
        "storage_key": key,
        "original_filename": original_filename or key,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "referenced_by": list(referenced_by),
    }


async def _upload_backup(client, actor, zip_bytes):
    return await client.post(
        actor.g("/imports/backup"),
        headers=actor.headers,
        files={"file": ("backup.zip", zip_bytes, "application/zip")},
    )


async def _apply_backup(client, actor, zip_bytes, monkeypatch, role_session) -> dict:
    """Upload → confirm → worker → the finished job row."""
    resp = await _upload_backup(client, actor, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    confirmed = await client.post(
        actor.g(f"/imports/jobs/{job_id}/confirm"), headers=actor.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)
    return (
        await client.get(actor.g(f"/imports/jobs/{job_id}"), headers=actor.headers)
    ).json()


async def _run_import_worker(monkeypatch, role_session):
    user_session = await role_session("app_admin")
    monkeypatch.setattr(
        import_worker, "_open_user_session", lambda _guild_id: user_session
    )
    await import_worker.process_import_jobs()


async def test_backup_import_end_to_end_with_assets(
    client, acting_user, session, monkeypatch, role_session
):
    """Upload → plan → confirm → worker apply: a new initiative appears with
    the manifest's tool switches and the importer as manager; entries apply
    through the per-type importers; the uploaded file's blob is restored
    (deduped here — same guild, key already exists) and quota-checked."""
    from sqlmodel import select

    from app.models.tenant.file import File
    from app.models.tenant.initiative import Initiative, InitiativeMember
    from app.models.tenant.queue import Queue

    from app.testing.factories import create_upload

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    payload = b"%PDF-restored-handout"
    # The blob and its uploads row already exist in this guild (the re-import
    # case) — the restore must dedupe on the storage key, not overwrite.
    get_guild_storage(a.guild.id).write(
        "restore-me.pdf", payload, content_type="application/pdf"
    )
    await create_upload(
        session,
        a.guild,
        a.user,
        filename="restore-me.pdf",
        size_bytes=len(payload),
        content_type="application/pdf",
    )

    entry, envelope = _queue_entry()
    file_entry = _file_entry("restore-me.pdf", entity_id=2, tags=["restored"])
    manifest = _minimal_manifest(
        entries=[entry, file_entry],
        assets=[
            _asset_record(
                "restore-me.pdf",
                size_bytes=len(payload),
                original_filename="Handout.pdf",
                referenced_by=["initiatives/1-restored/files/2-handout"],
            )
        ],
    )
    zip_bytes = _make_backup_zip(
        manifest,
        {
            entry["path"]: json.dumps(envelope).encode(),
            "assets/restore-me.pdf": payload,
        },
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    job_id = body["id"]
    assert body["status"] == ImportJobStatus.staged.value
    plan = body["plan"]
    assert plan["source_community_name"] == "Source Guild"
    assert plan["initiatives"][0]["proposed_name"] == "Restored"
    assert plan["initiatives"][0]["entry_counts"] == {"queue": 1, "file": 1}
    assert plan["asset_count"] == 1
    assert plan["asset_bytes"] == len(payload)

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == ImportJobStatus.queued.value

    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    result = job["result"]
    assert result["per_tool"]["queue"]["created"] == 1
    assert result["per_tool"]["file"]["created"] == 1
    # Same guild: the storage key already existed, so the blob deduped.
    assert result["assets_deduped"] == 1
    assert result["assets_restored"] == 0

    restored = (
        await session.exec(select(Initiative).where(Initiative.name == "Restored"))
    ).one()
    assert restored.description == "from backup"
    assert restored.queues_enabled is True
    assert restored.counter_groups_enabled is False  # "disabled" in manifest
    member = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == restored.id
            )
        )
    ).one()
    assert member.user_id == a.user.id

    queue = (
        await session.exec(select(Queue).where(Queue.initiative_id == restored.id))
    ).one()
    assert queue.name == "Restored Queue"
    file_doc = (
        await session.exec(
            select(File).where(
                File.initiative_id == restored.id,
                File.current_version_id.is_not(None),
            )
        )
    ).one()
    assert file_doc.name == "Handout"
    # The restored file is the file's version 1, typed from its bytes.
    version = file_doc.current_version
    assert version is not None and version.version_number == 1
    assert version.file_url.endswith("/restore-me.pdf")
    assert version.original_filename == "Handout.pdf"
    assert version.file_content_type == "application/pdf"


async def test_backup_belongs_to_the_seat(client, acting_user, session):
    """Restoring a community's backup sits with the seat that exports one —
    an ordinary admin is refused, as a member is."""
    seat = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=seat.guild)
    member = await acting_user(guild_role=CommunityRole.member, guild=seat.guild)
    zip_bytes = _make_backup_zip(_minimal_manifest())
    for caller in (admin, member):
        denied = await _upload_backup(client, caller, zip_bytes)
        assert denied.status_code == 403, caller.membership.role
        assert denied.json()["detail"] == "IMPORT_SUPERADMIN_REQUIRED"


async def test_backup_rejects_invalid_and_bomb_zips(
    client, acting_user, session, monkeypatch
):
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    garbage = await _upload_backup(client, a, b"not a zip at all")
    assert garbage.status_code == 400
    assert garbage.json()["detail"] == "IMPORT_ZIP_INVALID"

    traversal = _make_backup_zip(_minimal_manifest(), {"../escape.txt": b"x"})
    escaped = await _upload_backup(client, a, traversal)
    assert escaped.status_code == 400
    assert escaped.json()["detail"] == "IMPORT_ZIP_INVALID"

    monkeypatch.setattr(import_limits, "IMPORT_MAX_ZIP_MEMBERS", 1)
    entry, envelope = _queue_entry()
    bomb = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    too_many = await _upload_backup(client, a, bomb)
    assert too_many.status_code == 400
    assert too_many.json()["detail"] == "IMPORT_TOO_LARGE"

    monkeypatch.setattr(import_limits, "IMPORT_MAX_ZIP_MEMBERS", 20_000)
    future = _make_backup_zip({**_minimal_manifest(), "schema_version": 99})
    unsupported = await _upload_backup(client, a, future)
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"] == "IMPORT_SCHEMA_VERSION_UNSUPPORTED"


async def test_backup_rejects_asset_key_with_path_components(
    client, acting_user, session
):
    """An asset storage_key is both the uploads-row identity and the storage
    write target; the backends key by basename. A backup whose key carries path
    components is rejected whole at upload, leaving an existing blob of the same
    basename untouched and creating no second uploads row."""
    from sqlmodel import select

    from app.models.tenant.upload import Upload
    from app.testing import route_session_to_guild
    from app.testing.factories import create_upload

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    original = b"%PDF-original"
    get_guild_storage(a.guild.id).write(
        "keep.pdf", original, content_type="application/pdf"
    )
    await create_upload(
        session,
        a.guild,
        a.user,
        filename="keep.pdf",
        size_bytes=len(original),
        content_type="application/pdf",
    )

    manifest = _minimal_manifest(
        assets=[
            {
                "path": "assets/nested/keep.pdf",
                "storage_key": "nested/keep.pdf",
                "original_filename": "keep.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(original),
                "referenced_by": [],
            }
        ],
    )
    zip_bytes = _make_backup_zip(
        manifest, {"assets/nested/keep.pdf": b"REPLACED-BYTES"}
    )
    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_ZIP_INVALID"

    blob = get_guild_storage(a.guild.id).open_readable("keep.pdf")
    assert blob is not None and blob.path.read_bytes() == original
    await route_session_to_guild(session, a.guild.id)
    rows = (await session.exec(select(Upload))).all()
    assert [u.filename for u in rows] == ["keep.pdf"]


def test_reject_non_flat_asset_keys_unit():
    """The one choke point both plan and apply funnel through: flat keys pass;
    a storage_key or file-entry asset with path components raises."""
    from app.schemas.tenant.backup_export import (
        BackupManifest,
        ManifestAsset,
        ManifestEntry,
    )
    from app.services.import_engine.backup import _reject_non_flat_asset_keys
    from app.services.import_engine.contract import ImportEngineError

    def _manifest(assets=None, entries=None):
        return BackupManifest(
            type="initiative-backup",
            schema_version=1,
            app_version="0.0.0-test",
            exported_at="2026-07-15T00:00:00+00:00",
            guild={"id": 1, "name": "g"},
            include_uploads=True,
            initiatives=[],
            entries=entries or [],
            assets=assets or [],
            skipped=[],
        )

    def _asset(storage_key):
        return ManifestAsset(path=f"assets/{storage_key}", storage_key=storage_key)

    def _file_entry(asset_ref):
        return ManifestEntry(
            path=asset_ref,
            tool="file",
            type="file",
            entity_id=1,
            title="f",
            initiative_id=1,
            asset=asset_ref,
        )

    # Flat keys pass (a legit export only ever emits these).
    _reject_non_flat_asset_keys(_manifest(assets=[_asset("abc123.pdf")]))
    _reject_non_flat_asset_keys(_manifest(entries=[_file_entry("assets/abc123.pdf")]))

    # Path components in the asset key (incl. self-collision spellings) reject.
    for bad in ("nested/keep.pdf", "a/b/keep.pdf", "./keep.pdf"):
        with pytest.raises(ImportEngineError) as exc:
            _reject_non_flat_asset_keys(_manifest(assets=[_asset(bad)]))
        assert exc.value.code == "IMPORT_ZIP_INVALID"

    # And in a file entry's asset reference.
    with pytest.raises(ImportEngineError):
        _reject_non_flat_asset_keys(
            _manifest(entries=[_file_entry("assets/nested/keep.pdf")])
        )


async def test_backup_confirm_include_map_skips_tools(
    client, acting_user, session, monkeypatch, role_session
):
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"include": {"queue": False}},
    )
    assert confirmed.status_code == 200

    await _run_import_worker(monkeypatch, role_session)
    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["per_tool"]["queue"]["skipped"] == 1
    assert job["result"]["per_tool"]["queue"]["created"] == 0


async def test_an_archive_from_before_files_restores_its_documents(
    client, acting_user, session, monkeypatch, role_session
):
    """An archive written while files were documents names them that way: the
    manifest's tool and switch, the envelope type and the key holding the
    file's type. A restore reads each as the file it is."""
    from sqlmodel import select

    from app.core.file_types import FileType

    from app.models.tenant.file import File

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    envelope = {
        "type": "initiative-document",
        "schema_version": 1,
        "document_type": "url",
        "name": "Old link",
        "content": {"url": "https://example.com"},
        "tags": [],
        "properties": [],
    }
    entry = {
        "path": "initiatives/1-restored/documents/1-old-link.json",
        "tool": "document",
        "type": "initiative-document",
        "schema_version": 1,
        "entity_id": 1,
        "title": "Old link",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    manifest = _minimal_manifest(entries=[entry])
    manifest["initiatives"][0]["tools"] = {"document": "included"}
    job = await _apply_backup(
        client,
        a,
        _make_backup_zip(manifest, {entry["path"]: json.dumps(envelope).encode()}),
        monkeypatch,
        role_session,
    )
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["per_tool"]["file"]["created"] == 1

    await route_session_to_guild(session, a.guild.id)
    restored = (await session.exec(select(File).where(File.name == "Old link"))).one()
    assert restored.file_type == FileType.url


async def test_an_archive_from_before_catalogs_restores_its_galleries(
    client, acting_user, session, monkeypatch, role_session
):
    """An archive written while catalogs were galleries names them that way:
    the manifest's tool and switch, the envelope type and the key holding its
    pictures. A restore reads each as the catalog it is."""
    from sqlmodel import select

    from app.models.tenant.catalog import Catalog, CatalogItem

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    payload = png_bytes()
    path = "initiatives/1-restored/galleries/1-old-wall"
    envelope = {
        "type": "initiative-gallery",
        "schema_version": 1,
        "name": "Old wall",
        "tags": [],
        "properties": [],
        "images": [
            {
                "storage_key": "shot.png",
                "title": "Shot",
                "content_type": "image/png",
                "size_bytes": len(payload),
                "original_filename": "shot.png",
            }
        ],
    }
    entry = {
        "path": f"{path}.json",
        "tool": "gallery",
        "type": "initiative-gallery",
        "schema_version": 1,
        "entity_id": 1,
        "title": "Old wall",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    manifest = _minimal_manifest(
        entries=[entry],
        assets=[
            _asset_record(
                "shot.png",
                size_bytes=len(payload),
                content_type="image/png",
                referenced_by=[path],
            )
        ],
    )
    manifest["initiatives"][0]["tools"] = {"gallery": "included"}
    job = await _apply_backup(
        client,
        a,
        _make_backup_zip(
            manifest,
            {entry["path"]: json.dumps(envelope).encode(), "assets/shot.png": payload},
        ),
        monkeypatch,
        role_session,
    )
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["per_tool"]["catalog"]["created"] == 1

    await route_session_to_guild(session, a.guild.id)
    restored = (
        await session.exec(select(Catalog).where(Catalog.name == "Old wall"))
    ).one()
    items = (
        await session.exec(
            select(CatalogItem).where(CatalogItem.catalog_id == restored.id)
        )
    ).all()
    assert [item.title for item in items] == ["Shot"]


async def test_backup_corrupt_entry_fails_alone(
    client, acting_user, session, monkeypatch, role_session
):
    """One corrupt member fails its entry; the rest of the backup restores
    and the job completes with a per-entry report."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    good_entry, good_envelope = _queue_entry()
    bad_entry = dict(good_entry)
    bad_entry["path"] = "initiatives/1-restored/queues/2-bad.initiative-queue.json"
    bad_entry["title"] = "Bad Queue"
    bad_entry["entity_id"] = 2
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[good_entry, bad_entry]),
        {
            good_entry["path"]: json.dumps(good_envelope).encode(),
            bad_entry["path"]: b"{corrupt json",
        },
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["per_tool"]["queue"] == {
        "created": 1,
        "failed": 1,
        "skipped": 0,
    }
    statuses = {e["title"]: e["status"] for e in job["result"]["entries"]}
    assert statuses == {"Restored Queue": "created", "Bad Queue": "failed"}


async def test_backup_seat_vacated_before_apply_fails_closed(
    client, acting_user, session, monkeypatch, role_session
):
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text

    a.membership.role = CommunityRole.member
    session.add(a.membership)
    await session.commit()

    await _run_import_worker(monkeypatch, role_session)
    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_SUPERADMIN_REQUIRED"


async def test_backup_quota_exceeded_fails_job(
    client, acting_user, session, monkeypatch, role_session
):
    from sqlmodel import select

    from app.models.platform.guild import Guild

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    guild = (await session.exec(select(Guild).where(Guild.id == a.guild.id))).one()
    await guild_administration(session, guild, max_storage_bytes=1)

    manifest = _minimal_manifest(
        assets=[
            _asset_record(
                "huge.bin",
                size_bytes=1_000_000,
                content_type="application/octet-stream",
            )
        ]
    )
    zip_bytes = _make_backup_zip(manifest, {"assets/huge.bin": b"x" * 1024})
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)
    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_QUOTA_EXCEEDED"


async def test_backup_staged_expiry_and_cancel(
    client, acting_user, session, monkeypatch
):
    """An unconfirmed staged backup expires via GC (payload deleted); a
    staged backup can also be cancelled; a cancelled/expired one can't be
    confirmed."""
    from datetime import datetime, timedelta, timezone

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    zip_bytes = _make_backup_zip(_minimal_manifest())

    staged = await _upload_backup(client, a, zip_bytes)
    job_id = staged.json()["id"]

    from app.testing import route_session_to_guild

    await route_session_to_guild(session, a.guild.id)
    row = await session.get(ImportJob, job_id)
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.add(row)
    await session.commit()

    # TTL elapsed but GC hasn't swept yet: confirm must refuse and expire the
    # job NOW — a 200 here would queue a job GC silently kills with no
    # notification.
    raced = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert raced.status_code == 409
    assert raced.json()["detail"] == "IMPORT_NOT_CONFIRMABLE"
    await session.refresh(row)
    assert row.status == ImportJobStatus.expired
    assert row.payload_ref is None

    # GC stays idempotent over the already-expired row.
    await each_guild([(Scope.PROVISIONED, import_worker.expire_payloads)], name="t")
    await session.refresh(row)
    assert row.status == ImportJobStatus.expired

    late = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert late.status_code == 409
    assert late.json()["detail"] == "IMPORT_NOT_CONFIRMABLE"

    second = await _upload_backup(client, a, zip_bytes)
    second_id = second.json()["id"]
    cancelled = await client.delete(
        a.g(f"/imports/jobs/{second_id}"), headers=a.headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == ImportJobStatus.cancelled.value


async def test_backup_restores_fresh_assets_into_storage(
    client, acting_user, session, monkeypatch, role_session
):
    """A cross-guild restore: the storage key doesn't exist here, so the blob
    is written into guild storage, an uploads row is registered, and the uploaded file serves from the restored key."""
    from pathlib import Path

    from sqlmodel import select

    from app.models.tenant.upload import Upload

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    payload = b"%PDF-brand-new-blob"
    file_entry = _file_entry("from-elsewhere.pdf", title="Foreign Handout")
    manifest = _minimal_manifest(
        entries=[file_entry],
        assets=[
            _asset_record(
                "from-elsewhere.pdf",
                size_bytes=len(payload),
                original_filename="Foreign Handout.pdf",
            )
        ],
    )
    zip_bytes = _make_backup_zip(manifest, {"assets/from-elsewhere.pdf": payload})

    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["assets_restored"] == 1
    assert job["result"]["asset_bytes"] == len(payload)

    blob = get_guild_storage(a.guild.id).open_readable("from-elsewhere.pdf")
    assert blob is not None
    assert Path(blob.path).read_bytes() == payload
    from app.testing import route_session_to_guild

    await route_session_to_guild(session, a.guild.id)
    upload = (
        await session.exec(
            select(Upload).where(Upload.filename == "from-elsewhere.pdf")
        )
    ).one()
    assert upload.size_bytes == len(payload)
    assert upload.content_type == "application/pdf"


async def test_backup_quota_uses_zip_sizes_not_manifest_claims(
    client, acting_user, session, monkeypatch, role_session
):
    """The manifest is caller-supplied text: declaring size_bytes=1 for a
    large blob must NOT slip past the guild storage quota — the check
    accumulates the zip's own central-directory sizes."""
    from sqlmodel import select

    from app.models.platform.guild import Guild

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    guild = (await session.exec(select(Guild).where(Guild.id == a.guild.id))).one()
    await guild_administration(session, guild, max_storage_bytes=10_000)

    big_blob = b"x" * 50_000  # actual bytes far over the quota
    manifest = _minimal_manifest(
        assets=[
            _asset_record(
                "liar.bin",
                size_bytes=1,  # understated claim
                content_type="application/octet-stream",
            )
        ]
    )
    zip_bytes = _make_backup_zip(manifest, {"assets/liar.bin": big_blob})

    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_QUOTA_EXCEEDED"
    # Nothing was written despite the understated claim.
    assert get_guild_storage(a.guild.id).open_readable("liar.bin") is None


async def test_backup_asset_restore_guards_actual_bytes_not_declarations(
    acting_user, session
):
    """Central-directory sizes are declarations too: if a zip's real
    decompressed output exceeds what the quota pass approved (interpreter
    truncation is behavior, not a contract), the restore fails before
    writing past the approved bound."""
    import zipfile as zipfile_mod

    from app.schemas.tenant.backup_export import BackupManifest, ManifestAsset
    from app.schemas.tenant.import_job import BackupImportResult
    from app.services.import_engine.backup import _restore_assets
    from app.services.import_engine.contract import ImportEngineError
    from app.testing import route_session_to_guild

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await route_session_to_guild(session, a.guild.id)

    class LyingArchive:
        """Declares 10 bytes in the central directory, emits 100_000."""

        def getinfo(self, name):
            info = zipfile_mod.ZipInfo(name)
            info.file_size = 10
            return info

        def open(self, info):
            return io.BytesIO(b"x" * 100_000)

    manifest = BackupManifest(
        type="initiative-backup",
        schema_version=1,
        app_version="0.0.0-test",
        exported_at="2026-07-15T00:00:00+00:00",
        guild={"id": 1, "name": "g"},
        include_uploads=True,
        initiatives=[],
        entries=[],
        assets=[
            ManifestAsset(
                path="assets/liar.bin",
                storage_key="unit-liar.bin",
                original_filename="liar.bin",
                content_type="application/octet-stream",
                size_bytes=10,
                referenced_by=[],
            )
        ],
        skipped=[],
    )
    result = BackupImportResult()
    with pytest.raises(ImportEngineError) as exc_info:
        await _restore_assets(
            session, LyingArchive(), manifest, a.guild.id, a.user, result
        )
    assert exc_info.value.code == "IMPORT_QUOTA_EXCEEDED"
    assert get_guild_storage(a.guild.id).open_readable("unit-liar.bin") is None


async def test_backup_assets_are_stored_as_what_their_bytes_are(
    client, acting_user, session, monkeypatch, role_session
):
    """The manifest says what each file is; the bytes decide. A file is
    stored as the type it turned out to be, a table of text becomes a
    spreadsheet, and one that is not a file this app holds is left out,
    reported, and the entry that needed it skipped."""
    from sqlmodel import select

    from app.core.file_types import FileType

    from app.models.tenant.file import File
    from app.models.tenant.upload import Upload
    from app.testing import route_session_to_guild

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    pdf = b"%PDF-1.4 handout"
    program = b"MZ\x90\x00" + b"\x00" * 60
    table = b"name,count\nAria,3\n"

    manifest = _minimal_manifest(
        entries=[
            _file_entry("typed-handout.pdf"),
            _file_entry("typed-tool.exe", entity_id=2, title="Tool"),
            _file_entry("typed-table.csv", entity_id=3, title="Table"),
        ],
        assets=[
            # Claimed as a page; it is a PDF.
            _asset_record(
                "typed-handout.pdf", size_bytes=len(pdf), content_type="text/html"
            ),
            _asset_record(
                "typed-tool.exe",
                size_bytes=len(program),
                content_type="application/x-msdownload",
            ),
            _asset_record(
                "typed-table.csv", size_bytes=len(table), content_type="text/csv"
            ),
        ],
    )
    job = await _apply_backup(
        client,
        a,
        _make_backup_zip(
            manifest,
            {
                "assets/typed-handout.pdf": pdf,
                "assets/typed-tool.exe": program,
                "assets/typed-table.csv": table,
            },
        ),
        monkeypatch,
        role_session,
    )
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    result = job["result"]
    assert result["assets_restored"] == 1
    assert "unsupported_file:typed-tool.exe" in result["warnings"]
    entries = {entry["title"]: entry for entry in result["entries"]}
    assert entries["Handout"]["status"] == "created"
    assert (entries["Tool"]["status"], entries["Tool"]["error"]) == (
        "skipped",
        "IMPORT_ASSET_MISSING",
    )
    assert entries["Table"]["status"] == "created"
    storage = get_guild_storage(a.guild.id)
    assert storage.exists("typed-tool.exe") is False
    assert storage.exists("typed-table.csv") is False

    await route_session_to_guild(session, a.guild.id)
    upload = (
        await session.exec(select(Upload).where(Upload.filename == "typed-handout.pdf"))
    ).one()
    assert upload.content_type == "application/pdf"
    sheet = await session.get(
        File,
        entries["Table"]["detail"]["entity_id"],
        options=[undefer(File.content)],
    )
    assert sheet.file_type == FileType.sheet
    assert sheet.content["sheets"][0]["cells"]


async def test_backup_entry_past_the_json_cap_fails_alone(
    client, acting_user, session, monkeypatch, role_session
):
    """Each envelope in a backup is read up to the envelope cap. One past it
    fails its own entry; the rest of the backup restores."""
    monkeypatch.setattr(import_limits, "IMPORT_MAX_ENVELOPE_BYTES", 4096)
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    good_entry, good_envelope = _queue_entry()
    big_entry = {
        **good_entry,
        "path": "initiatives/1-restored/queues/2-big.initiative-queue.json",
        "title": "Big Queue",
        "entity_id": 2,
    }
    big_envelope = {
        **good_envelope,
        "name": "Big Queue",
        "items": [
            {"label": f"Member {index}", "position": float(index)}
            for index in range(400)
        ],
    }
    job = await _apply_backup(
        client,
        a,
        _make_backup_zip(
            _minimal_manifest(entries=[good_entry, big_entry]),
            {
                good_entry["path"]: json.dumps(good_envelope).encode(),
                big_entry["path"]: json.dumps(big_envelope).encode(),
            },
        ),
        monkeypatch,
        role_session,
    )
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    entries = {entry["title"]: entry for entry in job["result"]["entries"]}
    assert entries["Restored Queue"]["status"] == "created"
    assert (entries["Big Queue"]["status"], entries["Big Queue"]["error"]) == (
        "failed",
        "IMPORT_TOO_LARGE",
    )


async def test_backup_upload_past_the_cap_is_refused_by_the_handler(
    client, acting_user, session, monkeypatch
):
    """The upload is copied to a temporary file up to its cap; one past it is
    refused with the same answer the transport gives, and nothing is staged."""
    monkeypatch.setattr(import_limits, "IMPORT_MAX_BACKUP_UPLOAD_BYTES", 64)
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    resp = await _upload_backup(client, a, _make_backup_zip(_minimal_manifest()))
    assert resp.status_code == 413
    assert resp.json()["detail"] == "IMPORT_TOO_LARGE"
    jobs = (await client.get(a.g("/imports/jobs"), headers=a.headers)).json()
    assert jobs == []


# ---------------------------------------------------------------------------
# Posts: an import is a write like any other, held to the same limits
# ---------------------------------------------------------------------------


def _post_envelope(**overrides) -> dict:
    from app.testing import lexical_body

    return {
        "type": "initiative-post",
        "schema_version": 1,
        "name": "Notice",
        "body": lexical_body("Short enough."),
        "tags": [],
        **overrides,
    }


async def test_importing_a_post_over_the_body_limit_is_refused(
    client, acting_user, session
):
    """Accepting it would store a post the endpoints refuse to accept or to
    save again."""
    from app.schemas.tenant.post import MAX_POST_TEXT_CHARS
    from app.testing import lexical_body

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()

    response = await _import_envelope(
        client,
        a,
        _post_envelope(body=lexical_body("x" * (MAX_POST_TEXT_CHARS + 1))),
        a.initiative.id,
    )
    assert response.status_code == 400


async def test_importing_a_structurally_oversized_body_is_refused(
    client, acting_user, session
):
    """The character count is not the only ceiling. A body can hold almost no
    words and still be enormous — deeply nested empty nodes — and a normal
    write refuses that, so an import has to as well."""
    from app.schemas.tenant.post import MAX_POST_BODY_BYTES

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()

    # Wide rather than wordy: thousands of empty paragraphs carry no text at
    # all, so the character limit lets them straight through.
    empty = {"type": "paragraph", "children": [], "version": 1, "format": ""}
    bloated = {"root": {"type": "root", "children": [empty] * 4000}}
    assert len(json.dumps(bloated).encode("utf-8")) > MAX_POST_BODY_BYTES

    response = await _import_envelope(
        client, a, _post_envelope(body=bloated), a.initiative.id
    )
    assert response.status_code == 400


async def test_importing_a_long_headline_trims_rather_than_fails(
    client, acting_user, session
):
    """A headline is display text. The column holds 255, and failing a whole
    restore over a long title helps nobody — so it is trimmed and said."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()

    response = await _import_envelope(
        client, a, _post_envelope(name="H" * 400), a.initiative.id
    )
    assert response.status_code in (200, 201, 202), response.text
    body = response.json()
    assert len(body["result"]["entity_title"]) <= 255
    assert any("shortened" in w.lower() for w in body["result"]["warnings"])


# ---------------------------------------------------------------------------
# What a project envelope now carries: when things happened, what was said on
# them, and what they point at
# ---------------------------------------------------------------------------


async def test_project_envelope_carries_comments_dates_and_links(
    client, acting_user, session
):
    """Export a project whose tasks have comments, real creation dates and an
    edge between them; import it somewhere else and find all three.

    This is the round trip the whole deferred pass exists for: the edge is
    between two tasks written by the same entry, so it resolves; the dates are
    the ones the source had, not the moment of the restore; and the comment
    arrives attributed to the person who ran the import, with its original
    author named in the text rather than impersonated.
    """
    from datetime import datetime, timezone

    from sqlmodel import select

    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.models.tenant.comment import Comment
    from app.models.tenant.project import Project
    from app.models.tenant.task import Task
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant.relationships import Endpoint
    from app.testing.factories import create_comment

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    written_at = datetime(2024, 3, 4, 9, 30, tzinfo=timezone.utc)
    blocker = await create_task(
        session, a.project, title="Pour the footings", created_at=written_at
    )
    blocked = await create_task(session, a.project, title="Raise the frame")
    await create_comment(session, a.user, task=blocker, content="Frost delayed us")
    await relationships_service.create(
        session,
        source=Endpoint(kind=SearchEntityType.task, id=blocked.id),
        relationship_type=RelationshipType.depends_on,
        target=Endpoint(kind=SearchEntityType.task, id=blocker.id),
        created_by=a.user.id,
    )
    await session.commit()

    envelope = await _export_json(
        client, a, "/exports/project", {"ids": [a.project.id]}
    )
    by_title = {task["title"]: task for task in envelope["tasks"]}
    assert by_title["Pour the footings"]["created_at"].startswith("2024-03-04")
    assert by_title["Pour the footings"]["comments"][0]["body"] == "Frost delayed us"
    assert by_title["Raise the frame"]["links"] == [
        {
            "type": "depends_on",
            "target_external_ref": f"task:{blocker.id}",
        }
    ]

    target = await _second_initiative(session, a)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert result["created"]["comments"] == 1
    assert (result["links_created"], result["links_unresolved"]) == (1, 0)

    project = (
        await session.exec(select(Project).where(Project.initiative_id == target.id))
    ).one()
    tasks = {
        task.title: task
        for task in (
            await session.exec(select(Task).where(Task.project_id == project.id))
        ).all()
    }
    assert tasks["Pour the footings"].created_at == written_at

    comment = (
        await session.exec(
            select(Comment).where(Comment.task_id == tasks["Pour the footings"].id)
        )
    ).one()
    # The author's handle is a member of the target initiative, so the comment
    # is theirs — nothing is added to what they said.
    assert comment.created_by == a.user.id
    assert comment.content == "Frost delayed us"
    assert comment.imported_author_name is None

    assert await relationships_service.related_ids(
        session,
        Endpoint(kind=SearchEntityType.task, id=tasks["Raise the frame"].id),
        relationship_type=RelationshipType.depends_on,
        other_kind=SearchEntityType.task,
    ) == [tasks["Pour the footings"].id]


async def test_envelope_link_out_of_the_file_is_counted(client, acting_user, session):
    """A link whose far end is not in this envelope is ordinary — a number in
    the report, not a refusal."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = {
        "type": "initiative-project",
        "schema_version": 1,
        "app_version": "0.0.0-test",
        "exported_at": "2026-07-15T00:00:00+00:00",
        "project": {"name": "Imported Board"},
        "tags": [],
        "task_statuses": [
            {"name": "To Do", "category": "todo", "position": 0, "is_default": True}
        ],
        "property_definitions": [],
        "layouts": [],
        "tasks": [
            {
                "title": "Fit the door",
                "status_name": "To Do",
                "external_ref": "jira:ACME-1",
                "tags": [],
                "assignee_handles": [],
                "checklist": [],
                "properties": [],
                "links": [
                    {"type": "related_to", "target_external_ref": "jira:OTHER-9"}
                ],
            }
        ],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert (result["links_created"], result["links_unresolved"]) == (0, 1)


# ---------------------------------------------------------------------------
# What a backup manifest now says: where an entry is filed, and where the
# bundle should land
# ---------------------------------------------------------------------------


async def test_backup_attach_to_files_a_file_in_its_wiki(
    client, acting_user, session, monkeypatch, role_session
):
    """An uploaded file that sat in a wiki still sits in it after a restore,
    under the page it was filed under.

    The edge names two rows whose ids the archive cannot carry, so it crosses
    as ``attach_to`` on the file's entry, pointing at the wiki's entry
    path. Both are applied as ordinary entries and the edge is written once
    the pass runs — which is why the file entry can come first.
    """
    from sqlmodel import select

    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.models.tenant.file import File
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.wiki import Wiki
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant.relationships import Endpoint
    from app.testing.factories import create_upload

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    payload = b"%PDF-field-notes"
    get_guild_storage(a.guild.id).write(
        "field-notes.pdf", payload, content_type="application/pdf"
    )
    await create_upload(
        session,
        a.guild,
        a.user,
        filename="field-notes.pdf",
        size_bytes=len(payload),
        content_type="application/pdf",
    )

    wiki_path = "initiatives/1-restored/wikis/7-handbook.initiative-wiki.json"
    wiki_envelope = {
        "type": "initiative-wiki",
        "schema_version": 1,
        "name": "Handbook",
        "pages": [{"title": "Rules", "slug": "rules", "content": {}}],
    }
    wiki_entry = {
        "path": wiki_path,
        "tool": "wiki",
        "type": "initiative-wiki",
        "schema_version": 1,
        "entity_id": 7,
        "title": "Handbook",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    file_entry = {
        **_file_entry("field-notes.pdf", entity_id=3, title="Field notes"),
        "attach_to": {"kind": "wiki", "ref": wiki_path, "page": "rules"},
    }
    manifest = _minimal_manifest(entries=[file_entry, wiki_entry])
    manifest["initiatives"][0]["tools"]["wiki"] = "included"
    zip_bytes = _make_backup_zip(
        manifest,
        {
            wiki_path: json.dumps(wiki_envelope).encode(),
            "assets/field-notes.pdf": payload,
        },
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["links_created"] == 1

    restored = (
        await session.exec(select(Initiative).where(Initiative.name == "Restored"))
    ).one()
    wiki = (
        await session.exec(select(Wiki).where(Wiki.initiative_id == restored.id))
    ).one()
    file = (
        await session.exec(
            select(File).where(
                File.initiative_id == restored.id,
                File.current_version_id.is_not(None),
            )
        )
    ).one()
    assert await relationships_service.related_ids(
        session,
        Endpoint(kind=SearchEntityType.file, id=file.id),
        relationship_type=RelationshipType.part_of,
        other_kind=SearchEntityType.wiki,
    ) == [wiki.id]
    # And under the page it was filed under.
    from app.models.tenant.wiki import WikiPage
    from app.services.tenant.wikis import file_parent

    rules = (
        await session.exec(select(WikiPage).where(WikiPage.wiki_id == wiki.id))
    ).one()
    assert file_parent(wiki, file.id) == rules.id


async def test_backup_applies_into_an_existing_initiative(
    client, acting_user, session, monkeypatch, role_session
):
    """A bundle naming ``target_initiative_id`` lands in an initiative
    somebody already runs, instead of creating one.

    This is what a foreign source needs: a Jira project belongs on a board in
    an initiative that exists, and choosing that is the importer's call, not
    ours. No new initiative appears, and nothing about the target's name or
    tool switches is touched.
    """
    from sqlmodel import select

    from app.models.tenant.initiative import Initiative
    from app.models.tenant.queue import Queue

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    target = await _second_initiative(session, a)
    before = len((await session.exec(select(Initiative.id))).all())

    entry, envelope = _queue_entry()
    manifest = _minimal_manifest(entries=[entry])
    manifest["initiatives"][0]["target_initiative_id"] = target.id
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["initiatives"][0]["initiative_id"] == target.id

    assert len((await session.exec(select(Initiative.id))).all()) == before
    assert (
        await session.exec(select(Initiative).where(Initiative.name == "Restored"))
    ).one_or_none() is None

    queue = (
        await session.exec(select(Queue).where(Queue.initiative_id == target.id))
    ).one()
    assert queue.name == "Restored Queue"


async def test_backup_into_an_unreachable_initiative_fails_the_job(
    client, acting_user, session, monkeypatch, role_session
):
    """An initiative the importer cannot reach is indistinguishable from one
    that is not there, and neither is a place to write to."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    entry, envelope = _queue_entry()
    manifest = _minimal_manifest(entries=[entry])
    manifest["initiatives"][0]["target_initiative_id"] = 10_000_000
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_INVALID_PARAMS"


# ---------------------------------------------------------------------------
# The fetching status
# ---------------------------------------------------------------------------


async def test_a_stale_fetch_is_re_claimed_not_failed(
    client, acting_user, session, monkeypatch, role_session
):
    """A crashed fetch goes back in the queue; a crashed apply does not.

    The difference is what is already in the database. An apply has committed
    rows under the always-create policy, so re-running it would duplicate
    them. A fetch has written nothing but a payload in storage, so there is
    nothing to duplicate — the partial payload is thrown away and the job
    starts over.
    """
    from datetime import datetime, timedelta, timezone

    from sqlmodel import select

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    long_ago = datetime.now(timezone.utc) - timedelta(hours=3)
    job = await create_import_job(
        session,
        a.guild,
        a.user,
        source="atlassian",
        params={"initiative_id": a.initiative.id},
        payload_ref="imports/half-written.json",
        status=ImportJobStatus.fetching,
    )
    # updated_at is stamped on write, so age it afterwards.
    await session.exec(
        ImportJob.__table__.update()
        .where(ImportJob.__table__.c.id == job.id)
        .values(updated_at=long_ago)
    )
    await session.commit()

    await _run_import_worker(monkeypatch, role_session)

    session.expunge_all()
    reclaimed = (
        await session.exec(select(ImportJob).where(ImportJob.id == job.id))
    ).one()
    # It left ``fetching`` and its half-written payload is gone, so the fetch
    # can start clean. It is NOT the apply path's fail-closed outcome, which
    # is the distinction this rule exists to make. (The same pass then picks
    # the queued row up and starts the fetch over, which fails on the spot:
    # this row was never given a credential to read the site with.)
    assert reclaimed.status is not ImportJobStatus.fetching
    assert reclaimed.error != "IMPORT_INTERRUPTED"
    assert reclaimed.payload_ref != "imports/half-written.json"
    assert (
        get_guild_storage(a.guild.id).open_readable("imports/half-written.json") is None
    )


# ---------------------------------------------------------------------------
# Who said what: matching a comment's author to an account here
# ---------------------------------------------------------------------------


def _project_envelope_with_comment(author_handle: str, author_name: str) -> dict:
    """A one-task project whose task carries one comment by somebody else."""
    return {
        "type": "initiative-project",
        "schema_version": 1,
        "app_version": "0.0.0-test",
        "exported_at": "2026-07-15T00:00:00+00:00",
        "project": {"name": "Imported Board"},
        "tags": [],
        "task_statuses": [
            {"name": "To Do", "category": "todo", "position": 0, "is_default": True}
        ],
        "property_definitions": [],
        "layouts": [],
        "tasks": [
            {
                "title": "Fit the door",
                "status_name": "To Do",
                "tags": [],
                "assignee_handles": [],
                "checklist": [],
                "properties": [],
                "comments": [
                    {
                        "author_handle": author_handle,
                        "author_name": author_name,
                        "body": "The frame is out of true",
                        "created_at": "2024-03-04T09:30:00+00:00",
                    }
                ],
            }
        ],
    }


async def test_an_unmatched_author_keeps_their_name_and_no_account(
    client, acting_user, session, monkeypatch, role_session
):
    """Nobody here is somebody. The comment carries the name it arrived with
    and is credited to no account — not to whoever ran the import.

    The envelope quotes a stranger, so it is staged rather than applied and
    the importer is asked who that is; leaving the row blank is the answer
    this test gives, and it is a real one.
    """
    from sqlmodel import select

    from app.models.tenant.comment import Comment

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "staged"

    confirm = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"), headers=a.headers, json={}
    )
    assert confirm.status_code == 200, confirm.text
    await _run_import_worker(monkeypatch, role_session)

    comment = (
        await session.exec(
            select(Comment).where(Comment.content == "The frame is out of true")
        )
    ).one()
    # The row names what wrote it, because every guild-content row does...
    assert comment.created_by == a.user.id
    # ...and the name rides beside it, which is what the reader sees.
    assert comment.imported_author_name == "Alice Chen"


async def test_mentions_link_to_whoever_the_people_step_names(
    client, acting_user, session, monkeypatch, role_session
):
    """Somebody only mentioned is still asked about, and once they are
    placed their ``@name`` links to them — in the description and in a reply,
    which arrives under the comment it answers. A name nobody placed stays a
    name."""
    from sqlmodel import select

    from app.models.tenant.comment import Comment
    from app.models.tenant.task import Task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    envelope = _project_envelope_with_comment("Robin", "Robin")
    task = envelope["tasks"][0]
    task["description"] = "Ask @Alice Chen first"
    task["mention_handles"] = ["Alice Chen"]
    task["comments"][0]["external_ref"] = "jira-comment:1"
    task["comments"].append(
        {
            "author_handle": "Robin",
            "author_name": "Robin",
            "body": "@Alice Chen agreed, and @Alice too",
            "created_at": "2024-03-05T09:30:00+00:00",
            "reply_to_ref": "jira-comment:1",
            "mention_handles": ["Alice Chen", "Alice"],
        }
    )

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert {p["handle"] for p in job["plan"]["people"]} == {
        "Robin",
        "Alice Chen",
        "Alice",
    }

    confirm = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"),
        headers=a.headers,
        json={"people_map": {"Alice Chen": b.user.id}},
    )
    assert confirm.status_code == 200, confirm.text
    await _run_import_worker(monkeypatch, role_session)

    imported = (
        await session.exec(select(Task).where(Task.title == "Fit the door"))
    ).one()
    assert imported.description == f"Ask @[]({b.user.id}) first"
    comments = {
        c.content: c
        for c in (
            await session.exec(select(Comment).where(Comment.task_id == imported.id))
        ).all()
    }
    parent = comments["The frame is out of true"]
    reply = comments[f"@[]({b.user.id}) agreed, and @Alice too"]
    assert reply.parent_comment_id == parent.id
    assert parent.parent_comment_id is None


async def test_an_envelope_quoting_a_stranger_asks_before_it_applies(
    client, acting_user, session
):
    """The people step for a lone envelope: nothing is written until somebody
    has answered, and the plan is the question."""
    from sqlmodel import select

    from app.models.tenant.project import Project

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "staged"
    assert job["plan"]["people"] == [
        {
            "handle": "stranger#4321",
            "name": "Alice Chen",
            "comment_count": 1,
            "suggested_user_id": None,
        }
    ]
    # Staged means staged: the board does not exist yet.
    assert not (
        await session.exec(select(Project).where(Project.name == "Imported Board"))
    ).all()


async def test_an_envelope_naming_strangers_only_as_assignees_still_asks(
    client, acting_user, session
):
    """Assignees go through the people step's answer too, so an envelope
    whose only people are assignees is a question like any other. It used to
    apply on the spot and report them afterwards as unmatched — which is what
    every Todoist, TickTick and Vikunja export did, since those name people
    only as the person responsible for a task."""
    from sqlmodel import select

    from app.models.tenant.project import Project

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["comments"] = []
    envelope["tasks"][0]["assignee_handles"] = ["Jordan", "Mel"]
    envelope["tasks"].append(
        {**envelope["tasks"][0], "title": "Hang it", "assignee_handles": ["Mel"]}
    )

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "staged"
    assert job["plan"]["people"] == [
        {
            "handle": handle,
            "name": None,
            "comment_count": 0,
            "suggested_user_id": None,
        }
        for handle in ("Jordan", "Mel")
    ]
    assert not (
        await session.exec(select(Project).where(Project.name == "Imported Board"))
    ).all()


async def test_the_people_step_decides_who_an_imported_task_is_assigned_to(
    client, acting_user, session, monkeypatch, role_session
):
    """The answer to the step is what lands: a handle nobody here goes by,
    mapped to a member of the initiative, is that member's task."""
    from sqlmodel import select

    from app.models.tenant.task import Task, TaskAssignee

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["comments"] = []
    envelope["tasks"][0]["assignee_handles"] = ["Jordan"]

    job = (await _import_envelope(client, a, envelope, a.initiative.id)).json()
    assert job["status"] == "staged"
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"),
        headers=a.headers,
        json={"people_map": {"Jordan": a.user.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    done = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert done["status"] == "done", done.get("error")
    assert done["result"]["unmatched_handles"] == []

    session.expunge_all()
    task = (await session.exec(select(Task).where(Task.title == "Fit the door"))).one()
    assignees = (
        await session.exec(select(TaskAssignee).where(TaskAssignee.task_id == task.id))
    ).all()
    assert [row.user_id for row in assignees] == [a.user.id]


async def test_two_properties_never_share_one_definition(client, acting_user, session):
    """A ``Priority`` the target already uses for another type is renamed onto
    the target's ``Priority_select``; the envelope's own ``Priority_select``
    then gets a definition of its own, so a task keeps both values."""
    from sqlmodel import select

    from app.models.tenant.property import (
        PropertyDefinition,
        PropertyType,
        PropertyValue,
    )
    from app.models.tenant.task import Task
    from app.testing import create_property_definition

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    high = [{"value": "high", "label": "High"}]
    await create_property_definition(
        session, a.initiative, name="Priority", type=PropertyType.number
    )
    await create_property_definition(
        session,
        a.initiative,
        name="Priority_select",
        type=PropertyType.select,
        options=high,
    )
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["comments"] = []
    envelope["property_definitions"] = [
        {"name": name, "type": "select", "position": 0, "options": high}
        for name in ("Priority", "Priority_select")
    ]
    envelope["tasks"][0]["properties"] = [
        {"property_name": name, "property_type": "select", "value_text": "high"}
        for name in ("Priority", "Priority_select")
    ]

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 201, resp.text

    session.expunge_all()
    task = (await session.exec(select(Task).where(Task.title == "Fit the door"))).one()
    names = (
        await session.exec(
            select(PropertyDefinition.name)
            .join(PropertyValue)
            .where(
                PropertyValue.entity_type == "task", PropertyValue.entity_id == task.id
            )
        )
    ).all()
    assert sorted(names) == ["Priority_select", "Priority_select_select"]


async def test_a_user_property_is_placed_by_the_people_step(
    client, acting_user, session, monkeypatch, role_session
):
    """A user-type property — a Reporter — names a person the way an assignee
    does, so it is asked about the same way, and the answer is what lands."""
    from sqlmodel import select

    from app.models.tenant.property import PropertyValue
    from app.models.tenant.task import Task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["comments"] = []
    envelope["property_definitions"] = [
        {"name": "Reporter", "type": "user_reference", "position": 0}
    ]
    # Under the key project exports used before every envelope said
    # ``properties``, which older files still carry.
    del envelope["tasks"][0]["properties"]
    envelope["tasks"][0]["property_values"] = [
        {
            "property_name": "Reporter",
            "property_type": "user_reference",
            "value_handle": "Robin",
        }
    ]

    job = (await _import_envelope(client, a, envelope, a.initiative.id)).json()
    assert job["status"] == "staged", job
    assert [p["handle"] for p in job["plan"]["people"]] == ["Robin"]

    await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"),
        headers=a.headers,
        json={"people_map": {"Robin": a.user.id}},
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert done["status"] == "done", done.get("error")

    session.expunge_all()
    task = (await session.exec(select(Task).where(Task.title == "Fit the door"))).one()
    values = (
        await session.exec(
            select(PropertyValue).where(
                PropertyValue.entity_type == "task", PropertyValue.entity_id == task.id
            )
        )
    ).all()
    assert [v.value_user_id for v in values] == [a.user.id]


async def test_a_file_naming_somebody_in_a_property_asks_first(
    client, acting_user, session
):
    """Files used to be an envelope that names nobody. A user-type
    property on one names somebody, so it stops to ask."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    envelope = {
        "type": "initiative-file",
        "schema_version": 1,
        "file_type": "url",
        "name": "Spec",
        "content": {"url": "https://example.com"},
        "tags": [],
        "properties": [
            {
                "property_name": "Owner",
                "property_type": "user_reference",
                "value_handle": "Robin",
            }
        ],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "staged"
    assert job["plan"]["people"] == [
        {
            "handle": "Robin",
            "name": None,
            "comment_count": 0,
            "suggested_user_id": None,
        }
    ]


async def test_an_envelope_whose_people_all_match_is_not_a_second_step(
    client, acting_user, session
):
    """Asking somebody to agree with a screen full of correct answers is not
    a step. Every handle matching a member exactly means there is nothing to
    decide, so the file imports on one click, as it always did."""
    from app.core.user_display import handle_of

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    envelope = _project_envelope_with_comment(handle_of(b.user), "Someone Else")

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 201, resp.text


async def test_only_the_creator_answers_an_envelopes_people_step(
    client, acting_user, session
):
    """A guild admin can SEE somebody else's staged job — RLS says so. Saying
    who its people are on their behalf is a different thing."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)

    resp = await _import_envelope(
        client,
        a,
        _project_envelope_with_comment("stranger#4321", "Alice Chen"),
        a.initiative.id,
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]

    stolen = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=admin.headers, json={}
    )
    assert stolen.status_code == 403, stolen.text
    assert stolen.json()["detail"] == "IMPORT_NOT_CONFIRMABLE"


async def _import_with_assignees(client, a, people_map, monkeypatch, role_session):
    """Import a one-task project assigning ``ghost#1111`` and ``phantom#2222``,
    with the people step answered by ``people_map``; the job's result."""
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["assignee_handles"] = ["ghost#1111", "phantom#2222"]
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    confirm = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": people_map},
    )
    assert confirm.status_code == 200, confirm.text
    await _run_import_worker(monkeypatch, role_session)
    job = await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    return job.json()["result"]


async def _named_on_the_import(session, a):
    """The imported task's assignees, and who the imported project is shared
    with at read."""
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.resource_grant import ResourceGrant
    from app.models.tenant.task import Task, TaskAssignee

    await route_session_to_guild(session, a.guild.id)
    task = (await session.exec(select(Task).where(Task.title == "Fit the door"))).one()
    project = await session.get(Project, task.project_id)
    assignees = set(
        (
            await session.exec(
                select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
            )
        ).all()
    )
    readers = set(
        (
            await session.exec(
                select(ResourceGrant.user_id).where(
                    ResourceGrant.resource_type == "project",
                    ResourceGrant.resource_id == project.id,
                    ResourceGrant.level == "read",
                )
            )
        ).all()
    )
    return assignees, readers


async def test_an_import_brings_in_the_people_it_names(
    client, acting_user, session, monkeypatch, role_session
):
    """Somebody an import assigns is somebody the importer means to work on
    it. Run by the initiative's manager, it adds the person to the initiative
    and shares the project with them, and the assignment lands."""
    from sqlmodel import select

    from app.models.tenant.initiative import InitiativeMember

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    inside = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    outside = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    await _import_with_assignees(
        client,
        a,
        {"ghost#1111": inside.user.id, "phantom#2222": outside.user.id},
        monkeypatch,
        role_session,
    )

    assignees, readers = await _named_on_the_import(session, a)
    assert assignees == readers == {inside.user.id, outside.user.id}
    joined = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == a.initiative.id,
                InitiativeMember.user_id == outside.user.id,
            )
        )
    ).one()
    assert joined.role_id is not None


async def test_an_import_by_a_member_brings_in_nobody(
    client, acting_user, session, monkeypatch, role_session
):
    """Who is in an initiative is its managers' to decide. A member's import
    shares the project with the people it names who are in the initiative
    already, and reports the rest rather than adding them."""
    manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await grant_role_permission(session, manager.initiative, "create_projects")
    a = await acting_user(
        guild_role=CommunityRole.member,
        guild=manager.guild,
        initiative=manager.initiative,
        initiative_role="member",
    )
    inside = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    outside = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    result = await _import_with_assignees(
        client,
        a,
        {"ghost#1111": inside.user.id, "phantom#2222": outside.user.id},
        monkeypatch,
        role_session,
    )

    assignees, readers = await _named_on_the_import(session, a)
    assert assignees == readers == {inside.user.id}
    assert result["unmatched_handles"] == ["phantom#2222"]


async def test_an_exact_handle_match_makes_the_comment_theirs(
    client, acting_user, session
):
    """A handle that is already a member of the initiative it is landing in
    needs nobody to confirm it: it is the same identifier."""
    from sqlmodel import select

    from app.core.user_display import handle_of
    from app.models.tenant.comment import Comment

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    envelope = _project_envelope_with_comment(handle_of(b.user), "Someone Else")

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 201, resp.text

    comment = (
        await session.exec(
            select(Comment).where(Comment.content == "The frame is out of true")
        )
    ).one()
    assert comment.created_by == b.user.id
    assert comment.imported_author_name is None


async def test_the_plan_lists_the_people_and_suggests_the_exact_matches(
    client, acting_user, session
):
    """The wizard's people step is rendered from the plan, so the plan has to
    carry everyone the archive quotes — read from the manifest, because the
    plan never opens an envelope."""
    from app.core.user_display import handle_of

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    manifest = _minimal_manifest(entries=[entry])
    manifest["people"] = [
        {"handle": handle_of(a.user), "name": "The Importer", "comment_count": 4},
        {"handle": "stranger#4321", "name": "Alice Chen", "comment_count": 1},
    ]
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    people = resp.json()["plan"]["people"]
    by_handle = {person["handle"]: person for person in people}

    # A member of this guild, by exact handle — offered as the answer.
    assert by_handle[handle_of(a.user)]["suggested_user_id"] == a.user.id
    assert by_handle[handle_of(a.user)]["comment_count"] == 4
    # A name nobody here answers to is left for a person to decide.
    assert by_handle["stranger#4321"]["suggested_user_id"] is None


async def test_the_confirmed_mapping_decides_who_a_comment_belongs_to(
    client, acting_user, session, monkeypatch, role_session
):
    """The people step's whole purpose: a name that matches nobody becomes
    somebody, because a person said so."""
    from sqlmodel import select

    from app.models.tenant.comment import Comment

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    entry = {
        "path": "initiatives/1-restored/projects/1-board.initiative-project.json",
        "tool": "project",
        "type": "initiative-project",
        "schema_version": 1,
        "entity_id": 1,
        "title": "Imported Board",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    manifest = _minimal_manifest(entries=[entry])
    manifest["people"] = [
        {"handle": "stranger#4321", "name": "Alice Chen", "comment_count": 1}
    ]
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"stranger#4321": b.user.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")

    comment = (
        await session.exec(
            select(Comment).where(Comment.content == "The frame is out of true")
        )
    ).one()
    assert comment.created_by == b.user.id
    assert comment.imported_author_name is None


def _mention_node(name: str, user_id: int | None) -> dict:
    return {
        "type": "mention",
        "version": 1,
        "mentionName": name,
        "mentionUserId": user_id,
        "text": name,
    }


def _editor_state(*inline: dict) -> dict:
    return {
        "root": {
            "type": "root",
            "children": [{"type": "paragraph", "children": list(inline)}],
        }
    }


def _mentions_in(content: dict) -> list[dict]:
    return [
        node
        for node in content["root"]["children"][0]["children"]
        if node.get("type") == "mention"
    ]


async def test_a_restored_mention_links_to_whoever_its_handle_is_here(
    client, acting_user, session, monkeypatch, role_session
):
    """A mention names an account by id, and an id means nothing where a
    backup is restored. So the backup names the person by handle — in a task's
    description, a comment, a file, a post and a wiki page — lists them for
    the people step, and the restore links each mention to whoever that step
    says the handle is here: another account entirely, in this test, which is
    what a restore into a community where the id is somebody else looks like.
    """
    from sqlmodel import select

    from app.api.v1.tenant_endpoints.exports_test import (
        _all_tools_enabled,
        _export,
        _rendered_zip,
    )
    from app.core.user_display import handle_of
    from app.models.tenant.comment import Comment
    from app.models.tenant.file import File
    from app.models.tenant.post import Post
    from app.models.tenant.project import Project
    from app.models.tenant.task import Task
    from app.models.tenant.wiki import Wiki, WikiPage
    from app.testing.factories import (
        create_comment,
        create_post,
        create_wiki,
        create_wiki_page,
    )

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    c = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    await _all_tools_enabled(session, a.initiative)
    handle = handle_of(b.user)
    said = _editor_state(
        {"type": "text", "text": "Ask "}, _mention_node("Bea", b.user.id)
    )

    task = await create_task(
        session,
        a.project,
        title="Hang the door",
        description=f"Ask @[Bea]({b.user.id})",
    )
    await create_comment(
        session, a.user, task=task, content=f"@[Bea]({b.user.id}) agreed"
    )
    await create_file(session, a.initiative, a.user, name="Plan", content=said)
    await create_post(session, a.initiative, a.user, name="Notice", body=said)
    wiki = await create_wiki(session, a.initiative, a.user, name="Handbook")
    await create_wiki_page(session, wiki, a.user, title="Start", content=said)

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    manifest = json.loads(archive.read("manifest.json"))
    assert handle in [person["handle"] for person in manifest["people"]]
    for name in archive.namelist():
        if name.endswith(".json") and name != "manifest.json":
            text = archive.read(name).decode()
            # Nothing in the archive names the account by its id any more.
            assert f"]({b.user.id})" not in text, name
            assert f'"mentionUserId": {b.user.id}' not in text, name

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as rezipped:
        for name in archive.namelist():
            rezipped.writestr(name, archive.read(name))
    upload = await _upload_backup(client, a, buffer.getvalue())
    assert upload.status_code == 201, upload.text
    job_id = upload.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {handle: c.user.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)
    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    restored = job["result"]["initiatives"][0]["initiative_id"]

    project = (
        await session.exec(select(Project).where(Project.initiative_id == restored))
    ).one()
    restored_task = (
        await session.exec(select(Task).where(Task.project_id == project.id))
    ).one()
    assert restored_task.description == f"Ask @[]({c.user.id})"
    comment = (
        await session.exec(select(Comment).where(Comment.task_id == restored_task.id))
    ).one()
    assert comment.content == f"@[]({c.user.id}) agreed"

    file = (
        await session.exec(
            select(File)
            .where(File.initiative_id == restored)
            .options(undefer(File.content))
        )
    ).one()
    post = (
        await session.exec(select(Post).where(Post.initiative_id == restored))
    ).one()
    restored_wiki = (
        await session.exec(select(Wiki).where(Wiki.initiative_id == restored))
    ).one()
    page = (
        await session.exec(select(WikiPage).where(WikiPage.wiki_id == restored_wiki.id))
    ).one()
    for content in (file.content, post.body, page.content):
        [mention] = _mentions_in(content)
        assert mention["mentionUserId"] == c.user.id
        assert (mention["mentionName"], mention["text"]) == ("", "")
        assert "mentionHandle" not in mention


async def test_a_files_own_export_names_its_mentions_by_handle(
    client, acting_user, session
):
    """The single-file export writes the same handle a backup does, and
    importing it links the mention to the member who answers to that handle —
    with no question asked, because the match is exact. The exported
    file itself is left as it was."""
    from sqlmodel import select

    from app.core.user_display import handle_of
    from app.models.tenant.file import File

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    target = await _second_initiative(session, a)
    said = _editor_state(_mention_node("Me", a.user.id))
    source = await create_file(
        session, a.initiative, a.user, name="Notes", content=said
    )

    envelope = await _export_json(client, a, "/exports/file", {"ids": [source.id]})
    assert envelope["mention_handles"] == [handle_of(a.user)]
    [exported] = _mentions_in(envelope["content"])
    assert exported["mentionUserId"] is None
    assert exported["mentionHandle"] == handle_of(a.user)

    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text

    imported = (
        await session.exec(
            select(File)
            .where(File.initiative_id == target.id)
            .options(undefer(File.content))
        )
    ).one()
    [mention] = _mentions_in(imported.content)
    assert mention["mentionUserId"] == a.user.id
    assert "mentionHandle" not in mention
    await session.refresh(source, ["content"])
    assert source.content == said


async def test_a_mention_nobody_places_is_restored_as_a_name(
    client, acting_user, session, monkeypatch, role_session
):
    """A file naming somebody the restore cannot place keeps their name
    and links to nobody — never to whoever holds the id it had at the source."""
    from sqlmodel import select

    from app.models.tenant.file import File

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    target = await _second_initiative(session, a, files_enabled=True)
    envelope = {
        "type": "initiative-file",
        "schema_version": 1,
        "file_type": "lexical",
        "name": "Minutes",
        "content": _editor_state(
            {**_mention_node("Bea", None), "mentionHandle": "stranger#4321"}
        ),
        "mention_handles": ["stranger#4321"],
    }

    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    # Somebody only mentioned is still somebody the step asks about.
    assert [p["handle"] for p in job["plan"]["people"]] == ["stranger#4321"]

    confirm = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"), headers=a.headers, json={}
    )
    assert confirm.status_code == 200, confirm.text
    await _run_import_worker(monkeypatch, role_session)

    file = (
        await session.exec(
            select(File)
            .where(File.initiative_id == target.id)
            .options(undefer(File.content))
        )
    ).one()
    [mention] = _mentions_in(file.content)
    assert mention["mentionUserId"] is None
    assert mention["mentionName"] == "Bea"
    assert "mentionHandle" not in mention


def _reference_node(entity_type: str, entity_id: int, text: str) -> dict:
    return {
        "type": "entity-mention",
        "version": 1,
        "entityType": entity_type,
        "entityId": entity_id,
        "text": text,
    }


def _chip_node(chip_kind: str, entity_id: int, text: str) -> dict:
    return {
        "type": "smart-chip",
        "version": 1,
        "chipKind": chip_kind,
        "entityId": entity_id,
        "text": text,
    }


def _wikilink_node(file_id: int, title: str) -> dict:
    return {
        "type": "wikilink",
        "version": 1,
        "documentId": file_id,
        "documentTitle": title,
        "text": title,
    }


async def _referencing_initiative(session, a) -> dict:
    """An initiative whose bodies name each other: a task naming a task, a
    file and a file in another initiative; a comment naming a wiki
    page; a file naming a task, its status, a counter's value and another
    file; a post naming the project; a page naming the post."""
    from app.api.v1.tenant_endpoints.exports_test import _all_tools_enabled
    from app.testing.factories import (
        create_comment,
        create_counter,
        create_post,
        create_wiki,
        create_wiki_page,
    )

    await _all_tools_enabled(session, a.initiative)
    elsewhere = await _second_initiative(session, a)
    outside = await create_file(session, elsewhere, a.user, name="Elsewhere")

    fix = await create_task(session, a.project, title="Fix the bug")
    spec = await create_file(session, a.initiative, a.user, name="Spec")
    group = await create_counter_group(session, a.initiative, a.user, name="Tally")
    counter = await create_counter(session, group, name="Wins")
    post = await create_post(
        session,
        a.initiative,
        a.user,
        name="Notice",
        body=_editor_state(_reference_node("project", a.project.id, "Roadmap")),
    )
    wiki = await create_wiki(session, a.initiative, a.user, name="Handbook")
    start = await create_wiki_page(
        session,
        wiki,
        a.user,
        title="Start",
        content=_editor_state(_reference_node("post", post.id, "Notice")),
    )
    await create_file(
        session,
        a.initiative,
        a.user,
        name="Plan",
        content=_editor_state(
            _reference_node("task", fix.id, "Fix the bug"),
            _chip_node("task:status", fix.id, "To do"),
            _chip_node("counter:value", counter.id, "3"),
            _wikilink_node(spec.id, "Spec"),
        ),
    )
    ship = await create_task(
        session,
        a.project,
        title="Ship it",
        description=(
            f"After #task[Fix the bug]({fix.id}), per #doc[Spec]({spec.id}) "
            f"and #file[Elsewhere]({outside.id})"
        ),
    )
    await create_comment(
        session,
        a.user,
        task=ship,
        content=f"Written up in #wiki-page[Start]({start.id})",
    )
    return {"outside": outside}


async def _restore_referencing_backup(
    client, a, monkeypatch, role_session, *, elsewhere: bool
) -> int:
    """Back the initiative up and restore it into the same community — or, with
    ``elsewhere``, as a backup taken from another community. Returns the
    restored initiative's id."""
    from app.api.v1.tenant_endpoints.exports_test import _export, _rendered_zip

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as rezipped:
        for name in archive.namelist():
            data = archive.read(name)
            if name == "manifest.json" and elsewhere:
                manifest = json.loads(data)
                manifest["guild"]["id"] = a.guild.id + 1000
                data = json.dumps(manifest).encode()
            rezipped.writestr(name, data)
    job = await _apply_backup(client, a, buffer.getvalue(), monkeypatch, role_session)
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    return job["result"]["initiatives"][0]["initiative_id"]


async def _restored(session, initiative_id: int) -> dict:
    """The restored rows the referencing initiative's bodies name, by name."""
    from sqlmodel import select

    from app.models.tenant.comment import Comment
    from app.models.tenant.counter import Counter, CounterGroup
    from app.models.tenant.file import File
    from app.models.tenant.post import Post
    from app.models.tenant.project import Project
    from app.models.tenant.task import Task
    from app.models.tenant.wiki import Wiki, WikiPage

    project = (
        await session.exec(
            select(Project).where(Project.initiative_id == initiative_id)
        )
    ).one()
    tasks = {
        task.title: task
        for task in (
            await session.exec(select(Task).where(Task.project_id == project.id))
        ).all()
    }
    files = {
        file.name: file
        for file in (
            await session.exec(
                select(File)
                .where(File.initiative_id == initiative_id)
                .options(undefer(File.content))
            )
        ).all()
    }
    wiki = (
        await session.exec(select(Wiki).where(Wiki.initiative_id == initiative_id))
    ).one()
    counter = (
        await session.exec(
            select(Counter)
            .join(CounterGroup, CounterGroup.id == Counter.counter_group_id)
            .where(CounterGroup.initiative_id == initiative_id)
        )
    ).one()
    return {
        "project": project,
        "tasks": tasks,
        "layouts": [],
        "files": files,
        "counter": counter,
        "post": (
            await session.exec(select(Post).where(Post.initiative_id == initiative_id))
        ).one(),
        "page": (
            await session.exec(select(WikiPage).where(WikiPage.wiki_id == wiki.id))
        ).one(),
        "comment": (
            await session.exec(
                select(Comment).where(Comment.task_id == tasks["Ship it"].id)
            )
        ).one(),
    }


def _nodes(content: dict) -> list[dict]:
    return content["root"]["children"][0]["children"]


async def test_a_restored_reference_points_at_the_restored_copy(
    client, acting_user, session, monkeypatch, role_session
):
    """A reference names what it points at by id, and a restore makes new
    rows — so the backup carries each reference by the ref it had, and the
    restore points it at the copy that ref became: in a task's description, a
    comment, a file (a mention, a live chip, a ``[[ ]]`` link), a post and
    a wiki page. Restored into the community it came from, a reference to
    something the backup did not carry still names what it named there. The
    restored bodies' references are edges from the start, as a save's are."""
    from sqlmodel import select

    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.api.v1.tenant_endpoints.exports_test import _export, _rendered_zip
    from app.models.tenant.relationship import EntityRelationship
    from app.services.import_engine.references import SOURCE_REF
    from app.services.tenant.relationships import Endpoint

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    scene = await _referencing_initiative(session, a)
    outside = scene["outside"]

    resp = await _export(client, a, "initiative", initiative_id=a.initiative.id)
    archive = await _rendered_zip(client, a, monkeypatch, role_session, resp)
    [project_entry] = [
        name for name in archive.namelist() if name.endswith(".initiative-project.json")
    ]
    exported = json.loads(archive.read(project_entry))
    [ship_env] = [t for t in exported["tasks"] if t["title"] == "Ship it"]
    # The archive names what it points at by ref, never by a bare id.
    assert f"#file[Elsewhere](file:{outside.id})" in ship_env["description"]
    assert exported["source_guild_id"] == a.guild.id

    restored_id = await _restore_referencing_backup(
        client, a, monkeypatch, role_session, elsewhere=False
    )
    r = await _restored(session, restored_id)
    fix, ship = r["tasks"]["Fix the bug"], r["tasks"]["Ship it"]
    spec, plan = r["files"]["Spec"], r["files"]["Plan"]

    assert ship.description == (
        f"After #task[Fix the bug]({fix.id}), per #doc[Spec]({spec.id}) "
        f"and #file[Elsewhere]({outside.id})"
    )
    assert r["comment"].content == f"Written up in #wiki-page[Start]({r['page'].id})"
    mention, status, value, wikilink = _nodes(plan.content)
    assert mention["entityId"] == fix.id
    assert status["entityId"] == fix.id
    assert value["entityId"] == r["counter"].id
    assert wikilink["documentId"] == spec.id
    [project_mention] = _nodes(r["post"].body)
    assert project_mention["entityId"] == r["project"].id
    [post_mention] = _nodes(r["page"].content)
    assert post_mention["entityId"] == r["post"].id
    for body in (plan.content, r["post"].body, r["page"].content):
        assert SOURCE_REF not in json.dumps(body)

    async def references(endpoint: Endpoint) -> set[tuple[str, int]]:
        rows = await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_node == endpoint.node,
                EntityRelationship.relationship_type
                == RelationshipType.references.value,
                EntityRelationship.removed_at.is_(None),
            )
        )
        return {(row.target_type, row.target_id) for row in rows.all()}

    # The file's edges are its mention, its chips and its ``[[ ]]`` link;
    # a task's come from its description and from what is said on it.
    assert await references(Endpoint(SearchEntityType.file, plan.id)) == {
        ("task", fix.id),
        ("counter", r["counter"].id),
        ("file", spec.id),
    }
    assert await references(Endpoint(SearchEntityType.task, ship.id)) == {
        ("task", fix.id),
        ("file", spec.id),
        ("file", outside.id),
        ("wiki_page", r["page"].id),
    }
    assert await references(Endpoint(SearchEntityType.wiki_page, r["page"].id)) == {
        ("post", r["post"].id)
    }


async def test_a_reference_restored_elsewhere_to_something_left_behind_is_its_title(
    client, acting_user, session, monkeypatch, role_session
):
    """Restored anywhere but the community it came from, a reference to
    something the backup did not carry has nothing here to point at, and its
    id names something else or nothing — so it is its title again. What the
    backup did carry still resolves."""
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    await _referencing_initiative(session, a)

    restored_id = await _restore_referencing_backup(
        client, a, monkeypatch, role_session, elsewhere=True
    )
    r = await _restored(session, restored_id)
    fix, ship = r["tasks"]["Fix the bug"], r["tasks"]["Ship it"]

    assert ship.description == (
        f"After #task[Fix the bug]({fix.id}), "
        f"per #doc[Spec]({r['files']['Spec'].id}) and Elsewhere"
    )


async def _import_archive(client, actor, zip_bytes, initiative_id, envelope_type=None):
    data = {"initiative_id": str(initiative_id)}
    if envelope_type is not None:
        data["envelope_type"] = envelope_type
    return await client.post(
        actor.g("/imports/envelope/archive"),
        headers=actor.headers,
        files={"file": ("catalog.zip", zip_bytes, "application/zip")},
        data=data,
    )


async def test_a_catalog_zip_imports_with_its_pictures_into_another_community(
    client, acting_user, session, monkeypatch, tmp_path
):
    """A catalog exported on its own is a zip of its envelope and its pictures,
    and importing that zip somewhere the pictures have never been stored brings
    them along: each lands in the community's storage under its key, and the
    catalog shows it. A description's link to another picture points at that
    picture's copy here, and a mention of somebody who is not here is their
    handle."""
    from sqlmodel import select

    from app.api.v1.tenant_endpoints.exports_test import _all_tools_enabled
    from app.core.config import settings
    from app.models.tenant.catalog import Catalog, CatalogItem
    from app.testing import route_session_to_guild
    from app.testing.factories import create_catalog, create_catalog_item

    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _all_tools_enabled(session, a.initiative)
    catalog = await create_catalog(session, a.initiative, a.user, name="Barovia maps")
    picture = await create_catalog_item(session, catalog, a.user, title="Village")
    key = picture.current_version.file_url.rsplit("/", 1)[-1]
    await create_catalog_item(
        session,
        catalog,
        a.user,
        title="Castle",
        description=f"Above #catalog-item[Village]({picture.id}), per @[]({a.user.id})",
    )

    exported = await client.get(
        a.g("/exports/catalog"),
        headers=a.headers,
        params={"ids": [catalog.id], "format": "json"},
    )
    assert exported.status_code == 200, exported.text

    b = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _all_tools_enabled(session, b.initiative)
    assert get_guild_storage(b.guild.id).exists(key) is False
    resp = await _import_archive(
        client, b, exported.content, b.initiative.id, "initiative-catalog"
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["result"]["created"]["items"] == 2

    assert get_guild_storage(b.guild.id).exists(key)
    await route_session_to_guild(session, b.guild.id)
    restored = (
        await session.exec(
            select(Catalog).where(Catalog.initiative_id == b.initiative.id)
        )
    ).one()
    items = {
        item.title: item
        for item in (
            await session.exec(
                select(CatalogItem).where(CatalogItem.catalog_id == restored.id)
            )
        ).all()
    }
    image = items["Village"]
    description = items["Castle"].description
    assert f"#catalog-item[Village]({image.id})" in description
    assert f"@[]({a.user.id})" not in description
    # The picture is its version 1, typed from its bytes.
    version = image.current_version
    assert version is not None and version.version_number == 1
    assert version.file_url == f"/uploads/{b.guild.id}/{key}"
    assert version.file_content_type == "image/png"


async def test_a_wiki_zip_imports_back_from_the_wiki_page(client, acting_user, session):
    """A wiki's importable export is a zip, like every wiki download; importing
    it restores the wiki, its settings and its pages, with the template naming
    the page it became."""
    from sqlmodel import select

    from app.api.v1.tenant_endpoints.exports_test import _all_tools_enabled
    from app.models.tenant.wiki import (
        Wiki,
        WikiPage,
        WikiPageOrder,
        WikiReadingWidth,
    )
    from app.testing.factories import create_wiki, create_wiki_page

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _all_tools_enabled(session, a.initiative)
    target = await _second_initiative(session, a, wikis_enabled=True)
    settings = {
        "page_order": WikiPageOrder.title,
        "contents_depth": 2,
        "show_connections": False,
        "show_updated_at": False,
        "reading_width": WikiReadingWidth.comfortable,
        "accent_color": "#336699",
    }
    wiki = await create_wiki(session, a.initiative, a.user, name="Handbook", **settings)
    start = await create_wiki_page(session, wiki, a.user, title="Start")
    wiki.template_page_id = start.id
    session.add(wiki)
    await session.commit()

    exported = await client.get(
        a.g("/exports/wiki"),
        headers=a.headers,
        params={"ids": [wiki.id], "format": "json"},
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"] == "application/zip"

    resp = await _import_archive(
        client, a, exported.content, target.id, "initiative-wiki"
    )
    assert resp.status_code == 201, resp.text
    restored = (
        await session.exec(select(Wiki).where(Wiki.initiative_id == target.id))
    ).one()
    pages = (
        await session.exec(select(WikiPage).where(WikiPage.wiki_id == restored.id))
    ).all()
    assert [page.title for page in pages] == ["Start"]
    assert {field: getattr(restored, field) for field in settings} == settings
    assert restored.template_page_id == pages[0].id


async def test_a_wiki_zip_brings_its_filed_files_back_where_they_were(
    client, acting_user, session
):
    """Imported somewhere none of it exists, a wiki's zip files every file
    it carried again: the text document and the spreadsheet recreated from the
    envelope, the upload over the bytes the zip brought, each joined to the
    wiki and under the page it sat under."""
    from sqlmodel import select

    from app.api.v1.tenant_endpoints.exports_test import (
        _all_tools_enabled,
        _wiki_with_filed_files,
    )
    from app.core.file_types import FileType
    from app.models.tenant.file import File
    from app.models.tenant.wiki import Wiki, WikiPage
    from app.services.tenant.wikis import file_parent, linked_files
    from app.testing import route_session_to_guild

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    wiki = await _wiki_with_filed_files(session, a, acting_user)
    exported = await client.get(
        a.g("/exports/wiki"),
        headers=a.headers,
        params={"ids": [wiki.id], "format": "json"},
    )
    assert exported.status_code == 200, exported.text

    b = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _all_tools_enabled(session, b.initiative)
    resp = await _import_archive(
        client, b, exported.content, b.initiative.id, "initiative-wiki"
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["result"]["created"]["files"] == 3

    await route_session_to_guild(session, b.guild.id)
    restored = (
        await session.exec(select(Wiki).where(Wiki.initiative_id == b.initiative.id))
    ).one()
    filed = {file.name: file for file in await linked_files(session, restored.id)}
    assert set(filed) == {"Session notes", "Loot", "Handout"}
    assert filed["Loot"].file_type == FileType.sheet
    handout = filed["Handout"]
    assert handout.file_type == FileType.pdf
    # The upload is the file's version 1, typed from its bytes.
    version = handout.current_version
    assert version is not None and version.version_number == 1
    assert version.file_url == f"/uploads/{b.guild.id}/handout-key.pdf"
    assert version.file_content_type == "application/pdf"
    assert get_guild_storage(b.guild.id).exists("handout-key.pdf")
    rules = (
        await session.exec(
            select(WikiPage).where(
                WikiPage.wiki_id == restored.id, WikiPage.title == "Rules"
            )
        )
    ).one()
    assert file_parent(restored, handout.id) == rules.id
    assert (
        await session.exec(select(File).where(File.initiative_id == b.initiative.id))
    ).all()


async def test_a_catalog_zip_leaves_out_what_is_not_a_picture(
    client, acting_user, session
):
    """The zip says what its files are; the bytes decide. A file that is not a
    picture a catalog can show is not stored, and the import says so."""
    from app.api.v1.tenant_endpoints.exports_test import _all_tools_enabled

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _all_tools_enabled(session, a.initiative)
    envelope = {
        "type": "initiative-catalog",
        "schema_version": 1,
        "name": "Handouts",
        "items": [
            {"storage_key": "note.png", "content_type": "image/png", "title": "Note"}
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("handouts.initiative-catalog.json", json.dumps(envelope))
        archive.writestr("assets/note.png", b"<svg onload='x'></svg>")

    resp = await _import_archive(client, a, buffer.getvalue(), a.initiative.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert "not_a_picture:note.png" in result["warnings"]
    assert result["created"]["items"] == 0
    assert get_guild_storage(a.guild.id).exists("note.png") is False


async def test_a_zip_is_refused_from_the_wrong_tool_or_without_an_export(
    client, acting_user, session
):
    from app.api.v1.tenant_endpoints.exports_test import _all_tools_enabled

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _all_tools_enabled(session, a.initiative)

    def zipped(**members: str) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        return buffer.getvalue()

    queue = json.dumps({"type": "initiative-queue", "schema_version": 1, "name": "Q"})
    wrong = await _import_archive(
        client, a, zipped(**{"q.json": queue}), a.initiative.id, "initiative-catalog"
    )
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "IMPORT_WRONG_TOOL"

    empty = await _import_archive(
        client, a, zipped(**{"readme.txt": "hi"}), a.initiative.id
    )
    assert empty.status_code == 400
    assert empty.json()["detail"] == "IMPORT_ARCHIVE_NO_ENVELOPE"


async def test_a_lone_envelope_resolves_what_it_carries(client, acting_user, session):
    """A project exported on its own points a task's reference at a sibling's
    new copy. A reference to something outside it keeps naming the original
    when imported into the community it came from, and is its title anywhere
    else."""
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    target = await _second_initiative(session, a)
    spec = await create_file(session, a.initiative, a.user, name="Spec")
    fix = await create_task(session, a.project, title="Fix the bug")
    await create_task(
        session,
        a.project,
        title="Ship it",
        description=f"After #task[Fix the bug]({fix.id}), per #doc[Spec]({spec.id})",
        # What an edit of just this task kept back is placed the same way.
        recurrence_carry={"description": f"Once #task[Fix the bug]({fix.id})"},
    )

    envelope = await _export_json(
        client, a, "/exports/project", {"ids": [a.project.id]}
    )
    elsewhere = {**envelope, "source_guild_id": a.guild.id + 1000}

    descriptions = []
    for sent in (envelope, elsewhere):
        resp = await _import_envelope(client, a, sent, target.id)
        assert resp.status_code == 201, resp.text
        project_id = resp.json()["result"]["entity_id"]
        tasks = {
            task.title: task
            for task in (
                await session.exec(select(Task).where(Task.project_id == project_id))
            ).all()
        }
        assert (await session.get(Project, project_id)).initiative_id == target.id
        descriptions.append((tasks["Fix the bug"].id, tasks["Ship it"].description))
        assert tasks["Ship it"].recurrence_carry == {
            "description": f"Once #task[Fix the bug]({tasks['Fix the bug'].id})"
        }

    (here_fix, here), (there_fix, there) = descriptions
    assert here == f"After #task[Fix the bug]({here_fix}), per #doc[Spec]({spec.id})"
    assert there == f"After #task[Fix the bug]({there_fix}), per Spec"


async def test_a_mapping_naming_a_non_member_is_dropped(
    client, acting_user, session, monkeypatch, role_session
):
    """The confirm may be hours old. Somebody named in it who has since left
    the community does not get authorship of anything."""
    from sqlmodel import select

    from app.models.tenant.comment import Comment

    outsider = await acting_user(guild_role=CommunityRole.member)
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )

    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    entry = {
        "path": "initiatives/1-restored/projects/1-board.initiative-project.json",
        "tool": "project",
        "type": "initiative-project",
        "schema_version": 1,
        "entity_id": 1,
        "title": "Imported Board",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    manifest = _minimal_manifest(entries=[entry])
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    # An account in a different guild entirely — the map names them anyway.
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"stranger#4321": outsider.user.id}},
    )
    await _run_import_worker(monkeypatch, role_session)

    comment = (
        await session.exec(
            select(Comment).where(Comment.content == "The frame is out of true")
        )
    ).one()
    assert comment.created_by != outsider.user.id
    assert comment.imported_author_name == "Alice Chen"


async def test_confirm_refuses_a_malformed_people_map(client, acting_user, session):
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]

    bad = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"stranger#4321": "not-an-id"}},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "IMPORT_INVALID_PARAMS"


# ---------------------------------------------------------------------------
# An initiative's own shape: property definitions, roles and members
# ---------------------------------------------------------------------------


def _structural_entry(type_: str, payload: dict, initiative_id=1):  # noqa: D401
    """One of the two files describing the initiative rather than its content."""
    name = type_.removeprefix("initiative-")
    entry = {
        "path": f"initiatives/1-restored/{name}.json",
        "tool": "initiative",
        "type": type_,
        "schema_version": 1,
        "entity_id": initiative_id,
        "title": "Restored",
        "initiative_id": initiative_id,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    return entry, payload


async def test_backup_restores_property_definitions_in_full(
    client, acting_user, session, monkeypatch, role_session
):
    """The definitions arrive as they were, rather than being rebuilt from
    whichever values happened to reference them."""
    from sqlmodel import select

    from app.testing import route_session_to_guild

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    entry, payload = _structural_entry(
        "initiative-properties",
        {
            "type": "initiative-properties",
            "schema_version": 1,
            "properties": [
                {
                    "name": "Region",
                    "type": "select",
                    "position": 0,
                    "color": "#abcdef",
                    "options": [
                        {"id": "n", "label": "North"},
                        {"id": "s", "label": "South"},
                    ],
                }
            ],
        },
    )
    manifest = _minimal_manifest(entries=[entry])
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(payload).encode()}
    )

    job = await _apply_backup(client, a, zip_bytes, monkeypatch, role_session)
    assert job["status"] == ImportJobStatus.done.value, job.get("error")

    from app.models.tenant.property import PropertyDefinition

    await route_session_to_guild(session, a.guild.id)
    definitions = {
        d.name: d
        for d in await session.exec(select(PropertyDefinition))
        if d.name == "Region"
    }
    region = definitions["Region"]
    assert [o["label"] for o in region.options] == ["North", "South"]
    assert region.color == "#abcdef"


async def test_backup_restores_roles_and_places_members(
    client, acting_user, session, monkeypatch, role_session
):
    """Roles the target lacks are created; people already in the community are
    placed into the initiative at the role the archive names."""
    from sqlmodel import select

    from app.core.user_display import handle_of
    from app.testing import route_session_to_guild

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    other = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    handle = handle_of(other.user)

    entry, payload = _structural_entry(
        "initiative-structure",
        {
            "type": "initiative-structure",
            "schema_version": 1,
            "roles": [
                {
                    "name": "lorekeeper",
                    "display_name": "Lorekeeper",
                    "is_manager": False,
                    "override_share_restrictions": False,
                    "position": 5,
                    "permissions": ["create_files"],
                }
            ],
            "members": [{"handle": handle, "role": "lorekeeper"}],
        },
    )
    manifest = _minimal_manifest(entries=[entry])
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(payload).encode()}
    )

    job = await _apply_backup(client, a, zip_bytes, monkeypatch, role_session)
    assert job["status"] == ImportJobStatus.done.value, job.get("error")

    from app.models.tenant.initiative import (
        Initiative,
        InitiativeMember,
        InitiativeRoleModel,
    )

    await route_session_to_guild(session, a.guild.id)
    created = (
        await session.exec(select(Initiative).where(Initiative.name == "Restored"))
    ).one()
    role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == created.id,
                InitiativeRoleModel.name == "lorekeeper",
            )
        )
    ).one()
    assert role.display_name == "Lorekeeper"
    member = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == created.id,
                InitiativeMember.user_id == other.user.id,
            )
        )
    ).one()
    assert member.role_id == role.id


async def test_backup_structure_never_overwrites_what_is_already_there(
    client, acting_user, session, monkeypatch, role_session
):
    """Applying is additive: a role of the same name is the target's answer,
    and nobody is removed or moved by an import."""
    from sqlmodel import select

    from app.testing import route_session_to_guild

    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    entry, payload = _structural_entry(
        "initiative-structure",
        {
            "type": "initiative-structure",
            "schema_version": 1,
            # A name every initiative already has.
            "roles": [
                {
                    "name": "member",
                    "display_name": "Renamed By The Archive",
                    "is_manager": True,
                    "permissions": [],
                }
            ],
            "members": [],
        },
    )
    manifest = _minimal_manifest(entries=[entry], initiative_id=a.initiative.id)
    manifest["initiatives"][0]["target_initiative_id"] = a.initiative.id
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(payload).encode()}
    )

    job = await _apply_backup(client, a, zip_bytes, monkeypatch, role_session)
    assert job["status"] == ImportJobStatus.done.value, job.get("error")

    from app.models.tenant.initiative import InitiativeRoleModel

    await route_session_to_guild(session, a.guild.id)
    roles = list(
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == a.initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    )
    assert len(roles) == 1
    assert roles[0].display_name != "Renamed By The Archive"


# ---------------------------------------------------------------------------
# Atlassian connect
# ---------------------------------------------------------------------------


def _atlassian_site(*, jira_status=200, confluence_status=200):
    """Stub one Atlassian site for the endpoint's egress."""
    import httpx

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "/rest/api/3/project/search" in url:
            if jira_status != 200:
                return httpx.Response(jira_status, json={})
            return httpx.Response(
                200, json={"values": [{"id": "1", "key": "ACME", "name": "Acme"}]}
            )
        if "/rest/api/3/search/approximate-count" in url:
            return httpx.Response(200, json={"count": 12})
        if "/wiki/api/v2/spaces" in url:
            if confluence_status != 200:
                return httpx.Response(confluence_status, json={})
            return httpx.Response(
                200, json={"results": [{"id": "9", "key": "DOCS", "name": "Docs"}]}
            )
        if "/wiki/rest/api/search" in url:
            return httpx.Response(200, json={"totalSize": 4})
        return httpx.Response(404, json={})

    return fake_request


async def _connect(client, actor, **overrides):
    body = {
        "site_url": "https://acme.atlassian.net",
        "email": "someone@example.com",
        "api_token": "shhh",
        **overrides,
    }
    return await client.post(
        actor.g("/imports/atlassian/connect"), headers=actor.headers, json=body
    )


async def test_connect_proves_the_token_and_says_what_is_there(
    client, acting_user, session, monkeypatch
):
    """One request answers both of the connect step's questions."""
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(atlassian_service, "request_public_target", _atlassian_site())
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    resp = await _connect(client, a)
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["site_url"] == "https://acme.atlassian.net"
    assert body["jira"]["available"] is True
    assert [(p["key"], p["issue_count"]) for p in body["jira"]["projects"]] == [
        ("ACME", 12)
    ]
    assert [(s["key"], s["page_count"]) for s in body["confluence"]["spaces"]] == [
        ("DOCS", 4)
    ]

    # The connect keeps nothing and hands nothing back to quote: the token
    # comes again with the request that starts an import.
    assert "shhh" not in resp.text
    assert "credential_id" not in body


async def test_a_rejected_token_is_an_error_not_a_connection(
    client, acting_user, session, monkeypatch
):
    """A token the site will not take fails the connect."""
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(
        atlassian_service,
        "request_public_target",
        _atlassian_site(jira_status=401),
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    resp = await _connect(client, a)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_SOURCE_AUTH"


async def test_connect_refuses_an_address_it_would_have_to_downgrade_for(
    client, acting_user, monkeypatch
):
    """http would put the token on the wire in the clear, so the address is
    refused before anything is sent anywhere."""
    from app.services.import_engine import atlassian as atlassian_service

    async def never_called(*a, **kw):  # pragma: no cover - must not run
        raise AssertionError("no request should be made for a refused address")

    monkeypatch.setattr(atlassian_service, "request_public_target", never_called)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    resp = await _connect(client, a, site_url="http://acme.atlassian.net")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_SOURCE_UNREACHABLE"


# ---------------------------------------------------------------------------
# A Jira import as a job: start → fetch → review → apply
# ---------------------------------------------------------------------------


_JIRA_STATUSES = [
    {
        "name": "Story",
        "statuses": [
            {"id": "1", "name": "To Do", "statusCategory": {"key": "new"}},
            {"id": "2", "name": "Done", "statusCategory": {"key": "done"}},
        ],
    }
]


def _jira_site(
    *, issues=None, locked=(), on_request=None, catalog=None, boards=None, files=None
):
    """Stub a site that answers both a connect and a fetch.

    ``locked`` names projects the token cannot read; ``on_request`` sees every
    URL before it is answered, which is how a test reaches into the middle of
    a fetch. ``catalog`` is the site's field list and ``boards`` maps a board
    id to its name.
    """
    import httpx

    probe = _atlassian_site()
    requested: list[str] = []

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        requested.append(url)
        if on_request is not None:
            await on_request(url)
        if any(f"/rest/api/3/project/{key}" in url for key in locked):
            return httpx.Response(403, json={})
        if "/rest/api/3/project/search" in url:
            return await probe(method, url, headers=headers, json=json)
        if url.endswith("/statuses"):
            return httpx.Response(200, json=_JIRA_STATUSES)
        if "/rest/api/3/project/" in url:
            key = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"key": key, "name": f"{key} Board"})
        if "/rest/api/3/search/jql" in url:
            return httpx.Response(200, json={"issues": issues or []})
        if "/rest/agile/1.0/board?" in url:
            return httpx.Response(404, json={})
        if "/attachment/content/" in url and files:
            attachment_id = url.split("/attachment/content/")[1].split("?")[0]
            if attachment_id in files:
                return httpx.Response(200, content=files[attachment_id])
        if url.endswith("/rest/api/3/field") and catalog is not None:
            return httpx.Response(200, json=catalog)
        if "/rest/agile/1.0/board/" in url and boards:
            board_id = int(url.rsplit("/", 1)[-1])
            if board_id in boards:
                return httpx.Response(
                    200, json={"id": board_id, "name": boards[board_id]}
                )
        return await probe(method, url, headers=headers, json=json)

    fake_request.requested = requested  # type: ignore[attr-defined]
    return fake_request


def _jira_issue(key, summary, status="To Do", assignee=None):
    fields = {"summary": summary, "status": {"name": status}}
    if assignee:
        fields["assignee"] = {"displayName": assignee}
    return {"key": key, "fields": fields}


async def _start_jira(client, actor, *, initiative_id, keys=("ACME",), **overrides):
    body = {
        "site_url": "https://acme.atlassian.net",
        "email": "someone@example.com",
        "api_token": "shhh",
        "initiative_id": initiative_id,
        "project_keys": list(keys),
        **overrides,
    }
    return await client.post(
        actor.g("/imports/atlassian/import"), headers=actor.headers, json=body
    )


async def _job_secret(session, guild_id, job_id):
    """The secret still on a job row, read as the system engine."""
    from app.db.session import set_rls_context

    session.expunge_all()
    await set_rls_context(session, SystemGuild(guild_id))
    job = await session.get(ImportJob, job_id)
    return None if job is None else job.secret_encrypted


async def test_a_jira_import_fetches_then_waits_for_review_then_applies(
    client, acting_user, session, monkeypatch, role_session
):
    """The whole path, once: the fetch reads the site into a bundle and parks
    it for review with nothing written, the review names the people and the
    counts, and the confirm files the project into the chosen initiative.

    The credential is gone the moment the bundle is staged — the review can
    wait for hours, and it has no need of a live secret to do it.
    """
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task
    from app.services.import_engine import atlassian as atlassian_service

    site = _jira_site(
        issues=[
            _jira_issue("ACME-1", "Wire the thing", assignee="Pat Smith"),
            _jira_issue("ACME-2", "Ship the thing", status="Done"),
        ]
    )
    monkeypatch.setattr(atlassian_service, "request_public_target", site)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    resp = await _start_jira(client, a, initiative_id=a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == ImportJobStatus.queued.value
    assert job["source"] == "atlassian"
    assert job["params"]["jira_projects"] == ["ACME"]
    assert job["params"]["site_url"] == "https://acme.atlassian.net"
    assert "shhh" not in resp.text

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    plan = staged["plan"]
    assert plan["atlassian"]["projects"] == 1
    assert plan["atlassian"]["tasks"] == 2
    assert plan["atlassian"]["unreadable_projects"] == []
    assert plan["initiatives"][0]["target_initiative_id"] == a.initiative.id
    assert [p["handle"] for p in plan["people"]] == ["Pat Smith"]

    # Fetched, not applied: no project yet, and the token is already gone.
    assert (
        await session.exec(select(Project).where(Project.name == "ACME Board"))
    ).one_or_none() is None
    assert await _job_secret(session, a.guild.id, job["id"]) is None

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    done = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")
    assert done["result"]["initiatives"][0]["initiative_id"] == a.initiative.id

    session.expunge_all()
    project = (
        await session.exec(select(Project).where(Project.name == "ACME Board"))
    ).one()
    assert project.initiative_id == a.initiative.id
    titles = {
        t.title
        for t in (
            await session.exec(select(Task).where(Task.project_id == project.id))
        ).all()
    }
    assert titles == {"Wire the thing", "Ship the thing"}


async def test_a_jira_import_brings_its_links_across(
    client, acting_user, session, monkeypatch, role_session
):
    """What Jira connected arrives connected: the blocked issue depends on its
    blocker, the sub-task is part of its parent, and a link to an issue that
    was not brought over is counted in the plan before anybody confirms and
    in the report after."""
    from sqlmodel import select

    from app.models.tenant.relationship import EntityRelationship
    from app.models.tenant.task import Task
    from app.services.import_engine import atlassian as atlassian_service

    blocker = _jira_issue("ACME-1", "Fit the frame")
    blocker["fields"]["issuelinks"] = [
        {
            "id": "10",
            "type": {"name": "Blocks", "outward": "blocks"},
            "outwardIssue": {"key": "ACME-2"},
        }
    ]
    blocked = _jira_issue("ACME-2", "Hang the door")
    blocked["fields"]["issuelinks"] = [
        {
            "id": "10",
            "type": {"name": "Blocks", "outward": "blocks"},
            "inwardIssue": {"key": "ACME-1"},
        },
        {
            "id": "11",
            "type": {"name": "Relates", "outward": "relates to"},
            "outwardIssue": {"key": "OPS-9"},
        },
    ]
    step = _jira_issue("ACME-3", "Oil the hinges")
    step["fields"]["parent"] = {"key": "ACME-2"}

    monkeypatch.setattr(
        atlassian_service,
        "request_public_target",
        _jira_site(issues=[blocker, blocked, step]),
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    assert staged["plan"]["atlassian"]["links"] == 2
    assert staged["plan"]["atlassian"]["links_outside_selection"] == 1

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")
    assert done["result"]["links_created"] == 2
    assert done["result"]["links_unresolved"] == 1

    session.expunge_all()
    ids = {
        t.title: t.id
        for t in (await session.exec(select(Task))).all()
        if t.title in {"Fit the frame", "Hang the door", "Oil the hinges"}
    }
    edges = {
        (row.source_id, row.relationship_type, row.target_id)
        for row in (
            await session.exec(
                select(EntityRelationship).where(
                    EntityRelationship.source_type == "task",
                    EntityRelationship.target_type == "task",
                )
            )
        ).all()
    }
    assert (ids["Hang the door"], "depends_on", ids["Fit the frame"]) in edges
    assert (ids["Oil the hinges"], "part_of", ids["Hang the door"]) in edges
    assert len(edges) == 2


async def test_a_jira_import_brings_its_fields_as_properties(
    client, acting_user, session, monkeypatch, role_session
):
    """What issues filled in arrives as properties, and a person field — the
    Reporter — is asked about in the people step and lands on whoever it was
    mapped to."""
    from sqlmodel import select

    from app.models.tenant.property import PropertyDefinition, PropertyValue
    from app.models.tenant.task import Task
    from app.services.import_engine import atlassian as atlassian_service

    issue = _jira_issue("ACME-1", "Fit the frame")
    issue["fields"]["priority"] = {"name": "Highest"}
    issue["fields"]["reporter"] = {"displayName": "Robin"}
    monkeypatch.setattr(
        atlassian_service, "request_public_target", _jira_site(issues=[issue])
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    listed = {p["name"]: p for p in staged["plan"]["atlassian"]["properties"]}
    assert listed["Priority"] == {
        "name": "Priority",
        "type": "select",
        "issue_count": 1,
    }
    assert listed["Reporter"]["type"] == "user_reference"
    assert "Robin" in [p["handle"] for p in staged["plan"]["people"]]

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"Robin": a.user.id}},
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    task = (await session.exec(select(Task).where(Task.title == "Fit the frame"))).one()
    rows = (
        await session.exec(
            select(PropertyValue, PropertyDefinition)
            .join(
                PropertyDefinition,
                PropertyDefinition.id == PropertyValue.property_id,
            )
            .where(
                PropertyValue.entity_type == "task", PropertyValue.entity_id == task.id
            )
        )
    ).all()
    by_name = {definition.name: value for value, definition in rows}
    assert by_name["Priority"].value_text == "Highest"
    assert by_name["Jira key"].value_text == "ACME-1"
    assert by_name["Reporter"].value_user_id == a.user.id


_SPRINT_CATALOG = [
    {
        "id": "customfield_10020",
        "name": "Sprint",
        "custom": True,
        "schema": {
            "type": "array",
            "items": "json",
            "custom": "com.pyxis.greenhopper.jira:gh-sprint",
        },
    }
]


def _in_sprint(issue, sprint_id=7, name="Sprint 7"):
    issue["fields"]["customfield_10020"] = [
        {
            "id": sprint_id,
            "name": name,
            "state": "closed",
            "boardId": 3,
            "goal": "Ship the door",
            "startDate": "2024-03-04T09:00:00.000Z",
            "endDate": "2024-03-18T09:00:00.000Z",
            "completeDate": "2024-03-18T10:00:00.000Z",
        }
    ]
    return issue


async def test_a_jira_sprint_becomes_an_event_its_tasks_are_related_to(
    client, acting_user, session, monkeypatch, role_session
):
    """A sprint lands once, as an event on a calendar named after its board,
    and each task that was in it is related to it — its dates live on the
    event, not copied onto every task (D11)."""
    from sqlmodel import select

    from app.core.tools import Tool
    from app.models.tenant.calendar import Calendar
    from app.models.tenant.calendar_event import CalendarEvent
    from app.models.tenant.relationship import EntityRelationship
    from app.models.tenant.task import Task
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(
        atlassian_service,
        "request_public_target",
        _jira_site(
            issues=[
                _in_sprint(_jira_issue("ACME-1", "Fit the frame")),
                _in_sprint(_jira_issue("ACME-2", "Hang the door")),
            ],
            catalog=_SPRINT_CATALOG,
            boards={3: "Door team"},
        ),
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    setattr(a.initiative, Tool.calendar.view_permission, True)
    session.add(a.initiative)
    await session.commit()

    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]
    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["sprints"], summary["sprint_calendars"]) == (1, 1)
    assert summary["sprints_skipped"] is None

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    calendar = (
        await session.exec(select(Calendar).where(Calendar.name == "Door team"))
    ).one()
    event = (
        await session.exec(
            select(CalendarEvent).where(CalendarEvent.calendar_id == calendar.id)
        )
    ).one()
    assert event.title == "Sprint 7"
    assert "Ship the door" in (event.description or "")
    task_ids = {
        t.id
        for t in (await session.exec(select(Task))).all()
        if t.title in {"Fit the frame", "Hang the door"}
    }
    # related_to is symmetric and stored once, in node order, so the event can
    # be either end; whichever it is, the other end is the task.
    rows = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.relationship_type == "related_to"
            )
        )
    ).all()
    related = {
        row.target_id if row.source_type == "calendar_event" else row.source_id
        for row in rows
        if (row.source_type, row.source_id) == ("calendar_event", event.id)
        or (row.target_type, row.target_id) == ("calendar_event", event.id)
    }
    assert related == task_ids


async def test_sprints_are_left_behind_and_said_so_when_calendars_are_off(
    client, acting_user, session, monkeypatch, role_session
):
    """An initiative without calendars cannot hold a sprint. The projects
    still come over, and the plan says why the sprints do not — rather than
    the apply refusing everything over a tool the projects never needed."""
    from sqlmodel import select

    from app.core.tools import Tool
    from app.models.tenant.calendar import Calendar
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(
        atlassian_service,
        "request_public_target",
        _jira_site(
            issues=[_in_sprint(_jira_issue("ACME-1", "Fit the frame"))],
            catalog=_SPRINT_CATALOG,
            boards={3: "Door team"},
        ),
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    setattr(a.initiative, Tool.calendar.view_permission, False)
    session.add(a.initiative)
    await session.commit()

    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]
    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    summary = staged["plan"]["atlassian"]
    assert summary["sprints"] == 1
    assert summary["sprint_calendars"] == 0
    assert summary["sprints_skipped"] == "IMPORT_TOOL_DISABLED"

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")
    assert done["result"]["links_unresolved"] == 0

    session.expunge_all()
    assert not (await session.exec(select(Calendar))).all()


async def test_a_jira_import_brings_its_comments_to_whoever_wrote_them(
    client, acting_user, session, monkeypatch, role_session
):
    """Comments land on their task, oldest first; the one somebody mapped in
    the people step is that member's, one nobody mapped keeps its writer's
    name, and one restricted to a role at the source stays behind."""
    from sqlmodel import select

    from app.models.tenant.comment import Comment
    from app.models.tenant.task import Task
    from app.services.import_engine import atlassian as atlassian_service

    def body(text):
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            ],
        }

    issue = _jira_issue("ACME-1", "Fit the frame")
    issue["fields"]["comment"] = {
        "total": 3,
        "comments": [
            {
                "author": {"displayName": "Robin"},
                "body": body("Measured twice"),
                "created": "2024-03-04T09:00:00.000+0000",
            },
            {
                "author": {"displayName": "Sam"},
                "body": body("Cut once"),
                "created": "2024-03-05T09:00:00.000+0000",
            },
            {
                "author": {"displayName": "Ash"},
                "body": body("Admins only"),
                "created": "2024-03-06T09:00:00.000+0000",
                "visibility": {"type": "role", "value": "Administrators"},
            },
        ],
    }
    monkeypatch.setattr(
        atlassian_service, "request_public_target", _jira_site(issues=[issue])
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["comments"], summary["comments_restricted"]) == (2, 1)
    people = {p["handle"]: p["comment_count"] for p in staged["plan"]["people"]}
    assert people == {"Robin": 1, "Sam": 1}

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"Robin": a.user.id}},
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    task = (await session.exec(select(Task).where(Task.title == "Fit the frame"))).one()
    comments = (
        await session.exec(
            select(Comment)
            .where(Comment.task_id == task.id)
            .order_by(Comment.created_at)
        )
    ).all()
    assert [c.content for c in comments] == ["Measured twice", "Cut once"]
    assert comments[0].created_by == a.user.id
    assert comments[0].imported_author_name is None
    assert comments[1].imported_author_name == "Sam"


async def test_a_jira_import_brings_its_images_as_uploads(
    client, acting_user, session, monkeypatch, role_session
):
    """An attached image lands in the community's storage as an ordinary
    upload, and the task shows it; a PDF beside it becomes an uploaded file of
    its own, and the task is attached to it."""
    from sqlmodel import select

    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.models.tenant.file import File
    from app.models.tenant.task import Task
    from app.models.tenant.upload import Upload
    from app.services.import_engine import atlassian as atlassian_service
    from app.services.storage import get_guild_storage
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant.relationships import Endpoint

    png = _PNG
    pdf = b"%PDF-spec"
    issue = _jira_issue("ACME-1", "Fit the frame")
    issue["fields"]["attachment"] = [
        {
            "id": "10",
            "filename": "frame.png",
            "mimeType": "image/png",
            "size": len(png),
        },
        {
            "id": "11",
            "filename": "spec.pdf",
            "mimeType": "application/pdf",
            "size": len(pdf),
        },
    ]
    monkeypatch.setattr(
        atlassian_service,
        "request_public_target",
        _jira_site(issues=[issue], files={"10": png, "11": pdf}),
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["images"], summary["files"], summary["other_attachments"]) == (
        1,
        1,
        0,
    )
    assert summary["image_bytes"] == len(png)
    assert summary["file_bytes"] == len(pdf)

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")
    assert done["result"]["assets_restored"] == 2

    session.expunge_all()
    task = (await session.exec(select(Task).where(Task.title == "Fit the frame"))).one()
    upload = (
        await session.exec(select(Upload).where(Upload.content_type == "image/png"))
    ).one()
    assert f"/uploads/{a.guild.id}/{upload.filename}" in (task.description or "")
    blob = get_guild_storage(a.guild.id).open_readable(upload.filename)
    assert blob is not None

    file = (
        await session.exec(select(File).where(File.current_version_id.is_not(None)))
    ).one()
    assert file.current_version.original_filename == "spec.pdf"
    assert await relationships_service.related_ids(
        session,
        Endpoint(kind=SearchEntityType.task, id=task.id),
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.file,
    ) == [file.id]


async def test_a_jira_file_stays_behind_when_the_initiative_has_no_files(
    client, acting_user, session, monkeypatch, role_session
):
    """The pictures still come; the file is counted rather than taking the
    whole import down with it."""
    from app.services.import_engine import atlassian as atlassian_service

    png = _PNG
    issue = _jira_issue("ACME-1", "Fit the frame")
    issue["fields"]["attachment"] = [
        {
            "id": "10",
            "filename": "frame.png",
            "mimeType": "image/png",
            "size": len(png),
        },
        {"id": "11", "filename": "spec.pdf", "mimeType": "application/pdf", "size": 9},
    ]
    monkeypatch.setattr(
        atlassian_service,
        "request_public_target",
        _jira_site(issues=[issue], files={"10": png, "11": b"%PDF-spec"}),
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    a.initiative.files_enabled = False
    session.add(a.initiative)
    await session.commit()
    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["images"], summary["files"], summary["other_attachments"]) == (
        1,
        0,
        1,
    )


async def test_a_property_unticked_on_the_review_is_not_created(
    client, acting_user, session, monkeypatch, role_session
):
    """The review lists every property the import would add to the
    initiative; one unticked there is not created, and no task carries a
    value for it. The rest arrive as usual."""
    from sqlmodel import select

    from app.models.tenant.property import PropertyDefinition, PropertyValue
    from app.models.tenant.task import Task
    from app.services.import_engine import atlassian as atlassian_service

    issue = _jira_issue("ACME-1", "Fit the frame")
    issue["fields"]["priority"] = {"name": "Highest"}
    issue["fields"]["issuetype"] = {"name": "Story"}
    monkeypatch.setattr(
        atlassian_service, "request_public_target", _jira_site(issues=[issue])
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]
    await _run_import_worker(monkeypatch, role_session)

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"exclude_properties": ["Priority"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["params"]["exclude_properties"] == ["Priority"]
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    names = {
        d.name
        for d in (
            await session.exec(
                select(PropertyDefinition).where(
                    PropertyDefinition.initiative_id == a.initiative.id
                )
            )
        ).all()
    }
    assert "Priority" not in names
    assert "Jira key" in names
    # The issue type is the task's own type rather than a property.
    assert "Issue type" not in names

    task = (await session.exec(select(Task).where(Task.title == "Fit the frame"))).one()
    values = (
        await session.exec(
            select(PropertyValue, PropertyDefinition)
            .join(
                PropertyDefinition,
                PropertyDefinition.id == PropertyValue.property_id,
            )
            .where(
                PropertyValue.entity_type == "task", PropertyValue.entity_id == task.id
            )
        )
    ).all()
    assert {definition.name for _value, definition in values} == {"Jira key"}
    from app.models.tenant.task import TaskType

    task_type = await session.get(TaskType, task.task_type_id)
    assert task_type is not None and task_type.name == "Story"


@pytest.mark.parametrize(
    "bad",
    ["Priority", [1, 2], [""], ["x" * 256], ["p"] * 501],
)
async def test_confirm_refuses_a_malformed_list_of_unticked_properties(
    client, acting_user, session, bad
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    job = await create_import_job(
        session,
        a.guild,
        a.user,
        source="atlassian",
        params={},
        status=ImportJobStatus.staged,
        payload_ref="imports/x.zip",
    )

    resp = await client.post(
        a.g(f"/imports/jobs/{job.id}/confirm"),
        headers=a.headers,
        json={"exclude_properties": bad},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_INVALID_PARAMS"


async def test_starting_a_jira_import_refuses_what_it_can_up_front(
    client, acting_user, session, monkeypatch
):
    """Everything that can be refused before the site is read is refused
    before the site is read, so the answer arrives in the wizard rather than
    as a failed job minutes later."""
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(atlassian_service, "request_public_target", _jira_site())
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    nothing = await _start_jira(client, a, initiative_id=a.initiative.id, keys=())
    assert nothing.status_code == 400
    assert nothing.json()["detail"] == "IMPORT_SOURCE_NOTHING_SELECTED"

    # A key travels into a URL path and a JQL clause at the other end, so one
    # that is not shaped like a Jira key never gets that far.
    malformed = await _start_jira(
        client,
        a,
        initiative_id=a.initiative.id,
        keys=('ACME" OR project = "X',),
    )
    assert malformed.status_code == 422

    target = await _second_initiative(session, a, projects_enabled=False)
    disabled = await _start_jira(client, a, initiative_id=target.id)
    assert disabled.status_code == 400
    assert disabled.json()["detail"] == "IMPORT_TOOL_DISABLED"

    first = await _start_jira(client, a, initiative_id=a.initiative.id)
    assert first.status_code == 202, first.text
    # Each job carries its own secret, so a second import of the same site is
    # an ordinary second job rather than a contested connection.
    second = await _start_jira(client, a, initiative_id=a.initiative.id)
    assert second.status_code == 202, second.text
    assert second.json()["id"] != first.json()["id"]


async def test_a_site_that_refuses_every_project_fails_the_job_and_drops_the_token(
    client, acting_user, session, monkeypatch, role_session
):
    """A failed fetch is a failed job with a code, a notification, and no
    credential left behind."""
    from sqlmodel import select

    from app.models.platform.notification import Notification, NotificationType
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(
        atlassian_service, "request_public_target", _jira_site(locked=("ACME",))
    )
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]

    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_SOURCE_UNREACHABLE"
    await drain_notices()
    failed = [
        n
        for n in (
            await session.exec(
                select(Notification).where(Notification.user_id == a.user.id)
            )
        ).all()
        if n.type == NotificationType.import_failed
    ]
    assert [n.data["import_job_id"] for n in failed] == [job_id]

    # Last, because it reads the row as the system rather than as anybody.
    assert await _job_secret(session, a.guild.id, job["id"]) is None


async def test_cancelling_a_fetch_stops_it_at_the_next_project(
    client, acting_user, session, monkeypatch, role_session
):
    """A fetch has written nothing but its own payload, so stopping one is
    safe — and it should actually stop, not read the rest of the site first
    and throw it away."""
    from app.services.import_engine import atlassian as atlassian_service

    state: dict = {}

    async def cancel_mid_read(url):
        # The first project's issues are being read: cancel the job, as the
        # wizard's Cancel button would, before the second is reached.
        if "search/jql" in url and not state.get("cancelled"):
            state["cancelled"] = True
            resp = await client.delete(
                state["actor"].g(f"/imports/jobs/{state['job_id']}"),
                headers=state["actor"].headers,
            )
            assert resp.status_code == 200, resp.text

    site = _jira_site(issues=[_jira_issue("ACME-1", "One")], on_request=cancel_mid_read)
    monkeypatch.setattr(atlassian_service, "request_public_target", site)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    job_id = (
        await _start_jira(
            client,
            a,
            initiative_id=a.initiative.id,
            keys=("ACME", "BETA"),
        )
    ).json()["id"]
    state.update(actor=a, job_id=job_id)

    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.cancelled.value
    assert not any("/project/BETA" in url for url in site.requested)
    assert await _job_secret(session, a.guild.id, job["id"]) is None


# ---------------------------------------------------------------------------
# Imports from another product's export file
# ---------------------------------------------------------------------------

TODOIST_CSV = (
    "TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,AUTHOR,RESPONSIBLE,DATE,"
    "DATE_LANG,TIMEZONE,DURATION,DURATION_UNIT,meta,DEADLINE,DEADLINE_LANG\n"
    "section,Doing,,,,,,,,,,,,,\n"
    "task,Ship it,With detail,1,1,,,,,,,,,2026-03-09,\n"
    "task,A step,,4,2,,,,,,,,,,\n"
    "note,Said something,,,,Dana (42),,,,,,,,,\n"
)


async def _preview_foreign(client, actor, source, content):
    return await client.post(
        actor.g(f"/imports/foreign/{source}/preview"),
        headers={**actor.headers, "Content-Type": "text/plain"},
        content=content.encode(),
    )


async def test_preview_says_what_a_todoist_export_holds(client, acting_user):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    resp = await _preview_foreign(client, a, "todoist", TODOIST_CSV)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "todoist"
    # A Todoist CSV names one project and does not say which, so the step that
    # follows collects a name rather than offering a choice.
    assert body["picks_one"] is False
    assert body["options"][0]["task_count"] == 1


async def test_preview_of_an_unknown_product_is_refused(client, acting_user):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    resp = await _preview_foreign(client, a, "trello", "anything")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_UNKNOWN_SOURCE"


async def test_preview_of_a_file_that_is_not_that_export_is_refused(
    client, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    resp = await _preview_foreign(client, a, "vikunja", "this is not json }{{{")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_FILE_UNREADABLE"


async def test_a_todoist_export_becomes_a_project(client, acting_user, session):
    """The whole point: a foreign file lands as a project carrying what it
    said — statuses from its sections, a checklist, a comment, a deadline —
    through the same apply path an exported project takes."""
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    resp = await client.post(
        a.g("/imports/foreign/todoist"),
        headers=a.headers,
        json={
            "initiative_id": a.initiative.id,
            "selection": "From Todoist",
            "content": TODOIST_CSV,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["result"]["created"]["tasks"] == 1

    project = (
        await session.exec(select(Project).where(Project.name == "From Todoist"))
    ).first()
    assert project is not None
    task = (await session.exec(select(Task).where(Task.project_id == project.id))).one()
    assert task.title == "Ship it"
    assert [item["text"] for item in task.checklist] == ["A step"]
    assert task.due_date is not None


async def test_a_real_sized_export_arrives_whole(
    client, acting_user, session, monkeypatch
):
    """An export is not a short string. A file past the plain-text field
    ceiling — which every real export is — used to be refused with a 422
    before the handler ran, and markup in a task's text was stripped on the
    way in. The file is the file: every row lands, and so does what it said.
    """
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task
    from app.schemas.base import MAX_PLAIN_TEXT_LENGTH

    header, *rows = TODOIST_CSV.splitlines()
    padding = [
        f"task,Filler task number {i} with a longish title,,4,1,,,,,,,,,,"
        for i in range(400)
    ]
    content = "\n".join(
        [header, rows[0], "task,Compare a < b & <b>c</b>,,1,1,,,,,,,,,,", *padding]
    )
    assert len(content) > MAX_PLAIN_TEXT_LENGTH
    # Applied in the request, so what landed can be read straight back.
    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 10_000)

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    resp = await client.post(
        a.g("/imports/foreign/todoist"),
        headers=a.headers,
        json={
            "initiative_id": a.initiative.id,
            "selection": "Big Todoist",
            "content": content,
        },
    )
    assert resp.status_code == 201, resp.text

    project = (
        await session.exec(select(Project).where(Project.name == "Big Todoist"))
    ).one()
    titles = {
        t.title
        for t in (
            await session.exec(select(Task).where(Task.project_id == project.id))
        ).all()
    }
    assert len(titles) == 401
    # The characters survive; the markup is stripped by the task title's own
    # rule, the same one a title typed in the app goes through.
    assert "Compare a < b & c" in titles


async def test_importing_from_a_product_needs_the_create_permission(
    client, acting_user, session
):
    """Nothing about arriving from another product widens who may create a
    project here — it is the same gate the envelope route applies."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    other = await _second_initiative(session, a)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=other,
        initiative_role="member",
    )
    resp = await client.post(
        b.g("/imports/foreign/todoist"),
        headers=b.headers,
        json={
            "initiative_id": other.id,
            "selection": "Nope",
            "content": TODOIST_CSV,
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "IMPORT_PERMISSION_REQUIRED"


async def test_importing_into_an_initiative_you_cannot_reach_is_a_404(
    client, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    resp = await client.post(
        a.g("/imports/foreign/todoist"),
        headers=a.headers,
        json={
            "initiative_id": 9_999_999,
            "selection": "Nope",
            "content": TODOIST_CSV,
        },
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Confluence: a space becomes a wiki
# ---------------------------------------------------------------------------


def _confluence_site(
    *, pages, users=None, labels=None, attachments=None, files=None, comments=None
):
    """Stub a Confluence site answering a connect and a fetch of one space."""
    import httpx

    probe = _atlassian_site()
    names: dict[str, str] = users or {}
    page_labels: dict[str, list[str]] = labels or {}
    page_attachments: dict[str, list[dict]] = attachments or {}
    blobs: dict[str, bytes] = files or {}
    threads: dict[str, list[dict]] = comments or {}

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "-comments" in url:
            path = url.split("/wiki/api/v2/")[1].split("?")[0]
            return httpx.Response(200, json={"results": threads.get(path, [])})
        if "/attachments?" in url:
            page_id = url.split("/pages/")[1].split("/")[0]
            return httpx.Response(
                200, json={"results": page_attachments.get(page_id, [])}
            )
        if "/child/attachment/" in url:
            att_id = url.split("/child/attachment/")[1].split("/")[0]
            return httpx.Response(
                302, headers={"location": f"https://media.example.com/{att_id}"}
            )
        if url.startswith("https://media.example.com/"):
            return httpx.Response(200, content=blobs[url.rsplit("/", 1)[1]])
        if "/wiki/api/v2/spaces?keys=" in url:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "9", "key": "DOCS", "name": "Docs", "homepageId": "1"}
                    ]
                },
            )
        if "/wiki/api/v2/spaces/9/pages" in url:
            return httpx.Response(200, json={"results": pages})
        if "/labels" in url:
            page_id = url.split("/pages/")[1].split("/")[0]
            return httpx.Response(
                200,
                json={"results": [{"name": n} for n in page_labels.get(page_id, [])]},
            )
        if url.endswith("/wiki/api/v2/users-bulk"):
            wanted = (json or {}).get("accountIds") or []
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"accountId": a, "displayName": names[a]}
                        for a in wanted
                        if a in names
                    ]
                },
            )
        return await probe(method, url, headers=headers, json=json)

    return fake_request


def _confluence_page(page_id, title, body, parent=None, author="acc-1"):
    return {
        "id": str(page_id),
        "title": title,
        "parentId": str(parent) if parent else None,
        "parentType": "page" if parent else None,
        "position": page_id,
        "authorId": author,
        "createdAt": "2024-03-04T09:00:00.000Z",
        "version": {"createdAt": "2024-05-01T10:00:00.000Z"},
        "body": {"storage": {"value": body}},
    }


async def _start_confluence(client, actor, *, initiative_id, keys=("DOCS",)):
    return await client.post(
        actor.g("/imports/atlassian/import"),
        headers=actor.headers,
        json={
            "site_url": "https://acme.atlassian.net",
            "email": "someone@example.com",
            "api_token": "shhh",
            "initiative_id": initiative_id,
            "space_keys": list(keys),
        },
    )


async def test_a_confluence_space_becomes_a_wiki_with_its_tree_and_its_people(
    client, acting_user, session, monkeypatch, role_session
):
    """Fetch, review, confirm, apply: the space arrives as one wiki in the
    chosen initiative, its pages under their parents, a link between two of
    them pointing at the imported page, and the people the review placed —
    the author and somebody mentioned — named on the pages they are on."""
    from sqlmodel import select

    from app.models.tenant.wiki import Wiki, WikiPage
    from app.services.import_engine import atlassian as atlassian_service

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    site = _confluence_site(
        pages=[
            _confluence_page(1, "Home", "<p>Welcome</p>"),
            _confluence_page(
                2,
                "Guide",
                '<p>Read <ac:link><ri:page ri:content-title="Home"/></ac:link> and '
                'ask <ac:link><ri:user ri:account-id="acc-2"/></ac:link></p>',
                parent=1,
            ),
        ],
        users={"acc-1": "Robin Ade", "acc-2": "Sam Bee"},
        labels={"2": ["howto"]},
    )
    monkeypatch.setattr(atlassian_service, "request_public_target", site)

    resp = await _start_confluence(client, a, initiative_id=a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["params"]["confluence_spaces"] == ["DOCS"]
    assert "shhh" not in resp.text

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["spaces"], summary["pages"], summary["labels"]) == (1, 2, 1)
    assert {p["handle"] for p in staged["plan"]["people"]} == {"Robin Ade", "Sam Bee"}
    assert await _job_secret(session, a.guild.id, job["id"]) is None

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"),
        headers=a.headers,
        json={"people_map": {"Robin Ade": a.user.id, "Sam Bee": b.user.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)
    done = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    wiki = (await session.exec(select(Wiki).where(Wiki.name == "Docs"))).one()
    assert wiki.initiative_id == a.initiative.id
    pages = {
        p.title: p
        for p in (
            await session.exec(select(WikiPage).where(WikiPage.wiki_id == wiki.id))
        ).all()
    }
    home, guide = pages["Home"], pages["Guide"]
    assert wiki.home_page_id == home.id
    assert guide.parent_page_id == home.id
    assert guide.created_by == a.user.id

    (paragraph,) = guide.content["root"]["children"]
    by_type = {n["type"]: n for n in paragraph["children"]}
    assert by_type["entity-mention"]["entityId"] == home.id
    assert "importSlug" not in by_type["entity-mention"]
    assert by_type["mention"]["mentionUserId"] == b.user.id


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDA"
    b"Tx\xdac\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xf7\x03AC\x00\x00\x00"
    b"\x00IEND\xaeB`\x82"
)
_PDF = b"%PDF-spec"


def _attachment_site():
    """One page showing a picture, linking a PDF, and holding a picture it
    never shows."""
    png, pdf = _PNG, _PDF
    return _confluence_site(
        pages=[
            _confluence_page(
                1,
                "Home",
                '<p><ac:image><ri:attachment ri:filename="chart.png"/></ac:image>'
                '<ac:link><ri:attachment ri:filename="spec.pdf"/>'
                "<ac:plain-text-link-body><![CDATA[the spec]]>"
                "</ac:plain-text-link-body></ac:link></p>",
            )
        ],
        users={"acc-1": "Robin Ade"},
        attachments={
            "1": [
                {
                    "id": "att1",
                    "title": "chart.png",
                    "mediaType": "image/png",
                    "fileSize": len(png),
                },
                {
                    "id": "att2",
                    "title": "spec.pdf",
                    "mediaType": "application/pdf",
                    "fileSize": len(pdf),
                },
                {
                    "id": "att3",
                    "title": "hidden.png",
                    "mediaType": "image/png",
                    "fileSize": len(png),
                },
            ]
        },
        files={"att1": png, "att2": pdf, "att3": png},
    )


async def test_a_confluence_pages_attachments_arrive_as_uploads_and_files(
    client, acting_user, session, monkeypatch, role_session
):
    """A picture the page shows is an upload it renders from; a file it links
    to is a file filed in the wiki, and the link is a mention of it; a
    picture nobody shows is a file too, rather than lost."""
    from sqlmodel import select

    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.models.tenant.file import File
    from app.models.tenant.wiki import Wiki, WikiPage
    from app.services.import_engine import atlassian as atlassian_service
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant.relationships import Endpoint

    png, pdf = _PNG, _PDF
    site = _attachment_site()
    monkeypatch.setattr(atlassian_service, "request_public_target", site)
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    job_id = (await _start_confluence(client, a, initiative_id=a.initiative.id)).json()[
        "id"
    ]
    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["page_images"], summary["page_files"]) == (1, 2)
    assert summary["page_attachment_bytes"] == 2 * len(png) + len(pdf)

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")
    assert done["result"]["assets_restored"] == 3

    session.expunge_all()
    wiki = (await session.exec(select(Wiki).where(Wiki.name == "Docs"))).one()
    home = (
        await session.exec(select(WikiPage).where(WikiPage.wiki_id == wiki.id))
    ).one()
    files = {
        d.current_version.original_filename: d
        for d in (
            await session.exec(
                select(File).where(
                    File.initiative_id == a.initiative.id,
                    File.current_version_id.is_not(None),
                )
            )
        ).all()
    }
    assert set(files) == {"spec.pdf", "hidden.png"}
    assert sorted(
        await relationships_service.related_ids(
            session,
            Endpoint(kind=SearchEntityType.wiki, id=wiki.id),
            relationship_type=RelationshipType.part_of,
            other_kind=SearchEntityType.file,
        )
    ) == sorted(d.id for d in files.values())

    # Filed in the wiki under the page they were attached to.
    await session.refresh(wiki)
    from app.services.tenant.wikis import file_parent

    assert {file_parent(wiki, d.id) for d in files.values()} == {home.id}

    (paragraph,) = home.content["root"]["children"]
    image, mention = paragraph["children"]
    assert image["src"].startswith(f"/uploads/{a.guild.id}/")
    assert mention["entityType"] == "file"
    assert mention["entityId"] == files["spec.pdf"].id
    assert mention["text"] == "the spec" and "importRef" not in mention


async def test_an_initiative_without_files_takes_only_the_pictures(
    client, acting_user, session, monkeypatch, role_session
):
    """Attachments would be files, which this initiative has switched off: the
    pictures the page shows still come, the rest are counted as left behind,
    and the import is not refused over them."""
    from sqlmodel import select

    from app.models.tenant.file import File
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(atlassian_service, "request_public_target", _attachment_site())
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    a.initiative.files_enabled = False
    session.add(a.initiative)
    await session.commit()

    job_id = (await _start_confluence(client, a, initiative_id=a.initiative.id)).json()[
        "id"
    ]
    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["page_images"], summary["page_files"]) == (1, 0)
    assert summary["page_files_blocked"] == 2

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")
    session.expunge_all()
    assert (await session.exec(select(File))).all() == []


async def test_a_confluence_pages_comments_arrive_on_its_wiki_page(
    client, acting_user, session, monkeypatch, role_session
):
    """Footer and inline comments land in the page's thread, replies under what
    they answer, each under whoever the people step said wrote it — and a
    comment's link to another page points at the page it became."""
    from sqlmodel import select

    from app.models.tenant.comment import Comment
    from app.models.tenant.wiki import Wiki, WikiPage
    from app.services.import_engine import atlassian as atlassian_service

    def said(comment_id, body, author):
        return {
            "id": str(comment_id),
            "version": {"authorId": author, "createdAt": "2024-05-01T10:00:00.000Z"},
            "body": {"storage": {"value": body}},
        }

    site = _confluence_site(
        pages=[
            _confluence_page(1, "Home", "<p>Welcome</p>"),
            _confluence_page(2, "Guide", "<p>How to</p>", parent=1),
        ],
        users={"acc-1": "Robin Ade", "acc-2": "Sam Bee"},
        comments={
            "pages/1/footer-comments": [
                said(
                    10,
                    '<p>Read <ac:link><ri:page ri:content-title="Guide"/></ac:link> '
                    '<ac:link><ri:user ri:account-id="acc-2"/></ac:link></p>',
                    "acc-1",
                )
            ],
            "footer-comments/10/children": [said(11, "<p>Done</p>", "acc-2")],
            "pages/1/inline-comments": [
                {
                    **said(20, "<p>Typo</p>", "acc-2"),
                    "properties": {"inlineOriginalSelection": "Welcom"},
                }
            ],
        },
    )
    monkeypatch.setattr(atlassian_service, "request_public_target", site)
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    job_id = (await _start_confluence(client, a, initiative_id=a.initiative.id)).json()[
        "id"
    ]
    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    assert staged["plan"]["atlassian"]["page_comments"] == 3

    # Robin is placed; Sam is left as a name.
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"Robin Ade": b.user.id}},
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    wiki = (await session.exec(select(Wiki).where(Wiki.name == "Docs"))).one()
    pages = {
        p.title: p
        for p in (
            await session.exec(select(WikiPage).where(WikiPage.wiki_id == wiki.id))
        ).all()
    }
    thread = (
        await session.exec(
            select(Comment)
            .where(Comment.wiki_page_id == pages["Home"].id)
            .order_by(Comment.id)
        )
    ).all()
    first, reply, inline = thread
    assert first.created_by == b.user.id and first.imported_author_name is None
    assert first.content == (f"Read #wiki_page[Guide]({pages['Guide'].id}) @Sam Bee")
    assert reply.parent_comment_id == first.id
    assert reply.created_by == a.user.id and reply.imported_author_name == "Sam Bee"
    assert inline.content == "> Welcom\n\nTypo"


async def _upload_export(client, actor, zip_bytes, *, initiative_id, **form):
    return await client.post(
        actor.g("/imports/atlassian/export"),
        headers=actor.headers,
        data={"initiative_id": str(initiative_id), **form},
        files={"file": ("export.zip", zip_bytes, "application/zip")},
    )


async def test_a_confluence_html_export_becomes_a_wiki(
    client, acting_user, session, monkeypatch, role_session
):
    """Upload the zip Confluence's space export writes: the worker converts
    it, the review shows it like a fetched space, and confirming files the
    wiki, its tree and its files into the chosen initiative — no site, no
    token."""
    from sqlmodel import select

    from app.models.tenant.file import File
    from app.models.tenant.wiki import Wiki, WikiPage
    from app.services.import_engine.confluence_export_test import export_bytes
    from app.services.tenant.wikis import file_parent

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    resp = await _upload_export(
        client, a, export_bytes(), initiative_id=a.initiative.id
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["spaces"], summary["pages"]) == (1, 4)
    assert (summary["page_images"], summary["page_files"]) == (1, 1)
    assert {p["handle"] for p in staged["plan"]["people"]} == {"Robin Ade", "Sam Bee"}

    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"Robin Ade": b.user.id}},
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    wiki = (await session.exec(select(Wiki).where(Wiki.name == "Team Docs"))).one()
    assert wiki.initiative_id == a.initiative.id
    pages = {
        p.title: p
        for p in (
            await session.exec(select(WikiPage).where(WikiPage.wiki_id == wiki.id))
        ).all()
    }
    assert wiki.home_page_id == pages["Home"].id
    assert pages["Guide"].parent_page_id == pages["Home"].id
    assert pages["Home"].created_by == b.user.id
    file = (
        await session.exec(select(File).where(File.current_version_id.is_not(None)))
    ).one()
    assert file.current_version.original_filename == "spec.pdf"
    assert file_parent(wiki, file.id) == pages["Home"].id


async def test_an_upload_that_is_not_an_export_is_refused_up_front(client, acting_user):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    not_zip = await _upload_export(
        client, a, b"not a zip", initiative_id=a.initiative.id
    )
    assert not_zip.status_code == 400
    assert not_zip.json()["detail"] == "IMPORT_ZIP_INVALID"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "hello")
    no_pages = await _upload_export(
        client, a, buffer.getvalue(), initiative_id=a.initiative.id
    )
    assert no_pages.status_code == 400
    assert no_pages.json()["detail"] == "IMPORT_ZIP_INVALID"


async def test_starting_a_confluence_import_refuses_what_it_can_up_front(
    client, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    nothing = await _start_confluence(client, a, initiative_id=a.initiative.id, keys=())
    assert nothing.status_code == 400
    assert nothing.json()["detail"] == "IMPORT_SOURCE_NOTHING_SELECTED"

    bad_key = await _start_confluence(
        client, a, initiative_id=a.initiative.id, keys=("DOCS/../x",)
    )
    assert bad_key.status_code == 422


async def test_a_confluence_page_points_its_jira_issues_at_the_tasks_they_became(
    client, acting_user, session, monkeypatch, role_session
):
    """An issue the Jira import already brought over is found by the key it
    recorded: the page's Jira macro becomes that task and its live status,
    and a plain link to it a mention of it. One that never came over keeps
    its link to Jira, and a status lozenge is a status in its colour."""
    from sqlmodel import select

    from app.models.tenant.wiki import Wiki, WikiPage
    from app.services.import_engine import atlassian as atlassian_service
    from app.testing import (
        create_property_definition,
        create_property_value,
        create_task,
    )

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    key_property = await create_property_definition(
        session, a.initiative, name="Jira key"
    )
    task = await create_task(session, a.project, title="Task 1")
    await create_property_value(session, task, key_property, value_text="SCRUM-1")

    site = _confluence_site(
        pages=[
            _confluence_page(
                1,
                "Roadmap",
                "<table><tr><td>"
                '<ac:structured-macro ac:name="jira">'
                '<ac:parameter ac:name="key">SCRUM-1</ac:parameter>'
                "</ac:structured-macro></td><td>"
                '<ac:structured-macro ac:name="jira">'
                '<ac:parameter ac:name="key">SCRUM-9</ac:parameter>'
                "</ac:structured-macro></td><td>"
                '<a href="https://acme.atlassian.net/browse/SCRUM-1">see SCRUM-1</a>'
                '</td><td><ac:structured-macro ac:name="status">'
                '<ac:parameter ac:name="colour">Green</ac:parameter>'
                '<ac:parameter ac:name="title">DONE</ac:parameter>'
                "</ac:structured-macro></td></tr></table>",
            )
        ],
        users={"acc-1": "Robin Ade"},
    )
    monkeypatch.setattr(atlassian_service, "request_public_target", site)

    resp = await _start_confluence(client, a, initiative_id=a.initiative.id)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    await _run_import_worker(monkeypatch, role_session)
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    wiki = (await session.exec(select(Wiki).where(Wiki.name == "Docs"))).one()
    page = (
        await session.exec(select(WikiPage).where(WikiPage.wiki_id == wiki.id))
    ).one()
    (table,) = page.content["root"]["children"]
    cells = [
        cell["children"][0]["children"] for cell in table["children"][0]["children"]
    ]
    found, missing, linked, lozenge = cells

    mention, _space, chip = found
    assert (mention["type"], mention["entityType"], mention["entityId"]) == (
        "entity-mention",
        "task",
        task.id,
    )
    assert (chip["type"], chip["chipKind"], chip["entityId"]) == (
        "smart-chip",
        "task:status",
        task.id,
    )
    assert missing[0]["type"] == "link"
    assert missing[0]["url"] == "https://acme.atlassian.net/browse/SCRUM-9"
    assert all(node["type"] != "smart-chip" for node in missing)
    assert linked == [
        {
            "type": "entity-mention",
            "version": 1,
            "entityType": "task",
            "entityId": task.id,
            "text": "see SCRUM-1",
        }
    ]
    assert lozenge == [
        {"type": "status", "version": 1, "text": "DONE", "color": "green"}
    ]
    assert "importJiraKey" not in str(page.content)


async def test_one_atlassian_import_joins_its_issues_and_pages_both_ways(
    client, acting_user, session, monkeypatch, role_session
):
    """Projects and spaces read together are joined whichever way they point:
    the page's Jira macro is the task and its live status, the issue's link
    to the page is a mention of the wiki page, and the page the issue lists
    under "Confluence pages" is related to its task. Found through the job
    itself — the Jira key property is unticked here, and it still joins."""
    import httpx
    from sqlmodel import select

    from app.models.tenant.relationship import EntityRelationship
    from app.models.tenant.task import Task
    from app.models.tenant.wiki import WikiPage
    from app.services.import_engine import atlassian as atlassian_service

    page_url = "https://acme.atlassian.net/wiki/spaces/DOCS/pages/2/Guide"
    issue = _jira_issue("ACME-1", "Wire the thing")
    issue["fields"]["description"] = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Read "},
                    {
                        "type": "text",
                        "text": "the guide",
                        "marks": [{"type": "link", "attrs": {"href": page_url}}],
                    },
                ],
            }
        ],
    }
    jira = _jira_site(issues=[issue])
    confluence = _confluence_site(
        pages=[
            _confluence_page(
                2,
                "Guide",
                '<p>Tracked in <ac:structured-macro ac:name="jira">'
                '<ac:parameter ac:name="key">ACME-1</ac:parameter>'
                "</ac:structured-macro></p>",
            )
        ],
        users={"acc-1": "Robin Ade"},
    )

    async def both(method, url, *, headers=None, json=None, timeout=None, **kw):
        if url.endswith("/remotelink"):
            return httpx.Response(
                200,
                json=[
                    {
                        "application": {"type": "com.atlassian.confluence"},
                        "object": {
                            "url": "https://acme.atlassian.net/wiki/pages/"
                            "viewpage.action?pageId=2",
                            "title": "Guide",
                        },
                    }
                ],
            )
        site = confluence if "/wiki/" in url else jira
        return await site(method, url, headers=headers, json=json, timeout=timeout)

    monkeypatch.setattr(atlassian_service, "request_public_target", both)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    resp = await client.post(
        a.g("/imports/atlassian/import"),
        headers=a.headers,
        json={
            "site_url": "https://acme.atlassian.net",
            "email": "someone@example.com",
            "api_token": "shhh",
            "initiative_id": a.initiative.id,
            "project_keys": ["ACME"],
            "space_keys": ["DOCS"],
        },
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]
    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    summary = staged["plan"]["atlassian"]
    assert (summary["projects"], summary["tasks"]) == (1, 1)
    assert (summary["spaces"], summary["pages"]) == (1, 1)
    # The macro, the description's link and the "Confluence pages" entry.
    assert summary["cross_links"] == 3

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"exclude_properties": ["Jira key"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)
    done = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")

    session.expunge_all()
    task = (
        await session.exec(select(Task).where(Task.title == "Wire the thing"))
    ).one()
    page = (await session.exec(select(WikiPage).where(WikiPage.title == "Guide"))).one()

    assert f"#wiki_page[the guide]({page.id})" in (task.description or "")
    (paragraph,) = page.content["root"]["children"]
    by_type = {node["type"]: node for node in paragraph["children"]}
    assert by_type["entity-mention"]["entityId"] == task.id
    assert by_type["smart-chip"]["entityId"] == task.id
    edges = (await session.exec(select(EntityRelationship))).all()
    ends = {
        frozenset({(e.source_type, e.source_id), (e.target_type, e.target_id)})
        for e in edges
        if e.relationship_type == "related_to"
    }
    assert frozenset({("task", task.id), ("wiki_page", page.id)}) in ends


async def test_an_apply_touches_its_row_as_it_goes(
    client, acting_user, monkeypatch, role_session
):
    """Each entry applied refreshes the job's row, so a long apply is never
    taken for a crashed one by the stale sweep."""
    from app.services.import_engine import atlassian

    monkeypatch.setattr(atlassian, "HEARTBEAT_SECONDS", 0)
    beats: list[int] = []
    real_throttled = import_worker.throttled

    def counting(beat):
        async def counted():
            beats.append(1)
            await beat()

        return real_throttled(counted)

    monkeypatch.setattr(import_worker, "throttled", counting)
    a = await acting_user(
        guild_role=CommunityRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )

    job = await _apply_backup(client, a, zip_bytes, monkeypatch, role_session)

    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert beats


# --- running imports side by side -------------------------------------------


_QUEUE_ENVELOPE = {
    "type": "initiative-queue",
    "schema_version": 1,
    "name": "Side by side",
    "items": [{"label": "Aria", "position": 1.0}],
}


async def _queued(client, actor) -> int:
    response = await _import_envelope(
        client, actor, _QUEUE_ENVELOPE, actor.initiative.id
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def _status(client, actor, job_id) -> str:
    job = (
        await client.get(actor.g(f"/imports/jobs/{job_id}"), headers=actor.headers)
    ).json()
    return job["status"]


async def _user_sessions(monkeypatch, role_session, count):
    sessions = iter([await role_session("app_admin") for _ in range(count)])
    monkeypatch.setattr(
        import_worker, "_open_user_session", lambda _guild_id: next(sessions)
    )


async def test_two_communities_import_side_by_side(
    client, acting_user, monkeypatch, role_session
):
    """One pass starts a job in each community, and neither waits for the
    other to finish."""
    import asyncio

    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first, second = await _queued(client, a), await _queued(client, b)
    await _user_sessions(monkeypatch, role_session, 2)

    started = await import_worker.jobs.dispatch()

    assert len(started) == 2
    await asyncio.gather(*started)
    assert await _status(client, a, first) == ImportJobStatus.done.value
    assert await _status(client, b, second) == ImportJobStatus.done.value


async def test_a_community_runs_one_import_at_a_time(
    client, acting_user, monkeypatch, role_session
):
    import asyncio

    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first, second = await _queued(client, a), await _queued(client, a)
    await _user_sessions(monkeypatch, role_session, 2)

    started = await import_worker.jobs.dispatch()

    assert len(started) == 1
    await asyncio.gather(*started)
    assert await _status(client, a, first) == ImportJobStatus.done.value
    assert await _status(client, a, second) == ImportJobStatus.queued.value

    await import_worker.process_import_jobs()
    assert await _status(client, a, second) == ImportJobStatus.done.value


async def test_a_process_starts_no_more_than_its_slots(
    client, acting_user, monkeypatch, role_session
):
    import asyncio

    monkeypatch.setattr(import_limits, "IMPORT_INLINE_MAX_ROWS", 0)
    monkeypatch.setattr(import_limits, "IMPORT_APPLY_SLOTS", 1)
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    b = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _queued(client, a)
    await _queued(client, b)
    await _user_sessions(monkeypatch, role_session, 2)

    started = await import_worker.jobs.dispatch()

    assert len(started) == 1
    await asyncio.gather(*started)
    await import_worker.process_import_jobs()


async def test_the_sweep_leaves_a_job_this_process_is_running(
    acting_user, session, monkeypatch
):
    """A row that looks stale but belongs to a job this process is running is
    not failed out from under it."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    job = await create_import_job(
        session,
        a.guild,
        a.user,
        source="initiative-queue",
        params={"initiative_id": a.initiative.id},
        payload_ref="imports/elsewhere.json",
        status=ImportJobStatus.running,
        created_at=stale_time,
        updated_at=stale_time,
    )

    alive = asyncio.create_task(asyncio.sleep(3600))
    monkeypatch.setitem(
        import_worker.jobs.running, (a.guild.id, job.id), ("apply", alive)
    )
    try:
        await import_worker.jobs.dispatch()
    finally:
        alive.cancel()

    await session.refresh(job)
    assert job.status == ImportJobStatus.running
