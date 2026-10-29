from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import logging
import secrets
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import ColumnElement, case, exists, func, or_, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import aliased
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.guild_auth_options import CommunityAuthOption
from app.core.intake import IntakeStream
from app.core.tools import Tool
from app.core.encryption import encrypt_field, normalize_email, SALT_EMAIL
from app.core.errors import CodedError
from app.core.messages import GuildMessages
from app.db import cohorts, post_commit
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.guild_migrations import GUILD_SCHEMA_REGEX
from app.db.query import apply_pagination, ids_in
from app.models.platform.guild import (
    BANNER_TEXT_COLORS,
    GUILD_ADMIN_ROLES,
    LIVE_STATUS_VALUES,
    UNLISTED_STATUSES,
    DEFAULT_BANNER,
    DEFAULT_BANNER_TEXT_COLOR,
    Guild,
    CommunityCategory,
    GuildInvite,
    GuildMembership,
    CommunityRole,
    CommunityStatus,
    restore_status_choices,
)
from app.models.platform.access_grant import AccessGrant, AccessGrantPurpose
from app.models.platform.guild_administration import GuildAdministration
from app.models.platform.notification import NotificationType
from app.models.tenant.guest_invite_grant import GuestInviteGrant
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.schemas.platform.guild import CommunityInviteGrant
from app.models.tenant.guild_setting import GuildSetting
from app.models.platform.user import User, UserStatus
from app.services import audit as audit_service
from app.services.marketplace import community_hooks
from app.services.auth import addresses
from app.services.platform import billing as billing_service

from app.services.platform import account_stream, user_stream
from app.services.platform import api_keys as api_keys_service
from app.services.platform import rules
from app.services.platform import contact_grants as contact_grants_service
from app.services.platform.retention import COMMUNITY_DELETION, COMMUNITY_HOLD
from app.db.request_context import Platform, SystemGuild, Unattributed

if TYPE_CHECKING:
    from app.services.email import EmailPieces

logger = logging.getLogger(__name__)

DEFAULT_INVITE_EXPIRATION_DAYS = 7
#: The rungs above ``guest`` a guest may hold on the demo deployment.
DEMO_GUEST_ROLES = (CommunityRole.member, CommunityRole.admin, CommunityRole.superadmin)
INVITE_CODE_BYTES = 16


class GuildInviteError(CodedError):
    """Raised when an invite cannot be redeemed."""


class GuildCapacityError(CodedError):
    """Raised when adding a member would exceed the guild's ``max_users`` cap,
    or a guest its ``max_guests``."""

    status_code = 403


class GuestsDisabledError(CodedError):
    """Raised when a guest would be made while the deployment allows none."""

    status_code = 403


class NotAGuestError(CodedError):
    """Raised when a guest's terms are changed for somebody who is not one."""

    status_code = 404


class GuestGrantError(CodedError):
    """Raised when a guest invite names an initiative or item the community
    does not hold."""

    status_code = 404


class GuestTimeEndedError(CodedError):
    """Raised when somebody whose time as a guest has just ended joins again
    before the sweep has removed their old membership."""

    status_code = 409


class CommunityJoinError(CodedError):
    """Raised when a guild cannot be joined from the community directory."""

    status_code = 404


class CommunityListingError(CodedError):
    """Raised when a guild does not qualify to be listed in the directory."""


class CommunityDirectoryDisabledError(CodedError):
    """Raised when the deployment runs no community directory at all."""

    status_code = 403


class AgeConfirmationRequiredError(CodedError):
    """The caller has not confirmed their age and asked to join a listed guild."""

    status_code = 403


class BannerColorError(CodedError):
    """Raised when a banner colour is not a ``#rrggbb`` value."""


class SupportIntakeMissingError(CodedError):
    """Raised when help requests are switched on with nowhere to send them."""


# A guild whose seat cap is one can never admit a joiner, so listing it would
# publish a card whose only button is guaranteed to fail. Unlike a guild that is
# merely full today, this one can never have room, which is why it is refused
# outright rather than left to the capacity check at join time.
MIN_COMMUNITY_SEATS = 2


@dataclass(frozen=True)
class NearPlace:
    """Where a reader of the directory is: a country, and optionally a point."""

    country: str
    latitude: float | None = None
    longitude: float | None = None


#: How far away a community still counts as nearby, whichever side of a border
#: it is on: about an hour's drive.
NEARBY_KM = 100

_EARTH_RADIUS_KM = 6371.0


def _distance_km(
    latitude: ColumnElement[float],
    longitude: ColumnElement[float],
    from_latitude: float,
    from_longitude: float,
) -> ColumnElement[float]:
    """The great-circle distance from a point (haversine), in kilometres."""
    d_lat = func.radians(latitude - from_latitude) / 2
    d_lon = func.radians(longitude - from_longitude) / 2
    a = func.power(func.sin(d_lat), 2) + func.cos(
        func.radians(from_latitude)
    ) * func.cos(func.radians(latitude)) * func.power(func.sin(d_lon), 2)
    # Rounding can carry ``a`` a hair past 1 for antipodal points.
    return 2 * _EARTH_RADIUS_KM * func.asin(func.sqrt(func.least(a, 1.0)))


def proximity_order(near: NearPlace) -> list[ColumnElement[Any]]:
    """The directory's order nearest ``near`` first, as ORDER BY terms.

    Nearby communities first (within ``NEARBY_KM``, across a border too), then
    the rest of the reader's country, then the communities whose country nobody
    knows, then everywhere else; within each, the closest first, and those
    with no point after those with one. A reader who gave only a country is
    ordered by the country alone.
    """
    location = Guild.__table__.c.location
    country = location["country"].astext
    same_country = country == near.country
    if near.latitude is None or near.longitude is None:
        return [
            case(
                (same_country, 0),
                # No location, or one nobody pinned: either kind of null — SQL
                # or JSON — has no country.
                (country.is_(None), 1),
                else_=2,
            )
        ]
    distance = _distance_km(
        location["latitude"].as_float(),
        location["longitude"].as_float(),
        near.latitude,
        near.longitude,
    )
    tier = case(
        (distance <= NEARBY_KM, 0),
        (same_country, 1),
        (country.is_(None), 2),
        else_=3,
    )
    return [tier, distance.asc().nulls_last()]


# Canonical order for a guild's categories: the order they are declared in
# ``CommunityCategory``. Storing them sorted means every card, filter chip, and
# assertion sees the same sequence regardless of the order they were checked.
_CATEGORY_ORDER = {
    category.value: index for index, category in enumerate(CommunityCategory)
}


def normalize_categories(categories: Sequence[str] | None) -> list[str]:
    """De-duplicate a category selection and put it in canonical order.

    Unknown values are dropped rather than rejected: the schema layer has
    already validated the request against ``CommunityCategory``, and the database
    CHECK is the backstop, so anything else reaching here is a value this build
    no longer recognizes and simply has no shelf to sit on.
    """
    if not categories:
        return []
    unique = {value for value in categories if value in _CATEGORY_ORDER}
    return sorted(unique, key=lambda value: _CATEGORY_ORDER[value])


async def _persist_new_guild(session: AsyncSession, guild: Guild) -> Guild:
    """Add a new guild row together with the administration row it must have.

    Every guild has exactly one ``guild_administration`` companion, carrying the
    defaults (no caps, no plan, guild sign-in off). Writing the pair here rather
    than at each creation site is what lets every reader assume the row exists —
    ``get_administration`` raises without it, and the operator dashboard joins
    against it. The caller commits.
    """
    session.add(guild)
    await session.flush()
    session.add(GuildAdministration(guild_id=guild.id))
    await session.flush()
    return guild


async def get_primary_guild(session: AsyncSession) -> Guild:
    result = await session.exec(select(Guild).order_by(Guild.id.asc()))
    guild = result.first()
    if guild:
        return guild
    # Zero VISIBLE guilds is either a genuinely fresh database (the designed
    # quiet path: the first boot seeds the primary guild before the first
    # registration, and every registration creates or joins a guild) or a
    # session that cannot see the real rows (wrong DATABASE_URL* target, a
    # blinded system engine). A blinded session reads zero rows in users too,
    # so row counts alone can't tell the two apart — but guild_<id> schemas
    # live in the catalog, which row-level security never filters, and
    # deprovisioning drops a deleted guild's schema. Either signal means this
    # database is NOT fresh: say so before seeding a default guild into what
    # may be a live install.
    user_count = (await session.exec(select(func.count()).select_from(User))).one()
    schema_count = (
        await session.exec(
            text("SELECT count(*) FROM pg_namespace WHERE nspname ~ :pat"),
            params={"pat": GUILD_SCHEMA_REGEX},
        )
    ).one()[0]
    if user_count or schema_count:
        logger.warning(
            "no guilds visible, but the database is not fresh (%d visible "
            "user(s), %d guild schema(s)) — creating a default primary guild. "
            "If this instance previously had guilds, verify the DATABASE_URL* "
            "variables point at the intended database and that the system "
            "engine can read public.guilds",
            user_count,
            schema_count,
        )
    now = datetime.now(timezone.utc)
    guild = await _persist_new_guild(
        session,
        Guild(
            name="Primary Community",
            description="Default community",
            created_at=now,
            updated_at=now,
        ),
    )
    # Commit the new guild row, then provision its schema — a brand-new primary
    # guild is schema-native from birth. (Only the first time the primary guild is
    # created, i.e. fresh-DB seeding.)
    await session.commit()
    from app.db.schema_provisioning import provision_guild

    await provision_guild(guild.id)
    return guild


async def get_primary_guild_id(session: AsyncSession) -> int:
    guild = await get_primary_guild(session)
    return guild.id  # ty: ignore[invalid-return-type]


async def get_guild(session: AsyncSession, guild_id: int) -> Guild:
    stmt = select(Guild).where(Guild.id == guild_id)
    result = await session.exec(stmt)
    guild = result.one_or_none()
    if not guild:
        raise ValueError(GuildMessages.COMMUNITY_NOT_FOUND)
    return guild


async def get_administration(
    session: AsyncSession, guild_id: int
) -> GuildAdministration:
    """The guild's operator-set row (caps / plan label / sign-in entitlement).

    Created with the guild, so a missing row means the guild is missing too —
    or that the caller's session cannot see it. The row is readable by the
    guild's own members (RLS scopes it to their guilds) but writable by no
    request-path role; write it on the system engine.
    """
    result = await session.exec(
        select(GuildAdministration).where(GuildAdministration.guild_id == guild_id)
    )
    administration = result.one_or_none()
    if not administration:
        raise ValueError(GuildMessages.COMMUNITY_NOT_FOUND)
    return administration


async def ensure_membership(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    role: CommunityRole = CommunityRole.member,
    force_role: bool = False,
    oidc_provider_id: int | None = None,
    actor_user_id: int | None = None,
    via: str = "direct",
    invite_id: int | None = None,
    guest_until: datetime | None = None,
) -> GuildMembership:
    """Put ``user_id`` in ``guild_id``, or return the membership they hold.

    ``actor_user_id`` is who brought them in; it defaults to the person joining,
    which is what every self-service path is. ``via`` names the way in — the
    value rides the record — and ``invite_id`` says which standing offer was
    redeemed, where one was. ``guest_until`` makes the new membership a
    guest's, until then: it takes no seat, so the guest cap applies instead of
    the member cap, and it joins no initiative on its own.
    """
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership:
        updated = False
        if force_role and membership.role != role:
            membership.role = role
            updated = True
        if oidc_provider_id is not None and membership.oidc_provider_id is None:
            membership.oidc_provider_id = oidc_provider_id
            updated = True
        if updated:
            session.add(membership)
            await session.flush()
        return membership
    # New member: enforce the per-guild cap. Only reached on a genuine insert
    # (re-joins / role updates return above), so an existing member is never
    # blocked. SSO/OIDC provisioning uses a separate insert path
    # (oidc_sync._create_guild_membership) and is intentionally exempt.
    if guest_until is None:
        await _assert_member_capacity(session, guild_id=guild_id)
    else:
        await _assert_guest_capacity(session, guild_id=guild_id)
    # A listed community never gains somebody who has answered the age question
    # as under the minimum, by any route. The paths with a person at the
    # keyboard ask the question first (``assert_age_confirmed``); this is the
    # floor under the ones without — a group sync, an admin adding somebody —
    # where refusing an unanswered account would refuse nearly everybody, but
    # an answered one is a fact already on the record.
    # The guild is asked first and the account only if the answer is yes: a
    # private guild is every guild on most deployments, and the rule does not
    # apply to one, so it should not cost a lookup. ``is_listed_in_directory``
    # itself stops at the deployment switch, so a deployment with no directory
    # pays a settings read and nothing else.
    if await is_listed_in_directory(
        session, guild_id=guild_id
    ) and await is_known_under_age(session, user_id=user_id):
        raise AgeConfirmationRequiredError(GuildMessages.AGE_BELOW_MINIMUM)
    next_position = await _next_membership_position(session, user_id=user_id)
    membership = GuildMembership(
        guild_id=guild_id,
        user_id=user_id,
        role=role,
        position=next_position,
        oidc_provider_id=oidc_provider_id,
        guest_until=guest_until,
    )
    session.add(membership)
    await session.flush()
    detail: dict[str, object] = {"role": role.value, "via": via}
    if guest_until is not None:
        detail["guest_until"] = guest_until.isoformat()
    if invite_id is not None:
        detail["invite_id"] = invite_id
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_MEMBER_ADDED,
        actor_user_id=actor_user_id if actor_user_id is not None else user_id,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail=detail,
    )
    # Belonging somewhere new can change what this account is asked for — a
    # listed community asks its members their age — and the person may have
    # had nothing to do with arriving here. Their open tabs re-read the
    # account once this commits.
    account_stream.queue_account_signal(session, user_id, "membership")
    # Nudge billing that this guild's membership changed. No-op unless a
    # hosted deployment configured the outbound billing settings.
    if guest_until is None:
        enroll_new_member_in_auto_join_initiatives(
            session, guild_id=guild_id, user_id=user_id, role=role
        )
    return membership


