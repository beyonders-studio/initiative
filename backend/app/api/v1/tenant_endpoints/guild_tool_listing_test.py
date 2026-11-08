"""The guild home's table, asked of every tool it can show.

That table is one table — the tool only supplies the rows — so the six list
endpoints behind it have to answer the same two questions the same way: search
the guild's whole set by name, and order it by name, by initiative, or by when
it was last touched. These tests state that contract once and run it against
each tool, because the failure they exist to catch is one endpoint quietly
drifting out of it.

Search and sort are asserted against the *whole* set rather than the page in
hand: a search that only reached the twenty rows already fetched would pass a
weaker test than the one the guild home needs.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models.platform.guild import CommunityRole
from app.testing import (
    create_calendar,
    create_counter_group,
    create_dashboard,
    create_file,
    create_initiative,
    create_project,
)

# Every tool the guild home can show: its list path, and the factory that
# makes one row of it. Each factory takes (session, initiative, creator) and a
# ``name``, which is all these tests need to tell rows apart.
TOOL_LISTS = [
    pytest.param("/projects/", create_project, id="projects"),
    pytest.param("/files/", create_file, id="files"),
    pytest.param("/counter-groups/", create_counter_group, id="counter-groups"),
    pytest.param("/calendars/", create_calendar, id="calendars"),
    pytest.param("/dashboards/", create_dashboard, id="dashboards"),
]

# Projects and files are core (always on); the rest are opt-in switches
# that default to off, and a tool has to be on for its list to return anything
# at all — so every initiative these tests make has all of them on.
ALL_TOOLS_ON = {
    "counter_groups_enabled": True,
    "calendars_enabled": True,
    "dashboards_enabled": True,
}


async def _workspace(session, acting_user):
    """A guild admin and an initiative with every tool switched on."""
    actor = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    initiative = await create_initiative(
        session, actor.guild, actor.user, name="Home", **ALL_TOOLS_ON
    )
    return actor, initiative


async def _names(client: AsyncClient, actor, path: str, **params) -> list[str]:
    """The names a list endpoint answers with, in the order it answers."""
    response = await client.get(actor.g(path), headers=actor.headers, params=params)
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()["items"]]


@pytest.mark.parametrize("path,factory", TOOL_LISTS)
async def test_search_narrows_to_matching_names(
    client: AsyncClient, session, acting_user, path, factory
):
    """``search`` is a case-insensitive substring of the name, and it counts."""
    a, home = await _workspace(session, acting_user)
    await factory(session, home, a.user, name="Barovia Arc")
    await factory(session, home, a.user, name="Waterdeep Docks")

    response = await client.get(
        a.g(path), headers=a.headers, params={"search": "barovia"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Barovia Arc"]
    # The count is of what matched, not of what the guild holds — the pager
    # below the table reads it.
    assert body["total_count"] == 1


@pytest.mark.parametrize("path,factory", TOOL_LISTS)
async def test_sort_by_name(client: AsyncClient, session, acting_user, path, factory):
    """``sort_by=name`` orders the whole set, in either direction."""
    a, home = await _workspace(session, acting_user)
    for name in ("Zulu", "alpha", "Mike"):
        await factory(session, home, a.user, name=name)

    ascending = await _names(client, a, path, sort_by="name")
    descending = await _names(client, a, path, sort_by="name", sort_dir="desc")

    # Case-insensitively, or "alpha" would sort after "Zulu".
    assert ascending == ["alpha", "Mike", "Zulu"]
    assert descending == ["Zulu", "Mike", "alpha"]


@pytest.mark.parametrize("path,factory", TOOL_LISTS)
async def test_sort_by_initiative(
    client: AsyncClient, session, acting_user, path, factory
):
    """``sort_by=initiative`` orders by the initiative's *name* — the column
    the table shows — not by its id."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    # Made in the opposite order to their names, so an id ordering would fail.
    zebra = await create_initiative(
        session, a.guild, a.user, name="Zebra", **ALL_TOOLS_ON
    )
    aardvark = await create_initiative(
        session, a.guild, a.user, name="Aardvark", **ALL_TOOLS_ON
    )
    await factory(session, zebra, a.user, name="In Zebra")
    await factory(session, aardvark, a.user, name="In Aardvark")

    ascending = await _names(client, a, path, sort_by="initiative")
    descending = await _names(client, a, path, sort_by="initiative", sort_dir="desc")

    assert ascending == ["In Aardvark", "In Zebra"]
    assert descending == ["In Zebra", "In Aardvark"]


@pytest.mark.parametrize("path,factory", TOOL_LISTS)
async def test_sort_by_last_updated(
    client: AsyncClient, session, acting_user, path, factory
):
    """``sort_by=updated_at&sort_dir=desc`` is what the guild home asks for by
    default, so it has to mean most-recently-touched first everywhere."""
    a, home = await _workspace(session, acting_user)
    now = datetime.now(UTC)
    await factory(
        session, home, a.user, name="Stale", updated_at=now - timedelta(days=3)
    )
    await factory(session, home, a.user, name="Fresh", updated_at=now)
    await factory(
        session, home, a.user, name="Middling", updated_at=now - timedelta(days=1)
    )

    newest_first = await _names(client, a, path, sort_by="updated_at", sort_dir="desc")
    oldest_first = await _names(client, a, path, sort_by="updated_at", sort_dir="asc")

    assert newest_first == ["Fresh", "Middling", "Stale"]
    assert oldest_first == ["Stale", "Middling", "Fresh"]


@pytest.mark.parametrize("path,factory", TOOL_LISTS)
async def test_unknown_sort_falls_back_to_the_tool_default(
    client: AsyncClient, session, acting_user, path, factory
):
    """A sort field nobody offers is ignored, not an error — the list still
    answers in the tool's own order rather than failing the page."""
    a, home = await _workspace(session, acting_user)
    await factory(session, home, a.user, name="Only One")

    names = await _names(client, a, path, sort_by="whatever", sort_dir="sideways")

    assert names == ["Only One"]
