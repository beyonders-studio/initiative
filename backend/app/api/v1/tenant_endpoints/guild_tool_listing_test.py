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
from httpx2 import AsyncClient

from app.models.platform.guild import CommunityRole
from app.testing import (
    create_calendar,
    create_dashboard,
    create_file,
    create_initiative,
    create_project,
    create_wiki,
)

# Every tool the guild home can show: its list path, and the factory that
# makes one row of it. Each factory takes (session, initiative, creator) and a
# ``name``, which is all these tests need to tell rows apart.
TOOL_LISTS = [
    pytest.param("/projects/", create_project, id="projects"),
    pytest.param("/files/", create_file, id="files"),
    pytest.param("/wikis/", create_wiki, id="wikis"),
    pytest.param("/calendars/", create_calendar, id="calendars"),
    pytest.param("/dashboards/", create_dashboard, id="dashboards"),
]


async def _names(client: AsyncClient, actor, path: str, **params) -> list[str]:
    """The names a list endpoint answers with, in the order it answers."""
    response = await client.get(actor.g(path), headers=actor.headers, params=params)
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()["items"]]


@pytest.mark.parametrize("path,factory", TOOL_LISTS)
async def test_search_and_sort_answer_over_the_whole_set(
    client: AsyncClient, session, acting_user, path, factory
):
    """``search`` is a case-insensitive substring of the name, and it counts.
    ``sort_by=name`` orders case-insensitively, ``initiative`` by the
    initiative's *name* — the column the table shows — not its id, and
    ``updated_at`` (``desc`` is the guild home's default) most-recently-touched
    first. A sort field nobody offers is ignored, not an error."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    # Made in the opposite order to their names, so an id ordering would fail.
    zebra = await create_initiative(session, a.guild, a.user, name="Zebra")
    aardvark = await create_initiative(session, a.guild, a.user, name="Aardvark")
    now = datetime.now(UTC)
    # Each ordering below differs from the others.
    for name, initiative, age in (
        ("Zulu", zebra, 1),
        ("alpha", zebra, 3),
        ("Mike", aardvark, 0),
    ):
        await factory(
            session, initiative, a.user, name=name, updated_at=now - timedelta(days=age)
        )

    response = await client.get(a.g(path), headers=a.headers, params={"search": "zUL"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Zulu"]
    # The count is of what matched, not of what the guild holds — the pager
    # below the table reads it.
    assert body["total_count"] == 1

    assert await _names(client, a, path, sort_by="name") == ["alpha", "Mike", "Zulu"]
    assert await _names(client, a, path, sort_by="name", sort_dir="desc") == [
        "Zulu",
        "Mike",
        "alpha",
    ]
    assert (await _names(client, a, path, sort_by="initiative"))[0] == "Mike"
    assert (await _names(client, a, path, sort_by="initiative", sort_dir="desc"))[
        -1
    ] == "Mike"
    assert await _names(client, a, path, sort_by="updated_at", sort_dir="desc") == [
        "Mike",
        "Zulu",
        "alpha",
    ]
    assert await _names(client, a, path, sort_by="updated_at", sort_dir="asc") == [
        "alpha",
        "Zulu",
        "Mike",
    ]
    names = await _names(client, a, path, sort_by="whatever", sort_dir="sideways")
    assert sorted(names) == ["Mike", "Zulu", "alpha"]
