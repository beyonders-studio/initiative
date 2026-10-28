"""Privileged Access Management (PAM) service.

Time-bound, per-guild access grants: a lower-privilege platform user requests
temporary access to one guild, an approver (``access.approve`` holder) grants
it, and it auto-expires. See ``app.models.access_grant``.

Grants are written on the system engine alone. They are read on the caller's
platform tier: a grantee's own rows (``access_grants_self``) and, for
``access.approve`` holders, the whole queue (``access_grants_admin``).
Capability and ownership checks happen at the endpoint as well.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional, Sequence, cast

from fastapi import status
from sqlalchemy import or_, update as sa_update
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import AccessGrantMessages
from app.core.capabilities import (
    ROLE_MAX_GRANT_MINUTES,
    Capability,
    capabilities_for,
    may_hold_grant,
    roles_with_capability,
)
from app.core.login_methods import LoginMethod
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.query import paginated_query
from app.core.email_i18n import translate
from app.models.platform.access_grant import (
    LEVEL_LABEL_KEYS,
    AccessGrant,
    AccessGrantPurpose,
    AccessGrantStatus,
    AccessLevel,
    CommunityNotice,
)
from app.models.platform.guild import Guild, CommunityStatus
from app.models.platform.notification import NotificationType
from app.models.platform.user import User, UserRole, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.models.platform.user_totp import UserTotp
from app.schemas.platform.user import UserIdentity
from app.schemas.platform.access_grant import (
    AccessGrantCreate,
    AccessGrantRead,
    BreakGlassCreate,
)
from app.services import email as email_service
from app.services.platform import auth_posture
from app.services.platform import guilds as guilds_service
from app.services.platform import notice_outbox
from app.core.user_display import handle_of
from app.core.clock import utcnow

logger = logging.getLogger(__name__)


class AccessGrantError(CodedError):
    """Raised for PAM rule violations, with an ``AccessGrantMessages`` code."""


async def _lock_user_guild_grants(
    session: AsyncSession, *, user_id: int, guild_id: int
) -> None:
    """Serialize grant changes for one user and guild until transaction end."""
    await advisory_lock(session, LockNamespace.ACCESS_GRANT, f"{user_id}:{guild_id}")


#: The window a grant gets when the request names none.
DEFAULT_DURATION_MINUTES = 240  # 4 hours
#: The absolute ceiling on any grant.
MAX_DURATION_MINUTES = 1440  # 24 hours

# Break-glass is self-approved, so its window is short and re-issued to
# extend. Capped below the role maxima.
BREAK_GLASS_DEFAULT_MINUTES = 60  # 1 hour
BREAK_GLASS_MAX_MINUTES = 240  # 4 hours


def max_minutes_for_role(role: UserRole) -> int:
    """The longest grant the given role may hold (clamped to the ceiling)."""
    role_cap = ROLE_MAX_GRANT_MINUTES.get(role, DEFAULT_DURATION_MINUTES)
    return min(role_cap, MAX_DURATION_MINUTES)


def _capped_duration(requested: Optional[int], role: UserRole) -> int:
    """Resolve a requested duration for a grantee of ``role`` to the effective
    one, or raise if it exceeds that role's maximum."""
    cap = max_minutes_for_role(role)
    minutes = requested if requested is not None else min(DEFAULT_DURATION_MINUTES, cap)
    if minutes > cap:
        raise AccessGrantError(AccessGrantMessages.DURATION_TOO_LONG)
    return minutes


def break_glass_max_minutes(role: UserRole) -> int:
    """The longest break-glass window the given role may issue itself: the role
    cap, further clamped to the (shorter) break-glass ceiling because a
    self-approved grant has no second-person check."""
    return min(max_minutes_for_role(role), BREAK_GLASS_MAX_MINUTES)


def _break_glass_duration(requested: Optional[int], role: UserRole) -> int:
    """Resolve a break-glass window against ``break_glass_max_minutes``.
    Defaults to ``BREAK_GLASS_DEFAULT_MINUTES``."""
    cap = break_glass_max_minutes(role)
    minutes = (
        requested if requested is not None else min(BREAK_GLASS_DEFAULT_MINUTES, cap)
    )
    if minutes > cap:
        raise AccessGrantError(AccessGrantMessages.DURATION_TOO_LONG)
    return minutes


