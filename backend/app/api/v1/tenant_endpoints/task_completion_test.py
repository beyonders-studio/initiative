"""Integration tests for the ``completed_at`` invariant.

A task carries a completion timestamp exactly when its status sits in the
``done`` category. These cover every endpoint that can move a task across that
boundary — including recategorising a status, which flips done-ness for a whole
column without writing a single task row.

The rule itself is unit-tested in
``app/services/tenant/task_completion_test.py``.
"""

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.project import Project
from app.models.tenant.task import TaskStatus, TaskStatusCategory
from app.services.tenant import task_statuses as task_statuses_service
from app.testing import Actor
from app.testing.factories import create_project


async def _statuses(
    session: AsyncSession, project: Project
) -> dict[TaskStatusCategory, TaskStatus]:
    """``{category: status}`` for the project's seeded default statuses."""
    await task_statuses_service.ensure_default_statuses(
        session, project.id, locale="en"
    )
    statuses = await task_statuses_service.list_statuses(session, project.id)
    await session.commit()
    return {s.category: s for s in statuses}


async def _create_task(
    client: AsyncClient, a: Actor, *, status_id: int, title: str = "Task"
) -> dict:
    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={"project_id": a.project.id, "title": title, "task_status_id": status_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _get_task(client: AsyncClient, a: Actor, task_id: int) -> dict:
    response = await client.get(a.g(f"/tasks/{task_id}"), headers=a.headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _set_status(
    client: AsyncClient, a: Actor, task_id: int, status_id: int
) -> dict:
    response = await client.patch(
        a.g(f"/tasks/{task_id}"),
        headers=a.headers,
        json={"task_status_id": status_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- creation ---------------------------------------------------------------


async def test_task_created_in_done_status_is_complete(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)

    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.done].id)

    assert task["completed_at"] is not None


async def test_task_created_in_open_status_is_incomplete(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)

    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.todo].id)

    assert task["completed_at"] is None


# --- status changes on the task --------------------------------------------


async def test_moving_into_done_stamps_completed_at(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.todo].id)
    assert task["completed_at"] is None

    updated = await _set_status(
        client, a, task["id"], statuses[TaskStatusCategory.done].id
    )

    assert updated["completed_at"] is not None


async def test_moving_out_of_done_clears_completed_at(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Reopening a task un-completes it — the timestamp must not linger."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.done].id)
    assert task["completed_at"] is not None

    updated = await _set_status(
        client, a, task["id"], statuses[TaskStatusCategory.in_progress].id
    )

    assert updated["completed_at"] is None


async def test_moving_between_done_statuses_keeps_the_original_time(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    second_done = await client.post(
        a.g(f"/projects/{a.project.id}/task-statuses/"),
        headers=a.headers,
        json={"name": "Shipped", "category": "done"},
    )
    assert second_done.status_code == 201, second_done.text

    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.done].id)
    completed_at = task["completed_at"]

    updated = await _set_status(client, a, task["id"], second_done.json()["id"])

    assert updated["completed_at"] == completed_at


async def test_kanban_drag_into_done_stamps_completed_at(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The reorder endpoint carries a status per item — the drag-to-Done path."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.todo].id)

    response = await client.post(
        a.g("/tasks/reorder"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "items": [
                {
                    "id": task["id"],
                    "task_status_id": statuses[TaskStatusCategory.done].id,
                    "position": 0,
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert (await _get_task(client, a, task["id"]))["completed_at"] is not None


async def test_kanban_drag_out_of_done_clears_completed_at(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.done].id)

    response = await client.post(
        a.g("/tasks/reorder"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "items": [
                {
                    "id": task["id"],
                    "task_status_id": statuses[TaskStatusCategory.todo].id,
                    "position": 0,
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    assert (await _get_task(client, a, task["id"]))["completed_at"] is None


# --- recategorising a status (no task row is written) -----------------------


async def test_recategorising_a_column_out_of_done_clears_its_tasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Flipping a Done column to another category reopens everything in it."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    # A second done status, so the project still has one after the flip.
    keeper = await client.post(
        a.g(f"/projects/{a.project.id}/task-statuses/"),
        headers=a.headers,
        json={"name": "Shipped", "category": "done"},
    )
    assert keeper.status_code == 201, keeper.text

    done_status = statuses[TaskStatusCategory.done]
    task = await _create_task(client, a, status_id=done_status.id)
    assert task["completed_at"] is not None

    response = await client.patch(
        a.g(f"/projects/{a.project.id}/task-statuses/{done_status.id}"),
        headers=a.headers,
        json={"category": "in_progress"},
    )

    assert response.status_code == 200, response.text
    assert (await _get_task(client, a, task["id"]))["completed_at"] is None


async def test_recategorising_a_column_into_done_stamps_its_tasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    todo_status = statuses[TaskStatusCategory.todo]
    task = await _create_task(client, a, status_id=todo_status.id)
    assert task["completed_at"] is None

    response = await client.patch(
        a.g(f"/projects/{a.project.id}/task-statuses/{todo_status.id}"),
        headers=a.headers,
        json={"category": "done"},
    )

    assert response.status_code == 200, response.text
    assert (await _get_task(client, a, task["id"]))["completed_at"] is not None


async def test_recategorising_a_column_leaves_other_columns_alone(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The realignment is scoped to the edited status, not the whole project."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    done_status = statuses[TaskStatusCategory.done]
    shipped = await client.post(
        a.g(f"/projects/{a.project.id}/task-statuses/"),
        headers=a.headers,
        json={"name": "Shipped", "category": "done"},
    )
    assert shipped.status_code == 201, shipped.text

    untouched = await _create_task(
        client, a, status_id=shipped.json()["id"], title="Shipped task"
    )
    flipped = await _create_task(client, a, status_id=done_status.id, title="Done task")

    response = await client.patch(
        a.g(f"/projects/{a.project.id}/task-statuses/{done_status.id}"),
        headers=a.headers,
        json={"category": "todo"},
    )
    assert response.status_code == 200, response.text

    assert (await _get_task(client, a, flipped["id"]))["completed_at"] is None
    assert (await _get_task(client, a, untouched["id"]))["completed_at"] == untouched[
        "completed_at"
    ]


# --- other writers ----------------------------------------------------------


async def test_moving_a_done_task_to_another_project_clears_completed_at(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A move lands the task in the target project's default status, which is
    an open one — so the task is no longer complete."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.done].id)
    assert task["completed_at"] is not None

    target = await create_project(session, a.initiative, a.user, name="Target")
    await _statuses(session, target)

    response = await client.post(
        a.g(f"/tasks/{task['id']}/move"),
        headers=a.headers,
        json={"target_project_id": target.id},
    )

    assert response.status_code == 200, response.text
    assert response.json()["completed_at"] is None


async def test_duplicating_a_done_task_produces_a_complete_copy(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The copy keeps the source's status, so it must keep a timestamp too —
    otherwise it would be a done task that was never completed."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await _statuses(session, a.project)
    task = await _create_task(client, a, status_id=statuses[TaskStatusCategory.done].id)

    response = await client.post(
        a.g(f"/tasks/{task['id']}/duplicate"), headers=a.headers, json={}
    )

    assert response.status_code == 201, response.text
    assert response.json()["completed_at"] is not None
