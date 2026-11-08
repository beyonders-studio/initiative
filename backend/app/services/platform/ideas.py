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

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from limits import parse
from sqlalchemy import String, and_, cast, false, func, literal
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import CaseField, IntakeStream, meta, offered_streams
from app.core.rate_limit import take_allowance
from app.core.relationships import EndpointKind, RelationshipType
from app.db import cohorts, reference_targets
from app.db.request_context import SystemGuild
from app.db.session import routed_guild_id, set_rls_context
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.tenant.intake import IdeaVote, IntakeBinding, IntakeCase
from app.models.tenant.metadata import MetadataDefinition, MetadataValue
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.services.platform import notice_outbox
from app.services.platform.intake import configured_operations_guild_id
from app.services.tenant import relationships
from app.services.tenant.archive import archive_entity
from app.services.tenant.search import FUZZY_THRESHOLD

#: The counter namespace a vote's pace is kept under.
_PACE_NAMESPACE = "ideas"


class IdeaNotFound(Exception):
    """No published idea by that id, or no board to read one on."""


class VoteRefused(Exception):
    """The idea is closed: it keeps its votes and takes no change to them."""


class VotingTooFast(Exception):
    """This account has voted as often as its pace allows."""


class NotOnTheBoard(Exception):
    """A join names a task that is not on the Ideas board, or joins something
    that is not feedback."""


class IdeaSort(str, Enum):
    """How the list is ordered."""

    votes = "votes"
    newest = "newest"


@dataclass(frozen=True)
class IdeaStatus:
    """A status of the Ideas board, under the name the team gave it."""

    id: int
    name: str
    color: str | None
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
    updated_at: datetime | None
    #: Only on one idea's own page.
    description: str | None = None

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
async def _as_reader(user: User | None) -> AsyncIterator[AsyncSession | None]:
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


def _ideas_query(user: User | None, *, with_description: bool = False):
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
    user: User | None,
    *,
    search: str | None = None,
    status_id: int | None = None,
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


async def read_idea(user: User | None, task_id: int) -> tuple[int, IdeaRead]:
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


async def similar(user: User | None, text: str) -> list[IdeaRead]:
    """The open published ideas whose title is close to ``text``, closest
    first: what somebody writing feedback may vote for instead. Close either
    way round, so a few words find a longer title and a long draft finds a
    short one; the threshold decides what shows, not a count."""
    async with _as_reader(user) as session:
        if session is None:
            raise IdeaNotFound
        query, _, _ = _ideas_query(user)
        closeness = func.greatest(
            func.word_similarity(Task.title, text),
            func.word_similarity(text, Task.title),
        )
        rows = (
            await session.exec(
                query.where(closeness >= FUZZY_THRESHOLD)
                .where(
                    cast(TaskStatus.category, String) != TaskStatusCategory.done.value
                )
                .order_by(closeness.desc(), Task.id.desc())
            )
        ).all()
    return [_read(row) for row in rows]


async def joined_into(task_id: int) -> int | None:
    """The published idea an idea joined into another now is, following each
    join, so its old page opens it; ``None`` for any other task. A joined idea
    is archived, with a ``part_of`` edge to the one it joined."""
    guild_id = await configured_operations_guild_id() if board_open() else None
    if guild_id is None:
        return None
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        seen: set[int] = set()
        current = task_id
        while current not in seen:
            seen.add(current)
            following = (
                await session.exec(
                    _edges_into_board(
                        select(EntityRelationship.target_id).join(
                            Task, Task.id == EntityRelationship.source_id
                        )
                    )
                    .where(EntityRelationship.source_type == EndpointKind("task").value)
                    .where(EntityRelationship.source_id == current)
                    .where(Task.project_id == _board_project())
                    .where(Task.archived_at.is_not(None))  # type: ignore[union-attr]
                    .order_by(EntityRelationship.id.desc())
                )
            ).first()
            if following is None:
                return None
            public = (
                await session.exec(
                    _public(select(Task.id).select_from(Task)).where(
                        Task.id == following
                    )
                )
            ).first()
            if public is not None:
                return following
            current = following
    return None


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
                    voted_at=datetime.now(UTC),
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


async def published(session: AsyncSession, task_id: int) -> Any | None:
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


def _board_project():
    """The project bound to ``ideas``, as a subquery."""
    return (
        select(IntakeBinding.project_id)
        .where(IntakeBinding.stream == IntakeStream.ideas.value)
        .scalar_subquery()
    )


