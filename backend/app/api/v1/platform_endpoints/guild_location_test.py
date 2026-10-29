"""A community's location: set by its admin, read by its members and the
directory.

``PATCH /api/v1/communities/{guild_id}`` replaces the whole location; omitting
it leaves it alone and ``null`` clears it.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.services.platform import rules
from app.testing.factories import create_guild


async def _admin(session: AsyncSession, acting_user):
    guild = await create_guild(session, name="Queen Anne Gardeners")
    admin = await acting_user(guild_role=CommunityRole.admin, guild=guild)
    return guild, admin


async def _patch(client: AsyncClient, guild_id: int, headers: dict, body: dict):
    return await client.patch(
        f"/api/v1/communities/{guild_id}", json=body, headers=headers
    )


async def test_a_guild_starts_with_no_location(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)

    response = await client.get("/api/v1/communities/", headers=admin.headers)

    assert response.status_code == 200
    [read] = [item for item in response.json() if item["id"] == guild.id]
    assert read["location"] is None


async def test_a_country_alone_is_a_location(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)

    response = await _patch(
        client,
        guild.id,
        admin.headers,
        {"location": {"text": "Japan", "country": "jp"}},
    )

    assert response.status_code == 200, response.text
    await session.refresh(guild)
    # Stored upper case, and with only the parts that were given.
    assert guild.location == {"text": "Japan", "country": "JP"}
    assert response.json()["location"] == {
        "text": "Japan",
        "label": None,
        "country": "JP",
        "latitude": None,
        "longitude": None,
    }


async def test_an_exact_address_is_stored_tidied(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)

    response = await _patch(
        client,
        guild.id,
        admin.headers,
        {
            "location": {
                "text": "  Booth #4, 1 Queen  Anne Ave N, Seattle, WA 98109 ",
                "label": " Queen Anne  Neighborhood ",
                "country": "us",
                "latitude": 47.60621,
                "longitude": -122.33207,
            }
        },
    )

    assert response.status_code == 200, response.text
    await session.refresh(guild)
    assert guild.location == {
        "text": "Booth #4, 1 Queen Anne Ave N, Seattle, WA 98109",
        "label": "Queen Anne Neighborhood",
        "country": "US",
        "latitude": 47.60621,
        "longitude": -122.33207,
    }

    # Text nobody pinned is a location too: it just sorts nowhere.
    unplaced = await _patch(
        client, guild.id, admin.headers, {"location": {"text": "The old mill"}}
    )
    assert unplaced.status_code == 200, unplaced.text
    await session.refresh(guild)
    assert guild.location == {"text": "The old mill"}


async def test_omitting_the_location_leaves_it_and_null_clears_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, admin = await _admin(session, acting_user)
    await _patch(
        client,
        guild.id,
        admin.headers,
        {"location": {"text": "Toronto", "country": "CA"}},
    )

    renamed = await _patch(client, guild.id, admin.headers, {"name": "Gardeners"})
    assert renamed.status_code == 200, renamed.text
    await session.refresh(guild)
    assert guild.location == {"text": "Toronto", "country": "CA"}

    cleared = await _patch(client, guild.id, admin.headers, {"location": None})
    assert cleared.status_code == 200, cleared.text
    await session.refresh(guild)
    assert guild.location is None
    assert cleared.json()["location"] is None


@pytest.mark.parametrize(
    "location",
    [
        {"country": "US"},
        {"text": "   "},
        {"text": "x" * 201},
        {"text": "Japan", "country": "JPN"},
        {"text": "Japan", "country": "1A"},
        {"text": "Seattle", "country": "US", "latitude": 47.6},
        {"text": "Seattle", "latitude": 47.6, "longitude": -122.3},
        {"text": "Seattle", "country": "US", "latitude": 91, "longitude": 0},
        {"text": "Seattle", "label": "x" * 61},
        {"text": "Seattle", "label": "Booth #4"},
    ],
    ids=[
        "no text",
        "blank",
        "too long",
        "three letters",
        "not letters",
        "half a point",
        "point without country",
        "off the globe",
        "label too long",
        "label sigil",
    ],
)
async def test_a_malformed_location_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, location: dict
):
    guild, admin = await _admin(session, acting_user)

    response = await _patch(client, guild.id, admin.headers, {"location": location})

    assert response.status_code == 422
    await session.refresh(guild)
    assert guild.location is None


async def test_a_member_cannot_set_the_location(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild = await create_guild(session, name="Queen Anne Gardeners")
    member = await acting_user(guild_role=CommunityRole.member, guild=guild)

    response = await _patch(
        client, guild.id, member.headers, {"location": {"text": "US"}}
    )

    assert response.status_code == 403
    await session.refresh(guild)
    assert guild.location is None


async def test_members_and_the_directory_read_the_location(
    client: AsyncClient, session: AsyncSession, acting_user
):
    await rules.put(session, "community_directory_enabled", True)
    await session.commit()
    guild = await create_guild(
        session,
        name="Queen Anne Gardeners",
        location={"text": "Seattle, WA", "country": "US"},
    )
    member = await acting_user(guild_role=CommunityRole.member, guild=guild)
    guild.is_community = True
    guild.categories = ["other"]
    guild.has_adult_content = False
    session.add(guild)
    await session.commit()

    mine = await client.get("/api/v1/communities/", headers=member.headers)
    [read] = [item for item in mine.json() if item["id"] == guild.id]
    assert read["location"]["text"] == "Seattle, WA"

    browser = await acting_user("member")
    directory = await client.get(
        "/api/v1/communities/directory", headers=browser.headers
    )
    [card] = [item for item in directory.json()["items"] if item["id"] == guild.id]
    assert card["location"]["country"] == "US"


# ---------------------------------------------------------------------------
# Searching the directory by location
# ---------------------------------------------------------------------------


async def _listed_at(session: AsyncSession, name: str, location: dict | None):
    guild = await create_guild(session, name=name, location=location)
    guild.is_community = True
    guild.categories = ["other"]
    guild.has_adult_content = False
    session.add(guild)
    await session.commit()
    return guild


async def _directory_names(client: AsyncClient, headers: dict, **params) -> set[str]:
    response = await client.get(
        "/api/v1/communities/directory", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    return {item["name"] for item in response.json()["items"]}


@pytest.fixture
async def located_directory(session: AsyncSession):
    await rules.put(session, "community_directory_enabled", True)
    await session.commit()
    await _listed_at(
        session,
        "Gardeners",
        {
            "text": "Seattle, Washington 98109",
            "label": "Queen Anne Neighborhood",
            "country": "US",
            "latitude": 47.6062,
            "longitude": -122.3321,
        },
    )
    await _listed_at(session, "Go Club", {"text": "Kyoto", "country": "JP"})
    await _listed_at(session, "Choir", None)


@pytest.mark.parametrize(
    "params,expected",
    [
        ({"search": "seattle"}, {"Gardeners"}),
        ({"search": "Queen Anne"}, {"Gardeners"}),
        ({"search": "washington"}, {"Gardeners"}),
        ({"search": "98109"}, {"Gardeners"}),
        ({"search": "kyoto"}, {"Go Club"}),
        # A country is stored as a code: the client names the codes the
        # search text means, and either is enough.
        ({"search": "Japan", "search_country": ["jp"]}, {"Go Club"}),
        ({"search": "Japan"}, set()),
        # A malformed code is ignored rather than refused.
        ({"search": "Japan", "search_country": ["japan"]}, set()),
    ],
)
async def test_the_directory_searches_where_a_community_is(
    client: AsyncClient,
    acting_user,
    located_directory,
    params: dict,
    expected: set[str],
):
    browser = await acting_user("member")

    assert await _directory_names(client, browser.headers, **params) == expected


async def test_a_country_alone_does_not_filter_without_a_search(
    client: AsyncClient, acting_user, located_directory
):
    """``search_country`` widens a search; it is not a filter of its own."""
    browser = await acting_user("member")

    names = await _directory_names(client, browser.headers, search_country=["JP"])

    assert names == {"Gardeners", "Go Club", "Choir"}


# ---------------------------------------------------------------------------
# Putting the communities near the reader first
# ---------------------------------------------------------------------------


async def _directory_order(client: AsyncClient, headers: dict, **params) -> list[str]:
    response = await client.get(
        "/api/v1/communities/directory", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    return [item["name"] for item in response.json()["items"]]


@pytest.fixture
async def spread_directory(session: AsyncSession):
    await rules.put(session, "community_directory_enabled", True)
    await session.commit()
    places = {
        "Kyoto Go": {
            "text": "Kyoto",
            "country": "JP",
            "latitude": 35.0116,
            "longitude": 135.7681,
        },
        "Nowhere Choir": None,
        # Said where, but never pinned.
        "Mill Knitters": {"text": "The old mill"},
        "Austin Rodeo": {
            "text": "Austin, Texas",
            "country": "US",
            "latitude": 30.2672,
            "longitude": -97.7431,
        },
        # A country alone: no point to measure from.
        "Texans": {"text": "Texas", "country": "US"},
        "Ann Arbor Chess": {
            "text": "Ann Arbor, Michigan",
            "country": "US",
            "latitude": 42.2808,
            "longitude": -83.7430,
        },
        # Across the river from Detroit: another country, and still nearby.
        "Windsor Rowers": {
            "text": "Windsor, Ontario",
            "country": "CA",
            "latitude": 42.3149,
            "longitude": -83.0364,
        },
        "Detroit Makers": {
            "text": "Detroit, Michigan",
            "country": "US",
            "latitude": 42.3314,
            "longitude": -83.0458,
        },
    }
    for name, location in places.items():
        await _listed_at(session, name, location)


async def test_the_nearest_communities_come_first(
    client: AsyncClient, acting_user, spread_directory
):
    browser = await acting_user("member")

    order = await _directory_order(
        client,
        browser.headers,
        near_country="us",
        near_lat=42.33,
        near_lon=-83.05,
    )

    # Nearby, closest first, either side of the border; then the rest of the
    # country, a point before none; then nowhere in particular; then abroad.
    assert order[:5] == [
        "Detroit Makers",
        "Windsor Rowers",
        "Ann Arbor Chess",
        "Austin Rodeo",
        "Texans",
    ]
    assert set(order[5:7]) == {"Nowhere Choir", "Mill Knitters"}
    assert order[7:] == ["Kyoto Go"]


async def test_a_country_alone_puts_that_country_first(
    client: AsyncClient, acting_user, spread_directory
):
    browser = await acting_user("member")

    order = await _directory_order(client, browser.headers, near_country="JP")

    assert order[0] == "Kyoto Go"
    assert set(order[1:3]) == {"Nowhere Choir", "Mill Knitters"}


async def test_near_reorders_without_narrowing(
    client: AsyncClient, acting_user, spread_directory
):
    browser = await acting_user("member")

    near = await _directory_order(client, browser.headers, near_country="JP")
    anywhere = await _directory_order(client, browser.headers)

    assert sorted(near) == sorted(anywhere)
