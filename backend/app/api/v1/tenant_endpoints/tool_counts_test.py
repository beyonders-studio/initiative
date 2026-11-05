"""Every count is a count of a tool's own list, proved once for every tool.

``GET /tools/{tool}/counts`` and the sidebar's ``/tools/counts/by-initiative``
read each tool's list conditions rather than restating them, so a badge cannot
disagree with the list it sits on. These tests hold that for every tool in
``TOOL_LISTS``: a new tool is covered by being registered.
"""

import json
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS
from app.core.tools import Tool
from app.models.platform.guild import CommunityRole
from app.services.tenant import tags as tags_service
from app.testing import TOOL_FACTORIES, create_initiative, create_tag

TOOLS = pytest.mark.parametrize("tool", list(TOOL_LISTS), ids=lambda t: t.value)


async def _one_of_each(session, acting_user, tool: Tool):
    """An initiative holding one row in each of the tool's views, the live
    one tagged, beside a second live row with no tag. A tool with templates
    also has an archived template, which belongs to the archive."""
    actor = await acting_user(guild_role=CommunityRole.admin)
    home = await create_initiative(
        session, actor.guild, actor.user, **{t.view_permission: True for t in Tool}
    )
    factory = TOOL_FACTORIES[tool]
    tagged = await factory(session, home, actor.user)
    await factory(session, home, actor.user)
    await factory(session, home, actor.user, archived_at=datetime.now(timezone.utc))
    if "templates" in TOOL_LISTS[tool].views:
        await factory(session, home, actor.user, is_template=True)
        await factory(
            session,
            home,
            actor.user,
            is_template=True,
            archived_at=datetime.now(timezone.utc),
        )
    tag = await create_tag(session, actor.guild)
    await tags_service.set_entity_tags(
        session,
        tags_service.TOOL_TAG_LINKS[tool],
        guild_id=actor.guild.id,
        entity_id=tagged.id,
        tag_ids=[tag.id],
    )
    await session.commit()
    return actor, home, tag


async def _counts(client: AsyncClient, actor, tool: Tool, **params) -> dict:
    response = await client.get(
        actor.g(f"/tools/{tool.value}/counts"), headers=actor.headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _listed(client: AsyncClient, actor, tool: Tool, **params) -> int:
    response = await client.get(
        actor.g(f"/{tool.route_segment}/"), headers=actor.headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()["total_count"]


@TOOLS
async def test_each_view_counts_what_its_list_holds(
    client: AsyncClient, session, acting_user, tool: Tool
):
    actor, home, _tag = await _one_of_each(session, acting_user, tool)

    counts = await _counts(client, actor, tool, initiative_id=home.id)

    assert set(counts["views"]) == set(TOOL_LISTS[tool].views)
    for name, params in TOOL_LISTS[tool].views.items():
        listed = await _listed(client, actor, tool, initiative_id=home.id, **params)
        assert counts["views"][name] == listed, name
    assert counts["views"]["active"] == 2
    # The archive holds whatever was archived, templates included, and no
    # other view shows an archived row.
    if "templates" in TOOL_LISTS[tool].views:
        assert (counts["views"]["templates"], counts["views"]["archived"]) == (1, 2)
    else:
        assert counts["views"]["archived"] == 1
    # A page with no tag tree does not pay for one.
    assert (counts["tag_counts"], counts["untagged_count"]) == (None, None)


@TOOLS
async def test_the_tag_tree_counts_the_view_shown(
    client: AsyncClient, session, acting_user, tool: Tool
):
    actor, home, tag = await _one_of_each(session, acting_user, tool)

    live = await _counts(client, actor, tool, initiative_id=home.id, include_tags=True)
    assert live["tag_counts"] == {str(tag.id): 1}
    assert live["untagged_count"] == 1
    assert live["tag_counts"][str(tag.id)] == await _listed(
        client, actor, tool, initiative_id=home.id, tag_ids=[tag.id]
    )

    archived = await _counts(
        client, actor, tool, initiative_id=home.id, view="archived", include_tags=True
    )
    assert archived["tag_counts"] == {}
    # The archived row, and the archived template where the tool has them.
    assert archived["untagged_count"] == (
        2 if "templates" in TOOL_LISTS[tool].views else 1
    )

    # The tree counts what the list shows under the list's own filters.
    nothing = await _counts(
        client,
        actor,
        tool,
        initiative_id=home.id,
        include_tags=True,
        filters=json.dumps({"search": "no row is called this"}),
    )
    assert (nothing["tag_counts"], nothing["untagged_count"]) == ({}, 0)
    # The view decides its own archive leg, whatever the filters say.
    overlapping = await _counts(
        client,
        actor,
        tool,
        initiative_id=home.id,
        include_tags=True,
        filters=json.dumps({"archived": True}),
    )
    assert overlapping["tag_counts"] == live["tag_counts"]
    # A malformed filter is refused whether or not the tree is asked for.
    for include_tags in (True, False):
        refused = await client.get(
            actor.g(f"/tools/{tool.value}/counts"),
            headers=actor.headers,
            params={"include_tags": include_tags, "filters": json.dumps({"page": 2})},
        )
        assert refused.status_code == 400, include_tags


@TOOLS
async def test_the_sidebar_counts_each_tools_live_view(
    client: AsyncClient, session, acting_user, tool: Tool
):
    actor, home, _tag = await _one_of_each(session, acting_user, tool)

    response = await client.get(
        actor.g("/tools/counts/by-initiative"), headers=actor.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["counts"][tool.value] == {str(home.id): 2}


async def test_a_view_the_tool_does_not_have_is_refused(
    client: AsyncClient, acting_user
):
    actor = await acting_user(guild_role=CommunityRole.admin)

    response = await client.get(
        actor.g("/tools/counter_group/counts"),
        headers=actor.headers,
        params={"view": "templates"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "QUERY_UNKNOWN_VIEW"
