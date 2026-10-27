"""Asking for something you can't open or edit, and answering.

A person's own routes: a plug-in neither asks nor answers. Who may read and
write which request is the table's row security (``app.db.guild_ddl``), and
what a reader may know is there is ``app.db.presence``.
"""

from __future__ import annotations

from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select

from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.core.messages import ShareRequestMessages
from app.core.tools import Tool
from app.models.platform.guild import GuildMembership
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.platform.user import UserSummary
from app.schemas.tenant.share_request import (
    ShareRequestAnswer,
    ShareRequestBatch,
    ShareRequestCreate,
    ShareRequestRead,
    ShareStanding,
)
from app.services.tenant import share_requests as share_requests_service

router = APIRouter()

CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


@router.get("/standing", response_model=ShareStanding)
async def read_share_standing(
    resource_type: Annotated[Tool, Query()],
    resource_id: Annotated[int, Query()],
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> ShareStanding:
    """Where the reader stands on one thing: the rung they hold, and what
    they asked for that is unanswered. 404 for something they can neither
    open nor know is there — the same answer as for nothing at all."""
    found = await share_requests_service.standing_on(
        session, tool=resource_type, resource_id=resource_id, user_id=current_user.id
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ShareRequestMessages.NOT_FOUND,
        )
    return ShareStanding(
        initiative_id=found.initiative_id, level=found.level, pending=found.pending
    )


@router.post("/", response_model=ShareRequestBatch, status_code=status.HTTP_201_CREATED)
async def create_share_request(
    payload: ShareRequestCreate,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> ShareRequestBatch:
    """Ask for one thing, or for the files of a collection or a wiki the
    reader can't open, and tell whoever answers."""
    place: Optional[tuple[str, int]] = None
    if payload.resource_id is not None:
        ids = [payload.resource_id]
    else:
        ids = await share_requests_service.hidden_files(
            session, collection_id=payload.collection_id, wiki_id=payload.wiki_id
        )
        place = (
            ("collection", payload.collection_id)
            if payload.collection_id is not None
            else ("wiki", payload.wiki_id)  # type: ignore[assignment]
        )
    made = await share_requests_service.ask(
        session,
        user=current_user,
        tool=payload.resource_type,
        resource_ids=ids,
        level=payload.level,
        message=payload.message,
    )
    batch = ShareRequestBatch(batch_id=made[0].batch_id, count=len(made))
    await session.commit()
    await share_requests_service.tell_answerers(
        guild_id=guild_context.guild_id,
        requester=current_user,
        tool=payload.resource_type,
        requests=made,
        place=place,
    )
    return batch


async def _read(session, rows) -> List[ShareRequestRead]:
    if not rows:
        return []
    names = await share_requests_service.names(
        session, [share_requests_service.ref(r) for r in rows]
    )
    requesters = {r.user_id for r in rows}
    profiles = {
        p.id: p
        for p in (
            await session.exec(
                select(MemberProfile).where(MemberProfile.id.in_(requesters))  # type: ignore[attr-defined]
            )
        ).all()
    }
    guests = dict(
        (
            await session.exec(
                select(GuildMembership.user_id, GuildMembership.guest_until).where(
                    GuildMembership.user_id.in_(requesters),  # type: ignore[attr-defined]
                    GuildMembership.guest_until.is_not(None),  # type: ignore[union-attr]
                )
            )
        ).all()
    )
    return [
        ShareRequestRead(
            id=r.id,
            batch_id=r.batch_id,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            resource_name=names.get(share_requests_service.ref(r), ""),
            initiative_id=r.initiative_id,
            user=UserSummary.model_validate(profiles[r.user_id]),
            guest_until=guests.get(r.user_id),
            level=ResourceAccessLevel(r.level),
            message=r.message,
            created_at=r.created_at,
        )
        for r in rows
        if r.user_id in profiles
    ]


@router.get("/", response_model=List[ShareRequestRead])
async def list_share_requests(
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
    batch_id: Annotated[Optional[UUID], Query()] = None,
    resource_type: Annotated[Optional[Tool], Query()] = None,
    resource_id: Annotated[Optional[int], Query()] = None,
) -> List[ShareRequestRead]:
    """The requests waiting on the reader's answer: from one ask, or on one
    thing, oldest first."""
    rows = await share_requests_service.answerable(
        session,
        user_id=current_user.id,
        batch_id=batch_id,
        tool=resource_type,
        resource_id=resource_id,
    )
    return await _read(session, rows)


@router.post("/answer", status_code=status.HTTP_204_NO_CONTENT)
async def answer_share_requests(
    payload: ShareRequestAnswer,
    session: RLSSessionDep,
    current_user: CurrentUserDep,
    guild_context: GuildContextDep,
) -> None:
    """Say yes or no to requests the reader may answer."""
    await share_requests_service.answer(
        session,
        guild_id=guild_context.guild_id,
        answerer=current_user,
        request_ids=payload.ids,
        approve=payload.approve,
        level=payload.level,
        scope=payload.scope,
        tell=payload.tell,
    )
    await session.commit()
