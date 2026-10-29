"""What an operator has granted one guild.

The single read of ``guild_administration.auth_options``. Both the management
gates and the just-in-time provisioning check come through here, so "has this
guild been granted X" is one query with one answer.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.guild_auth_options import CommunityAuthOption, effective_options
from app.core.messages import GuildMessages
from app.models.platform.guild_administration import GuildAdministration


async def auth_options_for(
    session: AsyncSession, guild_id: int
) -> frozenset[CommunityAuthOption]:
    """The sign-in options this guild holds. Empty when it holds none, and
    empty when it has no administration row at all — a guild nobody has granted
    anything is the same as a guild with nothing granted.

    What is stored goes through :func:`effective_options`, so an option ticked
    under a master nobody granted reads here the way it reads everywhere."""
    administration = (
        await session.exec(
            select(GuildAdministration).where(GuildAdministration.guild_id == guild_id)
        )
    ).one_or_none()
    if administration is None:
        return frozenset()
    return effective_options(administration.auth_options)


def holds_option(guild_id: Any, option: CommunityAuthOption) -> ColumnElement[bool]:
    """Whether a rule that needs ``option`` applies to the community:
    ``public.guild_holds_option``, the answer the sign-in gate gives. True
    unless the row the session reads shows the option withdrawn."""
    return func.public.guild_holds_option(guild_id, option.value)


async def has_auth_option(
    session: AsyncSession, guild_id: int, option: CommunityAuthOption
) -> bool:
    return option in await auth_options_for(session, guild_id)


async def require_auth_option(
    session: AsyncSession, guild_id: int, option: CommunityAuthOption
) -> None:
    """One operator-granted sign-in option, or 404.

    This bounds *management* only. Withdrawing an option closes the surface
    that sets it up; it never deletes providers, and keeps existing members
    signing in through them. What the community had set under it stays set,
    and stops applying until the option is granted again.
    """
    if not await has_auth_option(session, guild_id, option):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_AUTH_NOT_ENABLED,
        )
