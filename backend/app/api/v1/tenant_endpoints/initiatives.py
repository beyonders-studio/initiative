from typing import Annotated, List, Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import ColumnElement, Select, func
from sqlalchemy.orm import contains_eager, selectinload, undefer
from sqlmodel import select

from app.db.session import routed_guild_id
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    plugin_scope,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
    GuildAdminContext,
)
from app.core.audit_events import AuditEventType
from app.core.messages import (
    AuthMessages,
    GuildMessages,
    InitiativeMessages,
    UserMessages,
)
from app.core.tools import Tool
from app.models.tenant.initiative import (
    Initiative,
    InitiativeJoinRequest,
    InitiativeMember,
    InitiativeRoleModel,
    JoinRequestStatus,
    LOCKED_PERMISSION_ROLE_NAMES,
)
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import NotificationType
from app.models.platform.user import Presence, User
from app.models.platform.user_profile_view import MemberProfile
from app.schemas.tenant.initiative import (
    InitiativeCreate,
    InitiativeDirectoryEntry,
    InitiativeJoinRequestCreate,
    InitiativeJoinRequestRead,
    InitiativeListScope,
    InitiativeMemberAdd,
    InitiativeMemberListResponse,
    InitiativeMemberUpdate,
    InitiativeRead,
    InitiativeRoleCreate,
    InitiativeRoleRead,
    InitiativeRoleUpdate,
    InitiativeUpdate,
    serialize_initiative,
    serialize_initiative_member,
    serialize_role,
)
from app.schemas.platform.user import UserSummaryListResponse
from app.db.query import (
    MAX_ID_FILTER_VALUES,
    build_paginated_response,
    ids_in,
    paginated_query,
)
from app.services import audit as audit_service
from app.services import email as email_service
from app.services import notifications as notifications_service
from app.services.platform import accounts as accounts_service
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant.names import ensure_name_free
from app.services.platform import guilds as guilds_service
from app.services.platform import presence
from app.services.platform import users as users_service
from app.services.content_sockets import sockets as content_sockets
from app.services import rls as rls_service
from app.services.membership import initiative_scope_clause


router = APIRouter(route_class=ActorRoute)

_S = TypeVar("_S", bound=Select)

#: The routes an installed plug-in may call, under the initiatives scope.
InitiativesRead = Annotated[ActorContext, Depends(plugin_scope("initiatives:read"))]


#: What an initiative read loads beside the row: what the caller may do in it,
#: its headcount, and the caller's own role there.
_READ_OPTIONS = (
    undefer(Initiative.actions),
    undefer(Initiative.member_count),
    undefer(Initiative.role_display_name),
)


def _reaches_whole_guild(guild_context: ActorContext) -> bool:
    """Whether this request reads every initiative in the guild without holding
    a membership row: a guild admin, or a live PAM / break-glass grantee."""
    return guild_context.is_pam or guild_context.is_admin


async def _record_membership(
    session: SessionDep,
    *,
    event_type: AuditEventType,
    actor_user_id: int,
    member_user_id: int,
    initiative_id: int,
    guild_id: int,
    detail: dict,
) -> None:
    """One membership record: whose membership, in which initiative, and what
    the change was. Staged beside the write it describes."""
    await audit_service.record(
        session,
        event_type=event_type,
        actor_user_id=actor_user_id,
        target_user_id=member_user_id,
        guild_id=guild_id,
        target_type="initiative",
        target_id=initiative_id,
        detail=detail,
    )


#: What a record of a role edit reports on beyond its permissions.
_ROLE_AUDIT_FIELDS = ("display_name", "is_manager")


def _role_permissions(role: InitiativeRoleModel) -> dict[str, bool]:
    """A role's permission toggles, by key."""
    return {p.key: p.enabled for p in role.permissions}


async def _get_initiative_or_404(
    initiative_id: int, session: SessionDep, *options
) -> Initiative:
    """The initiative row, with whatever ``options`` load beside it."""
    statement = (
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .execution_options(populate_existing=True)
        .options(*options)
    )
    result = await session.exec(statement)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND
        )
    return initiative


async def _read_initiative(
    initiative_id: int, session: SessionDep, guild_context: ActorContext
) -> InitiativeRead:
    """The initiative as a route answers with it."""
    initiative = await _get_initiative_or_404(initiative_id, session, *_READ_OPTIONS)
    return serialize_initiative(initiative, context=guild_context)


async def _member_ids(
    session: SessionDep, initiative_id: int, *, role_id: int | None = None
) -> list[int]:
    """The accounts in an initiative, or those holding one of its roles —
    whose open connections a change to it re-checks once it commits."""
    stmt = select(InitiativeMember.user_id).where(
        InitiativeMember.initiative_id == initiative_id
    )
    if role_id is not None:
        stmt = stmt.where(InitiativeMember.role_id == role_id)
    return list((await session.exec(stmt)).all())


async def _require_manager_access(
    session: SessionDep,
    initiative: Initiative,
    current_user: User,
    *,
    guild_context: GuildContext | None = None,
) -> None:
    """Require that the user has manager-level access to the initiative."""
    if guild_context is not None and guild_context.is_admin:
        return
    is_manager = (
        initiative.id in guild_context.manager_initiatives
        if guild_context is not None
        else await rls_service.is_initiative_manager(
            session, initiative_id=initiative.id
        )
    )
    if not is_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.MANAGER_REQUIRED,
        )


