"""Post service — loaders, the board's ordering, and the pin rule.

A post is a shareable DAC resource (``resource_type='post'``) holding a
notice as a Lexical editor state. It owns no child content; its comments
belong to the shared comment table like every other tool's, and its reactions
to the shared reaction table.

The one thing that is genuinely this tool's own is the **board order**:
:func:`board_order` puts the live pins first, most recently pinned at the top,
and everything else newest-first behind them. It is written once here so the
list endpoint, the export, and anything else that renders a board cannot
disagree about what "the top" means.
"""

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import or_
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.tenant._mixins import ActorKind
from app.models.tenant.post import Post, board_time, pin_is_live
from app.models.tenant.post_poll import PostPoll
from app.models.tenant.post_read import PostRead
from app.services import permissions as permissions_service


def list_loader_options() -> list:
    """Eager-load what a post *list* row needs: its sharing, its initiative,
    the level the request holds on it, and its tags."""
    return [
        selectinload(Post.grants),
        selectinload(Post.initiative),
        undefer(Post.actions),
        # Who wrote it. A notice is signed — the board shows the person above
        # the headline the way a comment shows its author — so the profile
        # comes with the row rather than costing a query per card.
        selectinload(Post.creator),
        # The question it asks, if it asks one. A board renders its polls, so
        # the options come with the row rather than costing a query per card.
        selectinload(Post.poll).selectinload(PostPoll.options),
    ]


def post_loader_options() -> list:
    """Eager-load everything post serialization + authorization needs."""
    return list_loader_options()


def board_order(*, anchored: bool = False) -> list:
    """The bulletin board's order: live pins on top, then newest first.

    ``anchored`` drops the pinned band. A reader who has jumped to a date is
    reading the board as a chronology, and a pin means "this matters here right
    now" — carrying it to the top of March would answer a question nobody
    asked, and would put the same notice above every month they visit.

    ``pin_is_live()`` is what decides membership of the pinned band, so a pin
    whose expiry has passed falls back into the feed by date without anything
    having to sweep the column. Within the band the most recently pinned notice
    leads; behind it the feed is strictly reverse-chronological, with the id as
    the tiebreak so two posts written in the same instant still order stably.

    The second key reads the pin time *through* the same liveness test rather
    than reading the column directly. A lapsed pin still has a ``pinned_at``,
    and ordering on the raw column would sort it above every post that was
    never pinned at all — putting it back at the top of the board by the very
    expiry that was supposed to take it down.

    The feed is dated by :func:`board_time`, not by when the row was written: a
    notice scheduled for Friday belongs at the top of Friday's board, not
    wherever the moment somebody drafted it would put it.
    """
    from sqlalchemy import case, desc

    chronological = [board_time().desc(), Post.id.desc()]
    if anchored:
        return chronological
    live = pin_is_live()
    return [
        desc(case((live, 1), else_=0)),
        case((live, Post.pinned_at), else_=None).desc().nullslast(),
        *chronological,
    ]


def anchored_clause(until: datetime):
    """The WHERE leg for "start the board here and go back".

    Inclusive, and measured by :func:`board_time` — the same instant the feed
    is ordered by — so the notice a rail's anchor names is the first one the
    page returns rather than the one just above it.
    """
    return board_time() <= until


async def audience_user_ids(
    session: AsyncSession, post: Post, *, exclude: int | None = None
) -> set[int]:
    """Who a notice was shared with — the people to tell about it.

    :func:`permissions.audience`: a post shared with three people notifies
    three people, and a board of a hundred members is not interrupted because
    somebody posted to a subset of it.
    """
    audience = (await permissions_service.audience(session, Tool.post, [post])).get(
        post.id, set()
    )
    if exclude is not None:
        audience.discard(exclude)
    return audience


def unread_clause(user_id: int):
    """The WHERE leg for "notices this reader has not read".

    Unread is the absence of a receipt, so this is a NOT EXISTS rather than a
    flag to keep in step with anything. A notice nobody has opened has no rows
    here at all, which is what keeps the table the size of what has been read
    instead of posts x members.

    Your own notices are never among them. There is no receipt for a notice you
    wrote — the roster is about who it reached, and its author is not somebody
    it had to reach — so without this leg every notice you ever posted would sit
    in your unread filter forever.
    """
    from sqlalchemy import and_, exists

    return and_(
        or_(Post.created_by_kind != ActorKind.member, Post.created_by != user_id),
        ~exists().where(PostRead.post_id == Post.id, PostRead.user_id == user_id),
    )


