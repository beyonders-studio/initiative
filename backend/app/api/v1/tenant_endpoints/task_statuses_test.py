"""
Integration tests for task status endpoints.

Covers the color/icon fields added for customizable status appearance,
including category-driven defaults and PATCH behavior around category changes.
"""

from datetime import UTC, datetime

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.soft_delete_filter import select_including_deleted
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import InitiativeMember, InitiativeRoleModel
from app.models.tenant.task import Task, TaskStatusCategory
from app.services.tenant import archive as archive_service
from app.services.tenant import task_statuses as task_statuses_service
from app.services.tenant.soft_delete import soft_delete_entity
from app.testing import guild_of, route_session_to_guild
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_task_status,
    create_user,
    get_auth_headers,
)


async def _setup_project(session: AsyncSession):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    initiative = await create_initiative(session, guild, user, name="Test Initiative")
    project = await create_project(session, initiative, user, name="Test Project")
    headers = get_auth_headers(user)
    return project, headers


async def test_create_status_uses_category_defaults(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)

    response = await client.post(
        f"/api/v1/c/{guild_of(project)}/projects/{project.id}/task-statuses/",
        json={"name": "Review", "category": "todo"},
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["color"] == "#94A3B8"
    assert body["icon"] == "circle"


async def test_create_status_respects_explicit_color_icon(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)

    response = await client.post(
        f"/api/v1/c/{guild_of(project)}/projects/{project.id}/task-statuses/",
        json={
            "name": "Shipping",
            "category": "in_progress",
            "color": "#FF00AA",
            "icon": "rocket",
        },
        headers=headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["color"] == "#FF00AA"
    assert body["icon"] == "rocket"


async def test_patch_updates_color_and_icon(client: AsyncClient, session: AsyncSession):
    project, headers = await _setup_project(session)
    statuses = await task_statuses_service.ensure_default_statuses(
        session, project.id, locale="en"
    )
    await session.commit()
    todo = next(s for s in statuses if s.category == TaskStatusCategory.todo)

    response = await client.patch(
        f"/api/v1/c/{guild_of(project)}/projects/{project.id}/task-statuses/{todo.id}",
        json={"color": "#123456", "icon": "star"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["color"] == "#123456"
    assert body["icon"] == "star"


async def test_patch_category_change_keeps_existing_color_icon(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)
    statuses = await task_statuses_service.ensure_default_statuses(
        session, project.id, locale="en"
    )
    await session.commit()
    todo = next(
        s
        for s in statuses
        if s.category == TaskStatusCategory.todo and s.name == "To Do"
    )

    # First set explicit custom color/icon
    first = await client.patch(
        f"/api/v1/c/{guild_of(project)}/projects/{project.id}/task-statuses/{todo.id}",
        json={"color": "#ABCDEF", "icon": "flag"},
        headers=headers,
    )
    assert first.status_code == 200

    # Now change category only — color/icon should remain untouched
    second = await client.patch(
        f"/api/v1/c/{guild_of(project)}/projects/{project.id}/task-statuses/{todo.id}",
        json={"category": "in_progress"},
        headers=headers,
    )
    assert second.status_code == 200
    body = second.json()
    assert body["category"] == "in_progress"
    assert body["color"] == "#ABCDEF"
    assert body["icon"] == "flag"


async def test_create_status_rejects_invalid_hex_color(
    client: AsyncClient, session: AsyncSession
):
    project, headers = await _setup_project(session)

    response = await client.post(
        f"/api/v1/c/{guild_of(project)}/projects/{project.id}/task-statuses/",
        json={
            "name": "Bad color",
            "category": "todo",
            "color": "notcolor",
        },
        headers=headers,
    )

    assert response.status_code == 422


async def test_default_seeded_statuses_have_category_colors(
    session: AsyncSession,
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(session, user=user, guild=guild)
    initiative = await create_initiative(session, guild, user, name="Seed Initiative")
    project = await create_project(session, initiative, user, name="Seed Project")

    statuses = await task_statuses_service.ensure_default_statuses(
        session, project.id, locale="en"
    )
    by_category = {s.category: s for s in statuses}

    assert [(s.name, s.category, s.is_default) for s in statuses] == [
        ("To Do", TaskStatusCategory.todo, True),
        ("In Progress", TaskStatusCategory.in_progress, False),
        ("Done", TaskStatusCategory.done, False),
    ]
    assert by_category[TaskStatusCategory.todo].color == "#94A3B8"
    assert by_category[TaskStatusCategory.todo].icon == "circle"
    assert task_statuses_service.defaults_for_category(TaskStatusCategory.backlog) == (
        "#94A3B8",
        "circle-dashed",
    )
    assert by_category[TaskStatusCategory.in_progress].color == "#60A5FA"
    assert by_category[TaskStatusCategory.in_progress].icon == "circle-play"
    assert by_category[TaskStatusCategory.done].color == "#34D399"
    assert by_category[TaskStatusCategory.done].icon == "circle-check"


# ---------------------------------------------------------------------------
# GET /initiatives/{initiative_id}/task-statuses/ — the columns an initiative
# offers, aggregated over the projects the caller can read.
# ---------------------------------------------------------------------------


async def test_initiative_statuses_collapse_across_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    second = await create_project(session, a.initiative, a.user, name="Second")
    for project in (a.project, second):
        await create_task_status(
            session,
            project,
            name="Backlog",
            category=TaskStatusCategory.backlog,
            position=0,
        )
    await create_task_status(
        session,
        a.project,
        name="Blocked",
        category=TaskStatusCategory.todo,
        position=1,
        color="#FBBF24",
        icon="circle-pause",
    )

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 200
    body = response.json()
    # Ordered by board position: the shared Backlog column, then Blocked.
    assert body == [
        {
            "name": "Backlog",
            "category": "backlog",
            "color": "#94A3B8",
            "icon": "circle-dashed",
            "project_count": 2,
            "projects_total": 2,
        },
        {
            "name": "Blocked",
            "category": "todo",
            "color": "#FBBF24",
            "icon": "circle-pause",
            "project_count": 1,
            "projects_total": 2,
        },
    ]


async def test_initiative_statuses_separate_same_name_by_category(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, a.project, name="Review", category=TaskStatusCategory.todo, position=0
    )
    await create_task_status(
        session,
        a.project,
        name="Review",
        category=TaskStatusCategory.done,
        position=1,
    )

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 200
    body = response.json()
    assert [(entry["name"], entry["category"]) for entry in body] == [
        ("Review", "todo"),
        ("Review", "done"),
    ]


async def test_initiative_statuses_only_cover_readable_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, owner.project, name="Unshared", category=TaskStatusCategory.todo
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    theirs = await create_project(session, owner.initiative, member.user, name="Theirs")
    await create_task_status(
        session, theirs, name="Shared", category=TaskStatusCategory.todo
    )

    response = await client.get(
        member.g(f"/initiatives/{owner.initiative.id}/task-statuses/"),
        headers=member.headers,
    )

    assert response.status_code == 200
    body = response.json()
    # The project they hold no grant on contributes neither a column nor a
    # project to the total.
    assert [entry["name"] for entry in body] == ["Shared"]
    assert body[0]["projects_total"] == 1


async def test_initiative_statuses_skip_archived_and_template_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, a.project, name="Active", category=TaskStatusCategory.todo
    )
    archived = await create_project(
        session,
        a.initiative,
        a.user,
        name="Archived",
        archived_at=datetime.now(UTC),
    )
    await create_task_status(
        session, archived, name="Archived Only", category=TaskStatusCategory.todo
    )
    template = await create_project(
        session, a.initiative, a.user, name="Template", is_template=True
    )
    await create_task_status(
        session, template, name="Template Only", category=TaskStatusCategory.todo
    )

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body] == ["Active"]
    assert body[0]["projects_total"] == 1


async def test_initiative_statuses_empty_when_no_readable_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.get(
        a.g(f"/initiatives/{a.initiative.id}/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_initiative_statuses_cover_the_guild_for_an_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, owner.project, name="Unshared", category=TaskStatusCategory.todo
    )
    admin = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)

    response = await client.get(
        admin.g(f"/initiatives/{owner.initiative.id}/task-statuses/"),
        headers=admin.headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body] == ["Unshared"]
    assert body[0]["projects_total"] == 1


async def _grant_full_access(session: AsyncSession, initiative, user) -> None:
    """Turn on "Full access" for the role ``user`` holds in ``initiative``."""
    await route_session_to_guild(session, guild_of(initiative))
    membership = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == initiative.id,
                InitiativeMember.user_id == user.id,
            )
        )
    ).one()
    role = await session.get(InitiativeRoleModel, membership.role_id)
    assert role is not None
    role.override_share_restrictions = True
    session.add(role)
    await session.commit()


