"""Telling the people who work the operations community's cases that work
has arrived: a case opened, or its requester answered on one nobody has taken.

Both go to everyone who can read the case — the people its project is shared
with and the community's admins — because until somebody takes it, nobody in
particular is answering it. A stream kept to an initiative of its own is told
only to that initiative, since nobody else can read it. Each person can turn
the ``cases`` category down.

What leaves the app — the email and the push — names no case and nobody in
it: it says a case opened, or was answered, and the app says which. The bell
line carries only ids, and reads the title when it is read.

Both ride the caller's transaction, on the session routed into the operations
community, and never commit. :func:`works_cases` says who can hear them, so
the settings page offers the category only to them.
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.tenant.comment import Comment
from app.models.tenant.intake import IntakeBinding
from app.models.tenant.task import Task, TaskAssignee


async def works_cases(user: User) -> bool:
    """Whether ``user`` can read a project a stream lands its cases in, as
    themselves in the operations community: who the notices here reach."""
    from app.services.platform.grant_cases import _as_reader

    session, _guild_id = await _as_reader(user)
    if session is None:
        return False
    try:
        return (
            await session.exec(
                select(IntakeBinding.id).where(IntakeBinding.enabled).limit(1)
            )
        ).first() is not None
    finally:
        await session.close()


async def is_taken(session: AsyncSession, task_id: int) -> bool:
    """Whether anybody is assigned to case ``task_id``."""
    return (
        await session.exec(
            select(TaskAssignee.user_id).where(TaskAssignee.task_id == task_id).limit(1)
        )
    ).first() is not None


async def opened(
    session: AsyncSession,
    *,
    task: Task,
    stream: IntakeStream,
    filer_id: int | None,
) -> None:
    """Tell everyone who can read case ``task`` that it opened. Whoever filed
    it is not told of their own case."""
    from app.services import notifications

    subject = await notifications.resolve_subject(session, ("task", int(task.id)))
    if subject is None:
        return
    await notifications.notify(
        session,
        NotificationType.case_opened,
        sorted(subject.readers - {filer_id}),
        about=subject,
        key="case.opened",
        data={
            "task_id": task.id,
            "project_id": task.project_id,
            "stream": stream.value,
        },
    )


async def replied(
    session: AsyncSession, *, task: Task, comment: Comment, filer: User
) -> None:
    """Tell everyone who can read case ``task`` that its requester answered,
    rolled into one unread line for the case."""
    from app.services import notifications

    subject = await notifications.resolve_subject(session, ("task", int(task.id)))
    if subject is None:
        return
    name = await notifications.actor_name(session, filer)
    await notifications.notify(
        session,
        NotificationType.case_replied,
        sorted(subject.readers),
        about=subject,
        key="case.replied",
        data={
            "comment_id": comment.id,
            "task_id": task.id,
            "project_id": task.project_id,
            "commenter_name": name,
            "commenter_id": filer.id,
        },
        actor=filer,
        rollup_key=f"case:{task.id}",
    )