async def _event_notification_data(session: AsyncSession, grant: AccessGrant) -> dict:
    """Common notification payload for grant lifecycle events — enough for the
    frontend to render an informative message and link to the Access page."""
    guild = await guilds_service.get_guild(session, guild_id=grant.guild_id)
    return {
        "grant_id": str(grant.id),
        "community_id": str(grant.guild_id),
        "community_name": guild.name if guild else None,
        "access_level": grant.access_level,
    }


async def _approvers(session: AsyncSession) -> list[User]:
    """Active users who can approve access requests (for notification fan-out)."""
    roles = list(roles_with_capability(Capability.ACCESS_APPROVE))
    if not roles:
        return []
    result = await session.exec(
        select(User).where(User.role.in_(roles), User.status == UserStatus.active)
    )
    return list(result.all())


async def _tell(
    session: AsyncSession,
    *,
    recipient: User,
    notification_type: NotificationType,
    lines: Sequence[dict],
    push_key: str,
    email_event: str,
    guild_name: Optional[str],
    levels: Optional[Sequence[str]] = None,
    requester: Optional[str] = None,
) -> None:
    """Write down a PAM event for ``recipient``: a bell line for each of
    ``lines``, with one push and one email riding the first.

    Delivered by the notice worker under the account's own settings, as any
    other notice is. The email stands whether or not the line has been read:
    it is a record of somebody acting on the account's access. ``push_key``
    selects the ``accessGrant.<key>`` entry in the ``notifications`` namespace,
    localized to the recipient.

    ``levels`` and ``requester`` populate the ``{{level}}`` / ``{{requester}}``
    placeholders that only some body templates contain — ``requester`` is used by
    the ``requested`` event only and is intentionally ``None`` for approve/deny/
    revoke. Each is passed to the interpolator only when present, so it maps to
    exactly the placeholders its template declares.

    ``levels`` is a sequence because one ask can be for two things at once. It
    is what the recipient is being asked to decide about, so every one of them
    is named: a message that described only the first would be asking for a
    decision about something it had not mentioned.
    """
    locale = getattr(recipient, "locale", None) or "en"
    body_vars: dict[str, str] = {"guild": guild_name or "a guild"}
    if levels:
        body_vars["level"] = ", ".join(
            translate(LEVEL_LABEL_KEYS[level], locale, namespace="notifications")
            for level in levels
            if level in LEVEL_LABEL_KEYS
        )
    if requester is not None:
        body_vars["requester"] = requester
    first, *rest = lines
    # The community it is about, so a person who has muted that community
    # hears about it the way they asked to.
    guild_id = int(first["community_id"]) if first.get("community_id") else None
    rows = [
        await notice_outbox.notice(
            session,
            recipient,
            notification_type,
            first,
            guild_id=guild_id,
            push=(
                translate(
                    f"accessGrant.{push_key}.title", locale, namespace="notifications"
                ),
                translate(
                    f"accessGrant.{push_key}.body",
                    locale,
                    namespace="notifications",
                    **body_vars,
                ),
            ),
            push_data={
                "type": notification_type.value,
                "target_path": "/settings/operator/access",
            },
            email=email_service.access_grant_pieces(
                recipient,
                event=email_event,
                guild_name=guild_name or "a guild",
                levels=levels,
                requester=requester,
            ),
            email_names_line=False,
        )
    ]
    rows += [
        notice_outbox.row(cast(int, recipient.id), guild_id, notification_type, line)
        for line in rest
    ]
    await notice_outbox.enqueue(session, rows)


