"""A member whose API access the community turned off: the setting, and what
it means.

The rule is answered in three places and they have to agree — the seat's
setting on the roster, the mint, and every path that reaches the guild's
content with a key in hand.
"""

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.models.tenant._mixins import ActorKind
from app.testing.factories import (
    create_access_grant,
    create_calendar,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_project,
    create_user,
    get_auth_headers,
    guild_administration,
)
from app.testing.schema_harness import route_session_to_guild


async def _key_headers(client: AsyncClient, headers: dict, **body) -> dict[str, str]:
    """Mint a key for the caller and return the headers that present it."""
    created = await client.post(
        "/api/v1/me/api-keys", headers=headers, json={"name": "k", **body}
    )
    assert created.status_code == 201, created.text
    return {"Authorization": f"Bearer {created.json()['secret']}"}


def _api_access(guild_id: int, user_id: int) -> str:
    return f"/api/v1/communities/{guild_id}/members/{user_id}/api-access"


# --- The setting ------------------------------------------------------------


async def test_the_seat_sets_a_members_api_access_and_the_roster_reads_it(
    client: AsyncClient, session: AsyncSession
):
    seat = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(session, user=member, guild=guild)
    headers = get_auth_headers(seat)

    def allowed(response) -> bool:
        return next(
            m["api_keys_allowed"]
            for m in response.json()["items"]
            if m["id"] == member.id
        )

    roster = f"/api/v1/c/{guild.id}/users/"
    assert allowed(await client.get(roster, headers=headers)) is True

    off = await client.put(
        _api_access(guild.id, member.id),
        headers=headers,
        json={"api_keys_allowed": False},
    )
    assert off.status_code == 204, off.text
    assert allowed(await client.get(roster, headers=headers)) is False

    on = await client.put(
        _api_access(guild.id, member.id),
        headers=headers,
        json={"api_keys_allowed": True},
    )
    assert on.status_code == 204, on.text
    assert allowed(await client.get(roster, headers=headers)) is True


async def test_only_the_seat_sees_or_sets_api_access(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await create_guild_membership(session, user=member, guild=guild)
    headers = get_auth_headers(admin)

    roster = await client.get(f"/api/v1/c/{guild.id}/users/", headers=headers)
    assert {m["api_keys_allowed"] for m in roster.json()["items"]} == {None}

    refused = await client.put(
        _api_access(guild.id, member.id),
        headers=headers,
        json={"api_keys_allowed": False},
    )
    assert refused.status_code == 403


async def test_turning_api_access_off_needs_restrictions(
    client: AsyncClient, session: AsyncSession
):
    """Off is a rule and needs the option; on only ever admits more."""
    seat = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=seat, auth_options=[])
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=member, guild=guild, api_keys_allowed=False
    )
    headers = get_auth_headers(seat)

    off = await client.put(
        _api_access(guild.id, member.id),
        headers=headers,
        json={"api_keys_allowed": False},
    )
    assert off.status_code == 404

    on = await client.put(
        _api_access(guild.id, member.id),
        headers=headers,
        json={"api_keys_allowed": True},
    )
    assert on.status_code == 204, on.text


# --- The mint ---------------------------------------------------------------


async def test_no_key_is_minted_into_a_guild_that_declines_the_member(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session,
        user=user,
        guild=guild,
        role=CommunityRole.member,
        api_keys_allowed=False,
    )

    response = await client.post(
        "/api/v1/me/api-keys",
        headers=get_auth_headers(user),
        json={"name": "no", "community_id": guild.id},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_API_KEYS_REFUSED"


# --- The guild ---------------------------------------------------------------


async def test_a_key_minted_before_access_is_revoked_stops_reaching_the_guild(
    client: AsyncClient, session: AsyncSession
):
    """The answer is decided when the key is used, not when it was made, and
    applies while the guild holds the ``restrictions`` option it needs."""
    seat = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(session, user=member, guild=guild)
    headers = get_auth_headers(member)
    key_headers = await _key_headers(client, headers, community_id=guild.id)

    before = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=key_headers)
    assert before.status_code == 200

    revoked = await client.put(
        _api_access(guild.id, member.id),
        headers=get_auth_headers(seat),
        json={"api_keys_allowed": False},
    )
    assert revoked.status_code == 204, revoked.text

    after = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=key_headers)
    assert after.status_code == 403
    assert after.json()["detail"] == "COMMUNITY_API_KEYS_REFUSED"

    await guild_administration(session, guild, auth_options=[])
    lapsed = await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=key_headers)
    assert lapsed.status_code == 200
    await guild_administration(session, guild, auth_options=["restrictions"])

    # The same account's own sign-in still reaches it, so what was refused was
    # the credential rather than the membership.
    assert (
        await client.get(f"/api/v1/c/{guild.id}/initiatives/", headers=headers)
    ).status_code == 200


