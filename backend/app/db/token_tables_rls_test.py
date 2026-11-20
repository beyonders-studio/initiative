"""Role-security test for ``push_tokens``.

It is reached from the platform path for the caller's own devices, and
delivered from on the system engine; the guild floors hold nothing on it.

Style mirrors ``plugin_service_registrations_rls_test``: ``SET ROLE`` drops the
superuser setup session to the role under test, so table grants and policies
are enforced as they are on a real request.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db.public_rls import (
    platform_tier,
    role_name,
)
from app.models.platform.user import UserRole
from app.testing import as_role, create_user


async def _push_token(session, user_id: int, value: str) -> None:
    await session.exec(
        text(
            "INSERT INTO push_tokens "
            "(user_id, push_token, platform, created_at, updated_at) "
            "VALUES (:u, :t, 'android', now(), now())"
        ),
        params={"u": user_id, "t": value},
    )


async def test_the_guild_floors_hold_nothing_on_push_tokens(session):
    owner = await create_user(session)
    await _push_token(session, owner.id, "fcm-guild-floor")
    for role in ("app_guild_base", "app_guild_base_ro", "app_user"):
        async with as_role(session, role, owner.id):
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
