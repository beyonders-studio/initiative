"""Server-side session lifecycle for the new login model (auth rewrite, Phase 0).

This is the substrate that makes the stateless access token revocable.
One ``auth_sessions`` row = one
login; each ``/auth/refresh`` **rotates** it — mints a fresh row pointing at the
one it replaces (``parent_id`` chain) and single-use-revokes the old one. Reuse
of an already-spent refresh token is treated as **theft** and kills the whole
chain, including its still-live tail.

**Runs on the system engine (``app_admin``).** Session validation is a pre-auth
lookup *by refresh-token hash* — the user is unknown until it resolves — so it
structurally cannot run under own-row RLS. The request path holds no grant on
``auth_sessions`` at all (migration 20260706_0132); these functions take the
system session, like ``services.platform.access_grants``.

Nothing calls this yet — the ``/auth/refresh`` endpoint + dual-verify wiring land
in the next slice. This PR is the tested logic layer only (additive-first).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from sqlalchemy import text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.clock import utcnow
from app.core.config import settings
from app.models.platform.auth_session import AuthSession
from app.services.auth import session_lifetime

logger = logging.getLogger(__name__)

__all__ = [
    "SESSION_PURGE_POLL_SECONDS",
    "SESSION_RETENTION_DAYS",
    "IssuedSession",
    "LiveSession",
    "RefreshOutcome",
    "RotationResult",
    "create_session",
    "delete_all_for_user",
    "follow_devices",
    "get_live_session_by_refresh_token",
    "latest_of_install",
    "list_live_for_user",
    "live_chain_tips",
    "process_dead_session_purge",
    "purge_dead_sessions",
    "revoke_all_for_user",
    "revoke_chain",
    "revoke_session",
    "rotate_session",
]

# 256 bits of entropy — infeasible to guess, so the hash (not a slow KDF) is the
# only thing that needs storing.
_REFRESH_TOKEN_BYTES = 32

#: How long a session row outlives its own usefulness. A row carries a user
#: agent, an IP and a device label for the "your active sessions" screen; once
#: the session can no longer be used, that is all it carries, so it is kept for
#: a window and then removed.
SESSION_RETENTION_DAYS = 30

#: ``auth_sessions`` is app_admin-only, so the sweep runs on SystemSessionLocal
#: with no guild routing — the same shape as the expired-token purge.
SESSION_PURGE_POLL_SECONDS = 3600


def _capped(expires: datetime, chain_ends: datetime | None) -> datetime:
    """An idle window never outlives the chain it belongs to."""
    return expires if chain_ends is None else min(expires, chain_ends)


def _generate_refresh_token() -> str:
    """A fresh opaque refresh token (URL-safe, never persisted in the clear)."""
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


#: How long a device's session stands unused: the phone and desktop apps stay
#: signed in where a browser would not.
DEVICE_REFRESH_TTL = timedelta(days=90)


async def _narrowed_ttl(
    session: AsyncSession,
    *,
    user_id: int,
    requested: timedelta | None,
    device: bool,
) -> timedelta:
    """How long the refresh row may stand.

    The deployment's own window, or the device window, unless the caller named
    one, narrowed by what a community held to the compliance standard asks of
    its members. Resolved
    here rather than by each caller: a rotation learns whose session it is
    from the token it was handed, so there is one place that knows.
    """
    ttl = requested or (
        DEVICE_REFRESH_TTL if device else timedelta(days=settings.AUTH_REFRESH_TTL_DAYS)
    )
    idle = await session_lifetime.idle_window(session, user_id=user_id)
    return min(ttl, idle) if idle is not None else ttl


def _hash_refresh_token(raw: str) -> bytes:
    """SHA-256 of the raw token — *deterministic* so a presented token maps to
    exactly one session by an indexed lookup. The token is 256-bit random, so a
    plain fast hash is safe here (a salted/slow KDF would defeat the O(1) lookup
    that ``uq_auth_sessions_refresh_token_hash`` exists to serve). The raw token
    is returned to the client once and never stored."""
    return hashlib.sha256(raw.encode("utf-8")).digest()


@dataclass(frozen=True)
class IssuedSession:
    """A newly created/rotated session plus its raw refresh token.

    ``refresh_token`` is the *only* time the raw token exists — hand it to the
    client (cookie / secure storage) and drop it; only its hash is persisted.
    """

    session: AuthSession
    refresh_token: str


class RefreshOutcome(str, Enum):
    """The result of a rotation attempt. The string values double as machine-
    readable codes the endpoint maps to an HTTP status + localized message."""

    ROTATED = "rotated"
    UNKNOWN = "unknown_refresh_token"
    EXPIRED = "refresh_token_expired"
    REUSED = "refresh_token_reused"


@dataclass(frozen=True)
class RotationResult:
    """Outcome of :func:`rotate_session`.

    ``rotate_session`` **returns** this rather than raising, deliberately: on
    ``REUSED`` it has written a theft-revocation to the caller's session, and an
    exception there would let a conventional ``try/commit … except/rollback``
    handler silently discard that security response. Returning keeps the outcome
    on the caller's normal control flow — a single commit persists whichever
    write happened (the rotation on ``ROTATED``, the chain kill on ``REUSED``).
    """

    outcome: RefreshOutcome
    issued: IssuedSession | None = None  # present iff ``outcome is ROTATED``
    #: Whose session the token belonged to. Set whenever the token resolved to
    #: a row, so a ``REUSED`` rejection — where there is no ``issued`` — can
    #: still say whose chain was killed. ``None`` for a token that matched
    #: nothing at all.
    user_id: int | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is RefreshOutcome.ROTATED


# Revoke every session in a token's rotation chain, in both directions, given any
# member id. On reuse the live continuation is a *descendant* of the replayed
# node (ancestors are already revoked), but we walk both ways for defense in
# depth. The graph is a strict in-tree — ``parent_id`` always points at an older,
# pre-existing row, and ``ck_auth_sessions_parent_not_self`` blocks the only
# reachable self-loop — so the recursion terminates.
_REVOKE_CHAIN_SQL = text(
    """
    WITH RECURSIVE
    ancestors AS (
        SELECT id, parent_id FROM auth_sessions WHERE id = :sid
        UNION
        SELECT s.id, s.parent_id
        FROM auth_sessions s JOIN ancestors a ON s.id = a.parent_id
    ),
    descendants AS (
        SELECT id, parent_id FROM auth_sessions WHERE id = :sid
        UNION
        SELECT s.id, s.parent_id
        FROM auth_sessions s JOIN descendants d ON s.parent_id = d.id
    )
    UPDATE auth_sessions SET revoked_at = :now
    WHERE revoked_at IS NULL
      AND id IN (SELECT id FROM ancestors UNION SELECT id FROM descendants)
    RETURNING id
    """
)


async def create_session(
    session: AsyncSession,
    *,
    user_id: int,
    amr: list[str],
    satisfied_providers: list[int],
    provider_auth: dict[str, Any] | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
    device_name: str | None = None,
    install_id: uuid.UUID | None = None,
    refresh_ttl: timedelta | None = None,
    now: datetime | None = None,
    ends_by: datetime | None = None,
) -> IssuedSession:
    """Open a new session for ``user_id`` and mint its first refresh token.

    ``amr`` / ``satisfied_providers`` record which factors/providers this login
    satisfied — they are mirrored into the access token so the per-guild
    auth-policy gate and step-up read them locally. ``provider_auth`` carries
    each satisfied provider's own account of its authentication event (see
    ``services.auth.assurance``).

    **Opening a session calls off a pending deletion.** Somebody whose account
    is waiting out its erasure window has just proved they are its holder and
    that they want it, which is the whole of what cancelling asks for. It
    happens here rather than at each of the ways in, because every one of them
    ends at this function and a rule spread over eight of them is a rule with
    seven places to forget it. It lands in the same transaction as the session,
    so a sign-in that fails leaves the deletion exactly where it was.

    ``ends_by``, when given, is the latest the whole chain may last.
    """
    issued = now or utcnow()
    ttl = await _narrowed_ttl(
        session,
        user_id=user_id,
        requested=refresh_ttl,
        device=install_id is not None,
    )
    # The end of the whole chain, read once here and carried forward from now
    # on. ``expires_at`` is the idle window and never outlives it.
    chain_ends = await session_lifetime.chain_deadline(
        session, user_id=user_id, issued=issued
    )
    if ends_by is not None:
        chain_ends = min(chain_ends, ends_by) if chain_ends else ends_by
    raw = _generate_refresh_token()
    row = AuthSession(
        user_id=user_id,
        refresh_token_hash=_hash_refresh_token(raw),
        amr=list(amr),
        satisfied_providers=list(satisfied_providers),
        provider_auth=dict(provider_auth or {}),
        created_at=issued,
        chain_expires_at=chain_ends,
        expires_at=_capped(issued + ttl, chain_ends),
        user_agent=user_agent,
        ip=ip,
        device_name=device_name,
        install_id=install_id,
    )
    session.add(row)
    await session.flush()
    # Imported here: ``users`` reaches back into the auth package, and the two
    # would import each other at module scope.
    from app.services.platform import users as users_service

    await users_service.cancel_account_deletion(
        session, user_id, actor_user_id=user_id, via="sign_in"
    )
    return IssuedSession(session=row, refresh_token=raw)


async def rotate_session(
    session: AsyncSession,
    *,
    raw_refresh_token: str,
    amr: list[str] | None = None,
    satisfied_providers: list[int] | None = None,
    provider_auth: dict[str, Any] | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
    device_name: str | None = None,
    refresh_ttl: timedelta | None = None,
    idle: timedelta = timedelta(0),
    now: datetime | None = None,
) -> RotationResult:
    """Single-use rotate: spend the presented refresh token, mint its successor.

    Carries ``amr``/``satisfied_providers``/``provider_auth`` (and device
    metadata) forward from the parent unless overridden — a step-up rotation
    passes the widened set.

    ``idle`` is how long ago the person last did something, as the client
    reports it. The idle window runs from then, not from the renewal, so a
    client renewing on its own keeps the session no longer than the person's
    last input allows. A session whose window has already run out from there
    is ended, and answers ``EXPIRED``.

    **Returns** a :class:`RotationResult` (never raises for a bad token) —
    ``ROTATED`` carries the new :class:`IssuedSession`; ``UNKNOWN``/``EXPIRED``/
    ``REUSED`` are rejections. On ``REUSED`` the whole chain has been revoked on
    ``session`` (theft response). Returning rather than raising is the point: the
    caller commits on its normal path, so one commit durably persists whichever
    write occurred and a rollback-on-exception handler can't drop the chain kill.

    **Caller contract:** commit ``session`` before acting on the outcome —
    ``rotate → commit → branch`` — so both the rotation and the theft-revocation
    are persisted regardless of how the request ends.
    """
    issued = now or utcnow()
    presented_hash = _hash_refresh_token(raw_refresh_token)

    row = (
        await session.exec(
            select(AuthSession).where(AuthSession.refresh_token_hash == presented_hash)
        )
    ).one_or_none()
    if row is None:
        return RotationResult(RefreshOutcome.UNKNOWN)

    # Already spent (rotated or explicitly revoked) ⇒ replay of a dead token.
    if row.revoked_at is not None:
        await revoke_chain(session, session_id=row.id, now=issued)
        return RotationResult(RefreshOutcome.REUSED, user_id=row.user_id)

    if row.expires_at <= issued:
        return RotationResult(RefreshOutcome.EXPIRED, user_id=row.user_id)

    # The chain's own end, which no rotation moves. Reached, the answer is a
    # fresh sign-in rather than another renewal.
    if row.chain_expires_at is not None and row.chain_expires_at <= issued:
        return RotationResult(RefreshOutcome.EXPIRED, user_id=row.user_id)

    # Whose session this is only becomes known here, from the token that was
    # presented, so the window it may stand for is worked out now rather than
    # by a caller that could not have known.
    ttl = await _narrowed_ttl(
        session,
        user_id=row.user_id,
        requested=refresh_ttl,
        device=row.install_id is not None,
    )
    if idle >= ttl:
        # Nobody has been here for the whole window. Ended rather than left to
        # expire, so a later renewal cannot take it up again.
        await revoke_session(session, session_id=row.id, now=issued)
        return RotationResult(RefreshOutcome.EXPIRED, user_id=row.user_id)
    active_at = issued - idle

    # Atomic single-use claim: only one caller can flip revoked_at NULL→now, so
    # two concurrent refreshes with the same token can't both mint a child.
    claimed = (
        await session.exec(
            text(
                "UPDATE auth_sessions SET revoked_at = :now, last_used_at = :now "
                "WHERE id = :id AND revoked_at IS NULL RETURNING id"
            ),
            params={"now": issued, "id": row.id},
        )
    ).first()
    if claimed is None:
        # Lost the race to a concurrent rotation — treated as reuse.
        await revoke_chain(session, session_id=row.id, now=issued)
        return RotationResult(RefreshOutcome.REUSED, user_id=row.user_id)
    # Keep the in-session parent honest (the raw UPDATE bypassed the ORM).
    await session.refresh(row)

    raw = _generate_refresh_token()
    child = AuthSession(
        user_id=row.user_id,
        refresh_token_hash=_hash_refresh_token(raw),
        amr=list(amr) if amr is not None else list(row.amr),
        satisfied_providers=(
            list(satisfied_providers)
            if satisfied_providers is not None
            else list(row.satisfied_providers)
        ),
        provider_auth=(
            dict(provider_auth)
            if provider_auth is not None
            else dict(row.provider_auth)
        ),
        parent_id=row.id,
        created_at=issued,
        chain_expires_at=row.chain_expires_at,
        expires_at=_capped(active_at + ttl, row.chain_expires_at),
        user_agent=user_agent if user_agent is not None else row.user_agent,
        ip=ip if ip is not None else row.ip,
        device_name=device_name if device_name is not None else row.device_name,
        install_id=row.install_id,
        continues_since=row.continues_since,
    )
    session.add(child)
    await session.flush()
    await follow_devices(session, from_id=row.id, to_id=child.id)
    return RotationResult(
        RefreshOutcome.ROTATED,
        issued=IssuedSession(session=child, refresh_token=raw),
    )


async def follow_devices(
    session: AsyncSession, *, from_id: uuid.UUID, to_id: uuid.UUID
) -> None:
    """Move what a device registered under one session to the session taking
    its place: its push registrations and its message key store.

    Called wherever a session is succeeded — a renewal, a step-up, a
    replacement — so a device's push row and key store go on naming the same
    live sign-in, which is how a message finds the phone that can read it. Does
    not commit: it lands with the session change.
    """
    # Imported here: both reach back into the auth package.
    from app.services.platform import dm_transport, push_tokens

    await push_tokens.follow_session(session, from_id=from_id, to_id=to_id)
    await dm_transport.follow_session(session, from_id=from_id, to_id=to_id)


async def latest_of_install(
    session: AsyncSession, *, user_id: int, install_id: uuid.UUID
) -> uuid.UUID | None:
    """The newest session one installed copy of the app holds for this account,
    live or not: where its key store and push registration were last left."""
    return (
        await session.exec(
            select(AuthSession.id)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.install_id == install_id,
            )
            .order_by(col(AuthSession.created_at).desc())
            .limit(1)
        )
    ).first()


async def get_live_session_by_refresh_token(
    session: AsyncSession,
    raw_refresh_token: str,
    *,
    now: datetime | None = None,
) -> AuthSession | None:
    """The live (unrevoked, unexpired) session a presented refresh token
    belongs to, or ``None`` — a read-only lookup with none of ``rotate``'s
    side effects. Used by a completing provider login to carry the current
    session's satisfied set forward into the replacement session."""
    row = (
        await session.exec(
            select(AuthSession).where(
                AuthSession.refresh_token_hash == _hash_refresh_token(raw_refresh_token)
            )
        )
    ).one_or_none()
    current = now or utcnow()
    if row is None or row.revoked_at is not None or row.expires_at <= current:
        return None
    return row