def enroll_new_member_in_auto_join_initiatives(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    role: CommunityRole,
) -> None:
    """Put a brand-new guild member into the guild's auto-join initiatives once
    ``session`` commits.

    Called on a genuine membership insert only, which is what makes this the
    onboarding hook rather than a sweep: someone who was already in the guild
    is returned earlier and is never re-enrolled.

    A guild admin is skipped. Their standing already reaches every initiative,
    so nothing here is theirs to be handed. They pick which initiatives they
    navigate by joining them.

    The enrolment runs on a system session from the guild's cohort, after the
    membership commits. Landing somewhere useful is a convenience, and it is
    never the reason someone's guild join fails.
    """
    if role in GUILD_ADMIN_ROLES:
        return
    from app.db.session import set_rls_context
    from app.services.tenant import initiatives as initiatives_service

    async def enroll_in_auto_join_initiatives() -> None:
        async with cohorts.system_session(guild_id) as guild_session:
            await set_rls_context(guild_session, SystemGuild(guild_id))
            await initiatives_service.enroll_in_auto_join_initiatives(
                guild_session, guild_id=guild_id, user_id=user_id
            )
            await guild_session.commit()

    post_commit.after_commit(session, enroll_in_auto_join_initiatives)


def align_admin_initiative_roles(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    role: CommunityRole,
) -> None:
    """Bring a freshly promoted guild admin's initiative rows up to their
    standing once ``session`` commits.

    A guild admin's membership row carries a manager role, which every write
    path settles for itself. A promotion changes the guild role and nothing
    else, so the rows the person already held are reconciled here — the one
    moment their standing changes underneath rows that already exist.

    Only a promotion to admin does anything; a demotion leaves the manager role
    in place, which is an ordinary initiative role for an ordinary member to
    hold, and taking it away would be a second decision nobody asked for.

    The reconciliation runs on a system session from the guild's cohort, after
    the role change commits, so it is never what makes the role change fail.
    """
    if role not in GUILD_ADMIN_ROLES:
        return
    from app.db.session import set_rls_context
    from app.services.tenant import initiatives as initiatives_service

    async def align_guild_admin_membership_roles() -> None:
        async with cohorts.system_session(guild_id) as guild_session:
            await set_rls_context(guild_session, SystemGuild(guild_id))
            await initiatives_service.align_guild_admin_membership_roles(
                guild_session, guild_id=guild_id, user_id=user_id
            )
            await guild_session.commit()

    post_commit.after_commit(session, align_guild_admin_membership_roles)


async def _assert_member_capacity(
    session: AsyncSession, *, guild_id: int, claiming_seat: bool = True
) -> None:
    """Raise ``GuildCapacityError`` if the guild is at its ``max_users`` cap.

    A ``NULL`` cap means unlimited and short-circuits before any lock or count.
    The caller's session must be able to see the guild's ``guild_memberships``
    rows (system engine, or an RLS context routed to this guild) — the same
    precondition ``count_members`` documents.

    ``claiming_seat`` (the default) is the join path: the call must run in the
    SAME transaction that then inserts the membership and commits, and when a
    cap is set it takes a transaction-scoped advisory lock keyed on the guild
    before counting, so the count check and the insert that follows cannot
    interleave with a concurrent join and collectively exceed the cap. The lock
    releases on commit/rollback and only serializes joins to the SAME guild
    (mirrors ``enforce_storage_quota``).

    Pass ``claiming_seat=False`` when the caller only reads the cap and takes no
    seat in the same transaction (minting an invite): the answer is a
    point-in-time reading either way, so serializing joins against it would buy
    nothing. The join path stays the authoritative gate.
    """
    administration = await get_administration(session, guild_id=guild_id)
    if administration.max_users is None:
        return
    if claiming_seat:
        await advisory_lock(session, LockNamespace.MEMBER_CAP, guild_id)
    if await count_members(session, guild_id=guild_id) >= administration.max_users:
        raise GuildCapacityError(GuildMessages.COMMUNITY_USER_LIMIT_REACHED)


async def _assert_guest_capacity(
    session: AsyncSession, *, guild_id: int, claiming_seat: bool = True
) -> None:
    """Raise ``GuildCapacityError`` if the guild is at its ``max_guests`` cap.

    The guest half of :func:`_assert_member_capacity`: the same session
    requirement and the same ``claiming_seat``, with the lock under its own
    namespace so guests and members do not queue behind each other. A cap of 0
    takes no new guests.
    """
    administration = await get_administration(session, guild_id=guild_id)
    if administration.max_guests is None:
        return
    if claiming_seat:
        await advisory_lock(session, LockNamespace.GUEST_CAP, guild_id)
    if await count_guests(session, guild_id=guild_id) >= administration.max_guests:
        raise GuildCapacityError(GuildMessages.COMMUNITY_GUEST_LIMIT_REACHED)


async def _guest_days(session: AsyncSession, *, guild_id: int, days: int) -> int:
    """``days`` held to the community's longest guest stay and the
    deployment's. Raises ``GuestsDisabledError`` while the deployment allows no
    guests."""
    platform = await rules.platform_values(session)
    if not platform["guests_enabled"]:
        raise GuestsDisabledError(GuildMessages.COMMUNITY_GUESTS_DISABLED)
    guild_limit = await rules.community_value(session, guild_id, "guest_max_days")
    limits = (days, platform["max_guest_days"], guild_limit)
    return min(limit for limit in limits if limit is not None)


async def _refuse_ended_guest(
    session: AsyncSession, *, guild_id: int, user_id: int
) -> None:
    """Refuse a join by somebody whose guest membership has ended and not yet
    been removed. Joining would return that membership unchanged; the sweep
    removes it, and what it carried, within minutes."""
    membership = await get_membership(session, guild_id=guild_id, user_id=user_id)
    if (
        membership is not None
        and membership.guest_until is not None
        and membership.guest_until <= datetime.now(timezone.utc)
    ):
        raise GuestTimeEndedError(GuildMessages.GUEST_TIME_ENDED)


async def extend_guest(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    days: int,
    actor_user_id: int,
) -> GuildMembership:
    """End ``user_id``'s time as a guest ``days`` from now, held to the same
    limits as a new guest's. Raises ``NotAGuestError`` unless they are one.
    Nobody sets their own end."""
    if actor_user_id == user_id:
        raise CodedError(GuildMessages.CANNOT_CHANGE_OWN_ROLE)
    membership = await get_membership(
        session, guild_id=guild_id, user_id=user_id, for_update=True
    )
    if membership is None or membership.guest_until is None:
        raise NotAGuestError(GuildMessages.NOT_A_GUEST)
    before = membership.guest_until
    days = await _guest_days(session, guild_id=guild_id, days=days)
    if before <= datetime.now(timezone.utc):
        # An ended guest no longer counts against the cap, so bringing one back
        # takes a place as a new guest does.
        await _assert_guest_capacity(session, guild_id=guild_id)
    membership.guest_until = datetime.now(timezone.utc) + timedelta(days=days)
    session.add(membership)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_GUEST_EXTENDED,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={
            "from": before.isoformat(),
            "to": membership.guest_until.isoformat(),
        },
    )
    return membership


async def make_guest_a_member(
    session: AsyncSession, *, guild_id: int, user_id: int, actor_user_id: int
) -> GuildMembership:
    """Make a guest a member: their time no longer ends and they take a seat,
    so the member cap applies. Raises ``NotAGuestError`` unless they are a
    guest. Nobody makes themselves a member."""
    if actor_user_id == user_id:
        raise CodedError(GuildMessages.CANNOT_CHANGE_OWN_ROLE)
    membership = await get_membership(
        session, guild_id=guild_id, user_id=user_id, for_update=True
    )
    if membership is None or membership.guest_until is None:
        raise NotAGuestError(GuildMessages.NOT_A_GUEST)
    await _assert_member_capacity(session, guild_id=guild_id)
    membership.guest_until = None
    if membership.role == CommunityRole.guest:
        membership.role = CommunityRole.member
    session.add(membership)
    await session.flush()
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_GUEST_MADE_MEMBER,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"role": membership.role.value},
    )
    account_stream.queue_account_signal(session, user_id, "membership")
    enroll_new_member_in_auto_join_initiatives(
        session, guild_id=guild_id, user_id=user_id, role=membership.role
    )
    return membership


async def _next_membership_position(session: AsyncSession, *, user_id: int) -> int:
    result = await session.exec(
        select(func.max(GuildMembership.position)).where(
            GuildMembership.user_id == user_id
        )
    )
    max_value = result.one_or_none()
    highest = max_value if max_value is not None else -1
    return highest + 1


async def reorder_memberships(
    session: AsyncSession,
    *,
    user_id: int,
    ordered_guild_ids: list[int],
) -> None:
    if not ordered_guild_ids:
        return

    stmt = select(GuildMembership).where(GuildMembership.user_id == user_id)
    result = await session.exec(stmt)
    memberships = result.all()
    if not memberships:
        return

    membership_by_guild = {
        membership.guild_id: membership for membership in memberships
    }
    seen: set[int] = set()
    final_order: list[int] = []

    # Explicitly named guilds first, in the requested order — deduped, and only
    # ones the user actually belongs to.
    for guild_id in ordered_guild_ids:
        if guild_id in seen or guild_id not in membership_by_guild:
            continue
        final_order.append(guild_id)
        seen.add(guild_id)

    # Memberships the client didn't mention keep their relative order, appended
    # after — stable on current position, then join time.
    remaining = sorted(
        (m for m in memberships if m.guild_id not in seen),
        key=lambda m: (m.position if m.position is not None else 0, m.joined_at),
    )
    final_order.extend(m.guild_id for m in remaining)

    # ``position`` is the whole write, on rows the caller already holds, so the
    # unit of work is left to issue it. Its row count is checked per row, which
    # is what turns a write that lands nowhere into an error rather than a
    # reorder that quietly reverts on the next read.
    for index, guild_id in enumerate(final_order):
        membership_by_guild[guild_id].position = index
    session.add_all(memberships)
    await session.flush()


