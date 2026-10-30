"""Initiative-level access helpers and the sharing pickers' roster queries.

What the database enforces is the guild schema's own policies and functions
(``app/db/authorization.py``); what a request holds is its standing
(``GuildContext``, built by the seam in ``app/api/deps``). This module keeps the
questions those two do not answer as a value: who manages an initiative, which
of its members a role permits, and the roster queries the sharing surfaces
list from.

The guild-level questions that used to live here — is this an admin, does
this account hold the seat, is there a membership row — are the standing's:
``GuildContext.is_admin``, ``.seat``, ``.reaches``.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import and_, func, or_
from sqlmodel import select

from app.models.tenant.initiative import (
    InitiativeMember,
    InitiativeRoleModel,
    InitiativeRule,
    PermissionKey,
    DEFAULT_PERMISSION_VALUES,
)
from app.models.platform.user import User

# Re-export the RLS context helper so callers can import from a single place.
from app.db.session import require_guild_context, set_rls_context  # noqa: F401
from app.db.authorization import standing_arg


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Initiative manager checks
# ---------------------------------------------------------------------------


async def is_initiative_manager(session: AsyncSession, *, initiative_id: int) -> bool:
    """Whether this request manages ``initiative_id``, by the standing.

    The seam computed ``app.manager_initiatives`` from the roster and the
    roles' rows when it routed the session; this reads that answer back rather
    than asking the rows again. Granted access manages nothing.
    """
    context = require_guild_context(session)
    return initiative_id in context.manager_initiatives


async def check_initiative_permission(
    session: AsyncSession,
    *,
    initiative_id: int,
    user: User | None,
    permission_key: PermissionKey,
) -> bool:
    """Whether ``user``'s role in the initiative permits ``permission_key``.

    ``None`` is an installed plug-in, whose standing carries the keys its scopes
    allow in the initiatives it is placed in.

    Asked of the schema's own ``initiative_role_permits`` — the function the
    content policies call — so the rule has one body: a manager holds every
    key, a stored row decides, and the key's documented default decides when
    there is none. It reads the standing the session was routed with, so it
    answers for the request's own account.
    """
    default = DEFAULT_PERMISSION_VALUES.get(permission_key, False)
    return bool(
        (
            await session.exec(
                select(
                    func.initiative_role_permits(
                        initiative_id,
                        user.id if user is not None else None,
                        permission_key.value,
                        default,
                        standing_arg(),
                    )
                )
            )
        ).one()
    )


def _role_permits(permission_key: PermissionKey):
    """Whether a role (``InitiativeRoleModel``, outer-joined to its row for
    ``permission_key``) grants the key — the same rule as
    :func:`check_initiative_permission`: a manager holds every key, a stored
    row decides, and the key's documented default decides when there is none."""
    default = DEFAULT_PERMISSION_VALUES.get(permission_key, False)
    return or_(
        InitiativeRoleModel.is_manager,
        func.coalesce(InitiativeRule.enabled, default),
    )


def _with_permission_row(statement, permission_key: PermissionKey):
    return statement.outerjoin(
        InitiativeRule,
        and_(
            InitiativeRule.initiative_role_id == InitiativeRoleModel.id,
            InitiativeRule.key == permission_key,
        ),
    )


async def members_permitted(
    session: AsyncSession,
    *,
    initiative_id: int,
    user_ids: set[int],
    permission_key: PermissionKey,
) -> set[int]:
    """Which of ``user_ids`` hold ``permission_key`` in ``initiative_id``.

    :func:`check_initiative_permission` asked about many people at once, so
    sharing can narrow a list of grantees without restating what a role
    grants. A member with no role holds nothing.
    """
    if not user_ids:
        return set()
    statement = _with_permission_row(
        select(InitiativeMember.user_id).join(
            InitiativeRoleModel, InitiativeRoleModel.id == InitiativeMember.role_id
        ),
        permission_key,
    ).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id.in_(list(user_ids)),
        _role_permits(permission_key),
    )
    return set((await session.exec(statement)).all())


async def roles_permitting(
    session: AsyncSession,
    *,
    initiative_id: int,
    role_ids: set[int],
    permission_key: PermissionKey,
) -> set[int]:
    """Which of ``role_ids`` grant ``permission_key`` — the role-shaped form of
    :func:`members_permitted`, for sharing addressed to a role."""
    if not role_ids:
        return set()
    statement = _with_permission_row(
        select(InitiativeRoleModel.id), permission_key
    ).where(
        InitiativeRoleModel.initiative_id == initiative_id,
        InitiativeRoleModel.id.in_(list(role_ids)),
        _role_permits(permission_key),
    )
    return set((await session.exec(statement)).all())
