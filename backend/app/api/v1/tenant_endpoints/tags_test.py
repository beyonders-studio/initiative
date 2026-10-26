"""Behavioral tests for tag assignment — the shared service path, the bulk
endpoint, soft-delete interaction, and the cross-initiative isolation gate.
"""

from httpx import AsyncClient
from sqlmodel import select

from app.core.relationships import node_id
from app.core.search import SearchEntityType
from app.models.platform.guild import CommunityRole
from app.models.tenant.relationship import EntityRelationship
from app.testing import (
    create_initiative,
    create_tag,
    create_task,
)


async def _task_tag_ids(session, guild_id: int, task_id: int) -> set[int]:
    from app.db.session import clear_rls_context
    from app.testing.schema_harness import route_session_to_guild

    clear_rls_context(session)
    await route_session_to_guild(session, guild_id)
    result = await session.exec(
        select(EntityRelationship.target_id).where(
            EntityRelationship.source_node == node_id(SearchEntityType.task, task_id),
            EntityRelationship.relationship_type == "tagged_with",
            EntityRelationship.removed_at.is_(None),
        )
    )
    return set(result.all())


# ---------------------------------------------------------------------------
# Tag dictionary permissions (deliberate product decision)
# ---------------------------------------------------------------------------


async def test_any_guild_member_can_manage_the_tag_dictionary(
    client: AsyncClient, acting_user
):
    """Product decision: the tag dictionary is a guild-wide folksonomy.

    EVERY guild member — even one in no initiative — can create, rename,
    recolor, and trash tags; only hard purge is admin-gated (the RESTRICTIVE
    RLS policy). This test pins the decision so the openness reads as
    intentional, not as a missing gate.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    created = await client.post(
        member.g("/tags/"),
        headers=member.headers,
        json={"name": "Folk Tag", "color": "#112233"},
    )
    assert created.status_code == 201
    tag_id = created.json()["id"]

    renamed = await client.patch(
        member.g(f"/tags/{tag_id}"),
        headers=member.headers,
        json={"name": "Folk Tag Renamed", "color": "#445566"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Folk Tag Renamed"

    trashed = await client.delete(member.g(f"/tags/{tag_id}"), headers=member.headers)
    assert trashed.status_code == 204


# ---------------------------------------------------------------------------
# Single-entity set-tags (shared service path)
# ---------------------------------------------------------------------------


async def test_task_tags_replace_and_dedup(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    other = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"tag_ids": [tag.id, other.id, tag.id]},
    )
    assert response.status_code == 200
    assert {t["id"] for t in response.json()["tags"]} == {tag.id, other.id}

    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"tag_ids": [other.id]}
    )
    assert response.status_code == 200
    assert await _task_tag_ids(session, a.guild.id, task.id) == {other.id}


async def test_set_tags_rejects_trashed_tag(client: AsyncClient, acting_user, session):
    """A trashed tag id is invalid everywhere — the incident regression: a
    stale client merging a since-trashed tag id must get a clean 400."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    delete = await client.delete(a.g(f"/tags/{tag.id}"), headers=a.headers)
    assert delete.status_code == 204

    response = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"tag_ids": [tag.id]}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_TAG_IDS"


