"""Telling the person who filed a case that it moved.

A sweep, not a hook: a case moves however its team moves it — a drag on the
board, a bulk edit, a plug-in, a reply — and every one of those already has its
own writer. Once each pass, the sweep reads the cases of the operations
community that have a filer, works out where each stands for its filer the
same way their own view does (:func:`tickets.derive_state`), and compares that
and the newest reply said to them with what they were last told
(``filer_notified_state`` / ``filer_notified_comment_id``). Anything that
moved becomes one notice; the case then records what it told them.

A closed case its filer has already been told about drops out of the scan
unless something new is said to them, so a pass reads the open work, not the
history.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import and_, func, or_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.db import cohorts
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.notification import NotificationType
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.services.platform import notice_outbox, ticket_stream
from app.services.platform.intake import configured_operations_guild_id
from app.services.platform.tickets import (
    FilerState,
    derive_state,
    latest_reply,
    reaches_filer,
)

logger = logging.getLogger(__name__)

#: How often the sweep looks. Somebody waiting on an answer checks back often;
#: half a minute is soon enough to read as prompt.
TICKET_NOTICE_POLL_SECONDS = 30


async def _moved(session: AsyncSession) -> list[Any]:
    latest = latest_reply().label("latest_reply")
    closed = or_(
        Task.deleted_at.is_not(None),  # type: ignore[union-attr]
        TaskStatus.category == TaskStatusCategory.done,
    )
    rows = await session.exec(
        select(
            IntakeCase,
            Task.task_status_id,
            Task.deleted_at,
            TaskStatus.category,
            IntakeBinding.awaiting_filer_status_id,
            latest,
        )
        .join(Task, Task.id == IntakeCase.task_id)
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .outerjoin(IntakeBinding, IntakeBinding.stream == IntakeCase.stream)
        .where(IntakeCase.filer_user_id.is_not(None))  # type: ignore[union-attr]
        .where(reaches_filer())
        .where(
            or_(
                # Not yet settled as closed: its state may have moved.
                IntakeCase.filer_notified_state.is_distinct_from(  # type: ignore[union-attr]
                    FilerState.closed.value
                ),
                ~closed,
                # Closed and told, but somebody said something since.
                and_(
                    latest.is_not(None),
                    latest > func.coalesce(IntakeCase.filer_notified_comment_id, 0),
                ),
            )
        )
        .order_by(IntakeCase.id)
        # Two instances sweeping at once each take different cases.
        .with_for_update(of=IntakeCase, skip_locked=True)
    )
    return list(rows.all())


def _notice(case: IntakeCase, state: FilerState, *, replied: bool) -> dict[str, Any]:
    return notice_outbox.row(
        int(case.filer_user_id),  # type: ignore[arg-type]
        None,
        NotificationType.ticket_updated,
        {
            "task_id": case.task_id,
            "stream": case.stream,
            "subject": case.filer_subject,
            "state": state.value,
            "replied": replied,
            # The filer's own view of it, outside any community.
            "target_path": f"/my-tickets/{case.task_id}",
        },
    )


async def notify_filers() -> int:
    """One pass: tell each filer whose case moved. Returns how many were told."""
    guild_id = await configured_operations_guild_id()
    if guild_id is None:
        return 0
    notices: list[dict[str, Any]] = []
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        for case, status_id, deleted_at, category, awaiting, latest in await _moved(
            session
        ):
            state = derive_state(
                category=category,
                status_id=status_id,
                awaiting_status_id=awaiting,
                stream=IntakeStream(case.stream),
                topic=case.topic,
                trashed=deleted_at is not None,
            )
            replied = latest is not None and latest > (
                case.filer_notified_comment_id or 0
            )
            previous: Optional[str] = case.filer_notified_state
            moved = previous is not None and previous != state.value
            # A case's first pass only records where it starts: its filer
            # filed it a moment ago and knows. A reply is still worth telling.
            if replied or moved:
                notices.append(_notice(case, state, replied=replied))
            if previous == state.value and not replied:
                continue
            # An open ticket page reads it again, whether or not this pass
            # was worth a notice.
            ticket_stream.queue_ticket_signal(session, case.filer_user_id)
            case.filer_notified_state = state.value
            if latest is not None:
                case.filer_notified_comment_id = latest
            session.add(case)
        await notice_outbox.enqueue(session, notices)
        await session.commit()
    return len(notices)


async def process_ticket_notices() -> None:
    """Background sweep: tell filers what moved on their cases."""
    told = await notify_filers()
    if told:
        logger.info("tickets: told %s filer(s) their case moved", told)
