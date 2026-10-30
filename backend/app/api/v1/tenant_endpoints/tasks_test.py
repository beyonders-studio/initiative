"""
Integration tests for task endpoints.

Tests the task API endpoints at /api/v1/tasks including:
- Listing tasks
- Creating tasks
- Updating tasks
- Deleting tasks
- Moving tasks
- Duplicating tasks
- Managing a task's checklist
- Task reordering
"""

import json
from typing import Any
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlmodel import select

from app.services.tenant.task_types import get_default_type
from app.services.tenant.task_series import advance_recurrence_if_needed
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import Task, TaskStatusCategory
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing.schema_harness import route_session_to_guild
from app.models.tenant.batched_notice import BatchedNotice
from app.core.messages import CommonMessages, TaskMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.testing.factories import (
    assign_tag,
    checklist_items,
    create_counter,
    create_counter_group,
    create_file,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_relationship,
    create_task,
    create_task_status,
    create_tag,
    create_user,
)
from app.testing import create_resource_grant, guild_of, route_as

LOS_ANGELES = ZoneInfo("America/Los_Angeles")


async def _create_task(session, project, title="Test Task", checklist=None):
    """Helper to create a task."""
    from app.models.tenant.task import Task
    from app.services.tenant import task_statuses as task_statuses_service

    # Ensure default statuses exist and get the default status
    await task_statuses_service.ensure_default_statuses(
        session, project.id, locale="en"
    )
    status = await task_statuses_service.get_default_status(session, project.id)

    task = Task(
        title=title,
        project_id=project.id,
        task_status_id=status.id,
        task_type_id=(await get_default_type(session, project.id)).id,
        checklist=checklist or [],
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def test_list_tasks_in_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test listing tasks filtered by project. A row carries its description
    as a plain-text excerpt and a flag, never the whole text."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    long = await create_task(
        session,
        a.project,
        description="## [WIP] Plan\n\n"
        + "Draft the **budget**, then share it with everyone. " * 15,
    )
    short = await create_task(
        session,
        a.project,
        description=f"Ask @[Mel]({a.user.id}) about [the budget](https://example.com).",
    )
    linked = await create_task(
        session,
        a.project,
        description="Read [the brief](https://example.com/" + "a" * 700 + ")",
    )
    bare = await create_task(session, a.project)

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()["items"]}
    assert {
        task.id: (
            rows[task.id]["description_excerpt"],
            rows[task.id]["has_description"],
        )
        for task in (long, short, linked, bare)
    } == {
        long.id: (
            "[WIP] Plan Draft the budget, then share it with everyone. Draft the"
            " budget, then share it with everyone. Draft the budget, then share it"
            " with everyone. Draft…",
            True,
        ),
        short.id: (f"Ask @[]({a.user.id}) about the budget.", True),
        linked.id: ("Read…", True),
        bare.id: (None, False),
    }
    assert not any("description" in row for row in rows.values())


async def test_list_tasks_sorts_by_status_and_by_tag(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A status sorts in its board order, and tags by the first tag's name,
    ignoring case, with untagged tasks last either way."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    done = await create_task(
        session, a.project, title="Done", status_category=TaskStatusCategory.done
    )
    backlog = await create_task(
        session, a.project, title="Backlog", status_category=TaskStatusCategory.backlog
    )
    await create_task(session, a.project, title="Untagged")
    for task, name in ((done, "beta"), (backlog, "Alpha")):
        await assign_tag(session, task, await create_tag(session, a.guild, name=name))
    await session.commit()

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )

    async def titles(field: str, direction: str) -> list[str]:
        sorting = json.dumps([{"field": field, "dir": direction}])
        response = await client.get(
            a.g(f"/tasks/?conditions={conditions}&sorting={sorting}"),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        return [row["title"] for row in response.json()["items"]]

    assert await titles("status_position", "asc") == ["Backlog", "Untagged", "Done"]
    assert await titles("tag_name", "asc") == ["Backlog", "Done", "Untagged"]
    assert await titles("tag_name", "desc") == ["Done", "Backlog", "Untagged"]


async def test_task_groups_are_the_lists_in_its_order_with_each_tasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The groups of the filtered list in the order it shows them, a closed
    vocabulary's whether or not a task is in them, and each task's groups: a
    task under each of its tags, an untagged one in none."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    both = await create_task(session, a.project, title="Both")
    untagged = await create_task(session, a.project, title="Untagged")
    beta = await create_tag(session, a.guild, name="Beta")
    alpha = await create_tag(session, a.guild, name="alpha")
    for tag in (beta, alpha):
        await assign_tag(session, both, tag)
    await session.commit()

    async def groups(**params) -> dict:
        response = await client.get(
            a.g("/tasks/groups"), params=params, headers=a.headers
        )
        assert response.status_code == 200, response.text
        return response.json()

    by_tag = await groups(group_by="tag_ids")
    assert by_tag["groups"] == [
        {"key": str(alpha.id), "label": "alpha"},
        {"key": str(beta.id), "label": "Beta"},
        {"key": "", "label": None},
    ]
    assert by_tag["rows"] == {str(both.id): [str(beta.id), str(alpha.id)]}
    assert str(untagged.id) not in by_tag["rows"]

    by_priority = await groups(group_by="priority")
    assert [g["key"] for g in by_priority["groups"]] == [
        "urgent",
        "high",
        "medium",
        "low",
    ]

    by_week = await groups(group_by="created_at", bucket="week")
    assert len(by_week["groups"]) == 1  # both made this week

    for refused in ({"group_by": "title"}, {"group_by": "created_at"}):
        response = await client.get(
            a.g("/tasks/groups"), params=refused, headers=a.headers
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "QUERY_INVALID_GROUPING"


async def test_list_tasks_hides_a_project_the_member_holds_no_grant_on(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The task list resolves a task through its project's sharing.

    Tasks carry no grants of their own, so project sharing is what decides.
    A ``project_id`` condition narrows the result; it is not how access is
    resolved.
    """
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    # Same initiative; create_project seeds only the owner's grant.
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    task = await _create_task(session, owner.project, "Not Shared")

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": owner.project.id}]
    )
    response = await client.get(
        member.g(f"/tasks/?conditions={conditions}"), headers=member.headers
    )
    assert response.status_code == 200
    assert response.json()["items"] == []

    # Unfiltered, too — the gate is not a property of the filter.
    response = await client.get(member.g("/tasks/"), headers=member.headers)
    assert response.status_code == 200
    assert task.id not in {t["id"] for t in response.json()["items"]}


async def test_list_tasks_guild_admin_sees_unjoined_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin sees every project's tasks, even ones they never joined.

    Regression: the admin is NOT an initiative member of the project's
    initiative and holds no explicit/role DAC permission on the project (the
    "Barovia Arc" scenario). They must still list its tasks — guild admins have
    full guild access. Previously ``_allowed_project_ids`` lacked a guild-admin
    branch, so the admin got "no results".
    """
    # ``owner`` (a plain guild member) builds the initiative + project, so the
    # admin is neither a member nor a permission holder.
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)

    task1 = await _create_task(session, owner.project, "Hidden Task 1")
    task2 = await _create_task(session, owner.project, "Hidden Task 2")

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": owner.project.id}]
    )
    response = await client.get(
        admin.g(f"/tasks/?conditions={conditions}"), headers=admin.headers
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert task1.id in task_ids
    assert task2.id in task_ids


async def test_a_project_filter_that_narrows_nothing_does_not_widen_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Naming a project id is not the same as being confined to that project.

    ``project_id != N`` and ``project_id NOT IN []`` each carry a value while
    leaving the request spanning every other project in the community, so they
    take the cross-initiative rule: what has been shared with the reader. The
    equality above is what asks about a guild admin's standing in one project,
    and it still answers in full.
    """
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    hidden = await _create_task(session, owner.project, "Hidden Task")

    # Negated equality: every project EXCEPT the named one.
    conditions = json.dumps(
        [
            {
                "field": "project_id",
                "op": "eq",
                "value": owner.project.id + 1000,
                "negate": True,
            }
        ]
    )
    response = await client.get(
        admin.g(f"/tasks/?conditions={conditions}"), headers=admin.headers
    )
    assert response.status_code == 200
    assert hidden.id not in {t["id"] for t in response.json()["items"]}

    # An empty NOT IN narrows nothing at all.
    conditions = json.dumps(
        [{"field": "project_id", "op": "in_", "value": [], "negate": True}]
    )
    response = await client.get(
        admin.g(f"/tasks/?conditions={conditions}"), headers=admin.headers
    )
    assert response.status_code == 200
    assert hidden.id not in {t["id"] for t in response.json()["items"]}


async def test_an_archived_project_still_lists_its_tasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Archiving a project stamps its tasks with the project's own
    ``archived_at``; opened on its own, the project still shows them.

    A task archived earlier, on its own, carries a different stamp and stays
    behind the "show archived" toggle, as it does in a live project.
    """
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    earlier = await create_task(session, a.project, title="Archived earlier")
    await client.post(a.g(f"/archive/task/{earlier.id}"), headers=a.headers)
    task = await create_task(session, a.project, title="Archived with project")
    archived = await client.post(
        a.g(f"/archive/project/{a.project.id}"), headers=a.headers
    )
    assert archived.status_code == 200

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )
    assert response.status_code == 200
    assert {t["id"] for t in response.json()["items"]} == {task.id}

    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}&include_archived=true"),
        headers=a.headers,
    )
    assert response.status_code == 200
    assert {t["id"] for t in response.json()["items"]} == {task.id, earlier.id}

    # Spanning every project, an archived one stays out.
    response = await client.get(a.g("/tasks/"), headers=a.headers)
    assert response.status_code == 200
    assert task.id not in {t["id"] for t in response.json()["items"]}