async def test_a_calendar_feed_is_refused_to_a_member_whose_api_access_is_off(
    client: AsyncClient, session: AsyncSession
):
    """A subscription link is a key, so the community's answer reaches it at
    the mint and on every fetch."""
    seat = await create_user(session)
    member = await create_user(session)
    guild = await create_guild(session, creator=seat)
    await create_guild_membership(
        session, user=seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(session, user=member, guild=guild)
    await guild_administration(session, guild, auth_options=["restrictions"])
    initiative = await create_initiative(session, guild, seat)
    await create_initiative_member(session, initiative, member)
    calendar = await create_calendar(session, initiative, seat)
    headers = get_auth_headers(member)
    link = {
        "name": "k",
        "community_id": guild.id,
        "resource_type": "calendar",
        "resource_id": calendar.id,
    }
    created = await client.post("/api/v1/me/api-keys", headers=headers, json=link)
    assert created.status_code == 201, created.text
    feed = (
        f"/api/v1/c/{guild.id}/calendars/{calendar.id}/feed.ics"
        f"?token={created.json()['secret']}"
    )
    assert (await client.get(feed)).status_code == 200

    async def use_api() -> bool:
        """What the member's community list says, which Subscribe reads."""
        listed = await client.get("/api/v1/communities/", headers=headers)
        return next(c for c in listed.json() if c["id"] == guild.id)["can"]["use_api"]

    assert await use_api() is True

    revoked = await client.put(
        _api_access(guild.id, member.id),
        headers=get_auth_headers(seat),
        json={"api_keys_allowed": False},
    )
    assert revoked.status_code == 204, revoked.text
    assert await use_api() is False
    refused = await client.get(feed)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "COMMUNITY_API_KEYS_REFUSED"
    minted = await client.post("/api/v1/me/api-keys", headers=headers, json=link)
    assert minted.status_code == 403
    assert minted.json()["detail"] == "COMMUNITY_API_KEYS_REFUSED"


async def test_a_grant_is_never_reached_with_a_key(
    client: AsyncClient, session: AsyncSession
):
    """Whatever the community's options: a grantee reaches it signed in, and
    not with a personal API key."""
    support = await create_user(session, role=UserRole.support)
    guild = await create_guild(session, auth_options=[])
    await create_access_grant(
        session, user=support, guild=guild, access_level="read_write"
    )
    headers = get_auth_headers(support)
    key_headers = await _key_headers(client, headers)
    path = f"/api/v1/c/{guild.id}/initiatives/"

    assert (await client.get(path, headers=headers)).status_code == 200

    refused = await client.get(path, headers=key_headers)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "COMMUNITY_API_KEYS_REFUSED"


async def test_an_unpinned_key_does_not_reach_a_guild_that_declines_the_member(
    client: AsyncClient, session: AsyncSession
):
    """A key pinned to no guild addresses every one the account belongs to, so
    the guild's answer cannot rest on what the key names."""
    user = await create_user(session)
    open_guild = await create_guild(session, creator=user)
    closed = await create_guild(session, creator=user)
    for guild in (open_guild, closed):
        await create_guild_membership(
            session,
            user=user,
            guild=guild,
            role=CommunityRole.member,
            api_keys_allowed=guild is open_guild,
        )
    key_headers = await _key_headers(client, get_auth_headers(user))

    reached = await client.get(
        f"/api/v1/c/{open_guild.id}/initiatives/", headers=key_headers
    )
    assert reached.status_code == 200

    refused = await client.get(
        f"/api/v1/c/{closed.id}/initiatives/", headers=key_headers
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "COMMUNITY_API_KEYS_REFUSED"


async def test_an_upload_is_not_served_to_a_key_the_guild_declines(
    client: AsyncClient, session: AsyncSession, tmp_path, monkeypatch
):
    """``/uploads`` reaches its guild through the same seam as REST, so a
    member whose keys are declined is declined there too."""
    from app.core.config import settings
    from app.models.tenant.upload import Upload
    from app.services.storage import get_guild_storage

    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path / "uploads"))

    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.superadmin
    )
    get_guild_storage(guild.id).write("note.txt", b"hello")
    await route_session_to_guild(session, guild.id)
    session.add(
        Upload(
            filename="note.txt",
            created_by=admin.id,
            created_by_kind=ActorKind.member,
            size_bytes=5,
        )
    )
    await session.commit()

    headers = get_auth_headers(admin)
    key_headers = await _key_headers(client, headers)
    path = f"/uploads/{guild.id}/note.txt"

    assert (await client.get(path, headers=key_headers)).status_code == 200

    await create_guild_membership(
        session,
        user=admin,
        guild=guild,
        role=CommunityRole.superadmin,
        api_keys_allowed=False,
    )

    refused = await client.get(path, headers=key_headers)
    assert refused.status_code == 403
    assert refused.json()["detail"] == "COMMUNITY_API_KEYS_REFUSED"

    # The same account's own sign-in still gets the file.
    assert (await client.get(path, headers=headers)).status_code == 200


