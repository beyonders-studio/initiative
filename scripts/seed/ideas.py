"""Published ideas on the Ideas board, with votes, so the Suggestions page has
something on it on a fresh dev database.

One idea in each of the board's statuses, voted for by a different number of
the seeded accounts, and one draft, which the page never shows. Each has a
category, filled from its words where they name one, as the board fills it.
Three are shipped: one in this release, which reads as shipped; one in an
earlier release, which only its own page shows; and one with no release yet,
which reads as the board's last in-progress status. Only where this server has
the board (Initiative Cloud, or a dev server playing it).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream, offered_streams
from app.core.version import __version__
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.tenant.intake import IdeaVote, IntakeBinding
from app.models.tenant.metadata import MetadataDefinition, MetadataValue
from app.models.tenant.task import Task, TaskPriority, TaskStatus, TaskType
from app.services.platform import ideas as ideas_service
from app.services.tenant.task_completion import sync_completed_at
from seed.common import NOW, days_ago

#: The version this server is, and a release before it.
_THIS_RELEASE = __version__
_major, _minor, *_ = (int(part) for part in __version__.split("."))
_EARLIER_RELEASE = f"{_major}.{max(_minor - 1, 0)}.0"


@dataclass(frozen=True)
class SeedIdea:
    title: str
    description: str
    #: ``None`` keeps it a draft.
    status: str | None
    votes: int
    #: How many days ago it was written.
    age: int
    #: Its category where its words name none.
    category: str | None = None
    #: The release a shipped idea shipped in.
    release: str | None = None


IDEAS: list[SeedIdea] = [
    SeedIdea(
        "Keyboard shortcuts for moving tasks between columns",
        "Move the selected task to the next or previous column without reaching"
        " for the mouse.",
        "Planned",
        12,
        40,
        category="Projects",
    ),
    SeedIdea(
        "Pin a comment to the top of a task",
        "Keep the decision everybody needs to see above the rest of the thread.",
        "Under consideration",
        8,
        3,
        category="Projects",
    ),
    SeedIdea(
        "Snooze a notification until tomorrow",
        "Put a notification away for now and have it come back in the morning.",
        "Under consideration",
        4,
        10,
    ),
    SeedIdea(
        "Choose which day the week starts on",
        "Calendars and date pickers start the week on the day you choose.",
        "Building",
        9,
        25,
    ),
    SeedIdea(
        "Export a project to a spreadsheet",
        "Download a project's tasks, with their statuses and fields, as a CSV file.",
        "Shipped",
        15,
        60,
        release=_THIS_RELEASE,
    ),
    SeedIdea(
        "Sign in with a passkey",
        "Use the fingerprint or face unlock your device already has instead of"
        " a password.",
        "Shipped",
        11,
        90,
        category="Account",
        release=_EARLIER_RELEASE,
    ),
    SeedIdea(
        "Install plug-ins without leaving the app",
        "Browse and add plug-ins from inside your community.",
        "Shipped",
        6,
        20,
    ),
    SeedIdea(
        "Reactions on wiki pages",
        "React to a wiki page the way you can to a comment.",
        "Not planned",
        2,
        30,
    ),
    SeedIdea(
        "A weekly summary for initiative managers",
        "Still being worded: what moved, what's overdue and who's waiting.",
        None,
        0,
        1,
        category="Notifications",
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

    options = {
        option["label"]: option["value"]
        for option in (
            await session.exec(
                select(MetadataDefinition.options).where(
                    MetadataDefinition.id == binding.category_field_id
                )
            )
        ).one()
        or []
    }

    def value(field_id: int | None, task: Task, text: str) -> None:
        session.add(
            MetadataValue(
                entity_type="task",
                entity_id=task.id,
                property_id=field_id,
                value_text=text,
            )
        )

    published = 0
    for position, idea in enumerate(IDEAS):
        status = statuses[idea.status] if idea.status else default_status
        task = Task(
            project_id=project_id,
            task_status_id=status.id,
            task_type_id=binding.task_type_id if idea.status else draft_type,
            title=idea.title,
            description=idea.description,
            priority=TaskPriority.medium,
            position=float(position),
            created_at=days_ago(idea.age),
        )
        sync_completed_at(task, status.category, now=NOW)
        session.add(task)
        await session.flush()
        if idea.category:
            value(binding.category_field_id, task, options[idea.category])
        else:
            await ideas_service.fill_category(session, task)
        if idea.release:
            value(binding.release_field_id, task, idea.release)
        published += bool(idea.status)
        # Each voter was last told the status it reads as: a shipped idea
        # with no release yet reads as Building.
        told = (
            statuses["Building"]
            if idea.status == "Shipped" and not idea.release
            else status
        )
        for voter in voters[: idea.votes]:
            session.add(
                IdeaVote(
                    task_id=task.id,
                    user_id=voter.id,
                    voted_at=days_ago(idea.age),
                    notified_status_id=told.id,
                )
            )
    await session.commit()
    await set_rls_context(session, Unattributed())
    return published