async def annotate_read_state(
    session: AsyncSession, rows: Sequence[Post], *, user_id: int
) -> None:
    """Stamp ``is_read`` on each post for this reader, in one query.

    A plain attribute, the way the comment count is: the posts table has no
    relationship to the receipts, and a board of twenty must not become twenty
    queries.

    A notice you wrote reads as read, and always has no receipt behind it:
    :func:`mark_read` refuses to record one for an author, because the roster
    counts who a notice reached and its author is not somebody it had to reach.
    Reporting that absence as "unread" would leave your own board permanently
    full of your own notices — and, worse, have the reader tracker keep offering
    receipts the server keeps declining, so the count on the card would drift up
    past what the roster behind it lists.
    """
    ids = [post.id for post in rows if post.id is not None]
    if not ids:
        return
    read_ids = set(
        (
            await session.exec(
                select(PostRead.post_id).where(
                    PostRead.post_id.in_(ids), PostRead.user_id == user_id
                )
            )
        ).all()
    )
    for post in rows:
        mine = post.created_by_kind == ActorKind.member and post.created_by == user_id
        object.__setattr__(post, "is_read", mine or post.id in read_ids)


def current_readers(
    post: Post, reader_ids: Iterable[int], audience: set[int]
) -> set[int]:
    """Of the people who have read this notice, the ones it is still for.

    Sharing changes after a notice goes up: somebody who read it can leave the
    initiative or lose their grant, and their receipt stays behind. The roster
    and the count both answer against the audience as it is NOW, so the two
    sides of the roster are drawn from one set — otherwise "Read 3, Unread 1"
    could describe four people and a board of five.

    Its author is not among them. Writing a notice is not reading it, and the
    roster says so on the other side too.
    """
    return {
        user_id
        for user_id in reader_ids
        if user_id in audience
        and not (
            post.created_by_kind == ActorKind.member and user_id == post.created_by
        )
    }


async def annotate_read_counts(session: AsyncSession, rows: Sequence[Post]) -> None:
    """Stamp ``read_count`` on each post — how many people have read it.

    One query for the page, the way the comment count is done: a board of five
    must not become five more. It returns the readers rather than a count per
    post, because the number shown is the readers the notice is still FOR (see
    :func:`current_readers`) and that is a per-post question no GROUP BY can
    answer. Bounded by the page, which is five.
    """
    ids = [post.id for post in rows if post.id is not None]
    if not ids:
        return
    pairs = (
        await session.exec(
            select(PostRead.post_id, PostRead.user_id).where(PostRead.post_id.in_(ids))
        )
    ).all()
    by_post: dict[int, set[int]] = {}
    for post_id, user_id in pairs:
        by_post.setdefault(post_id, set()).add(user_id)
    audiences = await permissions_service.audience(
        session, Tool.post, [post for post in rows if post.id is not None]
    )
    for post in rows:
        readers = current_readers(
            post, by_post.get(post.id, set()), audiences.get(post.id, set())
        )
        object.__setattr__(post, "read_count", len(readers))


async def list_readers(
    session: AsyncSession, post: Post
) -> tuple[list[Any], list[int]]:
    """Who has read this notice, and who it is still waiting on.

    Both sides are drawn from the notice's current audience —
    :func:`audience_user_ids`, the same set the publication notified. That is
    the only honest denominator: a board of a hundred where a notice went to
    five is not ninety-five people ignoring it, and somebody who has since left
    is on neither side rather than only on one.

    Returns the reader rows (newest first, carrying their profile) and the ids
    of everyone still to read it; the endpoint resolves those ids to people.
    """
    receipts = (
        (
            await session.exec(
                select(PostRead)
                .where(PostRead.post_id == post.id)
                .options(selectinload(PostRead.reader))
                .order_by(PostRead.read_at.desc())
            )
        )
        .unique()
        .all()
    )
    audience = await audience_user_ids(
        session,
        post,
        exclude=post.created_by if post.created_by_kind == ActorKind.member else None,
    )
    read_ids = current_readers(
        post, (receipt.user_id for receipt in receipts), audience
    )
    waiting = audience - read_ids
    return [r for r in receipts if r.user_id in read_ids], sorted(waiting)