#: Every live session for one account, each with the moment its sign-in
#: happened rather than the moment it last renewed.
#
# A refresh mints a new row and revokes the one it replaces, so the live rows
# are already one per sign-in — the recursion is only there to walk each one
# back to the sign-in it descends from. Without that, a browser left open for a
# month reads as signed in fifteen minutes ago, which is when it last renewed.
#
# ``purge_dead_sessions`` eventually removes the spent ancestors, so a very old
# chain reports the oldest row still kept. That is the retention window, and it
# is the right answer to give once the earlier rows are gone.
_LIVE_SESSIONS_SQL = text(
    """
    WITH RECURSIVE live AS (
        SELECT
            id, parent_id, created_at, last_used_at, user_agent, ip, device_name,
            install_id
        FROM auth_sessions
        WHERE user_id = :uid AND revoked_at IS NULL AND expires_at > :now
    ),
    chain AS (
        SELECT id, parent_id, created_at, id AS tip FROM live
        UNION ALL
        SELECT s.id, s.parent_id, s.created_at, c.tip
        FROM auth_sessions s JOIN chain c ON s.id = c.parent_id
    ),
    roots AS (
        SELECT tip, MIN(created_at) AS started_at FROM chain GROUP BY tip
    )
    SELECT
        live.id,
        roots.started_at,
        live.last_used_at,
        live.user_agent,
        host(live.ip) AS ip,
        live.device_name,
        live.install_id IS NOT NULL AS device
    FROM live JOIN roots ON roots.tip = live.id
    ORDER BY COALESCE(live.last_used_at, roots.started_at) DESC
    """
)


