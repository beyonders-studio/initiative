"""One pair of endpoints, every archivable kind.

The kinds are derived from the mixin, so what is worth testing is not each of
the nine in turn but the things that differ: a tool that could not be archived
before this existed, the two non-tools, and what a repeat of the same call does.
"""

from datetime import datetime

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import KINDS
from app.models.platform.guild import CommunityRole
from app.models.tenant.task import TaskStatusCategory
from app.testing import create_counter_group, create_file, create_task


async def test_a_tool_that_could_not_be_archived_before_can_be_now(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)

    response = await client.post(
        a.g(f"/archive/counter_group/{group.id}"), headers=a.headers
    )

    assert response.status_code == 200
    assert response.json()["archived_at"] is not None


async def test_archiving_twice_answers_with_the_stamp_it_has(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The second call is a repeat, not a conflict — an archived row is
    read-only, and this is the write that made it so."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    file = await create_file(session, a.initiative, a.user)

    first = await client.post(a.g(f"/archive/file/{file.id}"), headers=a.headers)
    assert first.status_code == 200

    again = await client.post(a.g(f"/archive/file/{file.id}"), headers=a.headers)
    assert again.status_code == 200
    assert again.json()["archived_at"] == first.json()["archived_at"]


async def test_unarchiving_something_live_is_a_repeat_too(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    file = await create_file(session, a.initiative, a.user)

    response = await client.post(a.g(f"/unarchive/file/{file.id}"), headers=a.headers)

    assert response.status_code == 200
    assert response.json()["archived_at"] is None


async def test_an_archived_tool_goes_back(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    group = await create_counter_group(session, a.initiative, a.user)

    await client.post(a.g(f"/archive/counter_group/{group.id}"), headers=a.headers)
    back = await client.post(
        a.g(f"/unarchive/counter_group/{group.id}"), headers=a.headers
    )

    assert back.status_code == 200
    assert back.json()["archived_at"] is None


async def test_archiving_an_initiative_archives_what_is_inside_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Finished is finished all the way down, and with one stamp, so a list
    filtering live work reads one column and gets the same answer everywhere."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    group = await create_counter_group(session, a.initiative, a.user)
    task = await create_task(session, a.project)

    response = await client.post(
        a.g(f"/archive/initiative/{a.initiative.id}"), headers=a.headers
    )
    assert response.status_code == 200
    stamp = response.json()["archived_at"]

    await session.refresh(a.project)
    await session.refresh(group)
    await session.refresh(task)
    assert a.project.archived_at is not None
    assert group.archived_at is not None
    assert task.archived_at is not None
    # One stamp, shared — including the one the endpoint answered with.
    assert a.project.archived_at == group.archived_at == task.archived_at
    assert a.project.archived_at == datetime.fromisoformat(stamp)


async def test_unarchiving_leaves_what_was_archived_on_its_own(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The shared stamp is what tells the two apart: a counter group put away
    earlier carries a different one and keeps it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    group = await create_counter_group(session, a.initiative, a.user)

    await client.post(a.g(f"/archive/counter_group/{group.id}"), headers=a.headers)
    await client.post(a.g(f"/archive/initiative/{a.initiative.id}"), headers=a.headers)
    await client.post(
        a.g(f"/unarchive/initiative/{a.initiative.id}"), headers=a.headers
    )

    await session.refresh(a.initiative)
    await session.refresh(a.project)
    await session.refresh(group)
    assert a.initiative.archived_at is None
    assert a.project.archived_at is None
    assert group.archived_at is not None


async def test_a_task_cannot_be_taken_out_from_under_an_archived_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Otherwise it is live inside a finished thing — and a live row is not
    asked about its ancestry again, so it could then be moved or deleted out."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)

    await client.post(a.g(f"/archive/project/{a.project.id}"), headers=a.headers)
    response = await client.post(a.g(f"/unarchive/task/{task.id}"), headers=a.headers)

    assert response.status_code == 409
    assert response.json()["detail"] == "PARENT_IS_FROZEN"
    await session.refresh(task)
    assert task.archived_at is not None

    # One that is not there is refused as a task, not as its project.
    missing = await client.post(
        a.g(f"/unarchive/task/{task.id + 1000}"), headers=a.headers
    )
    assert missing.status_code == 404
    assert missing.json() == KINDS["task"].not_found().body


async def test_the_project_going_back_takes_its_tasks_with_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The way out is the parent, and it still works — the cascade clears the
    parent before the children, which is the order the guard requires."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    task = await create_task(session, a.project)

    await client.post(a.g(f"/archive/project/{a.project.id}"), headers=a.headers)
    back = await client.post(
        a.g(f"/unarchive/project/{a.project.id}"), headers=a.headers
    )

    assert back.status_code == 200
    await session.refresh(task)
    assert task.archived_at is None


async def test_archiving_a_projects_done_tasks_archives_each_as_archiving_it_would(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One stamp for the batch, the live work left alone, and each task taken
    back out on its own through the same route as any other."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first = await create_task(
        session, a.project, status_category=TaskStatusCategory.done
    )
    second = await create_task(
        session, a.project, status_category=TaskStatusCategory.done
    )
    live = await create_task(session, a.project)

    response = await client.post(
        a.g("/tasks/archive-done"),
        params={"project_id": a.project.id},
        headers=a.headers,
    )

    assert response.json() == {"archived_count": 2}
    for task in (first, second, live):
        await session.refresh(task)
    assert first.archived_at is not None
    assert first.archived_at == second.archived_at
    assert live.archived_at is None

    back = await client.post(a.g(f"/unarchive/task/{first.id}"), headers=a.headers)
    assert back.status_code == 200
    await session.refresh(first)
    await session.refresh(second)
    assert first.archived_at is None
    assert second.archived_at is not None
