"""The published ideas: what anybody reads of the Ideas board, and the votes.

An idea is a task on the board bound to the ``ideas`` stream, of the type that
binding names: the team publishes one by giving it that type, and takes it
back by giving it another. Reading goes through the ideas role
(``app.db.operations_schema``), signed in or not: a published idea's title,
description, status and category, the release it shipped in once it has, and
how many voted. A vote is written on the system session once a read through
that role has shown the idea is published and open.

The status anybody reads is the idea's own, but for one: an idea in the
binding's shipped status reads as shipped only while the release it records
is this server's version. Before that release is out it reads as the board's
last in-progress status, and once a later one is out it leaves the list and
the roadmap, though its own page still reads it as shipped in its release
(:func:`_presented`).

Only Initiative Cloud has the board (``app.core.intake.offered_streams``).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from limits import parse
from sqlalchemy import (
    Integer,
    String,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    or_,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import CaseField, IntakeStream, meta, offered_streams
from app.core.rate_limit import take_allowance
from app.core.relationships import EndpointKind, RelationshipType
from app.core.version import __version__, compare_versions
from app.db import cohorts, reference_targets
from app.db.request_context import SystemGuild
from app.db.session import routed_guild_id, set_rls_context
from app.models.platform.notification import NotificationType
from app.models.platform.user import User
from app.models.tenant.intake import IdeaVote, IntakeBinding, IntakeCase
from app.models.tenant.metadata import MetadataDefinition, MetadataValue
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.task import Task, TaskStatus, TaskStatusCategory
from app.schemas.tenant.property import PropertyValueInput
from app.services.platform import notice_outbox
from app.services.platform.intake import configured_operations_guild_id
from app.services.tenant import metadata as metadata_service
from app.services.tenant import relationships
from app.services.tenant.archive import archive_entity
from app.services.tenant.search import FUZZY_THRESHOLD
from app.services.tenant.task_queries import description_excerpt, description_head

#: The counter namespace a vote's pace is kept under.
_PACE_NAMESPACE = "ideas"

#: How long a listed idea's summary runs.
SUMMARY_CHARS = 200


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
    icon: str | None
    category: str


@dataclass(frozen=True)
class IdeaRead:
    """One published idea, as anybody reads it."""

    task_id: int
    title: str
    #: The status it reads as (:func:`_presented`).
    status: IdeaStatus
    votes: int
    #: Whether the reader voted for it; False for somebody signed out.
    voted: bool
    created_at: datetime
    updated_at: datetime | None
    #: The label of its category option, where it has one.
    category: str | None = None
    #: The release it shipped in, where it reads as shipped.
    release: str | None = None
    #: Its description's first paragraph, in a list.
    summary: str | None = None
    #: Only on one idea's own page.
    description: str | None = None

    @property
    def closed(self) -> bool:
        return self.status.category == TaskStatusCategory.done.value


@dataclass(frozen=True)
class CategoryCount:
    """One category the list can show, and how many ideas are in it."""

    name: str
    count: int


@dataclass(frozen=True)
class IdeaPage:
    items: list[IdeaRead]
    total: int
    #: The statuses the published ideas read as, in the board's order, for
    #: filtering by.
    statuses: list[IdeaStatus]
    #: The categories of the ideas the list shows, the category asked for
    #: aside, in the field's order.
    categories: list[CategoryCount]


@dataclass(frozen=True)
class RoadmapColumn:
    status: IdeaStatus
    items: list[IdeaRead]


def board_open() -> bool:
    """Whether this server has an Ideas board at all."""
    return IntakeStream.ideas in offered_streams()


# ── Category, from the words ─────────────────────────────────────────────────


def _words(text: str) -> list[str]:
    """``text`` as lower-case words: each a run of letters and digits, a
    hyphen joining the two sides it stands between rather than parting them."""
    words: list[str] = []
    word = ""
    for char in text.lower():
        if char.isalnum():
            word += char
        elif char != "-" and word:
            words.append(word)
            word = ""
    if word:
        words.append(word)
    return words


def _forms(label: str) -> set[tuple[str, ...]]:
    """The word sequences that name option ``label``: its words, and its last
    word with one trailing "s" taken off or put on."""
    words = _words(label)
    if not words:
        return set()
    *head, last = words
    forms = {tuple(words), (*head, f"{last}s")}
    if len(last) > 1 and last.endswith("s"):
        forms.add((*head, last[:-1]))
    return forms


def category_named(
    title: str | None, description: str | None, labels: Sequence[str]
) -> str | None:
    """The option of ``labels`` an idea's words name: the one named earliest
    in ``title``, else in ``description``, by whole words, either case, its
    label or that with one "s" more or less, hyphens aside ("plugin",
    "plug-in" and "Plug-ins" all name Plug-ins). Two named at the same word go
    to the first in ``labels``. ``None`` where none is named."""
    forms = [(label, _forms(label)) for label in labels]
    for text in (title, description):
        words = _words(text or "")
        for start in range(len(words)):
            for label, named in forms:
                if any(tuple(words[start : start + len(f)]) == f for f in named):
                    return label
    return None


# ── The board's roles, and the status an idea reads as ───────────────────────


def _version(release: str) -> str | None:
    """The version ``release`` names, without a leading "v"; ``None`` where
    it names none."""
    bare = release.strip().lstrip("vV")
    return bare if bare[:1].isdigit() else None


@dataclass(frozen=True)
class _Board:
    """What the Ideas binding names, read on the session asking."""

    project_id: int | None = None
    category_field_id: int | None = None
    release_field_id: int | None = None
    shipped_status_id: int | None = None
    #: The board's last in-progress status, or its first waiting one where it
    #: has none, which a shipped idea reads as until its release is out.
    building_status_id: int | None = None
    #: The category field's options, as ``(value, label)``, in order.
    options: tuple[tuple[str, str], ...] = ()
    #: Every release written on an idea the session reads.
    releases: tuple[str, ...] = ()

    def label(self, value: str | None) -> str | None:
        return next((label for v, label in self.options if v == value), None)

    def value(self, label: str) -> str | None:
        return next((v for v, name in self.options if name == label), None)

    def releases_of(self, version: str, against: int = 0) -> list[str]:
        """The releases written that compare with ``version`` as ``against``
        says: 0 for the same version, -1 for those before it."""
        return [
            release
            for release in self.releases
            if (named := _version(release)) is not None
            and compare_versions(named, version) == against
        ]


def _options(raw: Any) -> tuple[tuple[str, str], ...]:
    return tuple(
        (option["value"], option["label"])
        for option in raw or ()
        if isinstance(option, dict) and "value" in option and "label" in option
    )


async def _board(session: AsyncSession) -> _Board:
    """The Ideas binding's roles, as ``session`` reads them; empty where the
    board is not bound."""

    def first(category: TaskStatusCategory, *order: Any) -> Any:
        return (
            select(TaskStatus.id)
            .where(TaskStatus.project_id == IntakeBinding.project_id)
            # As text: the ideas role decodes no enum type.
            .where(cast(TaskStatus.category, String) == category.value)
            .order_by(*order)
            .limit(1)
            .correlate(IntakeBinding)
            .scalar_subquery()
        )

    # The last in-progress status, or, on a board with none, the first status
    # still waiting, so a shipped idea whose release is not out stays readable.
    building = func.coalesce(
        first(
            TaskStatusCategory.in_progress,
            TaskStatus.position.desc(),  # type: ignore[union-attr]
            TaskStatus.id.desc(),  # type: ignore[union-attr]
        ),
        first(
            TaskStatusCategory.todo,
            TaskStatus.position.asc(),  # type: ignore[union-attr]
            TaskStatus.id.asc(),  # type: ignore[union-attr]
        ),
    )
    options = (
        select(MetadataDefinition.options)
        .where(MetadataDefinition.id == IntakeBinding.category_field_id)
        .correlate(IntakeBinding)
        .scalar_subquery()
    )
    row = (
        await session.exec(
            select(
                IntakeBinding.project_id,
                IntakeBinding.category_field_id,
                IntakeBinding.release_field_id,
                IntakeBinding.shipped_status_id,
                building.label("building_status_id"),
                options.label("options"),
            ).where(IntakeBinding.stream == IntakeStream.ideas.value)
        )
    ).first()
    if row is None:
        return _Board()
    releases: Sequence[str | None] = ()
    if row.release_field_id is not None:
        releases = (
            await session.exec(
                select(MetadataValue.value_text)
                .where(MetadataValue.entity_type == "task")
                .where(MetadataValue.property_id == row.release_field_id)
                .distinct()
            )
        ).all()
    return _Board(
        project_id=row.project_id,
        category_field_id=row.category_field_id,
        release_field_id=row.release_field_id,
        shipped_status_id=row.shipped_status_id,
        building_status_id=row.building_status_id,
        options=_options(row.options),
        releases=tuple(release for release in releases if release),
    )


@dataclass(frozen=True)
class _Shape:
    """How an idea is read: the columns read beside its task's own."""

    board: _Board
    #: The ``metadata_values`` aliases its category and release are read
    #: from, each with the field it holds; none for a field the board lacks.
    fields: tuple[tuple[Any, int], ...]
    #: Its category option's value, and the release written on it.
    category: Any
    release: Any
    #: The status it reads as (:func:`_presented`).
    presented: Any
    votes: Any
    voted: Any


