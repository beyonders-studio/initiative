"""The task and task-status routes an installed plug-in calls.

Each test installs a plug-in (placed in initiative A, not in B) and calls the
routes with its installation token on the real-role client. A task answers to
the projects scopes; people in requests and responses are named by the
install's own references.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import select

from app.core.messages import PluginMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task
from app.testing import (
    create_resource_grant,
    guild_url,
    create_project,
    create_relationship,
    create_task,
    route_session_to_guild,
    drain_notices,
)
from app.testing.plugin_clients import (
    assert_names_nobody,
    install_plugin,
    install_headers,
    lift_person_and_guild_ids,
)


READ = ["projects:read"]
WRITE = ["projects:read", "projects:write"]


def _at(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


async def _reference_for_seat(
    client: Any, session: Any, installed: Any, headers: dict
) -> str:
    """What the install calls the seat, from the owner of a project the seat
    made and shared with the install's initiative."""
    project = await create_project(
        session, installed.placed, installed.seat.user, name="Seat's"
    )
    await create_resource_grant(session, project, all_initiative_members=True)
    read = await client.get(
        guild_url(installed.guild.id, f"/projects/{project.id}"), headers=headers
    )
    assert read.status_code == 200, read.text
    reference = read.json()["owner_id"]
    assert isinstance(reference, str)
    return reference


