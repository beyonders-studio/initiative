"""Telling a change the owner made from a risky one.

A change is the owner's when the session making it was proved with a passkey,
or when it comes from somewhere the account already uses (the phone or desktop
app, or a sign-in at least a day old) and is not one of a run of changes. Any
other change is risky, and the notice reporting it can undo it.

What is read is already on the session row, in the account's own notices and
in its held changes; nothing new is kept to answer it.
"""

from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.session_opening import (
    current_session_row,
    signed_in_since,
)
from app.models.platform.account_change_hold import AccountChangeHold
from app.models.platform.auth_session import AuthSession
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.user import User
from app.services.auth.assurance import carries_passkey

#: How long a sign-in has to have stood for its place to count as one the
#: account already uses.
ESTABLISHED_AFTER = timedelta(hours=24)

#: Other changes to how the account is signed into, within the window before
#: this one, that make it one of a run.
RUN_LENGTH = 2
RUN_WINDOW = timedelta(hours=1)


async def is_risky(request: Request, system_session: AsyncSession, user: User) -> bool:
    """Whether the change this request makes to ``user``'s account is risky."""
    session_id = current_session_row(request)
    row = await system_session.get(AuthSession, session_id) if session_id else None
    if row is None or row.user_id != user.id:
        return True
    return await risky_session(system_session, row)


async def risky_session(
    system_session: AsyncSession, row: AuthSession, *, now: datetime | None = None
) -> bool:
    """Whether a change made on the session ``row`` is risky."""
    now = now or datetime.now(UTC)
    if carries_passkey(row.amr):
        return False
    since = await signed_in_since(system_session, session_id=row.id)
    established = row.install_id is not None or (
        since is not None and since <= now - ESTABLISHED_AFTER
    )
    if not established:
        return True
    return await _in_a_run(system_session, user_id=row.user_id, now=now)


async def _in_a_run(
    system_session: AsyncSession, *, user_id: int, now: datetime
) -> bool:
    """Whether the account shows other changes just before this one.

    Each change writes one notice row per address, all at one moment, so the
    moments are what is counted. A held change counts from its hold, which is
    there whether or not the deployment sends mail, and not again from its
    notice.
    """
    since = now - RUN_WINDOW
    noticed = (
        await system_session.exec(
            select(func.count(func.distinct(EmailOutboxItem.created_at))).where(
                EmailOutboxItem.user_id == user_id,
                EmailOutboxItem.security.is_(True),
                EmailOutboxItem.change.is_not(None),
                col(EmailOutboxItem.change)["undo"]["kind"].astext.is_distinct_from(
                    "hold"
                ),
                EmailOutboxItem.created_at >= since,
            )
        )
    ).one()
    held = (
        await system_session.exec(
            select(func.count()).where(
                AccountChangeHold.user_id == user_id,
                AccountChangeHold.requested_at >= since,
            )
        )
    ).one()
    return noticed + held >= RUN_LENGTH
