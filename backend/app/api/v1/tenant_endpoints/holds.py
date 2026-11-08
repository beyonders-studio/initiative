"""Holds: content kept in place for the platform.

- ``POST /holds`` — hold something. A community moderator holds it *for the
  platform*, which opens a moderation case; a platform moderator under a
  ``moderate`` grant holds it against a case.
- ``GET /holds`` — the holds in the community, for a ``moderate`` grantee.
  Anyone else is refused: the record is the platform's.
- ``POST /holds/{hold_id}/release`` — end a hold, under a ``moderate`` grant.

See ``app.services.platform.holds``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.core.messages import HoldMessages
from app.core.moderation import HoldReason, HoldRelease, HoldVia, LegalBasis
from app.models.platform.user import User
from app.schemas.tenant.hold import (
    ContentHoldRead,
    HoldCreate,
    HoldPlaced,
    HoldReleaseCreate,
)
from app.services.platform import holds as holds_service

router = APIRouter()


def _read(view: holds_service.HoldView) -> ContentHoldRead:
    hold = view.hold
    return ContentHoldRead(
        id=int(hold.id),  # type: ignore[arg-type]
        target_type=hold.target_type,
        target_id=hold.target_id,
        label=view.label,
        case_task_id=hold.case_task_id,
        placed_via=HoldVia(hold.placed_via),
        reason=HoldReason(hold.reason),
        legal_basis=LegalBasis(hold.legal_basis) if hold.legal_basis else None,
        note=view.note,
        placed_at=hold.placed_at,
        released_at=hold.released_at,
        release_outcome=(
            HoldRelease(hold.release_outcome) if hold.release_outcome else None
        ),
    )


@router.post("", response_model=HoldPlaced, status_code=status.HTTP_201_CREATED)
async def place_hold(
    payload: HoldCreate,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> HoldPlaced:
    """Hold something for the platform. From now on it reads as absent to the
    whole community, whoever held it included."""
    await holds_service.place(
        session,
        guild_context,
        guild_id=guild_context.guild_id,
        placed_by=current_user.id,
        request=holds_service.HoldRequest(
            target_type=payload.target_type,
            target_id=payload.target_id,
            reason=payload.reason,
            legal_basis=payload.legal_basis,
            note=payload.note,
            case_task_id=payload.case_task_id,
        ),
    )
    return HoldPlaced()


@router.get("", response_model=list[ContentHoldRead])
async def list_holds(
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    case_task_id: int | None = Query(default=None),
    open_only: bool = Query(default=False),
) -> list[ContentHoldRead]:
    """The holds in the community, newest first, for a ``moderate``
    grantee. Anyone else is refused rather than shown none, so a reader
    without the grant is told so rather than told nothing is held."""
    if not guild_context.pam_moderate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=HoldMessages.NOT_ALLOWED
        )
    views = await holds_service.listed(
        session, case_task_id=case_task_id, open_only=open_only
    )
    return [_read(view) for view in views]


@router.post("/{hold_id}/release", response_model=ContentHoldRead)
async def release_hold(
    hold_id: int,
    payload: HoldReleaseCreate,
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> ContentHoldRead:
    """End a hold: ``restore`` it, ``remove`` it — through the community's
    moderation log, a comment to a tombstone and anything else to the trash —
    or ``purge`` it. The platform's alone, under a ``moderate`` grant."""
    hold = await holds_service.release(
        guild_context,
        guild_id=guild_context.guild_id,
        hold_id=hold_id,
        outcome=payload.outcome,
        released_by=current_user.id,
    )
    return _read(
        holds_service.HoldView(
            hold=hold,
            label=None,
            note=holds_service.open_note(hold.note),
        )
    )
