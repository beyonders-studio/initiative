import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import case, func
from sqlmodel import select

from app.api.deps import (
    SystemSessionDep,
    UserSessionDep,
    get_current_active_user,
    require_capability,
)
from app.api.v1.platform_endpoints.session_opening import require_login_method
from app.core.audit_events import AuditEventType
from app.core.capabilities import (
    Capability,
    can_assign_role,
    capabilities_for,
    may_act_on,
    role_rank,
    user_has_capability,
)
from app.core.login_methods import LoginMethod
from app.core.messages import (
    AuthMessages,
    GuildMessages,
    OperatorMessages,
    SettingsMessages,
    UserMessages,
)
from app.core.user_display import handle_of
from app.db.query import build_paginated_response, paginated_query
from app.models.platform.user import User, UserStatus
from app.models.platform.user_email import UserEmail
from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.schemas.platform.auth import VerificationSendResponse
from app.schemas.platform.operator import (
    CommunityBlockerInfo,
    OperatorAccountCaseRead,
    OperatorDeletionEligibilityResponse,
    OperatorSuspensionUpdate,
    OperatorUserDeleteRequest,
    OperatorUsernameUpdate,
    PlatformRoleUpdate,
    ProfileField,
)
from app.schemas.platform.user import (
    AccountDeletionResponse,
    OperatorUserListResponse,
    OperatorUserRead,
    UserAction,
)
from app.services import audit as audit_service
from app.services import email as email_service
from app.services import notifications as notifications_service
from app.services.auth import addresses, sign_in_locks
from app.services.auth import challenges as challenge_service
from app.services.auth import sessions as session_service
from app.services.auth import totp as totp_service
from app.services.content_sockets import sockets as content_sockets
from app.services.platform import (
    account_stream,
    case_activity,
    csv_export,
    grant_cases,
    user_tokens,
)
from app.services.platform import api_keys as api_keys_service
from app.services.platform import guilds as guilds_service
from app.services.platform import user_avatars as user_avatars_service
from app.services.platform import usernames as username_service
from app.services.platform import users as users_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-capability guards. Each operator endpoint is gated on the specific
# capability it needs rather than a platform role name, so the privilege
# ladder (member → support → moderator → operator → owner) maps cleanly onto
# what each operation actually requires.
UsersReadDep = Annotated[User, Depends(require_capability(Capability.USERS_READ))]
UsersAgeUnblockDep = Annotated[
    User, Depends(require_capability(Capability.USERS_AGE_UNBLOCK))
]
UsersManageDep = Annotated[User, Depends(require_capability(Capability.USERS_MANAGE))]
ContentModerateDep = Annotated[
    User, Depends(require_capability(Capability.CONTENT_MODERATE))
]
UsersDeleteDep = Annotated[User, Depends(require_capability(Capability.USERS_DELETE))]
GuildsManageDep = Annotated[
    User, Depends(require_capability(Capability.COMMUNITIES_MANAGE))
]
CommunitiesReadDep = Annotated[
    User, Depends(require_capability(Capability.COMMUNITIES_READ))
]
CommunitiesSuspendDep = Annotated[
    User, Depends(require_capability(Capability.COMMUNITIES_SUSPEND))
]
BillingInsightsDep = Annotated[
    User, Depends(require_capability(Capability.BILLING_INSIGHTS))
]
BillingContractsDep = Annotated[
    User, Depends(require_capability(Capability.BILLING_CONTRACTS))
]
BillingDirectoryDep = Annotated[
    User, Depends(require_capability(Capability.BILLING_DIRECTORY))
]
BillingControlDep = Annotated[
    User, Depends(require_capability(Capability.BILLING_CONTROL))
]
RolesAssignDep = Annotated[User, Depends(require_capability(Capability.ROLES_ASSIGN))]
# App-wide configuration (OIDC, SMTP, branding, role labels, platform AI).
# Owner-only — imported by settings.py / ai_settings.py.
ConfigManageDep = Annotated[User, Depends(require_capability(Capability.CONFIG_MANAGE))]


#: What each account act is called on the case it was taken for.
_ACT_NAMES: dict[str, str] = {
    "clear_second_factor": "cleared the second factor of",
    "sign_user_out_everywhere": "signed out everywhere",
    "clear_profile_field": "cleared part of the profile of",
    "trigger_password_reset": "sent a password reset to",
    "reactivate_user": "reactivated",
    "restore_deleted_user": "called off the deletion of",
    "remove_user_avatar": "took down the picture of",
    "set_user_username": "renamed",
    "set_user_suspension": "changed the suspension of",
    "lift_sign_in_lock": "turned password sign-in back on for",
    "revoke_user_api_keys": "revoked the API keys of",
    "clear_age_block": "let answer the age question again",
    "update_platform_role": "changed the platform role of",
    "delete_user": "deleted",
}


@dataclass
class ActCase:
    """The operations case an act on an account is taken for, where one is
    named. ``what`` says what the act did, where the route knows better than
    its name."""

    task_id: int | None = None
    what: str | None = None


