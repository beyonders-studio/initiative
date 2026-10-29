"""Integration tests for the community directory.

Covers the two endpoints a guild's opt-in unlocks —
``GET /api/v1/communities/directory`` (browse) and
``POST /api/v1/communities/directory/{community_id}/join`` (join without an invite) —
plus the guild-admin PATCH that sets the opt-in and its categories.
"""

from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import (
    Guild,
    GuildMembership,
    CommunityRole,
    CommunityStatus,
)
from app.models.platform.user import User, UserRole, UserStatus
from app.models.tenant.initiative import InitiativeMember
from app.services.platform import rules
from app.services.platform import guilds as guilds_service
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_resource_grant,
    create_user,
    guild_administration,
)
from app.testing.schema_harness import route_session_to_guild


@pytest.fixture(autouse=True)
async def community_directory_on(session: AsyncSession) -> None:
    """Run the directory for this module.

    The switch is a platform-owner setting that starts off, so every test below
    would otherwise be testing a deployment with no directory. Stated once here
    instead of in each test; the tests about the switch itself set it
    themselves.
    """
    await rules.put(session, "community_directory_enabled", True)
    await session.commit()


async def _list_as_community(
    session: AsyncSession,
    guild: Guild,
    *,
    categories: list[str] | None = None,
) -> Guild:
    """Opt a guild into the directory directly, without the settings page.

    A listed guild is always on a shelf and always declared free of adult
    content — the database refuses to store one that is not — so the default
    category keeps every test that does not care about shelves valid.
    """
    guild.is_community = True
    guild.categories = categories or ["other"]
    guild.has_adult_content = False
    session.add(guild)
    await session.commit()
    await session.refresh(guild)
    return guild


async def _a_listed_guild(
    session: AsyncSession, *, categories: list[str] | None = None, **guild_fields
) -> Guild:
    """A guild that has opted into the directory."""
    return await _list_as_community(
        session, await create_guild(session, **guild_fields), categories=categories
    )


async def _admin_of(session: AsyncSession, acting_user, **guild_fields):
    """A guild plus the headers of one of its admins."""
    guild = await create_guild(session, **guild_fields)
    admin = await acting_user(guild_role=CommunityRole.admin, guild=guild)
    return guild, admin.headers


async def _membership_of(
    session: AsyncSession, *, guild: Guild, user_id: int
) -> GuildMembership | None:
    return (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == user_id,
            )
        )
    ).one_or_none()