@dataclass(frozen=True)
class LiveSession:
    """One place an account is signed in, as the account's own list shows it.

    Carries nothing secret: the refresh-token hash stays in the table this was
    read from.
    """

    id: uuid.UUID
    started_at: datetime
    last_used_at: datetime | None
    user_agent: str | None
    ip: str | None
    device_name: str | None
    #: Opened by the phone or desktop app.
    device: bool


async def list_live_for_user(
    session: AsyncSession, *, user_id: int, now: datetime | None = None
) -> list[LiveSession]:
    """Every session this account can still use, most recently active first."""
    connection = await session.connection()
    result = await connection.execute(
        _LIVE_SESSIONS_SQL, {"uid": user_id, "now": now or utcnow()}
    )
    return [LiveSession(**row) for row in result.mappings()]


#: For each session id given, the live row its rotation chain has reached.
#
# A refresh spends the row it rotates and mints a child, so a sign-in that
# named row A an hour ago is row C now. The walk goes forward from each given
# row through spent ones only and stops at the first live one; a chain ended
# by ``revoke_chain`` or ``revoke_all_for_user`` has no live row to stop at,
# and one left alone past its expiry has none either. A caller that keeps the
# answer and asks from there next time walks one or two rows per ask.
_LIVE_CHAIN_TIPS_SQL = text(
    """
    WITH RECURSIVE walk AS (
        SELECT id AS origin, id, revoked_at, expires_at
        FROM auth_sessions
        WHERE id = ANY(CAST(:ids AS uuid[]))
        UNION ALL
        SELECT w.origin, s.id, s.revoked_at, s.expires_at
        FROM walk w JOIN auth_sessions s ON s.parent_id = w.id
        WHERE w.revoked_at IS NOT NULL
    )
    SELECT DISTINCT ON (origin) origin, id
    FROM walk
    WHERE revoked_at IS NULL AND expires_at > :now
    ORDER BY origin, expires_at DESC
    """
)