async def test_set_tags_rejects_other_guilds_tag(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    b = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    foreign_tag = await create_tag(session, b.guild)
    task = await create_task(session, a.project)

    response = await client.patch(
        a.g(f"/tasks/{task.id}"),
        headers=a.headers,
        json={"tag_ids": [foreign_tag.id]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_TAG_IDS"


async def test_generic_tool_tags_route_covers_every_tool(
    client: AsyncClient, acting_user, session
):
    """PUT /tools/{tool}/{tool_id}/tags works for EVERY Tool member.

    Both halves derive from the enum — the feature toggles from ``Tool`` and
    the entities from ``TOOL_FACTORIES`` — so a new
    tool is exercised here the moment it exists, rather than when someone
    remembers to add a line. A tool with no factory fails at import of
    ``app.testing``, once, naming itself.
    """
    from app.core.tools import Tool
    from app.testing import create_tool_entity, enable_all_tools

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await enable_all_tools(session, a.initiative)
    tag = await create_tag(session, a.guild)

    entities = {
        tool: await create_tool_entity(session, tool, a.initiative, a.user)
        for tool in Tool
    }

    for tool, entity in entities.items():
        response = await client.put(
            a.g(f"/tools/{tool.value}/{entity.id}/tags"),
            headers=a.headers,
            json={"tag_ids": [tag.id]},
        )
        assert response.status_code == 200, (tool, response.text)
        assert [t["id"] for t in response.json()] == [tag.id], tool

    # Every tool's own read path serves the assignment back. Asked of all of
    # them rather than one: a tag lives in the shared edge table now, so what
    # differs between one tool's listing and the next is only whether it
    # remembered to ask for them.
    for tool, entity in entities.items():
        listing = await client.get(a.g(f"/{tool.route_segment}/"), headers=a.headers)
        assert listing.status_code == 200, (tool, listing.text)
        body = listing.json()
        rows = body["items"] if isinstance(body, dict) else body
        (row,) = [r for r in rows if r["id"] == entity.id]
        assert [t["id"] for t in row["tags"]] == [tag.id], tool


async def test_generic_tool_tags_route_rejects_unknown_tool(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    response = await client.put(
        a.g("/tools/task/1/tags"), headers=a.headers, json={"tag_ids": []}
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Bulk edit
# ---------------------------------------------------------------------------


async def test_bulk_add_and_remove_task_tags(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    keep = await create_tag(session, a.guild)
    added = await create_tag(session, a.guild)
    tasks = [await create_task(session, a.project) for _ in range(3)]
    first = tasks[0]

    seed = await client.patch(
        a.g(f"/tasks/{first.id}"), headers=a.headers, json={"tag_ids": [keep.id]}
    )
    assert seed.status_code == 200

    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={
            "target_type": "task",
            "target_ids": [t.id for t in tasks],
            "add_tag_ids": [added.id],
        },
    )
    assert response.status_code == 200
    assert response.json()["updated_count"] == 3
    # Adds are idempotent and preserve unrelated existing tags.
    assert await _task_tag_ids(session, a.guild.id, first.id) == {keep.id, added.id}
    for task in tasks[1:]:
        assert await _task_tag_ids(session, a.guild.id, task.id) == {added.id}

    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={
            "target_type": "task",
            "target_ids": [t.id for t in tasks],
            "remove_tag_ids": [added.id],
        },
    )
    assert response.status_code == 200
    assert await _task_tag_ids(session, a.guild.id, first.id) == {keep.id}
    for task in tasks[1:]:
        assert await _task_tag_ids(session, a.guild.id, task.id) == set()


async def test_every_tag_target_is_bulk_tagged_and_listed_on_its_tag(
    client: AsyncClient, acting_user, session
):
    """Bulk editing reaches every taggable kind — each tool, and each
    sub-resource through the tool that governs it — and the tag's own page
    lists every one of them back."""
    from app.core.tools import TAGGABLE_EXTRAS, Tool
    from app.testing import (
        create_calendar_event,
        create_catalog_item,
        create_queue_item,
        create_tool_entity,
        create_wiki_page,
        enable_all_tools,
    )

    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await enable_all_tools(session, a.initiative)
    tag = await create_tag(session, a.guild)
    tools = {
        tool: await create_tool_entity(session, tool, a.initiative, a.user)
        for tool in Tool
    }
    extras = {
        "task": await create_task(session, tools[Tool.project]),
        "queue_item": await create_queue_item(session, tools[Tool.queue]),
        "calendar_event": await create_calendar_event(
            session, tools[Tool.calendar], a.user
        ),
        "catalog_item": await create_catalog_item(
            session, tools[Tool.catalog], a.user, write_blob=False
        ),
        "wiki_page": await create_wiki_page(session, tools[Tool.wiki], a.user),
    }
    assert set(extras) == set(TAGGABLE_EXTRAS)
    targets = {tool.value: entity for tool, entity in tools.items()} | extras

    for target, entity in targets.items():
        response = await client.post(
            a.g("/tags/bulk"),
            headers=a.headers,
            json={
                "target_type": target,
                "target_ids": [entity.id],
                "add_tag_ids": [tag.id],
            },
        )
        assert response.status_code == 200, (target, response.text)

    counts = await client.get(a.g(f"/tags/{tag.id}/counts"), headers=a.headers)
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"] == {target: 1 for target in targets}

    for target, entity in targets.items():
        listed = await client.get(
            a.g(f"/tags/{tag.id}/entities"),
            headers=a.headers,
            params={"kind": target},
        )
        assert listed.status_code == 200, (target, listed.text)
        body = listed.json()
        assert body["total_count"] == 1, target
        (item,) = body["items"]
        assert (item["entity_type"], item["entity_id"]) == (target, entity.id)
        assert item["tool_title"], target


async def test_a_tags_entities_page_through_one_kind_by_name(
    client: AsyncClient, acting_user, session
):
    """A tag's page lists one kind at a time, a page at a time, in name order,
    and its count for the kind is the list's own total."""
    from app.testing import assign_tag

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild)
    for title in ("Charlie", "alpha", "Bravo"):
        task = await create_task(session, a.project, title=title)
        await assign_tag(session, task, tag, commit=True)

    first = await client.get(
        a.g(f"/tags/{tag.id}/entities"),
        headers=a.headers,
        params={"kind": "task", "page_size": 2},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert [item["title"] for item in body["items"]] == ["alpha", "Bravo"]
    assert body["total_count"] == 3
    assert body["has_next"] is True
    assert {item["tool_title"] for item in body["items"]} == {a.project.name}

    second = await client.get(
        a.g(f"/tags/{tag.id}/entities"),
        headers=a.headers,
        params={"kind": "task", "page_size": 2, "page": 2},
    )
    assert [item["title"] for item in second.json()["items"]] == ["Charlie"]
    assert second.json()["has_next"] is False


async def test_a_tags_page_leaves_out_the_archive(
    client: AsyncClient, acting_user, session
):
    """The page lists what each tool's own list shows by default: an archived
    project is in its archive, and so is everything inside it."""
    from datetime import datetime, timezone

    from app.testing import assign_tag, create_project

    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, a.guild)
    live_task = await create_task(session, a.project, title="live")
    await assign_tag(session, live_task, tag, commit=True)
    archived_task = await create_task(
        session, a.project, title="put away", archived_at=datetime.now(timezone.utc)
    )
    await assign_tag(session, archived_task, tag, commit=True)
    shelved = await create_project(
        session, a.initiative, a.user, archived_at=datetime.now(timezone.utc)
    )
    await assign_tag(session, shelved, tag, commit=True)
    inside = await create_task(session, shelved, title="inside")
    await assign_tag(session, inside, tag, commit=True)

    counts = await client.get(a.g(f"/tags/{tag.id}/counts"), headers=a.headers)
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"] == {"task": 1}
    listed = await client.get(
        a.g(f"/tags/{tag.id}/entities"), headers=a.headers, params={"kind": "task"}
    )
    assert [item["entity_id"] for item in listed.json()["items"]] == [live_task.id]


async def test_a_tags_entities_need_a_taggable_kind(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.member)
    tag = await create_tag(session, a.guild)
    missing = await client.get(a.g(f"/tags/{tag.id}/entities"), headers=a.headers)
    assert missing.status_code == 422
    untaggable = await client.get(
        a.g(f"/tags/{tag.id}/entities"), headers=a.headers, params={"kind": "comment"}
    )
    assert untaggable.status_code == 422


async def test_bulk_edit_requires_an_operation(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={"target_type": "task", "target_ids": [1]},
    )
    assert response.status_code == 422


async def test_bulk_edit_rejects_trashed_tag_atomically(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    trashed = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    delete = await client.delete(a.g(f"/tags/{trashed.id}"), headers=a.headers)
    assert delete.status_code == 204

    response = await client.post(
        a.g("/tags/bulk"),
        headers=a.headers,
        json={
            "target_type": "task",
            "target_ids": [task.id],
            "add_tag_ids": [trashed.id],
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INVALID_TAG_IDS"
    assert await _task_tag_ids(session, a.guild.id, task.id) == set()


async def test_bulk_edit_denied_without_project_write(
    client: AsyncClient, acting_user, session
):
    """A member without write on the tasks' project can bulk-edit nothing —
    the whole request fails and no junction row changes."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g("/tags/bulk"),
        headers=b.headers,
        json={
            "target_type": "task",
            "target_ids": [task.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert response.status_code in (403, 404)
    assert await _task_tag_ids(session, a.guild.id, task.id) == set()


# ---------------------------------------------------------------------------
# Initiative isolation (gate 2)
# ---------------------------------------------------------------------------


async def test_cross_initiative_member_cannot_touch_tags(
    client: AsyncClient, acting_user, session
):
    """A member of a different initiative in the same guild gets 404 (RLS
    hides the row) for both the per-entity and bulk tag paths."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    # b belongs to the same guild but a DIFFERENT initiative (creator → PM
    # there), so a's task must be invisible to them.
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    await create_initiative(session, a.guild, b.user)

    response = await client.patch(
        b.g(f"/tasks/{task.id}"), headers=b.headers, json={"tag_ids": [tag.id]}
    )
    assert response.status_code == 404

    # Same gate on the generic tool route: a's project is invisible to b.
    response = await client.put(
        b.g(f"/tools/project/{a.project.id}/tags"),
        headers=b.headers,
        json={"tag_ids": [tag.id]},
    )
    assert response.status_code == 404

    response = await client.post(
        b.g("/tags/bulk"),
        headers=b.headers,
        json={
            "target_type": "task",
            "target_ids": [task.id],
            "add_tag_ids": [tag.id],
        },
    )
    assert response.status_code == 404
    assert await _task_tag_ids(session, a.guild.id, task.id) == set()
