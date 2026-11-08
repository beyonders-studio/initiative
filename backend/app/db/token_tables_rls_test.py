"""Role-security test for the two token tables.

``user_tokens`` is read and written on the system engine alone: no request
floor holds a verb on it and it carries no policy. ``push_tokens`` is reached
from the platform path for the caller's own devices, and delivered from on the
system engine; the guild floors hold nothing on it.

Style mirrors ``plugin_service_registrations_rls_test``: ``SET ROLE`` drops the
superuser setup session to the role under test, so table grants and policies
are enforced as they are on a real request.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.public_rls import (
    FORCED_NO_POLICY,
    PUBLIC_RLS,
    SHARED_TABLE_REGISTRY,
    platform_tier,
    role_name,
)
from app.models.platform.user import UserRole
from app.testing import as_role, create_user

PLATFORM_FLOOR = role_name("platform_base")
REQUEST_FLOORS = ("app_user", "app_guild_base", "app_guild_base_ro", PLATFORM_FLOOR)
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")


async def _user_token(session, user_id: int) -> None:
    await session.exec(
        text(
            "INSERT INTO user_tokens (user_id, token, purpose, expires_at, created_at) "
            "VALUES (:u, :t, 'password_reset', :exp, now())"
        ),
        params={
            "u": user_id,
            "t": f"hash-{user_id}",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
    )


async def _push_token(session, user_id: int, value: str) -> None:
    await session.exec(
        text(
            "INSERT INTO push_tokens "
            "(user_id, push_token, platform, created_at, updated_at) "
            "VALUES (:u, :t, 'android', now(), now())"
        ),
        params={"u": user_id, "t": value},
    )


async def _flags(session, table: str) -> tuple[bool, bool]:
    row = (
        await session.exec(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = :name"
            ),
            params={"name": table},
        )
    ).one()
    return row[0], row[1]


def test_registry_records_the_token_tables():
    """``user_tokens`` is the system engine's alone; ``push_tokens`` is the
    platform floor's own rows and nothing of the guild floor's. The floor's
    read half reads those rows too, and writes none of them."""
    assert PUBLIC_RLS["user_tokens"] == FORCED_NO_POLICY
    user_tokens = SHARED_TABLE_REGISTRY["user_tokens"].grants
    assert user_tokens.app_user is None
    assert user_tokens.app_guild_base is None
    assert user_tokens.platform_base is None
    push_tokens = SHARED_TABLE_REGISTRY["push_tokens"].grants
    assert push_tokens.app_guild_base is None
    assert push_tokens.app_user is None
    rls = PUBLIC_RLS["push_tokens"]
    assert rls.enabled and rls.forced
    assert {p.command: p.roles for p in rls.policies} == {
        "SELECT": ("platform_base", "platform_base_ro"),
        "INSERT": ("platform_base",),
        "UPDATE": ("platform_base",),
        "DELETE": ("platform_base",),
    }


async def test_both_token_tables_force_row_security(session):
    for table in ("user_tokens", "push_tokens"):
        assert await _flags(session, table) == (True, True), table


async def test_no_request_floor_holds_a_verb_on_user_tokens(session):
    for role in REQUEST_FLOORS:
        for verb in VERBS:
            held = (
                await session.exec(
                    text("SELECT has_table_privilege(:r, 'public.user_tokens', :v)"),
                    params={"r": role, "v": verb},
                )
            ).scalar_one()
            assert not held, f"{role} holds {verb} on user_tokens"


@pytest.mark.parametrize(
    "role",
    [
        "app_user",
        "app_guild_base",
        "app_guild_base_ro",
        UserRole.member,
        UserRole.owner,
    ],
)
async def test_user_tokens_are_unreadable_on_the_request_path(session, role):
    """The token's own account included: every request floor is refused."""
    # The tier roles carry a per-run prefix, so they are named here rather than
    # in the ids, which every worker must collect alike.
    if isinstance(role, UserRole):
        role = role_name(platform_tier(role))
    owner = await create_user(session)
    await _user_token(session, owner.id)
    seen = (await session.exec(text("SELECT count(*) FROM user_tokens"))).scalar_one()
    assert seen >= 1

    async with as_role(session, role, owner.id):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(text("SELECT token FROM user_tokens"))


async def test_the_guild_floors_hold_nothing_on_push_tokens(session):
    for role in ("app_guild_base", "app_guild_base_ro", "app_user"):
        for verb in VERBS:
            held = (
                await session.exec(
                    text("SELECT has_table_privilege(:r, 'public.push_tokens', :v)"),
                    params={"r": role, "v": verb},
                )
            ).scalar_one()
            assert not held, f"{role} holds {verb} on push_tokens"

    owner = await create_user(session)
    await _push_token(session, owner.id, "fcm-guild-floor")
    async with as_role(session, "app_guild_base", owner.id):
        with pytest.raises(DBAPIError):
            async with session.begin_nested():
                await session.exec(text("SELECT push_token FROM push_tokens"))


async def test_a_platform_tier_reaches_only_its_own_push_tokens(session):
    """Own rows are listed, registered, re-registered and removed; another
    account's are neither seen nor touched, at every tier."""
    me = await create_user(session)
    other = await create_user(session)
    await _push_token(session, other.id, "fcm-theirs")

    for tier in UserRole:
        mine = f"fcm-mine-{tier.value}"
        async with as_role(session, role_name(platform_tier(tier)), me.id):
            async with session.begin_nested():
                await _push_token(session, me.id, mine)
                # The registration upsert: conflicts on its own row and returns it.
                upserted = (
                    await session.exec(
                        text(
                            "INSERT INTO push_tokens "
                            "(user_id, push_token, platform, created_at, updated_at) "
                            "VALUES (:u, :t, 'ios', now(), now()) "
                            "ON CONFLICT (user_id, push_token) "
                            "DO UPDATE SET platform = EXCLUDED.platform "
                            "RETURNING platform"
                        ),
                        params={"u": me.id, "t": mine},
                    )
                ).scalar_one()
                assert upserted == "ios"

                visible = {
                    row[0]
                    for row in (
                        await session.exec(text("SELECT user_id FROM push_tokens"))
                    ).all()
                }
                assert visible == {me.id}, tier

                touched = (
                    await session.exec(
                        text("DELETE FROM push_tokens WHERE push_token = 'fcm-theirs'")
                    )
                ).rowcount
                assert touched == 0, tier
                touched = (
                    await session.exec(
                        text(
                            "UPDATE push_tokens SET platform = 'x' WHERE user_id = :u"
                        ),
                        params={"u": other.id},
                    )
                ).rowcount
                assert touched == 0, tier

                removed = (
                    await session.exec(
                        text("DELETE FROM push_tokens WHERE push_token = :t"),
                        params={"t": mine},
                    )
                ).rowcount
                assert removed == 1, tier

            with pytest.raises(DBAPIError):
                async with session.begin_nested():
                    await _push_token(session, other.id, f"fcm-for-them-{tier.value}")

    theirs = (
        await session.exec(
            text("SELECT platform FROM push_tokens WHERE push_token = 'fcm-theirs'")
        )
    ).scalar_one()
    assert theirs == "android"
