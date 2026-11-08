"""The SPA storage-usage read backing the guild usage panel.

Invariants: it returns the guild-scoped SUM(uploads.size_bytes); it is read
on the settings surface by its admin rung — an administrator, or a settings
grant at either rung, which is how support holding the seat sees the Usage tab
(the guild-wide total, like ``status``, is not disclosed to regular members);
and a non-member can't reach another guild's usage at all.
"""

from __future__ import annotations

import pytest
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.access_grant import AccessGrantPurpose, SettingsLevel
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.testing import (
    create_access_grant,
    create_upload,
    create_user,
    get_auth_headers,
)


async def test_storage_usage_sums_guild_bytes(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Every file counts, including one the admin cannot read: another
    member's that is not saved anywhere yet."""
    a = await acting_user(guild_role=CommunityRole.admin)
    other = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
    await create_upload(session, a.guild, a.user, size_bytes=2048)
    await create_upload(session, a.guild, a.user, size_bytes=52)
    await create_upload(session, a.guild, other.user, size_bytes=900)

    response = await client.get(a.g("/storage/usage"), headers=a.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"community_id": a.guild.id, "usage_bytes": 3000}


async def test_storage_usage_zero_for_empty_guild(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.admin)
    response = await client.get(a.g("/storage/usage"), headers=a.headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"community_id": a.guild.id, "usage_bytes": 0}


async def test_storage_usage_requires_guild_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A regular member of the SAME guild is refused — the guild-wide total
    is an admin-settings figure, not member-visible data."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    await create_upload(session, admin.guild, admin.user, size_bytes=999)

    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    response = await client.get(member.g("/storage/usage"), headers=member.headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "COMMUNITY_ADMIN_REQUIRED"


async def test_storage_usage_requires_membership(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A user who isn't in the guild can't read its usage — RLS hides the
    guild (404)."""
    owner = await acting_user(guild_role=CommunityRole.admin)
    await create_upload(session, owner.guild, owner.user, size_bytes=999)

    outsider = await acting_user(guild_role=CommunityRole.member)  # a different guild
    response = await client.get(
        f"/api/v1/c/{owner.guild.id}/storage/usage", headers=outsider.headers
    )
    assert response.status_code in (403, 404)


@pytest.mark.parametrize("rung", [SettingsLevel.superadmin, SettingsLevel.admin])
@pytest.mark.parametrize("with_content_grant", [True, False])
async def test_a_settings_grantee_reads_the_usage_the_tab_shows_them(
    client: AsyncClient, session: AsyncSession, acting_user, rung, with_content_grant
):
    """Support lent the seat opens the Usage tab, so the figure on it is theirs
    to read — with or without a content grant beside the settings one."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    await create_upload(session, admin.guild, admin.user, size_bytes=1234)
    support = await create_user(session, role=UserRole.support)
    if with_content_grant:
        await create_access_grant(session, user=support, guild=admin.guild)
    await create_access_grant(
        session,
        user=support,
        guild=admin.guild,
        access_level=rung.value,
        purpose=AccessGrantPurpose.settings.value,
    )

    response = await client.get(
        f"/api/v1/c/{admin.guild.id}/storage/usage", headers=get_auth_headers(support)
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"community_id": admin.guild.id, "usage_bytes": 1234}


async def test_a_content_grant_alone_does_not_read_usage(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Reaching the community's content is not reaching its settings."""
    admin = await acting_user(guild_role=CommunityRole.admin)
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session, user=support, guild=admin.guild, access_level="read_write"
    )

    response = await client.get(
        f"/api/v1/c/{admin.guild.id}/storage/usage", headers=get_auth_headers(support)
    )
    assert response.status_code == 403, response.text