async def _act_case(
    request: Request,
    actor: Annotated[User, Depends(get_current_active_user)],
    case_task_id: Annotated[
        int | None,
        Query(
            gt=0,
            description=(
                "The operations case this act is for: one the caller can read, "
                "still open. The case is told of the act."
            ),
        ),
    ] = None,
) -> AsyncIterator[ActCase]:
    """Hold the case an act names to one the actor reads and that is open,
    before the act; tell it of the act once the act is done."""
    act = ActCase(task_id=case_task_id)
    if case_task_id is not None:
        try:
            await grant_cases.check_account_case(actor, case_task_id=case_task_id)
        except grant_cases.GrantCaseError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    yield act
    if act.task_id is None:
        return
    route = getattr(request.scope.get("route"), "name", "")
    target_id = request.path_params.get("user_id")
    target = None
    if target_id is not None:
        from app.db.session import SystemSessionLocal

        async with SystemSessionLocal() as session:
            target = await session.get(User, int(target_id))
    named = (
        f"account {handle_of(target)} (#{target_id})"
        if target is not None
        else f"account #{target_id}"
    )
    what = act.what or _ACT_NAMES.get(route, "acted on")
    await grant_cases.note(
        act.task_id,
        case_activity.ActivityKind.account_act,
        f"{handle_of(actor)} {what} {named}.",
    )


#: The case an act on an account is taken for. See :func:`_act_case`.
ActCaseDep = Annotated[ActCase, Depends(_act_case)]


async def _account_within_rank(
    session: SystemSessionDep, user_id: int, actor: User, *, lock: bool = False
) -> User:
    """The account an operator action names, when the actor may act on it
    (:func:`~app.core.capabilities.may_act_on`): not their own, and at or
    below their own rung — the bound a role change and a suspension apply."""
    stmt = select(User).where(User.id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    user = (await session.exec(stmt)).one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )
    if not may_act_on(actor, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                OperatorMessages.CANNOT_ACT_ON_SELF
                if user.id == actor.id
                else OperatorMessages.CANNOT_MANAGE_HIGHER_ROLE
            ),
        )
    return user


def _user_actions(
    actor: User,
    target: User,
    read: OperatorUserRead,
    *,
    community_names: bool,
    password_sign_in: bool,
) -> list[UserAction]:
    """What ``actor`` may do to ``target``, from their capabilities, their
    rung and the account's state: each route's own refusals, asked up front."""
    can = lambda capability: user_has_capability(actor, capability)
    acts = may_act_on(actor, target)
    live = target.status in (UserStatus.active, UserStatus.suspended)
    actions: list[UserAction] = []
    if acts and can(Capability.CONTENT_MODERATE):
        if target.status != UserStatus.anonymized:
            actions.append(UserAction.rename)
        if target.avatar_url:
            actions.append(UserAction.remove_avatar)
        if community_names:
            actions.append(UserAction.clear_display_names)
        if target.custom_status:
            actions.append(UserAction.clear_custom_status)
        if target.profile_decorations:
            actions.append(UserAction.clear_decorations)
    if acts and can(Capability.CONTENT_MODERATE):
        if target.status == UserStatus.active:
            actions.append(UserAction.suspend)
        if target.status == UserStatus.suspended:
            actions.append(UserAction.unsuspend)
    if (
        can(Capability.ROLES_ASSIGN)
        and target.id != actor.id
        and target.status == UserStatus.active
        and can_assign_role(actor, target.role)
    ):
        actions.append(UserAction.change_role)
    if acts and can(Capability.USERS_MANAGE):
        if read.api_key_count > 0:
            actions.append(UserAction.revoke_api_keys)
        if read.second_factor_enrolled:
            actions.append(UserAction.clear_second_factor)
        if live:
            actions.append(UserAction.sign_out_everywhere)
        if target.status == UserStatus.active and password_sign_in:
            actions.append(UserAction.reset_password)
        if target.status == UserStatus.active and not read.email_verified:
            actions.append(UserAction.resend_verification)
        if read.sign_in_locked_until is not None:
            actions.append(UserAction.lift_sign_in_lock)
    if (
        acts
        and can(Capability.USERS_AGE_UNBLOCK)
        and (read.age_below_minimum_at or read.birthdate_on_file)
    ):
        actions.append(UserAction.clear_age_block)
    if acts and can(Capability.USERS_MANAGE):
        if target.status == UserStatus.deactivated:
            actions.append(UserAction.reactivate)
        if target.status == UserStatus.deleted:
            actions.append(UserAction.restore)
    if acts and can(Capability.USERS_DELETE) and target.status != UserStatus.anonymized:
        actions.append(UserAction.delete)
    return actions


