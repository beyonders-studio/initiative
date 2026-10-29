"""The community's own configuration is written by whoever administers it.

A membership row's administrator writes what it administers. A settings grant
reads at its rung, and writes only beside a read_write content grant — the two
asks together. Each test writes on the real request login, routed through the
seam, and carries no guard of its own: what the database accepts is what the
policies allow.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import DBAPIError
from sqlmodel import select

from app.models.platform.guild import GuildInvite, CommunityRole
from app.models.platform.rule import CommunityRule
from app.models.platform.user import UserRole
from app.testing import (
    create_access_grant,
    create_auth_provider,
    create_guild_auth_policy,
    create_user,
    route_as,
)


def _invite(guild_id: int, user_id: int, code: str) -> GuildInvite:
    return GuildInvite(
        code_hash=code, guild_id=guild_id, created_by=user_id, max_uses=1
    )


async def _writing_as(role_session, *, user_id: int, guild_id: int, settings=False):
    """A request-login session routed into the community, as a request is."""
    s = await role_session("app_user")
    await route_as(s, user_id=user_id, guild_id=guild_id, settings=settings)
    return s


async def _invite_exists(session, code: str) -> bool:
    row = (
        await session.exec(select(GuildInvite).where(GuildInvite.code_hash == code))
    ).first()
    return row is not None


async def test_a_member_neither_reads_nor_writes_an_invite(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    session.add(_invite(a.guild.id, a.user.id, "issued-by-the-admin"))
    await session.commit()
    member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    s = await _writing_as(role_session, user_id=member.user.id, guild_id=a.guild.id)
    assert list(await s.exec(select(GuildInvite.code_hash))) == []
    s.add(_invite(a.guild.id, member.user.id, "by-a-member"))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.commit()
    await s.rollback()
    assert not await _invite_exists(session, "by-a-member")


async def test_the_administrator_reads_and_writes_an_invite(
    session, acting_user, role_session
):
    a = await acting_user(guild_role=CommunityRole.admin)
    s = await _writing_as(role_session, user_id=a.user.id, guild_id=a.guild.id)
    s.add(_invite(a.guild.id, a.user.id, "by-the-admin"))
    await s.commit()
    assert await _invite_exists(session, "by-the-admin")
    assert list(await s.exec(select(GuildInvite.code_hash))) == ["by-the-admin"]


async def test_a_settings_grant_reads_invites_and_does_not_write_them(
    session, acting_user, role_session
):
    """A settings rung reads what a guild admin administers."""
    a = await acting_user(guild_role=CommunityRole.admin)
    session.add(_invite(a.guild.id, a.user.id, "issued-by-the-admin"))
    await session.commit()
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session, user=support, guild=a.guild, access_level="admin", purpose="settings"
    )
    s = await _writing_as(
        role_session, user_id=support.id, guild_id=a.guild.id, settings=True
    )
    assert list(await s.exec(select(GuildInvite.code_hash))) == ["issued-by-the-admin"]
    s.add(_invite(a.guild.id, support.id, "by-a-settings-grant"))
    with pytest.raises(DBAPIError, match="permission denied|row-level security"):
        await s.commit()
    await s.rollback()
    assert not await _invite_exists(session, "by-a-settings-grant")


async def test_a_settings_grant_beside_read_write_writes_an_invite(
    session, acting_user, role_session
):
    """The two asks together: the rung names the surface, the read_write grant
    lets it be changed."""
    a = await acting_user(guild_role=CommunityRole.admin)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session, user=support, guild=a.guild, access_level="admin", purpose="settings"
    )
    await create_access_grant(
        session, user=support, guild=a.guild, access_level="read_write"
    )
    s = await _writing_as(
        role_session, user_id=support.id, guild_id=a.guild.id, settings=True
    )
    s.add(_invite(a.guild.id, support.id, "by-the-pair"))
    await s.commit()
    assert await _invite_exists(session, "by-the-pair")


#: The members' sign-in requirement, which is a row only where it asks something.
_REQUIREMENT = (CommunityRule.key == "auth_policy", CommunityRule.user_id.is_(None))


async def _sign_in_rule(session, guild_id: int) -> str:
    asks = (
        await session.exec(
            select(CommunityRule.id).where(
                CommunityRule.guild_id == guild_id, *_REQUIREMENT
            )
        )
    ).first()
    return "open" if asks is None else "required"


async def _seat_session(role_session, *, user_id: int, guild_id: int):
    s = await role_session("app_user")
    await route_as(s, user_id=user_id, guild_id=guild_id, seat=True)
    return s


async def test_a_lent_seat_changes_the_sign_in_rule_only_beside_read_write(
    session, acting_user, role_session
):
    """The seat's own write, lent for a window: read on the rung alone, and
    changed once a read_write grant stands beside it."""
    a = await acting_user(guild_role=CommunityRole.superadmin)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_auth_policy(session, a.guild, provider)
    before = await _sign_in_rule(session, a.guild.id)
    assert before != "open"
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session,
        user=support,
        guild=a.guild,
        access_level="superadmin",
        purpose="settings",
    )

    s = await _seat_session(role_session, user_id=support.id, guild_id=a.guild.id)
    assert (await s.exec(select(CommunityRule.id).where(*_REQUIREMENT))).first()
    await s.exec(
        delete(CommunityRule).where(CommunityRule.guild_id == a.guild.id, *_REQUIREMENT)
    )
    await s.commit()
    assert await _sign_in_rule(session, a.guild.id) == before

    await create_access_grant(
        session, user=support, guild=a.guild, access_level="read_write"
    )
    s = await _seat_session(role_session, user_id=support.id, guild_id=a.guild.id)
    await s.exec(
        delete(CommunityRule).where(CommunityRule.guild_id == a.guild.id, *_REQUIREMENT)
    )
    await s.commit()
    assert await _sign_in_rule(session, a.guild.id) == "open"


async def test_a_content_grant_does_not_write_an_invite(
    session, acting_user, role_session
):
    """A content grant reaches the work, not the roster."""
    a = await acting_user(guild_role=CommunityRole.admin)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session, user=support, guild=a.guild, access_level="read_write"
    )
    s = await _writing_as(role_session, user_id=support.id, guild_id=a.guild.id)
    s.add(_invite(a.guild.id, support.id, "by-a-content-grant"))
    with pytest.raises(DBAPIError, match="row-level security"):
        await s.commit()
    await s.rollback()
    assert not await _invite_exists(session, "by-a-content-grant")