async def test_initiative_statuses_cover_the_initiative_on_full_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, owner.project, name="Unshared", category=TaskStatusCategory.todo
    )
    manager = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="project_manager",
    )
    await _grant_full_access(session, owner.initiative, manager.user)

    response = await client.get(
        manager.g(f"/initiatives/{owner.initiative.id}/task-statuses/"),
        headers=manager.headers,
    )

    # Full access reaches every project in the initiative, so the column shows
    # up here exactly as it would when opening that project directly.
    assert response.status_code == 200
    body = response.json()
    assert [entry["name"] for entry in body] == ["Unshared"]
    assert body[0]["project_count"] == 1
    assert body[0]["projects_total"] == 1


async def test_initiative_statuses_refused_to_a_non_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await create_task_status(
        session, owner.project, name="Unshared", category=TaskStatusCategory.todo
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    response = await client.get(
        outsider.g(f"/initiatives/{owner.initiative.id}/task-statuses/"),
        headers=outsider.headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "INITIATIVE_NOT_FOUND"


async def test_initiative_statuses_404_for_an_unknown_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

    response = await client.get(
        a.g("/initiatives/999999/task-statuses/"), headers=a.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "INITIATIVE_NOT_FOUND"


# ---------------------------------------------------------------------------
# DELETE /projects/{project_id}/task-statuses/{status_id} — a column can be
# retired without another column in its own category to catch its tasks.
# ---------------------------------------------------------------------------


async def test_delete_moves_tasks_to_the_default_without_a_fallback(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The case a legacy Blocked column was stuck in: no todo sibling to name."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    await session.commit()
    default_status = next(s for s in statuses if s.is_default)
    blocked = await create_task_status(
        session, a.project, name="Blocked", category=TaskStatusCategory.todo, position=9
    )
    created = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "title": "Waiting on legal",
            "task_status_id": blocked.id,
        },
    )
    assert created.status_code == 201, created.text

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{blocked.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 204, response.text
    task = await client.get(a.g(f"/tasks/{created.json()['id']}"), headers=a.headers)
    assert task.json()["task_status_id"] == default_status.id


async def test_delete_accepts_a_fallback_in_another_category(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    await session.commit()
    in_progress = next(
        s for s in statuses if s.category == TaskStatusCategory.in_progress
    )
    blocked = await create_task_status(
        session, a.project, name="Blocked", category=TaskStatusCategory.todo, position=9
    )
    created = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "title": "Unblocked",
            "task_status_id": blocked.id,
        },
    )
    assert created.status_code == 201, created.text

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{blocked.id}"),
        headers=a.headers,
        json={"fallback_status_id": in_progress.id},
    )

    assert response.status_code == 204, response.text
    task = await client.get(a.g(f"/tasks/{created.json()['id']}"), headers=a.headers)
    assert task.json()["task_status_id"] == in_progress.id


async def test_delete_into_done_completes_the_tasks_it_moves(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Crossing the done boundary stamps ``completed_at``, as a task move would."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    await session.commit()
    todo = next(s for s in statuses if s.category == TaskStatusCategory.todo)
    done = next(s for s in statuses if s.category == TaskStatusCategory.done)
    created = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "project_id": a.project.id,
            "title": "Shipped after all",
            "task_status_id": todo.id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["completed_at"] is None

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{todo.id}"),
        headers=a.headers,
        json={"fallback_status_id": done.id},
    )

    assert response.status_code == 204, response.text
    task = await client.get(a.g(f"/tasks/{created.json()['id']}"), headers=a.headers)
    assert task.json()["completed_at"] is not None


async def test_delete_into_done_advances_a_recurring_task(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    default_status = next(status for status in statuses if status.is_default)
    remaining_statuses = [
        status for status in statuses if status.id != default_status.id
    ]
    successor_status = (
        task_statuses_service.first_by_category_preference(remaining_statuses)
        or remaining_statuses[0]
    )
    done = next(
        status for status in statuses if status.category == TaskStatusCategory.done
    )
    due = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    recurring = await create_task(
        session,
        a.project,
        title="Daily check",
        task_status_id=default_status.id,
        due_date=due,
        recurrence="RRULE:FREQ=DAILY",
        recurrence_strategy="fixed",
    )

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{default_status.id}"),
        headers=a.headers,
        json={"fallback_status_id": done.id},
    )

    assert response.status_code == 204, response.text
    session.expunge_all()
    tasks = list(
        await session.exec(
            select(Task).where(
                Task.project_id == a.project.id,
                Task.title == "Daily check",
            )
        )
    )
    assert len(tasks) == 2
    completed = next(task for task in tasks if task.id == recurring.id)
    successor = next(task for task in tasks if task.id != recurring.id)
    assert completed.completed_at is not None
    assert completed.recurrence is None
    assert successor.task_status_id == successor_status.id
    assert successor.due_date == datetime(2026, 9, 17, 12, 0, tzinfo=UTC)
    assert successor.recurrence == "RRULE:FREQ=DAILY"


async def test_delete_can_remove_the_last_status_of_a_category(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    await session.commit()
    done = next(s for s in statuses if s.category == TaskStatusCategory.done)

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{done.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 204, response.text
    remaining = await client.get(
        a.g(f"/projects/{a.project.id}/task-statuses/"), headers=a.headers
    )
    assert [s["category"] for s in remaining.json()] == ["todo", "in_progress"]


async def test_delete_refuses_the_projects_only_status(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    only = await create_task_status(
        session, a.project, name="Everything", category=TaskStatusCategory.todo
    )

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{only.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "TASK_STATUS_CANNOT_REMOVE_LAST"


async def test_deleting_the_default_promotes_the_next_entry_column(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    await session.commit()
    todo = next(s for s in statuses if s.category == TaskStatusCategory.todo)
    await create_task_status(
        session,
        a.project,
        name="Someday",
        category=TaskStatusCategory.backlog,
        position=9,
    )

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{todo.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 204, response.text
    remaining = await client.get(
        a.g(f"/projects/{a.project.id}/task-statuses/"), headers=a.headers
    )
    default = next(s for s in remaining.json() if s["is_default"])
    assert default["name"] == "Someday"


async def test_a_legacy_projects_entry_column_is_its_backlog_not_its_blocked(
    session: AsyncSession, acting_user
):
    """A project seeded before this change keeps Backlog as where work starts.

    Its Blocked column is ``todo``, so a preference that reached for ``todo``
    first would start every task in it.
    """
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    for name, category, position in (
        ("Backlog", TaskStatusCategory.backlog, 0),
        ("In Progress", TaskStatusCategory.in_progress, 1),
        ("Blocked", TaskStatusCategory.todo, 2),
        ("Done", TaskStatusCategory.done, 3),
    ):
        await create_task_status(
            session, a.project, name=name, category=category, position=position
        )

    statuses = await task_statuses_service.list_statuses(session, a.project.id)
    assert all(not s.is_default for s in statuses)

    entry = task_statuses_service.first_by_category_preference(statuses)
    assert entry is not None and entry.name == "Backlog"

    default_status = await task_statuses_service.get_default_status(
        session, a.project.id
    )
    assert default_status.name == "Backlog"


# ---------------------------------------------------------------------------
# A column is retired or recategorised as a whole: the archived and trashed
# tasks in it follow the live ones, rather than pinning it in place.
# ---------------------------------------------------------------------------


async def _seed_column_with_frozen_tasks(session: AsyncSession, a):
    """A Blocked column holding a live, an archived and a trashed task."""
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    await session.commit()
    blocked = await create_task_status(
        session, a.project, name="Blocked", category=TaskStatusCategory.todo, position=9
    )
    live = await create_task(
        session, a.project, title="Live", task_status_id=blocked.id
    )
    archived = await create_task(
        session, a.project, title="Archived", task_status_id=blocked.id
    )
    trashed = await create_task(
        session, a.project, title="Trashed", task_status_id=blocked.id
    )
    await archive_service.archive_entity(session, archived)
    await soft_delete_entity(
        session, trashed, deleted_by_user_id=a.user.id, retention_days=30
    )
    await session.commit()
    return statuses, blocked, live, archived, trashed


async def _tasks_by_title(session: AsyncSession, project_id: int) -> dict[str, Task]:
    session.expunge_all()
    rows = await session.exec(
        select_including_deleted(Task).where(Task.project_id == project_id)
    )
    return {task.title: task for task in rows}


async def test_delete_moves_archived_and_trashed_tasks_with_the_live_ones(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses, blocked, *_ = await _seed_column_with_frozen_tasks(session, a)
    in_progress = next(
        s for s in statuses if s.category == TaskStatusCategory.in_progress
    )

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{blocked.id}"),
        headers=a.headers,
        json={"fallback_status_id": in_progress.id},
    )

    assert response.status_code == 204, response.text
    tasks = await _tasks_by_title(session, a.project.id)
    assert {t.task_status_id for t in tasks.values()} == {in_progress.id}
    assert tasks["Archived"].archived_at is not None
    assert tasks["Trashed"].deleted_at is not None
    assert tasks["Live"].archived_at is None and tasks["Live"].deleted_at is None


async def test_delete_retires_a_column_holding_only_trashed_tasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The trash filter hides them from a count, but not from the foreign key."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    await session.commit()
    default_status = next(s for s in statuses if s.is_default)
    blocked = await create_task_status(
        session, a.project, name="Blocked", category=TaskStatusCategory.todo, position=9
    )
    trashed = await create_task(
        session, a.project, title="Trashed", task_status_id=blocked.id
    )
    await soft_delete_entity(
        session, trashed, deleted_by_user_id=a.user.id, retention_days=30
    )
    await session.commit()

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{blocked.id}"),
        headers=a.headers,
        json={},
    )

    assert response.status_code == 204, response.text
    tasks = await _tasks_by_title(session, a.project.id)
    assert tasks["Trashed"].task_status_id == default_status.id
    assert tasks["Trashed"].deleted_at is not None


async def test_delete_into_done_completes_frozen_tasks_without_recurring_them(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A finished recurring task moved into Done is not started over."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    statuses = await task_statuses_service.ensure_default_statuses(
        session, a.project.id, locale="en"
    )
    await session.commit()
    done = next(s for s in statuses if s.category == TaskStatusCategory.done)
    blocked = await create_task_status(
        session, a.project, name="Blocked", category=TaskStatusCategory.todo, position=9
    )
    archived = await create_task(
        session,
        a.project,
        title="Archived weekly",
        task_status_id=blocked.id,
        due_date=datetime(2026, 9, 16, 12, 0, tzinfo=UTC),
        recurrence="RRULE:FREQ=WEEKLY",
        recurrence_strategy="fixed",
    )
    await archive_service.archive_entity(session, archived)
    await session.commit()

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-statuses/{blocked.id}"),
        headers=a.headers,
        json={"fallback_status_id": done.id},
    )

    assert response.status_code == 204, response.text
    tasks = await _tasks_by_title(session, a.project.id)
    assert list(tasks) == ["Archived weekly"]
    moved = tasks["Archived weekly"]
    assert moved.task_status_id == done.id
    assert moved.completed_at is not None
    assert moved.archived_at is not None
    assert moved.recurrence is not None


async def test_patch_category_realigns_archived_and_trashed_tasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    _statuses, blocked, *_ = await _seed_column_with_frozen_tasks(session, a)

    response = await client.patch(
        a.g(f"/projects/{a.project.id}/task-statuses/{blocked.id}"),
        headers=a.headers,
        json={"category": "done"},
    )

    assert response.status_code == 200, response.text
    tasks = await _tasks_by_title(session, a.project.id)
    assert all(t.completed_at is not None for t in tasks.values())
    assert tasks["Archived"].archived_at is not None
    assert tasks["Trashed"].deleted_at is not None