async def _rows(users: list[User], actor: User) -> list[OperatorUserRead]:
    """The roster rows for ``users``, as ``actor`` may act on them: what they
    may do to each, and how many open cases each account has."""
    from app.db.session import SystemSessionLocal
    from app.models.platform.guild import GuildMembership
    from app.services.platform import auth_posture
    from app.services.platform import intake as intake_service

    reads = await users_service.to_operator_read(users)
    ids = [int(u.id) for u in users]
    async with SystemSessionLocal() as system:
        named = set(
            (
                await system.exec(
                    select(GuildMembership.user_id)
                    .where(GuildMembership.user_id.in_(ids))
                    .where(GuildMembership.display_name.is_not(None))
                    .distinct()
                )
            ).all()
        )
        password_sign_in = await auth_posture.login_method_allowed(
            system, LoginMethod.password
        )
    cases = await intake_service.open_case_counts(ids)
    for read, user in zip(reads, users):
        read.allowed_actions = _user_actions(
            actor,
            user,
            read,
            community_names=user.id in named,
            password_sign_in=password_sign_in,
        )
        read.open_case_count = cases.get(int(user.id), 0)
    return reads


async def _row(user: User, actor: User) -> OperatorUserRead:
    return (await _rows([user], actor))[0]


#: Accounts ordered by how much of the app is left to them, so sorting on
#: status brings the ones needing attention together at one end.
_STATUS_RANK = {
    UserStatus.active: 0,
    UserStatus.suspended: 1,
    UserStatus.deactivated: 2,
    UserStatus.deleted: 3,
    UserStatus.anonymized: 4,
}

_USER_SORT_FIELDS = {
    "id": User.id,
    "username": User.username,
    "status": case(_STATUS_RANK, value=User.status, else_=len(_STATUS_RANK)),
}