async def test_directory_lists_only_opted_in_guilds(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild appears only once it has opted in — invite-only guilds do not."""
    browser = await acting_user("member")
    await _a_listed_guild(session, name="Open Table")
    await create_guild(session, name="Private Office")

    response = await client.get(
        "/api/v1/communities/directory", headers=browser.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_count"] == 1
    assert [item["name"] for item in data["items"]] == ["Open Table"]


@pytest.mark.parametrize(
    "condition",
    ["suspended", "frozen", "one seat"],
)
async def test_the_directory_re_checks_a_listed_guild_before_offering_it(
    client: AsyncClient, session: AsyncSession, acting_user, condition: str
):
    """The opt-in is not the last word. A frozen or suspended guild takes no
    new members, and neither does one whose operator-set cap leaves no seat for
    a joiner — the cap can be lowered long after the listing was made."""
    browser = await acting_user("member")
    guild = await _a_listed_guild(session, name="Open Table")
    if condition == "one seat":
        await guild_administration(session, guild, max_users=1)
    else:
        guild.status = (
            CommunityStatus.suspended.value
            if condition == "suspended"
            else CommunityStatus.read_only.value
        )
        session.add(guild)
        await session.commit()

    response = await client.get(
        "/api/v1/communities/directory", headers=browser.headers
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["total_count"] == 0


async def test_directory_card_carries_only_published_fields(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The card is what the guild published, plus its roster size — no more."""
    browser = await acting_user("member")
    guild = await create_guild(
        session, name="Riverside Players", description="Community theatre."
    )
    await acting_user(guild_role=CommunityRole.member, guild=guild)
    await _list_as_community(session, guild, categories=["art", "writing"])

    response = await client.get(
        "/api/v1/communities/directory", headers=browser.headers
    )

    card = response.json()["items"][0]
    assert card["name"] == "Riverside Players"
    assert card["description"] == "Community theatre."
    assert card["categories"] == ["art", "writing"]
    assert card["member_count"] == 1
    assert card["already_member"] is False
    # Nothing about the guild's administration or lifecycle reaches a stranger.
    assert "status" not in card
    assert "tier_name" not in card
    assert "max_users" not in card
    assert "role" not in card


async def test_directory_flags_guilds_the_caller_is_already_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    joined = await _a_listed_guild(session, name="Open Table")
    browser = await acting_user(guild_role=CommunityRole.member, guild=joined)
    await _a_listed_guild(session, name="Somewhere Else")

    response = await client.get(
        "/api/v1/communities/directory", headers=browser.headers
    )

    assert {
        item["name"]: item["already_member"] for item in response.json()["items"]
    } == {
        "Open Table": True,
        "Somewhere Else": False,
    }


@pytest.mark.parametrize(
    "query,expected_status,expected_names",
    [
        pytest.param(
            "?category=ttrpg",
            200,
            ["Dice Goblins", "Painted Minis"],
            id="a shelf, reaching a guild that is on two of them",
        ),
        pytest.param(
            "?category=art&category=ttrpg",
            200,
            ["Dice Goblins", "Life Drawing", "Painted Minis"],
            id="two shelves, reaching a guild on either",
        ),
        pytest.param(
            "?search=dice",
            200,
            ["Dice Goblins", "Painted Minis"],
            id="a word, matched in a name and in a description",
        ),
        pytest.param("?category=nonsense", 422, None, id="a shelf nobody stocks"),
    ],
)
async def test_the_directory_narrows_to_what_was_asked_for(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    query: str,
    expected_status: int,
    expected_names: list[str] | None,
):
    """A shelf or a word narrows the directory to the guilds that match it, and
    a shelf that is not one of the published ones is not a narrowing at all."""
    browser = await acting_user("member")
    await _a_listed_guild(session, name="Dice Goblins", categories=["ttrpg"])
    await _a_listed_guild(session, name="Life Drawing", categories=["art"])
    await _a_listed_guild(
        session,
        name="Painted Minis",
        categories=["art", "ttrpg"],
        description="We paint dice trays too.",
    )

    response = await client.get(
        f"/api/v1/communities/directory{query}", headers=browser.headers
    )

    assert response.status_code == expected_status
    if expected_names is not None:
        assert sorted(item["name"] for item in response.json()["items"]) == (
            expected_names
        )


async def test_directory_lists_the_busiest_guilds_first(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Who is already in a guild is what someone with none is choosing between."""
    browser = await acting_user("member")
    # Named against the order they belong in, so an alphabetical sort cannot
    # pass this by accident.
    await _a_listed_guild(session, name="Aardvark Club")
    busy = await _a_listed_guild(session, name="Zebra Hall")
    for _ in range(3):
        await acting_user(guild_role=CommunityRole.member, guild=busy)

    response = await client.get(
        "/api/v1/communities/directory", headers=browser.headers
    )

    items = response.json()["items"]
    assert [item["name"] for item in items] == ["Zebra Hall", "Aardvark Club"]
    assert [item["member_count"] for item in items] == [3, 0]


async def test_directory_searches_every_guild_not_only_a_loaded_page(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The search is the query's, not the caller's.

    The match is the quietest guild here and the page holds one guild, so it is
    on no page a browser would have loaded by the time it searched.
    """
    browser = await acting_user("member")
    busy = await _a_listed_guild(session, name="Crowded Hall")
    for _ in range(3):
        await acting_user(guild_role=CommunityRole.member, guild=busy)
    await _a_listed_guild(session, name="Dice Goblins")

    response = await client.get(
        "/api/v1/communities/directory?search=goblins&page_size=1",
        headers=browser.headers,
    )

    body = response.json()
    assert [item["name"] for item in body["items"]] == ["Dice Goblins"]
    assert body["total_count"] == 1


async def test_directory_paginates(
    client: AsyncClient, session: AsyncSession, acting_user
):
    browser = await acting_user("member")
    for index in range(3):
        await _a_listed_guild(session, name=f"Guild {index}")

    first = await client.get(
        "/api/v1/communities/directory?page=1&page_size=2", headers=browser.headers
    )
    second = await client.get(
        "/api/v1/communities/directory?page=2&page_size=2", headers=browser.headers
    )

    # The total counts everything that matched, not just this page.
    assert first.json()["total_count"] == 3
    assert len(first.json()["items"]) == 2
    assert first.json()["has_next"] is True
    assert len(second.json()["items"]) == 1
    assert second.json()["has_next"] is False


async def test_directory_requires_authentication(client: AsyncClient):
    response = await client.get("/api/v1/communities/directory")

    assert response.status_code == 401


async def test_joining_a_listed_guild_needs_no_invite_and_repeats_harmlessly(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The listing is the authorization, and joining twice returns the guild
    rather than erroring or seating the same person twice."""
    joiner = await acting_user("member")
    guild = await _a_listed_guild(session, name="Open Table")
    url = f"/api/v1/communities/directory/{guild.id}/join"

    first = await client.post(url, headers=joiner.headers)
    second = await client.post(url, headers=joiner.headers)

    assert first.status_code == 200
    assert first.json()["id"] == guild.id
    assert first.json()["role"] == CommunityRole.member.value
    assert second.status_code == 200
    memberships = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.user_id == joiner.user.id,
            )
        )
    ).all()
    assert [m.role for m in memberships] == [CommunityRole.member]


@pytest.mark.parametrize(
    "condition,expected_detail",
    [
        pytest.param("never listed", "COMMUNITY_NOT_A_COMMUNITY", id="never listed"),
        pytest.param("suspended", "COMMUNITY_NOT_A_COMMUNITY", id="suspended"),
        pytest.param("one seat", "COMMUNITY_NOT_A_COMMUNITY", id="one seat"),
        pytest.param("no such guild", "COMMUNITY_NOT_FOUND", id="no such guild"),
    ],
)
async def test_a_guild_the_directory_would_not_show_cannot_be_joined(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    condition: str,
    expected_detail: str,
):
    """A join by id applies the directory's own filter, and an unlisted guild
    has published nothing — its id included. Only an id that names no guild at
    all is answered as a missing guild."""
    joiner = await acting_user("member")
    if condition == "never listed":
        guild = await create_guild(session, name="Private Office")
    else:
        guild = await _a_listed_guild(session, name="Open Table")
        if condition == "suspended":
            guild.status = CommunityStatus.suspended.value
            session.add(guild)
            await session.commit()
        elif condition == "one seat":
            await guild_administration(session, guild, max_users=1)

    guild_id = 999999 if condition == "no such guild" else guild.id
    response = await client.post(
        f"/api/v1/communities/directory/{guild_id}/join", headers=joiner.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == expected_detail
    if condition != "no such guild":
        assert (
            await _membership_of(session, guild=guild, user_id=joiner.user.id) is None
        )


async def test_join_respects_the_member_cap(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The directory does not bypass the guild's operator-set seat limit.

    Two seats, both taken: a listable guild (one seat could never admit anyone,
    so it would be refused as unlisted instead) that happens to be full today.
    """
    joiner = await acting_user("member")
    guild = await _a_listed_guild(session, name="Open Table")
    for _ in range(2):
        await acting_user(guild_role=CommunityRole.member, guild=guild)
    await guild_administration(session, guild, max_users=2)

    response = await client.post(
        f"/api/v1/communities/directory/{guild.id}/join", headers=joiner.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_USER_LIMIT_REACHED"


async def test_a_member_cannot_opt_the_guild_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild = await create_guild(session, name="Open Table")
    member = await acting_user(guild_role=CommunityRole.member, guild=guild)

    response = await client.patch(
        f"/api/v1/communities/{guild.id}",
        json={"is_community": True},
        headers=member.headers,
    )

    assert response.status_code == 403
    await session.refresh(guild)
    assert guild.is_community is False


async def test_an_unknown_category_is_rejected(
    client: AsyncClient, session: AsyncSession, acting_user
):
    guild, headers = await _admin_of(session, acting_user, name="Open Table")

    response = await client.patch(
        f"/api/v1/communities/{guild.id}",
        json={"categories": ["underwater-basket-weaving"]},
        headers=headers,
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# What a guild must be before it can be listed
# ---------------------------------------------------------------------------


async def test_the_adult_content_declaration_starts_unanswered(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """It is a question only the directory asks, so an ordinary guild has no
    answer on file rather than a default one."""
    guild, headers = await _admin_of(session, acting_user)

    response = await client.get("/api/v1/communities/", headers=headers)

    assert response.status_code == 200
    entry = next(item for item in response.json() if item["id"] == guild.id)
    assert entry["has_adult_content"] is None
    assert entry["is_community"] is False


#: The listing rules, each as the PATCH that breaks it. ``guild_fields`` go to
#: the guild, ``listed_with`` puts it on the directory first (so the rule is
#: met from the other side), and the guild must come back unchanged.
REFUSED_LISTINGS = (
    pytest.param(
        {},
        None,
        {"is_community": True, "has_adult_content": False},
        "COMMUNITY_COMMUNITY_REQUIRES_CATEGORY",
        id="a card nobody could reach by browsing",
    ),
    pytest.param(
        {},
        None,
        {"is_community": True, "categories": ["art"]},
        "COMMUNITY_COMMUNITY_CONTENT_NOT_DECLARED",
        id="the content question left unanswered",
    ),
    pytest.param(
        {},
        None,
        {"is_community": True, "categories": ["art"], "has_adult_content": True},
        "COMMUNITY_COMMUNITY_ADULT_CONTENT",
        id="an adult guild",
    ),
    pytest.param(
        {"max_users": 1},
        None,
        {"is_community": True, "categories": ["art"], "has_adult_content": False},
        "COMMUNITY_COMMUNITY_REQUIRES_CAPACITY",
        id="one seat, so no joiner could ever take one",
    ),
    pytest.param(
        {},
        ["art"],
        {"categories": []},
        "COMMUNITY_COMMUNITY_REQUIRES_CATEGORY",
        id="a listed guild clearing its shelves",
    ),
    pytest.param(
        {},
        ["art"],
        {"has_adult_content": True},
        "COMMUNITY_COMMUNITY_ADULT_CONTENT",
        id="a listed guild turning itself adult",
    ),
)


@pytest.mark.parametrize(
    "guild_fields,listed_with,body,expected_detail", REFUSED_LISTINGS
)
async def test_a_listing_that_breaks_a_rule_is_refused_and_changes_nothing(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    guild_fields: dict,
    listed_with: list[str] | None,
    body: dict,
    expected_detail: str,
):
    """Every rule is about the guild the PATCH would leave behind, not about
    what this request happened to carry — so listing one that breaks it and
    breaking it on one already listed are refused the same way, and the stored
    guild is left exactly as it was."""
    guild, headers = await _admin_of(session, acting_user, **guild_fields)
    if listed_with is not None:
        await _list_as_community(session, guild, categories=listed_with)
    before = (guild.is_community, guild.categories, guild.has_adult_content)

    response = await client.patch(
        f"/api/v1/communities/{guild.id}", json=body, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail
    await session.refresh(guild)
    assert (guild.is_community, guild.categories, guild.has_adult_content) == before


#: The PATCHes the rules let through, each with what the guild must read back
#: as afterwards — in the reply and in the row.
ACCEPTED_LISTINGS = (
    pytest.param(
        {},
        None,
        {
            "is_community": True,
            "categories": ["gaming", "ttrpg"],
            "has_adult_content": False,
        },
        {
            "is_community": True,
            "categories": ["gaming", "ttrpg"],
            "has_adult_content": False,
        },
        id="opting in",
    ),
    pytest.param(
        {"max_users": 2},
        None,
        {"is_community": True, "categories": ["art"], "has_adult_content": False},
        {"is_community": True},
        id="two seats, room for one more",
    ),
    pytest.param(
        {},
        None,
        {"categories": ["ttrpg", "art", "ttrpg"]},
        {"categories": ["art", "ttrpg"]},
        id="categories deduplicated and ordered",
    ),
    pytest.param(
        {},
        None,
        {"has_adult_content": True},
        {"has_adult_content": True, "is_community": False},
        id="an unlisted guild declaring adult content",
    ),
    pytest.param(
        {},
        ["gaming"],
        {"name": "Open Table Renamed"},
        {"name": "Open Table Renamed", "is_community": True, "categories": ["gaming"]},
        id="a rename leaving the listing alone",
    ),
    pytest.param(
        {},
        ["art"],
        {"is_community": False, "categories": []},
        {"is_community": False},
        id="delisting, which asks nothing of the guild",
    ),
)


@pytest.mark.parametrize("guild_fields,listed_with,body,expected", ACCEPTED_LISTINGS)
async def test_an_accepted_listing_patch_is_stored_as_it_reads_back(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    guild_fields: dict,
    listed_with: list[str] | None,
    body: dict,
    expected: dict,
):
    """A guild admin sets its shelves, its content declaration and whether it
    is listed at all. Whatever order the boxes were ticked in, storage is
    canonical — and the reply says the same thing as the row."""
    guild, headers = await _admin_of(
        session, acting_user, name="Open Table", **guild_fields
    )
    if listed_with is not None:
        await _list_as_community(session, guild, categories=listed_with)

    response = await client.patch(
        f"/api/v1/communities/{guild.id}", json=body, headers=headers
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    await session.refresh(guild)
    for field, value in expected.items():
        assert payload[field] == value
        assert getattr(guild, field) == value


# ---------------------------------------------------------------------------
# The platform-owner switch
# ---------------------------------------------------------------------------


async def _switch_directory_off(session: AsyncSession) -> None:
    await rules.put(session, "community_directory_enabled", False)
    await session.commit()


@pytest.mark.parametrize("surface", ["browsing", "joining", "listing itself"])
async def test_every_directory_surface_is_refused_where_it_is_switched_off(
    client: AsyncClient, session: AsyncSession, acting_user, surface: str
):
    """Refused outright, not answered with an empty page: a deployment without a
    directory has no directory, as distinct from one where nobody has listed.
    The invite-free join and the opt-in are the directory's other halves, so
    they go the same way — and nothing moves on the way."""
    guild, admin_headers = await _admin_of(session, acting_user, name="Open Table")
    caller = await acting_user("member")
    listed = surface != "listing itself"
    if listed:
        await _list_as_community(session, guild)
    await _switch_directory_off(session)

    if surface == "browsing":
        response = await client.get(
            "/api/v1/communities/directory", headers=caller.headers
        )
    elif surface == "joining":
        response = await client.post(
            f"/api/v1/communities/directory/{guild.id}/join", headers=caller.headers
        )
    else:
        response = await client.patch(
            f"/api/v1/communities/{guild.id}",
            json={
                "is_community": True,
                "categories": ["gaming"],
                "has_adult_content": False,
            },
            headers=admin_headers,
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_DIRECTORY_DISABLED"
    assert await _membership_of(session, guild=guild, user_id=caller.user.id) is None
    await session.refresh(guild)
    assert guild.is_community is listed


async def test_a_listed_guild_can_still_unlist_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Switching the directory off must not strand a guild inside a listing it
    can no longer withdraw."""
    guild, headers = await _admin_of(session, acting_user, name="Open Table")
    await _list_as_community(session, guild)
    await _switch_directory_off(session)

    response = await client.patch(
        f"/api/v1/communities/{guild.id}",
        json={"is_community": False},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["is_community"] is False


async def test_switching_the_directory_off_keeps_the_guilds_opt_in(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Off hides the listings; it does not unpublish anybody. Switching it back
    on shows the same guilds."""
    browser = await acting_user("member")
    await _a_listed_guild(session, name="Open Table")
    await _switch_directory_off(session)
    await rules.put(session, "community_directory_enabled", True)
    await session.commit()

    response = await client.get(
        "/api/v1/communities/directory", headers=browser.headers
    )

    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["Open Table"]


# ============================================================================
# Auto-join enrolment on arrival (discovery §5)
# ============================================================================


async def _initiative_with_shared_project(
    session: AsyncSession, guild: Guild, owner, *, name: str, auto_join: bool
):
    """An initiative plus a project shared with everyone in it.

    Gate 4 is satisfied for any member, so initiative membership is the only
    thing that decides whether the project is reachable.
    """
    initiative = await create_initiative(
        session, guild, owner, name=name, join_policy="open", auto_join=auto_join
    )
    project = await create_project(session, initiative, owner, name=f"{name} work")
    await create_resource_grant(session, project, all_initiative_members=True)
    return initiative, project


async def test_community_join_enrols_in_auto_join_initiatives(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Joining a public guild lands the arrival in real content.

    The membership row is the only thing that moves, and RLS does the rest: the
    auto-join initiative's project is reachable the moment the join returns,
    while its opt-in sibling in the same guild stays hidden. Which initiatives
    qualify is settled in ``app/services/platform/guilds_test.py``; this is the
    endpoint reaching that enrolment at all.
    """
    owner = await create_user(session)
    guild = await _a_listed_guild(session, name="Open Table", creator=owner)
    welcome, welcome_project = await _initiative_with_shared_project(
        session, guild, owner, name="Welcome", auto_join=True
    )
    _optin, optin_project = await _initiative_with_shared_project(
        session, guild, owner, name="Opt in", auto_join=False
    )

    joiner = await acting_user("member")

    # Not in the guild yet: the guild gate refuses before RLS is ever consulted.
    before = await client.get(
        f"/api/v1/c/{guild.id}/projects/{welcome_project.id}", headers=joiner.headers
    )
    assert before.status_code == 403

    response = await client.post(
        f"/api/v1/communities/directory/{guild.id}/join", headers=joiner.headers
    )
    assert response.status_code == 200

    after = await client.get(
        f"/api/v1/c/{guild.id}/projects/{welcome_project.id}", headers=joiner.headers
    )
    assert after.status_code == 200
    assert after.json()["name"] == "Welcome work"

    # The initiative that did not ask for arrivals is still hidden — so the
    # enrolment, not plain guild membership, is what opened the first one.
    sibling = await client.get(
        f"/api/v1/c/{guild.id}/projects/{optin_project.id}", headers=joiner.headers
    )
    assert sibling.status_code == 404

    await route_session_to_guild(session, guild.id)
    rows = (
        await session.exec(
            select(InitiativeMember).where(InitiativeMember.user_id == joiner.user.id)
        )
    ).all()
    assert [row.initiative_id for row in rows] == [welcome.id]
    assert rows[0].oidc_provider_id is None


async def test_a_profile_names_only_the_listed_communities(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A profile says which shelves someone is on, and nothing about the
    guilds they are in that never opted onto one. The count of who is there
    comes from asking — nothing about a guild row carries it."""
    listed = await _a_listed_guild(session)
    private = await create_guild(session)
    subject = await acting_user(
        guild_role=CommunityRole.member, guild=listed, username="tinker"
    )
    await create_guild_membership(session, user=subject.user, guild=private)
    reader = await acting_user(guild_role=CommunityRole.member, guild=listed)

    response = await client.get(
        f"/api/v1/users/{subject.user.username}{subject.user.discriminator:04d}/communities",
        headers=reader.headers,
    )

    assert response.status_code == 200
    assert [row["name"] for row in response.json()] == [listed.name]
    # The subject and the reader, at least.
    assert response.json()[0]["member_count"] >= 2


async def test_a_profile_names_no_communities_where_the_directory_is_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Nothing is published on a deployment that publishes nothing."""
    listed = await _a_listed_guild(session)
    subject = await acting_user(
        guild_role=CommunityRole.member, guild=listed, username="tinker"
    )
    reader = await acting_user("member")
    await _switch_directory_off(session)

    response = await client.get(
        f"/api/v1/users/{subject.user.username}{subject.user.discriminator:04d}/communities",
        headers=reader.headers,
    )

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# The age gate: who is asked, who is not, and what the answer is worth.
# ---------------------------------------------------------------------------


def _birthdate_for_age(years: int) -> str:
    """A date somebody of this age could have been born on, as ISO text."""
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    return today.replace(year=today.year - years).isoformat()


def _birthdate_days_before_turning(years: int, days: int) -> str:
    """A date that is ``days`` short of a ``years``-th birthday."""
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    return (today.replace(year=today.year - years) + timedelta(days=days)).isoformat()


def _tomorrow() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()


#: Comfortably past the minimum, for the tests that are not about the boundary.
ADULT_BIRTHDATE = _birthdate_for_age(30)


# The dates are passed as callables rather than values: a parametrize list is
# built at collection, which in a full run is up to an hour before the request
# it describes. Two of these sit exactly on a day boundary, so a UTC midnight
# in between turned "sixteen tomorrow" into sixteen today and "a date still to
# come" into today. Computing each one in the body closes that window.
@pytest.mark.parametrize(
    "make_birthdate,expected_status,expected_detail",
    [
        pytest.param(lambda: ADULT_BIRTHDATE, 200, None, id="an adult"),
        pytest.param(
            lambda: _birthdate_for_age(16),
            200,
            None,
            id="sixteen today, on the boundary",
        ),
        pytest.param(
            lambda: _birthdate_days_before_turning(16, 1),
            422,
            "USER_AGE_BELOW_MINIMUM",
            id="sixteen tomorrow, so fifteen today",
        ),
        pytest.param(
            lambda: _birthdate_for_age(14), 422, "USER_AGE_BELOW_MINIMUM", id="fourteen"
        ),
        pytest.param(
            _tomorrow, 422, "USER_AGE_INVALID_BIRTHDATE", id="a date still to come"
        ),
        pytest.param(
            lambda: _birthdate_for_age(200),
            422,
            "USER_AGE_INVALID_BIRTHDATE",
            id="a date nobody was born on",
        ),
    ],
)
async def test_the_age_a_birthdate_states_is_what_the_answer_turns_on(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    make_birthdate: Callable[[], str],
    expected_status: int,
    expected_detail: str | None,
):
    """The boundary belongs to the person on it: sixteen today is sixteen, and
    a birthday that has not come round is a year that has not happened. A date
    nobody could have been born on is refused separately, so the reply says
    which it was.

    Answered from the US, where thirteen is old enough for an account: under
    sixteen is then an account without a directory, which is what these
    assert. Where the country is not known the highest minimum applies and
    the same answers close the account instead — the tests at the end."""
    a = await acting_user("member", age_confirmed_at=None)
    birthdate = make_birthdate()

    response = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": birthdate},
        headers={**a.headers, "CF-IPCountry": "US"},
    )

    assert response.status_code == expected_status, response.text
    await session.refresh(a.user)
    if expected_detail is None:
        assert response.json()["age_confirmed_at"] is not None
        assert a.user.age_confirmed_at is not None
    else:
        assert response.json()["detail"] == expected_detail
        assert a.user.age_confirmed_at is None


@pytest.mark.parametrize(
    "prior_answer,expected_detail",
    [
        pytest.param(
            "never asked", "COMMUNITY_AGE_CONFIRMATION_REQUIRED", id="never answered"
        ),
        pytest.param(
            "answered under age", "COMMUNITY_AGE_BELOW_MINIMUM", id="answered under age"
        ),
    ],
)
async def test_join_refuses_an_account_that_has_not_confirmed_its_age(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    prior_answer: str,
    expected_detail: str,
):
    """Both are refused, and the two are told apart.

    One of them can be fixed by answering and the other cannot, and the reply
    is the only thing that knows which — so an account whose answer stands is
    not sent back to a form that has nothing for it.

    The under-age answer is fifteen from the US: old enough for an account
    there, so the account survives to be refused by the directory.
    """
    a = await acting_user("member", age_confirmed_at=None)
    guild = await _a_listed_guild(session, name="Open Table")
    if prior_answer == "answered under age":
        answered = await client.post(
            "/api/v1/me/age-confirmation",
            json={"birthdate": _birthdate_for_age(15)},
            headers={**a.headers, "CF-IPCountry": "US"},
        )
        assert answered.status_code == 422, answered.text

    response = await client.post(
        f"/api/v1/communities/directory/{guild.id}/join", headers=a.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == expected_detail
    assert await _membership_of(session, guild=guild, user_id=a.user.id) is None


async def test_confirming_age_lets_the_same_account_join(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The whole loop: refused, tick the box, join."""
    a = await acting_user("member", age_confirmed_at=None)
    guild = await _a_listed_guild(session, name="Open Table")

    refused = await client.post(
        f"/api/v1/communities/directory/{guild.id}/join", headers=a.headers
    )
    assert refused.status_code == 403

    confirmed = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=a.headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["age_confirmed_at"] is not None

    joined = await client.post(
        f"/api/v1/communities/directory/{guild.id}/join", headers=a.headers
    )
    assert joined.status_code == 200
    assert joined.json()["id"] == guild.id


async def test_join_allows_an_unconfirmed_account_when_the_gate_is_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An owner who asserts every account here is an adult is not asking."""
    await rules.put(session, "community_directory_enabled", True)
    await rules.put(session, "community_age_gate_enabled", False)
    await session.commit()
    a = await acting_user("member", age_confirmed_at=None)
    guild = await _a_listed_guild(session, name="Open Table")

    response = await client.post(
        f"/api/v1/communities/directory/{guild.id}/join", headers=a.headers
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "listed",
    [
        pytest.param(True, id="a member of a listed guild"),
        pytest.param(False, id="a member of a private guild"),
    ],
)
async def test_belonging_somewhere_never_holds_an_unanswered_account_up(
    client: AsyncClient, session: AsyncSession, acting_user, listed: bool
):
    """Being a member is not the question; joining from the directory is.

    A membership arrives by ways that had nobody at a keyboard to ask — an
    invite, a group sync, an admin adding somebody, or a guild that listed
    itself long after they joined it. None of them is the account walking into
    a room full of strangers on its own, and none of them is undone by an
    unanswered question, so the platform asks it nothing and hands back an
    account it can use.
    """
    guild = (
        await _a_listed_guild(session, name="Open Table")
        if listed
        else await create_guild(session, name="Just Us")
    )
    a = await acting_user(
        guild_role=CommunityRole.member, guild=guild, age_confirmed_at=None
    )

    response = await client.get("/api/v1/me", headers=a.headers)

    assert response.status_code == 200
    assert response.json()["age_confirmed_at"] is None
    # The gate is the directory's join, and there is nothing on the account
    # for a client to read as "you are blocked".
    assert "age_confirmation_required" not in response.json()


async def test_an_account_that_answered_under_age_keeps_its_communities(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The answer closes one door. It does not take away what is already theirs.

    A community somebody was invited to is that community's to answer for, so
    an under-age answer leaves the membership standing and everything in it
    reachable — the refusal is only ever the next directory join. (Fifteen in
    the US: old enough for an account there. Under the minimum for an account
    is a different answer, and closes it — the tests at the end.)
    """
    invited = await create_guild(session, name="Just Us")
    a = await acting_user(
        guild_role=CommunityRole.member, guild=invited, age_confirmed_at=None
    )
    await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers={**a.headers, "CF-IPCountry": "US"},
    )

    still_theirs = await client.get("/api/v1/communities/", headers=a.headers)

    assert still_theirs.status_code == 200
    assert [g["id"] for g in still_theirs.json()] == [invited.id]


# ---------------------------------------------------------------------------
# The rule belongs to the community, not to the route in.
# ---------------------------------------------------------------------------


async def _invite_code(client: AsyncClient, guild: Guild, admin_headers) -> str:
    response = await client.post(
        f"/api/v1/communities/{guild.id}/invites", headers=admin_headers, json={}
    )
    assert response.status_code == 201, response.text
    return response.json()["code"]


@pytest.mark.parametrize(
    "listed,expected_status",
    [
        pytest.param(True, 403, id="an invite into a listed community asks"),
        pytest.param(False, 200, id="an invite into a private one does not"),
    ],
)
async def test_an_invite_asks_the_age_question_only_where_the_guild_is_listed(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    listed: bool,
    expected_status: int,
):
    """Anyone signed in can find a listed community, so every way into one is a
    way into a room full of strangers — an invite included. A private community
    is its own to answer for and asks nothing, whoever turns up."""
    guild, admin_headers = await _admin_of(session, acting_user, name="Open Table")
    if listed:
        await _list_as_community(session, guild)
    code = await _invite_code(client, guild, admin_headers)
    invitee = await acting_user("member", age_confirmed_at=None)

    response = await client.post(
        "/api/v1/communities/invite/accept",
        headers=invitee.headers,
        json={"code": code},
    )

    assert response.status_code == expected_status, response.text
    membership = await _membership_of(session, guild=guild, user_id=invitee.user.id)
    assert (membership is None) is (expected_status != 200)


async def test_an_answered_under_age_account_cannot_be_put_in_a_listed_guild(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The floor under the ways in that have nobody at a keyboard.

    A group sync or an admin adding somebody never meets the question, so the
    answer already on the record is what holds: an account that said it is
    under the minimum does not land in a community anyone can find.
    """
    a = await acting_user("member", age_confirmed_at=None)
    await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers={**a.headers, "CF-IPCountry": "US"},
    )
    guild = await _a_listed_guild(session, name="Open Table")
    await session.refresh(a.user)

    with pytest.raises(guilds_service.AgeConfirmationRequiredError):
        await guilds_service.ensure_membership(
            session, guild_id=guild.id, user_id=a.user.id, via="sso"
        )


async def test_a_guild_holding_an_under_age_member_cannot_be_listed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A private guild collected its members under no age rule, so the move
    onto the shelf is the one moment that can be reconciled."""
    guild, admin_headers = await _admin_of(session, acting_user, name="Just Us")
    member = await acting_user(
        guild_role=CommunityRole.member, guild=guild, age_confirmed_at=None
    )
    await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers={**member.headers, "CF-IPCountry": "US"},
    )

    response = await client.patch(
        f"/api/v1/communities/{guild.id}",
        headers=admin_headers,
        json={
            "is_community": True,
            "categories": ["other"],
            "has_adult_content": False,
        },
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "COMMUNITY_COMMUNITY_UNDER_AGE_MEMBERS"
    await session.refresh(guild)
    assert guild.is_community is False


async def test_an_unanswered_member_does_not_stop_a_guild_being_listed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """ "We have not asked" is not "too young".

    A private guild never puts the question, so every one of them is full of
    unanswered accounts. Holding a listing until they all answer would mean no
    private guild could ever be listed at all.
    """
    guild, admin_headers = await _admin_of(session, acting_user, name="Just Us")
    await acting_user(
        guild_role=CommunityRole.member, guild=guild, age_confirmed_at=None
    )

    response = await client.patch(
        f"/api/v1/communities/{guild.id}",
        headers=admin_headers,
        json={
            "is_community": True,
            "categories": ["other"],
            "has_adult_content": False,
        },
    )

    assert response.status_code == 200, response.text
    await session.refresh(guild)
    assert guild.is_community is True


async def test_an_already_listed_guild_is_not_re_checked_on_an_unrelated_edit(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The rule is a gate on the way in, not a standing condition.

    Re-asking it on every edit would hand an admin a failure about somebody
    else's birthday with nothing to do about it but remove them.
    """
    guild, admin_headers = await _admin_of(session, acting_user, name="Open Table")
    await _list_as_community(session, guild)
    member = await acting_user(
        guild_role=CommunityRole.member, guild=guild, age_confirmed_at=None
    )
    await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers={**member.headers, "CF-IPCountry": "US"},
    )

    response = await client.patch(
        f"/api/v1/communities/{guild.id}",
        headers=admin_headers,
        json={"description": "Now with a description"},
    )

    assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "listed,answer,expected_status,expected_detail",
    [
        pytest.param(
            True,
            "unanswered",
            403,
            "COMMUNITY_AGE_CONFIRMATION_REQUIRED",
            id="a listed community asks at its own door",
        ),
        pytest.param(
            True,
            "under age",
            403,
            "COMMUNITY_AGE_BELOW_MINIMUM",
            id="and tells an answer that stands apart from a question",
        ),
        pytest.param(True, "confirmed", 200, None, id="an answered account walks in"),
        pytest.param(
            False, "unanswered", 200, None, id="a private community asks nothing"
        ),
    ],
)
async def test_a_listed_community_asks_its_own_members_before_letting_them_in(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    listed: bool,
    answer: str,
    expected_status: int,
    expected_detail: str | None,
):
    """The ways in with nobody at a keyboard could not put the question, so the
    community puts it at its own door.

    Not the platform's door: an account that has not answered keeps the rest of
    Initiative and every private community it belongs to. What it cannot do is
    walk into the listed one until it answers.
    """
    guild = (
        await _a_listed_guild(session, name="Open Table")
        if listed
        else await create_guild(session, name="Just Us")
    )
    a = await acting_user(
        guild_role=CommunityRole.member, guild=guild, age_confirmed_at=None
    )
    if answer != "unanswered":
        await client.post(
            "/api/v1/me/age-confirmation",
            json={
                "birthdate": (
                    ADULT_BIRTHDATE if answer == "confirmed" else _birthdate_for_age(15)
                )
            },
            headers={**a.headers, "CF-IPCountry": "US"},
        )

    response = await client.get(a.g("/initiatives/"), headers=a.headers)

    assert response.status_code == expected_status, response.text
    if expected_detail is not None:
        assert response.json()["detail"] == expected_detail


async def test_being_asked_by_one_community_does_not_close_another(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The question is the listed community's, not the platform's.

    Somebody a group sync put in a listed community owes it an answer. The
    private community they have been using for months is not part of that
    bargain and stays open while they decide.
    """
    listed = await _a_listed_guild(session, name="Open Table")
    a = await acting_user(
        guild_role=CommunityRole.member, guild=listed, age_confirmed_at=None
    )
    private = await create_guild(session, name="Just Us")
    await create_guild_membership(session, user=a.user, guild=private)

    refused = await client.get(a.g("/initiatives/"), headers=a.headers)
    still_open = await client.get(
        f"/api/v1/c/{private.id}/initiatives/", headers=a.headers
    )

    assert refused.status_code == 403
    assert refused.json()["detail"] == "COMMUNITY_AGE_CONFIRMATION_REQUIRED"
    assert still_open.status_code == 200, still_open.text


async def test_a_kept_date_stands_against_a_second_answer(
    client: AsyncClient, acting_user
):
    """Once a date is on file it is not re-answered: a date somebody could
    rewrite until a plug-in let them in is not one. The first answer's record
    does not move."""
    a = await acting_user("member", age_confirmed_at=None)

    first = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=a.headers,
    )
    second = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(40)},
        headers=a.headers,
    )

    assert first.status_code == 200
    assert first.json()["birthdate_on_file"] is True
    assert second.status_code == 409
    assert second.json()["detail"] == "USER_AGE_ANSWER_STANDS"


async def test_the_answer_stands_against_a_second_try(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A question you can re-answer until it comes out right is not a question."""
    a = await acting_user("member", age_confirmed_at=None)

    await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers={**a.headers, "CF-IPCountry": "US"},
    )
    second = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=a.headers,
    )

    assert second.status_code == 409
    assert second.json()["detail"] == "USER_AGE_ANSWER_STANDS"
    await session.refresh(a.user)
    assert a.user.age_confirmed_at is None


@pytest.mark.parametrize(
    "years,expected_status",
    [
        pytest.param(30, 200, id="an answer that passes"),
        pytest.param(15, 422, id="an answer that does not"),
    ],
)
async def test_the_date_is_kept_only_encrypted(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    years: int,
    expected_status: int,
):
    """The date is kept — a plug-in's minimum age differs by country — but only
    in ``user_birthdates``, encrypted, and never on the account row or in a
    reply. The fact is recorded beside it either way.
    """
    from app.core.encryption import SALT_BIRTHDATE, decrypt_field
    from app.models.platform.user_birthdate import UserBirthdate

    a = await acting_user("member", age_confirmed_at=None)
    birthdate = _birthdate_for_age(years)

    response = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": birthdate},
        headers={**a.headers, "CF-IPCountry": "US"},
    )
    assert response.status_code == expected_status, response.text

    # Nothing in the reply carries it back.
    assert birthdate not in response.text

    await session.refresh(a.user)
    if expected_status == 200:
        assert a.user.age_confirmed_at is not None
        assert a.user.age_below_minimum_at is None
    else:
        assert a.user.age_below_minimum_at is not None
        assert a.user.age_confirmed_at is None

    year, month, day = birthdate.split("-")
    for column in a.user.__table__.columns.keys():  # noqa: SIM118
        rendered = str(getattr(a.user, column))
        assert birthdate not in rendered, f"users.{column} holds the date"
        # The date reshaped is still the date.
        assert f"{day}/{month}/{year}" not in rendered, f"users.{column} holds the date"

    kept = (
        await session.exec(
            select(UserBirthdate).where(UserBirthdate.user_id == a.user.id)
        )
    ).one()
    assert birthdate not in kept.birthdate_encrypted
    assert decrypt_field(kept.birthdate_encrypted, SALT_BIRTHDATE) == birthdate


async def test_lifting_the_block_forgets_the_kept_date(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A mistyped year is put right by answering again, so the date goes too."""
    from app.models.platform.user_birthdate import UserBirthdate

    subject = await acting_user("member", age_confirmed_at=None)
    support = await acting_user(UserRole.support)
    await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers={**subject.headers, "CF-IPCountry": "US"},
    )

    lifted = await client.delete(
        f"/api/v1/operator/users/{subject.user.id}/age-block", headers=support.headers
    )
    again = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=subject.headers,
    )

    assert lifted.status_code == 200, lifted.text
    assert again.status_code == 200, again.text
    kept = (
        await session.exec(
            select(UserBirthdate).where(UserBirthdate.user_id == subject.user.id)
        )
    ).all()
    assert len(kept) == 1


@pytest.mark.parametrize(
    "tier,expected_status",
    [
        pytest.param(UserRole.support, 200, id="support, the lowest rung that has it"),
        pytest.param(UserRole.member, 403, id="an ordinary member"),
    ],
)
async def test_lifting_an_age_block_is_a_platform_capability(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    tier: UserRole,
    expected_status: int,
):
    """The way back from a mistyped year, and who holds it."""
    subject = await acting_user("member", age_confirmed_at=None)
    await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers={**subject.headers, "CF-IPCountry": "US"},
    )
    await session.refresh(subject.user)
    assert subject.user.age_below_minimum_at is not None

    staff = await acting_user(tier)
    response = await client.delete(
        f"/api/v1/operator/users/{subject.user.id}/age-block", headers=staff.headers
    )

    assert response.status_code == expected_status, response.text
    if expected_status != 200:
        return

    # And the question is answerable again, from scratch.
    retry = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=subject.headers,
    )
    assert retry.status_code == 200


async def test_lifting_a_block_that_is_not_there_says_so(
    client: AsyncClient, acting_user
):
    subject = await acting_user("member")
    support = await acting_user(UserRole.support)

    response = await client.delete(
        f"/api/v1/operator/users/{subject.user.id}/age-block", headers=support.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "USER_AGE_NOT_BLOCKED"


async def test_a_reset_adult_answering_under_age_is_not_still_confirmed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The reset starts the question over: an old confirmation left standing
    would admit somebody whose new answer is under the minimum."""
    subject = await acting_user("member", age_confirmed_at=None)
    support = await acting_user(UserRole.support)
    await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=subject.headers,
    )

    lifted = await client.delete(
        f"/api/v1/operator/users/{subject.user.id}/age-block", headers=support.headers
    )
    under = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers={**subject.headers, "CF-IPCountry": "US"},
    )

    assert lifted.status_code == 200, lifted.text
    assert under.status_code == 422
    assert under.json()["detail"] == "USER_AGE_BELOW_MINIMUM"
    await session.refresh(subject.user)
    assert subject.user.age_confirmed_at is None
    assert subject.user.age_below_minimum_at is not None


async def test_an_answer_that_failed_to_save_does_not_block_a_retry(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    """The date is kept first and taken back if the answer does not save, so
    the person can answer again."""
    from app.services.platform import users as users_service

    a = await acting_user("member", age_confirmed_at=None)
    recorded = users_service.record_age_answer

    def fails(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr(users_service, "record_age_answer", fails)
    with pytest.raises(RuntimeError):
        await client.post(
            "/api/v1/me/age-confirmation",
            json={"birthdate": ADULT_BIRTHDATE},
            headers=a.headers,
        )
    monkeypatch.setattr(users_service, "record_age_answer", recorded)

    retry = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": ADULT_BIRTHDATE},
        headers=a.headers,
    )

    assert retry.status_code == 200, retry.text
    assert retry.json()["birthdate_on_file"] is True


# ── Under the minimum for an account, answered late ─────────────────────────
#
# Sign-up refuses a date of birth under the minimum age for an account in the
# country the request comes from, and makes no account. An account made without
# a date (a sign-in provider asked for none, or the field was left empty)
# answers the same question here, and the same rule has to hold: what sign-up
# would not have made, this takes away.


@pytest.fixture(autouse=True)
def country_header(monkeypatch):
    """Run this module behind a proxy that names the visitor's country, as the
    cloud does behind Cloudflare: a request carrying ``CF-IPCountry`` is from
    there, and one without it is from nowhere known, where the highest
    minimum applies. The under-age answers above are fifteen from the US —
    old enough for an account there, so what they test is the directory."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "CLIENT_COUNTRY_HEADER", "CF-IPCountry")


def _from(headers: dict[str, str], country: str | None) -> dict[str, str]:
    return {**headers, **({"CF-IPCountry": country} if country else {})}


async def _row(session: AsyncSession, user_id: int) -> User:
    session.expunge_all()
    return (await session.exec(select(User).where(User.id == user_id))).one()


@pytest.mark.parametrize(
    ("years", "country"),
    [(12, "US"), (15, "DE"), (15, None), (15, "XX")],
    ids=["under the US minimum", "under the German minimum", "no header", "unknown"],
)
async def test_an_answer_under_the_account_minimum_closes_the_account(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    years: int,
    country: str | None,
):
    """The answer stands, the date is not kept, the account is scheduled for
    erasure with its sessions ended, and where the country is not known the
    highest minimum applies — exactly what sign-up does, one step later."""
    from app.services.platform import users as users_service

    a = await acting_user("member", age_confirmed_at=None)

    response = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(years)},
        headers=_from(a.headers, country),
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "USER_AGE_BELOW_ACCOUNT_MINIMUM"
    row = await _row(session, a.user.id)
    assert row.status == UserStatus.deleted
    assert row.age_below_minimum_at is not None
    assert row.age_below_account_minimum_at is not None
    assert row.age_confirmed_at is None
    assert await users_service.birthdate_of(session, user_id=a.user.id) is None
    # Every session the account held ended with it.
    assert (await client.get("/api/v1/me", headers=a.headers)).status_code == 401


async def test_old_enough_for_an_account_but_not_the_directory_keeps_the_account(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Fifteen in the US is an account without a directory, as before: the
    country's minimum for an account is the only thing this adds."""
    a = await acting_user("member", age_confirmed_at=None)

    response = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(15)},
        headers=_from(a.headers, "US"),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "USER_AGE_BELOW_MINIMUM"
    row = await _row(session, a.user.id)
    assert row.status == UserStatus.active
    assert row.age_below_minimum_at is not None
    assert row.age_below_account_minimum_at is None


async def test_a_date_nobody_was_born_on_closes_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A year still to come reads as an age below every minimum. It is refused
    as a typo before it is read as an age, so it cannot close an account."""
    a = await acting_user("member", age_confirmed_at=None)

    response = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _tomorrow()},
        headers=_from(a.headers, "US"),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "USER_AGE_INVALID_BIRTHDATE"
    row = await _row(session, a.user.id)
    assert row.status == UserStatus.active
    assert row.age_below_minimum_at is None
    assert row.age_below_account_minimum_at is None


async def test_a_deployment_that_does_not_check_age_closes_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """With the check off nothing is asked, and nothing answered may close an
    account."""
    await rules.put(session, "community_directory_enabled", False)
    await rules.put(session, "community_age_gate_enabled", False)
    await session.commit()
    a = await acting_user("member", age_confirmed_at=None)

    response = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(12)},
        headers=_from(a.headers, "US"),
    )

    assert response.status_code != 403, response.text
    row = await _row(session, a.user.id)
    assert row.status == UserStatus.active
    assert row.age_below_account_minimum_at is None


async def test_signing_in_does_not_call_the_closure_off_but_the_ticket_does(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A holder's own deletion is called off by signing in. This one is not:
    the answer stands until support clears it, and only then does the next
    sign-in restore the account whole and ask again."""
    from app.testing.factories import get_auth_headers

    support = await acting_user("owner")
    user = await create_user(session, age_confirmed_at=None)
    refused = await client.post(
        "/api/v1/me/age-confirmation",
        json={"birthdate": _birthdate_for_age(12)},
        headers=_from(get_auth_headers(user), "US"),
    )
    assert refused.status_code == 403, refused.text

    def sign_in():
        return client.post(
            "/api/v1/auth/token",
            data={"username": user.seeded_address, "password": "testpassword123"},
        )

    # Coming back is refused, and the account stays where it was: closed.
    back = await sign_in()
    assert back.status_code == 400, back.text
    assert back.json()["detail"] == "INACTIVE_USER"
    row = await _row(session, user.id)
    assert row.status == UserStatus.deleted
    assert row.age_below_account_minimum_at is not None

    # The ticket: the marks go, and the next sign-in calls the erasure off.
    cleared = await client.delete(
        f"/api/v1/operator/users/{user.id}/age-block", headers=support.headers
    )
    assert cleared.status_code == 200, cleared.text
    row = await _row(session, user.id)
    assert row.age_below_minimum_at is None
    assert row.age_below_account_minimum_at is None
    assert row.status == UserStatus.deleted

    back = await sign_in()
    assert back.status_code == 200, back.text
    row = await _row(session, user.id)
    assert row.status == UserStatus.active
    me = await client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {back.json()['access_token']}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["birthdate_required"] is True
