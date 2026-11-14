"""Integration tests for the cross-guild tool lists behind the My Tools page.

``GET /api/v1/me/{tool}`` is one route mounted per tool out of
``MY_TOOL_LISTS``, so the proofs that hold for every tool are parametrised
over the ``Tool`` enum rather than written per tool. What belongs to one tool
— a guild calendar, a project's archive — keeps its own case below.

``GET /api/v1/me/tools/counts``, which is what decides the page's tabs, is at
the end.
"""

from datetime import UTC, datetime

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.testing import (
    Actor,
    create_calendar,
    create_guild,
    create_guild_calendar,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_tool_entity,
    create_user,
    get_auth_headers,
    strip_non_owner_grants,
)

per_tool = pytest.mark.parametrize("tool", list(Tool), ids=lambda t: t.value)


def _path(tool: Tool) -> str:
    """The cross-guild list route for a tool."""
    return f"/api/v1/me/{tool.route_segment}"


def _keyed(response) -> set[tuple[int, int]]:
    """Items keyed by (guild, id): per-schema ids collide across communities,
    which is what callers of a merged list must key by too."""
    return {(item["community_id"], item["id"]) for item in response.json()["items"]}


async def _enable_tools(client, actor):
    """Turn on every tool for the actor's initiative."""
    response = await client.patch(
        actor.g(f"/initiatives/{actor.initiative.id}"),
        headers=actor.headers,
        json={tool.view_permission: True for tool in Tool},
    )
    assert response.status_code == 200, response.text


