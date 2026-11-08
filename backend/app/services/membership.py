"""Shared guild- and initiative-membership checks.

Initiative scoping has **one** definition: the ``initiative_access`` SQL
function (initiative member OR guild admin OR PAM grant, read from the request
GUCs). The guild-schema RLS policies call it, and ``initiative_scope_clause``
here calls the *same* function — for the tables the policies deliberately do
not cover, which is the structural initiative set (``initiatives`` itself and
its roster): those are guild-scoped by the schema boundary, so this clause is
their only scope gate rather than a second opinion on one.

This module also provides a batch guild-role lookup (resolve the role for
many users in one round trip instead of a per-user loop). ``guild_memberships``
is a shared/public table, so it works on any session, routed or not; the scope
clause needs a session already routed into the right guild (``RLSSessionDep``
or ``set_rls_context``), exactly like any other guild-scoped query.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.authorization import standing_arg
from app.models.platform.guild import CommunityRole, GuildMembership


def live_membership_clause(membership: Any = GuildMembership) -> ColumnElement[bool]:
    """``authorization.live_membership`` for a query over ``GuildMembership``
    (or an alias of it): a member's row always, and a guest's while it admits
    them."""
    return or_(
        membership.guest_until.is_(None),
        func.guest_membership_live(membership.guest_until, membership.role),
    )


# ---------------------------------------------------------------------------
# Clause builders — compose into WHERE conditions of any statement
# ---------------------------------------------------------------------------


def initiative_scope_clause(
    user_id: int,
    initiative_id_col: ColumnElement[int] | int,
    *,
    need_write: bool = False,
) -> ColumnElement[bool]:
    """Initiative-scope predicate for embedding in any SELECT — the **single
    source of truth**: it defers to the ``initiative_access`` SQL function
    (initiative member OR guild admin OR PAM grant, read from the request GUCs),
    the exact same predicate the guild-schema RLS policies use. There is one rule,
    in one place, called by both the database and the app.

    Because the function reads the request's standing (``app.guild_admin``,
    ``app.member_initiatives``) and ``app.pam_*`` from the
    session GUCs, the guild-admin and PAM legs come "for free" on any routed
    session (``RLSSessionDep`` or a per-guild ``set_rls_context``). ``need_write``
    selects the read vs. write PAM leg.
    """
    return func.initiative_access(
        initiative_id_col, user_id, need_write, standing_arg()
    )


# ---------------------------------------------------------------------------
# Batch lookups — one query regardless of how many users
# ---------------------------------------------------------------------------


async def guild_role_map(
    session: AsyncSession,
    guild_id: int,
    user_ids: Iterable[int],
) -> dict[int, CommunityRole]:
    """Guild role per user for a batch of users in one query. Users without a
    membership are absent from the result."""
    ids = tuple(set(user_ids))
    if not ids:
        return {}
    rows = await session.exec(
        select(GuildMembership.user_id, GuildMembership.role).where(
            GuildMembership.guild_id == guild_id,
            GuildMembership.user_id.in_(ids),
        )
    )
    return {user_id: role for user_id, role in rows.all()}