@router.get("/users", response_model=OperatorUserListResponse)
async def list_all_users(
    session: UserSessionDep,
    current_user: UsersReadDep,
    search: str | None = Query(
        default=None,
        description=(
            "Matches the handle's name part; a whole handle (`foobar#1234`) "
            "pins one account."
        ),
    ),
    sort_by: Literal["id", "username", "status"] | None = None,
    sort_dir: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> OperatorUserListResponse:
    """One page of the platform's accounts (``users.read``).

    Platform-scoped: runs on the role-scoped session (``platform_<tier>``), so the
    cross-user read is authorized by RLS (``users_platform_read``, support+) rather
    than the system engine. Initiative roles are guild-scoped and
    deliberately NOT loaded here — a platform user view exposes platform data only.

    Ordered by ``sort_by`` when given; otherwise nearest match first while
    searching, and oldest account first while not.
    """
    base = select(User)
    closest = None
    if search and (term := search.strip()):
        matches, closest = users_service.member_match(
            term, match_names=False, profile=User
        )
        base = base.where(matches)

    if sort_by is not None:
        order = _USER_SORT_FIELDS[sort_by]
        data_stmt = base.order_by(
            order.desc() if sort_dir == "desc" else order.asc(), User.id.asc()
        )
    elif closest is not None:
        data_stmt = base.order_by(closest.desc(), User.id.asc())
    else:
        data_stmt = base.order_by(User.id.asc())

    users, total_count, actual_page = await paginated_query(
        session,
        data_stmt,
        select(func.count()).select_from(base.subquery()),
        page=page,
        page_size=page_size,
    )
    return OperatorUserListResponse(
        **build_paginated_response(
            await _rows(list(users), current_user),
            total_count,
            actual_page,
            page_size,
        )
    )


#: ``email`` is masked here exactly as it is in the roster this exports, so
#: the two agree. The column stays because matching a row to an address you
#: were given is what it is read for.
_PLATFORM_CSV_HEADERS = [
    "user_id",
    "email",
    "handle",
    "platform_role",
    "status",
    "email_verified",
    "created_at",
    "updated_at",
    "timezone",
    "locale",
]


@router.get("/users/export.csv")
async def export_platform_users_csv(
    session: UserSessionDep,
    current_user: UsersReadDep,
    user_id: Annotated[list[int] | None, Query()] = None,
) -> Response:
    """Export platform users as a CSV file. Pass `user_id` one or more times to
    restrict the export to a subset. Without `user_id`, every user is included.
    Support and above (``users.read``)."""
    stmt = select(User).order_by(User.created_at.asc())
    if user_id:
        stmt = stmt.where(User.id.in_(user_id))
    result = await session.exec(stmt)
    users = list(result.all())

    if user_id and not users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    # Through the same shape the roster returns, so the export cannot be the one
    # place that forgets to mask an address.
    records = await users_service.to_operator_read(users)

    rows = []
    for record in records:
        rows.append(
            [
                record.id,
                record.email,
                handle_of(record),
                record.role.value if hasattr(record.role, "value") else record.role,
                record.status.value
                if hasattr(record.status, "value")
                else record.status,
                record.email_verified,
                record.created_at.isoformat() if record.created_at else "",
                record.updated_at.isoformat() if record.updated_at else "",
                record.timezone or "",
                record.locale or "",
            ]
        )

    csv_bytes = csv_export.build_csv(_PLATFORM_CSV_HEADERS, rows)

    if len(users) == 1 and user_id:
        single_user = users[0]
        # Named by handle rather than address: a filename outlives the
        # download, appearing in directory listings and wherever it is sent on.
        filename = (
            f"user-{single_user.id}-"
            f"{csv_export.safe_filename_component(single_user.username)}.csv"
        )
    else:
        datestamp = datetime.now(UTC).date().isoformat()
        filename = f"platform-users-{datestamp}.csv"

    # Nothing changed, so the endpoint has no commit of its own to ride: the
    # record is the whole write.
    await audit_service.record(
        session,
        event_type=AuditEventType.PLATFORM_USERS_EXPORTED,
        actor_user_id=current_user.id,
        detail={"count": len(users), "subset": bool(user_id)},
    )
    await session.commit()

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/users/{user_id}/second-factor", status_code=status.HTTP_204_NO_CONTENT)
async def clear_second_factor(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
    act_case: ActCaseDep,
) -> None:
    """Remove somebody's second factor for them.

    The lost-phone path: the person cannot present the factor and cannot reach
    the recovery codes either, so somebody with the run of platform accounts
    takes it off and they enrol again.

    A clear, never a read — nothing here hands back the seed or the codes, to
    this caller or any other. Their sessions and any part-way sign-in go with
    it, and the account is told.
    """
    user = await _account_within_rank(session, user_id, current_user)
    if not await totp_service.is_enrolled(session, user_id=user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.TOTP_NOT_ENROLLED,
        )

    await totp_service.disable(session, user_id=user_id)
    await challenge_service.revoke_for_user(session, user_id=user_id)
    await session_service.revoke_all_for_user(session, user_id=user_id)
    await audit_service.record(
        session,
        event_type=AuditEventType.AUTH_SECOND_FACTOR_RESET,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
    )
    await session.commit()
    # Connections opened on the ended sessions close now.
    await content_sockets.revoke_user_everywhere(user_id)
    await email_service.announce_second_factor_change(session, user, enabled=False)


@router.delete("/users/{user_id}/sessions", response_model=OperatorUserRead)
async def sign_user_out_everywhere(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """End every session an account has, on every device (``users.manage``).

    For an account somebody else may be signed in to: its holder signs in
    again, and whoever else had it does not. Its open connections close now.
    """
    user = await _account_within_rank(session, user_id, current_user, lock=True)
    await challenge_service.revoke_for_user(session, user_id=user_id)
    await session_service.revoke_all_for_user(session, user_id=user_id)
    # The access tokens already handed out stop working with the sessions.
    user.token_version += 1
    user.updated_at = datetime.now(UTC)
    session.add(user)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_SESSIONS_REVOKED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
    )
    await session.commit()
    await content_sockets.revoke_user_everywhere(user_id)
    await session.refresh(user)
    return await _row(user, current_user)


@router.delete("/users/{user_id}/profile/{field}", response_model=OperatorUserRead)
async def clear_profile_field(
    user_id: int,
    field: ProfileField,
    session: SystemSessionDep,
    current_user: ContentModerateDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Clear part of how an account appears to others (``content.moderate``).

    ``display_names`` clears the names it goes by in its communities, all of
    them; ``custom_status`` its status line; ``decorations`` its banner, frame
    and trophies. Like a picture takedown, for what breaches the terms of use:
    its holder may set them again.
    """
    from sqlalchemy import update

    from app.models.platform.guild import GuildMembership

    user = await _account_within_rank(session, user_id, current_user)
    act_case.what = {
        "display_names": "cleared the names in communities of",
        "custom_status": "cleared the status line of",
        "decorations": "cleared the decorations of",
    }[field]
    if field == "display_names":
        await session.exec(
            update(GuildMembership)
            .where(GuildMembership.user_id == user_id)
            .where(GuildMembership.display_name.is_not(None))
            .values(display_name=None)
        )
    elif field == "custom_status":
        user.custom_status = {}
    else:
        user.profile_decorations = {}
    user.updated_at = datetime.now(UTC)
    session.add(user)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_PROFILE_FIELD_CLEARED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"field": field},
    )
    # Told what went, never by whom, as for a picture taken down.
    await notifications_service.queue_profile_field_cleared(
        session, user=user, field=field
    )
    # Their open tabs read their own profile again.
    account_stream.queue_account_signal(session, user_id, "profile")
    await session.commit()
    await session.refresh(user)
    return await _row(user, current_user)


@router.get("/users/{user_id}/cases", response_model=list[OperatorAccountCaseRead])
async def list_account_cases(
    user_id: int,
    _current_user: UsersReadDep,
) -> list[OperatorAccountCaseRead]:
    """The open operations cases an account filed or is the subject of
    (``users.read``): where each lives, to open it, and nothing it says."""
    from app.services.platform import intake as intake_service

    return [
        OperatorAccountCaseRead(
            task_id=case.task_id,
            stream=case.stream,
            community_id=case.guild_id,
            initiative_id=case.initiative_id,
            project_id=case.project_id,
            filed=case.filed,
        )
        for case in await intake_service.open_cases_for(user_id)
    ]


@router.post("/users/{user_id}/reset-password", response_model=VerificationSendResponse)
async def trigger_password_reset(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
    act_case: ActCaseDep,
) -> VerificationSendResponse:
    """Trigger a password reset email for a user (``users.manage``).

    Refused where the deployment takes no password, as the reset it links to is.
    """
    await require_login_method(session, LoginMethod.password)
    user = await _account_within_rank(session, user_id, current_user)

    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_RESET_INACTIVE,
        )

    try:
        token = await user_tokens.create_token(
            session,
            user_id=user.id,
            purpose=UserTokenPurpose.password_reset,
            expires_minutes=60,
        )
        await email_service.send_password_reset_email(session, user, token)
    except email_service.EmailNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.SMTP_INCOMPLETE,
        ) from None
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SettingsMessages.EMAIL_SEND_FAILED,
        ) from exc
    return VerificationSendResponse(status="sent")


@router.post(
    "/users/{user_id}/verification-email", response_model=VerificationSendResponse
)
async def resend_verification_email(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
) -> VerificationSendResponse:
    """Send an account's sign-up confirmation letter again (``users.manage``).

    For somebody whose first letter expired or never arrived. It goes to the
    address they signed up with and replaces the one they were sent; the
    invite that letter was waiting on still joins when they confirm.
    """
    user = await _account_within_rank(session, user_id, current_user)
    address = None
    if not await addresses.has_proven_address(session, user_id=user.id):
        address = (
            await session.exec(
                select(UserEmail).where(
                    UserEmail.user_id == user.id,
                    UserEmail.is_primary,
                    UserEmail.verified_at.is_(None),
                    UserEmail.source != addresses.SOURCE_SYNTHETIC,
                )
            )
        ).one_or_none()
    if address is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=OperatorMessages.NOTHING_TO_VERIFY,
        )
    invite_id = (
        await session.exec(
            select(UserToken.invite_id).where(
                UserToken.user_id == user.id,
                UserToken.purpose == UserTokenPurpose.email_verification,
                UserToken.user_email_id == address.id,
                UserToken.invite_id.is_not(None),
            )
        )
    ).first()
    if not await email_service.email_configured(session):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=SettingsMessages.SMTP_INCOMPLETE,
        )

    # The new letter replaces the old one only once it has been sent.
    token = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.email_verification,
        expires_minutes=60 * 24,
        user_email_id=address.id,
        invite_id=invite_id,
        commit=False,
    )
    try:
        await email_service.send_verification_email(session, user, token)
    except RuntimeError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=SettingsMessages.EMAIL_SEND_FAILED,
        ) from exc
    await session.commit()
    return VerificationSendResponse(status="sent")


@router.post("/users/{user_id}/reactivate", response_model=OperatorUserRead)
async def reactivate_user(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Reactivate a deactivated user account (``users.manage``).

    A suspension is lifted through ``suspension`` and a pending deletion
    called off through ``restore``; this reopens only a deactivated account.
    """
    user = await _account_within_rank(session, user_id, current_user)

    if user.status == UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.USER_ALREADY_ACTIVE,
        )

    if user.status == UserStatus.anonymized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CANNOT_REACTIVATE_ANONYMIZED,
        )

    if user.status != UserStatus.deactivated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=OperatorMessages.USER_NOT_DEACTIVATED,
        )

    user.status = UserStatus.active
    user.updated_at = datetime.now(UTC)
    session.add(user)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_REACTIVATED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
    )
    await session.commit()
    await session.refresh(user)
    # Platform user management stays platform-table-only: initiative
    # membership is guild-schema content this path cannot read.
    return await _row(user, current_user)


