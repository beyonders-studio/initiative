"""Comments across every commentable surface.

``TOOL_COMMENT_TARGETS`` is the registry: **every** ``Tool`` entity is
commentable — one nullable FK per tool on ``comments``, drift-tested against
the enum — plus the content-level extras in ``EXTRA_COMMENT_TARGETS``, which
are not tools and anchor to the tool that owns them for access (a task to its
project, a wiki page to its wiki). Reading a thread takes read access on that
anchor, posting takes write access, exactly as it always has for tasks and
files.

Every tool entity also carries its own switch, ``comments_enabled``: while it
is off, that entity's thread is neither readable nor postable and the UI shows
none of it. An extra has no switch of its own, so its anchor's is what answers
for it — a wiki with comments off has no threads on its pages. The task is the
exception: its thread belongs to the task, not to the project's tool surface,
so a project with comments off still has task threads.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional, cast

from sqlalchemy import ColumnElement, and_, exists, func, or_, tuple_
from sqlalchemy.orm import aliased, selectinload
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import (
    CommentMessages,
    KindMessages,
)
from app.core.tools import KINDS, Tool
from app.db.initiative_rls import (
    COMMENT_PARENTS,
    COMMENT_PARENT_COLUMNS as RLS_COMMENT_PARENT_COLUMNS,
)
from app.db.query import ids_in
from app.db.session import guild_context, install_context, routed_guild_id
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant._mixins import tool_models
from app.models.tenant.calendar import Calendar
from app.models.tenant.comment import Comment, CommentAudience, in_thread
from app.models.platform.notification import NotificationType
from app.models.tenant.counter import CounterGroup
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.post import Post
from app.models.tenant.collection import Collection
from app.models.tenant.file import File
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.queue import Queue
from app.models.tenant.wiki import Wiki, WikiPage
from app.models.tenant.task import Task, TaskAssignee
from app.models.platform.user import User
from app.services import keyset_cursor
from app.services.tenant import attachments as attachments_service
from app.services.tenant import content_references, personal_items
from app.services import notifications
from app.services import reachability
from app.services.tenant.mention_parser import (
    extract_mentioned_user_ids,
    extract_mentioned_task_ids,
)

if TYPE_CHECKING:
    from app.schemas.tenant.comment import RecentActivityEntry

logger = logging.getLogger(__name__)


class CommentError(CodedError):
    """Base error for comment operations."""


class CommentNotFoundError(CommentError):
    """Raised when a linked resource cannot be found."""

    status_code = 404


class CommentPermissionError(CommentError):
    """Raised when the user lacks permission to comment."""

    status_code = 403


class CommentValidationError(CommentError):
    """Raised when the payload is inconsistent."""


@dataclass(frozen=True)
class CommentTarget:
    """How one tool binds to comments: its model and the FK column on
    ``comments`` (``{tool}_id``)."""

    tool: Tool
    model: type[SQLModel]

    @property
    def column(self) -> str:
        return f"{self.tool.value}_id"


#: Every tool's model, imported so it is *registered*: a class has to have been
#: imported before ``tool_models`` can find it by table name. Naming them here is
#: what makes the lookup below independent of import order.
_REGISTERED = (
    Calendar,
    CounterGroup,
    Dashboard,
    File,
    Post,
    Project,
    Queue,
    Wiki,
)

# Every Tool is commentable, derived from the enum rather than listed — a new
# tool carries a comment thread the day its model exists. comments_test asserts
# this spans the enum, and that the columns here match the model and the RLS
# parent registry (app.db.initiative_rls._COMMENT_PARENTS).
TOOL_COMMENT_TARGETS: dict[Tool, CommentTarget] = {
    tool: CommentTarget(tool, tool_models()[tool.plural]) for tool in Tool
}


_TARGETS_BY_COLUMN: dict[str, CommentTarget] = {
    target.column: target for target in TOOL_COMMENT_TARGETS.values()
}


@dataclass(frozen=True)
class ExtraCommentTarget:
    """A commentable thing that is NOT a tool — a task, a wiki page.

    It has no sharing and no comment switch of its own, so the tool it belongs
    to answers both; which tool that is, and how a row reaches it, is declared
    once in ``app.db.initiative_rls.COMMENT_PARENTS`` and read from there. What
    is left is what only this layer knows: the model to load and the field
    that titles the thread.
    """

    #: The kind's name — the ``{kind}_id`` column, and what an event or a
    #: notification about this thread calls it.
    kind: str
    model: type[SQLModel]
    #: The column holding what the thread is called.
    title_field: str
    #: Whether the anchoring tool's ``comments_enabled`` governs this thread.
    #: True for a wiki page — the wiki is where that switch is offered, and a
    #: wiki with comments off should have none on its pages. False for a task:
    #: its thread belongs to the task, so a project with comments off still
    #: has task threads. Either way the anchor's SHARING is what admits the
    #: reader.
    anchor_switch: bool = True

    @property
    def column(self) -> str:
        return f"{self.kind}_id"


#: The content-level extras, in the order the parent registry declares them.
EXTRA_COMMENT_TARGETS: dict[str, ExtraCommentTarget] = {
    target.column: target
    for target in (
        ExtraCommentTarget(
            "task",
            Task,
            "title",
            anchor_switch=False,
        ),
        ExtraCommentTarget("wiki_page", WikiPage, "title"),
        # A collection answers for its own thread: its own switch, and the
        # Files switch of its initiative.
        ExtraCommentTarget("collection", Collection, "name"),
    )
}

#: Every comment-parent column, extras first — the single-parent rule and the
#: create/list surfaces all read this tuple. Ordered by the parent registry so
#: this and the policies cannot disagree about the set.
COMMENT_PARENT_COLUMNS: tuple[str, ...] = RLS_COMMENT_PARENT_COLUMNS


async def annotate_comment_counts(
    session: AsyncSession,
    rows: Sequence[Any],
    *,
    column: str,
) -> None:
    """Set ``comment_count`` on each row from one grouped query.

    ``column`` is the comment-parent column these rows are the parent of —
    ``post_id`` for posts, ``queue_id`` for queues, and so on; every member of
    :data:`COMMENT_PARENT_COLUMNS` works. One statement for the whole page,
    rather than a count per row, because a board asks this about twenty posts
    at once.

    Trashed comments are excluded by the soft-delete filter, so a thread that
    was cleared out reads as empty rather than as history.
    """
    if column not in COMMENT_PARENT_COLUMNS:
        raise KeyError(f"{column} is not a comment parent")
    ids = [row.id for row in rows if getattr(row, "id", None) is not None]
    if not ids:
        return
    parent = getattr(Comment, column)
    result = await session.exec(
        select(parent, func.count(Comment.id))
        .where(parent.in_(tuple(ids)))
        .where(in_thread())
        .group_by(parent)
    )
    counts = dict(result.all())
    for row in rows:
        # ``object.__setattr__`` because these are SQLModel rows and the field
        # is not a column — it rides along for serialization only.
        object.__setattr__(row, "comment_count", counts.get(row.id, 0))


@dataclass
class _ParentContext:
    """The resolved parent of a comment, whichever shape it takes.

    A tool comment carries the tool and its row (``tool``/``resource`` set). An
    extra carries its own row as well (``extra``/``extra_row``), plus the tool
    it anchors to — a task also fills ``task``/``project``, which is the pair
    the task notifications and the task serializer read. Either way the fields
    every caller needs — the comments column, the parent id, the initiative
    (``None`` for a guild-level calendar), a display title — are filled.
    """

    column: str
    entity_id: int
    initiative_id: Optional[int]
    title: str
    task: Optional[Task] = None
    project: Optional[Project] = None
    tool: Optional[Tool] = None
    resource: Optional[SQLModel] = None
    extra: Optional[ExtraCommentTarget] = None
    extra_row: Optional[SQLModel] = None

    @property
    def ref_type(self) -> Optional[str]:
        """What a notification about this thread is ABOUT — the extra's own
        kind where there is one, else the tool. Every one of them opens by its
        own id, so this is also where a link to the thread goes."""
        if self.extra is not None:
            return self.extra.kind
        return self.tool.value if self.tool is not None else None


def _single_target(ids: Mapping[str, Optional[int]]) -> tuple[str, int]:
    provided = [(column, value) for column, value in ids.items() if value is not None]
    if len(provided) != 1:
        raise CommentValidationError(CommentMessages.PROVIDE_ONE_ENTITY)
    return provided[0]


def _comment_target(comment: Comment) -> tuple[str, int]:
    for column in COMMENT_PARENT_COLUMNS:
        value = getattr(comment, column)
        if value is not None:
            return column, value
    raise CommentValidationError(CommentMessages.NOT_LINKED)


async def _get_task_context(
    session: AsyncSession,
    *,
    task_id: int,
    guild_id: int,
) -> Optional[_ParentContext]:
    stmt = (
        select(Task, Project, Initiative)
        .join(Project, Project.id == Task.project_id)
        .join(Initiative, Initiative.id == Project.initiative_id)
        .where(
            Task.id == task_id,
        )
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if not row:
        return None
    task, project, initiative = row
    return _ParentContext(
        column="task_id",
        entity_id=cast(int, task.id),
        initiative_id=initiative.id,
        title=task.title,
        task=task,
        project=project,
        extra=EXTRA_COMMENT_TARGETS["task_id"],
        extra_row=task,
    )


async def _get_extra_context(
    session: AsyncSession,
    target: ExtraCommentTarget,
    *,
    entity_id: int,
    guild_id: int,
) -> Optional[_ParentContext]:
    """One extra's row, resolved through the tool that answers for it.

    The anchor is loaded by the same call a comment ON that tool would make, so
    a thread on a page is gated by exactly what a thread on its wiki is gated
    by — the master switch, the comment switch, and the sharing — and only the
    identity of the thread differs.
    """
    parent = COMMENT_PARENTS[target.column]
    statement = select(target.model).where(target.model.id == entity_id)  # type: ignore[attr-defined]
    if parent.governed_by is None:
        statement = statement.options(selectinload(target.model.initiative))  # type: ignore[attr-defined]
    row = (await session.exec(statement)).one_or_none()
    if row is None:
        return None
    if parent.governed_by is None:
        return _ParentContext(
            column=target.column,
            entity_id=cast(int, row.id),
            initiative_id=row.initiative_id,
            title=getattr(row, target.title_field),
            resource=row,
            extra=target,
            extra_row=row,
        )
    anchor = await _get_tool_context(
        session,
        TOOL_COMMENT_TARGETS[parent.governed_by],
        entity_id=getattr(row, cast(str, parent.tool_fk)),
        guild_id=guild_id,
    )
    if anchor is None:
        return None
    anchor.column = target.column
    anchor.entity_id = cast(int, row.id)
    anchor.title = getattr(row, target.title_field)
    anchor.extra = target
    anchor.extra_row = row
    return anchor


async def _get_tool_context(
    session: AsyncSession,
    target: CommentTarget,
    *,
    entity_id: int,
    guild_id: int,
) -> Optional[_ParentContext]:
    """Load one tool row with its initiative. The guild is checked through the
    initiative when the row has one, else through the row itself (a guild-level
    calendar names no initiative)."""
    stmt = (
        select(target.model)
        .where(target.model.id == entity_id)  # type: ignore[attr-defined]
        .options(selectinload(target.model.initiative))  # type: ignore[attr-defined]
    )
    row = (await session.exec(stmt)).one_or_none()
    if row is None:
        return None
    return _ParentContext(
        column=target.column,
        entity_id=cast(int, row.id),
        initiative_id=row.initiative_id,
        title=row.name,
        tool=target.tool,
        resource=row,
    )


async def _load_parent(
    session: AsyncSession,
    *,
    column: str,
    entity_id: int,
    guild_id: int,
) -> Optional[_ParentContext]:
    if column == "task_id":
        return await _get_task_context(session, task_id=entity_id, guild_id=guild_id)
    extra = EXTRA_COMMENT_TARGETS.get(column)
    if extra is not None:
        return await _get_extra_context(
            session, extra, entity_id=entity_id, guild_id=guild_id
        )
    return await _get_tool_context(
        session, _TARGETS_BY_COLUMN[column], entity_id=entity_id, guild_id=guild_id
    )


async def _shares_resource(
    session: AsyncSession,
    id_col: ColumnElement[int],
    *,
    resource_id: int,
) -> bool:
    """Whether this request can reach one resource by id.

    Selecting the id IS the question. The resource's own table carries the
    sharing gate, so a row the request may not reach does not come back, and
    the id is already known — loading the row with its grants to run the engine
    over them would ask what the lookup has just answered.

    Asked at read whatever the caller is doing, which is what the comment
    tables themselves ask: ``DAC_WRITE_COMMANDS`` puts ``comments`` in the
    responding set, so every command on a thread is gated by whether the
    parent is reachable, not by whether it is editable. You may answer a notice
    you cannot rewrite.
    """
    return (
        await session.exec(select(id_col).where(id_col == resource_id))
    ).first() is not None


async def _ensure_parent_access(
    session: AsyncSession,
    ctx: _ParentContext,
    *,
    user: Optional[User],
    access: str = "read",
) -> None:
    """Ensure the user can reach the comment's parent at ``access`` level.

    A task inherits from its project; a tool entity answers for itself. The
    sharing decision is the same one the parent's own endpoints make: the
    tool's master switch first, then its own comment switch, then DAC — where a
    request that reaches the whole guild (guild admin, or a live PAM grant at
    the right level) needs no grant row.

    The comment switch is checked through whatever answers for the thread: a
    tool entity's own, or — for an extra — the tool it anchors to, which is how
    a wiki with comments off has none on its pages. The task is the exception,
    and gets the project's sharing without the project's switch: its thread
    belongs to the task, not to the project's tool surface.
    """
    if ctx.extra is not None and not ctx.extra.anchor_switch:
        # An extra whose thread is its own: admitted by the anchor's sharing,
        # asked none of its switches. The task is the one, and its context
        # carries the project that answers for it.
        anchor_model, anchor_row = Project, ctx.project
    elif ctx.tool is None:
        # An extra that answers for itself, in its tool's switch and its own.
        extra = cast(ExtraCommentTarget, ctx.extra)
        tool = KINDS[extra.kind].tool
        initiative = getattr(ctx.extra_row, "initiative", None)
        if initiative is not None and not getattr(initiative, tool.view_permission):
            raise CommentPermissionError(
                KindMessages.TOOL_NOT_ENABLED, params={"kind": tool.value}
            )
        if not getattr(ctx.extra_row, "comments_enabled", True):
            raise CommentPermissionError(CommentMessages.COMMENTS_DISABLED)
        anchor_model, anchor_row = extra.model, ctx.extra_row
    else:
        target = TOOL_COMMENT_TARGETS[ctx.tool]
        initiative = getattr(ctx.resource, "initiative", None)
        if initiative is not None and not getattr(
            initiative, target.tool.view_permission
        ):
            raise CommentPermissionError(
                KindMessages.TOOL_NOT_ENABLED, params={"kind": target.tool.value}
            )
        if not getattr(ctx.resource, "comments_enabled", True):
            raise CommentPermissionError(CommentMessages.COMMENTS_DISABLED)
        anchor_model, anchor_row = target.model, ctx.resource

    if await _shares_resource(
        session,
        anchor_model.id,  # type: ignore[attr-defined]
        resource_id=cast(int, anchor_row.id),
    ):
        return
    raise CommentPermissionError(CommentMessages.PERMISSION_DENIED)


def serialize_comment(comment: Comment, *, viewer_id: Optional[int] = None):
    """The read shape of one comment. A task comment reports its task's
    project — resolved by whichever service call loaded the parent — through
    the same ``project_id`` field a project comment fills from its own column.

    Reactions come from rows stamped on the comment by
    :func:`attach_reactions`; a comment that was never stamped serializes with
    none rather than issuing a query of its own here.
    """
    from app.schemas.tenant.comment import CommentRead
    from app.services.tenant import reactions as reactions_service

    from app.schemas.tenant.comment import CommentRemoval

    read = CommentRead.model_validate(comment)
    task_project_id = getattr(comment, "_task_project_id", None)
    if task_project_id is not None:
        read.project_id = task_project_id
    removal = removal_of(comment)
    if removal is not None:
        # A tombstone names neither its words nor who wrote them; a deleted
        # comment with replies still under it reads as one.
        read.removed = CommentRemoval(by=removal[0], reason=removal[1])
        read.content = ""
        read.created_by = None
        read.author = None
        read.imported_author_name = None
        read.updated_at = None
        return read
    # Deleting is its author's: a moderator takes a comment down instead.
    read.can_remove = viewer_id is not None and comment.created_by == viewer_id
    rows = getattr(comment, "_reactions", None)
    if rows:
        read.reactions = reactions_service.summarize(rows, viewer_id=viewer_id)
    return read


def removal_of(comment: Comment) -> Optional[tuple[str, Optional[str]]]:
    """Who took ``comment`` out of the conversation, and why: a moderator,
    with a reason, or its author. ``None`` while it stands."""
    if comment.removed_at is not None:
        if comment.removal_id is not None:
            return "moderator", comment.removed_reason
        return "author", None
    if comment.deleted_at is not None:
        # In its author's trash with replies under it (``list_comments``).
        return "author", None
    return None


async def attach_reactions(session: AsyncSession, *comments: Comment) -> None:
    """Load every comment's reactions in ONE query and stamp them on the rows.

    A plain attribute, like ``_task_project_id`` above — the comments table has
    no relationship to the polymorphic reactions table, and a thread of fifty
    must not become fifty queries.
    """
    from app.services.tenant import reactions as reactions_service
    from app.core.reactions import ReactionTarget

    rows = [c for c in comments if c.id is not None]
    if not rows or install_context(session) is not None:
        # An installed plug-in reads no reactions: each is one person's gesture.
        return
    grouped = await reactions_service.load_reactions(
        session,
        target=ReactionTarget.comment,
        target_ids=[cast(int, c.id) for c in rows],
    )
    for comment in rows:
        object.__setattr__(comment, "_reactions", grouped.get(comment.id, []))


async def _get_comment(
    session: AsyncSession,
    *,
    comment_id: int,
) -> Optional[Comment]:
    stmt = select(Comment).where(Comment.id == comment_id)
    result = await session.exec(stmt)
    return result.one_or_none()


def _parent_missing(column: str) -> CommentNotFoundError:
    """The parent a ``{kind}_id`` column names is not there to comment on."""
    return CommentNotFoundError(
        KindMessages.NOT_FOUND, params={"kind": column.removesuffix("_id")}
    )


async def _resolved_parent(
    session: AsyncSession,
    *,
    column: str,
    entity_id: int,
    guild_id: int,
    user: Optional[User],
    access: str,
) -> _ParentContext:
    """Load + authorize one comment parent, raising the comment-shaped errors.

    ``user`` is ``None`` for an installed plug-in, which is in no initiative as a
    member: a parent its policies hid is simply not found.
    """
    ctx = await _load_parent(
        session, column=column, entity_id=entity_id, guild_id=guild_id
    )
    if ctx is None:
        # The policies took the parent out before this ran. In the initiative
        # it is the reader's to know about, so sharing is what refused it.
        table = COMMENT_PARENTS[column].table
        if user is not None and await reachability.reader_is_in_the_initiative(
            table, entity_id, cast(int, user.id), guild_id
        ):
            raise CommentPermissionError(CommentMessages.PERMISSION_DENIED)
        raise _parent_missing(column)
    await _ensure_parent_access(session, ctx, user=user, access=access)
    return ctx


def moderates_thread(session: AsyncSession, initiative_id: Optional[int]) -> bool:
    """Whether this request is in the moderation set of the initiative a
    thread is in (``moderation_acts.may_moderate``): it may take comments down
    and lock or unlock the thread.

    Read off the standing the seam computed, so it costs no query. An
    installed plug-in moderates nothing.
    """
    from app.services.tenant.moderation_acts import may_moderate

    context = guild_context(session)
    if context is None or install_context(session) is not None:
        return False
    return may_moderate(context, initiative_id)


async def _locked_now(session: AsyncSession, ctx: _ParentContext) -> bool:
    """Whether the thread is locked, read after taking its turn: a lock being
    placed at the same moment is committed first, and seen, or waits until
    this write has committed."""
    from app.db.advisory_locks import LockNamespace, advisory_lock

    row = ctx.extra_row if ctx.extra is not None else ctx.resource
    await advisory_lock(
        session,
        LockNamespace.COMMENT_THREAD,
        thread_key(routed_guild_id(session), str(row.__tablename__), int(row.id)),
    )
    model = type(row)
    if not hasattr(model, "comments_locked_at"):
        return False
    # Read again now that it is this write's turn.
    return (
        await session.exec(
            select_including_deleted(model.comments_locked_at).where(model.id == row.id)
        )
    ).first() is not None


def thread_key(guild_id: Optional[int], table: str, row_id: int) -> str:
    """The advisory key one thread takes turns on, for writing in it and for
    locking it (``moderation_acts``)."""
    return f"{guild_id}:{table}:{row_id}"


def thread_locked(ctx: _ParentContext) -> bool:
    """Whether a moderator closed this thread: nothing is added to it or
    edited in it, by anyone, until it is reopened."""
    row = ctx.extra_row if ctx.extra is not None else ctx.resource
    return getattr(row, "comments_locked_at", None) is not None


def _stamp_parent(
    session: AsyncSession, ctx: _ParentContext, *comments: Comment
) -> None:
    """Record what the parent says about loaded rows, for serialization: the
    task's project — a plain attribute, never the ``project_id`` column (that
    names a comment ON a project)."""
    for comment in comments:
        if ctx.project is not None:
            object.__setattr__(comment, "_task_project_id", ctx.project.id)


async def get_comment_with_parent(
    session: AsyncSession,
    *,
    comment_id: int,
    user: Optional[User],
    guild_id: int,
    access: str = "read",
) -> tuple[Comment, _ParentContext]:
    """One comment plus its resolved parent, gated at ``access``.

    The parent is what every decision about a comment runs through — who may
    read the thread, who may add to it — so anything acting ON a comment
    (reactions, the read-back route) resolves both in one call rather than
    re-deriving the chain.
    """
    stmt = (
        select(Comment)
        .where(Comment.id == comment_id)
        .options(selectinload(Comment.author))
    )
    comment = (await session.exec(stmt)).one_or_none()
    if not comment:
        # The policies took it out before this ran. In the initiative it is
        # theirs to know about, so a later gate is what refused it.
        if user is not None and await reachability.reader_is_in_the_initiative(
            "comments", comment_id, cast(int, user.id), guild_id
        ):
            raise CommentPermissionError(CommentMessages.PERMISSION_DENIED)
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)

    column, entity_id = _comment_target(comment)
    ctx = await _resolved_parent(
        session,
        column=column,
        entity_id=entity_id,
        guild_id=guild_id,
        user=user,
        access=access,
    )
    _stamp_parent(session, ctx, comment)
    await attach_reactions(session, comment)
    return comment, ctx


async def get_comment(
    session: AsyncSession,
    *,
    comment_id: int,
    user: Optional[User],
    guild_id: int,
) -> Comment:
    """One comment, gated exactly like listing its parent's thread.

    The read-back half of the event contract: a ``comments.*`` event names an
    id, and this is what resolves it. Access is the parent's — read on the
    task's project or on the tool entity — same as ``list_comments``.
    """
    comment, _ctx = await get_comment_with_parent(
        session, comment_id=comment_id, user=user, guild_id=guild_id, access="read"
    )
    return comment


async def _ensure_said_to_a_filer(
    session: AsyncSession,
    *,
    person: Optional[User],
    column: str,
    entity_id: int,
) -> None:
    """Refuse a comment said to a filer anywhere but a case that has one.

    Read on the poster's own session: a person who can comment on the task can
    read its case row, and nobody else gets this far.
    """
    from app.core.intake import Conversation, IntakeStream, conversation_for
    from app.models.tenant.intake import IntakeCase

    if person is None or column != "task_id":
        raise CommentValidationError(CommentMessages.NOT_SAID_TO_A_FILER)
    case = (
        await session.exec(
            select(IntakeCase.stream, IntakeCase.filer_user_id, IntakeCase.topic).where(
                IntakeCase.task_id == entity_id
            )
        )
    ).first()
    if (
        case is None
        or case[1] is None
        or conversation_for(IntakeStream(case[0]), case[2]) is Conversation.none
    ):
        raise CommentValidationError(CommentMessages.NOT_SAID_TO_A_FILER)


async def create_comment(
    session: AsyncSession,
    *,
    author: User | notifications.PluginAuthor,
    guild_id: int,
    content: str,
    targets: Mapping[str, Optional[int]],
    parent_comment_id: Optional[int] = None,
    audience: CommentAudience = CommentAudience.members,
) -> Comment:
    """Post one comment on one parent, and tell whoever it concerns.

    ``targets`` maps comment-parent columns to ids; exactly one is set.

    ``author`` is the person posting, or the installed plug-in posting as itself:
    its comment names no author, and the notices name the plug-in.

    ``audience`` is ``filer`` for a reply to whoever filed an operations case:
    only a person posts one, only on a case task that has a filer, and only
    where the case's stream holds a conversation.
    """
    person = author if isinstance(author, User) else None
    parent_comment = None
    if parent_comment_id is not None:
        parent_comment = await _get_comment(session, comment_id=parent_comment_id)
        if not parent_comment:
            raise CommentNotFoundError(CommentMessages.PARENT_NOT_FOUND)

    column, entity_id = _single_target(targets)
    ctx = await _resolved_parent(
        session,
        column=column,
        entity_id=entity_id,
        guild_id=guild_id,
        user=person,
        # Answering a thread is not editing what it hangs off — reaching the
        # parent is the gate, and its comment switch is the other half.
        access="read",
    )
    # A locked thread takes nothing new, a moderator's words included:
    # reopening it is how anyone adds to it.
    if await _locked_now(session, ctx):
        raise CommentPermissionError(CommentMessages.LOCKED)
    if parent_comment and getattr(parent_comment, column) != ctx.entity_id:
        raise CommentValidationError(CommentMessages.PARENT_MISMATCH)
    if parent_comment and parent_comment.audience != audience:
        raise CommentValidationError(CommentMessages.AUDIENCE_MISMATCH)
    if audience is CommentAudience.filer:
        await _ensure_said_to_a_filer(
            session, person=person, column=column, entity_id=ctx.entity_id
        )
        from app.services.platform import ticket_stream

        await ticket_stream.queue_for_case(session, ctx.entity_id)

    comment = Comment(
        content=content,
        created_by=author.id,
        parent_comment_id=parent_comment_id,
        audience=audience,
        **{column: ctx.entity_id},
    )
    session.add(comment)
    await session.flush()
    await session.refresh(comment, attribute_names=["author"])
    _stamp_parent(session, ctx, comment)
    await content_references.sync_for_comment(session, comment, author_id=author.id)
    await attachments_service.claim_uploads(session, comment)

    await _process_comment_notifications(
        session,
        comment=comment,
        author=author,
        ctx=ctx,
        parent_comment=parent_comment,
    )

    return comment


async def _task_assignee_ids(session: AsyncSession, task_id: int) -> list[int]:
    """Who a task is assigned to, in assignment order."""
    return list(
        (
            await session.exec(
                select(TaskAssignee.user_id)
                .where(TaskAssignee.task_id == task_id)
                .order_by(TaskAssignee.user_id)
            )
        ).all()
    )


async def notify_task_assignees(
    session: AsyncSession,
    *,
    comment: Comment,
    author: User | notifications.PluginAuthor,
    task: Task,
) -> None:
    """Tell a task's assignees there is a new comment on it, rolled into
    their unread line for the task: a requester's answer on a case somebody
    took, which arrives from outside the community rather than as a comment
    made in it."""
    thread = await notifications.resolve_subject(session, ("task", task.id))
    if thread is None:
        return
    recipients = [
        user_id
        for user_id in await _task_assignee_ids(session, cast(int, task.id))
        if user_id != author.id
    ]
    name = await notifications.actor_name(session, author)
    await notifications.notify(
        session,
        NotificationType.comment_on_task,
        recipients,
        about=thread,
        key="comment.onTask",
        values={"actor": name, "task": task.title},
        data={
            "comment_id": comment.id,
            "task_id": task.id,
            "project_id": task.project_id,
            "commenter_name": name,
            "commenter_id": author.id,
        },
        actor=author,
        rollup_key=f"task:{task.id}",
    )


async def _process_comment_notifications(
    session: AsyncSession,
    *,
    comment: Comment,
    author: User | notifications.PluginAuthor,
    ctx: _ParentContext,
    parent_comment: Comment | None,
) -> None:
    """Tell the people a new comment concerns, each once, in priority order:
    the author of the comment it replies to, the people it @mentions, the
    assignees of a task it #mentions, and everyone subscribed to what it is on
    (``personal_items.subscribers_of``): who made it, who is on it, and who
    follows it.

    Every notice is about the thread, so ``notifications.notify`` sends each
    only to people who can open it; a ``#task`` notice names the mentioned task
    too, so its assignees must also reach that one.
    """
    # Every notice below is about the thread; it is looked up once for all of
    # them. Nobody can open a thread that does not resolve, so nobody is told.
    thread = await notifications.resolve_subject(
        session, (cast(str, ctx.ref_type), ctx.entity_id)
    )
    if thread is None:
        return
    name = await notifications.actor_name(session, author)
    told: set[int] = {author.id} if author.id is not None else set()

    def first_time(user_ids: Sequence[int | None]) -> list[int]:
        fresh = [u for u in dict.fromkeys(user_ids) if u is not None and u not in told]
        told.update(fresh)
        return fresh

    # The thread's own fields: a task by its column, any other parent as an
    # entity.
    where = {"comment_id": comment.id, "task_id": comment.task_id}
    if ctx.task is None:
        where |= {"entity_type": ctx.ref_type, "entity_id": ctx.entity_id}

    if parent_comment is not None:
        await notifications.notify(
            session,
            NotificationType.comment_reply,
            first_time([parent_comment.created_by]),
            about=thread,
            key="comment.reply",
            values={"actor": name, "context": ctx.title},
            data={**where, "replier_name": name, "replier_id": author.id},
            actor=author,
        )

    await notifications.notify(
        session,
        NotificationType.mention,
        first_time(sorted(extract_mentioned_user_ids(comment.content))),
        about=thread,
        key="mention.comment",
        values={"actor": name, "context": ctx.title},
        data={**where, "mentioned_by_name": name, "mentioned_by_id": author.id},
        actor=author,
    )

    for task_id in extract_mentioned_task_ids(comment.content):
        mentioned = (
            await session.exec(select(Task.title).where(Task.id == task_id))
        ).first()
        subject = await notifications.resolve_subject(session, ("task", task_id))
        if mentioned is None or subject is None:
            continue
        assignees = [
            user_id
            for user_id in await _task_assignee_ids(session, task_id)
            if user_id in subject.readers
        ]
        await notifications.notify(
            session,
            NotificationType.mention,
            first_time(assignees),
            about=thread,
            key="mention.task",
            values={"actor": name, "task": mentioned, "context": ctx.title},
            data={
                "comment_id": comment.id,
                "mentioned_task_id": task_id,
                "context_task_id": comment.task_id,
                "context_entity_type": where.get("entity_type"),
                "context_entity_id": where.get("entity_id"),
                "mentioned_by_name": name,
                "mentioned_by_id": author.id,
            },
            actor=author,
        )

    # Last, so anybody the comment names or answers already heard of it
    # above: everyone subscribed to the thing, which includes whoever made it
    # and whoever is assigned to it or going to it, each on the one line they
    # keep for it beside its other changes: what they are given for those
    # named on it, what they follow for everyone else.
    kind, entity_id = thread.about
    subscribed = (
        await personal_items.subscribers_of(
            session, {thread.about: (thread.tool.value, thread.resource_id)}
        )
    )[thread.about]
    for named, notice_type, line in (
        (True, NotificationType.assigned_activity, "assigned"),
        (False, NotificationType.subscription_activity, "subscription"),
    ):
        await notifications.notify(
            session,
            notice_type,
            first_time(
                sorted(
                    person
                    for person, subscriber in subscribed.items()
                    if (subscriber.tie is personal_items.Tie.named) is named
                )
            ),
            about=thread,
            key=f"{line}.commented",
            values={"actor": name, "context": ctx.title},
            data={
                "comment_id": comment.id,
                "entity_type": kind,
                "entity_id": entity_id,
                "verb": "commented",
            },
            actor=author,
            rollup_key=f"{line}:{kind}:{entity_id}",
        )


async def list_comments(
    session: AsyncSession,
    *,
    user: Optional[User],
    guild_id: int,
    targets: Mapping[str, Optional[int]],
    limit: int,
    cursor: Optional[str] = None,
) -> "ThreadPage":
    """One page of a thread, and the cursor for the next, or None at the end.

    A page is ``limit`` conversations — top-level comments, newest first —
    with every reply under them, so a conversation is never split across
    pages. The rows come back in the order they were written.
    """
    column, entity_id = _single_target(targets)
    ctx = await _resolved_parent(
        session,
        column=column,
        entity_id=entity_id,
        guild_id=guild_id,
        user=user,
        access="read",
    )
    # A reply whose parent the reader can't see — held for the platform, say
    # (app.db.holds), or in its author's trash — starts a conversation of its
    # own, under a placeholder. A tombstone its author left is shown only
    # while there is a reply under it to keep a place for.
    parent = aliased(Comment)
    child = aliased(Comment)
    roots = select(Comment.id, Comment.created_at).where(
        getattr(Comment, column) == ctx.entity_id,
        or_(
            Comment.parent_comment_id.is_(None),
            # Trashed counts as absent here for every reader: the trash's own
            # row policy lets its deleter and the community's admin see it.
            ~exists().where(
                parent.id == Comment.parent_comment_id, parent.deleted_at.is_(None)
            ),
        ),
        ~and_(
            Comment.removed_at.is_not(None),
            Comment.removal_id.is_(None),
            ~exists().where(
                child.parent_comment_id == Comment.id, child.deleted_at.is_(None)
            ),
        ),
        in_thread(),
    )
    position = keyset_cursor.decode(cursor)
    if position is not None:
        roots = roots.where(tuple_(Comment.created_at, Comment.id) < position)
    roots = roots.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(
        limit + 1
    )
    root_rows = (await session.exec(roots)).all()
    # One more than asked for is how "is there another page" is answered
    # without a second count query.
    next_cursor = None
    if len(root_rows) > limit:
        last_id, last_created_at = root_rows[limit - 1]
        next_cursor = keyset_cursor.encode(last_created_at, last_id)
    root_ids = [row[0] for row in root_rows[:limit]]
    locked = thread_locked(ctx)
    can_moderate = moderates_thread(session, ctx.initiative_id)
    if not root_ids:
        return ThreadPage([], None, locked, can_moderate)

    # The conversations on this page, every reply at any depth included.
    thread = (
        select(Comment.id).where(Comment.id.in_(root_ids)).cte("thread", recursive=True)
    )
    reply = aliased(Comment)
    thread = thread.union_all(
        select(reply.id).where(
            reply.parent_comment_id == thread.c.id,
            reply.audience == CommentAudience.members,
        )
    )
    stmt = (
        select(Comment)
        .where(Comment.id.in_(select(thread.c.id)))
        .order_by(Comment.created_at.asc(), Comment.id.asc())
        .options(selectinload(Comment.author))
    )
    comments = list((await session.exec(stmt)).all())
    comments = await _with_deleted_parents(
        session, comments, guild_id=guild_id, column=column, entity_id=ctx.entity_id
    )
    _stamp_parent(session, ctx, *comments)
    await attach_reactions(session, *comments)
    return ThreadPage(comments, next_cursor, locked, can_moderate)


@dataclass(frozen=True)
class ThreadPage:
    """One page of a thread, and what the thread says about writing in it."""

    comments: Sequence[Comment]
    next_cursor: Optional[str]
    #: A moderator closed it to new comments.
    locked: bool
    #: The reader moderates the initiative it is in.
    can_moderate: bool


async def _with_deleted_parents(
    session: AsyncSession,
    comments: list[Comment],
    *,
    guild_id: int,
    column: str,
    entity_id: int,
) -> list[Comment]:
    """``comments`` and, in order, the comments their replies answer that are
    in their authors' trash — served as tombstones (``serialize_comment``), so
    the replies read where they were said.

    A trashed row reads only to its deleter and the community's admin, so the
    tombstones are read as the platform, and only what a tombstone shows:
    where it sits, and that it was deleted. A parent held for the platform
    stays absent, under the client's placeholder.
    """
    from app.db import cohorts
    from app.db.request_context import SystemGuild
    from app.db.session import set_rls_context

    present = {c.id for c in comments}
    missing = {
        c.parent_comment_id
        for c in comments
        if c.parent_comment_id is not None and c.parent_comment_id not in present
    }
    if not missing:
        return comments
    async with cohorts.system_session(guild_id) as system:
        await set_rls_context(system, SystemGuild(guild_id, read_only=True))
        deleted = list(
            (
                await system.exec(
                    select_including_deleted(Comment)
                    .where(ids_in(Comment.id, missing))
                    .where(getattr(Comment, column) == entity_id)
                    .where(Comment.deleted_at.is_not(None))  # type: ignore[union-attr]
                    .where(Comment.held_at.is_(None))  # type: ignore[union-attr]
                    .where(in_thread())
                )
            ).all()
        )
        system.expunge_all()
        await system.rollback()
    if not deleted:
        return comments
    from sqlalchemy.orm.attributes import set_committed_value

    for tombstone in deleted:
        # Nothing it said, or who said it, leaves the platform's read.
        tombstone.content = ""
        set_committed_value(tombstone, "author", None)
        object.__setattr__(tombstone, "_reactions", [])
    return sorted([*comments, *deleted], key=lambda c: (c.created_at, c.id or 0))


async def _tell_the_filer(session: AsyncSession, comment: Comment) -> None:
    """A change to what is said with whoever filed a case reaches their open
    ticket pages."""
    if comment.audience is CommentAudience.filer and comment.task_id is not None:
        from app.services.platform import ticket_stream

        await ticket_stream.queue_for_case(session, comment.task_id)


async def delete_comment(
    session: AsyncSession,
    *,
    comment_id: int,
    user: User,
    guild_id: int,
) -> Comment:
    comment = await _get_comment(session, comment_id=comment_id)
    if not comment:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)

    column, entity_id = _comment_target(comment)
    ctx = await _load_parent(
        session, column=column, entity_id=entity_id, guild_id=guild_id
    )
    if ctx is None:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)
    await _ensure_parent_access(session, ctx, user=user, access="read")
    _stamp_parent(session, ctx, comment)

    # Deleting is the author's alone; a moderator takes a comment down
    # instead (``moderation_acts``), which leaves a tombstone and a record.
    if comment.created_by != user.id:
        raise CommentPermissionError(CommentMessages.AUTHOR_ONLY_DELETE)
    if comment.removed_at is not None:
        raise CommentValidationError(CommentMessages.REMOVED)

    from app.services.tenant.soft_delete import trash

    # The comment alone goes to its author's trash: a reply is somebody
    # else's words and stays, under a line saying its author deleted it,
    # until the comment is restored or the trash lets go of it
    # (``soft_delete.hard_purge_entities``).
    await trash(
        session,
        comment,
        deleted_by_user_id=user.id,
    )
    # A trashed comment is out of the conversation, so what it alone pointed at
    # is no longer something this thing references.
    await content_references.sync_for_comment(
        session, comment, author_id=cast(int, user.id)
    )
    await _tell_the_filer(session, comment)
    return comment


async def update_comment(
    session: AsyncSession,
    *,
    comment_id: int,
    user: User,
    guild_id: int,
    content: str,
) -> tuple[Comment, set[str]]:
    """Update a comment's content. Only the original author can edit.

    Also returns the addresses of the pictures the edit took out, for the
    caller to release once it has committed (``release_unshown``).
    """
    comment = await _get_comment(session, comment_id=comment_id)
    if not comment:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)

    # Only the author can edit their own comment
    if comment.created_by != user.id:
        raise CommentPermissionError(CommentMessages.AUTHOR_ONLY_EDIT)
    if comment.removed_at is not None:
        raise CommentValidationError(CommentMessages.REMOVED)

    # Verify access to the linked entity (same checks as delete_comment)
    column, entity_id = _comment_target(comment)
    ctx = await _load_parent(
        session, column=column, entity_id=entity_id, guild_id=guild_id
    )
    if ctx is None:
        raise CommentNotFoundError(CommentMessages.NOT_FOUND)
    await _ensure_parent_access(session, ctx, user=user, access="read")
    # A locked thread stands as it was when it was locked, moderators' words
    # included. Taking one's own comment back is still a delete.
    if await _locked_now(session, ctx):
        raise CommentPermissionError(CommentMessages.LOCKED)
    _stamp_parent(session, ctx, comment)

    previous_content = comment.content
    comment.content = content
    comment.updated_at = datetime.now(timezone.utc)
    session.add(comment)
    await session.flush()
    let_go = attachments_service.upload_urls_in_markdown(
        previous_content
    ) - attachments_service.upload_urls_in_markdown(content)
    await content_references.sync_for_comment(
        session, comment, author_id=cast(int, user.id)
    )
    await attachments_service.claim_uploads(session, comment)
    await session.refresh(comment, attribute_names=["author"])
    # The edit reply is what the client writes back into its cache, so it must
    # carry the reactions the comment still has — serializing without them
    # would blank the chips until the next refetch.
    await attach_reactions(session, comment)
    await _tell_the_filer(session, comment)
    return comment, let_go


async def recent_activity(
    session: AsyncSession, *, viewer_id: int, limit: int
) -> list[RecentActivityEntry]:
    """The community's most recent top-level comments, newest first.

    Only comments on parents the reader can open: the parent tables' own
    policies and the soft-delete filter decide which rows each leg reaches, and
    a thread whose comments or whose tool is switched off is left out.
    """
    from app.schemas.tenant.comment import CommentAuthor, RecentActivityEntry
    from app.services.tenant import reactions as reactions_service
    from app.core.reactions import ReactionTarget

    conditions = [
        Comment.parent_comment_id.is_(None),
        Comment.removed_at.is_(None),
        in_thread(),
    ]
    # A comment is reached through its parent — the task's project, or the
    # tool entity itself — so the sharing gate is applied per kind, each leg a
    # subquery over the parent table (which also drops trashed parents via the
    # session's soft-delete filter). Each clause is a no-op for a request that
    # reaches the whole guild, leaving only "attached to some parent".
    legs = []
    reachable_by_tool = {}
    for tool, target in TOOL_COMMENT_TARGETS.items():
        model = target.model
        fk = getattr(Comment, target.column)
        # The entity's own comment switch gates its thread, so it gates the
        # feed too.
        parent_ids = select(model.id).where(model.comments_enabled.is_(True))
        # The tool's master switch gates the thread, so it gates the feed
        # too. A parent that names no initiative (a guild calendar) has no
        # switch to answer to.
        parent_ids = parent_ids.where(
            or_(
                model.initiative_id.is_(None),
                model.initiative_id.in_(
                    select(Initiative.id).where(
                        getattr(Initiative, tool.view_permission).is_(True)
                    )
                ),
            )
        )
        reachable_by_tool[tool] = parent_ids
        legs.append(and_(fk.isnot(None), fk.in_(parent_ids)))
    # The extras — a thread on something that is not a tool. Each is reached
    # through the tool that owns it, and takes that tool's switches only where
    # its registry entry says they answer for it.
    for column, extra in EXTRA_COMMENT_TARGETS.items():
        parent = COMMENT_PARENTS[column]
        fk = getattr(Comment, column)
        rows = select(extra.model.id)
        if parent.governed_by is None:
            tool = KINDS[extra.kind].tool
            rows = rows.where(
                extra.model.comments_enabled.is_(True),
                extra.model.initiative_id.in_(
                    select(Initiative.id).where(
                        getattr(Initiative, tool.view_permission).is_(True)
                    )
                ),
            )
        elif extra.anchor_switch:
            rows = rows.where(
                getattr(extra.model, parent.tool_fk).in_(
                    reachable_by_tool[parent.governed_by]
                )
            )
        legs.append(and_(fk.isnot(None), fk.in_(rows)))
    conditions.append(or_(*legs))

    stmt = (
        select(Comment)
        .where(*conditions)
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit)
    )
    result = await session.exec(stmt)
    comments = result.all()

    # Batch-load the parents the rows point at
    task_ids = {c.task_id for c in comments if c.task_id}
    tasks_by_id: dict[int, Task] = {}
    projects_by_id: dict[int, Project] = {}
    if task_ids:
        task_result = await session.exec(select(Task).where(Task.id.in_(task_ids)))
        for task in task_result.all():
            tasks_by_id[task.id] = task  # ty: ignore[invalid-assignment] — persisted row, id is set

        project_ids = {t.project_id for t in tasks_by_id.values()}
        if project_ids:
            proj_result = await session.exec(
                select(Project).where(Project.id.in_(project_ids))
            )
            for proj in proj_result.all():
                projects_by_id[proj.id] = proj  # ty: ignore[invalid-assignment] — persisted row, id is set

    # The extras' rows, and the tool row each belongs to — the feed shows the
    # thread's own name and links at its real address, and the initiative is
    # the tool's. The task is loaded above instead: its entry carries the
    # project as well, which no other extra has.
    extra_rows: dict[str, dict[int, object]] = {}
    extra_anchors: dict[str, dict[int, object]] = {}
    for column, extra in EXTRA_COMMENT_TARGETS.items():
        if column == "task_id":
            continue
        parent = COMMENT_PARENTS[column]
        ids = {value for c in comments if (value := getattr(c, column)) is not None}
        rows: dict[int, object] = {}
        anchors: dict[int, object] = {}
        if ids:
            loaded = (
                await session.exec(select(extra.model).where(extra.model.id.in_(ids)))
            ).all()
            rows = {row.id: row for row in loaded}
            if parent.governed_by is None:
                # It is its own anchor.
                extra_rows[column] = extra_anchors[column] = rows
                continue
            anchor_model = TOOL_COMMENT_TARGETS[parent.governed_by].model
            anchor_ids = {getattr(row, parent.tool_fk) for row in loaded}
            if anchor_ids:
                anchors = {
                    anchor.id: anchor
                    for anchor in (
                        await session.exec(
                            select(anchor_model).where(anchor_model.id.in_(anchor_ids))
                        )
                    ).all()
                }
        extra_rows[column] = rows
        extra_anchors[column] = anchors

    rows_by_tool: dict[Tool, dict] = {}
    for tool, target in TOOL_COMMENT_TARGETS.items():
        ids = {
            value for c in comments if (value := getattr(c, target.column)) is not None
        }
        if not ids:
            rows_by_tool[tool] = {}
            continue
        loaded = await session.exec(
            select(target.model).where(target.model.id.in_(ids))
        )
        rows_by_tool[tool] = {row.id: row for row in loaded.all()}

    # The feed's chips, in one query for the whole page rather than one per row.
    reactions_by_comment = await reactions_service.load_reactions(
        session,
        target=ReactionTarget.comment,
        target_ids=[c.id for c in comments],
    )

    entries: list[RecentActivityEntry] = []
    for comment in comments:
        author = comment.author
        author_payload = CommentAuthor.model_validate(author) if author else None
        fields: dict = {
            "comment_id": comment.id,
            "content": comment.content,
            "created_at": comment.created_at,
            "author": author_payload,
            "reactions": reactions_service.summarize(
                reactions_by_comment.get(comment.id, []), viewer_id=viewer_id
            ),
        }
        if comment.task_id:
            task = tasks_by_id.get(comment.task_id)
            project = projects_by_id.get(task.project_id) if task else None
            fields.update(
                project_id=project.id if project else None,
                project_name=project.name if project else None,
                entity_type="task",
                entity_id=comment.task_id,
                entity_name=task.title if task else None,
                initiative_id=project.initiative_id if project else None,
            )
        elif hit := next(
            (
                (column, value)
                for column in extra_rows
                if (value := getattr(comment, column)) is not None
            ),
            None,
        ):
            column, value = hit
            extra = EXTRA_COMMENT_TARGETS[column]
            row = extra_rows[column].get(value)
            tool_fk = COMMENT_PARENTS[column].tool_fk
            anchor = (
                extra_anchors[column].get(getattr(row, tool_fk) if tool_fk else value)
                if row is not None
                else None
            )
            fields.update(
                entity_type=extra.kind,
                entity_id=value,
                entity_name=getattr(row, extra.title_field) if row else None,
                initiative_id=anchor.initiative_id if anchor else None,
            )
        else:
            for tool, target in TOOL_COMMENT_TARGETS.items():
                value = getattr(comment, target.column)
                if value is None:
                    continue
                row = rows_by_tool[tool].get(value)
                fields.update(
                    entity_type=tool.value,
                    entity_id=value,
                    entity_name=row.name if row else None,
                    initiative_id=row.initiative_id if row else None,
                )
                break
        entries.append(RecentActivityEntry(**fields))
    return entries