async def request_grants(
    session: AsyncSession,
    *,
    requester: User,
    payload: AccessGrantCreate,
    asks: list[tuple[str, str]],
    community_notice: CommunityNotice = CommunityNotice.none,
) -> list[AccessGrant]:
    """Create the pending grants ``payload`` asks for, as one act.

    Validate every purpose first, create one row per purpose, and notify each
    approver once after the complete request is established.
    ``community_notice`` is the notice the case it names settled on.
    """
    await _lock_user_guild_grants(
        session, user_id=requester.id, guild_id=payload.community_id
    )
    try:
        guild = await guilds_service.get_guild(session, guild_id=payload.community_id)
    except ValueError:
        raise AccessGrantError(
            AccessGrantMessages.COMMUNITY_NOT_FOUND, status.HTTP_404_NOT_FOUND
        ) from None

    # Members don't need a grant — they already have standing access.
    membership = await guilds_service.get_membership(
        session, guild_id=payload.community_id, user_id=requester.id
    )
    if membership is not None:
        raise AccessGrantError(AccessGrantMessages.ALREADY_MEMBER)

    duration = _capped_duration(payload.requested_duration_minutes, requester.role)

    # Validate the complete request before creating any row.
    for purpose, level in asks:
        if not may_hold_grant(requester.role, purpose, level):
            raise AccessGrantError(
                AccessGrantMessages.MODERATE_NOT_HELD
                if level == AccessLevel.moderate.value
                else AccessGrantMessages.ONLY_MODERATE,
                status.HTTP_403_FORBIDDEN,
            )
        existing = await session.exec(
            select(AccessGrant).where(
                AccessGrant.user_id == requester.id,
                AccessGrant.guild_id == payload.community_id,
                AccessGrant.purpose == purpose,
                AccessGrant.status.in_(
                    [AccessGrantStatus.pending.value, AccessGrantStatus.approved.value]
                ),
            )
        )
        for grant in existing.all():
            if grant.status == AccessGrantStatus.pending.value or grant.is_live(
                now=utcnow()
            ):
                raise AccessGrantError(
                    AccessGrantMessages.OVERLAPPING_GRANT, status.HTTP_409_CONFLICT
                )

    created: list[AccessGrant] = []
    for purpose, level in asks:
        grant = AccessGrant(
            user_id=requester.id,
            guild_id=payload.community_id,
            access_level=level,
            purpose=purpose,
            status=AccessGrantStatus.pending.value,
            reason=payload.reason,
            requested_duration_minutes=duration,
            requested_by_id=requester.id,
            case_task_id=payload.case_task_id,
            community_notice=community_notice.value,
        )
        session.add(grant)
        created.append(grant)
    await session.flush()

    requester_name = handle_of(requester)
    for approver in await _approvers(session):
        await _tell(
            session,
            recipient=approver,
            notification_type=NotificationType.access_grant_requested,
            lines=[
                {
                    "grant_id": str(grant.id),
                    "community_id": str(grant.guild_id),
                    "community_name": guild.name,
                    "requester_id": str(requester.id),
                    "requester_name": requester_name,
                    "access_level": grant.access_level,
                }
                for grant in created
            ],
            push_key="requested",
            email_event="requested",
            guild_name=guild.name,
            levels=[grant.access_level for grant in created],
            requester=requester_name,
        )
    return created


async def demands_second_factor(session: AsyncSession, *, actor: User) -> bool:
    """Whether breaking glass has to carry this account's own second factor.

    Asked of this account alone, and for one of two reasons: it holds a factor
    of its own, or the deployment's second-factor requirement covers its rung.
    An account with neither breaks glass on its reason alone. One the
    requirement covers that holds nothing is answered by its identity
    provider's factor, when the sign-in carried one, and is otherwise sent to
    its Security page first.

    Only a method the deployment still offers counts. One it has withdrawn
    refuses new enrolments, so asking for it would ask for something the
    Security page cannot give.
    """
    offered = [
        method
        for method in (LoginMethod.totp, LoginMethod.passkey)
        if await auth_posture.login_method_allowed(session, method)
    ]
    if not offered:
        return False

    held = []
    if LoginMethod.totp in offered:
        held.append(
            select(UserTotp.user_id)
            .where(UserTotp.user_id == actor.id, UserTotp.confirmed_at.is_not(None))
            .exists()
        )
    if LoginMethod.passkey in offered:
        held.append(
            select(UserPasskey.user_id).where(UserPasskey.user_id == actor.id).exists()
        )
    if await session.scalar(select(or_(*held))):
        return True

    from app.core import auth_context
    from app.services.auth.assurance import SECOND_FACTOR_AMR

    return (
        auth_posture.rule_covers(
            await auth_posture.second_factor_requirement(session), actor.role
        )
        and SECOND_FACTOR_AMR not in auth_context.current().session_amr
    )


