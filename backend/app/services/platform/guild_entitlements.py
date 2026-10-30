"""Which sign-in options one community's plan gives it.

The single read of the two paid switches behind ``CommunityAuthOption``
(``app.core.rules.OPTION_RULES``), deployment rows of ``community_rules``. The
management gates come through here, so "has this community been granted X" is
one query with one answer.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.guild_auth_options import CommunityAuthOption
from app.core.messages import GuildMessages
from app.core.rules import OPTION_RULES, SetBy
from app.models.platform.rule import CommunityRule


async def auth_options_for(
    session: AsyncSession, guild_id: int
) -> frozenset[CommunityAuthOption]:
    """The sign-in options this community holds. Empty when it holds none: a
    community nobody has granted anything has no row for either."""
    held = set(
        (
            await session.exec(
                select(CommunityRule.key).where(
                    CommunityRule.guild_id == guild_id,
                    CommunityRule.key.in_(OPTION_RULES.values()),  # type: ignore[attr-defined]
                    CommunityRule.user_id.is_(None),  # type: ignore[union-attr]
                    CommunityRule.set_by == SetBy.deployment.value,
                    CommunityRule.enabled.is_(True),  # type: ignore[union-attr]
                )
            )
        ).all()
    )
    return frozenset(option for option, key in OPTION_RULES.items() if key in held)


def holds_option(guild_id: Any, option: CommunityAuthOption) -> ColumnElement[bool]:
    """Whether a rule that needs ``option`` applies to the community:
    ``public.guild_holds_option``, the answer the sign-in gate gives, over the
    option's paid key (``app.core.rules.OPTION_RULES``)."""
    return func.public.guild_holds_option(guild_id, OPTION_RULES[option])


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