async def _create(client, actor, tool: Tool, name: str) -> dict:
    """Make one of ``tool`` in the actor's initiative, through its own route.

    Every tool is created the same way — a name and the initiative that holds
    it — so the route is derived from the enum rather than listed per tool.
    """
    response = await client.post(
        actor.g(f"/{tool.route_segment}/"),
        headers=actor.headers,
        json={"name": name, "initiative_id": actor.initiative.id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _second_guild(client, session: AsyncSession, actor: Actor) -> Actor:
    """The actor's user in a second guild of their own, every tool switched on.

    The same user and auth, bound to the new guild so ``.g()`` addresses it."""
    guild = await create_guild(session, creator=actor.user, name="Second Guild")
    await create_guild_membership(
        session, user=actor.user, guild=guild, role=CommunityRole.admin
    )
    initiative = await create_initiative(session, guild, actor.user, name="Initiative")
    second = Actor(
        user=actor.user, headers=actor.headers, guild=guild, initiative=initiative
    )
    await _enable_tools(client, second)
    return second


# ---------------------------------------------------------------------------
# What every tool's list does
# ---------------------------------------------------------------------------


@per_tool
async def test_each_list_is_its_tools_live_view_in_every_guild(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """Inside each community a My Tools list is the tool's own list, asked for
    its live view: the same rows, serialized the same way, and the tab counts
    the same totals. What the live view leaves out — the archive, templates, a
    tool switched off, what was never shared — is the guild list's to say, and
    is tested there."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, a)
    b = await _second_guild(client, session, a)
    for actor in (a, b):
        await create_tool_entity(session, tool, actor.initiative, a.user, name="Live")
        await create_tool_entity(
            session,
            tool,
            actor.initiative,
            a.user,
            name="Archived",
            archived_at=datetime.now(UTC),
        )
        if "templates" in TOOL_LISTS[tool].views:
            await create_tool_entity(
                session, tool, actor.initiative, a.user, name="Kit", is_template=True
            )

    in_guilds: dict[tuple[int, int], dict] = {}
    for actor in (a, b):
        response = await client.get(
            actor.g(f"/{tool.route_segment}/"),
            headers=a.headers,
            params={**TOOL_LISTS[tool].views["active"], "page_size": 50},
        )
        assert response.status_code == 200, response.text
        for item in response.json()["items"]:
            in_guilds[(item["community_id"], item["id"])] = item

    mine = await client.get(_path(tool), headers=a.headers, params={"page_size": 50})
    assert mine.status_code == 200, mine.text
    assert {(i["community_id"], i["id"]): i for i in mine.json()["items"]} == in_guilds
    assert mine.json()["total_count"] == len(in_guilds) == 2

    counts = await client.get("/api/v1/me/tools/counts", headers=a.headers)
    assert counts.json()["counts"][tool.value] == len(in_guilds)


@per_tool
async def test_the_list_answers_with_what_reaches_the_caller(
    client: AsyncClient, acting_user, tool: Tool
):
    """The row a caller just made is in their cross-guild list for that tool."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, a)
    row = await _create(client, a, tool, "Standup")

    response = await client.get(_path(tool), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert row["id"] in {item["id"] for item in data["items"]}
    assert data["total_count"] >= 1


@per_tool
async def test_a_guild_the_caller_is_not_in_contributes_nothing(
    client: AsyncClient, acting_user, tool: Tool
):
    """The merge visits the caller's own communities and no others."""
    outsider = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    stranger = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, stranger)
    theirs = await _create(client, stranger, tool, "Not Yours")

    response = await client.get(_path(tool), headers=outsider.headers)

    assert response.status_code == 200
    assert (stranger.guild.id, theirs["id"]) not in _keyed(response)


@per_tool
async def test_created_by_me_keeps_only_what_the_caller_wrote(
    client: AsyncClient, acting_user, tool: Tool
):
    """The page's other view: authorship, not everything that reaches you."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, admin)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    theirs = await _create(client, admin, tool, "Admin's")

    everything = await client.get(_path(tool), headers=other.headers)
    assert everything.status_code == 200
    assert theirs["id"] in {item["id"] for item in everything.json()["items"]}

    mine = await client.get(f"{_path(tool)}?created_by_me=true", headers=other.headers)
    assert mine.status_code == 200
    assert theirs["id"] not in {item["id"] for item in mine.json()["items"]}


@per_tool
async def test_guild_ids_narrows_the_merge(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """Unfiltered the list spans every community the caller belongs to;
    ``guild_ids`` narrows it to the ones named."""
    a1 = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, a1)
    a2 = await _second_guild(client, session, a1)

    row1 = await _create(client, a1, tool, "In Guild 1")
    row2 = await _create(client, a2, tool, "In Guild 2")

    both = await client.get(_path(tool), headers=a1.headers)
    assert both.status_code == 200
    assert (a1.guild.id, row1["id"]) in _keyed(both)
    assert (a2.guild.id, row2["id"]) in _keyed(both)

    narrowed = await client.get(
        f"{_path(tool)}?community_ids={a1.guild.id}", headers=a1.headers
    )
    assert narrowed.status_code == 200
    assert (a1.guild.id, row1["id"]) in _keyed(narrowed)
    assert (a2.guild.id, row2["id"]) not in _keyed(narrowed)


@per_tool
async def test_search_narrows_by_name(client: AsyncClient, acting_user, tool: Tool):
    """The filter box reads the same index the search page does."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, a)
    alpha = await _create(client, a, tool, "Alpha Notes")
    beta = await _create(client, a, tool, "Beta Summary")

    response = await client.get(f"{_path(tool)}?search=alpha", headers=a.headers)

    assert response.status_code == 200
    found = {item["id"] for item in response.json()["items"]}
    assert alpha["id"] in found
    assert beta["id"] not in found


@per_tool
async def test_pagination_walks_the_merged_list(
    client: AsyncClient, session: AsyncSession, acting_user, tool: Tool
):
    """Each guild orders and limits its own rows, and the pages cut from their
    merge continue one another across guilds: every row once, in order."""
    a1 = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, a1)
    a2 = await _second_guild(client, session, a1)
    for actor, name in [
        (a1, "Delta"),
        (a2, "bravo"),
        (a1, "alpha"),
        (a2, "Charlie"),
        (a1, "Echo"),
    ]:
        await _create(client, actor, tool, name)

    pages = []
    for page in (1, 2, 3):
        response = await client.get(
            f"{_path(tool)}?sort_by=name&page={page}&page_size=2", headers=a1.headers
        )
        assert response.status_code == 200
        pages.append(response.json())

    assert [page["total_count"] for page in pages] == [5, 5, 5]
    assert [page["has_next"] for page in pages] == [True, True, False]
    assert pages[1]["has_prev"] is True
    walked = [item for page in pages for item in page["items"]]
    assert [item["name"] for item in walked] == [
        "alpha",
        "bravo",
        "Charlie",
        "Delta",
        "Echo",
    ]
    assert [item["community_id"] for item in walked] == [
        a1.guild.id,
        a2.guild.id,
        a2.guild.id,
        a1.guild.id,
        a1.guild.id,
    ]


async def test_a_co_member_reads_what_was_shared_with_the_initiative(
    client: AsyncClient, acting_user
):
    """Sharing is what the list answers by, not who made the row."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    # Created through the API, so it carries the default all-members read grant.
    admin_doc = await _create(client, admin, Tool.file, "Admin's Doc")

    response = await client.get("/api/v1/me/files", headers=other.headers)

    assert response.status_code == 200
    assert admin_doc["id"] in {d["id"] for d in response.json()["items"]}


# ---------------------------------------------------------------------------
# What belongs to one tool
# ---------------------------------------------------------------------------


async def test_my_projects_follows_grants_not_guild_admin_standing(
    client: AsyncClient, session: AsyncSession
):
    """A guild admin's My Projects is what has been shared with them.

    Their authority still reaches every project in the community — asking for
    the initiative by name still answers with all of it. A list that spans
    initiatives answers a different question: what reaches the reader.
    """
    owner = await create_user(session, email="owner@example.com")
    admin = await create_user(session, email="otheradmin@example.com")

    guild = await create_guild(session, creator=owner, name="Shared Guild")
    await create_guild_membership(
        session, user=owner, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )

    elsewhere = await create_initiative(session, guild, owner, name="Not Theirs")
    unshared = await create_project(session, elsewhere, owner, name="Someone Else's")

    mine = await create_initiative(session, guild, admin, name="Theirs")
    shared = await create_project(session, mine, admin, name="Their Own")

    response = await client.get("/api/v1/me/projects", headers=get_auth_headers(admin))

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert shared.id in project_ids
    assert unshared.id not in project_ids


async def test_an_initiative_listing_still_answers_a_guild_admin_in_full(
    client: AsyncClient, session: AsyncSession
):
    """Naming one initiative asks about standing, and an admin's reaches it all.

    The companion to the test above: the same project the cross-initiative list
    withholds is returned the moment the admin asks for its initiative, which is
    what keeps this a change to navigation rather than to authority.
    """
    owner = await create_user(session, email="owner2@example.com")
    admin = await create_user(session, email="otheradmin2@example.com")

    guild = await create_guild(session, creator=owner, name="Shared Guild")
    await create_guild_membership(
        session, user=owner, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )

    elsewhere = await create_initiative(session, guild, owner, name="Not Theirs")
    unshared = await create_project(session, elsewhere, owner, name="Someone Else's")

    headers = get_auth_headers(admin)
    across = await client.get(f"/api/v1/c/{guild.id}/projects/", headers=headers)
    assert across.status_code == 200
    assert unshared.id not in {p["id"] for p in across.json()["items"]}

    within = await client.get(
        f"/api/v1/c/{guild.id}/projects/?initiative_id={elsewhere.id}",
        headers=headers,
    )
    assert within.status_code == 200
    assert unshared.id in {p["id"] for p in within.json()["items"]}


async def test_my_calendars_carry_a_guild_calendar(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild calendar belongs to no initiative, and reaches every member.

    It is what makes this list unlike the other eight: the row answers to no
    initiative switch and to no initiative membership, and the guild member
    reading it here is in none of the guild's initiatives.
    """
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    calendar = await create_guild_calendar(session, a.guild, a.user)
    member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    response = await client.get("/api/v1/me/calendars", headers=member.headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert calendar.id in {c["id"] for c in items}
    assert next(c for c in items if c["id"] == calendar.id)["initiative_id"] is None


async def test_my_calendars_merge_across_guilds_and_apply_sharing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Sharing is resolved per guild, as the guild is entered."""
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _enable_tools(client, a)
    shared = await create_calendar(session, a.initiative, a.user, name="Home Cal")
    secret = await create_calendar(session, a.initiative, a.user, name="Secret Cal")

    # Second guild the same user belongs to, with its own calendar.
    b = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await _enable_tools(client, b)
    await create_guild_membership(session, user=a.user, guild=b.guild)
    await create_initiative_member(session, b.initiative, a.user)
    away = await create_calendar(session, b.initiative, b.user, name="Away Cal")

    response = await client.get("/api/v1/me/calendars", headers=a.headers)
    assert response.status_code == 200
    names = {c["name"] for c in response.json()["items"]}
    assert {shared.name, secret.name, away.name} <= names

    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await strip_non_owner_grants(session, secret, a.user.id)
    member_resp = await client.get("/api/v1/me/calendars", headers=member.headers)
    assert member_resp.status_code == 200
    member_names = {c["name"] for c in member_resp.json()["items"]}
    assert shared.name in member_names
    assert secret.name not in member_names
    assert away.name not in member_names  # not a member of guild b


# ---------------------------------------------------------------------------
# The tab counts
# ---------------------------------------------------------------------------


async def test_my_tool_counts(client: AsyncClient, acting_user):
    """Every tool is answered for, with a zero where the caller has none."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, a)
    await _create(client, a, Tool.counter_group, "Standup")
    await _create(client, a, Tool.counter_group, "Retro")

    response = await client.get("/api/v1/me/tools/counts", headers=a.headers)

    assert response.status_code == 200
    counts = response.json()["counts"]
    assert counts["counter_group"] == 2
    # Present rather than absent: the page needs "none" to be distinguishable
    # from "not asked" when it decides which tabs to draw.
    assert counts["dashboard"] == 0
    # Derived from the enum rather than listed: every tool has a tab on this
    # page, so a new one belongs here the day it exists.
    assert set(counts) == {tool.value for tool in Tool}


async def test_my_tool_counts_created_by_me(client: AsyncClient, acting_user):
    """The counts follow the view the page is in."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _enable_tools(client, admin)
    other = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    await _create(client, admin, Tool.counter_group, "Admin's Counters")

    everything = await client.get("/api/v1/me/tools/counts", headers=other.headers)
    assert everything.status_code == 200
    assert everything.json()["counts"]["counter_group"] == 1

    mine = await client.get(
        "/api/v1/me/tools/counts?created_by_me=true", headers=other.headers
    )
    assert mine.status_code == 200
    assert mine.json()["counts"]["counter_group"] == 0