async def live_chain_tips(
    session: AsyncSession,
    *,
    session_ids: Collection[uuid.UUID],
    now: datetime | None = None,
) -> dict[uuid.UUID, uuid.UUID]:
    """Map each given session id to the live row its chain has reached.

    An id whose chain has ended — revoked, or expired without a renewal — is
    absent from the answer. One statement for any number of ids, which is what
    lets a sweep over many open connections ask about all of their sign-ins
    at once.
    """
    if not session_ids:
        return {}
    connection = await session.connection()
    result = await connection.execute(
        _LIVE_CHAIN_TIPS_SQL,
        {"ids": list(session_ids), "now": now or utcnow()},
    )
    return {row.origin: row.id for row in result}


async def revoke_session(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    now: datetime | None = None,
) -> int:
    """Revoke one session (logout, unlink, disable MFA). Its access token still
    expires within the short TTL. Returns the number of rows revoked (0 if it was
    already revoked/absent)."""
    result = await session.exec(
        text(
            "UPDATE auth_sessions SET revoked_at = :now "
            "WHERE id = :id AND revoked_at IS NULL"
        ),
        params={"now": now or utcnow(), "id": session_id},
    )
    return result.rowcount


async def _revoke_until_settled(
    session: AsyncSession, statement: Any, params: dict[str, object]
) -> list[Any]:
    """Run a revoking ``statement`` until a pass after the first ends nothing,
    and return every row it revoked.

    A renewal that claimed a row before the first pass holds it until it
    commits. That pass waits for it and skips the row it spent, and the row
    the renewal opened is visible only to the next statement, so each pass
    revokes what the one before could not see.
    """
    revoked: list[Any] = []
    passes = 0
    while True:
        found = (await session.exec(statement, params=params)).all()
        revoked.extend(found)
        passes += 1
        if not found and passes > 1:
            return revoked


