"""A task's parent and parts: read onto list rows, written as its ``part_of``
edge, grouped by, and made from a checklist line."""

from datetime import datetime, timezone

from httpx import AsyncClient

from app.core.messages import ChecklistMessages, RelationshipMessages, TaskMessages
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import TaskStatusCategory
from app.services.tenant import task_checklist as checklist_service
from app.services.tenant.task_hierarchy import title_from_line
from app.testing import route_session_to_guild
from app.testing.factories import (
    checklist_items,
    create_initiative,
    create_project,
    create_relationship,
    create_task,
)
from sqlmodel import select

TASK = SearchEntityType.task


async def _part_of(session, guild, part, whole):
    await create_relationship(
        session,
        guild,
        source=(TASK, part.id),
        target=(TASK, whole.id),
        relationship_type=RelationshipType.part_of,
    )


async def _list(client: AsyncClient, a) -> dict[int, dict]:
    response = await client.get(
        a.g("/tasks/"),
        headers=a.headers,
        params={
            "conditions": f'[{{"field":"project_id","op":"eq","value":{a.project.id}}}]',
            "page_size": 100,
        },
    )
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()["items"]}


async def _live_parents(session, guild_id: int, task_id: int) -> list[int]:
    await route_session_to_guild(session, guild_id)
    rows = await session.exec(
        select(EntityRelationship.target_id).where(
            EntityRelationship.source_type == TASK.value,
            EntityRelationship.source_id == task_id,
            EntityRelationship.relationship_type == RelationshipType.part_of.value,
            EntityRelationship.removed_at.is_(None),
        )
    )
    return sorted(rows.all())


