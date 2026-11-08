"""A filer's use of the per-user signal channel: one of your tickets moved.

Whoever filed a case follows it from outside the community that works it, so
the community's own socket never reaches them. Their account socket does. When
the team answers them, they answer from another tab, or the case moves, a frame
says only "your tickets changed"; the client re-reads them through the filer
routes, and those reads — routed through the filer role — are where anything is
decided. The frame names no case and carries nothing said.

The socket, the after-commit queueing and the cross-worker bus belong to
:mod:`app.services.platform.user_stream`.
"""

from typing import Any

from sqlmodel import select

from app.services.platform import user_stream

#: What the client switches on to tell this channel from the others.
RESOURCE = "tickets"


def queue_ticket_signal(session: Any, user_id: int | None) -> None:
    """Tell ``user_id`` their tickets changed, once this session commits."""
    user_stream.queue_frame(
        session, user_id, user_stream.build_frame(RESOURCE, "changed")
    )


async def queue_for_case(session: Any, task_id: int) -> None:
    """Tell whoever filed the case behind ``task_id``, where somebody did.

    Read on the caller's session, which reads the case row wherever it may
    read the task the change was made to.
    """
    from app.models.tenant.intake import IntakeCase

    filer = (
        await session.exec(
            select(IntakeCase.filer_user_id).where(IntakeCase.task_id == task_id)
        )
    ).first()
    queue_ticket_signal(session, filer)
