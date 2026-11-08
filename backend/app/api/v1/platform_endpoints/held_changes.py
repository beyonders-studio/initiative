"""The change an account has waiting: reading it, cancelling it, making it now.

A risky request to make an address primary, remove an address, turn
two-factor authentication off or remove the last passkey answers ``202`` with
the change it holds (:func:`hold_change`, :func:`held_response`) rather than
making it. Every route
runs on the system engine, beside the rows a held change acts on.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CurrentUser, SystemSessionDep, require_first_party_session
from app.api.v1.platform_endpoints.session_opening import current_session_row
from app.core.messages import AuthMessages
from app.core.rate_limit import limiter
from app.models.platform.account_change_hold import AccountChangeHold, HeldChangeKind
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User
from app.schemas.platform.user import HeldChangeOutcome, HeldChangeRead
from app.services.auth import held_changes
from app.services.auth.assurance import carries_passkey

me_router = APIRouter()

#: What a route that answers with the changed row says when it holds the
#: change instead.
HELD: dict[int | str, dict[str, Any]] = {
    202: {"model": HeldChangeRead, "description": "The change waits until applies_at."}
}

#: What a route with no row to answer with says when it holds the change: the
#: same body as when it makes it, so a client reads one shape.
HELD_OUTCOME: dict[int | str, dict[str, Any]] = {
    202: {
        "model": HeldChangeOutcome,
        "description": "The change waits until held.applies_at.",
    }
}


def held_response(body: HeldChangeRead | HeldChangeOutcome) -> JSONResponse:
    """``202`` with what was held."""
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED, content=body.model_dump(mode="json")
    )


async def _read(
    system_session: AsyncSession, hold: AccountChangeHold
) -> HeldChangeRead:
    assert hold.id is not None
    return HeldChangeRead(
        id=hold.id,
        kind=hold.kind,
        subject=await held_changes.subject_of(system_session, hold),
        requested_at=hold.requested_at,
        applies_at=hold.applies_at,
    )


async def hold_change(
    request: Request,
    system_session: AsyncSession,
    user: User,
    *,
    kind: HeldChangeKind,
    address_id: int | None = None,
    passkey_id: uuid.UUID | None = None,
) -> HeldChangeRead:
    """Hold the change this request asks for, with what it has staged, and
    say what is waiting; ``409`` while another change waits."""
    session_id = current_session_row(request)
    try:
        hold = await held_changes.hold(
            system_session,
            user,
            kind=kind,
            # Named only where it is a session of this account's.
            session_id=(
                session_id
                if session_id
                and await system_session.get(AuthSession, session_id) is not None
                else None
            ),
            address_id=address_id,
            passkey_id=passkey_id,
        )
    except held_changes.ChangePending as exc:
        await system_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.ACCOUNT_CHANGE_PENDING,
        ) from exc
    return await _read(system_session, hold)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=AuthMessages.HELD_CHANGE_NOT_FOUND,
    )


@me_router.get("/held-change", response_model=HeldChangeRead | None)
async def read_held_change(
    current_user: CurrentUser,
    system_session: SystemSessionDep,
) -> HeldChangeRead | None:
    """The change this account has waiting, or nothing."""
    hold = await held_changes.pending_for_user(system_session, user_id=current_user.id)
    return await _read(system_session, hold) if hold else None


@me_router.post("/held-change/{hold_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/15minutes")
async def cancel_held_change(
    request: Request,
    hold_id: int,
    current_user: CurrentUser,
    system_session: SystemSessionDep,
    _first_party: str = Depends(require_first_party_session),
) -> Response:
    """Cancel the waiting change. Nothing about the account changes."""
    if not await held_changes.cancel(
        system_session, user_id=current_user.id, hold_id=hold_id, via="settings"
    ):
        raise _not_found()
    await system_session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post("/held-change/{hold_id}/apply", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/15minutes")
async def apply_held_change(
    request: Request,
    hold_id: int,
    current_user: CurrentUser,
    system_session: SystemSessionDep,
    _first_party: str = Depends(require_first_party_session),
) -> Response:
    """Make the waiting change now. Asks for a session proved with a passkey,
    which the passkey step-up gives; the account is told as it would be when
    the wait ends."""
    session_id = current_session_row(request)
    row = await system_session.get(AuthSession, session_id) if session_id else None
    if row is None or row.user_id != current_user.id or not carries_passkey(row.amr):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.HELD_CHANGE_NEEDS_PASSKEY,
        )
    if not await held_changes.apply(
        system_session,
        current_user,
        hold_id=hold_id,
        risky=False,
        keep_session=session_id,
    ):
        raise _not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
