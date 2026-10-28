"""Required fields: a page layout marks fields a person must fill in.

A person adding an item gives each one, and cannot empty one once it is
filled; an item that lacks one keeps it until a person fills it. A plug-in
acting as itself, an import and a repeating task's next one are not held to
it.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ToolLayoutMessages
from app.models.platform.guild import CommunityRole
from app.models.tenant.metadata import MetadataType
from app.services.tenant import task_types as task_types_service
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_collection,
    create_file,
    create_post,
    create_property_definition,
    create_resource_grant,
    create_tag,
    create_task,
    guild_url,
    route_session_to_guild,
)
from app.testing.plugin_clients import install_headers, install_plugin

MISSING = ToolLayoutMessages.REQUIRED_FIELDS_MISSING


def _required(field: str) -> dict[str, Any]:
    return {"type": "field", "props": {"field": field, "required": True}}


async def _require(
    client: AsyncClient,
    a: Any,
    params: dict[str, Any],
    kind: str,
    *side: dict[str, Any],
    task_type_id: int | None = None,
) -> None:
    """Lay out ``kind``'s page with ``side`` as its side column."""
    payload: dict[str, Any] = {"kind": kind, "definition": {"side": list(side)}}
    if task_type_id is not None:
        payload["task_type_id"] = task_type_id
    saved = await client.put(
        a.g("/layouts/"), params=params, json=payload, headers=a.headers
    )
    assert saved.status_code == 200, saved.text


async def _task_type(session: AsyncSession, a: Any, project_id: int) -> int:
    await route_session_to_guild(session, a.guild.id)
    type_id = (await task_types_service.list_types(session, project_id))[0].id
    assert type_id is not None
    return type_id


async def _require_on_tasks(
    client: AsyncClient, session: AsyncSession, a: Any, *side: dict[str, Any]
) -> int:
    """Require ``side`` on the project's task page; its type's id."""
    type_id = await _task_type(session, a, a.project.id)
    await _require(
        client,
        a,
        {"tool": "project", "tool_id": a.project.id},
        "task",
        *side,
        task_type_id=type_id,
    )
    return type_id


def _refused(response: Any, *fields: str) -> None:
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == MISSING
    assert response.json()["params"]["fields"].split("\n") == list(fields)


# -- The layout ---------------------------------------------------------------