async def break_glass(
    session: AsyncSession,
    *,
    actor: User,
    payload: BreakGlassCreate,
    allow_member: bool = False,
    purpose: AccessGrantPurpose = AccessGrantPurpose.content,
    level: str,
    community_notice: CommunityNotice = CommunityNotice.none,
) -> AccessGrant:
    """Self-issue a time-bound break-glass grant for ``actor`` to one guild.

    The capability-gated endpoint lets an operator self-approve a scoped,
    expiring PAM grant in one step. The result is an ``access_grants`` row with
    requester and approver both set to ``actor`` and the supplied reason kept
    for the audit trail. The window is capped server-side.

    ``purpose`` scopes what the grant authorises and ``level`` says how far it
    reaches within that purpose — the two vocabularies are different, which is
    why the caller states the level rather than a request body carrying one.
    ``allow_member`` goes with a non-content purpose, which membership does not
    already confer.

    A ``moderate`` grant is never self-issued: someone else approves it.
    """
    if level == AccessLevel.moderate.value:
        raise AccessGrantError(
            AccessGrantMessages.MODERATE_NOT_HELD, status.HTTP_403_FORBIDDEN
        )
    try:
        await guilds_service.get_guild(session, guild_id=payload.community_id)
    except ValueError:
        raise AccessGrantError(
            AccessGrantMessages.COMMUNITY_NOT_FOUND, status.HTTP_404_NOT_FOUND
        ) from None

    # A member already has standing access — nothing to break glass for.
    membership = await guilds_service.get_membership(
        session, guild_id=payload.community_id, user_id=actor.id
    )
    if membership is not None and not allow_member:
        raise AccessGrantError(AccessGrantMessages.ALREADY_MEMBER)

    # Serialize concurrent self-issues for this (actor, guild) so the
    # read-then-insert anti-stacking check below can't be raced into two live
    # grants. A transaction-scoped advisory lock on the (user_id, guild_id) pair
    # makes a second concurrent request wait, then see the first's grant and hit
    # ALREADY_LIVE; the lock auto-releases on commit/rollback.
    await _lock_user_guild_grants(
        session, user_id=actor.id, guild_id=payload.community_id
    )

    # Don't stack grants: a still-live grant already confers the access, and a
    # pending request would conflict. Re-trigger only after the current one ends.
    existing = await session.exec(
        select(AccessGrant).where(
            AccessGrant.user_id == actor.id,
            AccessGrant.guild_id == payload.community_id,
            AccessGrant.purpose == purpose.value,
            AccessGrant.status.in_(
                [AccessGrantStatus.pending.value, AccessGrantStatus.approved.value]
            ),
        )
    )
    now = utcnow()
    for grant in existing.all():
        if grant.status == AccessGrantStatus.pending.value:
            raise AccessGrantError(
                AccessGrantMessages.OVERLAPPING_GRANT, status.HTTP_409_CONFLICT
            )
        if grant.is_live(now=now):
            raise AccessGrantError(
                AccessGrantMessages.ALREADY_LIVE, status.HTTP_409_CONFLICT
            )

    duration = _break_glass_duration(payload.requested_duration_minutes, actor.role)
    grant = AccessGrant(
        user_id=actor.id,
        guild_id=payload.community_id,
        access_level=level,
        purpose=purpose.value,
        # Created AND approved in one step — self-approved, so there's no wait.
        status=AccessGrantStatus.approved.value,
        reason=payload.reason,
        requested_duration_minutes=duration,
        requested_by_id=actor.id,
        approved_by_id=actor.id,
        decided_at=now,
        expires_at=now + timedelta(minutes=duration),
        case_task_id=getattr(payload, "case_task_id", None),
        community_notice=community_notice.value,
    )
    session.add(grant)
    await session.flush()

    # Record the event for the actor (audit/visibility); the row itself is the
    # authoritative audit trail.
    data = await _event_notification_data(session, grant)
    await _tell(
        session,
        recipient=actor,
        notification_type=NotificationType.access_grant_approved,
        lines=[data],
        push_key="approved",
        email_event="approved",
        guild_name=data["community_name"],
        levels=[grant.access_level],
    )
    return grant


