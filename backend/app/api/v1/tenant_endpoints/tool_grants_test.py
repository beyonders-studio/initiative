"""Sharing a tool, proved once for every tool.

``PUT /{tool}/{id}/grants`` is mounted from the resource-access registry
(``tenant_endpoints/tool_grants.py``), so what is worth asserting is that it
behaves the same whichever tool is named — the entities come from
``TOOL_FACTORIES`` and the cases are parametrised over the ``Tool`` enum, which
means a new tool is exercised here the moment it exists.

What survives here from the per-tool copies these replace:

- *the owner shares it* — ``queues_test.test_set_queue_grants`` and
  ``dashboards_test.test_set_grants_replaces_sharing`` (the grantee can then
  write, and the owner's own grant is kept);
- *a role can be named instead of a person* —
  ``queues_test.test_set_queue_role_grants``;
- *a reader cannot re-share* — the first half of
  ``calendars_test.test_set_calendar_grants_owner_only``. Its second half —
  that revoking every non-owner grant hides the row again — is already proved
  per tool where the visibility rules live (``calendars_test`` and
  ``dashboards_test`` both strip grants and read back).

A grant change also lets go of the people named inside the tool whom the new
sharing no longer reaches — a task's assignee, an event's attendee, a queue
item's person.

What stays where it is: sharing that runs into the initiative-role gate
(``queues_test.test_sharing_does_not_reach_past_the_role_gate``), and every
test that merely *uses* the route to set up something else.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db import post_commit
from app.models.platform.guild import CommunityRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.tenant.property import PropertyType, PropertyValue
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services.tenant import named_people
from app.testing import (
    create_calendar_event,
    create_collection,
    create_property_definition,
    create_property_value,
    create_queue_item,
    create_resource_grant,
    create_task,
    create_tool_entity,
    enable_all_tools,
    grant_role_permission,
    route_session_to_guild,
)

#: Every tool, as its own test case.
TOOLS = pytest.mark.parametrize("tool", list(Tool), ids=[t.value for t in Tool])


async def _entity(session: AsyncSession, actor, tool: Tool):
    """One instance of ``tool``, owned by ``actor``, in an all-tools initiative."""
    await enable_all_tools(session, actor.initiative)
    return await create_tool_entity(session, tool, actor.initiative, actor.user)


@TOOLS
async def test_the_owner_shares_it_with_somebody(
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

    response = await client.put(
        a.g(f"/{tool.route_segment}/{entity.id}/grants"),
        headers=a.headers,
        json=[{"user_id": b.user.id, "level": "write"}],
    )
    assert response.status_code == 200, response.text
    grants = response.json()["grants"]
    assert [grant["level"] for grant in grants if grant["user_id"] == b.user.id] == [
        "write"
    ]
    # The owner is kept whether or not the replacement list names them.
    assert [grant["level"] for grant in grants if grant["user_id"] == a.user.id] == [
        "owner"
    ]


@TOOLS
async def test_a_role_can_be_named_instead_of_a_person(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    member_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == a.initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    ).one()

    response = await client.put(
        a.g(f"/{tool.route_segment}/{entity.id}/grants"),
        headers=a.headers,
        json=[{"role_id": member_role.id, "level": "read"}],
    )
    assert response.status_code == 200, response.text
    grants = response.json()["grants"]
    assert [
        grant["level"] for grant in grants if grant["role_id"] == member_role.id
    ] == ["read"]


@TOOLS
async def test_a_reader_cannot_reshare_it(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """Sharing is a write on the thing shared, so reading it is not enough."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.put(
        b.g(f"/{tool.route_segment}/{entity.id}/grants"),
        headers=b.headers,
        json=[{"user_id": b.user.id, "level": "write"}],
    )
    assert response.status_code == 403, response.text