async def _own_project(client: Any, installed: Any, headers: dict, name: str) -> int:
    created = await client.post(
        guild_url(installed.guild.id, "/projects/"),
        headers=headers,
        json={"name": name, "initiative_id": installed.placed.id},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _assignment_lines(session: Any, user_id: int) -> list[Notification]:
    await drain_notices()
    return list(
        (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.type == NotificationType.task_assignment,
                )
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# Reach
# ---------------------------------------------------------------------------


async def test_reads_the_tasks_of_projects_open_to_its_initiative(
    client, session, acting_user, role_session
):
    installed = await install_plugin(session, acting_user, role_session, granted=READ)
    in_a = await create_project(
        session, installed.placed, installed.seat.user, name="Open in A"
    )
    await create_resource_grant(session, in_a, all_initiative_members=True)
    in_b = await create_project(
        session, installed.unplaced, installed.seat.user, name="Open in B"
    )
    await create_resource_grant(session, in_b, all_initiative_members=True)
    task_a = await create_task(session, in_a, title="Task in A")
    task_b = await create_task(session, in_b, title="Task in B")
    headers = install_headers(installed, READ)
    gid = installed.guild.id

    listed = await client.get(guild_url(gid, "/tasks/"), headers=headers)
    assert listed.status_code == 200, listed.text
    assert [t["title"] for t in listed.json()["items"]] == ["Task in A"]

    read = await client.get(guild_url(gid, f"/tasks/{task_a.id}"), headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["title"] == "Task in A"
    other = await client.get(guild_url(gid, f"/tasks/{task_b.id}"), headers=headers)
    assert other.status_code == 404, other.text

    statuses = await client.get(
        guild_url(gid, f"/projects/{in_a.id}/task-statuses/"), headers=headers
    )
    assert statuses.status_code == 200, statuses.text
    assert task_a.task_status_id in [s["id"] for s in statuses.json()]
    hidden = await client.get(
        guild_url(gid, f"/projects/{in_b.id}/task-statuses/"), headers=headers
    )
    assert hidden.status_code == 404, hidden.text

    gathered = await client.get(
        guild_url(gid, f"/initiatives/{installed.placed.id}/task-statuses/"),
        headers=headers,
    )
    assert gathered.status_code == 200, gathered.text
    assert [(s["name"], s["project_count"]) for s in gathered.json()] == [
        ("To Do", 1),
        ("In Progress", 1),
        ("Done", 1),
    ]
    unplaced = await client.get(
        guild_url(gid, f"/initiatives/{installed.unplaced.id}/task-statuses/"),
        headers=headers,
    )
    assert unplaced.status_code == 404, unplaced.text


async def test_lists_with_the_filters_a_scan_sends(
    client, session, acting_user, role_session
):
    installed = await install_plugin(session, acting_user, role_session, granted=READ)
    project = await create_project(session, installed.placed, installed.seat.user)
    await create_resource_grant(session, project, all_initiative_members=True)
    await create_task(
        session,
        project,
        title="Late",
        due_date=_at("2026-01-02"),
        assignees=[installed.seat.user],
    )
    await create_task(session, project, title="Later", due_date=_at("2026-03-02"))
    await create_task(session, project, title="Nobody's", due_date=_at("2026-01-03"))
    headers = install_headers(installed, READ)
    conditions = [
        {"field": "due_date", "op": "gte", "value": "2026-01-01T00:00:00+00:00"},
        {"field": "due_date", "op": "lt", "value": "2026-02-01T00:00:00+00:00"},
        {
            "field": "status_category",
            "op": "in_",
            "value": ["done"],
            "negate": True,
        },
        {"field": "initiative_ids", "op": "in_", "value": [installed.placed.id]},
    ]

    listed = await client.get(
        guild_url(installed.guild.id, "/tasks/"),
        headers=headers,
        params={
            "conditions": json.dumps(conditions),
            "sorting": json.dumps([{"field": "due_date", "dir": "asc"}]),
            "page": 1,
            "page_size": 100,
        },
    )
    assert listed.status_code == 200, listed.text
    assert [t["title"] for t in listed.json()["items"]] == ["Late", "Nobody's"]

    # A filter names a person by what the install calls them.
    [seat] = listed.json()["items"][0]["assignees"]

    def _assigned_to(value: Any) -> dict[str, str]:
        return {
            "conditions": json.dumps(
                [{"field": "assignee_ids", "op": "in_", "value": [value]}]
            )
        }

    by_person = await client.get(
        guild_url(installed.guild.id, "/tasks/"),
        headers=headers,
        params=_assigned_to(seat["id"]),
    )
    assert by_person.status_code == 200, by_person.text
    assert [t["title"] for t in by_person.json()["items"]] == ["Late"]
    # JSON that leads with whitespace names the same person.
    padded = await client.get(
        guild_url(installed.guild.id, "/tasks/"),
        headers=headers,
        params={"conditions": " \n\t" + _assigned_to(seat["id"])["conditions"]},
    )
    assert padded.status_code == 200, padded.text
    assert [t["title"] for t in padded.json()["items"]] == ["Late"]
    for named in (installed.seat.user.id, "uplu_" + "x" * 32):
        refused = await client.get(
            guild_url(installed.guild.id, "/tasks/"),
            headers=headers,
            params=_assigned_to(named),
        )
        assert refused.status_code == 422, (named, refused.text)
        assert refused.json()["detail"] == PluginMessages.REFERENCE_UNKNOWN


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


async def test_a_write_needs_the_write_scope(
    client, session, acting_user, role_session
):
    installed = await install_plugin(session, acting_user, role_session, granted=WRITE)
    project = await create_project(session, installed.placed, installed.seat.user)
    await create_resource_grant(session, project, all_initiative_members=True)
    task = await create_task(session, project, title="Read only")
    other = await create_project(session, installed.placed, installed.seat.user)
    headers = install_headers(installed, READ)
    gid = installed.guild.id

    attempts = [
        lambda: client.post(
            guild_url(gid, "/tasks/"),
            headers=headers,
            json={"project_id": project.id, "title": "No"},
        ),
        lambda: client.patch(
            guild_url(gid, f"/tasks/{task.id}"), headers=headers, json={"title": "No"}
        ),
        lambda: client.post(
            guild_url(gid, f"/tasks/{task.id}/move"),
            headers=headers,
            json={"target_project_id": other.id},
        ),
        lambda: client.patch(
            guild_url(gid, f"/tasks/{task.id}/checklist/item1"),
            headers=headers,
            json={"done": True},
        ),
        lambda: client.post(
            guild_url(gid, f"/tasks/{task.id}/duplicate"), headers=headers
        ),
    ]
    for attempt in attempts:
        response = await attempt()
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == PluginMessages.SCOPE_REQUIRED


async def test_creates_a_task_assigned_by_reference_and_names_nobody(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(session, acting_user, role_session, granted=WRITE)
    headers = install_headers(installed, WRITE)
    gid = installed.guild.id
    seat_ref = await _reference_for_seat(client, session, installed, headers)
    project_id = await _own_project(client, installed, headers, "The plug-in's")

    created = await client.post(
        guild_url(gid, "/tasks/"),
        headers=headers,
        json={
            "project_id": project_id,
            "title": "Made by the plug-in",
            "description": "Follow up",
            "priority": "high",
            "due_date": "2026-10-01T09:00:00+00:00",
            "assignee_ids": [seat_ref],
            "checklist": [{"text": "First"}],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created_by"] is None
    assert [a["id"] for a in body["assignees"]] == [seat_ref]
    assert_names_nobody(created.text, [installed.seat.user.id, gid])

    listed = await client.get(guild_url(gid, "/tasks/"), headers=headers)
    assert listed.status_code == 200, listed.text
    row = next(t for t in listed.json()["items"] if t["id"] == body["id"])
    assert [a["id"] for a in row["assignees"]] == [seat_ref]
    assert isinstance(row["community_id"], str)
    assert_names_nobody(listed.text, [installed.seat.user.id, gid])

    await route_session_to_guild(session, gid)
    stored = await session.get(Task, body["id"])
    assert stored is not None and stored.created_by is None

    lines = await _assignment_lines(session, installed.seat.user.id)
    assert [line.data["assigned_by_name"] for line in lines] == [installed.plugin.name]

    # A person reading the same task is served row ids, as always.
    person = await client.get(
        guild_url(gid, f"/tasks/{body['id']}"), headers=installed.seat.headers
    )
    assert person.status_code == 200, person.text
    assert [a["id"] for a in person.json()["assignees"]] == [installed.seat.user.id]


async def test_an_assignee_named_by_row_id_or_foreign_reference_is_refused(
    client, session, acting_user, role_session
):
    installed = await install_plugin(session, acting_user, role_session, granted=WRITE)
    headers = install_headers(installed, WRITE)
    gid = installed.guild.id
    seat_ref = await _reference_for_seat(client, session, installed, headers)
    project_id = await _own_project(client, installed, headers, "The plug-in's")

    for named in (installed.seat.user.id, seat_ref[:-2] + "zz"):
        response = await client.post(
            guild_url(gid, "/tasks/"),
            headers=headers,
            json={"project_id": project_id, "title": "No", "assignee_ids": [named]},
        )
        assert response.status_code == 422, response.text


async def test_updates_moves_ticks_and_duplicates_what_it_may_write(
    client, session, acting_user, role_session
):
    await lift_person_and_guild_ids(session)
    installed = await install_plugin(session, acting_user, role_session, granted=WRITE)
    headers = install_headers(installed, WRITE)
    gid = installed.guild.id
    seat_ref = await _reference_for_seat(client, session, installed, headers)
    first = await _own_project(client, installed, headers, "First")
    second = await _own_project(client, installed, headers, "Second")

    created = await client.post(
        guild_url(gid, "/tasks/"),
        headers=headers,
        json={"project_id": first, "title": "Draft", "checklist": [{"text": "a"}]},
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    item_id = created.json()["checklist"][0]["id"]

    updated = await client.patch(
        guild_url(gid, f"/tasks/{task_id}"),
        headers=headers,
        json={"title": "Final", "priority": "urgent", "assignee_ids": [seat_ref]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "Final"
    assert [a["id"] for a in updated.json()["assignees"]] == [seat_ref]
    assert_names_nobody(updated.text, [installed.seat.user.id, gid])

    await route_session_to_guild(session, gid)
    lines = await _assignment_lines(session, installed.seat.user.id)
    assert [line.data["assigned_by_name"] for line in lines] == [installed.plugin.name]

    ticked = await client.patch(
        guild_url(gid, f"/tasks/{task_id}/checklist/{item_id}"),
        headers=headers,
        json={"done": True},
    )
    assert ticked.status_code == 200, ticked.text
    assert [(i["id"], i["done"]) for i in ticked.json()] == [(item_id, True)]

    moved = await client.post(
        guild_url(gid, f"/tasks/{task_id}/move"),
        headers=headers,
        json={"target_project_id": second},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["project_id"] == second

    got = await client.get(guild_url(gid, f"/tasks/{task_id}"), headers=headers)
    assert got.status_code == 200, got.text
    assert got.json()["project_id"] == second
    assert_names_nobody(got.text, [installed.seat.user.id, gid])

    copied = await client.post(
        guild_url(gid, f"/tasks/{task_id}/duplicate"), headers=headers
    )
    assert copied.status_code == 201, copied.text
    assert copied.json()["title"] == "Final (Copy)"
    assert [a["id"] for a in copied.json()["assignees"]] == [seat_ref]
    assert_names_nobody(copied.text, [installed.seat.user.id, gid])


async def test_duplicates_a_project_with_the_shipped_layouts(
    client, session, acting_user, role_session
):
    """Layouts are not a plug-in's to read, so its copy of a project that
    stores some has the shipped ones."""
    installed = await install_plugin(session, acting_user, role_session, granted=WRITE)
    headers = install_headers(installed, WRITE)
    gid = installed.guild.id
    project_id = await _own_project(client, installed, headers, "Laid out")
    layouts = guild_url(gid, "/layouts/")
    saved = await client.put(
        layouts,
        params={"tool": "project", "tool_id": project_id},
        headers=installed.seat.headers,
        json={"kind": "table", "definition": {"columns": ["title"]}},
    )
    assert saved.status_code == 200, saved.text

    copied = await client.post(
        guild_url(gid, f"/projects/{project_id}/duplicate"), headers=headers
    )

    assert copied.status_code == 201, copied.text
    read = await client.get(
        layouts,
        params={"tool": "project", "tool_id": copied.json()["id"]},
        headers=installed.seat.headers,
    )
    assert read.status_code == 200, read.text
    assert {layout["updated_at"] for layout in read.json()["layouts"]} == {None}


async def test_makes_a_project_from_a_template_with_its_task_links(
    client, session, acting_user, role_session
):
    """A template's dependency lands between the copies a plug-in makes, with
    the install as the one making the links."""
    scopes = [*WRITE, "relationships:write"]
    installed = await install_plugin(session, acting_user, role_session, granted=scopes)
    template = await create_project(
        session, installed.placed, installed.seat.user, is_template=True
    )
    await create_resource_grant(session, template, all_initiative_members=True)
    design = await create_task(session, template, title="Design")
    build = await create_task(session, template, title="Build")
    await create_relationship(
        session,
        installed.guild,
        source=(SearchEntityType.task, build.id),
        target=(SearchEntityType.task, design.id),
        relationship_type=RelationshipType.depends_on,
    )

    created = await client.post(
        guild_url(installed.guild.id, "/projects/"),
        headers=install_headers(installed, scopes),
        json={
            "name": "From template",
            "initiative_id": installed.placed.id,
            "template_id": template.id,
        },
    )
    assert created.status_code == 201, created.text

    await route_session_to_guild(session, installed.guild.id)
    copies = {
        task.title: task.id
        for task in (
            await session.exec(
                select(Task).where(Task.project_id == created.json()["id"])
            )
        ).all()
    }
    edges = (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_id == copies["Build"],
                EntityRelationship.source_type == SearchEntityType.task.value,
            )
        )
    ).all()
    assert [(e.relationship_type, e.target_id, e.created_by) for e in edges] == [
        (RelationshipType.depends_on.value, copies["Design"], None)
    ]


async def test_a_task_in_a_project_it_only_reads_is_not_its_to_change(
    client, session, acting_user, role_session
):
    installed = await install_plugin(session, acting_user, role_session, granted=WRITE)
    project = await create_project(session, installed.placed, installed.seat.user)
    await create_resource_grant(session, project, all_initiative_members=True)
    task = await create_task(session, project, title="Theirs")
    headers = install_headers(installed, WRITE)

    response = await client.patch(
        guild_url(installed.guild.id, f"/tasks/{task.id}"),
        headers=headers,
        json={"title": "Mine now"},
    )
    assert response.status_code == 403, response.text