async def test_list_rows_carry_parent_and_progress(
    client: AsyncClient, acting_user, session
):
    """A part names its parent; a parent counts how many of its live parts are
    done, leaving out the archived ones."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    post = await create_task(session, a.project, title="Post")
    done = await create_task(
        session, a.project, title="Script", status_category=TaskStatusCategory.done
    )
    open_ = await create_task(session, a.project, title="Shoot")
    shelved = await create_task(
        session, a.project, title="Old", archived_at=datetime.now(timezone.utc)
    )
    for part in (done, open_, shelved):
        await _part_of(session, a.guild, part, post)

    rows = await _list(client, a)

    assert rows[post.id]["subtask_progress"] == {"completed": 1, "total": 2}
    assert rows[post.id]["parent"] is None
    assert rows[done.id]["parent"] == {"id": post.id, "title": "Post"}
    assert rows[done.id]["subtask_progress"] is None


async def test_a_part_of_two_is_under_the_first(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first = await create_task(session, a.project, title="First")
    second = await create_task(session, a.project, title="Second")
    part = await create_task(session, a.project)
    await _part_of(session, a.guild, part, first)
    await _part_of(session, a.guild, part, second)

    rows = await _list(client, a)

    assert rows[part.id]["parent"]["id"] == first.id
    assert rows[second.id]["subtask_progress"] == {"completed": 0, "total": 1}


async def test_create_with_a_parent_links_it(client: AsyncClient, acting_user, session):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    post = await create_task(session, a.project, title="Post")

    response = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={"title": "Edit", "project_id": a.project.id, "parent_task_id": post.id},
    )

    assert response.status_code == 201, response.text
    assert response.json()["parent"] == {"id": post.id, "title": "Post"}
    assert await _live_parents(session, a.guild.id, response.json()["id"]) == [post.id]


async def test_update_moves_and_clears_the_parent(
    client: AsyncClient, acting_user, session
):
    """A new parent replaces every task the task was part of; null takes it
    out of them."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    first, second, third, part = [
        await create_task(session, a.project) for _ in range(4)
    ]
    await _part_of(session, a.guild, part, first)
    await _part_of(session, a.guild, part, second)

    moved = await client.patch(
        a.g(f"/tasks/{part.id}"), headers=a.headers, json={"parent_task_id": third.id}
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["parent"]["id"] == third.id
    assert await _live_parents(session, a.guild.id, part.id) == [third.id]

    kept = await client.patch(
        a.g(f"/tasks/{part.id}"), headers=a.headers, json={"title": "Renamed"}
    )
    assert kept.json()["parent"]["id"] == third.id

    cleared = await client.patch(
        a.g(f"/tasks/{part.id}"), headers=a.headers, json={"parent_task_id": None}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["parent"] is None
    assert await _live_parents(session, a.guild.id, part.id) == []


async def test_a_task_is_not_put_under_its_own_part(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    top, middle, bottom = [await create_task(session, a.project) for _ in range(3)]
    await _part_of(session, a.guild, middle, top)
    await _part_of(session, a.guild, bottom, middle)

    for parent in (top.id, bottom.id):
        response = await client.patch(
            a.g(f"/tasks/{top.id}"), headers=a.headers, json={"parent_task_id": parent}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == TaskMessages.PARENT_IS_PART
    assert await _live_parents(session, a.guild.id, top.id) == []


async def test_a_loop_is_refused_however_deep_the_chain(
    client: AsyncClient, acting_user, session
):
    """Past the ten hops a relationships walk stops at."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    chain = [await create_task(session, a.project) for _ in range(13)]
    for whole, part in zip(chain, chain[1:]):
        await _part_of(session, a.guild, part, whole)

    response = await client.patch(
        a.g(f"/tasks/{chain[0].id}"),
        headers=a.headers,
        json={"parent_task_id": chain[-1].id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == TaskMessages.PARENT_IS_PART


async def test_a_parent_in_another_initiative_is_refused(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    elsewhere = await create_initiative(session, a.guild, a.user, name="Elsewhere")
    other = await create_task(
        session, await create_project(session, elsewhere, a.user, name="Other")
    )
    task = await create_task(session, a.project)

    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"parent_task_id": other.id}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == RelationshipMessages.CROSS_INITIATIVE


async def test_grouped_by_parent_a_parent_leads_its_parts(
    client: AsyncClient, acting_user, session
):
    """Each part is listed under its parent, the parent under itself, and a
    task with neither in the empty group."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    post = await create_task(session, a.project, title="Post", position=1)
    other = await create_task(session, a.project, title="Another post", position=2)
    step = await create_task(session, a.project, title="Step")
    lone = await create_task(session, a.project, title="Lone")
    shelved = await create_task(
        session, a.project, archived_at=datetime.now(timezone.utc)
    )
    await _part_of(session, a.guild, step, post)
    # Its only part is archived, so it leads nothing.
    await _part_of(session, a.guild, shelved, other)

    response = await client.get(
        a.g("/tasks/groups"),
        headers=a.headers,
        params={
            "group_by": "parent_task_id",
            "conditions": f'[{{"field":"project_id","op":"eq","value":{a.project.id}}}]',
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [(g["key"], g["label"]) for g in body["groups"]] == [
        (str(post.id), "Post"),
        ("", None),
    ]
    assert body["rows"][str(post.id)] == [str(post.id)]
    assert body["rows"][str(step.id)] == [str(post.id)]
    assert str(lone.id) not in body["rows"]
    assert str(other.id) not in body["rows"]


async def test_promoting_a_line_makes_a_part(client: AsyncClient, acting_user, session):
    """The line becomes a task of the same project, part of this one, done if
    it was ticked, and leaves the checklist."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    items = [*checklist_items("Concept"), *checklist_items("Script", done=True)]
    post = await create_task(session, a.project, title="Post", checklist=items)

    response = await client.post(
        a.g(f"/tasks/{post.id}/checklist/{items[1]['id']}/promote"), headers=a.headers
    )

    assert response.status_code == 201, response.text
    made = response.json()
    assert made["title"] == "Script"
    assert made["project_id"] == a.project.id
    assert made["task_status"]["category"] == "done"
    assert made["parent"] == {"id": post.id, "title": "Post"}

    after = await client.get(a.g(f"/tasks/{post.id}"), headers=a.headers)
    assert [item["text"] for item in after.json()["checklist"]] == ["Concept"]
    assert after.json()["subtask_progress"] == {"completed": 1, "total": 1}


async def test_promoting_a_line_with_mentions_keeps_its_words(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    line = f"Call @[]({a.user.id}) about #billing"
    items = checklist_items(line)
    post = await create_task(session, a.project, checklist=items)

    response = await client.post(
        a.g(f"/tasks/{post.id}/checklist/{items[0]['id']}/promote"), headers=a.headers
    )

    assert response.status_code == 201, response.text
    assert response.json()["title"] == "Call about billing"
    assert response.json()["description"] == line
    assert response.json()["task_status"]["category"] != "done"


async def test_a_line_changed_since_it_was_read_is_kept(session, acting_user):
    """The removal matches the line as the task was made from it, so a tick or
    a rewording that landed in between is not thrown away."""
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    items = checklist_items("Concept", "Script")
    post = await create_task(session, a.project, checklist=items)
    read = dict(items[1])
    await session.exec(
        checklist_service.toggle_statement(),
        params=checklist_service.toggle_params(
            task_id=post.id,
            item_id=read["id"],
            done=True,
            now=datetime.now(timezone.utc),
        ),
    )

    removed = await session.exec(
        checklist_service.remove_statement(),
        params=checklist_service.remove_params(
            task_id=post.id, item=read, now=datetime.now(timezone.utc)
        ),
    )
    assert removed.one_or_none() is None

    read["done"] = True
    removed = await session.exec(
        checklist_service.remove_statement(),
        params=checklist_service.remove_params(
            task_id=post.id, item=read, now=datetime.now(timezone.utc)
        ),
    )
    assert [item["text"] for item in removed.one()[0]] == ["Concept"]


async def test_promoting_a_missing_line_is_404(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    post = await create_task(session, a.project, checklist=checklist_items("One"))

    response = await client.post(
        a.g(f"/tasks/{post.id}/checklist/nope/promote"), headers=a.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == ChecklistMessages.ITEM_NOT_FOUND


async def test_promoting_needs_write_on_the_task(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    items = checklist_items("One")
    post = await create_task(session, a.project, checklist=items)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        reader.g(f"/tasks/{post.id}/checklist/{items[0]['id']}/promote"),
        headers=reader.headers,
    )

    assert response.status_code in (403, 404)
    after = await client.get(a.g(f"/tasks/{post.id}"), headers=a.headers)
    assert len(after.json()["checklist"]) == 1


def test_title_from_line():
    assert title_from_line("Shoot the intro") == ("Shoot the intro", False)
    assert title_from_line("  Shoot   it ") == ("Shoot it", True)
    assert title_from_line("Ping @[](4) on #task[Brief](12) #ops") == (
        "Ping on ops",
        True,
    )
    assert title_from_line("@[](4)") == ("", True)
    long, shortened = title_from_line("word " * 100)
    assert shortened and len(long) <= 255 and long.endswith("…")