def _shape(board: _Board, user: User | None, *, past: bool) -> _Shape:
    """How an idea on ``board`` is read by ``user``, or by nobody signed in.
    With ``past``, an idea shipped in an earlier release reads as shipped;
    without, it is not read."""
    fields: list[tuple[Any, int]] = []
    columns: list[Any] = []
    for field_id in (board.category_field_id, board.release_field_id):
        if field_id is None:
            columns.append(literal(None, String))
            continue
        alias = aliased(MetadataValue)
        fields.append((alias, field_id))
        columns.append(alias.value_text)
    category, release = columns
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
    return _Shape(
        board=board,
        fields=tuple(fields),
        category=category,
        release=release,
        presented=_presented(board, release, past=past),
        votes=votes,
        voted=voted,
    )


def _presented(board: _Board, release: Any, *, past: bool) -> Any:
    """The status an idea reads as, as SQL: its own, but in the shipped
    status, that only while its release is this server's version. Before that
    release is out, or with none written, the board's last in-progress status;
    once a later one is out, with ``past`` the shipped status still. Anything
    else reads as NULL, and an idea whose status reads as NULL is not read."""
    shipped_id = board.shipped_status_id
    if shipped_id is None:
        return Task.task_status_id
    shipped = Task.task_status_id == shipped_id
    whens: list[tuple[Any, Any]] = []
    if current := board.releases_of(__version__):
        whens.append((and_(shipped, release.in_(current)), literal(shipped_id)))
    if earlier := board.releases_of(__version__, -1):
        whens.append(
            (
                and_(shipped, release.in_(earlier)),
                literal(shipped_id if past else None, Integer),
            )
        )
    whens.append((shipped, literal(board.building_status_id, Integer)))
    return case(*whens, else_=Task.task_status_id)


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


