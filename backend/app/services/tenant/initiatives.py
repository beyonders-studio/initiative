from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
import logging
from typing import Iterable

from sqlalchemy import case, desc, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, selectinload
from sqlmodel import select, delete, update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.query import ids_in
from app.db.session import routed_guild_id
from app.core.audit_events import AuditEventType
from app.core.errors import CodedError
from app.core.messages import InitiativeMessages
from app.db.session import routed_context
from app.models.tenant.resource_grant import ResourceGrant
from app.models.tenant.initiative import (
    INITIATIVE_CUSTOM_ROLES,
    INITIATIVE_MEMBER_PREFIX,
    INITIATIVE_TOOL_KEYS,
    BUILTIN_ROLES,
    Initiative,
    InitiativeJoinPolicy,
    InitiativeJoinRequest,
    InitiativeMember,
    InitiativeRoleModel,
    InitiativeRule,
    BUILTIN_ROLE_PERMISSIONS,
    JoinRequestStatus,
    PermissionKey,
)
from app.models.platform.guild import GUILD_ADMIN_ROLES, GuildMembership
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.schemas.platform.user import UserInitiativeRole, UserSummary
from app.schemas.tenant.initiative import (
    InitiativeDefaultsRead,
    InitiativeDefaultsUpdate,
    InitiativeDirectoryEntry,
    InitiativeJoinRequestRead,
)
from app.services import audit as audit_service


logger = logging.getLogger(__name__)


