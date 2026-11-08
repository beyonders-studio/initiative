"""Tests for the ``support`` guild role — the first-class identity a scoped
PAM grantee assumes inside a guild it isn't a member of.

Covers:
- the resolver synthesizes ``support`` for a scoped grant and ``admin`` for a
  break-glass grant (identity);
- the guild settings surface (guild AI settings) answers a grantee holding the
  seat's rung, with what they may do there bound by their content grant's
  read/write level at the Postgres role layer;
- ``support`` is never an assignable stored membership role.
"""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import _load_guild_context
from app.core.messages import AccessGrantMessages, GuildMessages
from app.models.platform.access_grant import (
    AccessGrant,
    AccessGrantPurpose,
    SettingsLevel,
)
from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.platform.user import UserRole
from app.testing import (
    create_guild,
    create_user,
    get_auth_headers,
)

AI_SETTINGS = "/ai/connections"


async def _live_grant(
    session: AsyncSession,
    *,
    user,
    guild,
    level: str = "read",
    purpose: AccessGrantPurpose = AccessGrantPurpose.content,
) -> AccessGrant:
    now = datetime.now(UTC)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=level,
        purpose=purpose.value,
        status="approved",
        reason="ticket",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=user.id,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    session.add(grant)
    await session.commit()
    return grant


async def _live_settings_grant(
    session: AsyncSession, *, user, guild, rung: SettingsLevel
) -> AccessGrant:
    """The second grant, on the other axis: what of the community's own
    configuration this request may work, and nothing about its content."""
    return await _live_grant(
        session,
        user=user,
        guild=guild,
        level=rung.value,
        purpose=AccessGrantPurpose.settings,
    )


def _ai_url(guild_id: int) -> str:
    return f"/api/v1/c/{guild_id}/settings{AI_SETTINGS}"


# ---------------------------------------------------------------------------
# identity: which role the resolver synthesizes
# ---------------------------------------------------------------------------


async def test_scoped_grant_synthesizes_support_role(session: AsyncSession):
    """A scoped PAM grant (support/moderator's request→approve flow, no
    data.bypass) resolves to the ``support`` role, not a ``member`` masquerade."""
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=guild, level="read")

    ctx = await _load_guild_context(session, support, guild.id)
    assert ctx.role == CommunityRole.support
    assert ctx.is_pam is True


async def test_an_operators_own_grant_is_support_too(session: AsyncSession):
    """Self-issued, read_write, held by a ``data.bypass`` operator — and it
    resolves exactly as support's does. What a grant reaches is what the grant
    says, not who holds it."""
    operator = await create_user(session, role=UserRole.operator)
    other = await create_user(session, role=UserRole.owner)
    guild2 = await create_guild(session, creator=other)  # operator is NOT a member
    await _live_grant(session, user=operator, guild=guild2, level="read_write")

    ctx = await _load_guild_context(session, operator, guild2.id)
    assert ctx.role == CommunityRole.support
    assert ctx.is_pam is True


# ---------------------------------------------------------------------------
# the settings surface: the seat's rung admits, the content grant bounds
# ---------------------------------------------------------------------------
#
# Two grants on two axes, and this surface asks both. The guild path is reached
# on the CONTENT grant — that is what makes a non-member a ``support`` identity
# in this guild at all — and the AI connections it leads to are the seat's, so
# the SETTINGS grant has to stand at the ``superadmin`` rung. What the grantee
# may then do there is the content grant's read/write level, which the Postgres
# role the session assumes carries.


async def test_a_content_grant_alone_does_not_reach_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Reaching the community's content is not reaching what configures it.

    The two axes are asked for separately and answered separately, so a grant
    on one says nothing about the other.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=admin.guild, level="read_write")

    resp = await client.get(_ai_url(admin.guild.id), headers=get_auth_headers(support))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED


