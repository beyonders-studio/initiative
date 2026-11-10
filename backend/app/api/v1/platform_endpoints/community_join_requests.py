"""Asking to join a ``request`` community, and its admins' answers.

The asker is in no community to route into, so asking and withdrawing run on
the system engine, as the directory's join does. The queue is the community's
own: read and answered on its settings session, where
``community_join_requests``' policies admit the holders of its members
surface. Approving claims the row there first and then writes the membership
on the system engine, which every way in does.
"""

from dataclasses import replace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    CommunityIdPath,
    GuildContext,
    SettingsRLSSessionDep,
    SystemSessionDep,
    get_current_active_user,
    require_surface,
)
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.messages import GuildMessages
from app.core.user_display import handle_of
from app.db import post_commit
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.guild import AdminSurface, CommunityJoinRequest, CommunityRole
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.schemas.platform.community_join_request import (
    CommunityJoinRequestCreate,
    CommunityJoinRequestRead,
)
from app.schemas.platform.user import UserIdentity
from app.services import audit as audit_service
from app.services import email as email_service
from app.services import notifications as notifications_service
from app.services.platform import guilds as guilds_service

router = APIRouter()

MembersContext = Annotated[
    GuildContext,
    Depends(require_surface(AdminSurface.members, settings=True)),
]
MembersWriteContext = Annotated[
    GuildContext,
    Depends(require_surface(AdminSurface.members, settings=True, write=True)),
]
CurrentUser = Annotated[User, Depends(get_current_active_user)]


@router.post(
    "/directory/{community_id}/join-requests",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def ask_to_join_community(
    guild_id: CommunityIdPath,
    payload: CommunityJoinRequestCreate,
    session: SystemSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Ask a listed ``request`` community to let the caller in. Asking again
    while a request waits changes nothing."""
    guild, _request, created = await guilds_service.ask_to_join(
        session, guild_id=guild_id, user=current_user, message=payload.message
    )
    await session.commit()
    if not created:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    # Addressed to whoever can answer, and straight to the queue they answer
    # it in: who asked, what they said, and where to answer.
    await set_rls_context(session, SystemGuild(guild_id))
    requester = handle_of(current_user)
    await notifications_service.notify(
        session,
        NotificationType.community_join_requested,
        await guilds_service.join_request_answerer_ids(session, guild_id=guild_id),
        about=None,
        key="community.joinRequested",
        values={"requester": requester, "community": guild.name},
        data={
            "community_name": guild.name,
            "requester_id": current_user.id,
            "requester_name": requester,
            "target_path": "/settings/users",
        },
        actor=current_user,
        email=lambda reader: email_service.join_request_pieces(
            reader,
            of="community",
            event="requested",
            name=guild.name,
            requester=requester,
            message=payload.message,
        ),
        email_names_line=False,
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/directory/{community_id}/join-requests",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def withdraw_community_join_request(
    guild_id: CommunityIdPath,
    session: SystemSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Take back the caller's own request. Nothing to take back is not an
    error."""
    await session.exec(
        delete(CommunityJoinRequest).where(
            col(CommunityJoinRequest.guild_id) == guild_id,
            col(CommunityJoinRequest.user_id) == current_user.id,
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{community_id}/join-requests", response_model=list[CommunityJoinRequestRead]
)
async def list_community_join_requests(
    guild_id: CommunityIdPath,
    _guild_context: MembersContext,
    session: SettingsRLSSessionDep,
    system_session: SystemSessionDep,
) -> list[CommunityJoinRequestRead]:
    """Who is asking to join, oldest first."""
    requests = (
        await session.exec(
            select(CommunityJoinRequest)
            .where(CommunityJoinRequest.guild_id == guild_id)
            .order_by(
                col(CommunityJoinRequest.created_at), col(CommunityJoinRequest.id)
            )
        )
    ).all()
    # The askers are in no roster this session reads, so the system engine
    # draws them, as notifications draw their recipients: these people only,
    # whom the policy above let this request see, and only the identity a
    # profile publishes (UserIdentity).
    profiles = {
        user.id: UserIdentity.model_validate(user)
        for user in (
            await system_session.exec(
                select(User).where(
                    col(User.id).in_([request.user_id for request in requests])
                )
            )
        ).all()
    }
    return [
        CommunityJoinRequestRead(
            id=request.id,
            user=profiles[request.user_id],
            message=request.message,
            created_at=request.created_at,
        )
        for request in requests
        if request.user_id in profiles
    ]


async def _claim(
    session: AsyncSession, guild_id: int, request_id: int
) -> tuple[int, str]:
    """Take a request off the queue on the answering admin's session: the
    policy decides whether they may, and the row stays locked until it
    commits. 404 when it is not there to take."""
    claimed = (
        await session.exec(
            delete(CommunityJoinRequest)
            .where(
                col(CommunityJoinRequest.id) == request_id,
                col(CommunityJoinRequest.guild_id) == guild_id,
            )
            .returning(col(CommunityJoinRequest.user_id))
        )
    ).first()
    if claimed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildMessages.COMMUNITY_JOIN_REQUEST_NOT_FOUND,
        )
    guild = await guilds_service.get_guild(session, guild_id=guild_id)
    return claimed[0], guild.name


async def _tell_requester(
    session: AsyncSession, *, user_id: int, community: str, approved: bool
) -> None:
    outcome = "approved" if approved else "denied"

    def letter(reader: User) -> email_service.EmailPieces:
        pieces = email_service.join_request_pieces(
            reader, of="community", event=outcome, name=community
        )
        if approved:
            return pieces
        return replace(pieces, link=f"{settings.APP_URL.rstrip('/')}/communities")

    await notifications_service.notify(
        session,
        NotificationType.community_join_approved
        if approved
        else NotificationType.community_join_denied,
        [user_id],
        about=None,
        key=f"community.join{outcome.capitalize()}",
        values={"community": community},
        # An approval opens the community they are now in; a denial the
        # directory, since there is nowhere inside it for them to go.
        data={
            "community_name": community,
            "target_path": "/" if approved else "/communities",
        },
        email=letter,
        email_names_line=False,
    )
    await session.commit()


@router.post(
    "/{community_id}/join-requests/{request_id}/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def approve_community_join_request(
    guild_id: CommunityIdPath,
    request_id: int,
    _guild_context: MembersWriteContext,
    session: SettingsRLSSessionDep,
    system_session: SystemSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Let the asker in as a member. A refusal on the way in (the community is
    full, the asker under age) leaves the request where it was."""
    user_id, community = await _claim(session, guild_id, request_id)
    await guilds_service.ensure_membership(
        system_session,
        guild_id=guild_id,
        user_id=user_id,
        role=CommunityRole.member,
        actor_user_id=current_user.id,
        via="request",
    )
    await system_session.commit()
    await post_commit.settle(system_session)
    await session.commit()
    await _tell_requester(session, user_id=user_id, community=community, approved=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{community_id}/join-requests/{request_id}/deny",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def deny_community_join_request(
    guild_id: CommunityIdPath,
    request_id: int,
    _guild_context: MembersWriteContext,
    session: SettingsRLSSessionDep,
    current_user: CurrentUser,
) -> Response:
    """Turn the asker down. They may ask again."""
    user_id, community = await _claim(session, guild_id, request_id)
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_JOIN_REQUEST_DENIED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
    )
    await session.commit()
    await _tell_requester(session, user_id=user_id, community=community, approved=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