async def get_membership(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    for_update: bool = False,
) -> GuildMembership | None:
    stmt = select(GuildMembership).where(
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    if for_update:
        # ``populate_existing`` so the lock returns what the row holds *now*:
        # an instance already in the identity map would otherwise come back as
        # it was first read, which is the state the lock was taken to leave
        # behind.
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()


async def set_member_display_name(
    session: AsyncSession, *, guild_id: int, user_id: int, display_name: str | None
) -> bool:
    """Set what ``user_id`` is called in ``guild_id``, or clear it with
    ``None``. ``False`` when they are not a member.

    The session decides who may: a member's routed session writes only its own
    row, and the system engine writes any, behind the admin guard."""
    membership = await get_membership(session, guild_id=guild_id, user_id=user_id)
    if membership is None:
        return False
    membership.display_name = display_name
    session.add(membership)
    return True


async def list_memberships(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[
    tuple[Guild, GuildMembership, int | None, int, GuildAdministration | None, bool]
]:
    """Return (guild, membership, retention_days, member_count, administration,
    accepts_api_keys) for each guild the user belongs to.

    One bounded pass, whatever the number of guilds:

    * The guild and membership rows, and ``administration`` (caps, plan label
      and sign-in entitlement), are shared tables the caller reads on their own
      platform tier: ``guild_administration`` admits a member's own guilds.
      ``administration`` is read only for the guilds the caller administers,
      since ``CommunityRead`` serves those fields to guild admins alone.
    * ``member_count`` is every guild's total, counted in one grouped query on
      the system engine over the guild ids the caller's own read returned. The
      caller's tier reads only its own membership rows, so a count there would
      see one member per guild.
    * ``retention_days`` lives in each guild's own schema (``guild_settings``)
      and is one of the administration fields, so it is read only where the
      caller is that guild's admin, each guild entered through the seam on its
      settings surface (:func:`gather_across_guilds`). A guild the seam does not
      admit the caller to right now reports ``None``; a member's entry is
      ``None`` and costs no query.
    * ``accepts_api_keys`` is the member's ``api_keys`` rule, selected beside
      the membership row.
    """
    # lazy: avoids a circular import
    from app.db.session import SystemSessionLocal, set_rls_context
    from app.services.cross_guild import gather_across_guilds

    await set_rls_context(session, Platform(user_id=user_id))
    rows = (
        await session.exec(
            select(
                Guild,
                GuildMembership,
                rules.community_rule_sql(
                    Guild.id, "api_keys", user_id=GuildMembership.user_id
                ),
            )
            .join(GuildMembership, GuildMembership.guild_id == Guild.id)
            .where(GuildMembership.user_id == user_id)
            .order_by(
                GuildMembership.position.asc(),
                GuildMembership.joined_at.asc(),
                Guild.id.asc(),
            )
        )
    ).all()

    # A suspended guild disappears from its members' guild list. Guild ADMINS
    # keep the entry, carrying its status, so the app can show them a closed
    # community rather than a missing one — they reach nothing inside it until
    # the platform lifts the suspension. The row is simply absent for members.
    #
    # A guild ON HOLD or DELETED disappears for everyone, admins included. Only
    # a platform operator sees it.
    listed = [
        (guild, membership, accepts)
        for guild, membership, accepts in rows
        if CommunityStatus(guild.status) not in UNLISTED_STATUSES
        and (guild.status in LIVE_STATUS_VALUES or membership.role in GUILD_ADMIN_ROLES)
    ]
    if not listed:
        return []

    administered = [
        guild for guild, membership, _ in listed if membership.role in GUILD_ADMIN_ROLES
    ]
    administrations: dict[int, GuildAdministration] = {}
    if administered:
        administrations = {
            row.guild_id: row
            for row in (
                await session.exec(
                    select(GuildAdministration).where(
                        GuildAdministration.guild_id.in_(
                            [guild.id for guild in administered]
                        )
                    )
                )
            ).all()
        }

    async with SystemSessionLocal() as system_session:
        counts = await count_members_by_guild(
            system_session, guild_ids=[guild.id for guild, *_ in listed]
        )

    retention: dict[int, int | None] = {}
    live_administered = [
        guild.id for guild in administered if guild.status in LIVE_STATUS_VALUES
    ]
    if live_administered:

        async def _retention(
            routed: AsyncSession, guild_id: int
        ) -> list[tuple[int, int | None]]:
            return [(guild_id, await get_guild_retention_days(routed))]

        retention = dict(
            await gather_across_guilds(
                session,
                {user_id: live_administered},
                _retention,
                for_settings=True,
            )
        )

    return [
        (
            guild,
            membership,
            retention.get(guild.id) if membership.role in GUILD_ADMIN_ROLES else None,
            counts.get(guild.id, 0),
            administrations.get(guild.id)
            if membership.role in GUILD_ADMIN_ROLES
            else None,
            bool(accepts),
        )
        for guild, membership, accepts in listed
    ]


async def count_members_by_guild(
    session: AsyncSession, *, guild_ids: Sequence[int]
) -> dict[int, int]:
    """How many members each of these guilds has, in one query.

    The bulk form of :func:`count_members`, for a surface drawing several
    cards at once. Same session requirement, and a guild with no row in the
    answer simply has nobody in it.
    """
    if not guild_ids:
        return {}
    rows = (
        await session.exec(
            select(GuildMembership.guild_id, func.count())
            .where(
                GuildMembership.guild_id.in_(list(guild_ids)),
                GuildMembership.guest_until.is_(None),
            )
            .group_by(GuildMembership.guild_id)
        )
    ).all()
    return {guild_id: total for guild_id, total in rows}


async def guest_ends(
    session: AsyncSession, *, guild_id: int, user_ids: Sequence[int]
) -> dict[int, datetime]:
    """When each of these people's time in the guild ends, for those who are
    its guests. Read under the caller's session: a guest reads their own row
    alone, so to them nobody else is marked."""
    if not user_ids:
        return {}
    rows = (
        await session.exec(
            select(GuildMembership.user_id, GuildMembership.guest_until).where(
                GuildMembership.guild_id == guild_id,
                ids_in(GuildMembership.user_id, user_ids),
                GuildMembership.guest_until.is_not(None),
            )
        )
    ).all()
    return {user_id: until for user_id, until in rows}


async def count_members(session: AsyncSession, *, guild_id: int) -> int:
    """Total number of members in a guild. A guest takes no seat, so guests
    are not counted.

    The caller must already hold a session that can see the guild's
    ``guild_memberships`` rows — a system-engine session, or one whose RLS
    context is set to this guild (``guild_id = current_guild_id``). Under a
    user-only context the ``guild_memberships_select`` policy would expose only
    the caller's own row."""
    return (
        await session.exec(
            select(func.count())
            .select_from(GuildMembership)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.guest_until.is_(None),
            )
        )
    ).one()


async def count_guests(session: AsyncSession, *, guild_id: int) -> int:
    """How many guests a guild has now: those whose time has not ended. A
    guest whose time ran out leaves room at once, before the sweep removes
    the row. Same session requirement as :func:`count_members`."""
    return (
        await session.exec(
            select(func.count())
            .select_from(GuildMembership)
            .where(
                GuildMembership.guild_id == guild_id,
                col(GuildMembership.guest_until) > func.now(),
            )
        )
    ).one()


async def create_guild_settings(session: AsyncSession, guild_id: int) -> GuildSetting:
    """Seed a guild_settings row. guild_settings is guild-scoped (it holds
    private config like API keys), so under schema-per-guild this must run with
    the session already routed to the guild's schema."""
    settings_row = GuildSetting(retention_days=90)
    session.add(settings_row)
    await session.flush()
    return settings_row


async def may_create_another_guild(session: AsyncSession, *, user_id: int) -> bool:
    """Has this account created fewer than ``GUILD_CREATION_DAILY_LIMIT``
    communities in the last day?

    Takes a per-account lock held until the transaction ends, so the guild the
    caller then inserts is committed before the next creation for this account
    counts. A deleted community still counts: its row stays for at least
    ``MIN_GUILD_RETENTION_DAYS`` after deletion, which is at least this window.
    """
    limit = settings.GUILD_CREATION_DAILY_LIMIT
    if not limit:
        return True
    await advisory_lock(session, LockNamespace.GUILD_CREATION, user_id)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    created = await session.scalar(
        select(func.count())
        .select_from(Guild)
        .where(Guild.created_by == user_id, Guild.created_at > since)
    )
    return (created or 0) < limit


async def create_guild(
    session: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    creator: User | None = None,
    owner: User | None = None,
    actor_user_id: int | None = None,
) -> Guild:
    """Create a guild's *shared* rows only — the guild row (public) and its
    admin membership (public). The guild-scoped seed rows live in the guild's
    schema, which doesn't exist yet; :func:`provision_new_guild` commits this
    and then calls :func:`seed_guild_content`.

    ``creator`` is who performed the creation and is recorded as such;
    ``owner`` is who gets the membership, defaulting to the creator. The row
    therefore says both who made the guild and who it is for. ``actor_user_id``
    is who the record names as having done it, defaulting to whoever the guild
    is for.

    That membership is ``superadmin``, the top of the guild ladder: whoever
    starts a community holds all of it, sign-in and billing included, and has
    somebody to pass the seat to only because they hold it first. Every guild
    keeps at least one from here on (:func:`must_keep_superadmin`).
    """
    now = datetime.now(timezone.utc)
    guild = Guild(
        name=name.strip(),
        description=description.strip()
        if description and description.strip()
        else None,
        created_by=creator.id if creator else None,
        created_at=now,
        updated_at=now,
    )
    await _persist_new_guild(session, guild)
    first = owner or creator
    owner_id = first.id if first else None
    actor = actor_user_id if actor_user_id is not None else owner_id
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_CREATED,
        actor_user_id=actor,
        target_user_id=owner_id,
        guild_id=guild.id,
        target_type="guild",
        target_id=guild.id,
        detail={"owner_is_actor": actor == owner_id},
    )
    if first:
        await ensure_membership(
            session,
            guild_id=guild.id,
            user_id=first.id,
            role=CommunityRole.superadmin,
            actor_user_id=actor,
            via="created",
        )
    return guild


async def seed_guild_content(
    session: AsyncSession,
    *,
    guild_id: int,
    owner: User,
) -> None:
    """Provision a new guild's schema and create its guild-scoped seed rows
    (settings + the plug-ins this deployment provides) *inside* it.

    ``owner`` is the user the guild is **for** — its admin. When someone creates
    a guild for another account, that account is the owner and the creator is
    left holding nothing in it.

    A new guild gets **no initiative**. An initiative names a body of work, and
    the seeded one only ever named the fact that nobody had made one yet: it
    arrived called "Default Initiative", was renamed or abandoned, and either way
    the owner had to decide what their community was for before the structure
    meant anything. Landing on the empty state — which offers "create the first
    one" to exactly the admin who may — asks that question once, instead of
    answering it wrongly and making them undo it.

    The shared guild row must already exist, committed; this provisions the
    schema + role and seeds into it on a system session from the guild's cohort,
    which it commits. ``session`` is the caller's, and is left as it was.
    Called from :func:`provision_new_guild`, which undoes the guild if this
    fails.

    Mandatory plug-ins (§7.7) land here because that is what "every guild has it"
    means. They are also the one part allowed to fail quietly: the install is a
    local row, and a plug-in service whose listing has not arrived yet is no reason
    a guild cannot be created — the boot sweep installs what is missing.
    """
    from app.db.schema_provisioning import provision_guild
    from app.db.session import set_rls_context
    from app.services.tenant import mandatory_plugins as mandatory_plugins_service

    await provision_guild(guild_id)
    # Seeding is the system engine's, routed into the new schema: the guild
    # has no members yet and nobody is asking for anything.
    async with cohorts.system_session(guild_id) as guild_session:
        await set_rls_context(guild_session, SystemGuild(guild_id))
        await create_guild_settings(guild_session, guild_id)
        installed: list[str] = []
        try:
            # Inside a savepoint, so a failure here rolls back the plug-in install
            # and nothing else: the guild being created must survive whatever
            # a plug-in's listing or registration is doing.
            async with guild_session.begin_nested():
                installed = await mandatory_plugins_service.install_mandatory_plugins(
                    guild_session, guild_id=guild_id, created_by=owner.id
                )
        except Exception:
            logger.exception(
                "mandatory plug-ins: guild %s was created without them; the boot "
                "sweep installs what is missing",
                guild_id,
            )
        await guild_session.commit()
        await mandatory_plugins_service.assign_install_settings(
            guild_session, guild_id, installed
        )


class GuildProvisionError(Exception):
    """A new guild's schema could not be provisioned or seeded; its shared
    rows have been removed again."""


async def provision_new_guild(
    session: AsyncSession,
    *,
    name: str,
    creator: User,
    owner: User | None = None,
    description: str | None = None,
    actor_user_id: int | None = None,
) -> Guild:
    """Create a guild end to end: :func:`create_guild`, commit, then
    :func:`seed_guild_content`.

    The shared rows are committed first so the seed runs as a separate step
    that can be undone. If it fails, the schema is dropped, the guild row is
    deleted through :func:`delete_guild` (recorded as ``provision_failed``),
    its plug-in references are forgotten, and :class:`GuildProvisionError` is
    raised. Anything else the caller committed alongside it (a registering
    account) is the caller's to remove.
    """
    from app.db.schema_provisioning import deprovision_guild
    from app.db.session import clear_rls_context
    from app.services.marketplace import plugin_refs

    first = owner or creator
    guild = await create_guild(
        session,
        name=name,
        description=description,
        creator=creator,
        owner=first,
        actor_user_id=actor_user_id,
    )
    await session.commit()
    # Read before the seed: the rollback below expires the ORM objects.
    guild_id = guild.id
    actor = actor_user_id if actor_user_id is not None else first.id
    try:
        await seed_guild_content(session, guild_id=guild_id, owner=first)
    except Exception as exc:
        logger.exception("Guild %s setup failed; rolling back", guild_id)
        # The seed may have left this session aborted or routed into the
        # schema being dropped; the cleanup runs unrouted, on public.
        await session.rollback()
        clear_rls_context(session)
        with suppress(Exception):
            await deprovision_guild(guild_id)
        await delete_guild(
            session,
            await get_guild(session, guild_id=guild_id),
            actor_user_id=actor,
            via="provision_failed",
        )
        await session.commit()
        await plugin_refs.forget_guild(guild_id=guild_id)
        raise GuildProvisionError(guild_id) from exc
    return guild