async def reconcile_break_glass_pair(
    session: AsyncSession,
    *,
    actor: User,
    payload: BreakGlassCreate,
) -> list[AccessGrant]:
    """Close open grants replaced by the fixed break-glass pair."""
    await _lock_user_guild_grants(
        session, user_id=actor.id, guild_id=payload.community_id
    )
    result = await session.exec(
        select(AccessGrant).where(
            AccessGrant.user_id == actor.id,
            AccessGrant.guild_id == payload.community_id,
            AccessGrant.purpose.in_(
                [AccessGrantPurpose.content.value, AccessGrantPurpose.settings.value]
            ),
            AccessGrant.status.in_(
                [AccessGrantStatus.pending.value, AccessGrantStatus.approved.value]
            ),
        )
    )
    now = utcnow()
    replaced: list[AccessGrant] = []
    for grant in result.all():
        if grant.status == AccessGrantStatus.pending.value:
            grant.status = AccessGrantStatus.denied.value
            grant.approved_by_id = actor.id
            grant.decided_at = now
            grant.updated_at = now
            session.add(grant)
            replaced.append(grant)
            continue
        if not grant.is_live(now=now):
            continue
        grant.status = AccessGrantStatus.revoked.value
        grant.revoked_by_id = actor.id
        grant.revoked_at = now
        grant.updated_at = now
        session.add(grant)
        replaced.append(grant)
    await session.flush()
    return replaced


async def get_grant(session: AsyncSession, grant_id: int) -> Optional[AccessGrant]:
    return await session.get(AccessGrant, grant_id)


async def approve(
    session: AsyncSession,
    *,
    grant: AccessGrant,
    approver: User,
    duration_minutes: Optional[int] = None,
) -> AccessGrant:
    if grant.status != AccessGrantStatus.pending.value:
        raise AccessGrantError(AccessGrantMessages.NOT_PENDING)
    if approver.id == grant.requested_by_id or approver.id == grant.user_id:
        raise AccessGrantError(AccessGrantMessages.CANNOT_APPROVE_OWN)

    # Cap by the GRANTEE's role (an approver shortening/extending can't exceed
    # the recipient's tier).
    # The grantee is asked about as they stand now, not as they stood when the
    # request was made.
    grantee = await session.get(User, grant.user_id)
    if (
        grantee is None
        or grantee.status != UserStatus.active
        or Capability.ACCESS_REQUEST not in capabilities_for(grantee.role)
        or not may_hold_grant(grantee.role, grant.purpose, grant.access_level)
    ):
        raise AccessGrantError(
            AccessGrantMessages.GRANTEE_INELIGIBLE, status.HTTP_409_CONFLICT
        )
    grantee_role = grantee.role
    duration = _capped_duration(
        duration_minutes or grant.requested_duration_minutes, grantee_role
    )
    now = utcnow()
    grant.status = AccessGrantStatus.approved.value
    grant.approved_by_id = approver.id
    grant.decided_at = now
    grant.expires_at = now + timedelta(minutes=duration)
    grant.updated_at = now
    session.add(grant)
    await session.flush()

    data = await _event_notification_data(session, grant)
    if grantee is not None:
        await _tell(
            session,
            recipient=grantee,
            notification_type=NotificationType.access_grant_approved,
            lines=[data],
            push_key="approved",
            email_event="approved",
            guild_name=data["community_name"],
            levels=[grant.access_level],
        )
    return grant


async def deny(
    session: AsyncSession, *, grant: AccessGrant, approver: User
) -> AccessGrant:
    if grant.status != AccessGrantStatus.pending.value:
        raise AccessGrantError(AccessGrantMessages.NOT_PENDING)
    now = utcnow()
    grant.status = AccessGrantStatus.denied.value
    grant.approved_by_id = approver.id
    grant.decided_at = now
    grant.updated_at = now
    session.add(grant)
    await session.flush()

    grantee = await session.get(User, grant.user_id)
    data = await _event_notification_data(session, grant)
    if grantee is not None:
        await _tell(
            session,
            recipient=grantee,
            notification_type=NotificationType.access_grant_denied,
            lines=[data],
            push_key="denied",
            email_event="denied",
            guild_name=data["community_name"],
        )
    return grant