async def test_support_read_grant_reads_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A grantee holding the seat's rung can READ the guild AI settings
    surface (the connection list)."""
    admin = await acting_user(guild_role=CommunityRole.admin)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=admin.guild, level="read")
    await _live_settings_grant(
        session, user=support, guild=admin.guild, rung=SettingsLevel.superadmin
    )

    resp = await client.get(_ai_url(admin.guild.id), headers=get_auth_headers(support))
    assert resp.status_code == 200, resp.text


async def test_the_admin_rung_does_not_reach_the_ai_settings_surface(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Two rungs on the settings axis, and this surface is the upper one's.

    What a community hands an AI provider is the same kind of question as who
    may sign in to it, so it answers to the seat rather than to running the
    place day to day.
    """
    admin = await acting_user(guild_role=CommunityRole.admin)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=admin.guild, level="read")
    await _live_settings_grant(
        session, user=support, guild=admin.guild, rung=SettingsLevel.admin
    )

    resp = await client.get(_ai_url(admin.guild.id), headers=get_auth_headers(support))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED


async def test_support_read_grant_cannot_write_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The seat's rung admits them to read; changing a connection asks for a
    read_write content grant beside it, so a read grant is refused by name."""
    admin = await acting_user(guild_role=CommunityRole.admin)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=admin.guild, level="read")
    await _live_settings_grant(
        session, user=support, guild=admin.guild, rung=SettingsLevel.superadmin
    )

    resp = await client.post(
        _ai_url(admin.guild.id),
        headers=get_auth_headers(support),
        json={"label": "x", "provider": "openai"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == AccessGrantMessages.WRITE_GRANT_REQUIRED


async def test_support_read_write_grant_writes_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A read_write content grant beside the seat's rung — held by a non-bypass
    user, so NOT break-glass — can WRITE the guild AI settings surface (the
    guild_<id>_support role has DML on guild_ai_connections; a read grant on
    _ro does not)."""
    admin = await acting_user(guild_role=CommunityRole.admin)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=admin.guild, level="read_write")
    await _live_settings_grant(
        session, user=support, guild=admin.guild, rung=SettingsLevel.superadmin
    )

    resp = await client.post(
        _ai_url(admin.guild.id),
        headers=get_auth_headers(support),
        json={"label": "Team", "provider": "openai"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["label"] == "Team"


async def test_plain_member_still_denied_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A plain member is denied, so none of the above loosened the surface for
    the community's own ordinary members."""
    a = await acting_user(guild_role=CommunityRole.member)
    resp = await client.get(_ai_url(a.guild.id), headers=a.headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED


# ---------------------------------------------------------------------------
# support is synthesized-only: never an assignable stored role
# ---------------------------------------------------------------------------


async def test_guild_admin_cannot_assign_support_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The member-facing role endpoint rejects ``support``: it is synthesized
    for a grant and never stored as a membership role."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    resp = await client.patch(
        f"/api/v1/communities/{admin.guild.id}/members/{member.user.id}",
        headers=admin.headers,
        json={"role": "support"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE


# ---------------------------------------------------------------------------
# guild role changes: admin-only, and the write runs on the system engine
# ---------------------------------------------------------------------------


async def test_guild_admin_can_promote_member_to_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin still promotes a member — the role write now runs on the
    system engine (the guild role holds no UPDATE on guild_memberships)."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    guild_id = admin.guild.id
    member_user_id = member.user.id

    resp = await client.patch(
        f"/api/v1/communities/{guild_id}/members/{member_user_id}",
        headers=admin.headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 204

    session.expire_all()
    updated = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == member_user_id,
            )
        )
    ).one()
    assert updated.role == CommunityRole.admin


async def test_plain_member_cannot_change_guild_roles(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A plain member cannot promote anyone — the guild-admin gate holds, and the
    shared guild role no longer has a DB write to fall back on."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    other = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)

    resp = await client.patch(
        f"/api/v1/communities/{admin.guild.id}/members/{other.user.id}",
        headers=member.headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == GuildMessages.COMMUNITY_ADMIN_REQUIRED