#: The characters a hex colour is made of, checked one at a time. An explicit
#: set rather than a pattern: the value ends up inside a style attribute, and
#: "which characters are allowed" should be readable as exactly that.
_HEX_DIGITS = frozenset("0123456789abcdef")


def normalize_banner_text_color(value: str | None) -> str:
    """One of :data:`BANNER_TEXT_COLORS`. Anything else raises.

    Banner text is not a free choice, here or in the UI that sets it: the fill
    behind it is the guild's to pick and its artwork can be anything, so the
    words stay readable only by sitting at one end of the scale or the other.
    """
    candidate = normalize_banner_color(value, fallback=DEFAULT_BANNER_TEXT_COLOR)
    if candidate not in BANNER_TEXT_COLORS:
        raise BannerColorError(GuildMessages.BANNER_TEXT_COLOR_INVALID)
    return candidate


def normalize_banner_color(value: str | None, *, fallback: str) -> str:
    """``#rrggbb`` lowercased. Never None — a banner always has its colours.

    ``None`` and an empty string both mean "back to the default", which is what
    a reset sends. A trailing alpha byte is dropped rather than refused: the
    shared colour picker can emit ``#rrggbbaa``, and a banner is a fill with
    nothing behind it for alpha to mean anything against.
    """
    if value is None:
        return fallback
    candidate = value.strip().lower()
    if not candidate:
        return fallback
    if len(candidate) == 9:
        candidate = candidate[:7]
    if (
        len(candidate) != 7
        or candidate[0] != "#"
        or any(character not in _HEX_DIGITS for character in candidate[1:])
    ):
        raise BannerColorError(GuildMessages.BANNER_COLOR_INVALID)
    return candidate


def normalize_banner(values: Mapping[str, str] | None) -> dict[str, str]:
    """The whole banner, canonical. ``None`` is a reset to the default.

    A banner is never colourless and never without a layout, so there is
    nothing here for "empty" to mean — every key comes back. The layout values
    arrive already inside their vocabularies (the request schema types them as
    the enums), leaving the colours to normalize.
    """
    if values is None:
        return dict(DEFAULT_BANNER)
    return {
        "color": normalize_banner_color(
            values.get("color"), fallback=DEFAULT_BANNER["color"]
        ),
        "text_color": normalize_banner_text_color(values.get("text_color")),
        "text_align": values.get("text_align") or DEFAULT_BANNER["text_align"],
        "fade": values.get("fade") or DEFAULT_BANNER["fade"],
    }


async def update_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    name: str | None = None,
    description: str | None = None,
    retention_days: int | None = None,
    retention_days_provided: bool = False,
    is_community: bool | None = None,
    categories: Sequence[str] | None = None,
    categories_provided: bool = False,
    has_adult_content: bool | None = None,
    has_adult_content_provided: bool = False,
    banner: Mapping[str, str] | None = None,
    banner_provided: bool = False,
    location: Mapping[str, Any] | None = None,
    location_provided: bool = False,
    max_storage_bytes: int | None = None,
    max_storage_bytes_provided: bool = False,
    max_users: int | None = None,
    max_users_provided: bool = False,
    max_guests: int | None = None,
    max_guests_provided: bool = False,
    auth_options: list[CommunityAuthOption] | None = None,
    banner_image_enabled: bool | None = None,
    support_enabled: bool | None = None,
) -> Guild:
    guild = await get_guild(session, guild_id=guild_id)
    updated = False
    if name is not None and name.strip() and guild.name != name.strip():
        guild.name = name.strip()
        updated = True
    if description is not None:
        normalized_description = description.strip() or None
        if guild.description != normalized_description:
            guild.description = normalized_description
            updated = True
    if banner_provided:
        normalized_banner = normalize_banner(banner)
        if guild.banner != normalized_banner:
            guild.banner = normalized_banner
            updated = True
    if location_provided:
        # Absent parts are dropped rather than stored as nulls, so two
        # locations that say the same thing are the same value.
        normalized_location = (
            {key: value for key, value in location.items() if value is not None}
            if location
            else None
        )
        if guild.location != normalized_location:
            guild.location = normalized_location
            updated = True
    # An explicit ``null`` is meaningless for a boolean opt-in (mirroring
    # ``auth_options`` below), so null and omitted alike are a no-op.
    if is_community is not None and guild.is_community != is_community:
        # Only the way in is gated. Un-listing is always available — a guild
        # that opted in while the directory was running must still be able to
        # opt back out after an owner switches it off.
        if is_community:
            await assert_community_directory_enabled(session)
        guild.is_community = is_community
        updated = True
        # Listing a community — or taking it back off the shelf — changes what
        # is asked of everybody already in it, none of whom did anything. The
        # one fan-out this channel has, and it is addressed to the roster.
        await _signal_members_present(session, guild_id=guild.id)
    if categories_provided:
        normalized = normalize_categories(categories)
        if guild.categories != normalized:
            # Assigned, never mutated in place: SQLAlchemy does not track
            # in-place changes to an ARRAY column, so an ``.append()`` here
            # would flush nothing.
            guild.categories = normalized
            updated = True
    # The one field here where an explicit null is an answer (back to
    # undeclared) rather than "leave it alone", so it reads the provided flag.
    if has_adult_content_provided and guild.has_adult_content != has_adult_content:
        guild.has_adult_content = has_adult_content
        updated = True
    # Checked against the state the guild is ending up in, not against what this
    # PATCH happened to carry: a request that only clears the categories of an
    # already-listed guild has to fail for the same reason as one that lists a
    # guild with none. Two of the three rules are also database CHECKs; this is
    # what turns them into an error a person can read.
    if guild.is_community:
        await _assert_listable(session, guild)
    if updated:
        guild.updated_at = datetime.now(timezone.utc)
        session.add(guild)
        await session.flush()

    # The operator-set fields live on their own row and are writable only on the
    # system engine, so they are applied separately from the identity edits
    # above — a guild admin's PATCH carries none of them, and skipping the whole
    # block spares that path a query it would never use.
    if (
        max_storage_bytes_provided
        or max_users_provided
        or max_guests_provided
        or auth_options is not None
        or banner_image_enabled is not None
        or support_enabled is not None
    ):
        administration_updated = False
        administration = await get_administration(session, guild_id=guild_id)
        if (
            max_storage_bytes_provided
            and administration.max_storage_bytes != max_storage_bytes
        ):
            administration.max_storage_bytes = max_storage_bytes
            administration_updated = True
        if max_users_provided and administration.max_users != max_users:
            administration.max_users = max_users
            administration_updated = True
        if max_guests_provided and administration.max_guests != max_guests:
            administration.max_guests = max_guests
            administration_updated = True
        # An explicit ``null`` is meaningless for an entitlement (unlike the
        # caps, where null resets to unlimited), so guard on ``is not None`` and
        # treat null/omitted alike as a no-op — mirroring how the operator
        # endpoint guards ``status``. Pydantic keeps an explicit null in
        # ``model_fields_set``, so a plain "provided" flag would let
        # ``{"auth_options": null}`` silently withdraw every option.
        #
        # A sent list replaces the set outright: these are grants, and the
        # operator is stating which ones the guild holds now.
        if auth_options is not None:
            requested = sorted({option.value for option in auth_options})
            if sorted(administration.auth_options or []) != requested:
                administration.auth_options = requested
                administration_updated = True
        if (
            banner_image_enabled is not None
            and administration.banner_image_enabled != banner_image_enabled
        ):
            administration.banner_image_enabled = banner_image_enabled
            administration_updated = True
        if (
            support_enabled is not None
            and administration.support_enabled != support_enabled
        ):
            # Switching it on offers the community's members a form. Where the
            # deployment has bound no support stream, that form has nowhere to
            # send what somebody writes in it, so the entitlement is refused
            # until the deployment has somewhere to receive them. Switching it
            # off is always allowed — a deployment that has stopped staffing
            # help stops offering it.
            from app.services.platform.intake import stream_is_bound

            if support_enabled and not await stream_is_bound(IntakeStream.support):
                raise SupportIntakeMissingError(
                    GuildMessages.SUPPORT_INTAKE_NOT_CONFIGURED
                )
            administration.support_enabled = support_enabled
            administration_updated = True
        if administration_updated:
            session.add(administration)
            await session.flush()
    if retention_days_provided:
        from app.services.platform.app_settings import get_or_create_guild_settings

        gs = await get_or_create_guild_settings(session, guild_id)
        if gs.retention_days != retention_days:
            gs.retention_days = retention_days
            session.add(gs)
            await session.flush()
    return guild


async def set_guild_status(
    session: AsyncSession,
    *,
    guild_id: int,
    status: CommunityStatus,
) -> Guild:
    """Set a guild's lifecycle status (operator moderation action).

    Kept separate from ``update_guild`` so only the platform-operator endpoint
    reaches it — a guild's own admins must never flip their guild's status. On a
    real transition it stamps ``status_changed_at``; a no-op change is left
    untouched. Enforcement of the status lives in the request path
    (``_load_guild_context`` + session routing), not here. Raises
    ``ValueError(COMMUNITY_PURGE_STARTED)`` for a community whose purge has
    begun.
    """
    guild = await get_guild(session, guild_id=guild_id)
    if guild.status != status.value and guild.purge_started_at is not None:
        # Its plug-ins have been asked to erase it: it can only finish going.
        raise ValueError(GuildMessages.COMMUNITY_PURGE_STARTED)
    if guild.status != status.value:
        # A suspension remembers where it began, so lifting it can go back;
        # any other move leaves nothing to go back to.
        guild.status_before_suspension = (
            guild.status if status is CommunityStatus.suspended else None
        )
        guild.status = status.value
        guild.status_changed_at = datetime.now(timezone.utc)
        session.add(guild)
        await session.flush()
        community_hooks.status_changed(session, guild_id)
    return guild


def lifted_status(
    guild: Guild, *, billing_status: CommunityStatus | None
) -> CommunityStatus:
    """Where lifting ``guild``'s suspension returns it: the status it was
    suspended from. A deleted community goes back to ``deleted``. Where billing
    sets plans, a live one goes to the status billing last wrote, which is the
    only one the database lets anything but billing move it to.
    """
    before = guild.status_before_suspension
    if before == CommunityStatus.deleted.value:
        return CommunityStatus.deleted
    if billing_service.billing_managed():
        return billing_status or CommunityStatus.active
    return CommunityStatus(before) if before else CommunityStatus.active


async def get_guild_retention_days(session: AsyncSession) -> int | None:
    """Return the trash retention period in days of the guild the session is
    routed to, or None for "never auto-purge".

    Selecting the full row (not the column) is intentional: NULL in
    ``retention_days`` is the user's explicit "never" choice, and we must
    distinguish it from "no guild_settings row yet" (which would be a
    setup gap, fall back to the 90-day default). A bare column select
    collapses both to None and silently re-enables auto-purge for guilds
    that opted out.
    """
    stmt = select(GuildSetting).limit(1)
    result = await session.exec(stmt)
    row = result.one_or_none()
    if row is None:
        return 90
    return row.retention_days


def _hash_code(code: str) -> str:
    """The stored form of an invite code. Codes are random
    (``INVITE_CODE_BYTES``), so one unsalted SHA-256 is enough and keeps the
    lookup indexed, as for ``user_tokens``."""
    return sha256(code.encode("utf-8")).hexdigest()


async def _invite_code_exists(session: AsyncSession, code: str) -> bool:
    stmt = select(GuildInvite.id).where(GuildInvite.code_hash == _hash_code(code))
    result = await session.exec(stmt)
    return result.first() is not None


async def _generate_unique_invite_code(session: AsyncSession) -> str:
    for _ in range(10):
        candidate = secrets.token_urlsafe(INVITE_CODE_BYTES)
        if not await _invite_code_exists(session, candidate):
            return candidate
    raise RuntimeError("Unable to generate unique invite code")


async def list_guild_invites(
    session: AsyncSession, *, guild_id: int
) -> Sequence[GuildInvite]:
    stmt = (
        select(GuildInvite)
        .where(GuildInvite.guild_id == guild_id)
        .order_by(GuildInvite.created_at.desc())
    )
    result = await session.exec(stmt)
    return result.all()