def _edges_into_board(query):
    """``query`` over live ``part_of`` edges whose target is a task on the
    Ideas board."""
    return (
        query.where(
            EntityRelationship.relationship_type == RelationshipType.part_of.value
        )
        .where(EntityRelationship.target_type == EndpointKind("task").value)
        .where(EntityRelationship.removed_at.is_(None))  # type: ignore[union-attr]
        .where(
            EntityRelationship.target_id.in_(  # type: ignore[attr-defined]
                select(Task.id).where(Task.project_id == _board_project())
            )
        )
    )


async def board_project(session: AsyncSession) -> int | None:
    """The Ideas board's project, where this server has one and it is bound,
    on the team's own session."""
    if not board_open():
        return None
    return (await session.exec(select(_board_project()))).first()


async def _board_task(session: AsyncSession, task_id: int, *, changing: bool) -> Task:
    """``task_id`` on the Ideas board and not archived, locked as a vote locks
    it: for update where its votes are about to move, and for share where one
    is about to be added, so neither is lost to the other."""
    task = (
        await session.exec(
            select(Task)
            .where(Task.id == task_id)
            .where(Task.project_id == _board_project())
        )
    ).first()
    if task is None:
        raise NotOnTheBoard
    await session.refresh(
        task,
        ["archived_at", "task_status_id"],
        with_for_update=True if changing else {"read": True},
    )
    if task.archived_at is not None:
        raise NotOnTheBoard
    return task


async def _joins(session: AsyncSession, case_task_id: int) -> list[EntityRelationship]:
    """The live edges joining feedback case ``case_task_id`` to an idea."""
    return list(
        (
            await session.exec(
                _edges_into_board(select(EntityRelationship))
                .where(EntityRelationship.source_type == EndpointKind("task").value)
                .where(EntityRelationship.source_id == case_task_id)
                .order_by(EntityRelationship.id)
            )
        ).all()
    )


async def joined_idea(session: AsyncSession, case_task_id: int) -> Task | None:
    """The idea feedback case ``case_task_id`` is joined to, on the team's own
    session."""
    joins = await _joins(session, case_task_id)
    if not joins:
        return None
    return (
        await session.exec(select(Task).where(Task.id == joins[-1].target_id))
    ).first()


async def _feedback(session: AsyncSession, task_id: int) -> None:
    """Refuse a task that is not a feedback case, or a community with no
    Ideas board."""
    from app.services.tenant.cases import holds_cases

    if not board_open() or not await holds_cases(session):
        raise NotOnTheBoard
    stream = (
        await session.exec(
            select(IntakeCase.stream).where(IntakeCase.task_id == task_id)
        )
    ).first()
    if stream != IntakeStream.feedback.value:
        raise NotOnTheBoard


async def _sender(session: AsyncSession, case_task_id: int) -> int | None:
    """Who sent feedback case ``case_task_id``: its ``subject_user``, which it
    holds whether or not they offered to be contacted."""
    value = (
        await session.exec(
            select(MetadataValue.value_number)
            .join(
                MetadataDefinition, MetadataDefinition.id == MetadataValue.property_id
            )
            .where(MetadataValue.entity_type == "task")
            .where(MetadataValue.entity_id == case_task_id)
            .where(MetadataDefinition.name == CaseField.subject_user.value)
        )
    ).first()
    return int(value) if value is not None else None


def _task(task_id: int) -> relationships.Endpoint:
    return relationships.Endpoint(EndpointKind("task"), task_id)


async def join(
    session: AsyncSession, case: Task, idea_task_id: int, *, by: int | None
) -> None:
    """Join feedback case ``case`` to the idea ``idea_task_id`` on the Ideas
    board, published or not: a ``part_of`` edge from the case to the idea, in
    place of any to another idea, and a vote for whoever sent it, where the
    idea is open and they have none. Joined, they hear when the idea moves,
    whether or not they offered to be contacted. The caller commits.

    Raises :class:`NotOnTheBoard`.
    """
    await _feedback(session, case.id)
    idea = await _board_task(session, idea_task_id, changing=False)
    joined = False
    for edge in await _joins(session, case.id):
        if edge.target_id == idea.id:
            joined = True
        else:
            await relationships.remove(session, edge, removed_by=by)
    if not joined:
        await relationships.create(
            session,
            source=_task(case.id),
            relationship_type=RelationshipType.part_of,
            target=_task(idea.id),
            created_by=by,
        )
    sender = await _sender(session, case.id)
    category = (
        await session.exec(
            select(TaskStatus.category).where(TaskStatus.id == idea.task_status_id)
        )
    ).one()
    if sender is not None and category != TaskStatusCategory.done:
        await session.exec(
            pg_insert(IdeaVote)
            .values(
                task_id=idea.id,
                user_id=sender,
                voted_at=datetime.now(UTC),
                notified_status_id=idea.task_status_id,
            )
            .on_conflict_do_nothing(constraint="uq_idea_votes_task_user")
        )


