"""Published ideas on the Ideas board, with votes, so the Ideas page has
something on it on a fresh dev database.

One idea in each of the board's statuses, voted for by a different number of
the seeded accounts, and one draft, which the page never shows. Only where
this server has the board (Initiative Cloud, or a dev server playing it).
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream, offered_streams
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.tenant.intake import IdeaVote, IntakeBinding
from app.models.tenant.task import Task, TaskPriority, TaskStatus, TaskType
from app.services.tenant.task_completion import sync_completed_at
from seed.common import NOW, days_ago

#: Title, description, status, how many voted, and how many days ago it was
#: written. ``None`` for the status keeps it a draft.
IDEAS: list[tuple[str, str, str | None, int, int]] = [
    (
        "Keyboard shortcuts for moving tasks between columns",
        "Move the selected task to the next or previous column without reaching for the mouse.",
        "Planned",
        12,
        40,
    ),
    (
        "Pin a comment to the top of a task",
        "Keep the decision everybody needs to see above the rest of the thread.",
        "Under consideration",
        8,
        3,
    ),
    (
        "Snooze a notification until tomorrow",
        "Put a notification away for now and have it come back in the morning.",
        "Under consideration",
        4,
        10,
    ),
    (
        "Choose which day the week starts on",
        "Calendars and date pickers start the week on the day you choose.",
        "Building",
        9,
        25,
    ),
    (
        "Export a project to a spreadsheet",
        "Download a project's tasks, with their statuses and fields, as a CSV file.",
        "Shipped",
        15,
        60,
    ),
    (
        "Reactions on wiki pages",
        "React to a wiki page the way you can to a comment.",
        "Not planned",
        2,
        30,
    ),
    (
        "A weekly summary for initiative managers",
        "Still being worded: what moved, what's overdue and who's waiting.",
        None,
        0,
        1,
    ),
]


async def seed(session: AsyncSession, guild: Guild, users: dict[str, User]) -> int:
    """Write the ideas and their votes. Returns how many were published."""
    if IntakeStream.ideas not in offered_streams():
        return 0
    await set_rls_context(session, SystemGuild(guild.id))
    binding = (
        await session.exec(
            select(IntakeBinding).where(
                IntakeBinding.stream == IntakeStream.ideas.value
            )
        )
    ).one()
    project_id = binding.project_id
    statuses = {
        status.name: status
        for status in await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == project_id)
        )
    }
    draft_type = (
        await session.exec(
            select(TaskType.id)
            .where(TaskType.project_id == project_id)
            .where(TaskType.id != binding.task_type_id)
        )
    ).first()
    default_status = next(s for s in statuses.values() if s.is_default)
    voters = list(users.values())

    published = 0
    for position, (title, description, status_name, votes, age) in enumerate(IDEAS):
        status = statuses[status_name] if status_name else default_status
        task = Task(
            project_id=project_id,
            task_status_id=status.id,
            task_type_id=binding.task_type_id if status_name else draft_type,
            title=title,
            description=description,
            priority=TaskPriority.medium,
            position=float(position),
            created_at=days_ago(age),
        )
        sync_completed_at(task, status.category, now=NOW)
        session.add(task)
        await session.flush()
        published += bool(status_name)
        for voter in voters[:votes]:
            session.add(
                IdeaVote(
                    task_id=task.id,
                    user_id=voter.id,
                    voted_at=days_ago(age),
                    notified_status_id=status.id,
                )
            )
    await session.commit()
    await set_rls_context(session, Unattributed())
    return published
