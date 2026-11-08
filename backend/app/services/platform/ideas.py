"""The published ideas: what anybody reads of the Ideas board, and the votes.

An idea is a task on the board bound to the ``ideas`` stream, of the type that
binding names: the team publishes one by giving it that type, and takes it
back by giving it another. Reading goes through the ideas role
(``app.db.operations_schema``), signed in or not: a published idea's title,
description and status, and how many voted. A vote is written on the system
session once a read through that role has shown the idea is published and
open.

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
from app.models.tenant.intake import IdeaVote, IntakeBinding
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
    created_at: datetime
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
    """``query`` over ``Task``, kept to what anybody may read: a task on the
    board bound to ``ideas``, of the type that binding names, and not archived,
    trashed or held. The ideas role's row policies say the same."""
    return (
        query.join(
            IntakeBinding,
            and_(
                IntakeBinding.stream == IntakeStream.ideas.value,
                IntakeBinding.project_id == Task.project_id,
                IntakeBinding.task_type_id == Task.task_type_id,
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
        Task.created_at,
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
        created_at=row.created_at,
        updated_at=row.updated_at,
        description=row.description,
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_ideas(
    user: Optional[User],
    *,
    search: Optional[str] = None,
    status_id: Optional[int] = None,
    voted_only: bool = False,
    sort: IdeaSort = IdeaSort.votes,
    page: int = 1,
    page_size: int = 50,
) -> IdeaPage:
    """The published ideas: the ones whose title holds ``search`` (case aside), in
    ``status_id``, or that the reader voted for, as asked; most voted or newest
    first."""
    async with _as_reader(user) as session:
        if session is None:
            raise IdeaNotFound
        query, votes, voted = _ideas_query(user)
        if search and search.strip():
            query = query.where(
                Task.title.ilike(f"%{_escape_like(search.strip())}%", escape="\\")  # type: ignore[attr-defined]
            )
        if status_id is not None:
            query = query.where(Task.task_status_id == status_id)
        if voted_only:
            query = query.where(voted)
        total = (
            await session.exec(select(func.count()).select_from(query.subquery()))
        ).one()
        order = (
            (votes.desc(), Task.created_at.desc(), Task.id.desc())  # type: ignore[union-attr]
            if sort is IdeaSort.votes
            else (Task.created_at.desc(), Task.id.desc())  # type: ignore[union-attr]
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
    published; written on the system session. A vote starts at the
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


async def published(session: AsyncSession, task_id: int) -> Optional[Any]:
    """When ``task_id`` was written and how many voted for it, as
    ``(created_at, votes)``, where it is a published idea; ``None`` for any
    other task. Read on the team's own session, for its case panel."""
    if not board_open():
        return None
    votes = (
        select(func.count())
        .select_from(IdeaVote)
        .where(IdeaVote.task_id == Task.id)
        .correlate(Task)
        .scalar_subquery()
    )
    return (
        await session.exec(
            _public(select(Task.created_at, votes).select_from(Task)).where(
                Task.id == task_id
            )
        )
    ).first()


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