async def create_guild_invite(
    session: AsyncSession,
    *,
    guild_id: int,
    created_by: int | None,
    expires_at: datetime | None = None,
    max_uses: int | None = 1,
    invitee_email: str | None = None,
    guest_days: int | None = None,
    guest_role: CommunityRole = CommunityRole.guest,
    grants: Sequence[CommunityInviteGrant] = (),
    actor_user_id: int | None = None,
) -> tuple[GuildInvite, str]:
    """Mint an invite, and return it with its code, which is not kept.
    ``guest_days`` makes it a guest invite: redeeming it makes a guest for
    that long, held to the community's and the deployment's limits, and gives
    them ``grants``. The session is routed into the community, where those are
    kept. ``guest_role`` is the rung the guest holds: ``guest``, or on the demo
    deployment a rung above it. ``actor_user_id`` names who for the record;
    without one the invite is minted unrecorded."""
    if guest_role is not CommunityRole.guest and not (
        settings.DEMO_MODE and guest_role in DEMO_GUEST_ROLES
    ):
        raise GuildInviteError(GuildMessages.COMMUNITY_ROLE_NOT_ASSIGNABLE)
    # A full guild mints no new invites: every seat is taken, so any code handed
    # out now could only fail at redemption. Raises ``GuildCapacityError``.
    if guest_days is None:
        await _assert_member_capacity(session, guild_id=guild_id, claiming_seat=False)
    else:
        guest_days = await _guest_days(session, guild_id=guild_id, days=guest_days)
        await _assert_guest_capacity(session, guild_id=guild_id, claiming_seat=False)
    code = await _generate_unique_invite_code(session)
    if expires_at is None:
        expiry = datetime.now(timezone.utc) + timedelta(
            days=DEFAULT_INVITE_EXPIRATION_DAYS
        )
    else:
        expiry = (
            expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
        )
    invite = GuildInvite(
        code_hash=_hash_code(code),
        guild_id=guild_id,
        created_by=created_by,
        expires_at=expiry,
        max_uses=max_uses,
        invitee_email_encrypted=encrypt_field(invitee_email, SALT_EMAIL)
        if invitee_email
        else None,
        guest_days=guest_days,
        guest_role=guest_role if guest_days is not None else None,
    )
    session.add(invite)
    await session.flush()
    for asked in grants:
        grant = GuestInviteGrant(
            invite_id=cast(int, invite.id),
            initiative_id=asked.initiative_id,
            resource_type=asked.resource_type,
            resource_id=asked.resource_id,
            level=ResourceAccessLevel(asked.level) if asked.level else None,
        )
        await _assert_grantable(session, grant)
        session.add(grant)
    await session.flush()
    if actor_user_id is not None:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_INVITE_CREATED,
            actor_user_id=actor_user_id,
            guild_id=guild_id,
            target_type="guild_invite",
            target_id=invite.id,
            detail=_invite_detail(invite),
        )
    return invite, code


async def _assert_grantable(session: AsyncSession, grant: GuestInviteGrant) -> None:
    """Raise ``GuestGrantError`` unless the community holds the initiative a
    guest invite names, and the item, where it names one, in that initiative."""
    from app.db.base import MODELS_BY_TABLE
    from app.models.tenant.initiative import Initiative

    if await session.get(Initiative, grant.initiative_id) is None:
        raise GuestGrantError(GuildMessages.GUEST_GRANT_NOT_FOUND)
    if grant.resource_type is None:
        return
    model = MODELS_BY_TABLE[Tool(grant.resource_type).plural]
    row = await session.get(model, grant.resource_id)
    if row is None or row.initiative_id != grant.initiative_id:
        raise GuestGrantError(GuildMessages.GUEST_GRANT_NOT_FOUND)


async def guest_invite_grants(
    session: AsyncSession, *, invite_ids: Sequence[int]
) -> dict[int, list[GuestInviteGrant]]:
    """What each of these guest invites gives, by invite. The session is
    routed into the community."""
    if not invite_ids:
        return {}
    rows = await session.exec(
        select(GuestInviteGrant)
        .where(ids_in(GuestInviteGrant.invite_id, invite_ids))
        .order_by(GuestInviteGrant.id)
    )
    found: dict[int, list[GuestInviteGrant]] = {}
    for row in rows:
        found.setdefault(row.invite_id, []).append(row)
    return found


def _give_guest_invite_grants(
    session: AsyncSession, *, invite: GuildInvite, user_id: int
) -> None:
    """Once ``session`` commits, give ``user_id`` what ``invite`` names: each
    initiative joined with the role their standing earns, each item shared at
    its level. Run in the community's cohort, as auto-join enrolment is, and
    recorded as its administrator's. Each is given on its own: one deleted or
    archived since is skipped, and the rest are still given."""
    from app.db.base import MODELS_BY_TABLE
    from app.db.session import set_rls_context
    from app.models.tenant.initiative import Initiative
    from app.services import permissions as permissions_service
    from app.services.tenant import initiatives as initiatives_service

    guild_id, invite_id, actor = invite.guild_id, invite.id, invite.created_by

    async def give() -> None:
        async with cohorts.system_session(guild_id) as guild_session:
            await set_rls_context(guild_session, SystemGuild(guild_id))
            grants = await guest_invite_grants(guild_session, invite_ids=[invite_id])
            for grant in grants.get(invite_id, []):
                try:
                    async with guild_session.begin_nested():
                        await give_one(guild_session, grant)
                except DBAPIError:
                    logger.info(
                        "guest invite %s: %s %s not given to user %s",
                        invite_id,
                        grant.resource_type or "initiative",
                        grant.resource_id or grant.initiative_id,
                        user_id,
                    )
            await guild_session.commit()

    async def give_one(guild_session: AsyncSession, grant: GuestInviteGrant) -> None:
        if grant.resource_type is None:
            initiative = await guild_session.get(Initiative, grant.initiative_id)
            if initiative is not None:
                await initiatives_service.self_join(
                    guild_session,
                    initiative=initiative,
                    user_id=user_id,
                    actor_user_id=actor,
                    via="guest_invite",
                )
            return
        tool = Tool(grant.resource_type)
        row = await guild_session.get(MODELS_BY_TABLE[tool.plural], grant.resource_id)
        if row is None or grant.level is None:
            return
        await permissions_service.share_with(
            guild_session,
            resource_type=tool,
            resource_id=row.id,
            guild_id=guild_id,
            initiative_id=row.initiative_id,
            user_id=user_id,
            level=grant.level,
            actor_user_id=actor,
        )

    post_commit.after_commit(session, give)


def _invite_detail(invite: GuildInvite) -> dict[str, object]:
    """What an invite record carries: its terms, and whether it names somebody.

    The code and the address it may be bound to are the invite itself, so
    neither is here — ``addressed`` says only that one is set.
    """
    return {
        "max_uses": invite.max_uses,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        "addressed": invite.invitee_email_encrypted is not None,
        "guest_days": invite.guest_days,
    }


async def delete_guild_invite(
    session: AsyncSession,
    *,
    guild_id: int,
    invite_id: int,
    actor_user_id: int | None = None,
) -> None:
    """Withdraw an invite. ``actor_user_id`` names who for the record; without
    one the withdrawal is unrecorded."""
    stmt = select(GuildInvite).where(
        GuildInvite.id == invite_id,
        GuildInvite.guild_id == guild_id,
    )
    result = await session.exec(stmt)
    invite = result.one_or_none()
    if invite:
        await session.exec(
            delete(GuestInviteGrant).where(col(GuestInviteGrant.invite_id) == invite.id)
        )
        if actor_user_id is not None:
            await audit_service.record(
                session,
                event_type=AuditEventType.GUILD_INVITE_REVOKED,
                actor_user_id=actor_user_id,
                guild_id=guild_id,
                target_type="guild_invite",
                target_id=invite.id,
                detail=_invite_detail(invite),
            )
        await session.delete(invite)


async def delete_guild(
    session: AsyncSession,
    guild: Guild,
    *,
    actor_user_id: int | None = None,
    via: str = "admin",
    target_user_id: int | None = None,
) -> None:
    """Delete a guild's shared rows.

    ``actor_user_id`` names who for the record, ``via`` which surface they did
    it from, and ``target_user_id`` the account the deletion was on behalf of
    where there is one. Without an actor the deletion is unrecorded.

    Under schema-per-guild the guild's content lives in its schema and is removed
    separately by ``deprovision_guild`` (``DROP SCHEMA … CASCADE``). Here we only
    delete the shared guild row; its ``ON DELETE CASCADE`` foreign keys clear the
    roster (memberships, invites, OIDC claim mappings, access grants).

    Order-independent w.r.t. the schema drop: guild-schema tables carry no FKs to
    ``public.guilds`` (provisioning omits cross-schema FKs), so this row delete is
    never blocked by the schema. Callers delete the row first (reliable, makes the
    guild gone) and drop the schema as best-effort cleanup afterwards.

    Uses a bulk DELETE (not ``session.delete``) so the row goes via the DB-level
    ON DELETE CASCADE FKs — ``session.delete`` would walk ORM relationships and
    attempt sync loads in the async context (MissingGreenlet).

    **Callers must follow a successful commit with**
    ``plugin_refs.forget_guild(guild_id=...)`` — what this guild's installed
    plug-ins called its members lives in a platform-wide table that neither the
    guild row's cascade nor the schema drop reaches. After the commit rather
    than here: those references are on a different connection and cannot join
    this transaction, so removing them first would leave a guild whose deletion
    then failed holding none of the identities its plug-ins know its members by.

    Everyone in the guild is poked first, because the cascade that clears the
    roster runs in the database: by the time this returns there is no membership
    row left for anything in Python to read, and every one of those people has
    an account that now says something different. Signalled here rather than at
    the three call sites, so deleting a guild announces itself however it is
    reached.
    """
    guild_id = guild.id
    await _signal_members_present(session, guild_id=guild_id, action="membership")
    if actor_user_id is not None:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_DELETED,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={"via": via},
        )
    await session.exec(delete(Guild).where(Guild.id == guild_id))


@dataclass(frozen=True)
class CommunityDeletionNotice:
    """What to write to whom after a community is deleted.

    Its recipients are gathered before the deletion rather than after: a
    community of one loses its roster on the way out, so the people to tell
    have to be read while they are still there.

    ``purge_at`` is ``None`` where the deployment keeps deleted communities
    indefinitely — then there is no date to name, only the fact that an
    operator can put it back.
    """

    community_name: str
    recipients: list[str]
    purge_at: datetime | None


async def _deletion_recipients(session: AsyncSession, guild: Guild) -> list[str]:
    """Who to tell that this community is gone.

    The people who run it. They are the ones who can ask an operator to put it
    back, and the ones a community's own news belongs to; its members are told
    by the community disappearing from their lists, which is what they can act
    on. Proved addresses only, as account mail is. Sorted and de-duplicated:
    somebody holding two addresses gets one letter at each, and two admins are
    not two letters to the same box.
    """
    from app.services.auth import addresses

    running_it = (
        await session.exec(
            select(GuildMembership.user_id).where(
                GuildMembership.guild_id == guild.id,
                GuildMembership.role == CommunityRole.superadmin,
            )
        )
    ).all()
    recipients: list[str] = []
    for user_id in running_it:
        recipients.extend(await addresses.proven_addresses(session, user_id=user_id))
    return sorted(set(recipients))


async def _superadmin_ids(session: AsyncSession, guild_id: int) -> list[int]:
    return list(
        (
            await session.exec(
                select(GuildMembership.user_id).where(
                    GuildMembership.guild_id == guild_id,
                    GuildMembership.role == CommunityRole.superadmin,
                )
            )
        ).all()
    )


async def announce_on_hold(session: AsyncSession, guild_id: int) -> None:
    """Tell the community's seat holders, once, that it is on hold and whom to
    contact.

    Called after the commit that put it there, on the system engine. The people
    told are its superadmins: the hold is about paying for it, which is the
    seat's errand. Each gets one line in their bell — an account notice, not
    one filed under the community, which none of them can open now — and one
    letter at every proved address, in the language they read, which names the
    day the community is deleted if the hold is still in place. The line goes
    through the notice outbox and the letters through the email outbox as
    account mail, written in one transaction, whose workers deliver and retry
    them.
    """
    from app.db.session import set_rls_context
    from app.services import email as email_service
    from app.services.platform import email_outbox, notice_outbox
    from app.services.platform import intake as intake_service

    await set_rls_context(session, Unattributed())
    guild = (
        await session.exec(select(Guild).where(Guild.id == guild_id))
    ).one_or_none()
    if guild is None or guild.status != CommunityStatus.on_hold.value:
        return
    contact = await intake_service.contact_for(session, IntakeStream.support)
    delete_at = COMMUNITY_HOLD.ends_at(guild, await rules.platform_values(session))
    seat_holders = (
        await session.exec(
            select(User).where(
                User.id.in_(await _superadmin_ids(session, guild_id))  # type: ignore[union-attr]
            )
        )
    ).all()
    data: dict[str, str | None] = {
        "community": guild.name,
        "contact": contact,
        "target_path": "/",
    }
    if delete_at is not None:
        # A calendar day; the bell writes it in the reader's language.
        data["delete_on"] = delete_at.date().isoformat()
    await notice_outbox.enqueue(
        session,
        [
            notice_outbox.row(
                cast(int, user.id), None, NotificationType.community_on_hold, data
            )
            for user in seat_holders
        ],
    )
    # Each letter in a savepoint of its own: one that cannot be queued is
    # logged and leaves the bell lines and the other letters to commit.
    for user in seat_holders:
        try:
            async with session.begin_nested():
                await email_outbox.enqueue_account_letter(
                    user,
                    email_service.community_on_hold_pieces(
                        community=guild.name,
                        contact=contact,
                        guild_id=guild_id,
                        delete_at=delete_at,
                        plan_managed=billing_service.billing_managed(),
                        locale=user.locale or "en",
                    ),
                    session=session,
                )
        except Exception:
            logger.exception(
                "On-hold letter for user %s of community %s was not queued",
                user.id,
                guild_id,
            )
    await session.commit()


