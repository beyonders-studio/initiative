"""Shared purge for one-shot ``jti`` replay-guard tables.

Every jti blocklist in the app — the billing service JWT blocklist
(``billing_jti_blocklist``) and the client assertions spent at the plug-in token
endpoint (``plugin_assertion_jtis``) — is the same shape: a ``jti`` primary
key plus an ``expires_at`` mirroring the token's own ``exp``. Each row is a
spent one-shot token, and it is **inert once expired** — the token's ``exp``
is checked at verification, before the blocklist is ever consulted, so a
replay of an expired token is refused whether or not its row still exists.
Purging expired rows therefore never re-opens a replay window; it only
bounds table growth.

The shared jti janitor delegates here for every blocklist rather than
re-implementing the DELETE, so the "purge is safe because exp already refuses
replay" invariant lives in one place. Runs on the system engine (``app_admin``
holds DELETE per ``app/db/system_grants.py``); the scoped request roles never
delete.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import SQLModel, delete
from sqlmodel.ext.asyncio.session import AsyncSession


async def purge_expired_jtis(session: AsyncSession, model: type[SQLModel]) -> int:
    """Delete blocklist rows whose ``expires_at`` has passed; return the count.

    ``model`` must expose an ``expires_at`` column (both jti models do). Owns
    its transaction boundary: commits on success, and on any failure rolls the
    partial statement back before re-raising, so the session is left clean.
    That is what makes it safe to call repeatedly on a **shared** session (the
    janitor sweeps several tables on one session) — a statement-level error on
    one table can't leave an aborted transaction that poisons the next call.
    """
    try:
        result = await session.exec(
            delete(model).where(model.expires_at < datetime.now(UTC))
        )
        await session.commit()
    except Exception:
        # Clear the aborted transaction so the next blocklist on this shared
        # session still sweeps; the caller logs and moves on.
        await session.rollback()
        raise
    return result.rowcount or 0