async def get_role_by_name(
    session: AsyncSession,
    *,
    initiative_id: int,
    role_name: str,
) -> InitiativeRoleModel | None:
    """Get a role by name within an initiative."""
    stmt = select(InitiativeRoleModel).where(
        InitiativeRoleModel.initiative_id == initiative_id,
        InitiativeRoleModel.name == role_name,
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def get_moderator_role(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> InitiativeRoleModel | None:
    """Get the moderator role for an initiative — the built-in that carries
    "Full access" (``override_share_restrictions``)."""
    return await get_role_by_name(
        session, initiative_id=initiative_id, role_name="moderator"
    )


async def get_member_role(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> InitiativeRoleModel | None:
    """Get the member role for an initiative."""
    return await get_role_by_name(
        session, initiative_id=initiative_id, role_name="member"
    )


async def is_guild_admin_member(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> bool:
    """Whether ``user_id`` administers ``guild_id`` — admin or above."""
    result = await session.exec(
        select(GuildMembership.role).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.user_id == user_id,
        )
    )
    return result.one_or_none() in GUILD_ADMIN_ROLES


async def resolve_membership_role(
    session: AsyncSession,
    *,
    initiative: Initiative,
    user_id: int,
    requested: InitiativeRoleModel | None = None,
) -> InitiativeRoleModel | None:
    """The role a membership row takes for ``user_id`` — the one rule every
    route into an initiative resolves its role through.

    A guild admin's standing already reaches every initiative in their guild,
    so their row carries a manager role: the built-in moderator unless another
    manager role was named. That is settled here rather than refused, so a
    project manager can bring an admin into their initiative like anyone else.

    Everyone else takes ``requested``, or the built-in ``member`` role when the
    caller names none. ``None`` means the initiative has no role to give, which
    is the caller's error to report.
    """
    if await is_guild_admin_member(
        session, guild_id=routed_guild_id(session), user_id=user_id
    ):
        if requested is not None and requested.is_manager:
            return requested
        return await get_moderator_role(session, initiative_id=initiative.id)
    if requested is not None:
        return requested
    return await get_member_role(session, initiative_id=initiative.id)


async def creator_role(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    roles: dict[str, InitiativeRoleModel],
) -> InitiativeRoleModel:
    """The built-in role the person who brings an initiative into being takes.

    A guild admin lands on the moderator role, the same as on any other route
    into an initiative — :func:`resolve_membership_role` settles that for a row
    somebody else writes, and this settles it for the row they write for
    themselves. Anyone else becomes the project manager of what they made.
    """
    if await is_guild_admin_member(session, guild_id=guild_id, user_id=user_id):
        return roles["moderator"]
    return roles["project_manager"]


async def align_guild_admin_membership_roles(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> list[int]:
    """Move ``user_id``'s existing initiative rows onto a manager role.

    A guild admin's membership row carries a manager role.
    :func:`resolve_membership_role` settles that for every row written from
    here on; this settles the rows that were already there when they were
    promoted, so everything that reads ``is_manager`` — the join-request queue
    and the notifications that follow it, the directory's queue badge — agrees
    with the standing they now hold.

    Rows already on a manager role are left alone, as is an initiative with no
    moderator role to move them to. Returns the initiative ids changed.

    The session must already be routed into the guild's schema; flush-only, the
    caller owns the transaction.
    """
    rows = (
        await session.exec(
            select(InitiativeMember)
            .options(selectinload(InitiativeMember.role_ref))
            .where(
                InitiativeMember.user_id == user_id,
            )
        )
    ).all()

    changed: list[int] = []
    for membership in rows:
        if membership.role_ref is not None and membership.role_ref.is_manager:
            continue
        moderator = await get_moderator_role(
            session, initiative_id=membership.initiative_id
        )
        if moderator is None:
            continue
        membership.role_id = moderator.id
        session.add(membership)
        changed.append(membership.initiative_id)
    if changed:
        await session.flush()
    return changed


async def create_builtin_roles(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> dict[str, InitiativeRoleModel]:
    """Create an initiative's built-in roles, keyed by name.

    Walks :data:`BUILTIN_ROLES` in order, so a role added to that tuple is a
    role every new initiative gets — nothing here names one.
    """
    roles: dict[str, InitiativeRoleModel] = {}
    for position, spec in enumerate(BUILTIN_ROLES):
        role = InitiativeRoleModel(
            initiative_id=initiative_id,
            name=spec.name,
            display_name=spec.display_name,
            is_builtin=True,
            is_manager=spec.is_manager,
            override_share_restrictions=spec.override_share_restrictions,
            position=position,
        )
        session.add(role)
        roles[spec.name] = role
    await session.flush()

    for spec in BUILTIN_ROLES:
        for perm_key, enabled in spec.permissions.items():
            session.add(
                InitiativeRule(
                    initiative_id=initiative_id,
                    initiative_role_id=roles[spec.name].id,
                    key=perm_key,
                    enabled=enabled,
                )
            )

    await session.flush()
    return roles


async def load_user_initiative_roles(
    session: AsyncSession, users: Sequence[User]
) -> None:
    """Load initiative role information for users (for display purposes)."""
    user_ids = [user.id for user in users if user.id is not None]
    if not user_ids:
        return
    stmt = (
        select(
            InitiativeMember.user_id,
            InitiativeRoleModel.name,
            Initiative.id,
            Initiative.name,
        )
        .join(Initiative, Initiative.id == InitiativeMember.initiative_id)
        .outerjoin(
            InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id
        )
        .where(ids_in(InitiativeMember.user_id, user_ids))
    )
    result = await session.exec(stmt)
    assignments: dict[int, list[UserInitiativeRole]] = {
        user_id: [] for user_id in user_ids
    }
    for user_id, role_name, initiative_id, initiative_name in result.all():
        assignments.setdefault(user_id, []).append(
            UserInitiativeRole(
                initiative_id=initiative_id,
                initiative_name=initiative_name,
                role=role_name,
            )
        )
    for user in users:
        user_assignments = assignments.get(user.id or 0, [])
        object.__setattr__(user, "initiative_roles", user_assignments)


async def get_initiative_membership(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> InitiativeMember | None:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def initiative_roster(
    session: AsyncSession, initiative_id: int, *, with_users: bool = False
) -> list[InitiativeMember]:
    """The initiative's members, for a caller whose question is the roster
    itself: who to notify, whose access to copy, whom to offer in a picker.

    A read of a resource does not carry it; what a reader may do with a row is
    the database's answer, and the roster is read here, where it is the point.
    """
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id
    )
    if with_users:
        stmt = stmt.options(selectinload(InitiativeMember.user))
    return list((await session.exec(stmt)).all())


async def get_initiative_membership_with_role(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> InitiativeMember | None:
    """Get membership with role eagerly loaded."""
    stmt = (
        select(InitiativeMember)
        .options(
            selectinload(InitiativeMember.role_ref).selectinload(
                InitiativeRoleModel.permissions
            )
        )
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeMember.user_id == user_id,
        )
    )
    result = await session.exec(stmt)
    return result.one_or_none()


async def ensure_managers_remain(
    session: AsyncSession,
    *,
    initiative_id: int,
    excluded_user_ids: Iterable[int] | None = None,
) -> None:
    """Ensure at least one manager remains after excluding certain users."""
    excluded = set(excluded_user_ids or [])
    stmt = (
        select(InitiativeMember)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeRoleModel.is_manager.is_(True),
        )
    )
    result = await session.exec(stmt)
    managers = [
        membership for membership in result.all() if membership.user_id not in excluded
    ]
    if not managers:
        raise CodedError(InitiativeMessages.MUST_HAVE_PM)


async def remove_user_from_guild_initiatives(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> None:
    """Take a user out of the community's content: every initiative, and the
    community's own tools.

    Used by every "user leaves the guild for any reason" path: leave-guild,
    deactivate, soft-delete, hard-delete, OIDC-sync revocation, and the
    guild-admin Remove-from-guild action.

    Deleting each membership row runs ``tr_initiative_members_departure``,
    which drops every grant naming them in that initiative, owner rows
    included, and takes them off its tasks, events, person fields and queue
    items. ``member_departs`` with no initiative does the same for content
    that belongs to the community itself. What they owned is left **unowned**
    rather than handed to anyone; guild admins can claim it whenever they
    choose (``app.services.tenant.ownership``). What they kept about its items
    (opens, bookmarks, subscriptions) goes too.
    """
    from app.db.schema_provisioning import guild_schema_name
    from app.services.tenant import personal_items

    schema = guild_schema_name(guild_id)
    await session.exec(select(func.public.member_departs(schema, user_id, None)))
    # An initiative they reached only through items shared with them has no
    # membership row to delete, so its departure is run here.
    shared_only = (
        select(ResourceGrant.initiative_id)
        .where(
            ResourceGrant.user_id == user_id,
            ResourceGrant.initiative_id.is_not(None),
            ResourceGrant.initiative_id.not_in(
                select(InitiativeMember.initiative_id).where(
                    InitiativeMember.user_id == user_id
                )
            ),
        )
        .distinct()
    )
    shared_only_ids = list((await session.exec(shared_only)).all())
    for initiative_id in shared_only_ids:
        await session.exec(
            select(func.public.member_departs(schema, user_id, initiative_id))
        )
    if shared_only_ids:
        # Outside a trigger the departure leaves archived content as it is,
        # its grants included. A grant goes whatever state its item is in.
        await session.exec(
            delete(ResourceGrant).where(
                ResourceGrant.user_id == user_id,
                ResourceGrant.initiative_id.in_(shared_only_ids),
            )
        )
    await session.exec(
        delete(InitiativeMember).where(
            InitiativeMember.user_id == user_id,
            InitiativeMember.initiative_id.in_(select(Initiative.id)),
        )
    )
    await personal_items.purge_for_user(session, user_id)


async def list_initiative_roles(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> list[InitiativeRoleModel]:
    """List all roles for an initiative with their permissions."""
    stmt = (
        select(InitiativeRoleModel)
        .options(selectinload(InitiativeRoleModel.permissions))
        .where(InitiativeRoleModel.initiative_id == initiative_id)
        .order_by(InitiativeRoleModel.position, InitiativeRoleModel.id)
    )
    result = await session.exec(stmt)
    return list(result.all())


async def get_role_by_id(
    session: AsyncSession,
    *,
    role_id: int,
    initiative_id: int | None = None,
) -> InitiativeRoleModel | None:
    """Get a role by ID, optionally verifying it belongs to an initiative."""
    stmt = (
        select(InitiativeRoleModel)
        .options(selectinload(InitiativeRoleModel.permissions))
        .where(InitiativeRoleModel.id == role_id)
    )
    if initiative_id is not None:
        stmt = stmt.where(InitiativeRoleModel.initiative_id == initiative_id)
    result = await session.exec(stmt)
    return result.one_or_none()


async def create_custom_role(
    session: AsyncSession,
    *,
    initiative_id: int,
    name: str,
    display_name: str,
    is_manager: bool = False,
    permissions: dict[PermissionKey, bool] | None = None,
) -> InitiativeRoleModel:
    """Create a custom role for an initiative."""
    # Get next position
    stmt = select(func.max(InitiativeRoleModel.position)).where(
        InitiativeRoleModel.initiative_id == initiative_id
    )
    result = await session.exec(stmt)
    max_position = result.one() or 0

    role = InitiativeRoleModel(
        initiative_id=initiative_id,
        name=name,
        display_name=display_name,
        is_builtin=False,
        is_manager=is_manager,
        position=max_position + 1,
    )
    session.add(role)
    await session.flush()

    # Add permissions (default to member permissions if not specified)
    perms = permissions or dict(BUILTIN_ROLE_PERMISSIONS["member"])
    for perm_key, enabled in perms.items():
        session.add(
            InitiativeRule(
                initiative_id=role.initiative_id,
                initiative_role_id=role.id,
                key=perm_key,
                enabled=enabled,
            )
        )

    await session.flush()
    await session.refresh(role, attribute_names=["permissions"])
    return role


async def update_role_permissions(
    session: AsyncSession,
    *,
    role: InitiativeRoleModel,
    permissions: dict[PermissionKey, bool],
) -> InitiativeRoleModel:
    """Update permissions for a role."""
    for perm_key, enabled in permissions.items():
        # Find existing permission
        existing = next(
            (p for p in role.permissions if p.key == perm_key),
            None,
        )
        if existing:
            existing.enabled = enabled
            session.add(existing)
        else:
            session.add(
                InitiativeRule(
                    initiative_id=role.initiative_id,
                    initiative_role_id=role.id,
                    key=perm_key,
                    enabled=enabled,
                )
            )
    await session.flush()
    await session.refresh(role, attribute_names=["permissions"])
    return role


async def delete_role(
    session: AsyncSession,
    *,
    role: InitiativeRoleModel,
) -> None:
    """Delete a custom role. Cannot delete built-in roles."""
    if role.is_builtin:
        raise CodedError(InitiativeMessages.CANNOT_DELETE_BUILTIN)

    # Check if any members use this role
    stmt = select(func.count()).where(InitiativeMember.role_id == role.id)
    result = await session.exec(stmt)
    member_count = result.one()
    if member_count > 0:
        raise CodedError(InitiativeMessages.ROLE_HAS_MEMBERS)

    await session.delete(role)
    await session.flush()


async def count_role_members(
    session: AsyncSession,
    *,
    role_id: int,
) -> int:
    """Count members assigned to a role."""
    stmt = select(func.count()).where(InitiativeMember.role_id == role_id)
    result = await session.exec(stmt)
    return result.one()


async def count_members_by_role(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> dict[int, int]:
    """Members per role across one initiative, in one query. A role nobody
    holds is absent."""
    stmt = (
        select(InitiativeMember.role_id, func.count())
        .where(InitiativeMember.initiative_id == initiative_id)
        .group_by(InitiativeMember.role_id)
    )
    return {
        role_id: count
        for role_id, count in (await session.exec(stmt)).all()
        if role_id is not None
    }


# ============================================================================
# Discovery: directory, self-join, join settings
# ============================================================================

#: The policies that put an initiative on the guild's directory for everyone.
#: ``private`` is deliberately absent: RLS *would* permit listing it (the
#: ``initiatives`` table is structural, so any guild member's session can read
#: the row), so keeping private initiatives off the directory is an app-layer
#: promise this constant makes in one place. The one exception is the caller's
#: own membership — a private initiative is listed to its own members, which
#: reveals nothing they don't already see in their sidebar.
LISTED_JOIN_POLICIES: tuple[str, ...] = (
    InitiativeJoinPolicy.request.value,
    InitiativeJoinPolicy.open.value,
)


async def list_directory_entries(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    is_guild_admin: bool = False,
) -> list[InitiativeDirectoryEntry]:
    """The guild's initiative directory, as seen by one caller.

    Active, non-archived initiatives whose policy asks to be listed — plus the
    caller's own initiatives whatever their policy, so the directory doubles as
    the guild's complete initiative list. Each entry carries its roster size
    and the caller's own state (in it and on which role / knocked / free to
    join) so the client renders one call to action per card. A private
    initiative the caller is *not* in stays unlisted.

    One reading for everyone, guild admin included: their authority still
    reaches every initiative, but the front page lists the ones they are in and
    the ones on offer, the same as anyone else. The whole-guild listing is
    ``scope=community`` on the initiatives endpoint, which backs guild settings.

    Managers additionally get the size of their own join-request queue, so the
    guild home needs no second call to badge it. A guild admin gets it for the
    initiatives they are in, whatever role their own row happens to carry —
    answering a request is authority they hold as admin. It stays off the
    initiatives they are not in, which are not theirs to read into.
    """
    member_count = (
        select(func.count())
        .select_from(InitiativeMember)
        .where(InitiativeMember.initiative_id == Initiative.id)
        .scalar_subquery()
    )
    is_member = (
        select(InitiativeMember.user_id)
        .where(
            InitiativeMember.initiative_id == Initiative.id,
            InitiativeMember.user_id == user_id,
        )
        .exists()
    )
    role_display_name = (
        select(InitiativeRoleModel.display_name)
        .join(InitiativeMember, InitiativeMember.role_id == InitiativeRoleModel.id)
        .where(
            InitiativeMember.initiative_id == Initiative.id,
            InitiativeMember.user_id == user_id,
        )
        .scalar_subquery()
    )
    has_pending_request = (
        select(InitiativeJoinRequest.id)
        .where(
            InitiativeJoinRequest.initiative_id == Initiative.id,
            InitiativeJoinRequest.user_id == user_id,
            InitiativeJoinRequest.status == JoinRequestStatus.pending.value,
        )
        .exists()
    )
    # The queue badge, and only for whoever may answer the queue: a manager of
    # that initiative, or a guild admin who is in it. Everyone else reads a flat
    # zero instead of a headcount of their peers' knocking, and the CASE means
    # the count is not computed for them at all.
    manages = (
        select(InitiativeMember.user_id)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.initiative_id == Initiative.id,
            InitiativeMember.user_id == user_id,
            InitiativeRoleModel.is_manager.is_(True),
        )
        .exists()
    )
    pending_count = (
        select(func.count())
        .select_from(InitiativeJoinRequest)
        .where(
            InitiativeJoinRequest.initiative_id == Initiative.id,
            InitiativeJoinRequest.status == JoinRequestStatus.pending.value,
        )
        .scalar_subquery()
    )
    may_answer = or_(manages, is_member) if is_guild_admin else manages
    pending_queue_size = case((may_answer, pending_count), else_=0)

    statement = (
        select(
            Initiative,
            member_count,
            is_member,
            role_display_name,
            has_pending_request,
            pending_queue_size,
        )
        .where(
            or_(Initiative.join_policy.in_(LISTED_JOIN_POLICIES), is_member),
            Initiative.archived_at.is_(None),
            Initiative.deleted_at.is_(None),
        )
        # The caller's own initiatives first — the list serves "mine" before
        # "what else is on offer".
        .order_by(desc(is_member), Initiative.name.asc(), Initiative.id.asc())
    )
    rows = (await session.exec(statement)).all()
    return [
        InitiativeDirectoryEntry(
            id=initiative.id,
            name=initiative.name,
            description=initiative.description,
            color=initiative.color,
            join_policy=initiative.join_policy,
            auto_join=initiative.auto_join,
            member_count=count,
            is_member=member,
            role_display_name=role,
            has_pending_request=pending,
            pending_join_request_count=queue_size,
        )
        for initiative, count, member, role, pending, queue_size in rows
    ]


def is_self_joinable(initiative: Initiative) -> bool:
    """Whether a guild member may add themselves to ``initiative`` right now."""
    return (
        initiative.join_policy == InitiativeJoinPolicy.open.value
        and initiative.archived_at is None
        and initiative.deleted_at is None
    )


def _acting_user_id(session: AsyncSession) -> int | None:
    """The account this session is acting as, or ``None``.

    The guild-join excursion and the claim sync route into a guild's schema
    with no account behind them, so what they enrol is recorded with no actor;
    every request path is recorded against the account making it.
    """
    try:
        return routed_context(session).user_id
    except RuntimeError:
        return None


async def self_join(
    session: AsyncSession,
    *,
    initiative: Initiative,
    user_id: int,
    actor_user_id: int | None = None,
    via: str = "self_join",
) -> InitiativeMember:
    """Add ``user_id`` to ``initiative`` with the role their standing earns.

    The floor, not the ceiling: ``member`` is view-only on the core tools and
    creates nothing, and per-resource sharing still decides what is reachable
    inside. The row is ordinary — no managing provider, so group sync neither
    reaps it nor fights it — which is the whole point: every join path ends at
    the same membership row RLS already reads.

    The role comes from :func:`resolve_membership_role`, so a guild admin
    arriving by any of these routes lands on the manager role their standing
    already implies.

    A membership this writes is recorded, with ``via`` naming the route that
    produced it. ``actor_user_id`` is who is doing it; left ``None`` it is the
    account the session is acting as, which on the self-join path is the
    joining user.

    Idempotent — an existing membership is returned untouched. Flush-only; the
    caller owns the transaction. The policy check is the caller's
    (:func:`is_self_joinable`).
    """
    existing = await get_initiative_membership(
        session, initiative_id=initiative.id, user_id=user_id
    )
    if existing is not None:
        return existing

    role = await resolve_membership_role(
        session, initiative=initiative, user_id=user_id
    )
    if role is None:
        raise ValueError(InitiativeMessages.MEMBER_ROLE_NOT_FOUND)

    membership = InitiativeMember(
        initiative_id=initiative.id,
        user_id=user_id,
        role_id=role.id,
        oidc_provider_id=None,
    )
    # Two overlapping joins both clear the lookup above, and the composite
    # primary key then rejects the loser. That is the same outcome the caller
    # asked for, so the savepoint absorbs it and the row that won is returned.
    try:
        async with session.begin_nested():
            session.add(membership)
            await session.flush()
    except IntegrityError:
        existing = await get_initiative_membership(
            session, initiative_id=initiative.id, user_id=user_id
        )
        if existing is None:
            raise
        return existing

    await audit_service.record(
        session,
        event_type=AuditEventType.INITIATIVE_MEMBER_ADDED,
        actor_user_id=(
            actor_user_id if actor_user_id is not None else _acting_user_id(session)
        ),
        target_user_id=user_id,
        guild_id=routed_guild_id(session),
        target_type="initiative",
        target_id=initiative.id,
        detail={"role_id": role.id, "role": role.name, "via": via},
    )
    return membership


async def list_auto_join_initiatives(
    session: AsyncSession,
    *,
    guild_id: int,
) -> list[Initiative]:
    """The initiatives a new member of ``guild_id`` is enrolled in on arrival.

    Live ones only — an archived or soft-deleted initiative is not somewhere to
    land. ``ck_initiatives_auto_join_open`` already guarantees every row here is
    ``join_policy = 'open'``, i.e. one the same person could have joined by
    themselves from the directory a moment later. Enrolment therefore hands out
    nothing that was not already on offer; it only saves the click.

    The session must already be routed into the guild's schema.
    """
    result = await session.exec(
        select(Initiative)
        .where(
            Initiative.auto_join.is_(True),
            Initiative.archived_at.is_(None),
            Initiative.deleted_at.is_(None),
        )
        .order_by(Initiative.id.asc())
    )
    return list(result.all())


async def enroll_in_auto_join_initiatives(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
) -> list[int]:
    """Enrol a brand-new guild member in the guild's auto-join initiatives.

    Each enrolment routes through :func:`self_join`, so an arrival lands on the
    same membership row every other join path writes — no managing provider,
    so group sync neither reaps nor fights it.

    Best effort, per initiative: one initiative that cannot take a member (its
    built-in ``member`` role is missing, say) is logged and skipped inside its
    own savepoint, so the rest still enrol and the guild join that triggered
    this never fails over an onboarding convenience.

    Returns the ids actually joined. The session must already be routed into the
    guild's schema; flush-only, the caller owns the transaction.
    """
    joined: list[int] = []
    for initiative in await list_auto_join_initiatives(session, guild_id=guild_id):
        try:
            async with session.begin_nested():
                await self_join(
                    session,
                    initiative=initiative,
                    user_id=user_id,
                    via="auto_join",
                )
        except Exception:
            logger.exception(
                "auto-join: user %s was not enrolled in initiative %s of guild %s",
                user_id,
                initiative.id,
                guild_id,
            )
            continue
        joined.append(initiative.id)
    return joined


# ============================================================================
# Discovery: join requests
# ============================================================================


def is_requestable(initiative: Initiative) -> bool:
    """Whether a guild member may knock on ``initiative`` right now."""
    return (
        initiative.join_policy == InitiativeJoinPolicy.request.value
        and initiative.archived_at is None
        and initiative.deleted_at is None
    )


async def get_pending_join_request(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_id: int,
) -> InitiativeJoinRequest | None:
    """The caller's live request for one initiative, if they have one."""
    result = await session.exec(
        select(InitiativeJoinRequest).where(
            InitiativeJoinRequest.initiative_id == initiative_id,
            InitiativeJoinRequest.user_id == user_id,
            InitiativeJoinRequest.status == JoinRequestStatus.pending.value,
        )
    )
    return result.one_or_none()


async def get_join_request(
    session: AsyncSession,
    *,
    request_id: int,
    initiative_id: int,
) -> InitiativeJoinRequest | None:
    """One request by id, scoped to the initiative it must belong to."""
    result = await session.exec(
        select(InitiativeJoinRequest).where(
            InitiativeJoinRequest.id == request_id,
            InitiativeJoinRequest.initiative_id == initiative_id,
        )
    )
    return result.one_or_none()


async def create_join_request(
    session: AsyncSession,
    *,
    initiative: Initiative,
    user_id: int,
    message: str | None = None,
) -> tuple[InitiativeJoinRequest, bool]:
    """Record ``user_id`` knocking on ``initiative``.

    Returns ``(row, created)``. A live request already on file is returned
    untouched with ``created=False`` — the caller turns that into the conflict
    answer. A *denied* request never blocks a new one: only the pending row is
    unique (``uq_initiative_join_requests_pending``), so asking again after a
    refusal is allowed and the refusals stay on file as history.

    Flush-only; the caller owns the transaction. The policy check is the
    caller's (:func:`is_requestable`).
    """
    existing = await get_pending_join_request(
        session, initiative_id=initiative.id, user_id=user_id
    )
    if existing is not None:
        return existing, False

    request = InitiativeJoinRequest(
        initiative_id=initiative.id,
        user_id=user_id,
        status=JoinRequestStatus.pending.value,
        message=message,
    )
    # Two overlapping knocks both clear the lookup above, and the partial unique
    # index then rejects the loser. The savepoint absorbs that so the loser
    # reads back the winner's row and gets the same deterministic answer as a
    # plain repeat, rather than a failed transaction.
    try:
        async with session.begin_nested():
            session.add(request)
            await session.flush()
    except IntegrityError:
        existing = await get_pending_join_request(
            session, initiative_id=initiative.id, user_id=user_id
        )
        if existing is None:
            raise
        return existing, False
    return request, True


class JoinRequestAlreadyResolved(Exception):
    """Another manager settled the request first.

    Raised when the atomic claim in :func:`resolve_join_request` matches no
    row, which can only mean the status moved off ``pending`` between the
    caller's check and its write.
    """


async def resolve_join_request(
    session: AsyncSession,
    *,
    request: InitiativeJoinRequest,
    resolver_id: int,
    approved: bool,
) -> InitiativeMember | None:
    """Settle a pending request, creating the membership row on approval.

    Approval routes through :func:`self_join`, so an approved requester lands on
    exactly the row every other join path produces — no managing provider —
    and someone who became a member by another route while the request sat in
    the queue is absorbed rather than colliding.

    The row is claimed before anything is granted: one UPDATE that fires only
    while the status is still ``pending``, so two managers answering at once
    cannot both write. The loser matches no row and raises
    :class:`JoinRequestAlreadyResolved`. Claiming first is what keeps an
    approval from creating a membership that a simultaneous denial then
    records as refused.

    Flush-only; the caller owns the transaction.
    """
    resolved = (
        JoinRequestStatus.approved.value if approved else JoinRequestStatus.denied.value
    )
    result = await session.exec(
        update(InitiativeJoinRequest)
        .where(
            InitiativeJoinRequest.id == request.id,
            InitiativeJoinRequest.status == JoinRequestStatus.pending.value,
        )
        .values(
            status=resolved,
            resolved_at=datetime.now(timezone.utc),
            resolved_by=resolver_id,
        )
    )
    if result.rowcount == 0:
        raise JoinRequestAlreadyResolved()
    # Keep the in-memory row in step with the write, since the caller returns it.
    await session.refresh(request)

    membership: InitiativeMember | None = None
    if approved:
        initiative = await session.get(Initiative, request.initiative_id)
        if initiative is None:
            raise ValueError(InitiativeMessages.NOT_FOUND)
        membership = await self_join(
            session,
            initiative=initiative,
            user_id=request.user_id,
            actor_user_id=resolver_id,
            via="join_request",
        )
    await session.flush()
    return membership


async def manager_user_ids(
    session: AsyncSession,
    *,
    initiative_id: int,
) -> list[int]:
    """Members of ``initiative_id`` holding a manager role — the people who can
    answer a join request, and therefore the people it notifies."""
    result = await session.exec(
        select(InitiativeMember.user_id)
        .join(InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id)
        .where(
            InitiativeMember.initiative_id == initiative_id,
            InitiativeRoleModel.is_manager.is_(True),
        )
    )
    return list(result.all())


async def list_join_requests(
    session: AsyncSession,
    *,
    initiative_id: int,
    status: str | None = JoinRequestStatus.pending.value,
    user_id: int | None = None,
) -> list[InitiativeJoinRequestRead]:
    """An initiative's join-request queue, newest knock first.

    ``status`` defaults to the pending queue — the only rows anyone can act on;
    pass ``None`` for the full history. ``user_id`` narrows the result to one
    requester, which is how a requester reads their own rows without being able
    to read anyone else's.

    Each row carries ``prior_denials``: how many times this initiative has
    already turned this person away. A denied requester may ask again, so the
    repeat has to be visible to whoever is deciding.
    """
    prior = aliased(InitiativeJoinRequest, name="prior_request")
    prior_denials = (
        select(func.count())
        .select_from(prior)
        .where(
            prior.initiative_id == initiative_id,
            prior.user_id == InitiativeJoinRequest.user_id,
            prior.status == JoinRequestStatus.denied.value,
            # Strictly prior: a denied row read back from the history does not
            # count itself.
            prior.id != InitiativeJoinRequest.id,
        )
        .scalar_subquery()
    )
    statement = (
        select(InitiativeJoinRequest, MemberProfile, prior_denials)
        .join(MemberProfile, MemberProfile.id == InitiativeJoinRequest.user_id)
        .where(InitiativeJoinRequest.initiative_id == initiative_id)
        .order_by(
            InitiativeJoinRequest.created_at.desc(), InitiativeJoinRequest.id.desc()
        )
    )
    if status is not None:
        statement = statement.where(InitiativeJoinRequest.status == status)
    if user_id is not None:
        statement = statement.where(InitiativeJoinRequest.user_id == user_id)

    rows = (await session.exec(statement)).all()
    return [
        InitiativeJoinRequestRead(
            id=request.id,
            initiative_id=request.initiative_id,
            user=UserSummary.model_validate(user),
            status=request.status,
            message=request.message,
            created_at=request.created_at,
            resolved_at=request.resolved_at,
            resolved_by=request.resolved_by,
            prior_denials=denials,
        )
        for request, user, denials in rows
    ]


async def keeps_content_in(
    session: AsyncSession, initiative_ids: Iterable[int | None]
) -> bool:
    """Whether any of ``initiative_ids`` keeps its content in
    (``Initiative.keep_content_in``)."""
    ids = {initiative_id for initiative_id in initiative_ids if initiative_id}
    if not ids:
        return False
    found = await session.exec(
        select(Initiative.id)
        .where(ids_in(Initiative.id, ids), Initiative.keep_content_in)
        .limit(1)
    )
    return found.first() is not None


def validate_join_settings(
    initiative: Initiative,
    *,
    join_policy: str | None,
    auto_join: bool | None,
) -> None:
    """Validate a ``join_policy`` / ``auto_join`` change as one pair.

    The two are coupled by ``ck_initiatives_auto_join_open``, and a PATCH may
    move either or both, so the rule is checked against the *resulting* state
    rather than each field alone. Turning a policy away from ``open`` while
    auto-join is on is rejected rather than silently clearing auto-join —
    dropping a guild-wide onboarding setting as a side effect of an unrelated
    edit would be worse than an error.

    Raises ``ValueError`` carrying the message constant when the pair is
    incoherent; returns None when it is fine.
    """
    resulting_policy = (
        join_policy if join_policy is not None else initiative.join_policy
    )
    resulting_auto_join = auto_join if auto_join is not None else initiative.auto_join
    if resulting_auto_join and resulting_policy != InitiativeJoinPolicy.open.value:
        raise ValueError(InitiativeMessages.AUTO_JOIN_REQUIRES_OPEN)


async def create_imported_initiative(
    session: AsyncSession,
    *,
    guild_id: int,
    name: str,
    description: str | None,
    color: str | None,
    tool_flags: dict[str, bool],
    manager_id: int,
    join_policy: InitiativeJoinPolicy | None = None,
    member_ids: Sequence[int] = (),
) -> Initiative:
    """Create an initiative for a backup import: the exact create-endpoint
    sequence (row → built-in roles → creator as PM), with the name suffixed
    on collision (always-create policy) instead of 409ing, and the tool
    master switches and join policy taken from the backup manifest.
    ``member_ids`` join it with the built-in member role. Flush-only — the
    backup orchestrator owns its per-chunk transaction."""
    from app.core.tools import DEFAULT_ENABLED_TOOLS, Tool
    from app.services.import_engine.common import unique_name

    existing = {row for row in (await session.exec(select(Initiative.name))).all()}
    initiative = Initiative(
        name=unique_name(existing, name),
        description=description,
        color=color,
        join_policy=(join_policy or InitiativeJoinPolicy.private).value,
        **{
            # A manifest that says nothing about a tool falls back to that
            # tool's own default rather than to off: a backup written before
            # projects and files had switches names no state for them, and
            # restoring it must not produce an initiative with neither.
            t.view_permission: bool(
                tool_flags.get(t.view_permission, t in DEFAULT_ENABLED_TOOLS)
            )
            for t in Tool
        },
    )
    session.add(initiative)
    await session.flush()

    roles = await create_builtin_roles(session, initiative_id=initiative.id)
    session.add(
        InitiativeMember(
            initiative_id=initiative.id,
            user_id=manager_id,
            role_id=(
                await creator_role(
                    session, guild_id=guild_id, user_id=manager_id, roles=roles
                )
            ).id,
        )
    )
    session.add_all(
        InitiativeMember(
            initiative_id=initiative.id,
            user_id=member_id,
            role_id=roles["member"].id,
        )
        for member_id in member_ids
        if member_id != manager_id
    )
    await session.flush()
    return initiative


def _member_key(key: PermissionKey) -> str:
    return f"{INITIATIVE_MEMBER_PREFIX}{key.value}"


async def _community_rows(session: AsyncSession) -> dict[str, InitiativeRule]:
    """The community's own ``initiative_rules`` rows, by key: the ones with no
    initiative."""
    rows = await session.exec(
        select(InitiativeRule).where(
            InitiativeRule.initiative_id.is_(None)  # type: ignore[union-attr]
        )
    )
    return {row.key: row for row in rows.all()}


async def community_defaults(session: AsyncSession) -> InitiativeDefaultsRead:
    """What the community sets for every initiative in it."""
    rows = await _community_rows(session)
    custom_roles = rows.get(INITIATIVE_CUSTOM_ROLES)
    return InitiativeDefaultsRead(
        tools={
            tool: rows[key].enabled
            for tool, key in INITIATIVE_TOOL_KEYS.items()
            if key in rows
        },
        member_permissions={
            key: rows[_member_key(key)].enabled
            for key in PermissionKey
            if _member_key(key) in rows
        },
        custom_roles=custom_roles is None or custom_roles.enabled,
    )


async def set_community_defaults(
    session: AsyncSession,
    *,
    guild_id: int,
    changes: InitiativeDefaultsUpdate,
    actor_user_id: int,
) -> InitiativeDefaultsRead:
    """Change what the community sets for every initiative. Each initiative
    keeps its own values beneath, which apply again where the community hands
    a tool or a permission back. Written on the admin's own session: the
    community's rows have no initiative, so no manager's policy admits them."""
    before = await community_defaults(session)
    stored: dict[str, bool | None] = {
        **{INITIATIVE_TOOL_KEYS[tool]: on for tool, on in changes.tools.items()},
        **{_member_key(key): on for key, on in changes.member_permissions.items()},
    }
    if changes.custom_roles is not None:
        # Allowed is the default, so it is no row.
        stored[INITIATIVE_CUSTOM_ROLES] = None if changes.custom_roles else False
    rows = await _community_rows(session)
    for key, value in stored.items():
        row = rows.get(key)
        if value is None:
            if row is not None:
                await session.delete(row)
        elif row is None:
            session.add(InitiativeRule(key=key, enabled=value))
        else:
            row.enabled = value
            session.add(row)
    await session.flush()

    after = await community_defaults(session)
    await audit_service.record_settings_change(
        session,
        guild_id=guild_id,
        actor_user_id=actor_user_id,
        area="initiative_defaults",
        before=before.model_dump(mode="json"),
        after=after.model_dump(mode="json"),
    )
    return after