async def revoke(
    session: AsyncSession, *, grant: AccessGrant, revoker: User
) -> AccessGrant:
    # Revoke is only meaningful for an approved grant (live or not-yet-expired);
    # a pending one should be denied, a terminal one is already over.
    if grant.status != AccessGrantStatus.approved.value:
        raise AccessGrantError(AccessGrantMessages.NOT_ACTIVE)
    now = utcnow()
    grant.status = AccessGrantStatus.revoked.value
    grant.revoked_by_id = revoker.id
    grant.revoked_at = now
    grant.updated_at = now
    session.add(grant)
    await session.flush()

    grantee = await session.get(User, grant.user_id)
    data = await _event_notification_data(session, grant)
    if grantee is not None:
        await _tell(
            session,
            recipient=grantee,
            notification_type=NotificationType.access_grant_revoked,
            lines=[data],
            push_key="revoked",
            email_event="revoked",
            guild_name=data["community_name"],
        )
    return grant


async def cancel_own_pending(
    session: AsyncSession, *, grant: AccessGrant, user: User
) -> None:
    """A requester withdraws their own still-pending request."""
    if grant.requested_by_id != user.id:
        raise AccessGrantError(
            AccessGrantMessages.CANNOT_CANCEL_OTHERS, status.HTTP_403_FORBIDDEN
        )
    if grant.status != AccessGrantStatus.pending.value:
        raise AccessGrantError(AccessGrantMessages.NOT_PENDING)
    await session.delete(grant)
    await session.flush()


async def get_live_grants(
    session: AsyncSession, *, user_id: int, guild_id: int
) -> dict[AccessGrantPurpose, AccessGrant]:
    """Return the user's currently-live grants for ``guild_id``, one per purpose.

    Used when resolving guild session context so a grantee can act in a guild
    they aren't a member of, for the grant's window only. Keyed by purpose so a
    grant issued for one authority is never spent as another. A grant counts
    only while its holder's rung may still hold it, as the standing statement
    reads it.
    """
    result = await session.exec(
        select(AccessGrant, User.role)
        .join(User, User.id == AccessGrant.user_id)
        .where(
            AccessGrant.user_id == user_id,
            AccessGrant.guild_id == guild_id,
            AccessGrant.live(utcnow()),
        )
        # At most one open grant per (user, guild, purpose) is allowed at
        # request time; the latest-expiring wins just in case.
        .order_by(AccessGrant.expires_at)
    )
    return {
        AccessGrantPurpose(grant.purpose): grant
        for grant, role in result.all()
        if may_hold_grant(role, grant.purpose, grant.access_level)
    }


async def get_live_grant(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
    purpose: AccessGrantPurpose = AccessGrantPurpose.content,
) -> Optional[AccessGrant]:
    """Return the user's currently-live grant of ``purpose`` for ``guild_id``,
    if any — content unless another is named."""
    grants = await get_live_grants(session, user_id=user_id, guild_id=guild_id)
    return grants.get(purpose)


async def list_grants(
    session: AsyncSession,
    *,
    user_id: Optional[int] = None,
    statuses: Optional[list[str]] = None,
    live_only: bool = False,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AccessGrant], int, int]:
    """One page of grants, newest first, optionally filtered to one grantee
    and/or a set of statuses.

    Approvers pass ``user_id=None`` for the full queue; requesters pass their
    own id for "my requests". ``live_only`` keeps only grants that are live:
    approved and unexpired. Returns ``(grants, total_count, page)``.
    """
    stmt = select(AccessGrant)
    if user_id is not None:
        stmt = stmt.where(AccessGrant.user_id == user_id)
    if statuses:
        stmt = stmt.where(AccessGrant.status.in_(statuses))
    if live_only:
        stmt = stmt.where(AccessGrant.live(utcnow()))
    return await paginated_query(
        session,
        stmt.order_by(AccessGrant.requested_at.desc(), AccessGrant.id.desc()),
        select(func.count()).select_from(stmt.subquery()),
        page,
        page_size,
    )


#: How often grants past their window are marked expired.
GRANT_EXPIRY_POLL_SECONDS = 300


