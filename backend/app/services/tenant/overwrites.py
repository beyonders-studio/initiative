"""Text written over whole, refused when it was written over another version.

A task's or event's description and a queue item's notes
are each sent whole, with the version they were written over (its base). One
written over a version that has since moved on would undo that move, so it is
refused instead.
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import CommonMessages


async def refuse_written_over(
    session: AsyncSession, row: object, column: str, base: Optional[str]
) -> None:
    """Refuse ``row``'s ``column`` written over ``base`` unless that is still
    what it holds. The row is locked until the write commits, so a write
    naming the same base reads this one's text."""
    await session.refresh(row, [column], with_for_update=True)
    if (getattr(row, column) or "") != (base or ""):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=CommonMessages.DESCRIPTION_CHANGED,
        )
