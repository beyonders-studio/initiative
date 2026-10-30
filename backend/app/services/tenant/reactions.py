"""Emoji reactions on anything reactable.

One table, one service, one set of endpoints for every kind of target. The
registry below is the only place a kind is wired: it says how to load the
target, how to authorize a reaction on it, and what a notification about it
should say. Comments are the first (and today only) member; a feed post joins
by adding a ``ReactionTarget`` member and one entry here.

**Access.** Reacting asks for ``write`` on the thing being reacted to, exactly
as posting a comment does — one gate, one answer, so a surface can never show a
reaction control where it would not show a reply box. Seeing the chips asks for
``read``, so a read-only PAM window can look without leaving a mark.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional, cast

from sqlalchemy import delete as sa_delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import KindMessages, ReactionMessages
from app.core.reactions import ReactionTarget
from app.core.tools import Tool
from app.db import session as db_session
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.tenant.batched_notice import BatchedNotice, BatchedNoticeKind
from app.models.tenant.reaction import Reaction
from app.models.platform.user import User
from app.services.platform import accounts as accounts_service
from app.schemas.tenant.reaction import ReactionGroup, ReactionSummary, ReactionUser
from app.services.tenant.initiative_tools import tool_on
from app.db.session import actor_context

logger = logging.getLogger(__name__)

#: How many reactors a group names. The chip shows a face pile / tooltip, not a
#: roster, and the count is always the whole truth.
MAX_NAMED_REACTORS = 8

#: A ceiling per person per target, so one account cannot turn a comment into
#: an unbounded list of chips.
MAX_REACTIONS_PER_USER = 20


class ReactionError(CodedError):
    """Base error for reaction operations."""


class ReactionNotFoundError(ReactionError):
    """The target does not exist (or is not visible)."""

    status_code = 404


class ReactionPermissionError(ReactionError):
    """The user may not react here."""

    status_code = 403


class ReactionValidationError(ReactionError):
    """The payload is refused."""


class ReactionDisabledError(ReactionError):
    """The target takes no reactions — its own switch is off."""

    status_code = 409


@dataclass(frozen=True)
class TargetContext:
    """A loaded, authorized reaction target.

    ``title`` labels it in a notification, ``author_id`` is who hears about the
    reaction (None when nobody should), and ``about`` is what that notice names
    — a comment's thread, or the post — from which it takes where it sits and
    where it opens.
    """

    target: ReactionTarget
    target_id: int
    title: str
    author_id: Optional[int]
    about: tuple[str, int]


#: Resolver signature: load + authorize one target, or raise.
Resolver = Callable[[AsyncSession, int, User, int, str], Awaitable["TargetContext"]]


async def _resolve_comment(
    session: AsyncSession,
    target_id: int,
    user: User,
    guild_id: int,
    access: str,
) -> TargetContext:
    """A comment is reachable exactly as its own thread is, and writable
    exactly as the thread is postable — the comments service already owns both
    decisions, so it makes them here too."""
    from app.services.tenant import comments as comments_service

    try:
        comment, ctx = await comments_service.get_comment_with_parent(
            session,
            comment_id=target_id,
            user=user,
            guild_id=guild_id,
            access=access,
        )
    except comments_service.CommentNotFoundError as exc:
        raise ReactionNotFoundError(ReactionMessages.TARGET_NOT_FOUND) from exc
    except comments_service.CommentPermissionError as exc:
        raise ReactionPermissionError(ReactionMessages.PERMISSION_DENIED) from exc
    if comment.removed_at is not None:
        # A tombstone has nothing left to react to.
        raise ReactionDisabledError(ReactionMessages.DISABLED)

    return TargetContext(
        target=ReactionTarget.comment,
        target_id=cast(int, comment.id),
        title=ctx.title,
        author_id=comment.created_by,
        about=(cast(str, ctx.ref_type), ctx.entity_id),
    )


async def _resolve_post(
    session: AsyncSession,
    target_id: int,
    user: User,
    guild_id: int,
    access: str,
) -> TargetContext:
    """A post is reachable exactly as the post itself is.

    Reacting is a **read**-level gesture, not a write: a notice everyone on the
    board can see is a notice everyone can react to, the same way anyone who
    can read a comment thread can react in it. So the requested ``access`` is
    not passed through — the resource gate is asked for read either way.
    """
    from app.services import permissions as permissions_service
    from app.services.tenant import posts as posts_service

    post = await posts_service.get_post(session, target_id)
    if post is None:
        raise ReactionNotFoundError(ReactionMessages.TARGET_NOT_FOUND)
    if post.initiative is not None and not tool_on(
        actor_context(session), post.initiative, Tool.post
    ):
        raise ReactionNotFoundError(ReactionMessages.TARGET_NOT_FOUND)
    # The notice's own switch, the counterpart to a thread's. Off means it
    # takes none and shows none, keeping the ones already on it.
    if not post.reactions_enabled:
        raise ReactionDisabledError(ReactionMessages.DISABLED)
    context = db_session.guild_context(session)
    try:
        permissions_service.require_access(
            permissions_service.DAC_RESOURCES[Tool.post],
            post,
            context=context,
            access="read",
        )
    except Exception as exc:  # the DAC engine raises its own HTTP error type
        raise ReactionPermissionError(
            KindMessages.NO_ACCESS, params={"kind": Tool.post.value}
        ) from exc

    return TargetContext(
        target=ReactionTarget.post,
        target_id=cast(int, post.id),
        title=post.name,
        author_id=post.created_by,
        about=(Tool.post.value, cast(int, post.id)),
    )


#: Every reactable kind -> how to load and authorize it. The single wiring point.
TARGET_RESOLVERS: dict[ReactionTarget, Resolver] = {
    ReactionTarget.comment: _resolve_comment,
    ReactionTarget.post: _resolve_post,
}


async def resolve_target(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_id: int,
    user: User,
    guild_id: int,
    access: str = "read",
) -> TargetContext:
    """Load + authorize one reaction target at ``access`` level."""
    return await TARGET_RESOLVERS[target](session, target_id, user, guild_id, access)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


async def load_reactions(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_ids: Sequence[int],
) -> dict[int, list[Reaction]]:
    """Every reaction on each of ``target_ids``, oldest first.

    One query for a whole thread: the comment list serializes its reactions
    from this rather than asking per row. RLS has already decided which of
    these rows the request may see.
    """
    if not target_ids:
        return {}
    rows = (
        await session.exec(
            select(Reaction)
            .where(
                Reaction.target_type == target.value,
                Reaction.target_id.in_(tuple(target_ids)),
            )
            .order_by(Reaction.created_at.asc(), Reaction.id.asc())
            .options(selectinload(Reaction.reactor))
        )
    ).all()
    grouped: dict[int, list[Reaction]] = {target_id: [] for target_id in target_ids}
    for row in rows:
        grouped.setdefault(row.target_id, []).append(row)
    return grouped


def summarize(
    reactions: Iterable[Reaction], *, viewer_id: Optional[int]
) -> list[ReactionGroup]:
    """Collapse rows into one group per emoji, in first-reacted order.

    Ordering by when an emoji first appeared (rather than by count) keeps the
    chips from reshuffling under the cursor as counts change.
    """
    groups: dict[str, ReactionGroup] = {}
    for reaction in reactions:
        group = groups.get(reaction.emoji)
        if group is None:
            group = ReactionGroup(emoji=reaction.emoji, count=0)
            groups[reaction.emoji] = group
        group.count += 1
        if reaction.created_by == viewer_id:
            group.reacted = True
        if len(group.users) < MAX_NAMED_REACTORS and reaction.reactor is not None:
            group.users.append(ReactionUser.model_validate(reaction.reactor))
    return list(groups.values())


async def summary_for(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_id: int,
    viewer_id: Optional[int],
) -> ReactionSummary:
    """The whole reaction state of one target, as the toggle route replies."""
    grouped = await load_reactions(session, target=target, target_ids=[target_id])
    return ReactionSummary(
        target_type=target,
        target_id=target_id,
        groups=summarize(grouped.get(target_id, []), viewer_id=viewer_id),
    )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


async def toggle_reaction(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_id: int,
    emoji: str,
    user: User,
    guild_id: int,
) -> tuple[ReactionSummary, bool]:
    """Add the user's ``emoji`` to a target, or take it back if it is there.

    Returns the target's full reaction state plus whether this call ADDED one —
    the caller needs that to decide whether anyone should be notified.
    """
    ctx = await resolve_target(
        session,
        target=target,
        target_id=target_id,
        user=user,
        guild_id=guild_id,
        # Reacting is answering, not editing: it takes reaching the target.
        access="read",
    )

    # A toggle is one decision made of three statements — is it there, take it
    # back or put it in, and does that leave the ceiling intact — so it is
    # serialized per (person, target) before any of them run. Without this a
    # double tap (which a reaction button invites) can have both requests read
    # "not there yet" and race, and two concurrent adds can each count
    # themselves under the cap.
    #
    # Transaction-scoped, so it releases on commit with no unlock to forget.
    # The key names the person AND the target, so two people reacting to the
    # same comment never wait on each other — only a request racing itself
    # does, which is the only case with anything to serialize.
    await advisory_lock(
        session,
        LockNamespace.REACTION_TOGGLE,
        f"{target.value}:{ctx.target_id}:{user.id}",
    )

    mine = (
        Reaction.target_type == target.value,
        Reaction.target_id == ctx.target_id,
        Reaction.created_by == user.id,
    )

    # The DELETE reports whether there was one to take back, so the branch
    # comes from the statement rather than from a read the next statement then
    # trusts.
    removed = (
        (
            await session.exec(
                sa_delete(Reaction)
                .where(*mine, Reaction.emoji == emoji)
                .returning(Reaction.id)
            )
        )
        .scalars()
        .first()
    )
    if removed is not None:
        await withdraw_batched_notices(session, reaction_ids=[cast(int, removed)])
        await _withdraw_reaction_notification(
            session,
            reaction_id=cast(int, removed),
            reactor=user,
            emoji=emoji,
            ctx=ctx,
            guild_id=guild_id,
        )
        return (
            await summary_for(
                session, target=target, target_id=ctx.target_id, viewer_id=user.id
            ),
            False,
        )

    held = (
        await session.exec(select(func.count()).select_from(Reaction).where(*mine))
    ).one()
    if held >= MAX_REACTIONS_PER_USER:
        raise ReactionValidationError(ReactionMessages.TOO_MANY)

    # ``ON CONFLICT DO NOTHING`` cannot fire while the lock above is held. It
    # stays as the fail-safe: were that lock ever lost, a duplicate degrades to
    # "someone else already added this one" rather than to a 500.
    inserted = (
        (
            await session.exec(
                pg_insert(Reaction)
                .values(
                    target_type=target.value,
                    target_id=ctx.target_id,
                    emoji=emoji,
                    created_by=cast(int, user.id),
                    # Spelled out: this is a Core insert, so the model's
                    # default_factory never runs for it.
                    created_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(constraint="uq_reactions_target_user_emoji")
                .returning(Reaction.id)
            )
        )
        .scalars()
        .first()
    )
    added = inserted is not None

    if added:
        reaction = (
            await session.exec(select(Reaction).where(Reaction.id == inserted))
        ).one()
        await _queue_reaction_notification(
            session, reaction=reaction, reactor=user, ctx=ctx, guild_id=guild_id
        )

    summary = await summary_for(
        session, target=target, target_id=ctx.target_id, viewer_id=user.id
    )
    return summary, added


async def _queue_reaction_notification(
    session: AsyncSession,
    *,
    reaction: Reaction,
    reactor: User,
    ctx: TargetContext,
    guild_id: int,
) -> None:
    """Tell whoever a reaction concerns, as a comment on the same thing would.

    On a comment, its author: somebody answered what they said. Through the
    digest, never at once: a reaction is the lightest signal in the app and
    they arrive in flurries, so the bell gets one entry immediately and
    email/push wait for the queue to settle, exactly as task assignment does.

    On a post, everyone subscribed to it (``personal_items.subscribers_of``),
    on the line their subscription keeps for the post, as a comment on it is
    told.
    """
    from app.models.platform.notification import NotificationType
    from app.services import notifications
    from app.services.tenant import personal_items

    if ctx.target is ReactionTarget.post:
        subject = await notifications.resolve_subject(session, ctx.about)
        if subject is None:
            return
        kind, entity_id = ctx.about
        subscribed = await personal_items.subscribers_of(
            session, {ctx.about: (subject.tool.value, subject.resource_id)}
        )
        name = await notifications.actor_name(session, reactor)
        await notifications.notify(
            session,
            NotificationType.subscription_activity,
            sorted(subscribed[ctx.about]),
            about=subject,
            key="subscription.reacted",
            values={"actor": name, "context": ctx.title},
            data={"entity_type": kind, "entity_id": entity_id, "verb": "reacted"},
            actor=reactor,
            rollup_key=f"subscription:{kind}:{entity_id}",
        )
        return
    if ctx.author_id is None or ctx.author_id == reactor.id:
        return
    # The line names what was reacted to, so it goes only to an author who can
    # still open it.
    subject = await notifications.resolve_subject(session, ctx.about)
    if subject is None or ctx.author_id not in subject.readers:
        return
    # On the system engine: whether they want to hear about this, and where to
    # write to, are facts about their account rather than about this guild.
    author = await accounts_service.load_one(
        ctx.author_id, excluding_ignorers_of=reactor.id
    )
    if author is None:
        return
    await notifications.enqueue_reaction_event(
        session,
        author=author,
        reactor=reactor,
        reaction=reaction,
        context_title=ctx.title,
        subject=subject,
        guild_id=guild_id,
    )


async def _withdraw_reaction_notification(
    session: AsyncSession,
    *,
    reaction_id: int,
    reactor: User,
    emoji: str,
    ctx: TargetContext,
    guild_id: int,
) -> None:
    """Un-say a reaction the author has not read yet.

    The bell rolls reactions up per target, so taking one back means editing
    that line rather than deleting a notification of its own — the notification
    service owns that edit.
    """
    from app.services import notifications

    # A post's subscribers hear of it on their line for the post, as of a
    # comment, which is not taken back.
    if ctx.target is ReactionTarget.post:
        return
    if ctx.author_id is None or ctx.author_id == reactor.id:
        return
    await notifications.withdraw_reaction_event(
        session,
        author_id=ctx.author_id,
        reaction_id=reaction_id,
        reactor_id=cast(int, reactor.id),
        emoji=emoji,
        target_type=ctx.target.value,
        target_id=ctx.target_id,
        guild_id=guild_id,
    )


async def withdraw_batched_notices(
    session: AsyncSession, *, reaction_ids: Sequence[int]
) -> None:
    """Drop not-yet-sent batched lines for reactions that no longer exist.

    Un-reacting within the quiet period should leave no trace; a line that has
    already gone out is not chased.
    """
    if not reaction_ids:
        return
    await session.exec(
        sa_delete(BatchedNotice).where(
            col(BatchedNotice.reaction_id).in_(tuple(reaction_ids)),
            col(BatchedNotice.processed_at).is_(None),
        )
    )


async def purge_reactions_for(
    session: AsyncSession,
    *,
    target: ReactionTarget,
    target_ids: Sequence[int],
) -> None:
    """Hard-delete every reaction on targets that are being purged.

    Reactions name their target polymorphically, so no foreign key carries them
    out with it — the purge path says so explicitly instead. A reaction is its
    reactor's alone, so the platform drops them.
    """
    from app.db.cohorts import exec_as_system

    if not target_ids:
        return
    ids = tuple(target_ids)
    await session.exec(
        sa_delete(BatchedNotice).where(
            col(BatchedNotice.kind) == BatchedNoticeKind.reaction,
            col(BatchedNotice.target_type) == target.value,
            col(BatchedNotice.target_id).in_(ids),
        )
    )
    await exec_as_system(
        session,
        sa_delete(Reaction).where(
            Reaction.target_type == target.value,
            Reaction.target_id.in_(ids),
        ),
    )