@pytest.mark.parametrize(
    "part",
    [
        _required("title"),
        _required("type"),
        _required("plugin:3:ci.state"),
        {"type": "status", "props": {"required": True}},
    ],
    ids=["a title", "a type", "a plug-in's field", "a status"],
)
async def test_only_what_a_person_fills_in_can_be_required(
    client: AsyncClient, acting_user, part: dict[str, Any]
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    type_id = (
        await client.get(
            a.g("/layouts/"),
            params={"tool": "project", "tool_id": a.project.id},
            headers=a.headers,
        )
    ).json()["layouts"][-1]["task_type_id"]

    response = await client.put(
        a.g("/layouts/"),
        params={"tool": "project", "tool_id": a.project.id},
        json={
            "kind": "task",
            "task_type_id": type_id,
            "definition": {"side": [part]},
        },
        headers=a.headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "TOOL_LAYOUTS_KIND_NOT_ALLOWED"


async def test_a_required_property_is_one_its_items_carry_and_fill_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    checkbox = await create_property_definition(
        session, a.initiative, type=MetadataType.checkbox
    )
    collection = await create_collection(
        session,
        a.initiative,
        a.user,
        files=[await create_file(session, a.initiative, a.user)],
    )
    metadata = await create_property_definition(
        session, a.initiative, collection=collection
    )
    type_id = await _task_type(session, a, a.project.id)
    params = {"tool": "project", "tool_id": a.project.id}

    for field in (f"property:{checkbox.id}", f"property:{metadata.id}"):
        response = await client.put(
            a.g("/layouts/"),
            params=params,
            json={
                "kind": "task",
                "task_type_id": type_id,
                "definition": {"side": [_required(field)]},
            },
            headers=a.headers,
        )
        assert response.status_code == 400, response.text

    # The collection's own metadata is what its file page can require.
    await _require(
        client,
        a,
        {"tool": "collection", "tool_id": collection.id},
        "file",
        _required(f"property:{metadata.id}"),
    )


async def test_a_deleted_required_property_requires_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    size = await create_property_definition(session, a.initiative, name="Size")
    page = (_required("description"), _required(f"property:{size.id}"))
    type_id = await _require_on_tasks(client, session, a, *page)
    deleted = await client.delete(
        a.g(f"/property-definitions/{size.id}"), headers=a.headers
    )
    assert deleted.status_code == 204, deleted.text

    # The page still saves as it is, and asks only for what remains.
    await _require(
        client,
        a,
        {"tool": "project", "tool_id": a.project.id},
        "task",
        *page,
        task_type_id=type_id,
    )
    refused = await client.post(
        a.g("/tasks/"),
        json={"project_id": a.project.id, "title": "Plan"},
        headers=a.headers,
    )
    _refused(refused, "description")


# -- Tasks --------------------------------------------------------------------


async def test_a_task_is_added_with_what_its_type_requires(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    size = await create_property_definition(session, a.initiative, name="Size")
    await _require_on_tasks(
        client,
        session,
        a,
        _required("description"),
        _required(f"property:{size.id}"),
        {"type": "dates", "props": {"required": True}},
    )
    task = {"project_id": a.project.id, "title": "Plan"}

    refused = await client.post(a.g("/tasks/"), json=task, headers=a.headers)
    _refused(refused, "description", "Size", "dates")

    added = await client.post(
        a.g("/tasks/"),
        json={
            **task,
            "description": "What and why",
            "due_date": "2099-01-01T09:00:00Z",
            "properties": [{"property_id": size.id, "value": "Large"}],
        },
        headers=a.headers,
    )
    assert added.status_code == 201, added.text


async def test_a_required_checklist_takes_one_item(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await _require_on_tasks(client, session, a, _required("checklist"))
    task = {"project_id": a.project.id, "title": "Pack"}

    empty = await client.post(
        a.g("/tasks/"), json={**task, "checklist": []}, headers=a.headers
    )
    _refused(empty, "checklist")

    added = await client.post(
        a.g("/tasks/"),
        json={**task, "checklist": [{"text": "Tent"}]},
        headers=a.headers,
    )
    assert added.status_code == 201, added.text

    emptied = await client.patch(
        a.g(f"/tasks/{added.json()['id']}"),
        json={"checklist": []},
        headers=a.headers,
    )
    _refused(emptied, "checklist")


async def test_a_filled_required_field_cannot_be_emptied(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    size = await create_property_definition(session, a.initiative, name="Size")
    task = await create_task(session, a.project, description="Filled")
    await create_resource_grant(session, a.project, all_initiative_members=True)
    await client.put(
        a.g(f"/properties/task/{task.id}"),
        json={"values": [{"property_id": size.id, "value": "Large"}]},
        headers=a.headers,
    )
    await _require_on_tasks(
        client, session, a, _required("description"), _required(f"property:{size.id}")
    )

    cleared = await client.patch(
        a.g(f"/tasks/{task.id}"), json={"description": "  "}, headers=a.headers
    )
    _refused(cleared, "description")

    taken_off = await client.put(
        a.g(f"/properties/task/{task.id}"), json={"values": []}, headers=a.headers
    )
    _refused(taken_off, "Size")

    changed = await client.patch(
        a.g(f"/tasks/{task.id}"), json={"description": "Still here"}, headers=a.headers
    )
    assert changed.status_code == 200, changed.text


async def test_an_item_made_before_keeps_what_it_lacks_until_filled(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A task without a field its type has since required is edited as
    before, and its repeat makes the next one without it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = (
        await client.post(
            a.g("/tasks/"),
            json={
                "project_id": a.project.id,
                "title": "Water the plants",
                "due_date": "2099-01-01T09:00:00Z",
                "recurrence": "FREQ=WEEKLY",
            },
            headers=a.headers,
        )
    ).json()
    await _require_on_tasks(client, session, a, _required("description"))

    renamed = await client.patch(
        a.g(f"/tasks/{task['id']}"), json={"title": "Water them"}, headers=a.headers
    )
    assert renamed.status_code == 200, renamed.text

    done = await client.patch(
        a.g(f"/tasks/{task['id']}"),
        json={"status_category": "done"},
        headers=a.headers,
    )
    assert done.status_code == 200, done.text
    listed = await client.get(
        a.g("/tasks/"),
        params={"project_id": a.project.id},
        headers=a.headers,
    )
    assert len(listed.json()["items"]) == 2, listed.text


async def test_a_plugin_acting_as_itself_is_not_held_to_it(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    granted = ["projects:read", "projects:write"]
    installed = await install_plugin(
        session, acting_user, role_session, granted=granted
    )
    seat = installed.seat
    headers = install_headers(installed, granted)
    project = await client.post(
        guild_url(installed.guild.id, "/projects/"),
        json={"name": "The plug-in's", "initiative_id": installed.placed.id},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    type_id = await _task_type(session, seat, project_id)
    await _require(
        client,
        seat,
        {"tool": "project", "tool_id": project_id},
        "task",
        _required("description"),
        task_type_id=type_id,
    )
    task = {"project_id": project_id, "title": "Made by the plug-in"}

    made = await client.post(
        guild_url(installed.guild.id, "/tasks/"), json=task, headers=headers
    )
    assert made.status_code == 201, made.text

    by_a_person = await client.post(seat.g("/tasks/"), json=task, headers=seat.headers)
    _refused(by_a_person, "description")


# -- Events -------------------------------------------------------------------


async def _calendar(session: AsyncSession, a: Any) -> Any:
    a.initiative.calendars_enabled = True
    session.add(a.initiative)
    await session.commit()
    return await create_calendar(session, a.initiative, a.user)


async def test_an_event_is_added_with_what_its_page_requires(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    calendar = await _calendar(session, a)
    params = {"tool": "calendar", "initiative_id": a.initiative.id}
    await _require(
        client,
        a,
        params,
        "calendar_event",
        _required("location"),
        _required("attendees"),
    )
    event = {
        "calendar_id": calendar.id,
        "title": "Standup",
        "start_at": "2099-10-20T12:00:00Z",
        "end_at": "2099-10-20T13:00:00Z",
    }

    refused = await client.post(a.g("/calendar-events/"), json=event, headers=a.headers)
    _refused(refused, "location", "attendees")

    added = await client.post(
        a.g("/calendar-events/"),
        json={**event, "location": "Room 4", "attendee_ids": [a.user.id]},
        headers=a.headers,
    )
    assert added.status_code == 201, added.text

    emptied = await client.put(
        a.g(f"/calendar-events/{added.json()['id']}/attendees"),
        json=[],
        headers=a.headers,
    )
    _refused(emptied, "attendees")


async def test_an_imported_event_is_not_held_to_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    calendar = await _calendar(session, a)
    await _require(
        client,
        a,
        {"tool": "calendar", "initiative_id": a.initiative.id},
        "calendar_event",
        _required("location"),
    )
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:one@example.com",
            "SUMMARY:Imported",
            "DTSTART:20991020T120000Z",
            "DTEND:20991020T130000Z",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )

    imported = await client.post(
        a.g("/calendar-events/import"),
        json={"calendar_id": calendar.id, "ics_content": ics},
        headers=a.headers,
    )

    assert imported.status_code == 200, imported.text
    assert imported.json()["events_created"] == 1, imported.text
    # A copy of it is the event's own machinery, and keeps what it lacks.
    made = await create_calendar_event(session, calendar, a.user)
    copied = await client.post(
        a.g(f"/calendar-events/{made.id}/duplicate"), headers=a.headers
    )
    assert copied.status_code == 201, copied.text


# -- Posts --------------------------------------------------------------------


async def test_a_post_is_added_with_the_tags_its_page_requires(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()
    tag = await create_tag(session, a.guild)
    await _require(
        client,
        a,
        {"tool": "post", "initiative_id": a.initiative.id},
        "post",
        _required("tags"),
    )
    post = {"name": "Hello", "initiative_id": a.initiative.id}

    refused = await client.post(a.g("/posts/"), json=post, headers=a.headers)
    _refused(refused, "tags")

    added = await client.post(
        a.g("/posts/"), json={**post, "tag_ids": [tag.id]}, headers=a.headers
    )
    assert added.status_code == 201, added.text

    untagged = await client.put(
        a.g(f"/tools/post/{added.json()['id']}/tags"),
        json={"tag_ids": []},
        headers=a.headers,
    )
    _refused(untagged, "tags")
    # One made before it was required is tagged and untagged as before.
    older = await create_post(session, a.initiative, a.user)
    untouched = await client.put(
        a.g(f"/tools/post/{older.id}/tags"), json={"tag_ids": []}, headers=a.headers
    )
    assert untouched.status_code == 200, untouched.text


# -- Collection files ---------------------------------------------------------


async def test_a_file_joins_a_collection_with_its_required_metadata(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    first = await create_file(session, a.initiative, a.user)
    second = await create_file(session, a.initiative, a.user)
    collection = await create_collection(session, a.initiative, a.user, files=[first])
    credit = await create_property_definition(
        session, a.initiative, name="Credit", collection=collection
    )
    await _require(
        client,
        a,
        {"tool": "collection", "tool_id": collection.id},
        "file",
        _required(f"property:{credit.id}"),
    )
    url = a.g(f"/collections/{collection.id}/files")

    refused = await client.post(url, json={"file_ids": [second.id]}, headers=a.headers)
    _refused(refused, "Credit")

    added = await client.post(
        url,
        json={
            "file_ids": [second.id],
            "metadata": [{"property_id": credit.id, "value": "Ada"}],
        },
        headers=a.headers,
    )
    assert added.status_code == 200, added.text

    cleared = await client.put(
        f"{url}/{second.id}/metadata", json={"values": []}, headers=a.headers
    )
    _refused(cleared, "Credit")
    # The file already in it lacks it, and may still be changed.
    kept = await client.put(
        f"{url}/{first.id}/metadata", json={"values": []}, headers=a.headers
    )
    assert kept.status_code == 200, kept.text
