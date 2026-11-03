"""Integration tests for /api/v1/me/contacts."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import Guild, CommunityRole
from app.models.platform.user import User, UserStatus
from app.models.platform.user_dm_settings import DmPolicy
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
)

SECTIONS = "/api/v1/me/contacts"


@pytest.fixture(autouse=True)
async def community_by_default(session: AsyncSession):
    """Run these against a deployment whose operator default is ``community``.

    A roster names the people the reader could actually reach out to, so on the
    shipped default — ``private`` — every one of these sections is empty and
    the paging, search and naming below have nothing to describe. Setting the
    operator's default here is what gives them members to be about; the default
    itself, and the empty page it makes, are
    ``services/platform/contacts_reachable_test.py``.

    Set before any account is made: the default is copied into the account when
    it is created, and moving it afterwards moves nobody.
    """
    from app.services.platform import rules

    await rules.put(session, "default_dm_policy", DmPolicy.community)
    await session.commit()


def _section(payload: dict, guild_id: int) -> dict:
    """The section for one guild, or fail the test saying it is missing."""
    for section in payload["sections"]:
        if section["community_id"] == guild_id:
            return section
    raise AssertionError(
        f"no section for guild {guild_id}; got "
        f"{[s['guild_id'] for s in payload['sections']]}"
    )


async def _join(
    session: AsyncSession, guild: Guild, user: User | None = None, **overrides
) -> User:
    """Put somebody in ``guild`` — a fresh account unless one is given."""
    if user is None:
        user = await create_user(session, **overrides)
    await create_guild_membership(session, user=user, guild=guild)
    return user


async def _rail(session: AsyncSession, user: User, *guilds: Guild) -> None:
    """Put ``user`` in each guild, in the rail order given."""
    for position, guild in enumerate(guilds):
        await create_guild_membership(
            session, user=user, guild=guild, position=position
        )


# --- sections ---------------------------------------------------------------


async def test_an_account_on_its_own_has_nothing_to_list(
    client: AsyncClient, acting_user
):
    """No communities: the list answers, empty."""
    a = await acting_user()

    sections = await client.get(SECTIONS, headers=a.headers)
    assert sections.status_code == 200
    assert sections.json()["sections"] == []


async def test_sections_follow_rail_order(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Sections come back in ``GuildMembership.position``, not guild id."""
    a = await acting_user()
    first = await create_guild(session)
    second = await create_guild(session)
    third = await create_guild(session)
    # Deliberately not id order: the rail is what decides.
    await _rail(session, a.user, second, third, first)
    # Somebody else in each, or there would be no section to order.
    for guild in (first, second, third):
        await _join(session, guild)

    response = await client.get(SECTIONS, headers=a.headers)
    assert response.status_code == 200
    assert [s["community_id"] for s in response.json()["sections"]] == [
        second.id,
        third.id,
        first.id,
    ]