async def revoke_chain(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    now: datetime | None = None,
) -> set[uuid.UUID]:
    """Revoke every still-live session in ``session_id``'s rotation chain (theft
    response, or unlink-provider cleanup). Returns the ids it revoked, which
    include the live row a renewal has moved the chain to, one committed while
    this ran among them."""
    rows = await _revoke_until_settled(
        session, _REVOKE_CHAIN_SQL, {"sid": session_id, "now": now or utcnow()}
    )
    return {row.id for row in rows}


async def revoke_all_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    now: datetime | None = None,
    except_session_id: str | None = None,
) -> dict[uuid.UUID, bool]:
    """Revoke all of a user's live sessions — the refresh-side of "sign out
    everywhere" (paired with the ``users.token_version`` bump that invalidates
    outstanding access tokens). Returns each revoked id and whether it was a
    device's session, a renewal committed while this ran included.

    ``except_session_id`` spares one sign-in, for the caller who asked: a change
    made from a settings page should not sign that page out. Its renewals are
    spared with it. Left unset, nothing is spared and this is "everywhere" in
    full.
    """
    params: dict[str, object] = {"now": now or utcnow(), "uid": user_id}
    kept = ""
    if except_session_id is not None:
        kept = (
            "WITH RECURSIVE kept AS ("
            " SELECT id FROM auth_sessions WHERE id = CAST(:keep AS uuid)"
            " UNION"
            " SELECT s.id FROM auth_sessions s JOIN kept k ON s.parent_id = k.id"
            ") "
        )
        params["keep"] = except_session_id
    statement = text(
        kept + "UPDATE auth_sessions SET revoked_at = :now "
        "WHERE user_id = :uid AND revoked_at IS NULL"
        + (" AND id NOT IN (SELECT id FROM kept)" if kept else "")
        + " RETURNING id, install_id IS NOT NULL AS device"
    )
    rows = await _revoke_until_settled(session, statement, params)
    return {row.id: row.device for row in rows}