#: The bell line each billing trial notice writes.
#: Each billing notice kind: the bell line's type, and the key its day is
#: kept under in the line's data.
_BILLING_NOTICES = {
    "trial_ending": (NotificationType.community_trial_ending, "trial_ends_on"),
    "trial_ended": (NotificationType.community_trial_ended, "trial_ends_on"),
    "pause_reminder": (NotificationType.community_pause_reminder, "holds_on"),
}


async def queue_billing_notice(
    session: AsyncSession,
    guild_id: int,
    *,
    kind: str,
    day: date,
    owner_user_id: int | None,
) -> bool:
    """Write down a notice billing asked for: a community's trial is ending
    or has ended, or its paused plan goes on hold on ``day``.

    On the system engine, before billing's event id is claimed: this commits
    the bell lines and the letters to the notice outbox, whose worker delivers
    and retries them, and only then does the caller record the event. A crash
    between the two repeats the reminder on billing's retry rather than losing
    it. True when anybody is to be told.

    The owner is the person billing holds the community under, while they
    still hold its seat; otherwise — billing named nobody, or somebody who has
    left or been moved off the seat — its current superadmins. A community that
    is deleted or suspended is told nothing: its members cannot act on a plan
    through either.

    Each recipient gets a line in their bell and a letter in their own
    language, both leading to the community's Plan & usage tab. An account
    notice, like a hold's: filed under no community, so no community's
    switches apply to it, and the letter is the recipient's to switch off like
    the rest of their account mail.
    """
    from app.db.session import set_rls_context
    from app.services import email as email_service

    await set_rls_context(session, Unattributed())
    guild = (
        await session.exec(select(Guild).where(Guild.id == guild_id))
    ).one_or_none()
    if guild is None or guild.status in (
        CommunityStatus.deleted.value,
        CommunityStatus.suspended.value,
    ):
        return False
    seats = await _superadmin_ids(session, guild_id)
    recipients = [owner_user_id] if owner_user_id in seats else seats
    if not recipients:
        return False
    notification_type, day_key = _BILLING_NOTICES[kind]
    await _queue_plan_notice(
        session,
        guild,
        recipients,
        notification_type,
        {day_key: day.isoformat()},
        lambda locale: email_service.community_billing_notice_pieces(
            kind=kind,
            community=guild.name,
            day=day,
            guild_id=guild_id,
            locale=locale,
        ),
    )
    return True


async def welcome_new_guild(guild_id: int, *, owner_user_id: int) -> None:
    """Once a new community is committed: where billing sets plans, welcome
    its owner to set one up. Never fails the creation. Billing learns of the
    community, and of its owner, from the change log."""
    if not settings.BILLING_URL:
        return
    try:
        async with cohorts.system_session(guild_id) as notice_session:
            await queue_welcome_notice(
                notice_session, guild_id, owner_user_id=owner_user_id
            )
    except Exception:
        logger.exception("could not welcome the owner of guild %s", guild_id)


async def queue_welcome_notice(
    session: AsyncSession, guild_id: int, *, owner_user_id: int
) -> None:
    """Welcome the person a community was just made for, and invite them to
    set up its plan.

    Called once the new community is committed, where billing sets plans, on
    a system session of its own. The owner is told rather than whoever made
    it: an operator making one for somebody else holds nothing in it. Told
    the way a trial notice is — a line in their bell and a letter in their
    own language — and committed to the notice outbox, whose worker sends it.
    """
    from app.db.session import set_rls_context
    from app.services import email as email_service

    await set_rls_context(session, Unattributed())
    guild = (
        await session.exec(select(Guild).where(Guild.id == guild_id))
    ).one_or_none()
    if guild is None:
        return
    await _queue_plan_notice(
        session,
        guild,
        [owner_user_id],
        NotificationType.community_welcome,
        # The bell line leads to Plan & usage like the trial ones, not to the
        # portal: in the phone app, which may not sell, that tab shows the plan
        # and offers nothing. The letter is the way straight to the portal.
        {},
        lambda locale: email_service.community_welcome_pieces(
            community=guild.name, guild_id=guild_id, locale=locale
        ),
    )


async def _queue_plan_notice(
    session: AsyncSession,
    guild: Guild,
    recipients: list[int],
    notification_type: NotificationType,
    data: dict[str, str],
    letter_for: Callable[[str], EmailPieces],
) -> None:
    """Write one account notice about a community's plan to each recipient: a
    bell line leading to its Plan & usage tab unless ``data`` names another
    ``target_path``, and a letter in the recipient's language. Commits."""
    from app.services.platform import notice_outbox

    locales = dict(
        (
            await session.exec(
                select(User.id, User.locale).where(User.id.in_(recipients))  # type: ignore[union-attr]
            )
        ).all()
    )
    rows = []
    for user_id in recipients:
        letter = letter_for(locales.get(user_id) or "en")
        rows.append(
            notice_outbox.row(
                user_id,
                None,
                notification_type,
                {
                    "community": guild.name,
                    "community_id": guild.id,
                    "target_path": "/settings/usage",
                    **data,
                },
                email_subject=letter.subject,
                email_headline=letter.headline,
                email_body=letter.body,
                email_link=letter.link,
                email_link_label=letter.link_label,
            )
        )
    await notice_outbox.enqueue(session, rows)
    await session.commit()


async def soft_delete_guild(
    session: AsyncSession,
    guild: Guild,
    *,
    actor_user_id: int | None = None,
    via: str = "admin",
    target_user_id: int | None = None,
    keep_roster: bool = False,
) -> CommunityDeletionNotice:
    """Delete a guild by moving it to ``deleted``, keeping everything.

    The guild is mutated in place, so a caller holding it keeps it. What comes
    back is the letter to write once the deletion is committed — gathered here
    rather than by each call site, because a community of one loses its roster
    on the way out and there would be nobody left to address.

    The guild stops existing for everybody in it — absent from their lists,
    refused on every path, admins included — but nothing is destroyed. The
    shared rows, the ``guild_<id>`` schema and the stored blobs all stay where
    they are, so a platform operator can put the community back inside the
    retention window. ``guild_purge`` is what eventually does the destroying,
    and does exactly what :func:`delete_guild` does today.

    ``status_changed_at`` is the deletion time and therefore what the purge
    date is counted from, which is why this stamps it unconditionally rather
    than through :func:`set_guild_status` (a guild deleted twice would keep the
    first stamp and be purged early).

    A community of **one** is the single case where the roster goes with it.
    That roster is a single row describing the person doing the deleting, and
    somebody clearing out a community of their own is often on their way to
    closing their account as well; a restore of one is seated from the wizard
    like any other. Every larger community keeps its roster, because those rows
    describe other people, and bringing the community back without them would
    make a restore into a different community with the same name.
    ``keep_roster`` keeps even that one row, for a deletion nobody asked for:
    a hold that ran out.

    Everyone is poked first, for the same reason :func:`delete_guild` does it:
    by the time this returns, every one of those people has an account that
    says something different.
    """

    guild_id = guild.id
    # Read while the roster is still there: a community of one loses it below.
    recipients = await _deletion_recipients(session, guild)
    await _signal_members_present(session, guild_id=guild_id, action="membership")
    members = await count_members(session, guild_id=guild_id)
    clear_roster = not keep_roster and members <= 1
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_DELETED,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"via": via, "roster_cleared": clear_roster},
    )
    if clear_roster:
        await session.exec(
            delete(GuildMembership).where(GuildMembership.guild_id == guild_id)
        )
    guild.status = CommunityStatus.deleted.value
    guild.status_changed_at = datetime.now(timezone.utc)
    session.add(guild)
    await session.flush()
    community_hooks.status_changed(session, guild_id)
    return CommunityDeletionNotice(
        community_name=guild.name,
        recipients=recipients,
        purge_at=COMMUNITY_DELETION.ends_at(
            guild, await rules.platform_values(session)
        ),
    )


async def guild_has_seat(session: AsyncSession, *, guild_id: int) -> bool:
    """Whether anybody in this guild can still run it.

    The ``superadmin`` seat, specifically: it holds the sign-in configuration
    and the billing portal, and a community without one cannot be configured by
    anybody who is in it. Read before a restore, because restoring a guild
    nobody can administer produces one that is live and unreachable.
    """
    held = (
        await session.exec(
            select(func.count())
            .select_from(GuildMembership)
            .where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.role == CommunityRole.superadmin,
            )
        )
    ).one()
    return held > 0


async def restore_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    status: CommunityStatus,
    seat_user_id: int | None = None,
    actor_user_id: int,
) -> Guild:
    """Bring a deleted guild back at ``status``, seating ``seat_user_id``.

    Raises :class:`ValueError` carrying a message code: the guild must be
    ``deleted``, the status it returns at must be one of
    :func:`restore_status_choices`, and a guild whose roster no longer holds a
    seat must be given one — an account named here is made its ``superadmin``.

    The operator names the status rather than the guild remembering it. A
    community suspended for nonpayment and then deleted should not come back
    trading, and a column recording what it used to be would be one more thing
    to keep correct for a decision somebody is making anyway.
    """
    guild = await get_guild(session, guild_id=guild_id)
    if guild.status != CommunityStatus.deleted.value:
        raise ValueError(GuildMessages.COMMUNITY_NOT_DELETED)
    if guild.purge_started_at is not None:
        # Its plug-ins have been asked to erase it: it can only finish going.
        raise ValueError(GuildMessages.COMMUNITY_PURGE_STARTED)
    if status == CommunityStatus.deleted:
        raise ValueError(GuildMessages.COMMUNITY_RESTORE_STATUS_INVALID)
    if billing_service.billing_managed():
        recorded = (await get_administration(session, guild_id=guild_id)).billing_status
        if status not in restore_status_choices(
            billing_status=CommunityStatus(recorded) if recorded else None,
            billing_managed=True,
        ):
            raise ValueError(GuildMessages.COMMUNITY_RESTORE_STATUS_SET_BY_BILLING)

    await lock_guild_seats(session, guild_id)
    seated: int | None = None
    if not await guild_has_seat(session, guild_id=guild_id):
        if seat_user_id is None:
            raise ValueError(GuildMessages.COMMUNITY_RESTORE_SEAT_REQUIRED)
        user = await session.get(User, seat_user_id)
        if user is None:
            raise ValueError(GuildMessages.COMMUNITY_OWNER_NOT_FOUND)
        await ensure_membership(
            session,
            guild_id=guild_id,
            user_id=seat_user_id,
            role=CommunityRole.superadmin,
            force_role=True,
            actor_user_id=actor_user_id,
            via="restored",
        )
        seated = seat_user_id

    guild.status = status.value
    guild.status_changed_at = datetime.now(timezone.utc)
    session.add(guild)
    community_hooks.status_changed(session, guild_id)
    await audit_service.record(
        session,
        event_type=AuditEventType.GUILD_RESTORED,
        actor_user_id=actor_user_id,
        target_user_id=seated,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"status": status.value, "seated": seated is not None},
    )
    await session.flush()
    return guild


async def get_invite_by_code(
    session: AsyncSession, *, code: str, lock: bool = False
) -> GuildInvite | None:
    """The invite ``code`` opens. ``lock`` holds its row until the transaction
    ends, so two redemptions are counted one after the other."""
    stmt = select(GuildInvite).where(GuildInvite.code_hash == _hash_code(code))
    if lock:
        stmt = stmt.with_for_update()
    result = await session.exec(stmt)
    return result.one_or_none()


def invite_is_active(invite: GuildInvite) -> bool:
    if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
        return False
    if invite.max_uses is not None and invite.uses >= invite.max_uses:
        return False
    return True


async def _live_invite(
    session: AsyncSession,
    *,
    code: str | None = None,
    invite_id: int | None = None,
    lock: bool = False,
) -> GuildInvite:
    """The invite named by its ``code`` or, for one a sign-up already holds,
    its ``invite_id``, while it can still be redeemed."""
    if code is not None:
        invite = await get_invite_by_code(session, code=code, lock=lock)
    else:
        invite = await session.get(GuildInvite, invite_id, with_for_update=lock)
    if not invite:
        raise GuildInviteError(GuildMessages.INVITE_NOT_FOUND)
    if not invite_is_active(invite):
        raise GuildInviteError(GuildMessages.INVITE_EXPIRED_OR_USED)
    # A non-active guild is frozen: no new members while read_only or
    # suspended. Reported as an ordinary expired invite — the guild's
    # lifecycle status is deliberately not disclosed.
    target_guild = await get_guild(session, guild_id=invite.guild_id)
    if target_guild.status != CommunityStatus.active.value:
        raise GuildInviteError(GuildMessages.INVITE_EXPIRED_OR_USED)
    if settings.DEMO_MODE:
        from app.demo import pitches

        # An invite into a pitch opens a copy of it (app.demo.copies), and
        # joins nobody to the pitch itself.
        if await pitches.is_pitch(session, invite.guild_id):
            raise GuildInviteError(GuildMessages.INVITE_NOT_FOUND)
    return invite