async def test_the_cross_guild_aggregate_leaves_out_a_guild_that_declines_the_member(
    client: AsyncClient, session: AsyncSession
):
    """``/me/*`` visits each guild itself rather than through the guild path, so
    it drops such a guild rather than being the way around the refusal."""
    user = await create_user(session)
    open_guild = await create_guild(session, creator=user)
    closed = await create_guild(session, creator=user)
    names = {}
    for guild in (open_guild, closed):
        await create_guild_membership(
            session,
            user=user,
            guild=guild,
            role=CommunityRole.member,
            api_keys_allowed=guild is open_guild,
        )
        initiative = await create_initiative(session, guild, user)
        project = await create_project(session, initiative, user)
        names[guild.id] = project.name

    headers = get_auth_headers(user)
    key_headers = await _key_headers(client, headers)

    by_session = await client.get("/api/v1/me/projects", headers=headers)
    assert {p["name"] for p in by_session.json()["items"]} == set(names.values())

    by_key = await client.get("/api/v1/me/projects", headers=key_headers)
    assert {p["name"] for p in by_key.json()["items"]} == {names[open_guild.id]}

    # Without the ``restrictions`` option the setting needs, it declines nothing.
    await guild_administration(session, closed, auth_options=[])
    by_key = await client.get("/api/v1/me/projects", headers=key_headers)
    assert {p["name"] for p in by_key.json()["items"]} == set(names.values())


async def test_a_key_limited_to_one_guild_reads_only_that_guild_across_guilds(
    client: AsyncClient, session: AsyncSession
):
    """``/me/*`` visits each guild the account belongs to; a key limited to
    one guild visits that one and no other."""
    user = await create_user(session)
    pinned = await create_guild(session, creator=user)
    other = await create_guild(session, creator=user)
    names = {}
    for guild in (pinned, other):
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.member
        )
        initiative = await create_initiative(session, guild, user)
        project = await create_project(session, initiative, user)
        names[guild.id] = project.name
    pinned_id = pinned.id

    headers = get_auth_headers(user)
    key_headers = await _key_headers(client, headers, community_id=pinned_id)

    by_key = await client.get("/api/v1/me/projects", headers=key_headers)
    assert by_key.status_code == 200, by_key.text
    assert {p["name"] for p in by_key.json()["items"]} == {names[pinned_id]}


async def test_the_community_list_leaves_out_a_guild_that_declines_the_member(
    client: AsyncClient, session: AsyncSession
):
    """A key is shown the communities it can address: listing one that would
    refuse it offers a door that does not open."""
    user = await create_user(session)
    open_guild = await create_guild(session, creator=user, name="Open")
    closed = await create_guild(session, creator=user, name="Closed")
    for guild in (open_guild, closed):
        await create_guild_membership(
            session,
            user=user,
            guild=guild,
            role=CommunityRole.member,
            api_keys_allowed=guild is open_guild,
        )
    headers = get_auth_headers(user)
    key_headers = await _key_headers(client, headers)

    by_session = await client.get("/api/v1/communities/", headers=headers)
    assert {c["name"] for c in by_session.json()} == {"Open", "Closed"}

    by_key = await client.get("/api/v1/communities/", headers=key_headers)
    assert {c["name"] for c in by_key.json()} == {"Open"}


async def test_a_key_limited_to_one_guild_lists_only_that_guild(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session)
    pinned = await create_guild(session, creator=user, name="Pinned")
    other = await create_guild(session, creator=user, name="Other")
    for guild in (pinned, other):
        await create_guild_membership(
            session, user=user, guild=guild, role=CommunityRole.member
        )
    headers = get_auth_headers(user)
    key_headers = await _key_headers(client, headers, community_id=pinned.id)
    unpinned_headers = await _key_headers(client, headers)

    by_key = await client.get("/api/v1/communities/", headers=key_headers)
    assert [c["name"] for c in by_key.json()] == ["Pinned"]

    by_unpinned = await client.get("/api/v1/communities/", headers=unpinned_headers)
    assert {c["name"] for c in by_unpinned.json()} == {"Pinned", "Other"}
