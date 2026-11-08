"""The operator's side of agreeing a community's claim values.

The same question support answers through the case, in the place a deployment
running no intake can reach it. One service so both surfaces give the same
answer and record it the same way.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AuthProviderMessages
from app.models.platform.auth_provider import AuthProvider
from app.models.platform.guild import CommunityStatus, Guild
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.schemas.platform.settings import CommunityNarrowingPending
from app.services.auth import narrowing_approval


def _pending(
    connection: GuildProviderConnection, guild: Guild, provider: AuthProvider
) -> CommunityNarrowingPending:
    return CommunityNarrowingPending(
        connection_id=connection.id,
        community_id=connection.guild_id,
        community_name=guild.name,
        provider_display_name=provider.display_name,
        claim=connection.claim or "",
        claim_values=list(connection.claim_values or ()),
        auto_join=connection.auto_join,
        agreed=connection.narrowing_approved_at is not None,
    )


async def pending_for_guild(
    session: AsyncSession, *, guild_id: int
) -> list[CommunityNarrowingPending]:
    """Every narrowing this community has written, answered or not."""
    guild = await session.get(Guild, guild_id)
    if guild is None:
        return []
    rows = (
        await session.exec(
            select(GuildProviderConnection)
            .where(GuildProviderConnection.guild_id == guild_id)
            .where(GuildProviderConnection.claim.is_not(None))
            .order_by(GuildProviderConnection.id)
        )
    ).all()
    out: list[CommunityNarrowingPending] = []
    for row in rows:
        provider = await session.get(AuthProvider, row.provider_id)
        if provider is not None:
            out.append(_pending(row, guild, provider))
    return out


async def unanswered(session: AsyncSession) -> list[CommunityNarrowingPending]:
    """Every community's claim still waiting for an answer, oldest first.

    One list across the deployment, so whoever answers them does not have to
    visit each community to find out which ones are asking.
    """
    rows = (
        await session.exec(
            select(GuildProviderConnection, Guild, AuthProvider)
            .join(Guild, Guild.id == GuildProviderConnection.guild_id)
            .join(AuthProvider, AuthProvider.id == GuildProviderConnection.provider_id)
            .where(
                GuildProviderConnection.enabled.is_(True),
                GuildProviderConnection.claim.is_not(None),
                GuildProviderConnection.narrowing_approved_at.is_(None),
                Guild.status != CommunityStatus.deleted,
            )
            .order_by(GuildProviderConnection.created_at, GuildProviderConnection.id)
        )
    ).all()
    return [_pending(row, guild, provider) for row, guild, provider in rows]


async def agree(
    session: AsyncSession,
    *,
    guild_id: int,
    connection_id: int,
    agreed: bool,
    actor_user_id: int,
) -> CommunityNarrowingPending:
    """Answer one community's claim. 404 where the connection is not theirs."""
    row = (
        await session.exec(
            select(GuildProviderConnection).where(
                GuildProviderConnection.id == connection_id,
                GuildProviderConnection.guild_id == guild_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthProviderMessages.CONNECTION_NOT_FOUND,
        )
    row = await narrowing_approval.agree(
        session, connection_id, agreed=agreed, actor_user_id=actor_user_id
    )
    guild = await session.get(Guild, guild_id)
    provider = await session.get(AuthProvider, row.provider_id)
    assert guild is not None and provider is not None
    return _pending(row, guild, provider)
