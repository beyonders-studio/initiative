"""Privileged Access Management (PAM) endpoints.

Self-service, time-bound, per-guild access grants: a lower-privilege platform
user requests temporary access to a guild, an approver grants/denies it, and it
auto-expires. See ``app.services.access_grants``.

The reads run on the caller's platform tier (``UserSessionDep``): a grantee
reads their own grants, and an ``access.approve`` holder reads the queue, each
through its own policy on ``access_grants``. Every write — requesting, breaking
glass, deciding, revoking, withdrawing — runs on the system engine, which alone
writes the table; authorization for those is enforced here via capabilities +
ownership, mirroring the ``/operator/*`` endpoints.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from webauthn.helpers import bytes_to_base64url

from app.api.deps import (
    UserSessionDep,
    get_current_active_user,
    require_capability,
    SystemSessionDep,
)
from app.api.v1.platform_endpoints.session_opening import prove_second_factor
from app.core.capabilities import Capability
from app.core.clock import utcnow
from app.core.audit_events import AuditEventType
from app.core.messages import AccessGrantMessages, AuthMessages
from app.db.query import build_paginated_response
from app.models.platform.user import User
from app.models.platform.access_grant import (
    AccessGrant,
    AccessGrantPurpose,
    AccessGrantStatus,
    AccessLevel,
    CommunityNotice,
    SettingsLevel,
)
from app.schemas.platform.access_grant import (
    AccessGrantListResponse,
    AccessGrantApprove,
    AccessGrantCreate,
    AccessGrantLimits,
    AccessGrantRead,
    BreakGlassCreate,
    SecondFactorAnswer,
    BreakGlassRequirements,
    GrantCaseList,
    GrantCaseRead,
)
from app.schemas.platform.passkey import PasskeyAuthenticationOptions
from app.services import audit as audit_service
from app.services.auth import challenges as challenge_service
from app.services.auth import passkeys as passkey_service
from app.services.auth import totp as totp_service
from app.services.platform import access_grants as service
from app.services.platform import case_activity, grant_cases
from app.services.content_sockets import sockets as content_sockets
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()

AccessRequestDep = Annotated[
    User, Depends(require_capability(Capability.ACCESS_REQUEST))
]
AccessApproveDep = Annotated[
    User, Depends(require_capability(Capability.ACCESS_APPROVE))
]
# Break-glass is gated on data.bypass — the repurposed capability that lets an
# operator/owner self-issue an audited, time-bound grant instead of holding a
# standing all-guild bypass.
BreakGlassDep = Annotated[User, Depends(require_capability(Capability.DATA_BYPASS))]


async def _one(grant, *, system_session: AsyncSession | None = None) -> AccessGrantRead:
    reads = await service.to_read([grant], system_session=system_session)
    return reads[0]


async def _check_case(
    actor: User,
    case_task_id: Optional[int],
    guild_id: int,
    *,
    required: bool,
    notice: Optional[CommunityNotice],
) -> CommunityNotice:
    """Hold the case a grant is asked for to what it may be: one the asker
    reads, open, of a kind a grant serves, and about this community or none
    yet. Settling a case that names none waits for :func:`_claim_case`, once
    the grant itself has passed its own checks. Returns the notice the
    community is owed, from the case and what the asker chose."""
    try:
        if case_task_id is None:
            if required and await grant_cases.cases_required():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=AccessGrantMessages.CASE_REQUIRED,
                )
            return grant_cases.community_notice(None, notice)
        stream = await grant_cases.check_case(
            actor, case_task_id=case_task_id, guild_id=guild_id
        )
        return grant_cases.community_notice(stream, notice)
    except grant_cases.GrantCaseError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


async def _commit_with_case(
    session: AsyncSession, case_task_id: Optional[int], guild_id: int
) -> None:
    """Settle the case a grant names as about the grant's community, then
    commit the grant: after the grant has passed its checks, so a refused
    request names nothing on its case, and undone if the grant then fails to
    commit, so the two stand or fall together."""
    if case_task_id is None:
        await session.commit()
        return
    outcome = await grant_cases.claim(case_task_id, guild_id=guild_id)
    if outcome == "other":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AccessGrantMessages.CASE_OTHER_COMMUNITY,
        )
    try:
        await session.commit()
    except BaseException:
        if outcome == "named":
            await grant_cases.unclaim(case_task_id, guild_id=guild_id)
        raise


async def _tell_requested(
    session: AsyncSession,
    grants: list[AccessGrant],
    *,
    requester: User,
    guild_name: Optional[str],
) -> None:
    """Tell the case a request names that access was asked for it, and write
    down that each grant serves it."""
    case = grants[0].case_task_id
    if case is None:
        return
    for grant in grants:
        audit_service.emit(
            event_type=AuditEventType.ACCESS_GRANT_CASE_LINKED,
            actor_user_id=requester.id,
            guild_id=grant.guild_id,
            target_type="access_grant",
            target_id=grant.id,
            detail={"case_task_id": case, "purpose": grant.purpose},
        )
    await grant_cases.note(
        case,
        case_activity.ActivityKind.grant_requested,
        grant_cases.requested_text(grants, guild_name=guild_name, holder=requester),
    )


async def _tell_decided(
    session: AsyncSession,
    grant: AccessGrant,
    *,
    decided_by: User,
    guild_name: Optional[str],
) -> None:
    """Tell a grant's case how it was decided; an approval also puts a case
    still waiting to be picked up to work."""
    if grant.case_task_id is None:
        return
    holder = await session.get(User, grant.user_id)
    await grant_cases.note(
        grant.case_task_id,
        case_activity.ActivityKind.grant_decided,
        grant_cases.decided_text(
            grant, guild_name=guild_name, holder=holder, decided_by=decided_by
        ),
    )
    if grant.status == AccessGrantStatus.approved.value:
        await grant_cases.activate(grant.case_task_id)


@router.post("/", response_model=AccessGrantRead, status_code=status.HTTP_201_CREATED)
async def create_access_request(
    payload: AccessGrantCreate,
    session: SystemSessionDep,
    current_user: AccessRequestDep,
) -> AccessGrantRead:
    """Request time-bound access to a guild (requires ``access.request``;
    anything but a ``moderate`` grant also takes ``access.request_any``).

    A body may ask for content, settings, or both; each becomes its own pending
    grant so an approver decides about them separately and the log keeps them
    apart. The content one is returned, being the one a caller routes in under.

    Where the operations community takes cases a grant may serve, the request
    names the case it is for (``case_task_id``): one the requester can read,
    still open, and about this community or none yet. The case is told.
    """
    notice = await _check_case(
        current_user,
        payload.case_task_id,
        payload.community_id,
        required=True,
        notice=payload.community_notice,
    )
    asked = await service.request_grants(
        session,
        requester=current_user,
        payload=payload,
        asks=payload.wanted,
        community_notice=notice,
    )
    grant = asked[0]
    for requested in asked:
        await audit_service.record(
            session,
            event_type=AuditEventType.ACCESS_GRANT_REQUESTED,
            actor_user_id=current_user.id,
            guild_id=requested.guild_id,
            target_type="access_grant",
            target_id=requested.id,
            detail={
                "purpose": requested.purpose,
                "level": requested.access_level,
            },
        )
    read = await _one(grant, system_session=session)
    await _commit_with_case(session, payload.case_task_id, payload.community_id)
    await _tell_requested(
        session,
        asked,
        requester=current_user,
        guild_name=read.community_name,
    )
    return read


_BREAK_GLASS_PURPOSES = (challenge_service.ChallengePurpose.break_glass,)


async def _answers_with_a_passkey(
    session: AsyncSession, *, actor: User, credential: dict
) -> bool:
    """Whether the assertion in this request answers for this account.

    The challenge it is held against was issued to the account by the begin
    route below and is spent here, so what it proves belongs to this request
    rather than to the session the request was made on — the same rule the
    code follows.
    """
    presented = await passkey_service.present_against_challenge(
        session,
        user_id=actor.id,
        credential=credential,
        purposes=_BREAK_GLASS_PURPOSES,
    )
    if isinstance(presented, passkey_service.PresentationRefused):
        if not presented.keep:
            await session.rollback()
        return False
    return True


async def check_second_factor(
    session: AsyncSession, *, actor: User, answer: SecondFactorAnswer, during: str
) -> None:
    """Take the account's own factor before a grant is self-issued.

    ``during`` names the errand in the audit line a refused answer writes.

    Asked for the way turning the factor off asks: against the request rather
    than against what the session remembers, so what answers is presented at
    the moment the grant is issued. Three things answer — a code from the
    authenticator, a recovery code, or one of the account's passkeys. The
    recovery code is there because an operator whose phone is gone is exactly
    who needs to reach a community; the passkey, because a holder who signs in
    with one has no reason to keep an authenticator app as well. A code is
    taken by :func:`prove_second_factor`, as it is at a sign-in, so the
    account's lock and its count of wrong answers hold here too.
    """
    if not await service.demands_second_factor(session, actor=actor):
        return

    # Read once: a refused assertion may put the transaction back, and the row
    # this came from is not this function's to re-read afterwards.
    actor_id = actor.id

    if not (
        await totp_service.is_enrolled(session, user_id=actor_id)
        or await passkey_service.count_for_user(session, user_id=actor_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AccessGrantMessages.SECOND_FACTOR_ENROLMENT_REQUIRED,
        )

    if answer.passkey is not None:
        if not await _answers_with_a_passkey(
            session, actor=actor, credential=answer.passkey
        ):
            await audit_service.record(
                session,
                event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
                actor_user_id=actor_id,
                detail={"method": "passkey", "during": during},
            )
            await session.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AccessGrantMessages.PASSKEY_INVALID,
            )
        return
    if not (answer.code or answer.recovery_code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AccessGrantMessages.SECOND_FACTOR_REQUIRED,
        )
    await prove_second_factor(
        session,
        user_id=actor_id,
        code=answer.code,
        recovery_code=answer.recovery_code,
        during=during,
        signed_in=True,
    )


@router.get("/break-glass", response_model=BreakGlassRequirements)
async def break_glass_requirements(
    session: SystemSessionDep,
    current_user: BreakGlassDep,
) -> BreakGlassRequirements:
    """What a break-glass request will be asked for.

    The form reads this to know whether to offer a code field, whether the
    caller has a factor to answer with, and the longest window it may ask for.
    """
    required = await service.demands_second_factor(session, actor=current_user)
    return BreakGlassRequirements(
        second_factor_required=required,
        max_duration_minutes=service.break_glass_max_minutes(current_user.role),
        totp_enrolled=await totp_service.is_enrolled(session, user_id=current_user.id),
        passkey_enrolled=bool(
            await passkey_service.count_for_user(session, user_id=current_user.id)
        ),
    )


@router.post("/break-glass/passkey", response_model=PasskeyAuthenticationOptions)
async def begin_break_glass_passkey(
    session: SystemSessionDep,
    current_user: BreakGlassDep,
) -> PasskeyAuthenticationOptions:
    """Options for answering a break-glass request with one of this account's
    passkeys.

    The challenge is bound to the account and to this purpose, and the request
    that carries the assertion spends it. Presenting a key here adds nothing to
    the session it was made on: what it answers for is the grant.
    """
    credentials = await passkey_service.list_for_user(session, user_id=current_user.id)
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.PASSKEY_NOT_FOUND,
        )

    ceremony = passkey_service.begin_authentication(credentials=credentials)
    await challenge_service.create(
        session,
        user_id=current_user.id,
        purpose=challenge_service.ChallengePurpose.break_glass,
        value=bytes_to_base64url(ceremony.challenge),
    )
    await session.commit()
    return PasskeyAuthenticationOptions(options=ceremony.options)


@router.post(
    "/break-glass", response_model=AccessGrantRead, status_code=status.HTTP_201_CREATED
)
async def break_glass_access(
    payload: BreakGlassCreate,
    session: SystemSessionDep,
    current_user: BreakGlassDep,
) -> AccessGrantRead:
    """Self-issue a time-bound break-glass grant to a guild (requires
    ``data.bypass``).

    Repurposes the old standing all-guild bypass: instead of ambient god-mode,
    the holder records scoped, expiring, self-approved PAM grants in one step.
    The grants are the audit trail; the holder then routes into the guild via
    the normal PAM path until they expire.

    **Two grants, not one.** Write access to the community's content, and its
    settings at ``superadmin``. They are separate rows with separate purposes,
    so the log says which authority was exercised — and so that asking for one
    of them, rather than both, is what the ordinary request flow is for. The
    content grant is returned, being the one the caller routes in under; both
    are in the list.
    """
    await check_second_factor(
        session, actor=current_user, answer=payload, during="break_glass"
    )
    notice = await _check_case(
        current_user,
        payload.case_task_id,
        payload.community_id,
        required=False,
        notice=payload.community_notice,
    )
    replaced = await service.reconcile_break_glass_pair(
        session, actor=current_user, payload=payload
    )
    # One act: both grants carry the same moment.
    issued_at = utcnow()
    grant = await service.break_glass(
        session,
        actor=current_user,
        payload=payload,
        level=AccessLevel.read_write.value,
        community_notice=notice,
        issued_at=issued_at,
    )
    settings_grant = await service.break_glass(
        session,
        actor=current_user,
        payload=payload,
        purpose=AccessGrantPurpose.settings,
        level=SettingsLevel.superadmin.value,
        community_notice=notice,
        issued_at=issued_at,
    )
    for prior in replaced:
        await audit_service.record(
            session,
            event_type=AuditEventType.ACCESS_GRANT_DECIDED,
            actor_user_id=current_user.id,
            guild_id=prior.guild_id,
            target_type="access_grant",
            target_id=prior.id,
            detail={
                "purpose": prior.purpose,
                "level": prior.access_level,
                "decision": prior.status,
                "replacement": "break_glass",
            },
        )
    # One line per grant, each naming its purpose and its rung, so the log
    # says what was taken and not merely that glass was broken.
    for issued in (grant, settings_grant):
        await audit_service.record(
            session,
            event_type=AuditEventType.ACCESS_GRANT_SELF_ISSUED,
            actor_user_id=current_user.id,
            guild_id=issued.guild_id,
            target_type="access_grant",
            target_id=issued.id,
            detail={
                "purpose": issued.purpose,
                "level": issued.access_level,
                "self_approved": True,
            },
        )
    read = await _one(grant, system_session=session)
    if notice is CommunityNotice.when_granted:
        await grant_cases.tell_community(
            session,
            [grant, settings_grant],
            ended=False,
            guild_name=read.community_name,
        )
    await _commit_with_case(session, payload.case_task_id, payload.community_id)
    await _tell_requested(
        session,
        [grant, settings_grant],
        requester=current_user,
        guild_name=read.community_name,
    )
    await _tell_decided(
        session, grant, decided_by=current_user, guild_name=read.community_name
    )
    return read


@router.get("/", response_model=AccessGrantListResponse)
async def list_access_grants(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    grant_status: Optional[str] = Query(None, alias="status"),
    live: bool = Query(False, description="Keep only grants that haven't expired yet."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AccessGrantListResponse:
    """List your own access grants.

    Newest first, a page at a time; ``live=true`` narrows to grants that are
    still within their window. The full queue is ``GET /access-grants/queue``.
    """
    grants, total_count, actual_page = await service.list_grants(
        session,
        user_id=current_user.id,
        statuses=[grant_status] if grant_status else None,
        live_only=live,
        page=page,
        page_size=page_size,
    )
    return AccessGrantListResponse(
        **build_paginated_response(
            await service.to_read(grants), total_count, actual_page, page_size
        )
    )


@router.get("/queue", response_model=AccessGrantListResponse)
async def list_access_grant_queue(
    session: UserSessionDep,
    _approver: AccessApproveDep,
    grant_status: Optional[str] = Query(None, alias="status"),
    live: bool = Query(False, description="Keep only grants that haven't expired yet."),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> AccessGrantListResponse:
    """Every grant on the platform, for approvers (``access.approve``).

    Newest-first and paged like the caller's own list; ``live=true`` keeps only
    grants still within their window.
    """
    grants, total_count, actual_page = await service.list_grants(
        session,
        statuses=[grant_status] if grant_status else None,
        live_only=live,
        page=page,
        page_size=page_size,
    )
    return AccessGrantListResponse(
        **build_paginated_response(
            await service.to_read(grants), total_count, actual_page, page_size
        )
    )


@router.get("/limits", response_model=AccessGrantLimits)
async def read_access_grant_limits(
    current_user: AccessRequestDep,
) -> AccessGrantLimits:
    """The longest grant the caller may ask for, as this deployment sets it."""
    return AccessGrantLimits(
        max_duration_minutes=service.max_minutes_for_role(current_user.role),
    )


@router.get("/cases", response_model=GrantCaseList)
async def list_grant_cases(
    current_user: Annotated[
        User,
        Depends(require_capability(Capability.ACCESS_REQUEST, Capability.DATA_BYPASS)),
    ],
    search: Optional[str] = Query(
        default=None,
        max_length=200,
        description="A title holding this, or the case with this number.",
    ),
) -> GrantCaseList:
    """The open operations cases the reader can read that a grant may serve,
    those assigned to them first — what the request and break-glass forms
    offer. Read as the reader, so it lists only cases they can open. At most
    fifty; ``search`` finds the rest."""
    return GrantCaseList(
        items=[
            GrantCaseRead(
                task_id=case.task_id,
                title=case.title,
                stream=case.stream,
                subject_community_id=case.subject_guild_id,
                mine=case.mine,
                community_notice=grant_cases.notice_rule(case.stream),
            )
            for case in await grant_cases.readable_open_cases(
                current_user, search=search
            )
        ],
        required=await grant_cases.cases_required(),
    )


@router.post("/{grant_id}/approve", response_model=AccessGrantRead)
async def approve_access_grant(
    grant_id: int,
    payload: AccessGrantApprove,
    session: SystemSessionDep,
    current_user: AccessApproveDep,
) -> AccessGrantRead:
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    grant = await service.approve(
        session,
        grant=grant,
        approver=current_user,
        duration_minutes=payload.duration_minutes,
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.ACCESS_GRANT_DECIDED,
        actor_user_id=current_user.id,
        guild_id=grant.guild_id,
        target_type="access_grant",
        target_id=grant.id,
        detail={
            "purpose": grant.purpose,
            "level": grant.access_level,
            "decision": "approved",
        },
    )
    read = await _one(grant, system_session=session)
    if grant.community_notice == CommunityNotice.when_granted.value:
        await grant_cases.tell_community(
            session, [grant], ended=False, guild_name=read.community_name
        )
    await session.commit()
    await _tell_decided(
        session, grant, decided_by=current_user, guild_name=read.community_name
    )
    return read


@router.post("/{grant_id}/deny", response_model=AccessGrantRead)
async def deny_access_grant(
    grant_id: int,
    session: SystemSessionDep,
    current_user: AccessApproveDep,
) -> AccessGrantRead:
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    grant = await service.deny(session, grant=grant, approver=current_user)
    await audit_service.record(
        session,
        event_type=AuditEventType.ACCESS_GRANT_DECIDED,
        actor_user_id=current_user.id,
        guild_id=grant.guild_id,
        target_type="access_grant",
        target_id=grant.id,
        detail={
            "purpose": grant.purpose,
            "level": grant.access_level,
            "decision": "denied",
        },
    )
    read = await _one(grant, system_session=session)
    await session.commit()
    await _tell_decided(
        session, grant, decided_by=current_user, guild_name=read.community_name
    )
    return read


@router.post("/{grant_id}/revoke", response_model=AccessGrantRead)
async def revoke_access_grant(
    grant_id: int,
    session: SystemSessionDep,
    current_user: AccessApproveDep,
) -> AccessGrantRead:
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    grant = await service.revoke(session, grant=grant, revoker=current_user)
    await audit_service.record(
        session,
        event_type=AuditEventType.ACCESS_GRANT_DECIDED,
        actor_user_id=current_user.id,
        guild_id=grant.guild_id,
        target_type="access_grant",
        target_id=grant.id,
        detail={
            "purpose": grant.purpose,
            "level": grant.access_level,
            "decision": "revoked",
        },
    )
    read = await _one(grant, system_session=session)
    await session.commit()
    # PAM access revoked — drop the grantee's live content streams in that guild
    # immediately, don't wait for the bounded re-auth tick.
    await content_sockets.revoke_user(grant.guild_id, grant.user_id)
    await _tell_decided(
        session, grant, decided_by=current_user, guild_name=read.community_name
    )
    return read


@router.delete(
    "/{grant_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def cancel_access_request(
    grant_id: int,
    session: SystemSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> Response:
    """Withdraw your own still-pending request."""
    grant = await service.get_grant(session, grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AccessGrantMessages.NOT_FOUND
        )
    await service.cancel_own_pending(session, grant=grant, user=current_user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