def _read_as(shape: _Shape, query, *, published: bool = True):
    """``query``, which reads ``Task``, with each idea's category and release
    beside it and the status it reads as, ``TaskStatus``; kept, with
    ``published``, to what anybody may read."""
    for alias, field_id in shape.fields:
        query = query.outerjoin(
            alias,
            and_(
                alias.entity_type == "task",
                alias.entity_id == Task.id,
                alias.property_id == field_id,
            ),
        )
    query = query.join(TaskStatus, TaskStatus.id == shape.presented)
    return _public(query) if published else query


# ── Reading ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def _as_reader(user: User | None) -> AsyncGenerator[AsyncSession | None]:
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


@asynccontextmanager
async def _reading(
    user: User | None, *, past: bool = False
) -> AsyncGenerator[tuple[AsyncSession, _Shape]]:
    """:func:`_as_reader`'s session, and how ideas are read on it.

    Raises :class:`IdeaNotFound` where there is no board to read.
    """
    async with _as_reader(user) as session:
        if session is None:
            raise IdeaNotFound
        yield session, _shape(await _board(session), user, past=past)


def _status_columns() -> tuple[Any, ...]:
    return (
        TaskStatus.id.label("status_id"),
        TaskStatus.name.label("status_name"),
        TaskStatus.color.label("status_color"),
        TaskStatus.icon.label("status_icon"),
        # As text: the role decodes no enum type, which the driver would first
        # have to look up in the catalog with privileges it does not hold.
        cast(TaskStatus.category, String).label("status_category"),
    )


