"""Helpers for endpoints that aggregate guild-scoped data across guilds.

Under schema-per-guild a routed session only sees one guild's schema, so a
"global" list (the user's items across every guild they belong to) has to visit
each guild's schema in turn and merge the results. Per-schema ids collide across
guilds, so callers must keep each item's ``guild_id``, and each guild is
visited on a session of its own.

A paged list across guilds is :func:`page_across_guilds`: each guild answers
with its first rows in the list's order and how many it has, and the page is
cut from their merge.
"""

from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence, TypeVar

from sqlmodel import col, select

from app.services.membership import live_membership_clause
from app.services.platform import rules
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import auth_context
from app.db import cohorts
from app.db.guild_standing import GuildContext
from app.db.query import effective_page_size, paginate_sequence
from app.db.session import set_rls_context
from app.models.platform.guild import (
    LIVE_STATUS_VALUES,
    CommunityRole,
    Guild,
    GuildMembership,
)
from app.models.platform.user import User, UserStatus
from app.db.request_context import Platform, Unattributed

T = TypeVar("T")
R = TypeVar("R")

#: Where this session remembers each (user, guild)'s standing. On
#: ``session.info``, so its lifetime is the session's — i.e. the request's.
#: Keyed by user as well as guild because this function takes the user as an
#: argument: one session may legitimately gather for more than one of them, and
#: a guild-only key would hand the second the first's standing. The surface
#: (content or settings) is part of the key, since each establishes its own. A cached
#: context is never written on its own — it is re-applied through the same
#: routing-and-standing pair a first visit goes through, which is what keeps
#: the session and its standing naming one community.
_CONTEXT_CACHE_KEY = "cross_guild_contexts"


async def member_guild_ids(
    session: AsyncSession,
    user_id: int,
    *,
    restrict_to: Optional[Sequence[int]] = None,
    guests: bool = True,
) -> list[int]:
    """Guild ids the user belongs to, sorted (optionally intersected with
    ``restrict_to``). Routes to the user-only context so the user's own rows in
    the shared ``guild_memberships`` table are visible.

    Suspended guilds are excluded for every membership role: content access is
    cut for members AND guild admins alike (admins keep only the settings
    surface), so no cross-guild aggregate may surface a suspended guild's
    content — the ``/c/{community_id}`` choke point (``_load_guild_context``)
    refuses those guilds and this is its aggregate-path twin.

    A suspended *user* is excluded the same way, and for the same reason. They
    keep every membership, so the join below would otherwise walk all of them:
    the guild path answers such a caller with nothing, and being the twin of
    that path means answering the same.

    A guild that turned off this member's API access is excluded when the
    request is carrying a personal API key, which is the same twinning:
    ``/c/{community_id}`` refuses that caller, so an aggregate cannot be the
    way its content is read instead.
    A key limited to one guild reaches that guild alone, for the same reason.

    ``guests=False`` leaves out the guilds the user is a guest of, for a reader
    of what a guild offers its members rather than of what was shared with
    them."""
    await set_rls_context(session, Platform(user_id=user_id))
    conditions = [
        GuildMembership.user_id == user_id,
        live_membership_clause(),
        Guild.status.in_(LIVE_STATUS_VALUES),
        User.status != UserStatus.suspended,
    ]
    if not guests:
        conditions.append(GuildMembership.role != CommunityRole.guest)
    recorded = auth_context.current()
    if recorded.api_key_credential:
        conditions.append(
            rules.community_rule_sql(
                Guild.id, "api_keys", user_id=GuildMembership.user_id
            )
        )
    pinned = recorded.api_key_guild_id
    if pinned is not None:
        conditions.append(GuildMembership.guild_id == pinned)
    rows = await session.exec(
        select(GuildMembership.guild_id)
        .join(Guild, Guild.id == GuildMembership.guild_id)
        .join(User, User.id == GuildMembership.user_id)
        .where(*conditions)
    )
    ids = sorted(rows)
    if restrict_to is not None:
        allowed = set(restrict_to)
        ids = [gid for gid in ids if gid in allowed]
    return ids