async def invite_awaiting_address(
    session: AsyncSession, *, code: str, email: str
) -> GuildInvite | None:
    """The invite a sign-up at ``email`` joins once it proves the address.

    For a sign-up that has not proved its address yet. An invite bound to that
    address waits for the proof rather than being redeemed now; one bound to
    another address is refused, as redeeming it would be. ``None`` for an
    invite that binds no address, which is redeemed with the account.
    """
    invite = await _live_invite(session, code=code)
    bound_email = invite.invitee_email
    if not bound_email:
        return None
    if normalize_email(bound_email) != normalize_email(email):
        raise GuildInviteError(GuildMessages.INVITE_EMAIL_MISMATCH)
    return invite


async def redeem_invite_for_user(
    session: AsyncSession,
    *,
    user: User,
    code: str | None = None,
    invite_id: int | None = None,
) -> Guild:
    """Join ``user`` to the community of the invite named by ``code`` or
    ``invite_id``."""
    invite = await _live_invite(session, code=code, invite_id=invite_id, lock=True)

    # A grant reaches the community for its window and makes nobody a
    # member; joining waits until the grant has ended. A billing grant
    # reaches the billing account alone.
    live_grant = await session.exec(
        select(AccessGrant.id)
        .where(
            AccessGrant.user_id == user.id,
            AccessGrant.guild_id == invite.guild_id,
            AccessGrant.purpose != AccessGrantPurpose.billing.value,
            AccessGrant.live(datetime.now(timezone.utc)),
        )
        .limit(1)
    )
    if live_grant.first() is not None:
        raise GuildInviteError(GuildMessages.INVITE_DURING_ACCESS_GRANT)

    # Email binding. An invite with no bound address
    # (``invitee_email_encrypted`` is NULL) is a shareable link that any
    # authenticated account may redeem. One with an address is for the person
    # holding that address, and redeeming it requires holding it.
    #
    # Any of the account's addresses, not only the one it was created with: an
    # invite sent to somebody's work address is for them. Resolved through the
    # same lookup a sign-in uses, so "proved they hold it" is stated once.
    bound_email = invite.invitee_email
    if bound_email and not await addresses.holds_address(
        session, user_id=user.id, email=bound_email
    ):
        raise GuildInviteError(GuildMessages.INVITE_EMAIL_MISMATCH)

    # An invite into a listed community is still a way into a listed community.
    # The rule belongs to the guild rather than to the route: anyone signed in
    # can find it, so the deployment's age question applies however somebody
    # arrived. A private guild asks nothing, which is every other invite.
    if await is_listed_in_directory(session, guild_id=invite.guild_id):
        await assert_age_confirmed(session, user=user)

    await _refuse_ended_guest(session, guild_id=invite.guild_id, user_id=user.id)
    guest_until = None
    if invite.guest_days is not None:
        days = await _guest_days(
            session, guild_id=invite.guild_id, days=invite.guest_days
        )
        guest_until = datetime.now(timezone.utc) + timedelta(days=days)
    await ensure_membership(
        session,
        guild_id=invite.guild_id,
        user_id=user.id,
        role=invite.guest_role or CommunityRole.member,
        via="invite",
        invite_id=invite.id,
        guest_until=guest_until,
    )
    if guest_until is not None:
        _give_guest_invite_grants(session, invite=invite, user_id=user.id)
    invite.uses += 1
    session.add(invite)
    guild = await get_guild(session, guild_id=invite.guild_id)
    return guild


async def _signal_members_present(
    session: AsyncSession, *, guild_id: int, action: str = "community"
) -> None:
    """Poke this guild's members: what their account says about it has changed.

    Addressed to the whole membership rather than to the sockets this process
    holds. A frame is published on the cross-worker bus, so narrowing to the
    local sockets first would decide, on this worker, that members sitting on
    every other worker are not here — and the frame for them would never be
    published for their own worker to deliver. The bus serializes its sends
    for exactly this fan-out.

    Members with nothing open are addressed too and cost a frame that reaches
    no socket. That is the price of the question being unanswerable from one
    process; they would re-read their account on arriving anyway.
    """
    rows = await session.exec(
        select(GuildMembership.user_id).where(GuildMembership.guild_id == guild_id)
    )
    user_stream.queue_signals(session, rows.all(), account_stream.RESOURCE, action)


async def assert_community_directory_enabled(session: AsyncSession) -> None:
    """Raise unless the platform owner has switched the directory on.

    Read here rather than at each call site so the three surfaces the directory
    consists of — browsing, joining, and a guild listing itself — cannot drift
    apart. Imported lazily because the app-settings service reads guilds.
    """
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.community_directory_enabled(session):
        raise CommunityDirectoryDisabledError(
            GuildMessages.COMMUNITY_DIRECTORY_DISABLED
        )


async def _assert_listable(session: AsyncSession, guild: Guild) -> None:
    """Raise ``CommunityListingError`` unless this guild may be listed.

    Three conditions, each with its own message so the reply says which one:

    - it is on at least one shelf,
    - it has declared itself free of adult content (an unanswered NULL is not a
      declaration and is refused separately from an 18+ guild), and
    - its seat cap leaves room for somebody to join.
    """
    if not guild.categories:
        raise CommunityListingError(GuildMessages.COMMUNITY_COMMUNITY_REQUIRES_CATEGORY)
    if guild.has_adult_content is None:
        raise CommunityListingError(
            GuildMessages.COMMUNITY_COMMUNITY_CONTENT_NOT_DECLARED
        )
    if guild.has_adult_content:
        raise CommunityListingError(GuildMessages.COMMUNITY_COMMUNITY_ADULT_CONTENT)
    administration = await get_administration(session, guild_id=guild.id)
    if (
        administration.max_users is not None
        and administration.max_users < MIN_COMMUNITY_SEATS
    ):
        raise CommunityListingError(GuildMessages.COMMUNITY_COMMUNITY_REQUIRES_CAPACITY)


def community_listing_filters() -> list:
    """The conditions a guild must meet to be showing a card in the directory.

    One list, because three paths ask the same question and must agree: the
    directory that lists a guild, the join that its listing authorizes, and the
    images that listing publishes. A guild that has dropped out of the first
    must drop out of the other two in the same instant.

    Two of the three are CHECK constraints on ``guilds`` as well (a listed
    guild is on a shelf and has declared itself free of adult content), so a
    row that reaches this query already satisfies them. The seat cap is not: it
    lives on ``guild_administration``, only an operator sets it, and it can be
    lowered long after the listing was made.
    """
    return [
        Guild.is_community.is_(True),
        Guild.status == CommunityStatus.active.value,
        # NULL is unlimited, hence the explicit null leg.
        or_(
            GuildAdministration.max_users.is_(None),
            GuildAdministration.max_users >= MIN_COMMUNITY_SEATS,
        ),
    ]


async def is_listed_in_directory(session: AsyncSession, *, guild_id: int) -> bool:
    """Whether this guild is showing a card in the directory right now.

    Asked per request rather than inherited from whatever produced a link, so a
    guild that un-lists itself — or that an operator drops below the seat floor
    — stops being reachable through it immediately.
    """
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.community_directory_enabled(session):
        return False
    statement = (
        select(func.count())
        .select_from(Guild)
        .join(GuildAdministration, GuildAdministration.guild_id == Guild.id)
        .where(Guild.id == guild_id)
    )
    for condition in community_listing_filters():
        statement = statement.where(condition)
    return bool((await session.exec(statement)).one())


async def is_known_under_age(session: AsyncSession, *, user_id: int) -> bool:
    """Whether this account has answered the age question as under the minimum.

    Positive knowledge only. An account that has never been asked answers
    ``False`` here, because "we do not know" is not "too young" — most accounts
    have never been asked, since a private community never puts the question.

    Reads another account's ``users`` row, so it wants a session that can see
    the table: the system engine, or the platform-tier session of the account
    itself. A guild-routed session cannot, which is why the listing guard below
    is asked before a request routes into its guild.
    """
    statement = (
        select(User.id)
        .where(User.id == user_id, User.age_below_minimum_at.is_not(None))
        .limit(1)
    )
    return (await session.exec(statement)).first() is not None


async def assert_may_list_with_members(session: AsyncSession, *, guild_id: int) -> None:
    """Raise unless this guild may move onto the shelf with the members it has.

    A listed community is open to anyone signed in, so the deployment's age
    rule applies to it — and a guild that has been private until now collected
    its members under no such rule. This is the one moment that can be
    reconciled: on the way in, before it is listed.

    Only accounts that have *answered* under the minimum count. An unanswered
    account is not evidence of anything, and holding a listing until every
    member has answered a question nobody has been asked would mean no private
    guild could ever be listed.

    **Asked on the transition only.** An already-listed guild is not re-checked,
    so an admin editing a description never meets a failure about somebody
    else's birthday, with nothing to do about it but remove them.
    """
    from app.services.platform import app_settings as app_settings_service

    if not await app_settings_service.community_age_gate_enabled(session):
        return
    statement = (
        select(GuildMembership.user_id)
        .join(User, User.id == GuildMembership.user_id)
        .where(
            GuildMembership.guild_id == guild_id,
            User.age_below_minimum_at.is_not(None),
        )
        .limit(1)
    )
    if (await session.exec(statement)).first() is not None:
        raise CommunityListingError(GuildMessages.COMMUNITY_COMMUNITY_UNDER_AGE_MEMBERS)


async def assert_age_confirmed(session: AsyncSession, *, user: User) -> None:
    """Raise unless this account may take a place in a listed guild.

    The only place the age question is enforced, and it guards one door: the
    directory's. A listed guild is open to anyone signed in, so taking a seat
    in one is the thing somebody has to be old enough for.

    **Every other way into a guild is not this function's business.** An
    invite, a group sync, an admin adding somebody — those are a community
    choosing who belongs to it, which is the community's to answer for and not
    the deployment's, and none of them come through here. An account that has
    never answered is not held up anywhere else on the platform.

    The directory's Join button asks first and this backs it, so answering is
    what joins rather than what is checked afterwards. An account that answered
    under age is refused with its own code: it is not being asked again, so a
    reply telling it to answer would send it to a form that has nothing for it.
    """
    from app.services.platform import app_settings as app_settings_service

    if user.age_confirmed_at is not None:
        return
    if not await app_settings_service.community_age_gate_enabled(session):
        return
    if user.age_below_minimum_at is not None:
        raise AgeConfirmationRequiredError(GuildMessages.AGE_BELOW_MINIMUM)
    raise AgeConfirmationRequiredError(GuildMessages.AGE_CONFIRMATION_REQUIRED)


async def list_profile_communities(
    session: AsyncSession,
    *,
    user_id: int,
) -> list[Guild]:
    """The listed communities one account belongs to, for their profile.

    Which guilds may appear is ``community_listing_filters()`` — the same list
    the directory, the join it authorizes and the images it publishes all ask,
    so a guild that leaves the shelf leaves every profile in the same instant.
    A guild someone is in that never opted in is nobody else's business and is
    not here.

    Needs a session that can see another account's ``guild_memberships`` (the
    system engine): the request path is scoped to the caller's own rows, and
    the question is about somebody else. Nothing from inside a guild's schema
    is read — only the identity it published by opting in.
    """
    from app.services.platform import app_settings as app_settings_service

    # A deployment with the directory off publishes no communities at all, so
    # there is nothing a profile could name.
    if not await app_settings_service.community_directory_enabled(session):
        return []
    stmt = (
        select(Guild)
        .join(GuildMembership, GuildMembership.guild_id == Guild.id)
        .join(
            GuildAdministration, GuildAdministration.guild_id == Guild.id, isouter=True
        )
        .where(GuildMembership.user_id == user_id, *community_listing_filters())
        .order_by(Guild.name.asc())
    )
    return list((await session.exec(stmt)).unique().all())