@router.post("/users/{user_id}/restore", response_model=OperatorUserRead)
async def restore_deleted_user(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Call off a pending erasure from the users table (``users.manage``).

    The account's holder can do this themselves simply by signing in, which is
    the ordinary way it happens. This is for when they cannot — the address is
    gone, the phone is gone, they asked somebody — and for an operator undoing
    a deletion they made on somebody's behalf.

    Nothing is restored as such: the account never lost anything. It kept its
    memberships, its initiative roles and the files it owns for the whole
    window, so this puts it back exactly where it was.

    Separate from ``reactivate``, which is for a *deactivated* account and
    gives back an account with no communities — the memberships that one
    dropped are not coming back.
    """
    user = await _account_within_rank(session, user_id, current_user)
    if user.status != UserStatus.deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=OperatorMessages.USER_NOT_DELETED,
        )
    await users_service.cancel_account_deletion(
        session, user_id, actor_user_id=current_user.id, via="operator"
    )
    await session.commit()
    await session.refresh(user)
    return await _row(user, current_user)


@router.delete("/users/{user_id}/avatar", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_avatar(
    user_id: int,
    session: SystemSessionDep,
    current_user: ContentModerateDep,
    act_case: ActCaseDep,
) -> Response:
    """Take down a user's profile picture.

    People occasionally upload images that breach the terms of use, so removal
    cannot wait for the uploader to do it. Gated on ``content.moderate``, which
    is a platform capability — a guild admin is a tenancy role and has no part
    in this, so a guild's administrator cannot reach a member's profile image.

    Removal only. There is deliberately no path by which one account sets
    another account's picture.

    The bytes are destroyed rather than hidden. Runs on the system engine
    because the row policies scope every request-path write to the caller's own
    avatar, so the capability check above, bounded by rank, is what admits it.
    """
    user = await _account_within_rank(session, user_id, current_user)

    # An externally hosted picture is the same surface by another route, so a
    # takedown that left it in place would not be one: both go.
    had_picture = bool(user.avatar_url)
    removed = await user_avatars_service.delete_avatar(
        session, user_id=user_id, user=user
    )
    if user.avatar_url:
        user.avatar_url = None
        session.add(user)

    if removed or had_picture:
        # Queued before the commit, not after it: silent removal reads as a
        # bug, so the picture going and the person being told are one write.
        await notifications_service.queue_avatar_removed(session, user=user)
        # Recorded in the same transaction, for the same reason: the takedown
        # and the record of who did it commit together or not at all.
        await audit_service.record(
            session,
            event_type=AuditEventType.USER_AVATAR_REMOVED,
            actor_user_id=current_user.id,
            target_user_id=user_id,
            target_type="user",
            target_id=user_id,
        )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/users/{user_id}/username", response_model=OperatorUserRead)
async def set_user_username(
    user_id: int,
    payload: OperatorUsernameUpdate,
    session: SystemSessionDep,
    current_user: ContentModerateDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Change someone's username.

    People occasionally pick a handle that breaches the terms of use, and it is
    the one part of an account everyone else sees, so changing it cannot wait
    for its owner. Gated on ``content.moderate`` — a platform capability, like
    the picture takedown beside it; a guild's administrator has no part in this.

    The name part is validated exactly as registration validates it. The number
    is not the moderator's to choose either: the existing one is kept, and a
    new one drawn only if that pair is already held.

    This also marks the handle as chosen, so its owner cannot immediately spend
    a pick on undoing a moderation decision.
    """
    user = await _account_within_rank(session, user_id, current_user)

    previous_handle = handle_of(user)
    await username_service.set_for_user(
        session, user=user, name=payload.username, keep_discriminator=True
    )

    user.updated_at = datetime.now(UTC)
    session.add(user)
    await notifications_service.queue_username_changed(
        session, user=user, previous_handle=previous_handle
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_USERNAME_CHANGED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
    )
    await session.commit()
    await session.refresh(user)
    return await _row(user, current_user)


@router.post("/users/{user_id}/suspension", response_model=OperatorUserRead)
async def set_user_suspension(
    user_id: int,
    payload: OperatorSuspensionUpdate,
    session: SystemSessionDep,
    current_user: ContentModerateDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Freeze an account, or let it go.

    Suspension takes nothing away: memberships, grants, assignments and
    everything the account authored stay exactly where they are, so lifting it
    restores the account whole. What it does is close every guild — the holder
    still signs in and reaches their own account, which is how they can be told
    why.

    Gated on ``content.moderate`` (moderator and above). No PAM grant is involved:
    this is a platform action about an account, not access to a guild's
    content.
    """
    if user_id == current_user.id:
        # Suspending yourself would take your own guilds away and leave the
        # lifting of it to someone else.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_SUSPEND_SELF,
        )

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    # A closed or erased account is not a live one to freeze, and thawing it
    # would quietly reopen an account its owner closed.
    if user.status not in (UserStatus.active, UserStatus.suspended):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_SUSPEND_INACTIVE,
        )

    # The same bound as a role change: nobody acts on an account that outranks
    # them, in either direction. An owner is therefore suspended only by another
    # owner, who stays behind holding config-management.
    if role_rank(user.role) > role_rank(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=OperatorMessages.CANNOT_SUSPEND_HIGHER_ROLE,
        )

    already = user.status == UserStatus.suspended
    if already == payload.suspended:
        # Nothing changed, so there is nothing to tell a case.
        act_case.task_id = None
        return await _row(user, current_user)

    act_case.what = "suspended" if payload.suspended else "lifted the suspension of"
    user.status = UserStatus.suspended if payload.suspended else UserStatus.active
    user.updated_at = datetime.now(UTC)
    user.status_changed_at = user.updated_at
    user.status_reason = (
        (payload.reason or "").strip() or None if payload.suspended else None
    )
    session.add(user)

    if payload.suspended:
        await notifications_service.queue_account_suspended(
            session, user=user, reason=payload.reason
        )
    else:
        await notifications_service.queue_account_unsuspended(session, user=user)

    await audit_service.record(
        session,
        event_type=(
            AuditEventType.USER_SUSPENDED
            if payload.suspended
            else AuditEventType.USER_UNSUSPENDED
        ),
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"reason_given": bool((payload.reason or "").strip())},
    )
    await session.commit()
    await session.refresh(user)

    if payload.suspended:
        # Sockets opened before this carry the account as it was when they
        # joined, so they are re-checked now rather than at the next sweep.
        # Everywhere at once: this is a change to the account, which has no one
        # guild to name.
        await content_sockets.revoke_user_everywhere(user_id)

    return await _row(user, current_user)


@router.delete("/users/{user_id}/sign-in-lock", response_model=OperatorUserRead)
async def lift_sign_in_lock(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Turn an account's password and code sign-in back on.

    Wrong passwords or codes turn them off for a while, longer for each lock
    within a day. This lifts the lock now, and starts both counts over.

    Gated on ``users.manage`` (moderator and above), like a suspension.
    """
    user = await _account_within_rank(session, user_id, current_user)
    if not await sign_in_locks.lift(session, user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.SIGN_IN_NOT_LOCKED,
        )

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_SIGN_IN_LOCK_LIFTED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={},
    )
    await session.commit()
    return await _row(user, current_user)


@router.delete("/users/{user_id}/api-keys", response_model=OperatorUserRead)
async def revoke_user_api_keys(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersManageDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Switch off every API key on an account that still works.

    The keys stay on the account's own list, marked off, so its holder can see
    what stopped and make new ones. Gated on ``users.manage``, like a
    suspension.
    """
    user = await _account_within_rank(session, user_id, current_user)
    revoked = await api_keys_service.deactivate_user_api_keys(
        session, user_id=user_id, revoked_by=current_user.id
    )
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.NO_LIVE_API_KEYS,
        )
    await session.commit()
    return await _row(user, current_user)


@router.delete("/users/{user_id}/age-block", response_model=OperatorUserRead)
async def clear_age_block(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersAgeUnblockDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Let an account answer the age question again.

    An answer stands — an under-age one, and any kept date of birth — and the
    question is not re-asked, otherwise it is not a question. This is the way
    back for the case that is nearly all of them: a mistyped year. It clears
    the under-age record, the confirmation and the kept date, and nothing
    else; the account answers again from scratch.

    An account whose answer closed it (under the minimum for an account where
    it was, ``age_below_account_minimum_at``) is still scheduled for erasure
    after this. Clearing the marks is what lets its holder sign in, and that
    sign-in is what calls the erasure off and restores the account whole —
    or ``restore`` below does, for an operator doing both at once.

    Gated on ``users.age_unblock``, which the support tier holds — the lowest
    rung, because getting somebody back into their account after a typo is
    support work rather than a moderation decision. Recorded either way: it is
    one person restoring another's access, which is exactly the kind of thing
    a log is for.
    """
    user = await _account_within_rank(session, user_id, current_user)
    kept = await users_service.birthdate_of(session, user_id=user_id) is not None
    if user.age_below_minimum_at is None and not kept:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=UserMessages.AGE_NOT_BLOCKED,
        )

    await users_service.forget_birthdate(session, user_id=user_id)
    # The account answers from scratch, so every part of the earlier answer goes.
    user.age_below_minimum_at = None
    user.age_below_account_minimum_at = None
    user.age_confirmed_at = None
    user.updated_at = datetime.now(UTC)
    session.add(user)

    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AGE_BLOCK_CLEARED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={},
    )
    # The question is theirs to answer again, so their open tabs re-read the
    # account and meet the form rather than the wall.
    account_stream.queue_account_signal(session, user_id, "age")
    await session.commit()
    await session.refresh(user)
    return await _row(user, current_user)


