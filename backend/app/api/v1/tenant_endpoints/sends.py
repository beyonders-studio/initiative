"""Sending somebody something: a line in their bell that opens it.

A person's own route: a plug-in sends nothing. Who may be told, and what the
line may name, is ``app.services.tenant.sends``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.models.platform.user import User
from app.schemas.tenant.send import SendCreate, SendResult
from app.services.tenant import sends as sends_service

router = APIRouter()


@router.post("/", response_model=SendResult)
async def send(
    payload: SendCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> SendResult:
    """Point people in this community at one thing, with a note if there is
    one. Whoever can't open it is let in at ``level`` where the sender may
    share it, or else told it is there and may ask for it — if they are in its
    initiative. Anybody outside it refuses the send (404)."""
    sent = await sends_service.send(
        session,
        sender=current_user,
        context=guild_context,
        kind=payload.kind.value,
        entity_id=payload.entity_id,
        user_ids=payload.user_ids,
        note=(payload.note or "").strip() or None,
        level=payload.level,
    )
    await session.commit()
    return SendResult(sent=sent.sent, let_in=sent.let_in, may_ask=sent.may_ask)