async def test_only_a_community_the_caller_shares_gets_a_section(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Three communities, one section: somebody else's is not the caller's to
    read, and being alone somewhere is not an empty roster, it is no roster —
    a section there would say nobody is accepting messages, which is a remark
    about people who are not there.
    """
    a = await acting_user()
    shared = await create_guild(session)
    alone = await create_guild(session)
    theirs = await create_guild(session)
    await _rail(session, a.user, shared, alone)
    await _join(session, shared)
    await _join(session, theirs)

    response = await client.get(SECTIONS, headers=a.headers)
    ids = [s["community_id"] for s in response.json()["sections"]]
    assert ids == [shared.id]
    assert alone.id not in ids
    assert theirs.id not in ids


async def test_a_section_names_the_other_people_who_are_still_here(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The caller is not their own contact, and a suspended account leaves the
    roster — count and all."""
    a = await acting_user(guild_role=CommunityRole.member)
    other = await _join(session, a.guild)

    response = await client.get(SECTIONS, headers=a.headers)
    section = _section(response.json(), a.guild.id)
    assert [item["id"] for item in section["items"]] == [other.id]

    other.status = UserStatus.suspended
    session.add(other)
    await session.commit()

    response = await client.get(SECTIONS, headers=a.headers)
    section = _section(response.json(), a.guild.id)
    assert section["items"] == []
    assert section["total_count"] == 0


async def test_sections_page_within_each_guild(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Paging is per section — a flat offset across a merged list would not
    mean anything for a grouped response."""
    a = await acting_user(guild_role=CommunityRole.member)
    for index in range(5):
        await _join(session, a.guild, username=f"member{index}")

    first = await client.get(f"{SECTIONS}?page=1&page_size=2", headers=a.headers)
    section = _section(first.json(), a.guild.id)
    assert len(section["items"]) == 2
    assert section["total_count"] == 5
    assert section["has_next"] is True

    last = await client.get(f"{SECTIONS}?page=3&page_size=2", headers=a.headers)
    section = _section(last.json(), a.guild.id)
    assert len(section["items"]) == 1
    assert section["has_next"] is False


async def test_guild_ids_narrows_to_one_section(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user()
    first = await create_guild(session)
    second = await create_guild(session)
    await _rail(session, a.user, first, second)
    for guild in (first, second):
        await _join(session, guild)

    response = await client.get(
        f"{SECTIONS}?community_ids={second.id}", headers=a.headers
    )
    assert [s["community_id"] for s in response.json()["sections"]] == [second.id]


# --- how a person is drawn ---------------------------------------------------


async def test_a_row_draws_somebody_as_every_surface_does(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A row draws somebody the way every other surface does."""
    a = await acting_user(guild_role=CommunityRole.member)
    await _join(
        session, a.guild, profile_decorations={"frame": "core.gold", "trophies": []}
    )
    roster = await client.get(SECTIONS, headers=a.headers)
    row = _section(roster.json(), a.guild.id)["items"][0]
    assert row["profile_decorations"]["frame"] == "core.gold"


# --- names, per guild -------------------------------------------------------


async def test_each_guild_names_someone_by_what_they_set_there(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """One response, two guilds, one person — named in each by the display name
    set there, and searchable by it only there."""
    a = await acting_user()
    named = await create_guild(session)
    unnamed = await create_guild(session)
    await _rail(session, a.user, named, unnamed)
    other = await create_user(session, username="qqqhandle")
    await _join(session, named, other)
    await _join(session, unnamed, other)
    await create_guild_membership(
        session, user=other, guild=named, display_name="Ada Lovelace"
    )

    payload = (await client.get(SECTIONS, headers=a.headers)).json()
    assert _section(payload, named.id)["items"][0]["display_name"] == "Ada Lovelace"
    assert _section(payload, unnamed.id)["items"][0]["display_name"] is None

    searched = await client.get(f"{SECTIONS}?search=Lovelace", headers=a.headers)
    assert [s["community_id"] for s in searched.json()["sections"]] == [named.id]


# --- the shared-guild chip --------------------------------------------------


async def test_shared_guilds_named_on_every_appearance(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The set is what the two of them share, so it is the same on each
    appearance and says nothing about where else the subject is."""
    a = await acting_user()
    guilds = [await create_guild(session) for _ in range(3)]
    await _rail(session, a.user, *guilds)

    other = await create_user(session)
    for guild in guilds:
        await _join(session, guild, other)
    # A guild the subject is in and the caller is not.
    elsewhere = await create_guild(session)
    await _join(session, elsewhere, other)

    payload = (await client.get(SECTIONS, headers=a.headers)).json()
    expected = [guild.id for guild in guilds]
    for guild in guilds:
        section = _section(payload, guild.id)
        assert [item["id"] for item in section["items"]] == [other.id]
        # Every appearance names the full set, in rail order; the chip is what
        # drops the section's own guild.
        assert section["items"][0]["shared_community_ids"] == expected
        assert elsewhere.id not in section["items"][0]["shared_community_ids"]


async def test_shared_guilds_stable_across_pages(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The map is read from memberships, not from the rows on the page.

    ``other`` is last alphabetically in the big guild, so it only appears on a
    later page there — and its chip must be the same on both.
    """
    a = await acting_user()
    big = await create_guild(session)
    small = await create_guild(session)
    await _rail(session, a.user, big, small)

    for index in range(4):
        await _join(session, big, username=f"aaa{index}")

    other = await create_user(session, username="zzztail")
    await _join(session, big, other)
    await _join(session, small, other)

    expected = [big.id, small.id]

    page_one = await client.get(f"{SECTIONS}?page=1&page_size=2", headers=a.headers)
    small_section = _section(page_one.json(), small.id)
    assert small_section["items"][0]["shared_community_ids"] == expected
    # ...and ``other`` is not even on the big guild's first page.
    assert other.id not in [i["id"] for i in _section(page_one.json(), big.id)["items"]]

    page_three = await client.get(f"{SECTIONS}?page=3&page_size=2", headers=a.headers)
    big_section = _section(page_three.json(), big.id)
    assert [i["id"] for i in big_section["items"]] == [other.id]
    assert big_section["items"][0]["shared_community_ids"] == expected


# --- search -----------------------------------------------------------------


async def test_search_finds_someone_past_the_first_page(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The reason search is server-side: a client filter over the loaded page
    could not reach this person."""
    a = await acting_user(guild_role=CommunityRole.member)
    for index in range(6):
        await _join(session, a.guild, username=f"aaa{index}")
    target = await _join(session, a.guild, username="zzzneedle")

    unsearched = await client.get(f"{SECTIONS}?page=1&page_size=3", headers=a.headers)
    assert target.id not in [
        i["id"] for i in _section(unsearched.json(), a.guild.id)["items"]
    ]

    searched = await client.get(
        f"{SECTIONS}?search=zzzneedle&page=1&page_size=3", headers=a.headers
    )
    section = _section(searched.json(), a.guild.id)
    assert [i["id"] for i in section["items"]] == [target.id]


async def test_search_hides_sections_with_no_match(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user()
    hit = await create_guild(session)
    miss = await create_guild(session)
    await _rail(session, a.user, hit, miss)
    await _join(session, hit, username="findme")
    await _join(session, miss, username="somebody")

    response = await client.get(f"{SECTIONS}?search=findme", headers=a.headers)
    assert [s["community_id"] for s in response.json()["sections"]] == [hit.id]