async def _guard_guild_admin_role(
    session: SessionDep,
    *,
    guild_id: int,
    target_user_id: int,
    role: InitiativeRoleModel | None,
) -> None:
    """Restrict which initiative roles a guild admin may be assigned.

    A guild admin already has complete access to every initiative in their
    guild (see ``GuildContext.is_admin``), so their membership
    row carries a manager role — purely for manager-style features like
    notifications — and never a standard member or custom one. Every route that
    *creates* a row settles that itself
    (:func:`initiatives_service.resolve_membership_role`); this is the backstop
    for the one route that only ever changes an existing role, where silently
    substituting would answer a question nobody asked.
    """
    if role is not None and role.is_manager:
        return  # manager role is the one allowed elevation for an admin
    if await initiatives_service.is_guild_admin_member(
        session, guild_id=guild_id, user_id=target_user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.GUILD_ADMIN_ROLE_RESTRICTED,
        )


async def _guard_full_access_role(
    session: SessionDep,
    *,
    guild_id: int,
    target_user_id: int,
    role: InitiativeRoleModel | None,
    guild_context: GuildContext,
) -> None:
    """Restrict who may put a member on a role carrying "Full access", or take
    them off one — ``role`` is either the role they take or the role they leave.

    A guild admin settles that one. Every other role — the other manager roles
    included — stays an initiative manager's to assign and to remove.

    A guild admin as the *target* is the exception: their standing already
    reaches every initiative in the guild, so the role neither adds to it nor
    takes from it, and this is the route a project manager brings an admin in by.
    """
    if role is None or not role.override_share_restrictions:
        return
    if guild_context.is_admin:
        return
    if await initiatives_service.is_guild_admin_member(
        session, guild_id=guild_id, user_id=target_user_id
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=InitiativeMessages.OVERRIDE_REQUIRES_GUILD_ADMIN,
    )


# ============================================================================
# Initiative CRUD
# ============================================================================


@router.get("/", response_model=List[InitiativeRead])
async def list_initiatives(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: InitiativesRead,
    scope: Annotated[InitiativeListScope, Query()] = InitiativeListScope.member,
) -> List[InitiativeRead]:
    """The initiatives the caller belongs to, or — for a guild admin asking for
    ``scope=community`` — every initiative in the guild.

    The default is the caller's own workspace: what the sidebar and the
    initiative pickers show. A guild admin's authority over their whole guild is
    unchanged; it simply no longer decides what appears in their navigation.
    They bring an initiative into it by taking the project manager role from the
    guild-settings initiative table, which is also what ``scope=community`` feeds.
    """
    if scope is InitiativeListScope.community and not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildMessages.COMMUNITY_ADMIN_REQUIRED,
        )

    # `initiatives` is a structural table (not initiative-RLS-gated), so scope it
    # in the query. The guild-wide listing uses the ONE access rule —
    # initiative_scope_clause defers to initiative_access (admin OR PAM OR
    # member, from the request GUCs), the same predicate the content-table RLS
    # uses. A time-bound grantee holds no memberships in the guild, so their
    # session stays on that predicate too: the grant is what they navigate by.
    # An installed plug-in's workspace is the initiatives it is placed in, which
    # its standing carries. A guest's are the initiatives they are in and those
    # of the items shared with them, which the same rule answers.
    if current_user is None:
        scope_clause = Initiative.id.in_(guild_context.member_initiatives)
    elif (
        scope is InitiativeListScope.community
        or guild_context.is_pam
        or guild_context.guest
    ):
        scope_clause = initiative_scope_clause(current_user.id, Initiative.id)
    else:
        scope_clause = Initiative.id.in_(
            select(InitiativeMember.initiative_id).where(
                InitiativeMember.user_id == current_user.id
            )
        )

    statement = (
        select(Initiative)
        .where(
            scope_clause,
        )
        .options(*_READ_OPTIONS)
    )
    result = await session.exec(statement)
    initiatives = result.all()
    return [
        serialize_initiative(initiative, context=guild_context)
        for initiative in initiatives
    ]