async def gather_across_guilds(
    session: AsyncSession,
    readers: Mapping[int, Sequence[int]],
    fetch: Callable[[AsyncSession, int], Awaitable[list[T]]],
    *,
    on_behalf: bool = False,
    for_settings: bool = False,
    writes: bool = False,
) -> list[T]:
    """Enter each community as each of its readers, call
    ``fetch(session, guild_id)``, and concatenate the results.

    ``readers`` maps each reader's user id to the communities to read them in.
    Every community is visited once, on a session of its own from its cohort,
    and routed as each of its readers in turn; ``fetch`` reads who that is from
    the routing (``require_guild_context(session).user_id``). Ids are unique only
    within a schema, so callers keep each item's community beside it.

    Each reader enters through the **same seam** a ``/c/{community_id}``
    request goes through, so what these views show is what that request would
    show: the same lookup, the same refusals, and the same standing computed in
    the community's own schema, as the reader, on whichever pool the session
    came from. A community a reader cannot reach right now contributes nothing
    for them rather than raising.

    The caller's session is the ambient ``auth_context`` — its ``sat`` on a
    request path — so a policy-gated guild contributes exactly when that
    session satisfies its policy. ``on_behalf`` is a job acting as the people it
    reads for (``establish_guild_access``).

    ``for_settings`` enters each community on its configuration surface, as
    ``/c/{community_id}`` settings routes do (``establish_guild_access``'s
    ``for_settings``), for a read of what its administrator configures.

    ``session`` is a request-path session, which reads for its own account
    alone, or one from ``cohorts.system_session``. It stays where it is: each
    community gets a session of the same kind from its own cohort
    (``app.db.cohorts``), which is closed before the next one opens. It is
    read-only unless ``writes`` is set, in which case each reader's writes are
    committed once their ``fetch`` returns, a transaction of their own rather
    than the caller's."""
    wanted = {user_id: guild_ids for user_id, guild_ids in readers.items() if guild_ids}
    if not wanted:
        return []
    from app.api.deps import (
        GuildAccessError,
        apply_guild_session_context,
        establish_guild_access,
    )

    # One shared-table read for the readers' accounts before routing into any
    # schema: a request reads its own account under its own context, and a job
    # reads all of them in one statement.
    await set_rls_context(
        session,
        Platform(user_id=next(iter(wanted))) if len(wanted) == 1 else Unattributed(),
    )
    # A suspended account reaches no community, so there is nothing across them
    # to gather. Checked here rather than only in ``member_guild_ids`` because a
    # caller may assemble its own guild list and reach this directly.
    accounts = {
        user.id: user
        for user in (
            await session.exec(
                select(User).where(
                    col(User.id).in_(wanted), User.status != UserStatus.suspended
                )
            )
        ).all()
    }
    by_guild: dict[int, list[int]] = {}
    for user_id, guild_ids in wanted.items():
        if user_id in accounts:
            for guild_id in guild_ids:
                by_guild.setdefault(guild_id, []).append(user_id)

    contexts: dict[tuple[int, int, bool], GuildContext] = session.info.setdefault(
        _CONTEXT_CACHE_KEY, {}
    )
    satisfied = auth_context.current().satisfied_providers

    async def enter(routed: AsyncSession, user_id: int, guild_id: int) -> bool:
        """Route ``routed`` into ``guild_id`` as ``user_id``; False when this
        reader cannot reach it right now."""
        account = await routed.merge(accounts[user_id], load=False)
        key = (user_id, guild_id, for_settings)
        cached = contexts.get(key)
        try:
            if cached is None:
                contexts[key] = await establish_guild_access(
                    routed,
                    account,
                    guild_id,
                    satisfied_providers=satisfied,
                    on_behalf=on_behalf,
                    for_settings=for_settings,
                )
            else:
                # The lookup's answer is the same one it gave a moment ago in
                # this request; what has to happen again is the routing and the
                # standing, which is the pair this applies.
                await apply_guild_session_context(
                    routed, account, cached, satisfied=satisfied, on_behalf=on_behalf
                )
        except GuildAccessError:
            # A community this caller cannot reach right now contributes
            # nothing, exactly as its own ``/c/{community_id}`` requests would.
            return False
        return True

    results: list[T] = []
    # Each community is read on a session from its own cohort's pool, so the
    # caller's connection never opens another cohort's schema.
    for guild_id, user_ids in sorted(by_guild.items()):
        async with cohorts.community_session(
            session, guild_id, read_only=not writes
        ) as routed:
            for user_id in user_ids:
                # Nothing one reader loaded is handed to the next from the
                # identity map: each reads afresh, as themselves.
                routed.expunge_all()
                if await enter(routed, user_id, guild_id):
                    results.extend(await fetch(routed, guild_id))
                    if writes:
                        await routed.commit()
    return results


async def page_across_guilds(
    session: AsyncSession,
    user_id: int,
    guild_ids: Sequence[int],
    fetch: Callable[[AsyncSession, int, int], Awaitable[tuple[Sequence[R], int]]],
    *,
    order: Callable[[R], tuple[Any, Any]],
    descending: bool,
    page: int,
    page_size: int,
) -> tuple[list[tuple[int, R]], int]:
    """One page of a list ordered across guilds, as ``(guild_id, row)`` pairs,
    and the list's total.

    ``fetch(session, guild_id, limit)`` answers with the guild's first ``limit``
    rows in the list's order and how many rows it has in all. ``order(row)`` is
    that order as ``(key, identity)``: ``key`` ascending, or descending when
    ``descending`` is set, then ``identity`` descending — the ORDER BY the
    fetch ran. Across guilds the guild id breaks a tie. No page reaches past a
    guild's first ``page * page_size`` rows, so none is read further, and the
    merge keeps no more than that many between guilds.
    """
    limit = max(page, 1) * effective_page_size(page_size)
    total = 0
    merged: list[tuple[int, R]] = []

    async def _fetch(routed: AsyncSession, guild_id: int) -> list:
        nonlocal total, merged
        rows, count = await fetch(routed, guild_id, limit)
        total += count
        merged += [(guild_id, row) for row in rows]
        merged.sort(key=lambda pair: (order(pair[1])[1], pair[0]), reverse=True)
        merged.sort(key=lambda pair: order(pair[1])[0], reverse=descending)
        del merged[limit:]
        return []

    await gather_across_guilds(session, {user_id: guild_ids}, _fetch)
    return paginate_sequence(merged, page, page_size), total