async def delete_all_for_user(session: AsyncSession, *, user_id: int) -> int:
    """Remove every session row for a user. Returns the number removed.

    The erasure counterpart to :func:`revoke_all_for_user`. A password change
    revokes, because the rows are still the record of where somebody was
    signed in. Erasing the account removes them, because by then the row is
    only a user agent, an IP and a device label belonging to a person who
    asked to be forgotten. A hard delete gets this from the ``users`` foreign
    key; an anonymize keeps the row, so it comes through here.

    Stages only — the caller commits, so this lands with the rest of the
    erasure or not at all.
    """
    result = await session.exec(
        text("DELETE FROM auth_sessions WHERE user_id = :uid"),
        params={"uid": user_id},
    )
    return result.rowcount


async def purge_dead_sessions(
    session: AsyncSession,
    *,
    retention_days: int = SESSION_RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """Remove sessions that can no longer be used and are past the retention
    window, and the key stores of browsers whose sign-in has ended. Returns the
    number of sessions removed.

    A row qualifies once it is expired, or was revoked, longer ago than
    ``retention_days``. A live session matches neither. ``parent_id`` is a
    plain uuid rather than a self-reference, so removing one end of a rotation
    chain leaves the rest intact.
    """
    from app.services.platform import dm_transport

    current = now or utcnow()
    # Read before the rows that say whose they were are gone.
    await dm_transport.withdraw_ended_browsers(session, now=current)
    horizon = current - timedelta(days=retention_days)
    result = await session.exec(
        text(
            "DELETE FROM auth_sessions "
            "WHERE expires_at < :horizon "
            "   OR (revoked_at IS NOT NULL AND revoked_at < :horizon)"
        ),
        params={"horizon": horizon},
    )
    await session.commit()
    return result.rowcount


async def process_dead_session_purge() -> None:
    """Hourly background sweep over ``auth_sessions`` (see
    :data:`SESSION_RETENTION_DAYS`)."""
    from app.db.session import SystemSessionLocal

    async with SystemSessionLocal() as session:
        removed = await purge_dead_sessions(session)
        if removed:
            logger.info("session purge removed %d dead session row(s)", removed)