@router.get("/directory", response_model=List[InitiativeDirectoryEntry])
async def list_initiative_directory(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> List[InitiativeDirectoryEntry]:
    """Initiatives in this guild that any member may discover and join.

    Open to every guild member — it lists only what each initiative published
    about itself (name, description, colour, roster size), never its content.
    Initiatives whose policy is ``private`` are listed only to their own
    members, guild admins included: an admin's authority over the guild is
    unchanged, but the front page shows what they are in and what is on offer,
    read the same way for everyone. ``/initiatives/?scope=community`` is the
    whole-guild listing, and guild settings is where it is managed.

    Declared before ``/{initiative_id}`` so the literal path wins the match.
    """
    return await initiatives_service.list_directory_entries(
        session,
        guild_id=guild_context.guild_id,
        user_id=current_user.id,
        is_guild_admin=guild_context.is_admin,
    )


@router.post("/{initiative_id}/join", response_model=InitiativeRead)
async def join_initiative(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Join an ``open`` initiative as yourself, with the built-in member role.

    Idempotent: already being a member is a success, not a conflict. Any other
    join policy answers 403 — the same answer for ``private`` and ``request``,
    so it says only "not by this route".

    A guild admin walks in whatever the policy says, and on the manager role:
    the queue exists to exercise an authority they already hold, and staffing
    themselves onto an initiative is how they bring it into their own
    navigation. It is the same act as ticking themselves in guild settings.
    """
    # A grantee reaches this guild for a window; the membership row this would
    # create has no end date, so joining is for real guild members.
    if guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        )
    initiative = await _get_initiative_or_404(initiative_id, session)
    if (
        not initiatives_service.is_self_joinable(initiative)
        and not guild_context.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_JOINABLE,
        )
    try:
        await initiatives_service.self_join(
            session, initiative=initiative, user_id=current_user.id
        )
    except ValueError:
        # An initiative missing its built-in member role can't take a joiner.
        # The code is the contract; the exception text is not.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=InitiativeMessages.MEMBER_ROLE_NOT_FOUND,
        )
    await session.commit()
    return await _read_initiative(initiative_id, session, guild_context)


# ============================================================================
# Join requests (join_policy == 'request')
# ============================================================================


def _require_no_scoped_grant(guild_context: GuildContext) -> None:
    """A scoped grantee may not create or answer a join request.

    A grant reaches the guild for a window; the membership row on the other side
    of an approval has no end date, so the two are never traded for each other.
    """
    if guild_context.is_pam:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.GRANT_CANNOT_MANAGE_MEMBERS,
        )


async def _load_pending_join_request(
    session: SessionDep,
    *,
    request_id: int,
    initiative_id: int,
) -> InitiativeJoinRequest:
    """One request of this initiative that is still open to an answer."""
    request = await initiatives_service.get_join_request(
        session, request_id=request_id, initiative_id=initiative_id
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.JOIN_REQUEST_NOT_FOUND,
        )
    if request.status != JoinRequestStatus.pending.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.JOIN_REQUEST_ALREADY_RESOLVED,
        )
    return request


async def _resolve_join_request(
    initiative_id: int,
    request_id: int,
    session: SessionDep,
    current_user: User,
    guild_context: GuildContext,
    *,
    approved: bool,
) -> InitiativeJoinRequestRead:
    """Shared body of approve and deny: same authority, same lifecycle, one
    boolean apart."""
    _require_no_scoped_grant(guild_context)
    initiative = await _get_initiative_or_404(initiative_id, session)
    # Answering a request grants access, so it takes exactly the authority that
    # adding a member by hand takes — no separate rule to keep in step.
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )
    request = await _load_pending_join_request(
        session, request_id=request_id, initiative_id=initiative_id
    )
    requester = await accounts_service.load_one(request.user_id)
    if requester is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    try:
        await initiatives_service.resolve_join_request(
            session, request=request, resolver_id=current_user.id, approved=approved
        )
    except initiatives_service.JoinRequestAlreadyResolved:
        # Another manager answered it between the check above and this write.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.JOIN_REQUEST_ALREADY_RESOLVED,
        )
    except ValueError:
        # The initiative's built-in member role is missing, so it can take no
        # joiner. The code is the contract; the exception text is not.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=InitiativeMessages.MEMBER_ROLE_NOT_FOUND,
        )
    await session.commit()

    outcome = "approved" if approved else "denied"
    await notifications_service.notify(
        session,
        NotificationType.initiative_join_approved
        if approved
        else NotificationType.initiative_join_denied,
        [requester.id],
        about=None,
        key=f"initiative.join{outcome.capitalize()}",
        values={"initiative": initiative.name},
        data={
            "request_id": request.id,
            "initiative_id": initiative.id,
            # An approval opens the initiative, whose membership now exists; a
            # denial the community's front page, which is as far as they go.
            "target_path": f"/i/{initiative.id}" if approved else "/",
        },
        email=lambda reader: email_service.initiative_join_request_pieces(
            reader, event=outcome, initiative_name=initiative.name
        ),
        email_names_line=False,
    )
    await session.commit()

    rows = await initiatives_service.list_join_requests(
        session,
        initiative_id=initiative_id,
        status=None,
        user_id=request.user_id,
    )
    return next(row for row in rows if row.id == request.id)


@router.post(
    "/{initiative_id}/join-requests",
    response_model=InitiativeJoinRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_join_request(
    initiative_id: int,
    payload: InitiativeJoinRequestCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeJoinRequestRead:
    """Knock on a ``request`` initiative and wait for a manager to answer.

    Any other join policy answers 403 — the same answer for ``private`` and
    ``open`` alike, so it says only "not by this route" and a private initiative
    stays exactly as hidden as it was.

    Being refused before does not bar asking again: only a *pending* request is
    unique, and the refusals stay on file so the manager reading the queue can
    see the repeat.
    """
    _require_no_scoped_grant(guild_context)
    initiative = await _get_initiative_or_404(initiative_id, session)
    if not initiatives_service.is_requestable(initiative):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_REQUESTABLE,
        )
    # A guild admin holds the authority this queue exercises, so they walk in
    # (``POST /join``, which takes them whatever the policy says) rather than
    # knocking and waiting for a member to answer.
    if guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.GUILD_ADMIN_NEED_NOT_REQUEST,
        )
    if initiative_id in guild_context.member_initiatives:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.ALREADY_A_MEMBER,
        )

    request, created = await initiatives_service.create_join_request(
        session,
        initiative=initiative,
        user_id=current_user.id,
        message=payload.message,
    )
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.JOIN_REQUEST_ALREADY_PENDING,
        )
    request_id = request.id
    await session.commit()

    manager_ids = await initiatives_service.manager_user_ids(
        session, initiative_id=initiative_id
    )
    if manager_ids:
        requester = await notifications_service.actor_name(session, current_user)
        # Addressed to the people who can answer it, and straight to the queue
        # they answer it in. It carries no initiative content: who asked, what
        # they said, and where to answer.
        await notifications_service.notify(
            session,
            NotificationType.initiative_join_requested,
            list(manager_ids),
            about=None,
            key="initiative.joinRequested",
            values={"requester": requester, "initiative": initiative.name},
            data={
                "request_id": request_id,
                "initiative_id": initiative.id,
                "requester_id": current_user.id,
                "requester_name": requester,
                "target_path": f"/i/{initiative.id}/settings/members",
            },
            actor=current_user,
            email=lambda reader: email_service.initiative_join_request_pieces(
                reader,
                event="requested",
                initiative_name=initiative.name,
                requester=requester,
                message=payload.message,
            ),
            email_names_line=False,
        )
        await session.commit()

    rows = await initiatives_service.list_join_requests(
        session, initiative_id=initiative_id, status=None, user_id=current_user.id
    )
    return next(row for row in rows if row.id == request_id)


@router.get(
    "/{initiative_id}/join-requests",
    response_model=List[InitiativeJoinRequestRead],
)
async def list_join_requests(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
    request_status: Annotated[
        JoinRequestStatus | None,
        Query(
            alias="status",
            description=(
                "Narrow the queue to one status. Omit for the pending queue — "
                "the rows that are still open to an answer."
            ),
        ),
    ] = None,
) -> List[InitiativeJoinRequestRead]:
    """The join-request queue for one initiative.

    Manager-only, matching who may answer it; a plain member of the initiative
    has no more business reading who asked to get in than a non-member does.
    """
    initiative = await _get_initiative_or_404(initiative_id, session)
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )
    return await initiatives_service.list_join_requests(
        session,
        initiative_id=initiative_id,
        status=(
            request_status.value
            if request_status is not None
            else JoinRequestStatus.pending.value
        ),
    )


@router.post(
    "/{initiative_id}/join-requests/{request_id}/approve",
    response_model=InitiativeJoinRequestRead,
)
async def approve_join_request(
    initiative_id: int,
    request_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeJoinRequestRead:
    """Let the requester in, with the built-in ``member`` role.

    The membership row is the one every join path produces, so the requester's
    access flips through ``initiative_access`` with no policy change. Someone who
    became a member by another route while the request waited is absorbed: the
    row is resolved and the call succeeds.
    """
    return await _resolve_join_request(
        initiative_id,
        request_id,
        session,
        current_user,
        guild_context,
        approved=True,
    )


@router.post(
    "/{initiative_id}/join-requests/{request_id}/deny",
    response_model=InitiativeJoinRequestRead,
)
async def deny_join_request(
    initiative_id: int,
    request_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeJoinRequestRead:
    """Turn the request down. No membership row, so nothing about what the
    requester can see changes; the row stays as history, and they may ask
    again."""
    return await _resolve_join_request(
        initiative_id,
        request_id,
        session,
        current_user,
        guild_context,
        approved=False,
    )


@router.get("/{initiative_id}", response_model=InitiativeRead)
async def get_initiative(
    initiative_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: InitiativesRead,
    include_deleted: IncludeDeletedDep = False,
) -> InitiativeRead:
    statement = (
        select(Initiative)
        .where(
            Initiative.id == initiative_id,
        )
        .options(*_READ_OPTIONS)
    )
    result = await session.exec(statement)
    initiative = result.first()
    # An installed plug-in reads the initiatives it is placed in; any other is not
    # there for it.
    if not initiative or (
        current_user is None and initiative.id not in guild_context.member_initiatives
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=InitiativeMessages.NOT_FOUND
        )
    # Reachable by an initiative member, by a guild admin (the same override the
    # RLS admin leg grants), by a PAM / break-glass grantee — who holds no
    # membership row in this guild and reads it through the grant for its window
    # — and by a guest given items in it.
    if current_user is not None and not _reaches_whole_guild(guild_context):
        if (
            initiative_id not in guild_context.member_initiatives
            and initiative_id not in guild_context.guest_item_initiatives
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.NOT_A_MEMBER,
            )
    return serialize_initiative(initiative, context=guild_context)


@router.post("/", response_model=InitiativeRead, status_code=status.HTTP_201_CREATED)
async def create_initiative(
    initiative_in: InitiativeCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[
        GuildContext, Depends(require_guild_roles(CommunityRole.admin))
    ],
) -> InitiativeRead:
    guild_id = guild_context.guild_id
    await ensure_name_free(
        session,
        Initiative.name,
        initiative_in.name,
        detail=InitiativeMessages.NAME_EXISTS,
    )
    initiative = Initiative(
        name=initiative_in.name,
        description=initiative_in.description,
        join_policy=initiative_in.join_policy.value,
        # One master switch per toggleable tool, derived — a new Tool member
        # flows through without touching this endpoint.
        **{t.view_permission: getattr(initiative_in, t.view_permission) for t in Tool},
    )
    if initiative_in.color:
        initiative.color = initiative_in.color
    session.add(initiative)
    await session.flush()

    # Create built-in roles for this initiative
    roles = await initiatives_service.create_builtin_roles(
        session, initiative_id=initiative.id
    )

    # Add the creator: a guild admin on the moderator role, anyone else as the
    # project manager of what they just made.
    creator_role = await initiatives_service.creator_role(
        session, guild_id=guild_id, user_id=current_user.id, roles=roles
    )
    session.add(
        InitiativeMember(
            initiative_id=initiative.id,
            user_id=current_user.id,
            role_id=creator_role.id,
        )
    )
    await _record_membership(
        session,
        event_type=AuditEventType.INITIATIVE_MEMBER_ADDED,
        actor_user_id=current_user.id,
        member_user_id=current_user.id,
        initiative_id=initiative.id,
        guild_id=guild_id,
        detail={
            "role_id": creator_role.id,
            "role": creator_role.name,
            "via": "created",
        },
    )
    await session.commit()
    return await _read_initiative(initiative.id, session, guild_context)


@router.patch("/{initiative_id}", response_model=InitiativeRead)
async def update_initiative(
    initiative_id: int,
    initiative_in: InitiativeUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    initiative = await _get_initiative_or_404(initiative_id, session)
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )

    update_data = initiative_in.model_dump(exclude_unset=True)
    # Auto-join enrols every future guild member, so it shapes onboarding for
    # the whole guild rather than for one initiative — guild admins only, the
    # same shape as the archive toggle above. join_policy stays with whoever may
    # already edit the initiative.
    if (
        update_data.get("auto_join") is not None
        and update_data["auto_join"] != initiative.auto_join
        and not guild_context.is_admin
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.AUTO_JOIN_ADMIN_ONLY,
        )
    if "join_policy" in update_data or "auto_join" in update_data:
        # The column stores the plain string, so normalize whichever form the
        # payload validated into before comparing or persisting.
        join_policy = update_data.get("join_policy")
        join_policy = getattr(join_policy, "value", join_policy)
        try:
            initiatives_service.validate_join_settings(
                initiative,
                join_policy=join_policy,
                auto_join=update_data.get("auto_join"),
            )
        except ValueError:
            # The only way the pair is incoherent. The code is the contract;
            # the exception text is not.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=InitiativeMessages.AUTO_JOIN_REQUIRES_OPEN,
            )
        if join_policy is not None:
            update_data["join_policy"] = join_policy
    if "name" in update_data:
        await ensure_name_free(
            session,
            Initiative.name,
            update_data["name"],
            Initiative.id != initiative_id,
            detail=InitiativeMessages.NAME_EXISTS,
        )
    for field, value in update_data.items():
        setattr(initiative, field, value)
    session.add(initiative)
    switched = any(field.endswith("_enabled") for field in update_data)
    members = await _member_ids(session, initiative_id) if switched else []
    await session.commit()
    await content_sockets.refresh_users(guild_context.guild_id, members)
    return await _read_initiative(initiative_id, session, guild_context)


@router.delete("/{initiative_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_initiative(
    initiative_id: int,
    session: RLSSessionDep,
    guild_context: GuildAdminContext,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> None:
    """Soft-delete an initiative. Cascades the same deleted_at to its
    projects, files, queues, and calendar events; their descendants
    (tasks, comments, queue items) follow recursively. Restoring the
    initiative resurfaces everything that was cascaded together."""
    from app.services.tenant.soft_delete import trash

    initiative = await _get_initiative_or_404(initiative_id, session)
    members = await _member_ids(session, initiative_id)
    retention_days = await trash(
        session,
        initiative,
        deleted_by_user_id=current_user.id,
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.INITIATIVE_DELETED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="initiative",
        target_id=initiative_id,
        detail={"via": "trash", "retention_days": retention_days},
    )
    await session.commit()
    await content_sockets.refresh_users(guild_context.guild_id, members)


# ============================================================================
# Role CRUD
# ============================================================================


@router.get("/{initiative_id}/roles", response_model=List[InitiativeRoleRead])
async def list_initiative_roles(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> List[InitiativeRoleRead]:
    """List all roles for an initiative with their permissions."""
    await _get_initiative_or_404(initiative_id, session)

    # Same readership as the initiative itself: member, guild admin, or grantee.
    if not _reaches_whole_guild(guild_context):
        if initiative_id not in guild_context.member_initiatives:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.NOT_A_MEMBER,
            )

    roles = await initiatives_service.list_initiative_roles(
        session, initiative_id=initiative_id
    )

    counts = await initiatives_service.count_members_by_role(
        session, initiative_id=initiative_id
    )
    return [serialize_role(role, member_count=counts.get(role.id, 0)) for role in roles]


@router.post(
    "/{initiative_id}/roles",
    response_model=InitiativeRoleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_initiative_role(
    initiative_id: int,
    role_in: InitiativeRoleCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRoleRead:
    """Create a new custom role for an initiative."""
    initiative = await _get_initiative_or_404(initiative_id, session)
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )

    # Check for duplicate name
    existing = await initiatives_service.get_role_by_name(
        session, initiative_id=initiative_id, role_name=role_in.name
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=InitiativeMessages.ROLE_NAME_EXISTS,
        )

    role = await initiatives_service.create_custom_role(
        session,
        initiative_id=initiative_id,
        name=role_in.name,
        display_name=role_in.display_name,
        is_manager=role_in.is_manager,
        permissions=role_in.permissions,
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.INITIATIVE_ROLE_CREATED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="initiative_role",
        target_id=role.id,
        detail={
            "initiative_id": initiative_id,
            "name": role.name,
            "is_manager": role.is_manager,
            "permissions": _role_permissions(role),
        },
    )
    await session.commit()
    return serialize_role(role, member_count=0)


@router.patch("/{initiative_id}/roles/{role_id}", response_model=InitiativeRoleRead)
async def update_initiative_role(
    initiative_id: int,
    role_id: int,
    role_in: InitiativeRoleUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRoleRead:
    """Update a role's display name and/or permissions.

    Note: the built-ins that already hold every permission (moderator, project
    manager) cannot have theirs changed, to prevent lockouts.
    """
    initiative = await _get_initiative_or_404(initiative_id, session)
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )

    role = await initiatives_service.get_role_by_id(
        session, role_id=role_id, initiative_id=initiative_id
    )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.ROLE_NOT_FOUND,
        )

    # The built-ins that hold every permission have nothing to configure.
    if role.name in LOCKED_PERMISSION_ROLE_NAMES and role_in.permissions is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=InitiativeMessages.CANNOT_MODIFY_BUILTIN_PERMISSIONS,
        )

    before = audit_service.snapshot(role, _ROLE_AUDIT_FIELDS)
    before_permissions = _role_permissions(role)

    # Update display name if provided
    if role_in.display_name is not None:
        role.display_name = role_in.display_name
        session.add(role)

    was_manager = role.is_manager
    # Update is_manager if provided (not for built-in roles)
    if role_in.is_manager is not None:
        if role.is_builtin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=InitiativeMessages.CANNOT_CHANGE_BUILTIN_MANAGER,
            )
        # If demoting from manager, ensure at least one manager remains
        if role.is_manager and not role_in.is_manager:
            # First check if this role has any members - if not, demotion is safe
            this_role_members = await initiatives_service.count_role_members(
                session, role_id=role_id
            )
            if this_role_members > 0:
                # Count managers excluding members with this role
                stmt = (
                    select(func.count())
                    .select_from(InitiativeMember)
                    .join(
                        InitiativeRoleModel,
                        InitiativeRoleModel.id == InitiativeMember.role_id,
                    )
                    .where(
                        InitiativeMember.initiative_id == initiative_id,
                        InitiativeRoleModel.is_manager.is_(True),
                        InitiativeRoleModel.id != role_id,
                    )
                )
                result = await session.exec(stmt)
                other_managers = result.one()
                if other_managers == 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=InitiativeMessages.MUST_HAVE_MANAGER,
                    )
        role.is_manager = role_in.is_manager
        session.add(role)

    # Update permissions if provided
    if role_in.permissions is not None:
        role = await initiatives_service.update_role_permissions(
            session, role=role, permissions=role_in.permissions
        )

    changed = audit_service.changed_fields(
        before, audit_service.snapshot(role, _ROLE_AUDIT_FIELDS)
    )
    after_permissions = _role_permissions(role)
    permissions_changed = {
        key: {"from": before_permissions.get(key), "to": after_permissions[key]}
        for key in after_permissions
        if before_permissions.get(key) != after_permissions[key]
    }
    if changed["changed"] or permissions_changed:
        await audit_service.record(
            session,
            event_type=AuditEventType.INITIATIVE_ROLE_UPDATED,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type="initiative_role",
            target_id=role.id,
            detail={
                "initiative_id": initiative_id,
                "name": role.name,
                **changed,
                "permissions_changed": permissions_changed,
            },
        )

    holders = (
        await _member_ids(session, initiative_id, role_id=role.id)
        if permissions_changed or role.is_manager != was_manager
        else []
    )
    await session.commit()
    await content_sockets.refresh_users(guild_context.guild_id, holders)
    member_count = await initiatives_service.count_role_members(
        session, role_id=role.id
    )
    return serialize_role(role, member_count=member_count)


@router.delete(
    "/{initiative_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_initiative_role(
    initiative_id: int,
    role_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> None:
    """Delete a custom role. Built-in roles cannot be deleted."""
    initiative = await _get_initiative_or_404(initiative_id, session)
    await _require_manager_access(
        session, initiative, current_user, guild_context=guild_context
    )

    role = await initiatives_service.get_role_by_id(
        session, role_id=role_id, initiative_id=initiative_id
    )
    if not role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.ROLE_NOT_FOUND,
        )

    role_name = role.name
    await initiatives_service.delete_role(session, role=role)
    await audit_service.record(
        session,
        event_type=AuditEventType.INITIATIVE_ROLE_DELETED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type="initiative_role",
        target_id=role_id,
        detail={"initiative_id": initiative_id, "name": role_name},
    )
    await session.commit()


# ============================================================================
# Member management
# ============================================================================


async def _require_roster_access(
    session: SessionDep,
    initiative_id: int,
    current_user: User,
    guild_context: GuildContext,
) -> None:
    """Who may read an initiative's roster: a member, a guild admin (the same
    override the RLS admin leg grants), or a PAM / break-glass grantee, who
    holds no membership row and reads it through the grant."""
    await _get_initiative_or_404(initiative_id, session)
    membership = await initiatives_service.get_initiative_membership(
        session,
        initiative_id=initiative_id,
        user_id=current_user.id,
    )
    if not membership and not guild_context.is_pam and not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=InitiativeMessages.NOT_A_MEMBER,
        )


def _roster_where(
    statement: _S,
    *,
    initiative_id: int,
    search: Optional[str],
) -> tuple[_S, tuple[ColumnElement, ...]]:
    """``statement`` (which joins ``InitiativeMember`` to ``MemberProfile``)
    narrowed to the initiative's listable members matching ``search``, and the
    order to read them in: nearest first while searching, alphabetical
    otherwise."""
    statement = statement.where(
        InitiativeMember.initiative_id == initiative_id,
        users_service.visible_to_other_people(),
    )
    closest = None
    if search and (term := search.strip()):
        matches, closest = users_service.member_match(term)
        statement = statement.where(matches)
    order = (
        *users_service.member_order(closest),
        MemberProfile.username.asc(),
        MemberProfile.discriminator.asc(),
        MemberProfile.id.asc(),
    )
    return statement, order


@router.get("/{initiative_id}/members", response_model=InitiativeMemberListResponse)
async def get_initiative_members(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
    search: Optional[str] = Query(
        default=None,
        description="Case-insensitive substring match on the member's name.",
    ),
    is_manager: Optional[bool] = Query(
        default=None,
        description="Only the members whose role is (or is not) a manager role.",
    ),
    online: bool = Query(
        default=False,
        description="Only the members who appear online, idle or busy right now.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> InitiativeMemberListResponse:
    """One page of an initiative's roster, each member with their role — the
    initiative's members settings and the moderation view. A picker wants
    :func:`search_initiative_members` instead."""
    await _require_roster_access(session, initiative_id, current_user, guild_context)

    base, order = _roster_where(
        select(InitiativeMember)
        .join(MemberProfile, MemberProfile.id == InitiativeMember.user_id)
        .outerjoin(
            InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id
        ),
        initiative_id=initiative_id,
        search=search,
    )
    if is_manager is not None:
        base = base.where(
            func.coalesce(InitiativeRoleModel.is_manager, False).is_(is_manager)
        )
    shown = presence.online.shown()
    if online:
        base = base.where(ids_in(MemberProfile.id, shown))

    count_stmt = select(func.count()).select_from(base.subquery())
    data_stmt = base.order_by(*order).options(
        contains_eager(InitiativeMember.user),
        contains_eager(InitiativeMember.role_ref),
    )
    memberships, total_count, actual_page = await paginated_query(
        session, data_stmt, count_stmt, page=page, page_size=page_size
    )
    guests = await guilds_service.guest_ends(
        session,
        guild_id=guild_context.guild_id,
        user_ids=[m.user_id for m in memberships],
    )
    return InitiativeMemberListResponse(
        **build_paginated_response(
            [
                serialize_initiative_member(
                    m,
                    shown.get(m.user_id, Presence.offline),
                    guests.get(m.user_id),
                )
                for m in memberships
            ],
            total_count,
            actual_page,
            page_size,
        )
    )


@router.get("/{initiative_id}/members/search", response_model=UserSummaryListResponse)
async def search_initiative_members(
    initiative_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
    search: Optional[str] = Query(
        default=None,
        description="Case-insensitive substring match on the member's name.",
    ),
    user_id: Annotated[list[int] | None, Query(max_length=MAX_ID_FILTER_VALUES)] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> UserSummaryListResponse:
    """Slim, searchable, paginated roster of an initiative's members.

    Same authorization as :func:`get_initiative_members` (member, guild
    admin, or PAM/break-glass grantee); the search/id/pagination params are
    additive filters on the already-RLS-gated query. Returns
    :class:`UserSummary` for typeahead/picker surfaces instead of the roster's
    member-and-role rows.

    Pass ``user_id`` one or more times to resolve a known selection (a picker
    rehydrating stored ids into names/avatars) rather than searching.
    """
    await _require_roster_access(session, initiative_id, current_user, guild_context)

    base, order = _roster_where(
        select(MemberProfile).join(
            InitiativeMember, InitiativeMember.user_id == MemberProfile.id
        ),
        initiative_id=initiative_id,
        search=search,
    )
    if user_id:
        base = base.where(MemberProfile.id.in_(user_id))

    count_stmt = select(func.count()).select_from(base.subquery())
    users, total_count, actual_page = await paginated_query(
        session, base.order_by(*order), count_stmt, page=page, page_size=page_size
    )

    items = await users_service.summaries_with_guild_role(
        session, guild_context.guild_id, users
    )
    return UserSummaryListResponse(
        **build_paginated_response(items, total_count, actual_page, page_size)
    )


@router.post(
    "/{initiative_id}/members",
    response_model=InitiativeRead,
    status_code=status.HTTP_200_OK,
)
async def add_initiative_member(
    initiative_id: int,
    payload: InitiativeMemberAdd,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Add a member to an initiative or update their role.

    Any project manager may bring in any member of the guild, guild admins
    included — an admin simply lands on the manager role their standing already
    implies, whatever role the invite named.
    """
    initiative = await _get_initiative_or_404(initiative_id, session)
    await _require_manager_access(
        session,
        initiative,
        current_user,
        guild_context=guild_context,
    )

    user_stmt = await session.exec(
        select(MemberProfile).where(MemberProfile.id == payload.user_id)
    )
    user = user_stmt.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    guild_membership = await guilds_service.get_membership(
        session,
        guild_id=routed_guild_id(session),
        user_id=user.id,
    )
    if not guild_membership:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.NOT_IN_GUILD,
        )

    requested_role = None
    if payload.role_id is not None:
        # Verify role exists and belongs to this initiative
        requested_role = await initiatives_service.get_role_by_id(
            session, role_id=payload.role_id, initiative_id=initiative_id
        )
        if not requested_role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=InitiativeMessages.ROLE_NOT_FOUND,
            )

    await _guard_full_access_role(
        session,
        guild_id=routed_guild_id(session),
        target_user_id=payload.user_id,
        role=requested_role,
        guild_context=guild_context,
    )

    # The role the row actually takes: what was asked for, the built-in member
    # role when nothing was, or the moderator role for a guild admin — whose
    # standing already reaches the initiative. Settling it here is what lets a
    # project manager invite an admin without knowing they are one.
    resolved_role = await initiatives_service.resolve_membership_role(
        session,
        initiative=initiative,
        user_id=payload.user_id,
        requested=requested_role,
    )
    if not resolved_role:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=InitiativeMessages.MEMBER_ROLE_NOT_FOUND,
        )
    role_id = resolved_role.id

    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == payload.user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    created = False

    if membership:
        if membership.role_id != role_id:
            # Check if demoting from manager role
            old_role = await initiatives_service.get_role_by_id(
                session, role_id=membership.role_id
            )
            await _guard_full_access_role(
                session,
                guild_id=routed_guild_id(session),
                target_user_id=payload.user_id,
                role=old_role,
                guild_context=guild_context,
            )
            new_role = await initiatives_service.get_role_by_id(
                session, role_id=role_id
            )
            if (
                old_role
                and old_role.is_manager
                and (not new_role or not new_role.is_manager)
            ):
                await initiatives_service.ensure_managers_remain(
                    session,
                    initiative_id=initiative.id,
                    excluded_user_ids={membership.user_id},
                )
            from_role_id = membership.role_id
            membership.role_id = role_id
            session.add(membership)
            await _record_membership(
                session,
                event_type=AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED,
                actor_user_id=current_user.id,
                member_user_id=payload.user_id,
                initiative_id=initiative_id,
                guild_id=routed_guild_id(session),
                detail={
                    "from_role_id": from_role_id,
                    "from": old_role.name if old_role else None,
                    "to_role_id": role_id,
                    "to": resolved_role.name,
                },
            )
    else:
        membership = InitiativeMember(
            initiative_id=initiative_id,
            user_id=payload.user_id,
            role_id=role_id,
        )
        session.add(membership)
        created = True
        await _record_membership(
            session,
            event_type=AuditEventType.INITIATIVE_MEMBER_ADDED,
            actor_user_id=current_user.id,
            member_user_id=payload.user_id,
            initiative_id=initiative_id,
            guild_id=routed_guild_id(session),
            detail={
                "role_id": role_id,
                "role": resolved_role.name,
                "via": "manager",
            },
        )

    await session.commit()
    await content_sockets.refresh_users(guild_context.guild_id, [payload.user_id])
    read = await _read_initiative(initiative_id, session, guild_context)
    if created:
        await notifications_service.notify(
            session,
            NotificationType.initiative_added,
            [user.id],
            about=None,
            key="initiative.added",
            values={"initiative": read.name},
            data={
                "initiative_id": read.id,
                "target_path": f"/i/{read.id}",
            },
            email=lambda reader: email_service.initiative_added_pieces(
                reader, read.name
            ),
        )
        await session.commit()
    return read