def _status(row: Any) -> IdeaStatus:
    return IdeaStatus(
        id=row.status_id,
        name=row.status_name,
        color=row.status_color,
        icon=row.status_icon,
        category=row.status_category,
    )


def _ideas_query(shape: _Shape, *, with_description: bool = False):
    """The published ideas as :func:`_read` reads them: with the description
    for one idea's page, and otherwise the head its summary is made from."""
    shipped_id = shape.board.shipped_status_id
    nothing = literal(None, String)
    columns = [
        Task.id.label("task_id"),
        Task.title,
        Task.created_at,
        Task.updated_at,
        *_status_columns(),
        shape.votes.label("votes"),
        shape.voted.label("voted"),
        shape.category.label("category_value"),
        # The release, only where the idea reads as shipped.
        (
            case((TaskStatus.id == shipped_id, shape.release), else_=nothing)
            if shipped_id is not None
            else nothing
        ).label("release"),
        (Task.description if with_description else nothing).label("description"),
        (
            nothing
            if with_description
            else description_head(Task.description, SUMMARY_CHARS)
        ).label("summary_head"),
    ]
    return _read_as(shape, select(*columns).select_from(Task))


def _read(row: Any, board: _Board) -> IdeaRead:
    return IdeaRead(
        task_id=row.task_id,
        title=row.title,
        status=_status(row),
        votes=row.votes,
        voted=bool(row.voted),
        created_at=row.created_at,
        updated_at=row.updated_at,
        category=board.label(row.category_value),
        release=_version(row.release) if row.release else None,
        summary=description_excerpt(row.summary_head, SUMMARY_CHARS, first_block=True),
        description=row.description,
    )


