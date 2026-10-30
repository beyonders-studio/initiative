"""Verification and operations for the external billing service.

Billing's requests carry the v2 envelope (``app.services.platform.billing_envelope``),
signed with billing's Ed25519 boundary key: :func:`verify_billing_envelope`
checks it over the raw body, and :func:`burn_jti` spends its ``jti`` on the
system engine before any work. Every verb then works community by community
under the ``initiative_billing`` role, scoped to the one community it names.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from starlette.datastructures import Headers
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import billing_capabilities
from app.core.config import settings
from app.core.errors import CodedError
from app.core.identify import bearer_token
from app.core.messages import BillingMessages
from app.core.rules import SYNCED_RULES, SetBy
from app.core.security import PublicKeyBundleError, load_verification_keys
from app.models.platform.billing import (
    BILLING_SOURCE,
    BillingEventLog,
    BillingJti,
    BillingOp,
)
from app.models.platform.guild import Guild, CommunityStatus
from app.models.platform.guild_administration import GuildAdministration
from app.models.platform.rule import CommunityRule
from app.schemas.platform.billing import CommunityFields
from app.core.audit_events import AuditEventType
from app.services import audit as audit_service
from app.services.marketplace import community_hooks
from app.services.platform import billing_envelope as envelope
from app.services.platform import rules

logger = logging.getLogger(__name__)


class BillingEnvelopeError(CodedError):
    """The request failed envelope verification: 403, or 503 when billing is
    absent (the self-host default) or this deployment's key is unreadable —
    neither a caller fault, so the answer is fail-closed and retryable."""

    status_code = 403


@dataclass(frozen=True)
class BillingClaims:
    """Validated identity of a billing service call."""

    jti: str
    expires_at: datetime


def billing_inbound_enabled() -> bool:
    """True when the inbound billing endpoints are configured to run.

    The single source of truth for "billing writes can happen": billing's
    boundary key and its statement key must both be present. Unset — the
    self-host default — means the endpoints 503 and nothing ever reaches the
    ``billing_*`` tables, so the janitor can skip its sweep entirely.
    """
    return bool(
        settings.BILLING_PUBLIC_KEY_PEM and settings.BILLING_STATEMENT_PUBLIC_KEY_PEM
    )


def billing_managed() -> bool:
    """True when a community's plan is set by the billing service.

    A portal to change it in and a signed way for it to write both have to
    exist; with either missing, the operator sets caps and entitlements by
    hand. The database reads the same answer from ``public.billing_managed()``
    (``app.db.billing_managed``), which also decides whether the change log is
    written at all.
    """
    return bool(settings.BILLING_URL) and billing_inbound_enabled()


def _keys(pem: str | None) -> tuple[Any, ...]:
    if not pem:
        raise BillingEnvelopeError(BillingMessages.NOT_CONFIGURED, 503)
    try:
        keys = load_verification_keys(pem)
    except PublicKeyBundleError as exc:
        # An unreadable key is this deployment's misconfiguration, not the
        # caller's fault, so it surfaces like "not configured" rather than as
        # a rejected request.
        raise BillingEnvelopeError(BillingMessages.KEY_UNREADABLE, 503) from exc
    if not keys:
        raise BillingEnvelopeError(BillingMessages.NOT_CONFIGURED, 503)
    return keys


def statement_keys() -> tuple[Any, ...]:
    """The keys an entitlement statement must be signed by."""
    return _keys(settings.BILLING_STATEMENT_PUBLIC_KEY_PEM)


def verify_billing_envelope(
    *,
    method: str,
    path: str,
    headers: Headers,
    body: bytes,
) -> BillingClaims:
    """Verify the envelope on a billing call. Pure — no DB; the ``jti`` is
    :func:`burn_jti`'s to spend."""
    if not billing_inbound_enabled():
        raise BillingEnvelopeError(BillingMessages.NOT_CONFIGURED, 503)
    keys = _keys(settings.BILLING_PUBLIC_KEY_PEM)
    token = bearer_token(headers)
    if not token:
        raise BillingEnvelopeError(BillingMessages.MISSING_SIGNATURE)
    try:
        seen = envelope.verify(
            token,
            keys=keys,
            issuer=envelope.BILLING,
            audience=envelope.TO_INITIATIVE,
            method=method,
            path=path,
            body=body,
        )
    except envelope.EnvelopeRefused as exc:
        raise BillingEnvelopeError(f"BILLING_{exc.code}") from exc
    return BillingClaims(jti=seen.jti, expires_at=seen.expires_at)


