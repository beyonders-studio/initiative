"""An account's cookie answer, read and written for that account alone."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.cookie_categories import CookieCategory
from app.models.platform.user_cookie_consent import UserCookieConsent


async def get_consent(
    session: AsyncSession, *, user_id: int
) -> UserCookieConsent | None:
    """This account's answer, or None where it has never given one.

    None and an answer granting nothing are different states: one has not been
    asked, the other said no. Only the first is worth asking again.
    """
    return (
        await session.exec(
            select(UserCookieConsent).where(UserCookieConsent.user_id == user_id)
        )
    ).first()


async def record_consent(
    session: AsyncSession,
    *,
    user_id: int,
    granted: list[CookieCategory],
    version: int,
) -> UserCookieConsent:
    """Replace this account's answer, stamped with the server's clock.

    Duplicates are dropped and the order is the enum's, so two clients sending
    the same answer differently spelled store the same row.
    """
    kept = [category.value for category in CookieCategory if category in granted]
    row = await get_consent(session, user_id=user_id)
    if row is None:
        row = UserCookieConsent(user_id=user_id, granted=kept, version=version)
    else:
        row.granted = kept
        row.version = version
    row.decided_at = datetime.now(UTC)
    session.add(row)
    await session.flush()
    return row