@router.delete("/{initiative_id}/members/{user_id}", response_model=InitiativeRead)
async def remove_initiative_member(
    initiative_id: int,
    user_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Remove a member from an initiative."""
    initiative = await _get_initiative_or_404(initiative_id, session)
    await _require_manager_access(
        session,
        initiative,
        current_user,
        guild_context=guild_context,
    )

    stmt = (
        select(InitiativeMember)
        .options(selectinload(InitiativeMember.role_ref))
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()

    if membership:
        await _guard_full_access_role(
            session,
            guild_id=guild_context.guild_id,
            target_user_id=user_id,
            role=membership.role_ref,
            guild_context=guild_context,
        )
        role_name = membership.role_ref.name if membership.role_ref else None
        # Removing a member is never blocked by them being the initiative's last
        # manager — the initiative is simply left without one until an admin
        # appoints another. (Demoting the last manager still is blocked; that
        # edits a live membership rather than ending it.)
        await session.delete(membership)
        await session.flush()
        await _record_membership(
            session,
            event_type=AuditEventType.INITIATIVE_MEMBER_REMOVED,
            actor_user_id=current_user.id,
            member_user_id=user_id,
            initiative_id=initiative_id,
            guild_id=guild_context.guild_id,
            detail={"role": role_name, "via": "manager"},
        )

        await session.commit()
        # Removed from the initiative — drop this user's live content streams in
        # the guild immediately (initiative-level access change).
        await content_sockets.revoke_user(guild_context.guild_id, user_id)

    return await _read_initiative(initiative_id, session, guild_context)


@router.patch("/{initiative_id}/members/{user_id}", response_model=InitiativeRead)
async def update_initiative_member(
    initiative_id: int,
    user_id: int,
    payload: InitiativeMemberUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> InitiativeRead:
    """Update a member's role."""
    initiative = await _get_initiative_or_404(initiative_id, session)
    await _require_manager_access(
        session,
        initiative,
        current_user,
        guild_context=guild_context,
    )

    # Verify role exists and belongs to this initiative
    new_role = await initiatives_service.get_role_by_id(
        session, role_id=payload.role_id, initiative_id=initiative_id
    )
    if not new_role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.ROLE_NOT_FOUND,
        )

    # Guild admins may only be elevated to a manager role, never assigned a
    # standard member or custom role (they already have full access).
    await _guard_guild_admin_role(
        session,
        guild_id=routed_guild_id(session),
        target_user_id=user_id,
        role=new_role,
    )
    await _guard_full_access_role(
        session,
        guild_id=routed_guild_id(session),
        target_user_id=user_id,
        role=new_role,
        guild_context=guild_context,
    )

    stmt = (
        select(InitiativeMember)
        .options(selectinload(InitiativeMember.role_ref))
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.MEMBER_NOT_FOUND,
        )

    if membership.role_id != payload.role_id:
        await _guard_full_access_role(
            session,
            guild_id=guild_context.guild_id,
            target_user_id=user_id,
            role=membership.role_ref,
            guild_context=guild_context,
        )
        # Check if demoting from manager role
        if (
            membership.role_ref
            and membership.role_ref.is_manager
            and not new_role.is_manager
        ):
            await initiatives_service.ensure_managers_remain(
                session, initiative_id=initiative.id, excluded_user_ids={user_id}
            )
        from_role_id = membership.role_id
        from_role_name = membership.role_ref.name if membership.role_ref else None
        membership.role_id = payload.role_id
        session.add(membership)
        await _record_membership(
            session,
            event_type=AuditEventType.INITIATIVE_MEMBER_ROLE_CHANGED,
            actor_user_id=current_user.id,
            member_user_id=user_id,
            initiative_id=initiative_id,
            guild_id=guild_context.guild_id,
            detail={
                "from_role_id": from_role_id,
                "from": from_role_name,
                "to_role_id": payload.role_id,
                "to": new_role.name,
            },
        )
        await session.commit()
        # Role change may reduce content access — re-check this user's live
        # content streams immediately (initiative-level access change).
        await content_sockets.revoke_user(guild_context.guild_id, user_id)

    return await _read_initiative(initiative_id, session, guild_context)
