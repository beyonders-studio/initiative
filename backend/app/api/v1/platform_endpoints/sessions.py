"""The account's own list of where it is signed in, and the way to end one.

Mounted on ``/auth`` beside the routes that open a session, because this is
the other end of the same thing: sign-in writes a row here, and this is where
somebody reads the rows back and closes one they do not recognise.

**Runs on the system engine** (``SystemSessionDep``), filtered by the
authenticated user. ``auth_sessions`` is reached that way everywhere — the
request path is granted nothing on it — and the filter is what makes this the
account's own list rather than a view of the table. What comes back carries no
refresh-token hash; :class:`~app.services.auth.sessions.LiveSession` selects
the columns a person needs to recognise their own laptop and no others.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import (
    AccountHolder,
    require_first_party_session,
    SystemSessionDep,
    NotDemoSample,
)
from app.api.v1.platform_endpoints.session_opening import current_session_row
from app.core.audit_events import AuditEventType
from app.core.messages import AuthMessages
from app.core.user_agents import describe, kind_of
from app.models.platform.auth_session import AuthSession
from app.schemas.platform.auth import SignedInSessionInfo
from app.services import audit as audit_service
from app.services.auth import sessions as session_service
from app.services.content_sockets import sockets as content_sockets
from app.services.platform import dm_transport

router = APIRouter()

#: The account's own sign-ins are listed and ended by the person, in a session of
#: their own, not through a standing credential.
FirstPartyOnly = Annotated[str, Depends(require_first_party_session)]


@router.get(
    "/sessions", response_model=list[SignedInSessionInfo], dependencies=[NotDemoSample]
)
async def list_my_sessions(
    request: Request,
    system_session: SystemSessionDep,
    current_user: AccountHolder,
    _first_party: FirstPartyOnly,
) -> list[SignedInSessionInfo]:
    """Every session this account can still use, newest activity first, each
    beside the message device that collects under it, then the message devices
    no live session names.

    Each row is one sign-in rather than one renewal — the service walks each
    live session back to the sign-in it descends from, so a browser left open
    for a month says so. A key store names the live row its sign-in has
    reached, which is the one listed here.
    """
    current = current_session_row(request)
    rows = await session_service.list_live_for_user(
        system_session, user_id=current_user.id
    )
    devices = await dm_transport.devices_of(system_session, current_user.id)
    by_session = {d.session_id: d.id for d in devices if d.session_id is not None}
    live = {row.id for row in rows}
    return [
        *(
            SignedInSessionInfo(
                id=row.id,
                message_device_id=by_session.get(row.id),
                device=row.device,
                # A device signs in with a name; a browser does not, so its
                # name is read from what it said about itself.
                label=row.device_name or describe(row.user_agent),
                kind=kind_of(row.user_agent),
                ip=row.ip,
                started_at=row.started_at,
                last_used_at=row.last_used_at,
                is_current=current is not None and row.id == current,
            )
            for row in rows
        ),
        *(
            SignedInSessionInfo(
                id=None,
                message_device_id=d.id,
                device=False,
                label=describe(d.label),
                kind=kind_of(d.label),
                ip=None,
                started_at=d.created_at,
                last_used_at=d.last_seen_at,
                is_current=False,
            )
            for d in devices
            if d.session_id not in live
        ),
    ]


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[NotDemoSample],
)
async def revoke_my_session(
    system_session: SystemSessionDep,
    current_user: AccountHolder,
    _first_party: FirstPartyOnly,
    session_id: uuid.UUID,
) -> None:
    """End one of the account's sessions, and withdraw the message device that
    collects under it.

    The whole rotation chain, so the session cannot renew its way out of it.
    Nothing more is encrypted to the device: a phone somebody cuts off from
    here is one they no longer trust, and a browser's keys go with its
    session.
    A session belonging to somebody else answers the same as one that does not
    exist, because the id is the only thing the caller supplied and it should
    not learn which of the two it got wrong.
    """
    row = await system_session.get(AuthSession, session_id)
    if row is None or row.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.SESSION_NOT_FOUND,
        )
    # By what the revocation ended as well as the id asked for: a renewal since
    # the list was read moved the key store to the chain's live row.
    ended = await session_service.revoke_chain(system_session, session_id=session_id)
    await dm_transport.withdraw_signed_in(
        system_session, user_id=current_user.id, session_ids=ended | {session_id}
    )
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SESSION_REVOKED,
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        target_type="auth_session",
        detail={"scope": "one"},
    )
    await system_session.commit()
    # Connections opened on the ended session close now rather than at the
    # next sweep; the account's others are re-checked and stay.
    await content_sockets.revoke_user_everywhere(current_user.id)


@router.post(
    "/sessions/revoke-others",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[NotDemoSample],
)
async def revoke_my_other_sessions(
    request: Request,
    system_session: SystemSessionDep,
    current_user: AccountHolder,
    _first_party: FirstPartyOnly,
) -> None:
    """End every session the account holds except the one asking.

    The browsers' message devices go with them; a phone or desktop app keeps
    its keys and picks up where it left off at its next sign-in, as after any
    lapse. Both tables are the system engine's, so the revocation, the
    withdrawal and the record commit together.
    """
    current = current_session_row(request)
    ended = await session_service.revoke_all_for_user(
        system_session,
        user_id=current_user.id,
        except_session_id=str(current) if current is not None else None,
    )
    await dm_transport.withdraw_signed_in(
        system_session,
        user_id=current_user.id,
        session_ids={session_id for session_id, device in ended.items() if not device},
    )
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_SESSION_REVOKED,
        actor_user_id=current_user.id,
        target_user_id=current_user.id,
        target_type="auth_session",
        detail={"scope": "others"},
    )
    await system_session.commit()
    # The connections this session opened pass the re-check; every other one
    # closes.
    await content_sockets.revoke_user_everywhere(current_user.id)