async def test_create_task(client: AsyncClient, session: AsyncSession, acting_user):
    """Creating a task. Its repeat is stored as picked, with the shift from the
    zone it was picked in; a repeat a task can't have is refused."""
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    # Create a task status
    await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    status = await task_statuses_service.get_default_status(session, a.project.id)
    await session.commit()

    payload = {
        "title": "New Task",
        "description": "Task description",
        "project_id": a.project.id,
        "task_status_id": status.id,
        "priority": "high",
        # Mondays at midnight in Berlin are Sundays in UTC.
        "due_date": "2026-10-04T22:00:00Z",
        "recurrence": "FREQ=WEEKLY;BYDAY=MO",
        "tz": "Europe/Berlin",
    }

    response = await client.post(a.g("/tasks/"), headers=a.headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Task"
    assert data["description"] == "Task description"
    assert data["priority"] == "high"
    assert (data["recurrence"], data["recurrence_shift"]) == (
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        1440,
    )

    hourly = await client.post(
        a.g("/tasks/"), headers=a.headers, json={**payload, "recurrence": "FREQ=HOURLY"}
    )
    assert hourly.status_code == 422


async def test_a_category_moves_a_task_to_its_column(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A caller that knows "done" but not which column that is sends the
    category, and the task lands in the project's column of it. A task already
    in that category stays in its column."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)

    async def move(category: str) -> dict:
        response = await client.patch(
            a.g(f"/tasks/{task.id}"),
            headers=a.headers,
            json={"status_category": category},
        )
        assert response.status_code == 200, response.text
        return response.json()["task_status"]

    done = await move("done")
    assert done["category"] == "done"
    assert (await move("done"))["id"] == done["id"]
    assert (await move("in_progress"))["category"] == "in_progress"


async def test_create_task_with_status(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A non-default ``task_status_id`` is honored on create."""
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    statuses = await task_statuses_service.list_statuses(session, a.project.id)
    default_status = await task_statuses_service.get_default_status(
        session, a.project.id
    )
    await session.commit()
    non_default = next(s for s in statuses if s.id != default_status.id)

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Statused Task",
            "project_id": a.project.id,
            "task_status_id": non_default.id,
        },
    )

    assert response.status_code == 201
    assert response.json()["task_status_id"] == non_default.id


async def test_create_task_with_tags(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``tag_ids`` on create attaches the tags in the same request."""
    from app.testing.factories import create_tag

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag1 = await create_tag(session, a.guild, name="urgent")
    tag2 = await create_tag(session, a.guild, name="backend")

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Tagged Task",
            "project_id": a.project.id,
            "tag_ids": [tag1.id, tag2.id],
        },
    )

    assert response.status_code == 201
    returned_tag_ids = {t["id"] for t in response.json()["tags"]}
    assert returned_tag_ids == {tag1.id, tag2.id}


async def test_a_create_naming_something_it_cannot_reach_persists_no_task(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The whole create is refused, and no half-written task survives it."""
    from sqlmodel import func, select

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Should Not Exist",
            "project_id": a.project.id,
            "tag_ids": [999999],
        },
    )

    assert response.status_code in (400, 404)
    count = (
        await session.exec(
            select(func.count())
            .select_from(Task)
            .where(Task.title == "Should Not Exist")
        )
    ).one()
    assert count == 0


async def test_update_task_with_tags_and_properties(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """PATCH replaces tags; omitting the key leaves them, and the task's
    property values, unchanged."""
    from app.testing.factories import create_property_definition, create_tag

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)
    tag = await create_tag(session, a.guild, name="review")
    defn = await create_property_definition(session, a.initiative, name="Estimate")

    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"tag_ids": [tag.id]}
    )
    assert response.status_code == 200
    assert {t["id"] for t in response.json()["tags"]} == {tag.id}
    response = await client.put(
        a.g(f"/properties/task/{task.id}"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": "later"}]},
    )
    assert response.status_code == 200, response.text

    # A PATCH that omits the keys must leave tags/properties intact.
    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"title": "Renamed"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert {t["id"] for t in body["tags"]} == {tag.id}
    assert {p["property_id"]: p["value"] for p in body["properties"]} == {
        defn.id: "later"
    }

    # A required field is omitted to keep it, never nulled.
    for field in ("title", "priority"):
        response = await client.patch(
            a.g(f"/tasks/{task.id}"), headers=a.headers, json={field: None}
        )
        assert response.status_code == 422, field
        assert "FIELD_CANNOT_BE_NULL" in response.text, field

    # An explicit empty list clears the tags.
    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"tag_ids": []}
    )
    assert response.status_code == 200
    assert response.json()["tags"] == []


async def test_create_task_requires_project_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that creating tasks requires project access."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    # ``outsider`` is a guild member but NOT an initiative member.
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    from app.services.tenant import task_statuses as task_statuses_service

    await task_statuses_service.ensure_default_statuses(
        session, owner.project.id, locale="en"
    )
    status = await task_statuses_service.get_default_status(session, owner.project.id)
    await session.commit()

    payload = {
        "title": "Forbidden Task",
        "project_id": owner.project.id,
        "task_status_id": status.id,
    }

    response = await client.post(
        outsider.g("/tasks/"), headers=outsider.headers, json=payload
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


async def test_get_task_by_id(client: AsyncClient, session: AsyncSession, acting_user):
    """Test getting a task by ID."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)

    response = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task.id
    assert data["title"] == task.title


async def test_get_task_not_found(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test getting non-existent task."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.get(a.g("/tasks/99999"), headers=a.headers)

    assert response.status_code == 404


async def test_update_task(client: AsyncClient, session: AsyncSession, acting_user):
    """Test updating a task."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)

    payload = {"title": "Updated Title", "description": "Updated description"}

    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert data["description"] == "Updated description"


async def test_a_description_written_over_an_old_one_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A description names the one it was written over, and is refused once
    that is no longer the stored one."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project, description="First")

    def write(base: str | None):
        return client.patch(
            a.g(f"/tasks/{task.id}"),
            headers=a.headers,
            json={"description": "Mine", "description_base": base},
        )

    stale = await write("Older")
    assert stale.status_code == 409
    assert stale.json()["detail"] == CommonMessages.DESCRIPTION_CHANGED

    saved = await write("First")
    assert saved.status_code == 200
    assert saved.json()["description"] == "Mine"


@pytest.mark.parametrize(
    ("method", "payload"),
    [("PATCH", {"title": "Hacked Title"}), ("DELETE", None)],
    ids=["an update", "a delete"],
)
async def test_a_task_of_an_initiative_the_member_is_not_in_is_not_found(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    method: str,
    payload: dict | None,
):
    """A guild member outside the initiative gets 404 for either write verb:
    RLS answers for a row it does not show the same way it answers for one
    that is not there."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
    task = await _create_task(session, owner.project)

    response = await client.request(
        method,
        outsider.g(f"/tasks/{task.id}"),
        headers=outsider.headers,
        json=payload,
    )

    assert response.status_code == 404


async def test_delete_task(client: AsyncClient, session: AsyncSession, acting_user):
    """Test deleting a task."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)

    response = await client.delete(a.g(f"/tasks/{task.id}"), headers=a.headers)

    assert response.status_code == 204


async def test_assign_user_to_task(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Anyone who can open the project can be assigned; someone it is not
    shared with cannot."""
    user = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    assignee = await acting_user(
        guild_role=CommunityRole.member,
        guild=user.guild,
        initiative=user.initiative,
        initiative_role="member",
    )
    task = await _create_task(session, user.project)
    payload = {"assignee_ids": [assignee.user.id]}

    refused = await client.patch(
        user.g(f"/tasks/{task.id}"), headers=user.headers, json=payload
    )
    assert refused.status_code == 422
    assert refused.json()["detail"] == "PERSON_CANNOT_READ"

    await create_resource_grant(session, user.project, user=assignee.user)
    response = await client.patch(
        user.g(f"/tasks/{task.id}"), headers=user.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assignee_ids = {a["id"] for a in data["assignees"]}
    assert assignee.user.id in assignee_ids


async def test_adding_and_removing_assignees_leaves_the_others(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Putting someone on a task, or taking them off, works against whoever
    is on it when the change lands, not a list the caller read earlier."""
    user = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=user.guild,
        initiative=user.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, user.project, user=other.user)
    task = await _create_task(session, user.project)
    url = user.g(f"/tasks/{task.id}")

    async def assignees(payload: dict) -> set[int]:
        response = await client.patch(url, headers=user.headers, json=payload)
        assert response.status_code == 200, response.text
        return {a["id"] for a in response.json()["assignees"]}

    assert await assignees({"add_assignee_ids": [other.user.id]}) == {other.user.id}
    # Added beside the one already on it, rather than in their place.
    assert await assignees({"add_assignee_ids": [user.user.id]}) == {
        user.user.id,
        other.user.id,
    }
    # Adding someone already on it changes nothing.
    assert await assignees({"add_assignee_ids": [user.user.id]}) == {
        user.user.id,
        other.user.id,
    }
    assert await assignees({"remove_assignee_ids": [user.user.id]}) == {other.user.id}


async def test_assignee_ids_is_not_combined_with_adding_or_removing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    user = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, user.project)

    response = await client.patch(
        user.g(f"/tasks/{task.id}"),
        headers=user.headers,
        json={"assignee_ids": [], "add_assignee_ids": [user.user.id]},
    )

    assert response.status_code == 422


async def test_unassigning_withdraws_the_pending_digest_item(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An assignment that is undone before the digest goes out should not be
    announced — the queue row is withdrawn along with the assignment."""
    user = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    assignee = await acting_user(
        guild_role=CommunityRole.member,
        guild=user.guild,
        initiative=user.initiative,
        initiative_role="member",
    )
    # The assignment notice names the task, so the assignee has to reach it.
    await create_resource_grant(
        session,
        user.project,
        all_initiative_members=True,
        level=ResourceAccessLevel.write,
    )
    task = await _create_task(session, user.project)

    assign = await client.patch(
        user.g(f"/tasks/{task.id}"),
        headers=user.headers,
        json={"assignee_ids": [assignee.user.id]},
    )
    assert assign.status_code == 200

    await route_as(session, user_id=user.user.id, guild_id=user.guild.id)
    pending = (
        await session.exec(
            select(BatchedNotice).where(
                BatchedNotice.user_id == assignee.user.id,
                BatchedNotice.processed_at.is_(None),
            )
        )
    ).all()
    assert len(pending) == 1

    unassign = await client.patch(
        user.g(f"/tasks/{task.id}"), headers=user.headers, json={"assignee_ids": []}
    )
    assert unassign.status_code == 200

    session.expunge_all()
    await route_as(session, user_id=user.user.id, guild_id=user.guild.id)
    pending = (
        await session.exec(
            select(BatchedNotice).where(
                BatchedNotice.user_id == assignee.user.id,
                BatchedNotice.processed_at.is_(None),
            )
        )
    ).all()
    assert pending == []


async def test_move_task_to_different_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Moving a task keeps the assignees who can open the destination and
    drops the rest."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    project1 = a.project
    project2 = await create_project(session, a.initiative, a.user, name="Project 2")
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, project1, user=member.user)

    task = await create_task(session, project1, assignees=[a.user, member.user])

    from app.services.tenant import task_statuses as task_statuses_service

    await task_statuses_service.ensure_default_statuses(
        session, project2.id, locale="en"
    )
    target_status = await task_statuses_service.get_default_status(session, project2.id)
    await session.commit()

    payload = {
        "target_project_id": project2.id,
        "target_status_id": target_status.id,
    }

    response = await client.post(
        a.g(f"/tasks/{task.id}/move"), headers=a.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["project_id"] == project2.id
    assert [assignee["id"] for assignee in data["assignees"]] == [a.user.id]


async def test_a_task_moves_only_inside_an_initiative_that_keeps_its_content_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    a.initiative.keep_content_in = True
    session.add(a.initiative)
    nearby = await create_project(session, a.initiative, a.user)
    elsewhere = await create_project(
        session, await create_initiative(session, a.guild, a.user), a.user
    )
    task = await create_task(session, a.project)
    await session.commit()

    refused = await client.post(
        a.g(f"/tasks/{task.id}/move"),
        headers=a.headers,
        json={"target_project_id": elsewhere.id},
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "INITIATIVE_CONTENT_KEPT_IN"

    moved = await client.post(
        a.g(f"/tasks/{task.id}/move"),
        headers=a.headers,
        json={"target_project_id": nearby.id},
    )
    assert moved.status_code == 200, moved.text


async def test_duplicate_task(client: AsyncClient, session: AsyncSession, acting_user):
    """A copy goes beside the original, at the end of its project, and is
    linked to what the original is linked to. It names only assignees who can
    open the project, and leaves every other task's assignees as they are."""
    from app.models.tenant.task import TaskAssignee

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    task = await create_task(
        session, a.project, title="Original Task", assignees=[a.user, outsider.user]
    )
    other = await create_task(session, a.project, assignees=[outsider.user])
    blocker = await _create_task(session, a.project, "Blocker")
    await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.task, task.id),
        target=(SearchEntityType.task, blocker.id),
        relationship_type=RelationshipType.depends_on,
    )

    response = await client.post(
        a.g(f"/tasks/{task.id}/duplicate"), headers=a.headers, json={}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Original Task (Copy)"
    assert data["project_id"] == task.project_id
    assert data["position"] > blocker.position
    assert data["blocked_by_open_count"] == 1
    assert [assignee["id"] for assignee in data["assignees"]] == [a.user.id]
    still = await session.exec(
        select(TaskAssignee.user_id).where(TaskAssignee.task_id == other.id)
    )
    assert still.all() == [outsider.user.id]


async def test_create_task_with_checklist(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A task can be created with its checklist already on it."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Ship the redesign",
            "project_id": a.project.id,
            "checklist": [
                {"id": "aaa111", "text": "Draft the copy", "done": True},
                {"text": "Get it reviewed"},
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert [item["text"] for item in data["checklist"]] == [
        "Draft the copy",
        "Get it reviewed",
    ]
    # An item that arrived without an id is given one, so it is addressable.
    assert data["checklist"][0]["id"] == "aaa111"
    assert data["checklist"][1]["id"]
    assert data["checklist_progress"] == {"completed": 1, "total": 2}


async def test_checklist_replaced_by_task_patch(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Adding, renaming, reordering and deleting all arrive as the whole list."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)

    first = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "checklist": [
                {"id": "one", "text": "First"},
                {"id": "two", "text": "Second"},
            ]
        },
    )
    assert first.status_code == 200

    # Reordered, one renamed, one dropped, one added.
    second = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "checklist": [
                {"id": "two", "text": "Second, renamed"},
                {"id": "three", "text": "Third"},
            ]
        },
    )
    assert second.status_code == 200
    assert [(i["id"], i["text"]) for i in second.json()["checklist"]] == [
        ("two", "Second, renamed"),
        ("three", "Third"),
    ]


async def test_checklist_edit_does_not_carry_completion(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A whole-list write says what the lines are, not what is done.

    Someone renaming a line holds whatever the list said when they opened it.
    A tick that lands in between is not theirs to undo.
    """
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)
    await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "checklist": [
                {"id": "one", "text": "First"},
                {"id": "two", "text": "Second"},
            ]
        },
    )

    await client.patch(
        a.g(f"/tasks/{task.id}/checklist/two"), headers=a.headers, json={"done": True}
    )

    # A rename sent from a view taken before that tick, still saying done=False.
    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "checklist": [
                {"id": "one", "text": "First, renamed", "done": False},
                {"id": "two", "text": "Second", "done": False},
            ]
        },
    )

    assert response.status_code == 200
    assert [(i["id"], i["text"], i["done"]) for i in response.json()["checklist"]] == [
        ("one", "First, renamed", False),
        ("two", "Second", True),
    ]


async def test_checklist_new_item_keeps_the_state_it_arrived_with(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An item the task does not hold yet is taken at its word — which is what
    an import and a restore need."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)

    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"checklist": [{"id": "fresh", "text": "Already done", "done": True}]},
    )

    assert response.status_code == 200
    assert response.json()["checklist"][0]["done"] is True


async def test_an_over_long_checklist_can_still_be_shortened(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A list carried in by a migration or an import can be longer than the cap.
    It has to stay editable, so the cap stops a list growing, not shrinking."""
    from app.schemas.tenant.task import MAX_CHECKLIST_ITEMS

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    oversized = checklist_items(
        *[f"Step {index}" for index in range(MAX_CHECKLIST_ITEMS + 20)]
    )
    # Straight onto the row: a list this long is what a migration or an import
    # leaves behind, and neither goes through the API.
    task = await _create_task(session, a.project, checklist=oversized)

    # Dropping one still submits an over-cap list, and must be allowed.
    shorter = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"checklist": oversized[1:]}
    )
    assert shorter.status_code == 200
    assert len(shorter.json()["checklist"]) == MAX_CHECKLIST_ITEMS + 19

    # Growing it again is not.
    longer = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"checklist": [*oversized, {"id": "extra", "text": "One more"}]},
    )
    assert longer.status_code == 400
    assert longer.json()["detail"] == "CHECKLIST_TOO_LONG"


async def test_checklist_capped_on_a_task_that_has_none(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    from app.schemas.tenant.task import MAX_CHECKLIST_ITEMS

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "Too much",
            "project_id": a.project.id,
            "checklist": [
                {"text": f"Step {index}"} for index in range(MAX_CHECKLIST_ITEMS + 1)
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "CHECKLIST_TOO_LONG"


async def test_checklist_patch_omitted_leaves_it_alone(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """PATCH semantics: an absent checklist means "leave unchanged"."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)

    await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"checklist": [{"id": "one", "text": "First"}]},
    )
    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"title": "Renamed"}
    )

    assert response.status_code == 200
    assert [i["id"] for i in response.json()["checklist"]] == ["one"]


async def test_toggle_checklist_item(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A tick names one item and leaves the rest of the list as it was."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)
    await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "checklist": [
                {"id": "one", "text": "First"},
                {"id": "two", "text": "Second"},
                {"id": "three", "text": "Third"},
            ]
        },
    )

    response = await client.patch(
        a.g(f"/tasks/{task.id}/checklist/two"), headers=a.headers, json={"done": True}
    )

    assert response.status_code == 200
    assert [(i["id"], i["done"]) for i in response.json()] == [
        ("one", False),
        ("two", True),
        ("three", False),
    ]

    untick = await client.patch(
        a.g(f"/tasks/{task.id}/checklist/two"), headers=a.headers, json={"done": False}
    )
    assert untick.status_code == 200
    assert untick.json()[1]["done"] is False


async def test_toggling_two_items_keeps_both(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Ticks of different items accumulate rather than replacing each other."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)
    await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "checklist": [
                {"id": "one", "text": "First"},
                {"id": "two", "text": "Second"},
            ]
        },
    )

    await client.patch(
        a.g(f"/tasks/{task.id}/checklist/one"), headers=a.headers, json={"done": True}
    )
    response = await client.patch(
        a.g(f"/tasks/{task.id}/checklist/two"), headers=a.headers, json={"done": True}
    )

    assert response.status_code == 200
    assert all(item["done"] for item in response.json())


async def test_toggle_unknown_checklist_item(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An id the task does not hold is a 404."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)

    response = await client.patch(
        a.g(f"/tasks/{task.id}/checklist/nosuchitem"),
        headers=a.headers,
        json={"done": True},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "CHECKLIST_ITEM_NOT_FOUND"


async def test_checklist_progress_on_task_list(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The list payload carries the count the cards and table rows draw."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)
    await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={
            "checklist": [
                {"id": "one", "text": "First", "done": True},
                {"id": "two", "text": "Second"},
            ]
        },
    )

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 200
    listed = next(item for item in response.json()["items"] if item["id"] == task.id)
    assert listed["checklist_progress"] == {"completed": 1, "total": 2}


async def test_duplicate_task_copies_checklist_unticked(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The copy carries the same lines with nothing done."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await _create_task(session, a.project)
    await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"checklist": [{"id": "one", "text": "First", "done": True}]},
    )

    response = await client.post(
        a.g(f"/tasks/{task.id}/duplicate"), headers=a.headers, json={}
    )

    assert response.status_code == 201
    copied = response.json()["checklist"]
    assert [item["text"] for item in copied] == ["First"]
    assert copied[0]["done"] is False
    # Fresh ids: the copy's lines are its own.
    assert copied[0]["id"] != "one"


async def test_reorder_tasks(client: AsyncClient, session: AsyncSession, acting_user):
    """Test reordering tasks within a project."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task1 = await _create_task(session, a.project, "Task 1")
    task2 = await _create_task(session, a.project, "Task 2")
    task3 = await _create_task(session, a.project, "Task 3")

    payload = {
        "project_id": a.project.id,
        "items": [
            {"id": task3.id, "task_status_id": task3.task_status_id, "position": 0},
            {"id": task1.id, "task_status_id": task1.task_status_id, "position": 1},
            {"id": task2.id, "task_status_id": task2.task_status_id, "position": 2},
        ],
    }

    response = await client.post(a.g("/tasks/reorder"), headers=a.headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    ordered_ids = [t["id"] for t in data]
    assert ordered_ids == [task3.id, task1.id, task2.id]


def test_reorder_item_takes_only_a_finite_position():
    """A position is a finite number, positive or negative; the schema holds
    the boundary to that."""
    import math

    from pydantic import ValidationError

    from app.schemas.tenant.task import TaskReorderItem

    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValidationError):
            TaskReorderItem(id=1, task_status_id=1, position=bad)

    # A normal (and a negative) finite position is accepted.
    assert TaskReorderItem(id=1, task_status_id=1, position=1.5).position == 1.5
    assert TaskReorderItem(id=1, task_status_id=1, position=-0.5).position == -0.5


async def test_reorder_single_task_returns_only_affected(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A reorder sends only the moved task and the response is slimmed to it."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task1 = await _create_task(session, a.project, "Task 1")
    task2 = await _create_task(session, a.project, "Task 2")
    task3 = await _create_task(session, a.project, "Task 3")

    # Anchor task1/task2 at 1 and 2 so task3 can drop between them.
    task1.position = 1.0
    task2.position = 2.0
    task3.position = 3.0
    session.add_all([task1, task2, task3])
    await session.commit()

    payload = {
        "project_id": a.project.id,
        "items": [
            {"id": task3.id, "task_status_id": task3.task_status_id, "position": 1.5},
        ],
    }

    response = await client.post(a.g("/tasks/reorder"), headers=a.headers, json=payload)

    assert response.status_code == 200
    data = response.json()
    # Only the moved task is returned, and its fractional position round-trips.
    assert [t["id"] for t in data] == [task3.id]
    assert data[0]["position"] == 1.5


async def test_reorder_rebalances_on_precision_exhaustion(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Colliding positions trigger a project-wide renumber that leaves the
    updated_at of merely-renumbered (not explicitly moved) tasks untouched."""
    from datetime import datetime

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task1 = await _create_task(session, a.project, "Task 1")
    task2 = await _create_task(session, a.project, "Task 2")
    task3 = await _create_task(session, a.project, "Task 3")

    # task1/task2 sit one representable step apart, so a midpoint between them
    # rounds onto a neighbor — precision is exhausted at the drop point.
    task1.position = 1.0
    task2.position = 1.0000000001
    task3.position = 5.0
    session.add_all([task1, task2, task3])
    await session.commit()
    task2_updated_before = task2.updated_at

    payload = {
        "project_id": a.project.id,
        # Drop task3 into the exhausted gap (its position collides with task2),
        # which is what triggers the project-wide renumber.
        "items": [
            {
                "id": task3.id,
                "task_status_id": task3.task_status_id,
                "position": 1.0000000001,
            },
        ],
    }

    response = await client.post(a.g("/tasks/reorder"), headers=a.headers, json=payload)

    assert response.status_code == 200
    data = {t["id"]: t for t in response.json()}
    # Rebalanced to evenly spaced integers across the project.
    assert data[task2.id]["position"] == 2.0
    assert data[task3.id]["position"] == 3.0

    # task2 was only renumbered, not explicitly moved -> updated_at must not churn.
    # (Normalize the trailing 'Z' — datetime.fromisoformat rejects it on <3.11.)
    def _parse(ts: str) -> datetime:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))

    assert _parse(data[task2.id]["updated_at"]) == task2_updated_before
    # task3 was explicitly moved -> updated_at advances.
    assert _parse(data[task3.id]["updated_at"]) > task2_updated_before


async def test_task_guild_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that tasks are isolated by guild."""
    # First guild (with a workspace) — the actor is admin of it.
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    task1 = await _create_task(session, a.project)

    # A SECOND guild for the SAME user (acting_user always makes a new user, so
    # build the second guild membership with the raw factories reusing a.user).
    guild2 = await create_guild(session, name="Guild 2")
    await create_guild_membership(
        session, user=a.user, guild=guild2, role=CommunityRole.admin
    )

    # Cannot access guild1 task with guild2 context
    response2 = await client.get(
        f"/api/v1/c/{guild2.id}/tasks/{task1.id}", headers=a.headers
    )

    assert response2.status_code == 404


async def test_list_my_tasks(client: AsyncClient, session: AsyncSession, acting_user):
    """Test listing tasks assigned to current user."""
    from app.models.tenant.task import TaskAssignee

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    other_user = await create_user(session, email="other@example.com")
    await create_guild_membership(session, user=other_user, guild=a.guild)

    # Create tasks
    my_task = await _create_task(session, a.project, "My Task")
    other_task = await _create_task(session, a.project, "Other Task")

    # Assign tasks
    session.add(TaskAssignee(task_id=my_task.id, user_id=a.user.id))
    session.add(TaskAssignee(task_id=other_task.id, user_id=other_user.id))
    await session.commit()

    conditions = json.dumps([{"field": "assignee_ids", "op": "in_", "value": ["me"]}])
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 200
    data = response.json()["items"]
    task_ids = {t["id"] for t in data}
    assert my_task.id in task_ids
    assert other_task.id not in task_ids


async def test_filter_tasks_by_status(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test filtering tasks by status."""
    from app.services.tenant import task_statuses as task_statuses_service

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    # Create statuses
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    todo_status = next(s for s in statuses if s.is_default)
    done_status = next(s for s in statuses if s.name == "Done")
    await session.commit()

    # Create tasks with different statuses
    from app.models.tenant.task import Task

    task1 = Task(
        title="Todo Task",
        project_id=a.project.id,
        task_status_id=todo_status.id,
        task_type_id=(await get_default_type(session, a.project.id)).id,
    )
    task2 = Task(
        title="Done Task",
        project_id=a.project.id,
        task_status_id=done_status.id,
        task_type_id=(await get_default_type(session, a.project.id)).id,
    )
    session.add(task1)
    session.add(task2)
    await session.commit()

    conditions = json.dumps(
        [
            {"field": "project_id", "op": "eq", "value": a.project.id},
            {"field": "task_status_id", "op": "in_", "value": [todo_status.id]},
        ]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"),
        headers=a.headers,
    )

    assert response.status_code == 200
    data = response.json()["items"]
    task_titles = {t["title"] for t in data}
    assert "Todo Task" in task_titles
    assert "Done Task" not in task_titles


@pytest.fixture
async def recurring_task_env(session: AsyncSession, acting_user):
    """An actor with a project, its default statuses seeded, and the two
    statuses a completion moves between.

    Returns a callable so a test can ask for the actor in a particular
    timezone.
    """
    from app.services.tenant import task_statuses as task_statuses_service

    async def _env(**actor_kwargs):
        a = await acting_user(
            guild_role=CommunityRole.member,
            initiative=True,
            project=True,
            **actor_kwargs,
        )
        statuses = await task_statuses_service.ensure_default_statuses(
            session, a.project.id, locale="en"
        )
        todo = next(status for status in statuses if status.is_default)
        done = next(status for status in statuses if status.name == "Done")
        await session.commit()
        return a, todo, done

    return _env


@pytest.mark.parametrize(
    ("strategy", "due", "recurrence", "next_time", "next_date"),
    [
        (
            "rolling",
            datetime(2026, 1, 20, 17, 0, 0, tzinfo=timezone.utc),
            "RRULE:FREQ=DAILY;INTERVAL=3",
            time(17, 0),
            None,
        ),
        (
            "fixed",
            datetime(2026, 1, 20, 9, 30, 0, tzinfo=timezone.utc),
            "RRULE:FREQ=DAILY;INTERVAL=2",
            time(9, 30),
            date(2026, 1, 22),
        ),
        (
            "rolling",
            datetime(2026, 1, 20, 0, 0, 0, tzinfo=timezone.utc),
            "RRULE:FREQ=WEEKLY;BYDAY=MO",
            time(0, 0),
            None,
        ),
    ],
    ids=[
        "rolling keeps the due time",
        "fixed counts from the original due date",
        "rolling keeps midnight",
    ],
)
async def test_completing_a_recurring_task_opens_the_next_occurrence(
    client: AsyncClient,
    session: AsyncSession,
    recurring_task_env,
    strategy: str,
    due: datetime,
    recurrence: str,
    next_time: time,
    next_date: date | None,
):
    """Marking one done through the API leaves the completed task and a
    successor due at the same time of day. A fixed strategy counts its
    interval from the original due date; a rolling one counts from the day it
    was completed, which is why only the fixed row can name a date.
    """
    a, todo, done = await recurring_task_env()

    task = Task(
        title="Recurring Task",
        project_id=a.project.id,
        task_status_id=todo.id,
        task_type_id=(await get_default_type(session, a.project.id)).id,
        due_date=due,
        recurrence=recurrence,
        recurrence_strategy=strategy,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"task_status_id": done.id},
    )
    assert response.status_code == 200

    conditions = json.dumps(
        [{"field": "project_id", "op": "eq", "value": a.project.id}]
    )
    listing = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )
    assert listing.status_code == 200
    tasks = listing.json()["items"]
    # The original, now completed, and the occurrence that replaces it.
    assert len(tasks) == 2

    successor = next(t for t in tasks if t["id"] != task.id)
    assert successor["title"] == "Recurring Task"
    next_due = datetime.fromisoformat(successor["due_date"].replace("Z", "+00:00"))
    assert next_due.time() == next_time
    if next_date is not None:
        assert next_due.date() == next_date


@pytest.mark.parametrize(
    ("due", "recurrence", "completed_at", "next_local"),
    [
        (
            # 5pm Los Angeles on Sunday 2026-05-03, which is already the 4th
            # in UTC, completed at 9pm the same Sunday.
            datetime(2026, 5, 4, 0, 0, 0, tzinfo=timezone.utc),
            "RRULE:FREQ=DAILY;INTERVAL=3",
            datetime(2026, 5, 4, 4, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 5, 6, 17, 0, 0, tzinfo=LOS_ANGELES),
        ),
        (
            # 2:30 AM Los Angeles, completed on the US spring-forward day.
            # 2:30 AM does not exist that night, so the day's time is 3:30,
            # and the next occurrence is a day on from it.
            datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            "RRULE:FREQ=DAILY",
            datetime(2026, 3, 8, 18, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 3, 9, 3, 30, 0, tzinfo=LOS_ANGELES),
        ),
    ],
    ids=[
        "the completion day is the user's, not UTC's",
        "a wall-clock time the spring-forward night does not have",
    ],
)
async def test_rolling_recurrence_counts_from_the_users_own_calendar_day(
    session: AsyncSession,
    recurring_task_env,
    due: datetime,
    recurrence: str,
    completed_at: datetime,
    next_local: datetime,
):
    """A rolling occurrence counts from the user's local calendar day, at the
    original's local time of day; from there the rule steps in UTC terms, as
    every repeat does.
    """
    a, todo, done = await recurring_task_env(timezone="America/Los_Angeles")

    task = Task(
        title="Feed frogs",
        project_id=a.project.id,
        task_status_id=todo.id,
        task_type_id=(await get_default_type(session, a.project.id)).id,
        due_date=due,
        recurrence=recurrence,
        recurrence_strategy="rolling",
    )
    session.add(task)
    await session.commit()
    # Eager-load every relationship the helper touches, so the call below
    # doesn't trip SQLAlchemy's async-greenlet guard on a lazy load.
    await session.refresh(task, attribute_names=["task_status", "assignees"])

    task.task_status_id = done.id
    task.task_status = done

    advanced = await advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=TaskStatusCategory.todo,
        now=completed_at,
        user_timezone=a.user.timezone,
    )
    assert advanced is True
    await session.commit()

    successor = (
        await session.exec(
            select(Task).where(Task.project_id == a.project.id, Task.id != task.id)
        )
    ).first()
    assert successor is not None
    assert successor.due_date is not None
    assert successor.due_date.astimezone(LOS_ANGELES) == next_local


async def test_completing_a_tagged_recurring_task_copies_tags_to_next_occurrence(
    session: AsyncSession,
    recurring_task_env,
):
    """The next occurrence carries the tags of the one it replaces, and
    serializing them emits no IO from sync context.
    """
    from app.services.tenant import tags as tags_service
    from app.testing.factories import create_tag, create_task

    a, todo, done = await recurring_task_env()

    tag = await create_tag(session, a.guild, name="Chores", color="#112233")
    task = await create_task(
        session,
        a.project,
        title="Tagged recurring task",
        task_status_id=todo.id,
        due_date=datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc),
        recurrence="RRULE:FREQ=DAILY",
        recurrence_strategy="fixed",
    )
    await tags_service.set_entity_tags(
        session,
        tags_service.TAG_LINKS["task"],
        guild_id=a.guild.id,
        entity_id=task.id,
        tag_ids=[tag.id],
    )
    await session.commit()
    await session.refresh(task, attribute_names=["task_status", "assignees"])

    task.task_status_id = done.id
    task.task_status = done

    # Drop the tag from the identity map so reading a link's ``tag`` has to
    # go to the database — as it does on a real request, where the tag was
    # never loaded into this session. Keeping it resident lets SQLAlchemy
    # satisfy the many-to-one from memory.
    tag_id = tag.id
    session.expunge(tag)

    advanced = await advance_recurrence_if_needed(
        session,
        task,
        previous_status_category=TaskStatusCategory.todo,
        now=datetime(2026, 5, 4, 13, 0, 0, tzinfo=timezone.utc),
        user_timezone="UTC",
    )
    assert advanced is True
    await session.commit()

    successor = (
        await session.exec(
            select(Task).where(Task.project_id == a.project.id, Task.id != task.id)
        )
    ).first()
    assert successor is not None
    copied = await tags_service.active_tag_ids(
        session, tags_service.TAG_LINKS["task"], successor.id
    )
    assert copied == [tag_id]


async def test_a_task_changes_alone_or_with_its_series(
    client: AsyncClient, session: AsyncSession, recurring_task_env
):
    """An edit of just this task stays on it, the next task is made with what
    it changed from; an edit of all reaches every task of the series; a skip
    moves the task on without completing it; and a delete is this task (a
    skip) or the whole series."""
    from app.testing.factories import create_tag, create_task

    a, todo, done = await recurring_task_env()
    tag = await create_tag(session, a.guild, name="garden")
    first = await create_task(
        session,
        a.project,
        title="Water plants",
        task_status_id=todo.id,
        due_date=datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
        recurrence="RRULE:FREQ=DAILY",
    )
    await session.commit()

    async def patch(task_id: int, **body):
        response = await client.patch(
            a.g(f"/tasks/{task_id}"), headers=a.headers, json=body
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def live() -> dict[int, dict]:
        conditions = json.dumps(
            [{"field": "project_id", "op": "eq", "value": a.project.id}]
        )
        listing = await client.get(
            a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
        )
        return {task["id"]: task for task in listing.json()["items"]}

    # Completed and tagged in one save: the next task has the tag.
    await patch(first.id, task_status_id=done.id, tag_ids=[tag.id])
    (second_id,) = set(await live()) - {first.id}
    assert [t["id"] for t in (await live())[second_id]["tags"]] == [tag.id]
    second = await patch(
        second_id,
        title="Water ferns",
        due_date="2026-05-05T15:00:00Z",
        scope="this",
    )
    assert (second["series_id"], second["series_size"]) == (first.id, 2)

    await patch(second_id, task_status_id=done.id)
    (third_id,) = set(await live()) - {first.id, second_id}
    third = (await live())[third_id]
    assert third["title"] == "Water plants"
    assert third["due_date"].startswith("2026-05-06T12:00")

    third = await patch(third_id, title="Water everything", scope="all")
    assert third["series_size"] == 3
    assert {task["title"] for task in (await live()).values()} == {"Water everything"}

    skipped = await client.post(a.g(f"/tasks/{third_id}/skip"), headers=a.headers)
    assert skipped.json()["due_date"].startswith("2026-05-07T12:00")
    refused = await client.post(a.g(f"/tasks/{first.id}/skip"), headers=a.headers)
    assert refused.json()["detail"] == TaskMessages.NOT_REPEATING

    await client.delete(a.g(f"/tasks/{third_id}?scope=this"), headers=a.headers)
    assert (await live())[third_id]["due_date"].startswith("2026-05-08T12:00")
    await client.delete(a.g(f"/tasks/{third_id}?scope=all"), headers=a.headers)
    assert await live() == {}


async def test_a_task_changes_type_alone_or_with_its_series(
    client: AsyncClient, session: AsyncSession, recurring_task_env
):
    """A type changed on just this task stays on it, and the next task is the
    series' type; changed on all, every task of the series is the new type."""
    from app.services.tenant.task_types import list_types
    from app.testing.factories import create_task

    a, todo, done = await recurring_task_env()
    task_type, bug, idea = (await list_types(session, a.project.id))[:3]
    first = await create_task(
        session,
        a.project,
        title="Water plants",
        task_status_id=todo.id,
        due_date=datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
        recurrence="RRULE:FREQ=DAILY",
    )
    await session.commit()

    async def patch(task_id: int, **body):
        response = await client.patch(
            a.g(f"/tasks/{task_id}"), headers=a.headers, json=body
        )
        assert response.status_code == 200, response.text
        return response.json()

    async def types() -> dict[int, int]:
        conditions = json.dumps(
            [{"field": "project_id", "op": "eq", "value": a.project.id}]
        )
        listing = await client.get(
            a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
        )
        return {task["id"]: task["task_type_id"] for task in listing.json()["items"]}

    await patch(first.id, task_type_id=bug.id, scope="this")
    await patch(first.id, task_status_id=done.id)
    (second_id,) = set(await types()) - {first.id}
    assert await types() == {first.id: bug.id, second_id: task_type.id}

    await patch(second_id, task_type_id=idea.id, scope="all")
    assert set((await types()).values()) == {idea.id}


async def test_a_series_type_deleted_since_leaves_the_task_its_own(
    client: AsyncClient, session: AsyncSession, recurring_task_env
):
    """A type kept back by an edit of just this task that has since been
    deleted is not one to make the next task with: it keeps the task's own."""
    from app.services.tenant.task_types import list_types
    from app.testing.factories import create_task

    a, todo, done = await recurring_task_env()
    task_type, bug, idea = (await list_types(session, a.project.id))[:3]
    first = await create_task(
        session,
        a.project,
        task_status_id=todo.id,
        due_date=datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc),
        recurrence="RRULE:FREQ=DAILY",
    )
    await session.commit()
    at = a.g(f"/tasks/{first.id}")

    changed = await client.patch(
        at, headers=a.headers, json={"task_type_id": bug.id, "scope": "this"}
    )
    assert changed.status_code == 200, changed.text
    # The series' type goes, and its tasks with it into another.
    gone = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-types/{task_type.id}"),
        headers=a.headers,
        json={"fallback_type_id": idea.id},
    )
    assert gone.status_code == 204, gone.text

    completed = await client.patch(
        at, headers=a.headers, json={"task_status_id": done.id}
    )
    assert completed.status_code == 200, completed.text
    following = (
        await session.exec(
            select(Task).where(Task.project_id == a.project.id, Task.id != first.id)
        )
    ).one()
    assert following.task_type_id == bug.id


async def test_filter_tasks_by_date_window_group(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An OR group windows tasks by start_date OR due_date.

    The shape the calendar sends: a task belongs on screen if either of its
    dates lands in the visible range, so a task due in-window but started
    before it must still come back.
    """
    from datetime import datetime, timezone

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    async def _dated(title, start, due):
        task = await _create_task(session, a.project, title)
        task.start_date = start
        task.due_date = due
        session.add(task)
        await session.commit()
        return task

    def _at(day):
        return datetime(2026, 6, day, 12, 0, tzinfo=timezone.utc)

    # Window is June 2026; each task is named for why it should/shouldn't match.
    both_inside = await _dated("both inside", _at(10), _at(11))
    due_only = await _dated("due only", None, _at(12))
    start_only = await _dated("start only", _at(13), None)
    # Starts in May, due in June: the due marker is on screen.
    straddles = await _dated(
        "straddles", datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc), _at(14)
    )
    outside = await _dated(
        "outside",
        datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )
    undated = await _create_task(session, a.project, "undated")

    window_start = "2026-06-01T00:00:00+00:00"
    window_end = "2026-06-30T23:59:59+00:00"
    conditions = json.dumps(
        [
            {
                "logic": "or",
                "conditions": [
                    {
                        "logic": "and",
                        "conditions": [
                            {"field": field, "op": "gte", "value": window_start},
                            {"field": field, "op": "lte", "value": window_end},
                        ],
                    }
                    for field in ("start_date", "due_date")
                ],
            }
        ]
    )

    # params= rather than an f-string URL: the "+" in a UTC offset is a space
    # once the query string is decoded.
    response = await client.get(
        a.g("/tasks/"),
        params={"conditions": conditions, "page_size": 0},
        headers=a.headers,
    )

    assert response.status_code == 200
    returned = {t["id"] for t in response.json()["items"]}
    assert returned == {both_inside.id, due_only.id, start_only.id, straddles.id}
    assert outside.id not in returned
    assert undated.id not in returned


async def test_list_tasks_rejects_conditions_nested_too_deeply(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    conditions = json.dumps(
        [
            {
                "conditions": [
                    {"conditions": [{"conditions": [{"field": "id", "value": 1}]}]}
                ]
            }
        ]
    )

    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "QUERY_INVALID_CONDITIONS"


async def test_read_task_includes_creator_summary(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The task read embeds a ``creator`` summary so the detail view can show
    'Created by …' without fetching the whole guild roster."""
    a = await acting_user(
        guild_role=CommunityRole.member,
        initiative=True,
        project=True,
        username="ada-c",
    )
    await create_guild_membership(
        session, user=a.user, guild=a.guild, display_name="Ada C."
    )
    create = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={"title": "Authored Task", "project_id": a.project.id},
    )
    assert create.status_code == 201
    task_id = create.json()["id"]

    response = await client.get(a.g(f"/tasks/{task_id}"), headers=a.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["created_by"] == a.user.id
    assert body["creator"] is not None
    assert body["creator"]["id"] == a.user.id
    # The handle is always there, and the name she set in this guild with it.
    assert body["creator"]["username"] == "ada-c"
    assert body["creator"]["display_name"] == "Ada C."


async def _assignment_fixture(session, actor):
    from app.models.tenant.task import TaskAssignee

    assigned = await _create_task(session, actor.project, "Assigned Task")
    unassigned = await _create_task(session, actor.project, "Unassigned Task")
    session.add(TaskAssignee(task_id=assigned.id, user_id=actor.user.id))
    await session.commit()
    return assigned, unassigned


async def test_filter_tasks_with_no_assignee(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    assigned, unassigned = await _assignment_fixture(session, a)

    conditions = json.dumps([{"field": "assignee_ids", "op": "is_null", "value": True}])
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert unassigned.id in task_ids
    assert assigned.id not in task_ids


async def test_filter_tasks_with_any_assignee(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``negate`` inverts it, so "has someone on it" comes free."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    assigned, unassigned = await _assignment_fixture(session, a)

    conditions = json.dumps(
        [{"field": "assignee_ids", "op": "is_null", "value": True, "negate": True}]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert assigned.id in task_ids
    assert unassigned.id not in task_ids


async def test_unassigned_or_mine_returns_the_union(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The filter panel compiles "none" alongside real ids into one OR group."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    assigned, unassigned = await _assignment_fixture(session, a)
    other_user = await create_user(session, email="someone-else@example.com")
    await create_guild_membership(session, user=other_user, guild=a.guild)
    theirs = await _create_task(session, a.project, "Their Task")
    from app.models.tenant.task import TaskAssignee

    session.add(TaskAssignee(task_id=theirs.id, user_id=other_user.id))
    await session.commit()

    conditions = json.dumps(
        [
            {
                "logic": "or",
                "conditions": [
                    {"field": "assignee_ids", "op": "is_null", "value": True},
                    {"field": "assignee_ids", "op": "in_", "value": ["me"]},
                ],
            }
        ]
    )
    response = await client.get(
        a.g(f"/tasks/?conditions={conditions}"), headers=a.headers
    )

    assert response.status_code == 200
    task_ids = {t["id"] for t in response.json()["items"]}
    assert {assigned.id, unassigned.id} <= task_ids
    assert theirs.id not in task_ids


async def test_my_tasks_unassigned_is_vacuous_not_an_error(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``/me/tasks`` is already the set of tasks assigned to you, so asking it
    for unassigned ones is empty by construction — but it must not error."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _assignment_fixture(session, a)

    conditions = json.dumps([{"field": "assignee_ids", "op": "is_null", "value": True}])
    response = await client.get(
        f"/api/v1/me/tasks?conditions={conditions}", headers=a.headers
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


# ---------------------------------------------------------------------------
# What is still holding a task up
# ---------------------------------------------------------------------------


async def test_blocked_by_open_count_counts_only_what_is_unfinished(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A done blocker stops being one, without anybody taking the link back."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    still_going = await create_task(
        session, a.project, status_category=TaskStatusCategory.todo
    )
    finished = await create_task(
        session, a.project, status_category=TaskStatusCategory.done
    )
    for blocker in (still_going, finished):
        await create_relationship(
            session,
            a.guild,
            source=(SearchEntityType.task, task.id),
            target=(SearchEntityType.task, blocker.id),
            relationship_type=RelationshipType.depends_on,
            created_by=a.user.id,
        )

    response = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)

    assert response.status_code == 200
    assert response.json()["blocked_by_open_count"] == 1


async def test_blocked_by_open_count_spans_kinds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Anything with a reading of "finished" can hold a task up, not just a task."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    blocker = await create_task(session, a.project)
    group = await create_counter_group(session, a.initiative, a.user)
    short = await create_counter(session, group, count=1, max=5)

    for kind, entity_id in (
        (SearchEntityType.task, blocker.id),
        (SearchEntityType.counter, short.id),
    ):
        await create_relationship(
            session,
            a.guild,
            source=(SearchEntityType.task, task.id),
            target=(kind, entity_id),
            relationship_type=RelationshipType.depends_on,
            created_by=a.user.id,
        )

    response = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)

    assert response.status_code == 200
    assert response.json()["blocked_by_open_count"] == 2


async def test_a_project_blocks_until_the_work_in_it_is_done(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Waiting on a whole project is waiting on the tasks in it."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    blocking_project = await create_project(session, a.initiative, a.user)
    todo = await create_task(
        session, blocking_project, status_category=TaskStatusCategory.todo
    )
    await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.task, task.id),
        target=(SearchEntityType.project, blocking_project.id),
        relationship_type=RelationshipType.depends_on,
        created_by=a.user.id,
    )

    response = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)
    assert response.status_code == 200
    assert response.json()["blocked_by_open_count"] == 1

    # Finish the work and the project stops holding anything up.
    await route_session_to_guild(session, a.guild.id)
    done = await create_task_status(
        session, blocking_project, category=TaskStatusCategory.done
    )
    todo.task_status_id = done.id  # ty: ignore[invalid-assignment] — persisted row, id is set
    todo.completed_at = datetime.now(timezone.utc)
    session.add(todo)
    await session.commit()

    response = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)
    assert response.status_code == 200
    assert response.json()["blocked_by_open_count"] == 0


async def test_a_file_is_not_counted_as_a_blocker(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Nothing on a file says when it stops holding something up, so it is
    shown as a link and left out of the count rather than blocking forever."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    doc = await create_file(session, a.initiative, a.user)
    await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.task, task.id),
        target=(SearchEntityType.file, doc.id),
        relationship_type=RelationshipType.depends_on,
        created_by=a.user.id,
    )

    response = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)

    assert response.status_code == 200
    assert response.json()["blocked_by_open_count"] == 0


async def test_blocking_the_other_way_round_is_not_counted(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The source of a dependency is the end that waits, so a task this one
    holds up is not something holding IT up."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)
    waiting_on_us = await create_task(session, a.project)
    await create_relationship(
        session,
        a.guild,
        source=(SearchEntityType.task, waiting_on_us.id),
        target=(SearchEntityType.task, task.id),
        relationship_type=RelationshipType.depends_on,
        created_by=a.user.id,
    )

    response = await client.get(a.g(f"/tasks/{task.id}"), headers=a.headers)

    assert response.status_code == 200
    assert response.json()["blocked_by_open_count"] == 0


async def test_a_blocker_the_reader_cannot_open_is_not_counted(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The relationships policy clears both ends, so a blocker in an initiative
    the reader is not in is invisible — and an invisible blocker must not show
    up as a number they cannot account for."""
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, owner.project)
    elsewhere = await create_initiative(session, owner.guild, owner.user)
    hidden_project = await create_project(session, elsewhere, owner.user)
    hidden = await create_task(session, hidden_project)
    await create_relationship(
        session,
        owner.guild,
        source=(SearchEntityType.task, task.id),
        target=(SearchEntityType.task, hidden.id),
        relationship_type=RelationshipType.depends_on,
        created_by=owner.user.id,
    )

    # The project is shared with the whole initiative, so the reader can open
    # the task itself: what is being tested is the far end of its blocker.
    await create_resource_grant(session, owner.project, all_initiative_members=True)

    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    response = await client.get(owner.g(f"/tasks/{task.id}"), headers=reader.headers)

    assert response.status_code == 200
    assert response.json()["blocked_by_open_count"] == 0


# ---------------------------------------------------------------------------
# Column limits
# ---------------------------------------------------------------------------


async def test_a_full_column_takes_no_more_from_a_person(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A person can't put a task into a column at its board's limit, by moving
    one there or adding one; a task already in it still changes and moves
    within it. A limited column reads as its limit and its open tasks, to
    those who can open the project."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    held = await create_task(
        session, a.project, status_category=TaskStatusCategory.in_progress
    )
    waiting = await create_task(session, a.project)
    await session.commit()
    full = held.task_status_id
    limited = await client.put(
        a.g("/layouts/"),
        params={"tool": "project", "tool_id": a.project.id},
        json={
            "kind": "board",
            "definition": {"limits": [{"status_id": full, "limit": 1}]},
        },
        headers=a.headers,
    )
    assert limited.status_code == 200, limited.text

    moved = await client.patch(
        a.g(f"/tasks/{waiting.id}"), headers=a.headers, json={"task_status_id": full}
    )
    added = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={"title": "One more", "project_id": a.project.id, "task_status_id": full},
    )
    changed = await client.patch(
        a.g(f"/tasks/{held.id}"), headers=a.headers, json={"title": "Still here"}
    )
    within = await client.post(
        a.g("/tasks/reorder"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "items": [{"id": held.id, "task_status_id": full, "position": 5}],
        },
    )
    outsider = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    fills = [
        await client.get(
            a.g("/tasks/column-limits"),
            params={"project_id": a.project.id},
            headers=reader.headers,
        )
        for reader in (a, outsider)
    ]

    for refused in (moved, added):
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == TaskMessages.STATUS_AT_LIMIT
    assert changed.status_code == 200, changed.text
    assert within.status_code == 200, within.text
    assert [fill.json() for fill in fills] == [
        [{"project_id": a.project.id, "status_id": full, "limit": 1, "count": 1}],
        [],
    ]


async def _project_types(session: AsyncSession, project) -> dict:
    from app.services.tenant import task_types as task_types_service

    await route_session_to_guild(session, guild_of(project))
    types = await task_types_service.ensure_default_types(
        session, project.id, locale="en"
    )
    await session.commit()
    return {task_type.name: task_type for task_type in types}


async def test_a_new_task_is_its_projects_default_type_unless_it_names_one(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    types = await _project_types(session, a.project)

    plain = await client.post(
        a.g("/tasks/"),
        json={"title": "Water the plants", "project_id": a.project.id},
        headers=a.headers,
    )
    bug = await client.post(
        a.g("/tasks/"),
        json={
            "title": "The tap leaks",
            "project_id": a.project.id,
            "task_type_id": types["Bug"].id,
        },
        headers=a.headers,
    )

    assert plain.status_code == 201, plain.text
    assert plain.json()["task_type_id"] == types["Task"].id
    assert bug.status_code == 201, bug.text
    assert bug.json()["task_type_id"] == types["Bug"].id


async def test_a_task_cannot_be_another_projects_type(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    elsewhere = await create_project(session, a.initiative, a.user, name="Elsewhere")
    await _project_types(session, a.project)
    foreign = (await _project_types(session, elsewhere))["Bug"]

    response = await client.post(
        a.g("/tasks/"),
        json={
            "title": "Lost",
            "project_id": a.project.id,
            "task_type_id": foreign.id,
        },
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "TASK_TYPE_NOT_FOUND_FOR_PROJECT"


async def test_changing_a_tasks_type_keeps_what_it_holds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    types = await _project_types(session, a.project)
    task = await create_task(
        session,
        a.project,
        due_date=datetime(2026, 11, 2, tzinfo=timezone.utc),
        checklist=[{"id": "a", "text": "Pack", "done": False}],
    )
    await session.commit()

    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        json={"task_type_id": types["Idea"].id},
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_type_id"] == types["Idea"].id
    assert body["due_date"].startswith("2026-11-02")
    assert [item["text"] for item in body["checklist"]] == ["Pack"]


async def test_a_moved_task_keeps_a_type_of_the_same_name(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    elsewhere = await create_project(session, a.initiative, a.user, name="Elsewhere")
    here = await _project_types(session, a.project)
    there = await _project_types(session, elsewhere)
    task = await create_task(session, a.project, task_type_id=here["Bug"].id)
    await session.commit()

    response = await client.post(
        a.g(f"/tasks/{task.id}/move"),
        json={"target_project_id": elsewhere.id},
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_type_id"] == there["Bug"].id


async def test_a_moved_task_with_no_same_named_type_takes_the_default(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    elsewhere = await create_project(session, a.initiative, a.user, name="Elsewhere")
    here = await _project_types(session, a.project)
    there = await _project_types(session, elsewhere)
    here["Bug"].name = "Fehler"
    session.add(here["Bug"])
    await session.commit()
    task = await create_task(session, a.project, task_type_id=here["Bug"].id)
    await session.commit()

    response = await client.post(
        a.g(f"/tasks/{task.id}/move"),
        json={"target_project_id": elsewhere.id},
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_type_id"] == there["Task"].id


async def test_a_duplicate_is_its_sources_type(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    types = await _project_types(session, a.project)
    task = await create_task(session, a.project, task_type_id=types["Milestone"].id)
    await session.commit()

    response = await client.post(a.g(f"/tasks/{task.id}/duplicate"), headers=a.headers)

    assert response.status_code == 201, response.text
    assert response.json()["task_type_id"] == types["Milestone"].id


async def test_a_new_task_starts_with_what_its_type_starts_one_with(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Where whoever made the task left a field empty, its type fills it: a
    description outline, checklist lines, a priority, and a repeat once there
    is a date to count from. What they gave is kept."""
    from app.services.tenant.task_types import ensure_default_types

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await ensure_default_types(session, a.project.id, locale="en")
    await session.commit()
    chore = (
        await client.post(
            a.g(f"/projects/{a.project.id}/task-types/"),
            json={
                "name": "Chore",
                "starting_values": {
                    "description": "**Where**\n\n",
                    "checklist": ["Gloves"],
                    "priority": "low",
                    "recurrence": "RRULE:FREQ=WEEKLY",
                    "recurrence_strategy": "rolling",
                },
            },
            headers=a.headers,
        )
    ).json()

    async def make(**body: Any) -> dict[str, Any]:
        response = await client.post(
            a.g("/tasks/"),
            headers=a.headers,
            json={"project_id": a.project.id, "task_type_id": chore["id"], **body},
        )
        assert response.status_code == 201, response.text
        return response.json()

    blank = await make(title="Gutters", due_date="2026-11-02T09:00:00Z")
    assert blank["description"].startswith("**Where**")
    assert [item["text"] for item in blank["checklist"]] == ["Gloves"]
    assert blank["priority"] == "low"
    assert blank["recurrence"].endswith("FREQ=WEEKLY")
    assert blank["recurrence_strategy"] == "rolling"

    given = await make(
        title="Lawn",
        description="Front only",
        checklist=[{"text": "Mower"}],
        priority="urgent",
    )
    assert given["description"] == "Front only"
    assert [item["text"] for item in given["checklist"]] == ["Mower"]
    assert given["priority"] == "urgent"
    # No date to count a repeat from.
    assert given["recurrence"] is None

    # Sent empty is sent: a cleared outline, list or repeat stays cleared.
    cleared = await make(
        title="Hedge",
        description=None,
        checklist=[],
        recurrence=None,
        due_date="2026-11-02T09:00:00Z",
    )
    assert cleared["description"] in (None, "")
    assert cleared["checklist"] == []
    assert cleared["recurrence"] is None

    # A type that starts nothing leaves a task as it was given.
    plain = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={"project_id": a.project.id, "title": "Plain"},
    )
    assert plain.json()["description"] in (None, "")
    assert plain.json()["checklist"] == []