@router.patch("/users/{user_id}/platform-role", response_model=OperatorUserRead)
async def update_platform_role(
    user_id: int,
    payload: PlatformRoleUpdate,
    session: SystemSessionDep,
    current_user: RolesAssignDep,
    act_case: ActCaseDep,
) -> OperatorUserRead:
    """Update a user's platform role (``roles.assign``).

    Restrictions:
    - Cannot change your own role
    - Cannot demote the last owner
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_CHANGE_OWN_ROLE,
        )

    stmt = select(User).where(User.id == user_id).with_for_update()
    result = await session.exec(stmt)
    user = result.one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AuthMessages.USER_NOT_FOUND
        )

    # Refuse role changes on non-active accounts. A deactivated row's role
    # change is meaningless until the user is reactivated, and an
    # anonymized row should never gain or lose elevated privileges (the
    # account is permanently gone). The last-owner check counts active
    # holders only, so promoting a husk would also confuse it.
    if user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_CHANGE_ROLE_INACTIVE,
        )

    # Bounded delegation: you may only assign a role whose capabilities are a
    # subset of your own, and you may not modify a user who already outranks
    # you (an operator can't touch an owner, in either direction).
    if not can_assign_role(current_user, payload.role) or not can_assign_role(
        current_user, user.role
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=OperatorMessages.CANNOT_ASSIGN_HIGHER_ROLE,
        )

    # Don't strip config-management from the last user who has it — that would
    # lock the platform out of its own configuration. (FOR UPDATE acquired above.)
    if Capability.CONFIG_MANAGE not in capabilities_for(payload.role):
        await users_service.ensure_config_manager_remains(
            session, user_id, for_update=True
        )

    previous_role = user.role
    act_case.what = (
        f"changed the platform role ({previous_role.value} to {payload.role.value}) of"
    )
    user.role = payload.role
    user.updated_at = datetime.now(UTC)
    session.add(user)
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_PLATFORM_ROLE_CHANGED,
        actor_user_id=current_user.id,
        target_user_id=user_id,
        target_type="user",
        target_id=user_id,
        detail={"from": previous_role.value, "to": payload.role.value},
    )
    # What this account may do just changed, and it was not their doing. Their
    # open tabs re-read it rather than showing a rung they no longer hold.
    account_stream.queue_account_signal(session, user_id, "role")
    await session.commit()
    await session.refresh(user)
    # Platform user management stays platform-table-only (see reactivate).
    return await _row(user, current_user)


@router.get(
    "/users/{user_id}/deletion-eligibility",
    response_model=OperatorDeletionEligibilityResponse,
)
async def check_user_deletion_eligibility(
    user_id: int,
    session: SystemSessionDep,
    current_user: UsersDeleteDep,
) -> OperatorDeletionEligibilityResponse:
    """Check if a user can be deleted (``users.delete``).

    Returns the blockers ``delete_user`` refuses on: being the last platform
    owner, and the communities the user holds the only superadmin seat of.
    Owning content does not stop a deletion, because ownership is released on
    the way out and the content is left unowned for a guild admin to claim.
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.USE_SELF_DELETION,
        )

    await _account_within_rank(session, user_id, current_user)

    last_owner = await users_service.is_last_capability_holder(
        session, user_id, Capability.CONFIG_MANAGE
    )
    community_blockers = [
        CommunityBlockerInfo(community_id=guild_id, community_name=guild_name)
        for guild_id, guild_name in await guilds_service.stranded_seats(
            session, user_id=user_id
        )
    ]
    return OperatorDeletionEligibilityResponse(
        can_delete=not last_owner and not community_blockers,
        last_owner=last_owner,
        community_blockers=community_blockers,
    )