async def unjoin(session: AsyncSession, case: Task, *, by: int | None) -> None:
    """Take feedback case ``case`` off the idea it is joined to. Its sender's
    vote stays: taking it back is theirs. The caller commits.

    Raises :class:`NotOnTheBoard`.
    """
    await _feedback(session, case.id)
    for edge in await _joins(session, case.id):
        await relationships.remove(session, edge, removed_by=by)


async def join_sent(case_task_id: int, idea_task_id: int, sender: User) -> None:
    """Join feedback just sent to the published idea its sender voted for
    while writing it. Nothing where that idea is not published: the feedback
    stands on its own."""
    try:
        guild_id, _ = await read_idea(sender, idea_task_id)
    except IdeaNotFound:
        return
    async with cohorts.system_session(guild_id) as session:
        await set_rls_context(session, SystemGuild(guild_id))
        case = (await session.exec(select(Task).where(Task.id == case_task_id))).one()
        await join(session, case, idea_task_id, by=sender.id)
        await session.commit()


async def join_into(
    session: AsyncSession, source: Task, target_task_id: int, *, by: int | None
) -> None:
    """Join idea ``source`` into ``target_task_id``, both on the Ideas board.
    Its votes move to the target, each voter's once, as does everything that
    is part of it, the feedback joined to it among them. It is then part of
    the target and archived, so it leaves the Ideas page and its page opens
    the target. The caller commits.

    Raises :class:`NotOnTheBoard`.
    """
    from app.services.tenant.cases import holds_cases

    if not board_open() or not await holds_cases(session):
        raise NotOnTheBoard
    if target_task_id == source.id:
        raise NotOnTheBoard
    await _board_task(session, source.id, changing=True)
    target = await _board_task(session, target_task_id, changing=False)
    # Each vote keeps the status its voter was last told about: both ideas
    # are on one board, so the next pass tells them where the target stands.
    await session.exec(
        pg_insert(IdeaVote)
        .from_select(
            ["task_id", "user_id", "voted_at", "notified_status_id"],
            select(
                literal(target.id),
                IdeaVote.user_id,
                IdeaVote.voted_at,
                IdeaVote.notified_status_id,
            ).where(IdeaVote.task_id == source.id),
        )
        .on_conflict_do_nothing(constraint="uq_idea_votes_task_user")
    )
    await session.exec(
        delete(IdeaVote).where(IdeaVote.task_id == source.id)  # type: ignore[arg-type]
    )
    parts = (
        await session.exec(
            select(EntityRelationship)
            .where(
                EntityRelationship.relationship_type == RelationshipType.part_of.value
            )
            .where(EntityRelationship.target_type == EndpointKind("task").value)
            .where(EntityRelationship.target_id == source.id)
            .where(EntityRelationship.removed_at.is_(None))  # type: ignore[union-attr]
        )
    ).all()
    for edge in parts:
        part = await reference_targets.resolve_one(
            session, EndpointKind(edge.source_type), edge.source_id, user_id=by
        )
        # What is archived keeps its links as they are: an idea joined into
        # this one before reaches the target through it.
        if part is None or part.archived:
            continue
        await relationships.remove(session, edge, removed_by=by, tombstone=False)
        if not (edge.source_type == "task" and edge.source_id == target.id):
            await relationships.create(
                session,
                source=relationships.Endpoint(
                    EndpointKind(edge.source_type), edge.source_id
                ),
                relationship_type=RelationshipType.part_of,
                target=_task(target.id),
                created_by=by,
            )
    await relationships.create(
        session,
        source=_task(source.id),
        relationship_type=RelationshipType.part_of,
        target=_task(target.id),
        created_by=by,
    )
    await archive_entity(session, source)


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
