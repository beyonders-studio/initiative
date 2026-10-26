"""Deleting and duplicating a tool, proved once for every tool.

``DELETE /{tool}/{id}`` is mounted from the resource-access registry
(``tenant_endpoints/tool_lifecycle.py``), so the cases are parametrised over the
``Tool`` enum and a new tool is exercised here the moment it exists. What goes
into the trash with it is ``soft_delete_test``'s; restoring it is ``trash_test``'s.

``POST /{tool}/{id}/duplicate`` is mounted for every tool in
``tool_copy.TOOL_COPIERS``, and its shared steps are proved here per tool; what
each tool carries inside it is that tool's own test. So is the duplicate of a
row inside a tool (``resource_access.SUB_TOOLS``), which each sub-tool routes
itself.

The queue and counter-group signal tests this replaces asserted the same thing
for two tools under their own event names.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.resource_access import SUB_TOOLS, governing_tool, parent_column
from app.api.tool_copy import TOOL_COPIERS
from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.comment import Comment
from app.models.tenant.counter import Counter
from app.models.tenant.catalog import CatalogItem
from app.models.tenant.queue import QueueItem
from app.models.tenant.task import Task
from app.models.tenant.wiki import WikiPage
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.tenant.lifecycle_tree import CASCADE_CHILDREN
from app.testing import (
    assign_tag,
    create_calendar_event,
    create_counter,
    create_initiative,
    create_queue_item,
    create_resource_grant,
    create_tag,
    create_task,
    create_tool_entity,
    enable_all_tools,
    create_wiki_page,
    grant_role_permission,
)
from app.services.tenant.tags import TAG_LINKS

#: Every tool, as its own test case.
TOOLS = pytest.mark.parametrize("tool", list(Tool), ids=[t.value for t in Tool])
#: Every tool that can be duplicated, as its own test case.
COPIABLE = pytest.mark.parametrize(
    "tool", list(TOOL_COPIERS), ids=[t.value for t in TOOL_COPIERS]
)


async def _entity(session: AsyncSession, actor, tool: Tool, **overrides):
    """One instance of ``tool``, owned by ``actor``, in an all-tools initiative."""
    await enable_all_tools(session, actor.initiative)
    return await create_tool_entity(
        session, tool, actor.initiative, actor.user, **overrides
    )


@TOOLS
async def test_the_owner_deletes_it_and_the_room_is_told(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool, monkeypatch
):
    from app.services.content_sockets import sockets

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    signalled: list[tuple] = []
    monkeypatch.setattr(sockets, "signal", lambda *args: signalled.append(args))

    response = await client.delete(
        a.g(f"/{tool.route_segment}/{entity.id}"), headers=a.headers
    )

    assert response.status_code == 204, response.text
    assert signalled == [(a.guild.id, tool, entity.id, "deleted")]
    gone = await client.get(
        a.g(f"/{tool.route_segment}/{entity.id}"), headers=a.headers
    )
    assert gone.status_code == 404


@TOOLS
async def test_writing_to_it_is_not_enough_to_delete_it(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, entity, level=ResourceAccessLevel.write, user=b.user
    )

    response = await client.delete(
        b.g(f"/{tool.route_segment}/{entity.id}"), headers=b.headers
    )

    assert response.status_code == 403, response.text
    still = await client.get(
        a.g(f"/{tool.route_segment}/{entity.id}"), headers=a.headers
    )
    assert still.status_code == 200


@COPIABLE
async def test_a_copy_keeps_its_sharing_beside_and_its_tags_anywhere(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool, name="Plan")
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, entity, level=ResourceAccessLevel.write, user=b.user
    )
    await assign_tag(session, entity, await create_tag(session, a.guild), commit=True)
    elsewhere = await enable_all_tools(
        session, await create_initiative(session, a.guild, a.user)
    )
    path = a.g(f"/{tool.route_segment}/{entity.id}/duplicate")

    beside = await client.post(path, headers=a.headers)
    moved = await client.post(
        path, headers=a.headers, json={"target_initiative_id": elsewhere.id}
    )
    # A file's name may carry a sigil, as its filename may; no other may.
    sigil = await client.post(path, headers=a.headers, json={"name": "Plan #2"})
    if tool is Tool.file:
        assert sigil.status_code == 201, sigil.text
    else:
        assert sigil.json()["detail"] == "RESERVED_SIGIL_IN_NAME"

    assert beside.status_code == 201, beside.text
    assert moved.status_code == 201, moved.text
    beside, moved = beside.json(), moved.json()
    assert (beside["name"], beside["initiative_id"]) == ("Plan (Copy)", a.initiative.id)
    assert (moved["name"], moved["initiative_id"]) == ("Plan", elsewhere.id)
    assert any(g["user_id"] == b.user.id for g in beside["grants"])
    assert not any(g["user_id"] == b.user.id for g in moved["grants"])
    assert len(beside["tags"]) == len(moved["tags"]) == 1

    # An initiative that keeps its content in is copied only beside itself.
    await client.patch(
        a.g(f"/initiatives/{a.initiative.id}"),
        headers=a.headers,
        json={"keep_content_in": True},
    )
    kept = await client.post(
        path, headers=a.headers, json={"target_initiative_id": elsewhere.id}
    )
    assert kept.json()["detail"] == "INITIATIVE_CONTENT_KEPT_IN", kept.text
    again = await client.post(path, headers=a.headers, json={"name": "Plan again"})
    assert again.status_code == 201, again.text


@COPIABLE
async def test_copying_takes_write_or_a_template_and_the_right_to_create(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    reader, writer = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for _ in range(2)
    ]
    for person, level in ((reader, "read"), (writer, "write")):
        await create_resource_grant(
            session, entity, level=ResourceAccessLevel(level), user=person.user
        )
    path = a.g(f"/{tool.route_segment}/{entity.id}/duplicate")

    async def copy(person, name: str | None = None) -> tuple[int, dict]:
        response = await client.post(path, headers=person.headers, json={"name": name})
        return response.status_code, response.json()

    assert await copy(reader) == (403, tool.write_required().body)
    assert await copy(writer) == (403, tool.create_denied().body)
    await grant_role_permission(session, a.initiative, f"create_{tool.plural}")
    assert (await copy(writer))[0] == 201
    if hasattr(entity, "is_template"):
        entity.is_template = True
        session.add(entity)
        await session.commit()
        assert (await copy(reader, "From the template"))[0] == 201


@pytest.mark.always
@COPIABLE
def test_every_table_inside_a_tool_is_copied_or_left_on_purpose(tool: Tool):
    """A table filed under a tool is either copied with it or, like its
    comments, stays with the original. A new one fails here until its copier
    says which."""
    inside = {child for child, _ in CASCADE_CHILDREN.get(TOOL_LISTS[tool].model, ())}
    assert inside - {Comment} == TOOL_COPIERS[tool].copies


#: Where each row inside a tool is addressed, and how one called ``name`` is made.
CHILDREN = {
    Task: ("tasks", lambda s, tool, user, name: create_task(s, tool, title=name)),
    Counter: (
        "counters",
        lambda s, tool, user, name: create_counter(s, tool, name=name),
    ),
    QueueItem: (
        "queue-items",
        lambda s, tool, user, name: create_queue_item(s, tool, label=name),
    ),
    CalendarEvent: (
        "calendar-events",
        lambda s, tool, user, name: create_calendar_event(s, tool, user, title=name),
    ),
    WikiPage: (
        "wiki-pages",
        lambda s, tool, user, name: create_wiki_page(s, tool, user, title=name),
    ),
    # Copied with its catalog, not on its own.
    CatalogItem: None,
}


@pytest.mark.parametrize(
    "model", list(SUB_TOOLS), ids=[m.__tablename__ for m in SUB_TOOLS]
)
async def test_a_row_inside_a_tool_is_copied_beside_itself_by_its_writers(
    client: AsyncClient, session: AsyncSession, acting_user, model: type
):
    entry = CHILDREN[model]
    if entry is None:
        pytest.skip("not copied on its own")
    segment, make = entry
    column = SUB_TOOLS[model].name
    length = model.__table__.c[column].type.length
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    tool = await _entity(session, a, governing_tool(model.__tablename__))
    # As long as the column takes, so the copy's name has to be shortened.
    name = "Plan" + "n" * 251
    expected = (name[: length - 7] if length else name) + " (Copy)"
    row = await make(session, tool, a.user, name)
    tagged = any(spec.entity is model for spec in TAG_LINKS.values())
    if tagged:
        await assign_tag(session, row, await create_tag(session, a.guild), commit=True)
    reader = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, tool, level=ResourceAccessLevel.read, user=reader.user
    )
    path = a.g(f"/{segment}/{row.id}/duplicate")

    refused = await client.post(path, headers=reader.headers)
    copied = await client.post(path, headers=a.headers)

    assert refused.status_code == 403, refused.text
    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert body["id"] != row.id
    assert (body[column], body[parent_column(model)]) == (expected, tool.id)
    assert len(body.get("tags", [])) == int(tagged)