def _most_voted(shape: _Shape) -> tuple[Any, ...]:
    return (shape.votes.desc(), Task.created_at.desc(), Task.id.desc())  # type: ignore[union-attr]


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_ideas(
    user: User | None,
    *,
    search: str | None = None,
    status_id: int | None = None,
    category: str | None = None,
    voted_only: bool = False,
    sort: IdeaSort = IdeaSort.votes,
    page: int = 1,
    page_size: int = 50,
) -> IdeaPage:
    """The published ideas the list shows: the ones whose title holds
    ``search`` (case aside), that read as ``status_id``, in the category
    labelled ``category``, or that the reader voted for, as asked; most voted
    or newest first. With them, how many of those ideas each category holds,
    whichever category was asked for."""
    async with _reading(user) as (session, shape):
        board = shape.board
        shown = _ideas_query(shape)
        query = shown
        if search and search.strip():
            query = query.where(
                Task.title.ilike(f"%{_escape_like(search.strip())}%", escape="\\")  # type: ignore[attr-defined]
            )
        if status_id is not None:
            query = query.where(TaskStatus.id == status_id)
        if voted_only:
            query = query.where(shape.voted)
        counted = query.subquery()
        in_each = dict(
            (
                await session.exec(
                    select(counted.c.category_value, func.count())
                    .where(counted.c.category_value.is_not(None))
                    .group_by(counted.c.category_value)
                )
            ).all()
        )
        if category is not None:
            value = board.value(category)
            query = query.where(
                shape.category == value if value is not None else false()
            )
        total = (
            await session.exec(select(func.count()).select_from(query.subquery()))
        ).one()
        order = (
            _most_voted(shape)
            if sort is IdeaSort.votes
            else (Task.created_at.desc(), Task.id.desc())  # type: ignore[union-attr]
        )
        rows = (
            await session.exec(
                query.order_by(*order).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        seen = shown.subquery()
        statuses = (
            await session.exec(
                select(*_status_columns())
                .where(TaskStatus.id.in_(select(seen.c.status_id)))  # type: ignore[union-attr]
                .order_by(TaskStatus.position, TaskStatus.id)
            )
        ).all()
    return IdeaPage(
        items=[_read(row, board) for row in rows],
        total=int(total),
        statuses=[_status(row) for row in statuses],
        categories=[
            CategoryCount(name=label, count=in_each[value])
            for value, label in board.options
            if in_each.get(value)
        ],
    )


async def roadmap(user: User | None) -> list[RoadmapColumn]:
    """The board's in-progress statuses in its order, then its shipped
    status, each with the published ideas that read as it, most voted first."""
    async with _reading(user) as (session, shape):
        board = shape.board
        shipped = TaskStatus.id == board.shipped_status_id
        statuses = (
            await session.exec(
                select(*_status_columns())
                .where(TaskStatus.project_id == board.project_id)
                .where(
                    or_(
                        cast(TaskStatus.category, String)
                        == TaskStatusCategory.in_progress.value,
                        shipped,
                    )
                )
                .order_by(shipped, TaskStatus.position, TaskStatus.id)
            )
        ).all()
        ids = [row.status_id for row in statuses]
        rows = (
            await session.exec(
                _ideas_query(shape)
                .where(TaskStatus.id.in_(ids))  # type: ignore[union-attr]
                .order_by(*_most_voted(shape))
            )
        ).all()
    items: dict[int, list[IdeaRead]] = {status_id: [] for status_id in ids}
    for row in rows:
        items[row.status_id].append(_read(row, board))
    return [
        RoadmapColumn(status=_status(row), items=items[row.status_id])
        for row in statuses
    ]


async def shipped_in(user: User | None, release: str) -> list[IdeaRead]:
    """The published ideas in the shipped status whose release is
    ``release``, most voted first; none for a release this server is not
    yet on."""
    version = _version(release)
    async with _reading(user, past=True) as (session, shape):
        board = shape.board
        if version is None or compare_versions(version, __version__) > 0:
            return []
        named = board.releases_of(version)
        if board.shipped_status_id is None or not named:
            return []
        rows = (
            await session.exec(
                _ideas_query(shape)
                .where(Task.task_status_id == board.shipped_status_id)
                .where(shape.release.in_(named))
                .order_by(*_most_voted(shape))
            )
        ).all()
    return [_read(row, board) for row in rows]


async def read_idea(user: User | None, task_id: int) -> tuple[int, IdeaRead]:
    """One published idea, with its description, and the operations
    community it was read in. One shipped in an earlier release still reads,
    as shipped."""
    async with _reading(user, past=True) as (session, shape):
        row = (
            await session.exec(
                _ideas_query(shape, with_description=True).where(Task.id == task_id)
            )
        ).first()
        guild_id = routed_guild_id(session)
    if row is None or guild_id is None:
        raise IdeaNotFound
    return guild_id, _read(row, shape.board)


async def similar(user: User | None, text: str) -> list[IdeaRead]:
    """The open published ideas whose title is close to ``text``, closest
    first: what somebody writing feedback may vote for instead. Close either
    way round, so a few words find a longer title and a long draft finds a
    short one; the threshold decides what shows, not a count."""
    async with _reading(user) as (session, shape):
        closeness = func.greatest(
            func.word_similarity(Task.title, text),
            func.word_similarity(text, Task.title),
        )
        rows = (
            await session.exec(
                _ideas_query(shape)
                .where(closeness >= FUZZY_THRESHOLD)
                .where(
                    cast(TaskStatus.category, String) != TaskStatusCategory.done.value
                )
                .order_by(closeness.desc(), Task.id.desc())
            )
        ).all()
    return [_read(row, shape.board) for row in rows]


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
        shape = _shape(await _board(session), None, past=True)
        category = (
            await session.exec(
                _read_as(
                    shape,
                    select(cast(TaskStatus.category, String)).select_from(Task),
                )
                .where(Task.id == task_id)
                .with_for_update(of=Task, read=True)
            )
        ).first()
        if category is None:
            raise IdeaNotFound
        if category == TaskStatusCategory.done.value:
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


async def _sees_bindings(session: AsyncSession) -> bool:
    """Whether the community ``session`` is routed into binds its streams,
    which only the operations community's schema does, and the session's
    role reads where they land."""
    from app.db.schema_provisioning import guild_schema_name

    guild_id = routed_guild_id(session)
    if guild_id is None:
        return False
    return bool(
        await session.scalar(
            sql_text(
                "SELECT coalesce(has_table_privilege(to_regclass(:t), 'SELECT'), false)"
            ),
            {"t": f'"{guild_schema_name(guild_id)}".intake_bindings'},
        )
    )


async def fill_category(session: AsyncSession, task: Task) -> None:
    """Give ``task`` the category its words name (:func:`category_named`),
    where it is on the Ideas board and its category is empty: one the team
    set stands. Called whenever a task is made or its words change, on the
    session that wrote it, in its transaction; elsewhere than the operations
    community it asks one question of the catalog and stops."""
    if not board_open() or not await _sees_bindings(session):
        return
    # The values this write gave it, so one it set stands.
    await session.flush()
    has_one = (
        select(MetadataValue.entity_id)
        .where(MetadataValue.entity_type == "task")
        .where(MetadataValue.entity_id == task.id)
        .where(MetadataValue.property_id == MetadataDefinition.id)
        .exists()
    )
    field = (
        await session.exec(
            select(MetadataDefinition.id, MetadataDefinition.options)
            .join(
                IntakeBinding,
                IntakeBinding.category_field_id == MetadataDefinition.id,
            )
            .where(IntakeBinding.stream == IntakeStream.ideas.value)
            .where(IntakeBinding.project_id == task.project_id)
            .where(~has_one)
        )
    ).first()
    if field is None:
        return
    options = _options(field.options)
    named = category_named(
        task.title, task.description, [label for _, label in options]
    )
    value = next((v for v, label in options if label == named), None)
    if value is not None:
        await metadata_service.write_on_update(
            session,
            task,
            [PropertyValueInput(property_id=field.id, value=value)],
            merge=True,
        )


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
    # The status the idea reads as, published or not.
    shape = _shape(await _board(session), None, past=True)
    status = (
        await session.exec(
            _read_as(
                shape,
                select(TaskStatus.id, cast(TaskStatus.category, String)).select_from(
                    Task
                ),
                published=False,
            ).where(Task.id == idea.id)
        )
    ).first()
    if (
        sender is not None
        and status is not None
        and status[1] != TaskStatusCategory.done.value
    ):
        await session.exec(
            pg_insert(IdeaVote)
            .values(
                task_id=idea.id,
                user_id=sender,
                voted_at=datetime.now(UTC),
                notified_status_id=status[0],
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
    """The notices owed to voters whose idea now reads as another status,
    each vote marked as told. Read on the operations community's system
    session by the ticket sweep, beside its filers' notices.

    Only what anybody may still read: the system's own role would also see a
    task moved off the board, trashed or held. The status compared is the
    one the idea reads as, so a voter hears it shipped once the release
    carrying it is out.
    """
    if not board_open():
        return []
    shape = _shape(await _board(session), None, past=True)
    rows = await session.exec(
        _read_as(
            shape,
            select(IdeaVote, TaskStatus.id, Task.title, TaskStatus.name)
            .select_from(IdeaVote)
            .join(Task, Task.id == IdeaVote.task_id),
        )
        .where(
            IdeaVote.notified_status_id.is_distinct_from(  # type: ignore[union-attr]
                TaskStatus.id
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
                    "target_path": f"/suggestions/{idea_vote.task_id}",
                },
            )
        )
        idea_vote.notified_status_id = status_id
        session.add(idea_vote)
    return notices