@router.delete("/users/{user_id}", response_model=AccountDeletionResponse)
async def delete_user(
    user_id: int,
    payload: OperatorUserDeleteRequest,
    session: SystemSessionDep,
    current_user: UsersDeleteDep,
    act_case: ActCaseDep,
) -> AccountDeletionResponse:
    """Delete, anonymize, or deactivate a user account (``users.delete``).

    `action` selects the path:
      - `deactivate` — reversible; flips status to deactivated, drops memberships.
      - `soft_delete` — anonymizes PII; keeps the row so historical FKs still resolve.
      - `hard_delete` — permanently removes the row and cascades cleanup.

    For both `soft_delete` and `hard_delete`, projects the user solely owns
    must be transferred — only owners hold certain permissions, and an
    anonymized owner row can't act on them.

    Restrictions:
    - Cannot delete yourself (use /me/delete-account)
    - Cannot delete the last owner
    """
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.CANNOT_DELETE_SELF,
        )

    user = await _account_within_rank(session, user_id, current_user, lock=True)
    act_case.what = {
        "deactivate": "deactivated",
        "soft_delete": "scheduled the deletion of",
        "hard_delete": "permanently deleted",
    }[payload.action]

    await users_service.ensure_config_manager_remains(session, user_id, for_update=True)

    # Holding a guild's only superadmin seat is the only blocker. Content the
    # user owns is released as their memberships go and left unowned for a guild
    # admin to claim, so there is nothing for this endpoint to collect first.
    if await users_service.is_last_guild_superadmin(session, user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=GuildMessages.CANNOT_VACATE_LAST_SUPERADMIN,
        )

    # An already-anonymized row is a permanently empty husk; the only
    # valid follow-up is hard delete. Refuse deactivate / soft_delete
    # explicitly — without this guard, deactivate would flip
    # ``anonymized`` → ``deactivated``, which then satisfies the
    # ``reactivate`` endpoint's anonymized check and lets an operator
    # accidentally resurrect the husk as an active loginable account.
    if user.status == UserStatus.anonymized and payload.action != "hard_delete":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=OperatorMessages.ALREADY_ANONYMIZED,
        )

    if payload.action == "deactivate":
        await users_service.deactivate_user(
            session, user_id, actor_user_id=current_user.id
        )
        return AccountDeletionResponse(
            success=True,
            action="deactivate",
            message=f"User {user.username} has been deactivated",
        )

    if payload.action == "soft_delete":
        # The same windowed deletion the account holder gets from their own
        # danger zone. One meaning for the word on both surfaces, and the
        # reversible action is the one that is easy to reach — ``hard_delete``
        # below is the one that is not.
        await users_service.request_account_deletion(
            session, user_id, actor_user_id=current_user.id
        )
        return AccountDeletionResponse(
            success=True,
            action="soft_delete",
            message=f"User {user.username} has been deleted",
        )

    # hard_delete: the same per-guild erasure the purge runs, then the row
    # itself goes. Ownership is released; authorship keeps naming the id.
    await users_service.hard_delete_user(
        session, user_id, actor_user_id=current_user.id
    )
    return AccountDeletionResponse(
        success=True,
        action="hard_delete",
        message=f"User {user.username} has been permanently deleted",
    )