@TOOLS
async def test_someone_outside_the_initiative_gets_the_tools_not_found(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """A guild member who is not in the initiative reaches none of its content,
    and the refusal is in the tool's own words."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    response = await client.put(
        outsider.g(f"/{tool.route_segment}/{entity.id}/grants"),
        headers=outsider.headers,
        json=[],
    )
    assert response.status_code == 404, response.text
    assert response.json() == tool.not_found().body


@TOOLS
async def test_the_room_is_told_that_sharing_moved(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool, monkeypatch
):
    """Sharing decides who has the thing at all, so everyone in the room is
    re-checked at once and the ones who remain are told to refetch — with the
    change's name, never the new sharing itself."""
    from app.services.content_sockets import resource_room, sockets

    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    signalled: list[tuple] = []
    rechecked: list[tuple] = []

    def _record(guild_id, signalled_tool, resource_id, event_type):
        signalled.append((guild_id, signalled_tool, resource_id, event_type))

    async def _recheck(room):
        rechecked.append(room)

    monkeypatch.setattr(sockets, "signal", _record)
    monkeypatch.setattr(sockets, "recheck_room", _recheck)

    response = await client.put(
        a.g(f"/{tool.route_segment}/{entity.id}/grants"),
        headers=a.headers,
        json=[{"user_id": b.user.id, "level": "write"}],
    )
    assert response.status_code == 200, response.text

    assert (a.guild.id, tool, entity.id, "permissions_changed") in signalled
    assert rechecked == [resource_room(a.guild.id, tool.value, entity.id)]


async def _assign(session: AsyncSession, actor, project, person) -> None:
    await create_task(session, project, assignees=[person])


async def _invite(session: AsyncSession, actor, calendar, person) -> None:
    await create_calendar_event(session, calendar, actor.user, attendees=[person])


async def _queue_up(session: AsyncSession, actor, queue, person) -> None:
    await create_queue_item(session, queue, user_id=person.id)


async def _person_field(session: AsyncSession, actor, entity, person) -> None:
    definition = await create_property_definition(
        session, actor.initiative, type=PropertyType.user_reference
    )
    await create_property_value(session, entity, definition, value_user_id=person.id)


#: How a person is named inside a tool: by its own rows, or by a person field,
#: which any tool may carry.
NAMES = {
    "task_assignee": (Tool.project, _assign),
    "event_attendee": (Tool.calendar, _invite),
    "queue_item": (Tool.queue, _queue_up),
    "person_field": (Tool.file, _person_field),
}


@pytest.mark.parametrize("case", list(NAMES))
async def test_a_grant_change_lets_go_only_of_who_can_no_longer_open_it(
    client: AsyncClient, session: AsyncSession, acting_user, case: str
):
    """Nobody stays named inside a tool they can no longer open, and the
    cleanup reads effective access: a lower level, or access through another
    grant, keeps them named."""
    tool, name = NAMES[case]
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    entity = await _entity(session, a, tool)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await grant_role_permission(session, a.initiative, tool.view_permission)
    await create_resource_grant(
        session, entity, user=b.user, level=ResourceAccessLevel.write
    )
    await name(session, a, entity, b.user)
    governing = named_people.Governing.of(tool, entity)
    url = a.g(f"/{tool.route_segment}/{entity.id}/grants")

    async def named() -> set[int]:
        await session.commit()
        await route_session_to_guild(session, a.guild.id)
        return await named_people.named_on(session, governing)

    assert b.user.id in await named()

    # The per-user grant swapped for an all-members read grant: still opens it.
    r = await client.put(
        url,
        headers=a.headers,
        json=[{"all_initiative_members": True, "level": "read"}],
    )
    assert r.status_code == 200, r.text
    assert b.user.id in await named()

    # Every grant removed: they can no longer open it and are let go.
    r = await client.put(url, headers=a.headers, json=[])
    assert r.status_code == 200, r.text
    assert b.user.id not in await named()


async def test_a_collection_names_whoever_can_open_a_file_in_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A collection has no sharing of its own: a file's sharing changing lets
    nobody go from a collection that only has the same id, and lets go of who
    can no longer open any file in a collection that holds it."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    file = await _entity(session, a, Tool.file)
    held = await create_tool_entity(session, Tool.file, a.initiative, a.user)
    collection = await create_collection(session, a.initiative, a.user, files=[held])
    assert collection.id == file.id
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await grant_role_permission(session, a.initiative, Tool.file.view_permission)
    await create_resource_grant(session, held, user=b.user)
    await _person_field(session, a, collection, b.user)

    async def named() -> list[int | None]:
        await post_commit.settle_all()
        await route_session_to_guild(session, a.guild.id)
        return list(
            (
                await session.exec(
                    select(PropertyValue.value_user_id).where(
                        PropertyValue.entity_type == "collection",
                        PropertyValue.entity_id == collection.id,
                    )
                )
            ).all()
        )

    for shared, still in ((file, [b.user.id]), (held, [None])):
        r = await client.put(
            a.g(f"/files/{shared.id}/grants"), headers=a.headers, json=[]
        )
        assert r.status_code == 200, r.text
        assert await named() == still
