"""What the people working an operations case see of how it was filed.

A case is an ordinary task with an ``intake_cases`` row beside it. This reads
that row for the task view: which stream opened it, who filed it and what they
called it, whether the stream holds a conversation with them, and which of the
binding's statuses mean "waiting on them" and "being worked". It also lets
somebody who works the case take it.

Everything is read on the caller's routed session, so a person who cannot read
the task reads nothing here either.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from sqlalchemy.orm import selectinload

from app.core.intake import Conversation, IntakeStream, conversation_for
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.evidence import Evidence
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory


@dataclass(frozen=True)
class CaseView:
    stream: IntakeStream
    opened_at: datetime
    filer: Optional[MemberProfile]
    filer_subject: Optional[str]
    #: What the case allows with whoever filed it; ``none`` where nobody did.
    conversation: Conversation
    awaiting_filer_status_id: Optional[int]
    active_status_id: Optional[int]
    #: The conversation with whoever filed it, oldest first: their words and
    #: what the team said to them. Not part of the task's thread.
    messages: list[Comment]
    #: What was attached to it, oldest first.
    evidence: list[Evidence]
    #: What it is about, as its references recorded it: the community, and
    #: the kind and id of the thing in it. ``None`` where they say nothing.
    subject_guild_id: Optional[int] = None
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
    #: What it is about within its stream, as its filer chose.
    topic: Optional[str] = None


async def read_case(session: AsyncSession, task_id: int) -> Optional[CaseView]:
    """The case behind ``task_id``, or ``None`` where the task is not one."""
    case = (
        await session.exec(select(IntakeCase).where(IntakeCase.task_id == task_id))
    ).first()
    if case is None:
        return None
    stream = IntakeStream(case.stream)
    binding = (
        await session.exec(
            select(
                IntakeBinding.awaiting_filer_status_id, IntakeBinding.active_status_id
            ).where(IntakeBinding.stream == stream.value)
        )
    ).first()
    filer = None
    if case.filer_user_id is not None:
        filer = (
            await session.exec(
                select(MemberProfile).where(MemberProfile.id == case.filer_user_id)
            )
        ).first()
    from app.services.platform import evidence as evidence_service

    attached = await evidence_service.listed(session, case_ids=[int(case.id)])
    return CaseView(
        stream=stream,
        opened_at=case.opened_at,
        filer=filer,
        filer_subject=case.filer_subject,
        conversation=(
            conversation_for(stream, case.topic)
            if case.filer_user_id is not None
            else Conversation.none
        ),
        topic=case.topic,
        awaiting_filer_status_id=binding[0] if binding else None,
        active_status_id=binding[1] if binding else None,
        messages=list(
            (
                await session.exec(
                    select(Comment)
                    .where(Comment.task_id == task_id)
                    .where(Comment.audience == CommentAudience.filer)
                    .options(selectinload(Comment.author))
                    .order_by(Comment.created_at, Comment.id)
                )
            ).all()
        ),
        evidence=attached.get(("case", int(case.id)), []),
        **await _subject(session, task_id),
    )


async def _subject(session: AsyncSession, task_id: int) -> dict[str, object]:
    """The case's subject, from the references it was opened with: the task's
    values for the case fields that name it."""
    from app.core.intake import CaseField
    from app.services.tenant.metadata import summaries_by_id

    values = {
        summary.name: summary.value
        for summary in (await summaries_by_id(session, "task", [task_id])).get(
            task_id, []
        )
    }

    def whole(name: str) -> Optional[int]:
        value = values.get(name)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    kind = values.get(CaseField.resource_type.value)
    return {
        "subject_guild_id": whole(CaseField.subject_guild.value),
        "resource_type": str(kind) if kind else None,
        "resource_id": whole(CaseField.resource_id.value),
    }


async def take(session: AsyncSession, task: Task, user_id: int) -> Optional[bool]:
    """Assign ``user_id`` to case ``task`` beside whoever already has it, and
    move a case still waiting to be picked up to the status its stream calls
    active. Returns whether they were newly assigned, or ``None`` where the
    task is not a case.

    The task is locked first, so two people taking it at once are both
    assigned rather than one replacing the other. Never commits.
    """
    from app.services.tenant import task_creation

    found = (
        await session.exec(
            select(IntakeCase.id, IntakeBinding.active_status_id)
            .outerjoin(IntakeBinding, IntakeBinding.stream == IntakeCase.stream)
            .where(IntakeCase.task_id == task.id)
        )
    ).first()
    if found is None:
        return None
    active = found[1]
    await session.refresh(task, ["task_status_id"], with_for_update=True)
    held = list(
        (
            await session.exec(
                select(TaskAssignee.user_id).where(TaskAssignee.task_id == task.id)
            )
        ).all()
    )
    newly = user_id not in held
    if newly:
        await task_creation.set_task_assignees(
            session, task, [*held, user_id], project=task.project
        )
    if active is not None:
        waiting = (
            await session.exec(
                select(TaskStatus.category).where(TaskStatus.id == task.task_status_id)
            )
        ).first() == TaskStatusCategory.todo
        # Checked against the task's own project: a case moved elsewhere
        # keeps its status rather than borrowing one.
        belongs = (
            await session.exec(
                select(TaskStatus.id)
                .where(TaskStatus.id == active)
                .where(TaskStatus.project_id == task.project_id)
            )
        ).first()
        if waiting and belongs is not None:
            task.task_status_id = active
    task.updated_at = datetime.now(timezone.utc)
    session.add(task)
    return newly