async def expire_due(session: AsyncSession) -> int:
    """Flip approved-but-past-expiry grants to ``expired`` for clean audit/UX.

    Liveness is computed independently, so this is housekeeping, not a
    correctness requirement: it is what records that a grant *ended*, which
    nothing else observes. Each one is recorded as decided by nobody.
    Returns the number of rows updated.
    """
    from app.core.audit_events import AuditEventType
    from app.services import audit as audit_service

    now = utcnow()
    # One statement claims the rows it changes: a second sweep running at the
    # same moment, or a revocation landing first, finds the row no longer
    # approved and leaves it alone, so each ending is recorded exactly once.
    claimed = (
        await session.exec(
            sa_update(AccessGrant)
            .where(
                AccessGrant.status == AccessGrantStatus.approved.value,
                AccessGrant.expires_at <= now,
            )
            .values(status=AccessGrantStatus.expired.value, updated_at=now)
            .returning(
                AccessGrant.id,
                AccessGrant.guild_id,
                AccessGrant.purpose,
                AccessGrant.access_level,
            )
            .execution_options(synchronize_session=False)
        )
    ).all()
    for grant_id, guild_id, purpose, level in claimed:
        await audit_service.record(
            session,
            event_type=AuditEventType.ACCESS_GRANT_DECIDED,
            actor_user_id=None,
            guild_id=guild_id,
            target_type="access_grant",
            target_id=grant_id,
            detail={
                "purpose": purpose,
                "level": level,
                "decision": AccessGrantStatus.expired.value,
            },
        )
    return len(claimed)


async def process_grant_expiry() -> None:
    """Background sweep: mark the grants whose window has closed."""
    from app.db.session import SystemSessionLocal

    from app.services.platform import grant_cases

    async with SystemSessionLocal() as session:
        expired = await expire_due(session)
        await session.commit()
    if expired:
        logger.info("access grants: marked %s expired", expired)
    # Then each case hears what the grants serving it did.
    async with SystemSessionLocal() as session:
        told = await grant_cases.report_activity(session)
    if told:
        logger.info("access grants: told %s cases what their grants did", told)


async def _enrichment(
    session: AsyncSession, *, user_ids: set[int], guild_ids: set[int]
) -> tuple[dict[int | None, User], dict[int | None, Guild]]:
    """The people and communities a page of grants names, for display."""
    users_result = await session.exec(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u for u in users_result.all()}
    # A community the lookup does not find leaves its rows unnamed rather
    # than failing the page.
    guilds_result = await session.exec(select(Guild).where(Guild.id.in_(guild_ids)))
    guilds = {g.id: g for g in guilds_result.all()}
    return users, guilds


async def to_read(
    grants: list[AccessGrant], *, system_session: Optional[AsyncSession] = None
) -> list[AccessGrantRead]:
    """Serialize grants, batch-loading display enrichment (user/guild names).

    The enrichment is read on the system engine: the people a grant names are
    named by handle whoever reads it, and the community it names is one its
    holder is not a member of. A route already on the system engine passes its session;
    a route on the caller's platform tier passes none and a short system
    session is opened for the lookup.
    """
    if not grants:
        return []

    user_ids: set[int] = set()
    guild_ids: set[int] = set()
    for g in grants:
        user_ids.add(g.user_id)
        guild_ids.add(g.guild_id)
        if g.approved_by_id is not None:
            user_ids.add(g.approved_by_id)

    if system_session is not None:
        users, guilds = await _enrichment(
            system_session, user_ids=user_ids, guild_ids=guild_ids
        )
    else:
        from app.db.session import SystemSessionLocal

        async with SystemSessionLocal() as own_session:
            users, guilds = await _enrichment(
                own_session, user_ids=user_ids, guild_ids=guild_ids
            )

    out: list[AccessGrantRead] = []
    for g in grants:
        read = AccessGrantRead.model_validate(g)
        grantee = users.get(g.user_id)
        if grantee is not None:
            read.user = UserIdentity.model_validate(grantee)
        guild = guilds.get(g.guild_id)
        if guild is not None:
            read.community_name = guild.name
            read.community_status = CommunityStatus(guild.status)
        if g.approved_by_id is not None:
            approver = users.get(g.approved_by_id)
            if approver is not None:
                read.approved_by = UserIdentity.model_validate(approver)
        out.append(read)
    return out


__all__ = [
    "AccessGrantError",
    "request_grants",
    "break_glass",
    "get_grant",
    "approve",
    "deny",
    "revoke",
    "cancel_own_pending",
    "get_live_grant",
    "get_live_grants",
    "list_grants",
    "expire_due",
    "process_grant_expiry",
    "to_read",
    "max_minutes_for_role",
    "break_glass_max_minutes",
    "AccessLevel",
]
