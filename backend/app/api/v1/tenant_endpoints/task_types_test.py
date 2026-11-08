"""A project's task types: the four it starts with, in its maker's language,
and adding, changing, ordering and deleting them."""

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.task_types import MAX_TASK_TYPES
from app.db.soft_delete_filter import select_including_deleted
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import Task, TaskType
from app.models.tenant.tool_layout import ToolLayout
from app.services.tenant import task_types as task_types_service
from app.services.tenant.soft_delete import soft_delete_entity
from app.testing import guild_of, route_session_to_guild
from app.testing.factories import create_project, create_task

_PAGE = {"main": [{"type": "comments"}]}


def _types_url(a, project_id: int) -> str:
    return a.g(f"/projects/{project_id}/task-types/")


async def _types(session: AsyncSession, project) -> list[TaskType]:
    await route_session_to_guild(session, guild_of(project))
    return await task_types_service.ensure_default_types(
        session, project.id, locale="en"
    )


async def _speaks(session: AsyncSession, user, locale: str) -> None:
    user.locale = locale
    session.add(user)
    await session.commit()


async def test_a_new_project_starts_with_four_types_in_its_makers_language(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _speaks(session, a.user, "de")

    created = await client.post(
        a.g("/projects/"),
        json={"name": "Umzug", "initiative_id": a.initiative.id},
        headers=a.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()

    assert [t["name"] for t in body["task_types"]] == [
        "Aufgabe",
        "Fehler",
        "Idee",
        "Meilenstein",
    ]
    assert [t["is_default"] for t in body["task_types"]] == [True, False, False, False]
    assert [t["layout_preset"] for t in body["task_types"]] == [
        "plain",
        "fix",
        "discussion",
        "dates",
    ]
    assert [s["name"] for s in body["task_statuses"]] == [
        "Zu erledigen",
        "In Arbeit",
        "Erledigt",
    ]


async def test_a_language_the_app_does_not_speak_starts_in_english(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _speaks(session, a.user, "xx")

    created = await client.post(
        a.g("/projects/"),
        json={"name": "Moving", "initiative_id": a.initiative.id},
        headers=a.headers,
    )

    assert created.status_code == 201, created.text
    assert [t["name"] for t in created.json()["task_types"]] == [
        "Task",
        "Bug",
        "Idea",
        "Milestone",
    ]


async def test_list_returns_the_types_in_order(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _types(session, a.project)
    await session.commit()

    response = await client.get(_types_url(a, a.project.id), headers=a.headers)

    assert response.status_code == 200
    assert [t["name"] for t in response.json()] == ["Task", "Bug", "Idea", "Milestone"]


async def test_create_adds_a_type_at_the_end(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _types(session, a.project)
    await session.commit()

    response = await client.post(
        _types_url(a, a.project.id),
        json={"name": "Chore", "icon": "repeat", "layout_preset": "repeat"},
        headers=a.headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["name"], body["position"], body["is_default"]) == ("Chore", 4, False)
    assert (body["icon"], body["layout_preset"]) == ("repeat", "repeat")


async def test_a_name_is_taken_whatever_its_case(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    await _types(session, a.project)
    await session.commit()

    response = await client.post(
        _types_url(a, a.project.id), json={"name": " bug "}, headers=a.headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "TASK_TYPE_NAME_TAKEN"


async def test_a_type_started_from_another_takes_its_look_and_its_page(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    bug = next(t for t in await _types(session, a.project) if t.name == "Bug")
    await session.commit()
    saved = await client.put(
        a.g(f"/layouts/?tool=project&tool_id={a.project.id}"),
        json={"kind": "task", "task_type_id": bug.id, "definition": _PAGE},
        headers=a.headers,
    )
    assert saved.status_code == 200, saved.text

    response = await client.post(
        _types_url(a, a.project.id),
        json={"name": "Crash", "start_from_type_id": bug.id},
        headers=a.headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["icon"], body["color"], body["layout_preset"]) == (
        bug.icon,
        bug.color,
        "fix",
    )
    page = (
        await session.exec(
            select(ToolLayout).where(ToolLayout.task_type_id == body["id"])
        )
    ).one()
    assert page.definition == _PAGE


async def test_a_project_holds_a_limited_number_of_types(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    types = await _types(session, a.project)
    for index in range(MAX_TASK_TYPES - len(types)):
        session.add(TaskType(project_id=a.project.id, name=f"Kind {index}"))
    await session.commit()

    response = await client.post(
        _types_url(a, a.project.id), json={"name": "One more"}, headers=a.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "TASK_TYPE_LIMIT_REACHED"


async def test_a_reader_cannot_add_a_type(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await _types(session, owner.project)
    await session.commit()

    response = await client.post(
        _types_url(reader, owner.project.id),
        json={"name": "Chore"},
        headers=reader.headers,
    )

    assert response.status_code in (403, 404)


async def test_making_a_type_the_default_unmarks_the_old_one(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    idea = next(t for t in await _types(session, a.project) if t.name == "Idea")
    await session.commit()

    response = await client.patch(
        a.g(f"/projects/{a.project.id}/task-types/{idea.id}"),
        json={"is_default": True, "name": "Thought"},
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    listed = (await client.get(_types_url(a, a.project.id), headers=a.headers)).json()
    assert [(t["name"], t["is_default"]) for t in listed] == [
        ("Task", False),
        ("Bug", False),
        ("Thought", True),
        ("Milestone", False),
    ]


async def test_reorder_puts_the_types_in_the_order_given(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    types = await _types(session, a.project)
    await session.commit()
    task, _bug, _idea, milestone = types

    response = await client.post(
        a.g(f"/projects/{a.project.id}/task-types/reorder"),
        json={
            "items": [
                {"id": milestone.id, "position": 0},
                {"id": task.id, "position": 1},
            ]
        },
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    assert [t["name"] for t in response.json()] == [
        "Milestone",
        "Task",
        "Bug",
        "Idea",
    ]


async def test_delete_moves_every_task_of_the_type_and_takes_its_page(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    _task_type, bug, idea, _ = await _types(session, a.project)
    live = await create_task(session, a.project, task_type_id=bug.id)
    trashed = await create_task(session, a.project, task_type_id=bug.id)
    await soft_delete_entity(
        session, trashed, deleted_by_user_id=a.user.id, retention_days=None
    )
    session.add(
        ToolLayout(
            initiative_id=a.initiative.id,
            tool="project",
            tool_id=a.project.id,
            kind="task",
            task_type_id=bug.id,
            definition=_PAGE,
        )
    )
    await session.commit()

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-types/{bug.id}"),
        json={"fallback_type_id": idea.id},
        headers=a.headers,
    )

    assert response.status_code == 204, response.text
    await route_session_to_guild(session, guild_of(a.project))
    moved = (
        await session.exec(
            select_including_deleted(Task.id, Task.task_type_id).where(
                Task.id.in_([live.id, trashed.id])
            )
        )
    ).all()
    assert {row[1] for row in moved} == {idea.id}
    assert (
        await session.exec(select(ToolLayout).where(ToolLayout.task_type_id == bug.id))
    ).first() is None
    remaining = [
        t.name for t in await task_types_service.list_types(session, a.project.id)
    ]
    assert remaining == ["Task", "Idea", "Milestone"]


async def test_deleting_the_default_hands_it_to_where_its_tasks_went(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task_type, bug, _, _ = await _types(session, a.project)
    await create_task(session, a.project, task_type_id=task_type.id)
    await session.commit()

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-types/{task_type.id}"),
        json={"fallback_type_id": bug.id},
        headers=a.headers,
    )

    assert response.status_code == 204, response.text
    listed = (await client.get(_types_url(a, a.project.id), headers=a.headers)).json()
    assert [(t["name"], t["is_default"], t["position"]) for t in listed] == [
        ("Bug", True, 0),
        ("Idea", False, 1),
        ("Milestone", False, 2),
    ]


async def test_the_last_type_stays(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    types = await _types(session, a.project)
    for extra in types[1:]:
        await session.delete(extra)
    await session.commit()

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-types/{types[0].id}"),
        json={},
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "TASK_TYPE_CANNOT_REMOVE_LAST"


async def test_a_type_cannot_take_its_own_tasks(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    bug = (await _types(session, a.project))[1]
    await session.commit()

    response = await client.request(
        "DELETE",
        a.g(f"/projects/{a.project.id}/task-types/{bug.id}"),
        json={"fallback_type_id": bug.id},
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "TASK_TYPE_FALLBACK_MUST_DIFFER"


async def test_another_projects_type_is_not_found(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    elsewhere = await create_project(session, a.initiative, a.user, name="Elsewhere")
    await _types(session, a.project)
    other = (await _types(session, elsewhere))[1]
    await session.commit()

    response = await client.patch(
        a.g(f"/projects/{a.project.id}/task-types/{other.id}"),
        json={"name": "Stolen"},
        headers=a.headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "TASK_TYPE_NOT_FOUND"