async def load_member_profiles(
    session: AsyncSession, user_ids: Sequence[int]
) -> list[Any]:
    """The people behind a set of ids, for a roster. Ordered by handle so the
    list reads the same on every request."""
    from app.models.platform.user_profile_view import MemberProfile

    if not user_ids:
        return []
    rows = (
        await session.exec(
            select(MemberProfile)
            .where(MemberProfile.id.in_(tuple(user_ids)))
            .order_by(MemberProfile.username.asc())
        )
    ).all()
    return list(rows)


async def mark_read(
    session: AsyncSession, post_ids: Sequence[int], *, user_id: int
) -> int:
    """Record that this reader has seen these notices. Returns how many were new.

    An upsert on the composite key, so the board sending the same page twice —
    which it will, every time somebody scrolls back up — costs one statement and
    changes nothing. The first read time is kept rather than refreshed: when
    somebody read a notice is a fact, and looking at it again does not make it
    newer.

    A receipt is only recorded for a notice this reader can actually see, and
    only from somebody other than its author: the ids narrow through the same
    conditions the board's own list applies, so what can be marked read is
    exactly what could be read.

    "Can see" has to include the two standings that reach a notice without a
    grant — a guild admin, and Full access in the notice's initiative — or
    somebody who reads a board perfectly well would leave every notice on it
    permanently unread. The ids may span initiatives, so the second is asked
    per row rather than once for the request.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if not post_ids:
        return 0
    now = datetime.now(UTC)
    # Sharing (including the "Full access" override) is the table's own policy,
    # so the statement asks only what this endpoint adds to it.
    readable = (
        await session.exec(
            select(Post.id).where(
                Post.id.in_(tuple(post_ids)),
                or_(
                    Post.created_by_kind != ActorKind.member, Post.created_by != user_id
                ),
            )
        )
    ).all()
    if not readable:
        return 0
    statement = (
        pg_insert(PostRead)
        .values(
            [
                {"post_id": post_id, "user_id": user_id, "read_at": now}
                for post_id in readable
            ]
        )
        .on_conflict_do_nothing(index_elements=["post_id", "user_id"])
        .returning(PostRead.post_id)
    )
    inserted = (await session.exec(statement)).all()
    return len(inserted)


async def mark_unread(session: AsyncSession, post_id: int, *, user_id: int) -> None:
    """Take this reader's receipt off one notice.

    A delete, because unread is the absence of a row. Silent when there was
    none: asking for a state a thing is already in is not an error.
    """
    from sqlalchemy import delete as sa_delete

    await session.exec(
        sa_delete(PostRead).where(
            PostRead.post_id == post_id, PostRead.user_id == user_id
        )
    )


async def attach_reactions(session: AsyncSession, *posts: Post) -> None:
    """Load every post's reactions in ONE query and stamp them on the rows.

    A plain attribute, the way comments carry theirs: the posts table has no
    relationship to the polymorphic reactions table, and a board of twenty must
    not become twenty queries.
    """
    from app.core.reactions import ReactionTarget
    from app.services.tenant import reactions as reactions_service

    rows = [post for post in posts if post.id is not None]
    if not rows:
        return
    grouped = await reactions_service.load_reactions(
        session,
        target=ReactionTarget.post,
        target_ids=[cast(int, post.id) for post in rows],
    )
    for post in rows:
        object.__setattr__(post, "_reactions", grouped.get(post.id, []))


async def get_post(
    session: AsyncSession,
    post_id: int,
    *,
    populate_existing: bool = False,
) -> Post | None:
    """Fetch a post with the relationships authorization + serialization need.
    RLS scopes the row to the request's guild."""
    stmt = select(Post).where(Post.id == post_id).options(*post_loader_options())
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    return result.one_or_none()