async def list_community_guilds(
    session: AsyncSession,
    *,
    user_id: int,
    query: str | None = None,
    query_countries: list[str] | None = None,
    categories: list[str] | None = None,
    near: NearPlace | None = None,
    page: int = 1,
    page_size: int = 24,
) -> tuple[list[tuple[Guild, int, bool]], int]:
    """The community directory: (guild, member_count, already_member) + total.

    Which guilds appear is not this function's decision — it is
    ``community_listing_filters()``, so the directory, the join it authorizes,
    and the images it publishes cannot drift apart.

    Ordered by member count, busiest first, since that is what someone with no
    guild yet is choosing between; ``query`` narrows on name or description
    across the whole directory rather than within a page, so a search reaches
    guilds no amount of scrolling had loaded. It reaches the location too: its
    text, and ``query_countries`` — the countries the search names, resolved by
    the caller, since a country is stored as its code.

    ``near`` reorders without narrowing: the communities nearest the reader
    first (``proximity_order``).

    Needs a session that can see every guild's ``guild_memberships`` rows to
    count them (the system engine), the same precondition ``count_members``
    documents. Nothing about a guild's *content* is read — only the identity it
    published by opting in, plus how many people are already there.
    """
    await assert_community_directory_enabled(session)
    member_count = (
        select(func.count())
        .select_from(GuildMembership)
        .where(
            GuildMembership.guild_id == Guild.id,
            GuildMembership.guest_until.is_(None),
        )
        .correlate(Guild)
        .scalar_subquery()
    )
    already_member = (
        select(func.count())
        .select_from(GuildMembership)
        .where(
            GuildMembership.guild_id == Guild.id,
            GuildMembership.user_id == user_id,
        )
        .correlate(Guild)
        .scalar_subquery()
    )

    filters = community_listing_filters()
    if categories:
        # On any of the shelves asked for.
        filters.append(Guild.categories.overlap(categories))
    if query and query.strip():
        # Case-insensitive across what a card shows: its name, its description
        # and where it is.
        needle = f"%{query.strip()}%"
        location = Guild.__table__.c.location
        matches = [Guild.name.ilike(needle), Guild.description.ilike(needle)]
        matches.extend(
            location[part].astext.ilike(needle) for part in ("text", "label")
        )
        if query_countries:
            matches.append(location["country"].astext.in_(query_countries))
        filters.append(or_(*matches))

    # Every guild has exactly one administration row, created with it, so this
    # is an inner join by construction.
    administration_join = (
        GuildAdministration,
        GuildAdministration.guild_id == Guild.id,
    )
    count_statement = select(func.count()).select_from(Guild).join(*administration_join)
    statement = select(Guild, member_count, already_member > 0).join(
        *administration_join
    )
    for condition in filters:
        statement = statement.where(condition)
        count_statement = count_statement.where(condition)

    total = (await session.exec(count_statement)).one()
    # Busiest first: someone browsing for a community to join is best served by
    # the ones with people already in them. Name and id break ties, so a guild
    # never swaps pages between two requests that saw the same counts.
    ordering = [member_count.desc(), Guild.name.asc(), Guild.id.asc()]
    if near is not None:
        ordering[:0] = proximity_order(near)
    statement = statement.order_by(*ordering)
    rows = (await session.exec(apply_pagination(statement, page, page_size))).all()
    return [(guild, int(count), bool(joined)) for guild, count, joined in rows], int(
        total
    )


async def join_community_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    user: User,
) -> Guild:
    """Join a listed community guild — the invite-free half of the directory.

    The opt-in is the authorization, so this asks the directory's own question
    (``is_listed_in_directory``) rather than a version of it. A guild that is
    not listed is reported as not found rather than as forbidden — an unlisted
    guild has published nothing, and its existence at a given id is part of
    that.

    Runs on the system engine for the same reason ``accept_invite`` does: the
    caller is not a member yet, so no guild-scoped role exists to write the
    membership under.
    """
    await assert_community_directory_enabled(session)
    try:
        guild = await get_guild(session, guild_id=guild_id)
    except ValueError as exc:
        raise CommunityJoinError(GuildMessages.COMMUNITY_NOT_FOUND) from exc
    # Exactly what the directory shows, so a guild it does not list cannot be
    # joined by asking for it directly either.
    if not await is_listed_in_directory(session, guild_id=guild_id):
        raise CommunityJoinError(GuildMessages.COMMUNITY_NOT_A_COMMUNITY)
    # Asked before the seat is taken, so the box is what joins rather than
    # something checked once they are already in.
    await assert_age_confirmed(session, user=user)
    await _refuse_ended_guest(session, guild_id=guild_id, user_id=user.id)
    # Capacity is enforced inside ensure_membership, which is also where a
    # repeat join short-circuits to the existing membership.
    await ensure_membership(
        session,
        guild_id=guild_id,
        user_id=user.id,
        role=CommunityRole.member,
        via="community",
    )
    return guild


async def describe_invite_code(
    session: AsyncSession,
    *,
    code: str,
) -> tuple[GuildInvite | None, Guild | None, bool, str | None]:
    invite = await get_invite_by_code(session, code=code)
    if not invite:
        return None, None, False, GuildMessages.INVITE_NOT_FOUND
    guild = await get_guild(session, guild_id=invite.guild_id)
    # A non-active guild accepts no new members; report the invite as plain
    # expired (never the guild's lifecycle status).
    if guild.status != CommunityStatus.active.value:
        return invite, guild, False, GuildMessages.INVITE_EXPIRED
    if invite_is_active(invite):
        return invite, guild, True, None

    reason = GuildMessages.INVITE_INVALID
    now = datetime.now(timezone.utc)
    if invite.expires_at and invite.expires_at < now:
        reason = GuildMessages.INVITE_EXPIRED
    elif invite.max_uses is not None and invite.uses >= invite.max_uses:
        reason = GuildMessages.INVITE_USED
    return invite, guild, False, reason


async def lock_guild_seats(session: AsyncSession, guild_id: int) -> None:
    """Order the changes that could leave a guild's sign-in rule unliftable.

    Advisory rather than row-based, for two reasons. The paths that change
    these do not all write on the connection that asks the question — leaving
    and being removed are decided on the system engine and written on the
    request one — and a row lock would not span that. And the rows involved
    differ per caller, so locking them directly has two demotions each waiting
    on the other's row.

    Every path that can empty the seat, or impose a requirement on it, takes
    this first, so they order rather than interleave. Held to the end of the
    transaction; the caller does not release it.
    """
    await advisory_lock(session, LockNamespace.GUILD_SEATS, guild_id)


def _sole_seats(user_id: int):
    """The live communities where this account holds the only seat.

    A seat held by an account on its way out is not one. That account keeps
    its membership for its whole window, so counting the row would let two
    seat holders each leave in turn — each one counting the other — and leave
    the community with nobody who can run it.
    """
    mine = aliased(GuildMembership)
    other_seat = aliased(GuildMembership)
    return (
        select(Guild.id, Guild.name)
        .join(mine, mine.guild_id == Guild.id)
        .where(
            mine.user_id == user_id,
            mine.role == CommunityRole.superadmin,
            Guild.status != CommunityStatus.deleted.value,
            ~exists().where(
                other_seat.guild_id == Guild.id,
                other_seat.user_id != user_id,
                other_seat.role == CommunityRole.superadmin,
                User.id == other_seat.user_id,
                User.status != UserStatus.deleted,
            ),
        )
    )


async def must_keep_superadmin(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> bool:
    """Whether this member's seat has to stay where it is.

    True when they hold ``superadmin`` and are the only one who does. Every
    guild keeps one: the seat holds the sign-in configuration and the billing
    portal, and a guild that has emptied it has nobody inside who can seat
    another — so emptying it is not something a guild can be allowed to do to
    itself.

    Narrower once: the last holder stayed only while a sign-in requirement
    stood, which was right while the seat was about sign-in alone and rare
    enough that most guilds never held one. It is now every guild's, and it
    reaches further than sign-in.

    A **deleted** community is exempt. The seat is held so that somebody can
    always appoint another, reach the billing and change the sign-in — none of
    which a deleted community has. Holding its seat therefore blocks nothing,
    which is what lets somebody delete their community and then their account:
    that sequence is the ordinary way out, and a rule written for live
    communities must not stand in the middle of it.

    Call :func:`lock_guild_seats` first — this reads two things that have to
    agree with each other, and the lock is what makes the answer still true
    when the caller acts on it.
    """
    stmt = _sole_seats(user_id).where(Guild.id == guild_id)
    return (await session.exec(stmt)).first() is not None


async def would_strand_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> bool:
    """Whether this account *going* would leave the community without a seat.

    :func:`must_keep_superadmin` with the exception that makes it liveable: a
    community whose only member is the person leaving has nobody to strand, and
    no remedy to offer either — appointing another superadmin takes somebody to
    appoint. They go, and what is left is a community with no members.

    Departure only. Demotion does not get the exception and asks
    :func:`must_keep_superadmin` directly: somebody who demotes themselves
    while alone is still there afterwards, in a community they can no longer
    configure and cannot re-seat.

    Call :func:`lock_guild_seats` first, as for the rule it builds on.
    """
    return bool(await stranded_seats(session, user_id=user_id, guild_id=guild_id))


async def stranded_seats(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int | None = None,
) -> list[tuple[int, str]]:
    """``(id, name)`` of every community this account going would strand, in
    id order — :func:`would_strand_guild` for all of its seats in one query.

    ``guild_id`` narrows it to one community.
    """
    others = aliased(GuildMembership)
    stmt = (
        _sole_seats(user_id)
        .where(
            exists().where(
                others.guild_id == Guild.id,
                others.user_id != user_id,
            )
        )
        .order_by(Guild.id)
    )
    if guild_id is not None:
        stmt = stmt.where(Guild.id == guild_id)
    return [(row[0], row[1]) for row in (await session.exec(stmt)).all()]


async def remove_user_from_guild(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    actor_user_id: int | None,
    via: str | None = None,
    only_if: ColumnElement[bool] | None = None,
) -> bool:
    """Remove a user from a guild, its initiatives, and its plug-ins. Says
    whether there was a membership to remove.

    With ``only_if``, the membership row goes first and only while it still
    matches: one statement checks and deletes it, and nothing else is touched
    when it no longer does.

    Leaving, being removed by an admin and being released by sign-in sync all
    come here: ``actor_user_id`` is the person themselves when they leave, and
    the admin when they are removed, and the record and the plug-in revocations
    say which it was. A removal nobody made passes no actor and names itself
    with ``via``.

    Leaving a guild ends what that guild's plug-ins let this person reach at an
    outside vendor: the credentials they connected under this guild's authority
    are deleted and the plug-ins holding them are told to let go. Their connections
    in other guilds are untouched — those relationships have not ended.

    The session must already be routed into the guild. Revocations are queued on
    it and delivered by the caller after the commit.
    """
    from app.services.tenant import plugin_connections as plugin_connections_service
    from app.services.tenant import plugin_member_consents as consents_service
    from app.services.tenant import initiatives as initiatives_service

    if via is None:
        left = actor_user_id == user_id
        via, reason = (
            ("left", "left_guild") if left else ("admin", "removed_from_guild")
        )
    else:
        reason = via
    this_row = (
        GuildMembership.guild_id == guild_id,
        GuildMembership.user_id == user_id,
    )
    if only_if is not None:
        previous_role = (
            await session.exec(
                delete(GuildMembership)
                .where(*this_row, only_if)
                .returning(GuildMembership.role)
            )
        ).scalar_one_or_none()
        if previous_role is None:
            return False
    else:
        # Read before the delete below takes the row: the record says which
        # standing the person held when they left.
        previous_role = (
            await session.exec(select(GuildMembership.role).where(*this_row))
        ).one_or_none()

    # Remove from all initiatives in this guild
    await initiatives_service.remove_user_from_guild_initiatives(
        session,
        guild_id=guild_id,
        user_id=user_id,
    )

    await plugin_connections_service.delete_member_connections(
        session,
        user_id=user_id,
        reason=reason,
    )
    # Leaving ends what this guild's plug-ins may do as this person, the same way it
    # ends what they reach at a vendor.
    await consents_service.delete_member_consents(session, user_id=user_id)
    # And their subscription links into it, so coming back does not bring an
    # old one back. They are the system engine's and go on a session of their
    # own, ahead of this one's commit; a removal that then rolls back leaves a
    # member with no links, who makes another.
    await api_keys_service.delete_resource_keys(user_id=user_id, guild_id=guild_id)

    # Remove guild membership
    removed = only_if is not None or bool(
        (await session.exec(delete(GuildMembership).where(*this_row))).rowcount
    )
    # Only a real removal is a membership change — mirror the insert side,
    # which pings only on a genuine insert (a no-op remove of a non-member
    # must not nudge billing).
    if removed:
        await audit_service.record(
            session,
            event_type=AuditEventType.GUILD_MEMBER_REMOVED,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
            detail={
                "role": previous_role.value if previous_role else None,
                "via": via,
            },
        )
        # Same reason as the insert side: what is asked of this account can
        # change with where it belongs, and leaving is not always their doing.
        account_stream.queue_account_signal(session, user_id, "membership")
        # This community was a leg of can_ask for everyone they shared it with,
        # so every open channel that rested on it is re-tested — one survives if
        # the pair connected, which is what a connection is for. Queued rather
        # than run here: the sweep reads the state this delete leaves behind,
        # and this delete is not committed yet.
        contact_grants_service.queue_stale_grant_sweep(session, user_id)
    return removed
