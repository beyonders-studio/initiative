"""Erase accounts whose retention window has run out.

Asking for an account to go no longer erases it: it moves to
``UserStatus.deleted`` and keeps everything — the row, its personal data, its
memberships, its initiative roles, the files it owns — so the person can
come back. Signing in is what brings them back; this worker is what happens if
they do not.

What it runs at the end is :func:`~app.services.platform.users.soft_delete_user`,
unchanged: the erasure that used to happen the moment somebody pressed the
button. Not ``hard_delete_user`` — anonymizing keeps the row, so the work the
account touched still tells one departed author from another.

Polled by ``background_tasks.Loop`` once an hour on
``SystemSessionLocal`` (the ``app_admin`` login). ``soft_delete_user`` does
each guild's part on a system session from that guild's cohort, so this session
stays in ``public``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import SystemSessionLocal
from app.models.platform.user import User
from app.services.platform.retention import ACCOUNT_DELETION

ACCOUNT_PURGE_POLL_SECONDS = 3600


async def _erase(session: AsyncSession, user: User, _days: int) -> None:
    # Imported here rather than at module scope: ``users`` reaches back into
    # this package, and the two would import each other.
    from app.services.platform import users as users_service

    await users_service.soft_delete_user(session, user.id, actor_user_id=None)


async def purge_due_accounts(session: AsyncSession, *, now: datetime) -> int:
    """One pass of :data:`~app.services.platform.retention.ACCOUNT_DELETION`.
    Returns how many accounts were erased.

    Split out from the loop entry point so tests can drive it with the test
    session and a chosen ``now``.
    """
    return await ACCOUNT_DELETION.sweep(session, now=now, act=_erase)


async def process_account_purges() -> None:
    """One pass of the account-purge loop. Idempotent and safe to run on a
    schedule even when nothing is due."""
    now = datetime.now(UTC)
    async with SystemSessionLocal() as session:
        await purge_due_accounts(session, now=now)
