"""What the guild floor reads of the platform.

``app_guild_base`` is what every routed ``guild_<id>`` role inherits, and
``app_guild_base_ro`` what the read-only and query roles do. Neither holds a
verb on the per-person platform tables: those are read and written under a
platform tier, the bare login role or the system engine. And of the tables
keyed by community, a routed request reads its own community's rows, while
the platform floor keeps reading every community its reader belongs to.

The routed half goes through the seam, as a request does; the platform half
assumes a platform tier the way ``UserSessionDep`` does. Both run on the
superuser setup session, which the ``SET ROLE`` drops to the role under test.
"""

import hashlib

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.session import set_rls_context
from app.db.public_rls import SHARED_TABLE_REGISTRY, role_name
from app.models.platform.user import UserRole
from app.testing import (
    create_auth_provider,
    create_guild,
    create_guild_auth_policy,
    create_guild_membership,
    create_user,
    route_as,
)
from app.db.request_context import Platform, Unattributed


GUILD_FLOORS = ("app_guild_base", "app_guild_base_ro")
PLATFORM_FLOOR = role_name("platform_base")
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")

#: Per-person platform tables the guild floors hold nothing on.
PER_PERSON = (
    "user_avatars",
    "user_cookie_consent",
    "user_notification_prefs",
    "user_view_preferences",
    "user_decorations",
    "announcements",
    "announcement_images",
    "marketplace_media",
)

#: Tables keyed by community, with the column naming it.
GUILD_KEYED = {
    "guilds": "id",
    "guild_memberships": "guild_id",
    "guild_administration": "guild_id",
    "guild_images": "guild_id",
    "community_rules": "guild_id",
    "guild_provider_connections": "guild_id",
}


async def _held(session, role: str, table: str, verb: str) -> bool:
    return (
        await session.exec(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            params={"r": role, "t": f"public.{table}", "v": verb},
        )
    ).scalar_one()


async def _guilds_seen(session, table: str, guild_ids: tuple[int, ...]) -> set[int]:
    column = GUILD_KEYED[table]
    rows = await session.exec(
        text(
            f"SELECT DISTINCT {column} FROM public.{table} WHERE {column} = ANY(:ids)"
        ),
        params={"ids": list(guild_ids)},
    )
    return {row[0] for row in rows.all()}


async def _two_guilds(session):
    """One account in two communities — an admin of one, a member of the
    other — each with a picture, a sign-in rule and a provider connection."""
    person = await create_user(session)
    one = await create_guild(session, creator=person)
    two = await create_guild(session)
    await create_guild_membership(session, user=person, guild=two)
    provider = await create_auth_provider(session)
    # Back on the setup login, whatever the factories left the session routed
    # to: the pictures are written the way the system engine writes them.
    await set_rls_context(session, Unattributed())
    for guild in (one, two):
        await create_guild_auth_policy(session, guild, provider)
        data = f"icon-{guild.id}".encode()
        await session.exec(
            text(
                "INSERT INTO public.guild_images "
                "(guild_id, variant, sha256, content_type, byte_size, data, "
                "created_at) "
                "VALUES (:g, 'icon', :sha, 'image/png', :size, :data, now())"
            ),
            params={
                "g": guild.id,
                "sha": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "data": data,
            },
        )
    await session.commit()
    return person, one, two


def test_the_registry_gives_the_guild_floor_none_of_them():
    for table in PER_PERSON:
        assert SHARED_TABLE_REGISTRY[table].grants.app_guild_base is None, table
    assert SHARED_TABLE_REGISTRY["marketplace_media"].grants.platform_base is None


@pytest.mark.parametrize("table", PER_PERSON)
async def test_the_guild_floors_hold_no_verb_on_it(session, table):
    for role in GUILD_FLOORS:
        for verb in VERBS:
            assert not await _held(session, role, table, verb), (
                f"{role} holds {verb} on {table}"
            )


async def test_the_platform_floor_does_not_read_marketplace_media(session):
    """Served before a session is routed, on the bare login role alone."""
    assert not await _held(session, PLATFORM_FLOOR, "marketplace_media", "SELECT")
    assert await _held(session, "app_user", "marketplace_media", "SELECT")


async def test_a_routed_request_reads_only_its_own_community(session):
    """Routed into the first community, the account's membership in the
    second reaches none of the second's rows, and none of the per-person
    tables at all."""
    person, one, two = await _two_guilds(session)
    ids = (one.id, two.id)

    await route_as(session, user_id=person.id, guild_id=one.id)

    for table in GUILD_KEYED:
        assert await _guilds_seen(session, table, ids) == {one.id}, table

    for table in PER_PERSON:
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(text(f"SELECT 1 FROM public.{table} LIMIT 1"))


async def test_the_platform_floor_reads_every_community_of_its_reader(session):
    """The guild list, a guild's picture and its sign-in rule, read before
    routing: every community the reader belongs to, and nobody else's. Every
    tier inherits the floor, so the lowest one stands for all of them."""
    person, one, two = await _two_guilds(session)
    stranger = await create_user(session)
    ids = (one.id, two.id)
    tier = UserRole.member.value

    await set_rls_context(session, Platform(user_id=person.id, tier=tier))
    for table in GUILD_KEYED:
        assert await _guilds_seen(session, table, ids) == {one.id, two.id}, table

    await set_rls_context(session, Platform(user_id=stranger.id, tier=tier))
    for table in GUILD_KEYED:
        assert await _guilds_seen(session, table, ids) == set(), table