async def burn_jti(claims: BillingClaims) -> None:
    """Spend the envelope's ``jti``, first presentation only, and commit, on
    the system engine: before any work, so a replay does nothing at all."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        session.add(
            BillingJti(
                jti=claims.jti,
                redeemed_at=datetime.now(timezone.utc),
                expires_at=claims.expires_at,
            )
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            audit_service.emit(
                event_type=AuditEventType.SECURITY_REPLAY_REJECTED,
                actor_user_id=None,
                detail={"channel": "billing"},
            )
            raise CodedError(BillingMessages.REPLAYED_TOKEN, 403) from exc


# The plan label and billing's bookkeeping live on ``guild_administration``;
# the lifecycle status stays on ``guilds`` (every request reads it); what the
# plan gives is the community's paid rules. Billing sees exactly these columns
# of the first two — nothing else on either table.
_GUILD_TIER_COLUMNS = (
    Guild.id,
    GuildAdministration.tier_name,
    GuildAdministration.billing_version,
    Guild.status,
)


#: A guild in one of these takes no status write from billing at all.
_BILLING_UNTOUCHABLE_STATUS_VALUES: frozenset[str] = frozenset(
    {CommunityStatus.suspended.value, CommunityStatus.deleted.value}
)


async def _select_tier_row(session: AsyncSession, guild_id: int, *, lock: bool = False):
    """Read the billing-visible slice of one guild. Explicit columns only —
    the role's grants are column-scoped, so an ORM ``SELECT *`` would fail.
    ``lock`` holds its administration row to the end of the transaction."""
    query = (
        select(*_GUILD_TIER_COLUMNS)
        .join(GuildAdministration, GuildAdministration.guild_id == Guild.id)
        .where(Guild.id == guild_id)
    )
    if lock:
        query = query.with_for_update(of=GuildAdministration)
    return (await session.exec(query)).one_or_none()


async def _claim_event(
    session: AsyncSession,
    *,
    event_id: str,
    guild_id: int,
    op: BillingOp,
) -> bool:
    """Claim one event id in ``billing_event_log``; False if already claimed.

    Plain INSERT in a savepoint rather than ON CONFLICT DO NOTHING: the
    billing role holds no SELECT on this table (append-only), and under RLS
    an ON CONFLICT insert would demand one. The unique-violation IS the
    replay signal; the savepoint confines the abort so the transaction
    survives.
    """
    claim = insert(BillingEventLog.__table__).values(
        event_id=event_id,
        guild_id=guild_id,
        op=op.value,
        source=BILLING_SOURCE,
        actor=None,
        applied_at=datetime.now(timezone.utc),
    )
    try:
        async with session.begin_nested():
            await session.exec(claim)
    except IntegrityError:
        return False
    return True


async def event_claimed(session: AsyncSession, event_id: str) -> bool:
    """Whether ``event_id`` is already in ``billing_event_log``.

    On the system engine: the billing role writes the log and may not read it,
    so the community notice asks here before it writes anything down.
    """
    return (
        await session.exec(
            select(BillingEventLog.event_id).where(BillingEventLog.event_id == event_id)
        )
    ).first() is not None


async def claim_community_notice(
    session: AsyncSession, key: str, *, guild_id: int
) -> bool:
    """Record one community notice in the event log; False if a concurrent
    delivery recorded it first.

    Claimed after the notice is written down, not before (see
    ``api.v1.platform_endpoints.billing.notices``): the billing role writes
    the log row and nothing else, and the notice is the system engine's.
    """
    return await _claim_event(
        session, event_id=key, guild_id=guild_id, op=BillingOp.community_notice
    )


@dataclass(frozen=True)
class Synced:
    """What a community holds after a sync item: the version, and whether
    this item put it on hold."""

    version: int
    went_on_hold: bool = False


async def apply_community_sync(
    session: AsyncSession,
    system: AsyncSession,
    *,
    guild_id: int,
    version: int,
    fields: CommunityFields,
) -> Synced:
    """Bring one community to billing's state at ``version``, if that's newer
    than the one it holds; answer with the version held either way.

    Billing sends its whole desired state every time, so every field is
    written: a capability that drops off a plan is withdrawn by the same
    write that renames the tier. A status write never moves a community out
    of ``suspended`` or ``deleted``; it's recorded, and a suspension that
    lifts returns the community to it. A rule the deployment does not offer
    the means to meet refuses the item; ``system`` reads what it offers.
    """
    # Locked, so two syncs for one community take turns: each reads the
    # version the other wrote, and an older one never lands after a newer.
    row = await _select_tier_row(session, guild_id, lock=True)
    if row is None:
        raise CodedError(BillingMessages.COMMUNITY_NOT_FOUND, 404)
    if version <= row.billing_version:
        return Synced(version=row.billing_version)

    synced = {rule.key: rule.value for rule in fields.rules if rule.key in SYNCED_RULES}
    await _refuse_what_is_not_offered(system, guild_id, synced)

    now = datetime.now(timezone.utc)
    administration_values: dict[str, Any] = {
        "tier_name": fields.tier_name,
        "billing_status": fields.status.value,
        "billing_version": version,
    }
    paid: dict[str, Any] = {
        "max_storage_bytes": fields.max_storage_bytes,
        "max_users": fields.max_users,
        "max_guests": fields.max_guests,
        **billing_capabilities.capability_values(fields.feature_keys),
    }
    guild_values: dict[str, Any] = {"updated_at": now}
    went_on_hold = False
    if fields.status.value != row.status:
        if row.status in _BILLING_UNTOUCHABLE_STATUS_VALUES:
            # The operator's time out and deletion own those. The caps still
            # land, and the status is recorded above.
            logger.info(
                "billing: guild %s status write %s -> %s held (version %s)",
                guild_id,
                row.status,
                fields.status.value,
                version,
            )
        else:
            guild_values["status"] = fields.status.value
            guild_values["status_changed_at"] = now
            went_on_hold = fields.status is CommunityStatus.on_hold
            community_hooks.status_changed(session, guild_id)
            logger.info(
                "billing: guild %s status %s -> %s (version %s)",
                guild_id,
                row.status,
                fields.status.value,
                version,
            )
    await session.exec(
        update(GuildAdministration)
        .where(GuildAdministration.guild_id == guild_id)
        .values(**administration_values)
    )
    for key, value in paid.items():
        await rules.put(session, key, value, guild_id=guild_id, set_by=SetBy.deployment)
    # The rest of the deployment's rules, whole: a rule it no longer sends
    # falls back to the community's own.
    await session.exec(
        delete(CommunityRule).where(
            CommunityRule.guild_id == guild_id,
            CommunityRule.set_by == SetBy.deployment.value,
            CommunityRule.user_id.is_(None),  # type: ignore[union-attr]
            CommunityRule.key.not_in(synced),  # type: ignore[attr-defined]
            CommunityRule.key.in_(SYNCED_RULES),  # type: ignore[attr-defined]
        )
    )
    for key, value in synced.items():
        await rules.put(session, key, value, guild_id=guild_id, set_by=SetBy.deployment)
    # Stamp the guild whichever row moved: "when did this guild last change"
    # stays a fact about the guild.
    await session.exec(update(Guild).where(Guild.id == guild_id).values(**guild_values))
    return Synced(version=version, went_on_hold=went_on_hold)


async def _refuse_what_is_not_offered(
    system: AsyncSession, guild_id: int, synced: dict[str, Any]
) -> None:
    """Refuse a rule the community's own settings would refuse for want of
    what the deployment offers: asking for a second factor where no kind is
    permitted."""
    # Here rather than at the top: the rules' write path reads the settings
    # module, which reaches billing.
    from app.services.platform import auth_posture

    ctx = auth_posture.RuleContext.community(system, system, None, guild_id)
    for key, value in synced.items():
        rule = auth_posture.COMMUNITY_RULES.get(key)
        if rule is None or not rule.tightens(rule.loose, value):
            continue
        try:
            await rule.offered(ctx, value)
        except HTTPException as exc:
            raise CodedError(BillingMessages.RULE_NOT_OFFERED, 409) from exc


@dataclass(frozen=True)
class GuildBillingRead:
    """What billing reads back about one community, beside its usage."""

    status: str
    name: str
    billing_version: int


async def guild_billing_read(
    session: AsyncSession, guild_id: int
) -> GuildBillingRead | None:
    """One community's status, name and the version of billing's state it
    holds, or None once it's purged. On the billing session, routed to the
    community: the role is granted exactly these columns."""
    row = (
        await session.exec(
            select(Guild.status, Guild.name, GuildAdministration.billing_version)
            .join(GuildAdministration, GuildAdministration.guild_id == Guild.id)
            .where(Guild.id == guild_id)
        )
    ).one_or_none()
    if row is None:
        return None
    return GuildBillingRead(status=row[0], name=row[1], billing_version=int(row[2]))


@dataclass(frozen=True)
class GuildUsage:
    """What one guild is using, for the signed usage read.

    ``usage_bytes`` is the figure ``enforce_storage_quota`` enforces against;
    ``member_count`` and ``guest_count`` are the ones ``ensure_membership``
    compares with ``max_users`` and ``max_guests``. Billing reads them so a
    plan is never cut below the people already in the community.
    """

    usage_bytes: int
    member_count: int
    guest_count: int


async def guild_usage(guild_id: int) -> GuildUsage:
    """Current stored bytes, member count and guest count for one guild, for the signed
    usage read.

    Neither is visible to the column-scoped ``initiative_billing`` role:
    ``uploads`` lives in the per-guild ``guild_<id>`` schema, and
    ``guild_memberships`` is outside its grants. So the guild is looked up — and
    its members counted — on a **system session from the guild's cohort**, not
    the billing-context session; that session bypasses RLS, which is what
    ``count_members`` asks of its caller. The sum is
    ``get_guild_storage_usage``'s. The billing session still owns envelope
    verification + the jti burn in the endpoint; this only reads the figures
    the app itself enforces against. Read-only — the app never pushes usage
    anywhere.
    """
    from app.db import cohorts
    from app.services.platform.guilds import count_guests, count_members
    from app.services.tenant.attachments import get_guild_storage_usage

    async with cohorts.system_session(guild_id) as session:
        # Existence check at the public baseline.
        exists = (
            await session.exec(select(Guild.id).where(Guild.id == guild_id))
        ).one_or_none()
        if exists is None:
            raise CodedError(BillingMessages.COMMUNITY_NOT_FOUND, 404)
        member_count = await count_members(session, guild_id=guild_id)
        guest_count = await count_guests(session, guild_id=guild_id)

    return GuildUsage(
        usage_bytes=await get_guild_storage_usage(guild_id),
        member_count=member_count,
        guest_count=guest_count,
    )
