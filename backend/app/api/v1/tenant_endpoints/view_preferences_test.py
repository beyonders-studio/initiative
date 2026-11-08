"""A person's views of a community's lists: ``/c/{community_id}/view-preferences``.

Each person reads and writes only their own rows, through the route and in the
database; the account's own map is a separate store.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole, CommunityStatus
from app.models.platform.user_view_preference import MAX_VALUE_JSON_BYTES
from app.models.tenant.view_preference import ViewPreference
from app.services.platform import app_settings as app_settings_service
from app.services.platform import rules
from app.testing import create_guest, get_auth_headers, route_as

VIEWS = "/view-preferences"


async def test_a_member_reads_and_writes_only_their_own(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    project = {"layout": "table", "parts": {"table": {"filters": {"tag_ids": [3]}}}}

    for key, value in (("view:project:12", project), ("view:members", {})):
        put = await client.put(
            a.g(f"{VIEWS}/{key}"), headers=a.headers, json={"value": value}
        )
        assert put.status_code == 204, put.text
    # The same key, somebody else's.
    put = await client.put(
        a.g(f"{VIEWS}/view:project:12"), headers=b.headers, json={"value": {"b": 1}}
    )
    assert put.status_code == 204, put.text
    # Writing it again replaces it.
    put = await client.put(
        a.g(f"{VIEWS}/view:members"), headers=a.headers, json={"value": {"v": 2}}
    )
    assert put.status_code == 204, put.text

    mine = await client.get(a.g(VIEWS), headers=a.headers)
    assert mine.json() == {
        "items": {"view:project:12": project, "view:members": {"v": 2}}
    }
    theirs = await client.get(a.g(VIEWS), headers=b.headers)
    assert theirs.json() == {"items": {"view:project:12": {"b": 1}}}
    # The account's own map holds none of them.
    account = await client.get("/api/v1/user-view-preferences", headers=a.headers)
    assert account.json() == {"items": {}}


async def test_another_member_reaches_none_of_them(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member)
    b = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    put = await client.put(
        a.g(f"{VIEWS}/view:members"), headers=a.headers, json={"value": {}}
    )
    assert put.status_code == 204, put.text

    await route_as(session, user_id=b.user.id, guild_id=a.guild.id)
    assert (await session.exec(select(ViewPreference))).all() == []


async def test_a_guest_keeps_their_own(
    client: AsyncClient, session: AsyncSession, acting_user
):
    await app_settings_service.ensure_settings_row(session)
    await rules.put(session, "guests_enabled", True)
    await session.commit()
    a = await acting_user(guild_role=CommunityRole.admin)
    guest = await create_guest(session, a.guild)
    headers = get_auth_headers(guest)

    put = await client.put(
        a.g(f"{VIEWS}/view:calendars"),
        headers=headers,
        json={"value": {"mode": "week"}},
    )
    assert put.status_code == 204, put.text
    got = await client.get(a.g(VIEWS), headers=headers)
    assert got.json() == {"items": {"view:calendars": {"mode": "week"}}}


async def test_a_read_only_community_keeps_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member)
    a.guild.status = CommunityStatus.read_only.value
    session.add(a.guild)
    await session.commit()

    put = await client.put(
        a.g(f"{VIEWS}/view:members"), headers=a.headers, json={"value": {}}
    )
    assert put.status_code == 204, put.text
    got = await client.get(a.g(VIEWS), headers=a.headers)
    assert got.json() == {"items": {}}


async def test_keys_and_values_are_held_to_the_account_store_s_caps(
    client: AsyncClient, acting_user
):
    a = await acting_user(guild_role=CommunityRole.member)
    for key in ("bad@key", "star*key", "x" * 129):
        put = await client.put(
            a.g(f"{VIEWS}/{key}"), headers=a.headers, json={"value": {}}
        )
        assert put.status_code == 422, key
    too_big = {"data": "a" * (MAX_VALUE_JSON_BYTES + 1)}
    put = await client.put(
        a.g(f"{VIEWS}/view:members"), headers=a.headers, json={"value": too_big}
    )
    assert put.status_code == 422
