"""Emoji reactions, one route set for every reactable kind.

``/reactions/{target_type}/{target_id}`` is generic on purpose: the kind is a
path segment resolved through the service registry, so the next reactable thing
gets these endpoints for free instead of a parallel set of its own.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
)
from app.core.reactions import ReactionTarget
from app.models.platform.user import User
from app.schemas.tenant.reaction import (
    SUGGESTED_EMOJI,
    ReactionSummary,
    ReactionToggle,
)
from app.services.tenant import reactions as reactions_service

router = APIRouter()


@router.get("/suggested", response_model=list[str])
async def suggested_reactions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[str]:
    """The emoji every reaction picker offers first.

    Served rather than hard-coded in the client so the set is one decision for
    the whole product — the same row appears on every surface, for everyone,
    instead of whatever each browser happened to pick last. The list itself is
    the same for every guild; the dependencies are the auth and path gates
    every route under here carries.
    """
    return list(SUGGESTED_EMOJI)


@router.put(
    "/{target_type}/{target_id}",
    response_model=ReactionSummary,
)
async def toggle_reaction(
    target_type: ReactionTarget,
    target_id: int,
    payload: ReactionToggle,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ReactionSummary:
    """Add this emoji, or take it back if it is already yours.

    A toggle rather than separate add/remove routes: the client already knows
    whether the chip is pressed, and one idempotent-per-intent call removes the
    race where a double tap leaves a reaction it meant to clear.
    """
    summary, _added = await reactions_service.toggle_reaction(
        session,
        target=target_type,
        target_id=target_id,
        emoji=payload.emoji,
        user=current_user,
        guild_id=guild_context.guild_id,
    )

    await session.commit()
    return summary
