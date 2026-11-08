"""The published ideas: what anybody reads of the Ideas board, and the votes.

An idea is a task on the board bound to the ``ideas`` stream that the team
published: its ``ideas`` case, a row in ``intake_cases`` the team opens and
takes away from the task's Idea panel. Reading goes through the ideas
role (``app.db.operations_schema``), signed in or not: a published idea's
title, description and status, and how many voted. A vote is written on the
writer's own session once a read through that role has shown the idea is
published and open, as a filer's answer is.

Only Initiative Cloud has the board (``app.core.intake.offered_streams``).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Optional

from limits import parse
from sqlalchemy import String, and_, cast, false, func, literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream, meta, offered_streams
from app.core.rate_limit import take_allowance
from app.db import cohorts
from app.db.request_context import SystemGuild
from app.db.session import routed_guild_id, set_rls_context
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.tenant.intake import IdeaVote, IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.services.platform import notice_outbox
from app.services.platform.intake import configured_operations_guild_id

#: The counter namespace a vote's pace is kept under.
_PACE_NAMESPACE = "ideas"


class IdeaNotFound(Exception):
    """No published idea by that id, or no board to read one on."""


class VoteRefused(Exception):
    """The idea is closed: it keeps its votes and takes no change to them."""


class VotingTooFast(Exception):
    """This account has voted as often as its pace allows."""


class IdeaSort(str, Enum):
    """How the list is ordered."""

    votes = "votes"
    newest = "newest"


@dataclass(frozen=True)
class IdeaStatus:
    """A status of the Ideas board, under the name the team gave it."""

    id: int
    name: str
    color: Optional[str]
    category: str


@dataclass(frozen=True)
class IdeaRead:
    """One published idea, as anybody reads it."""

    task_id: int
    title: str
    status: IdeaStatus
    votes: int
    #: Whether the reader voted for it; False for somebody signed out.
    voted: bool
    published_at: datetime
    updated_at: Optional[datetime]
    #: Only on one idea's own page.
    description: Optional[str] = None

    @property
    def closed(self) -> bool:
        return self.status.category == TaskStatusCategory.done.value


@dataclass(frozen=True)
class IdeaPage:
    items: list[IdeaRead]
    total: int
    #: Every status of the board, in its order, for filtering by.
    statuses: list[IdeaStatus]


def board_open() -> bool:
    """Whether this server has an Ideas board at all."""
    return IntakeStream.ideas in offered_streams()


@asynccontextmanager
async def _as_reader(user: Optional[User]) -> AsyncIterator[Optional[AsyncSession]]:
    """A request session routed as ``user``, or nobody signed in, reading the
    published ideas; ``None`` where there is no board to read."""
    from app.api.deps import FilerAccessError, establish_ideas_access

    guild_id = await configured_operations_guild_id() if board_open() else None
    if guild_id is None:
        yield None
        return
    async with cohorts.request_sessionmaker(guild_id)() as session:
        try:
            await establish_ideas_access(session, user)
        except FilerAccessError:
            yield None
            return
        yield session


def _status(row: Any) -> IdeaStatus:
    return IdeaStatus(
        id=row.status_id,
        name=row.status_name,
        color=row.status_color,
        category=row.status_category,
    )


def _public(query):
    """``query`` over ``Task``, kept to what anybody may read: a published
    idea still on the board bound to ``ideas``, not archived, trashed or held."""
    return (
        query.join(
            IntakeCase,
            and_(
                IntakeCase.task_id == Task.id,
                IntakeCase.stream == IntakeStream.ideas.value,
            ),
        )
        .join(
            IntakeBinding,
            and_(
                IntakeBinding.stream == IntakeStream.ideas.value,
                IntakeBinding.project_id == Task.project_id,
            ),
        )
        .where(Task.archived_at.is_(None))  # type: ignore[union-attr]
        .where(Task.deleted_at.is_(None))  # type: ignore[union-attr]
        .where(Task.held_at.is_(None))  # type: ignore[union-attr]
    )


def _ideas_query(user: Optional[User], *, with_description: bool = False):
    # Counted as rows: the ideas role reads which task a vote is for and whose
    # it is, and no other column.
    votes = (
        select(func.count())
        .select_from(IdeaVote)
        .where(IdeaVote.task_id == Task.id)
        .correlate(Task)
        .scalar_subquery()
    )
    # A granted column, never ``*``: the ideas role reads only these two.
    voted = (
        select(IdeaVote.task_id)
        .where(IdeaVote.task_id == Task.id)
        .where(IdeaVote.user_id == user.id)
        .correlate(Task)
        .exists()
        if user is not None
        else false()
    )
    columns = [
        Task.id.label("task_id"),
        Task.title,
        IntakeCase.opened_at.label("published_at"),
        Task.updated_at,
        TaskStatus.id.label("status_id"),
        TaskStatus.name.label("status_name"),
        TaskStatus.color.label("status_color"),
        # As text: the role decodes no enum type, which the driver would first
        # have to look up in the catalog with privileges it does not hold.
        cast(TaskStatus.category, String).label("status_category"),
        votes.label("votes"),
        voted.label("voted"),
        (Task.description if with_description else literal(None)).label("description"),
    ]
    query = _public(select(*columns).select_from(Task)).join(
        TaskStatus, TaskStatus.id == Task.task_status_id
    )
    return query, votes, voted


def _read(row: Any) -> IdeaRead:
    return IdeaRead(
        task_id=row.task_id,
        title=row.title,
        status=_status(row),
        votes=row.votes,
        voted=bool(row.voted),
        published_at=row.published_at,
        updated_at=row.updated_at,
        description=row.description,
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_ideas(
    user: Optional[User],
    *,
    q: Optional[str] = None,
    status_id: Optional[int] = None,
    voted_only: bool = False,
    sort: IdeaSort = IdeaSort.votes,
    page: int = 1,
    page_size: int = 50,
) -> IdeaPage:
    """The published ideas: the ones whose title holds ``q`` (case aside), in
    ``status_id``, or that the reader voted for, as asked; most voted or newest
    first."""
    async with _as_reader(user) as session:
        if session is None:
            raise IdeaNotFound
        query, votes, voted = _ideas_query(user)
        if q and q.strip():
            query = query.where(
                Task.title.ilike(f"%{_escape_like(q.strip())}%", escape="\\")  # type: ignore[attr-defined]
            )
        if status_id is not None:
            query = query.where(Task.task_status_id == status_id)
        if voted_only:
            query = query.where(voted)
        total = (
            await session.exec(select(func.count()).select_from(query.subquery()))
        ).one()
        order = (
            (votes.desc(), IntakeCase.opened_at.desc(), Task.id.desc())  # type: ignore[union-attr]
            if sort is IdeaSort.votes
            else (IntakeCase.opened_at.desc(), Task.id.desc())  # type: ignore[union-attr]
        )
        rows = (
            await session.exec(
                query.order_by(*order).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        statuses = (
            await session.exec(
                select(
                    TaskStatus.id.label("status_id"),
                    TaskStatus.name.label("status_name"),
                    TaskStatus.color.label("status_color"),
                    cast(TaskStatus.category, String).label("status_category"),
                ).order_by(TaskStatus.position, TaskStatus.id)
            )
        ).all()
    return IdeaPage(
        items=[_read(row) for row in rows],
        total=int(total),
        statuses=[_status(row) for row in statuses],
    )


async def read_idea(user: Optional[User], task_id: int) -> tuple[int, IdeaRead]:
    """One published idea, with its description, and the operations
    community it was read in."""
    async with _as_reader(user) as session:
        if session is None:
            raise IdeaNotFound
        query, _, _ = _ideas_query(user, with_description=True)
        row = (await session.exec(query.where(Task.id == task_id))).first()
        guild_id = routed_guild_id(session)
    if row is None or guild_id is None:
        raise IdeaNotFound
    return guild_id, _read(row)


async def vote(user: User, task_id: int, *, on: bool) -> IdeaRead:
    """Vote for an open published idea, or take the vote back.

    Read through the ideas role first, which is what says the idea is
    published; written on the writer's own session. A vote starts at the
    status it was cast on, so the vote sweep tells its voter nothing they
    already knew.
    """
    if not await take_allowance(
        parse(meta(IntakeStream.ideas).filing_rate),
        _PACE_NAMESPACE,
        f"vote:user:{user.id}",
    ):
        raise VotingTooFast
    guild_id, idea = await read_idea(user, task_id)
    if idea.closed:
        raise VoteRefused
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        # Asked again under a share lock on the task, so the team cannot close
        # or unpublish it between this answer and the write.
        category = (
            await session.exec(
                _public(select(TaskStatus.category).select_from(Task))
                .join(TaskStatus, TaskStatus.id == Task.task_status_id)
                .where(Task.id == task_id)
                .with_for_update(of=Task, read=True)
            )
        ).first()
        if category is None:
            raise IdeaNotFound
        if category == TaskStatusCategory.done:
            raise VoteRefused
        if on:
            await session.exec(
                pg_insert(IdeaVote)
                .values(
                    task_id=task_id,
                    user_id=user.id,
                    voted_at=datetime.now(timezone.utc),
                    notified_status_id=idea.status.id,
                )
                .on_conflict_do_nothing(constraint="uq_idea_votes_task_user")
            )
        else:
            await session.exec(
                delete(IdeaVote)
                .where(IdeaVote.task_id == task_id)  # type: ignore[arg-type]
                .where(IdeaVote.user_id == user.id)  # type: ignore[arg-type]
            )
        await session.commit()
    _, after = await read_idea(user, task_id)
    return after


# ── The team's side ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IdeaPanel:
    """What the team sees of an Ideas-board task: whether it is published, and
    how many voted."""

    published_at: Optional[datetime]
    votes: int


async def on_the_board(session: AsyncSession, task: Task) -> bool:
    """Whether ``task`` is the team's to publish: on the board bound to the
    ``ideas`` stream and no other stream's case, read on the team's own
    session. False on a server with no board."""
    if not board_open():
        return False
    bound = (
        await session.exec(
            select(IntakeBinding.project_id).where(
                IntakeBinding.stream == IntakeStream.ideas.value
            )
        )
    ).first()
    if bound is None or bound != task.project_id:
        return False
    # Another stream's case moved onto the board says what its filer wrote:
    # it is not the team's to publish.
    other = (
        await session.exec(
            select(IntakeCase.id)
            .where(IntakeCase.task_id == task.id)
            .where(IntakeCase.stream != IntakeStream.ideas.value)
        )
    ).first()
    return other is None


async def panel(session: AsyncSession, task: Task) -> IdeaPanel:
    """``task``'s Idea panel, read on the team's own session."""
    published = (
        await session.exec(
            select(IntakeCase.opened_at)
            .where(IntakeCase.task_id == task.id)
            .where(IntakeCase.stream == IntakeStream.ideas.value)
        )
    ).first()
    votes = (
        await session.exec(
            select(func.count(IdeaVote.id)).where(IdeaVote.task_id == task.id)
        )
    ).one()
    return IdeaPanel(published_at=published, votes=int(votes))


async def publish(session: AsyncSession, task: Task, *, on: bool) -> None:
    """Publish ``task`` as an idea, or take it back, on the team's own
    session: its row policies are what say the reader may change the task.

    Publishing opens the task's ``ideas`` case; :func:`on_the_board` has
    already refused a task that is another stream's case.
    """
    published = (
        await session.exec(
            select(IntakeCase.id)
            .where(IntakeCase.task_id == task.id)
            .where(IntakeCase.stream == IntakeStream.ideas.value)
        )
    ).first()
    if on and published is None:
        now = datetime.now(timezone.utc)
        session.add(
            IntakeCase(
                stream=IntakeStream.ideas,
                task_id=task.id,
                opened_at=now,
                last_seen_at=now,
                noted_at=now,
            )
        )
    elif not on:
        await session.exec(
            delete(IntakeCase)
            .where(IntakeCase.task_id == task.id)  # type: ignore[arg-type]
            .where(IntakeCase.stream == IntakeStream.ideas.value)  # type: ignore[arg-type]
        )
    await session.commit()


async def voter_notices(session: AsyncSession) -> list[dict[str, Any]]:
    """The notices owed to voters whose idea moved to another status, each
    vote marked as told. Read on the operations community's system session
    by the ticket sweep, beside its filers' notices.

    Only what anybody may still read: the system's own role would also see a
    task moved off the board, trashed or held.
    """
    if not board_open():
        return []
    rows = await session.exec(
        _public(
            select(IdeaVote, Task.task_status_id, Task.title, TaskStatus.name)
            .select_from(IdeaVote)
            .join(Task, Task.id == IdeaVote.task_id)
        )
        .join(TaskStatus, TaskStatus.id == Task.task_status_id)
        .where(
            IdeaVote.notified_status_id.is_distinct_from(  # type: ignore[union-attr]
                Task.task_status_id
            )
        )
        .order_by(IdeaVote.id)
        # Two instances sweeping at once each take different votes.
        .with_for_update(of=IdeaVote, skip_locked=True)
    )
    notices: list[dict[str, Any]] = []
    for idea_vote, status_id, title, status_name in rows.all():
        notices.append(
            notice_outbox.row(
                idea_vote.user_id,
                None,
                NotificationType.idea_updated,
                {
                    "task_id": idea_vote.task_id,
                    "title": title,
                    "status": status_name,
                    "target_path": f"/ideas/{idea_vote.task_id}",
                },
            )
        )
        idea_vote.notified_status_id = status_id
        session.add(idea_vote)
    return notices
