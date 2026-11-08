"""Poll service — writing the question, counting the answers.

A poll belongs to exactly one post and is reached through it, so nothing here
authorizes anything: the endpoints resolve the post first, through the same
``resource_access`` seam every other post route uses, and hand the poll over.
What lives here is the part that is genuinely the poll's own — who is allowed
to have answered, and what the numbers mean.

Two rules are worth stating outright, because both are decisions rather than
mechanics:

**A ballot is replaced, never appended to.** Voting sends the whole answer, and
the service clears the voter's previous rows before writing the new ones. That
is what makes changing your mind a vote rather than a second vote, and it is
the same statement whether the poll takes one answer or several.

**A poll's row is the lock its ballots and its edits queue on.** Editing the
question, casting a ballot and retracting one each decide what to write by
reading what has already been answered, so each takes the poll row with
:func:`lock_poll` first and holds it until the transaction commits. That makes
one poll's writes a queue: each sees a settled answer, acts on it, and hands the
row to the next. Whether the poll is still open is asked in the same statement,
against the wall clock at the moment the row is taken — so a ballot is measured
by the deadline in force when it is about to be written, rather than by when its
request arrived.

**Every ballot counts, and the sharing decides only who is still expected to
answer.** A read receipt asks "who still needs to see this", so it is measured
against the audience as it is now and a departed member's receipt drops out of
it. A poll asks "what did people say", and that a person said it does not stop
being true when they leave — so the tallies count every ballot, and the notice's
current audience is used for one thing only: the list of people who have not
answered yet. The two sides then still add up, which is what the narrowing was
there to protect.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import selectinload
from sqlmodel import delete as sa_delete
from sqlmodel import select
from sqlmodel import update as sa_update
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.tenant.post import Post
from app.models.tenant.post_poll import (
    PostPoll,
    PostPollOption,
    PostPollVote,
    poll_is_open,
)
from app.schemas.tenant.post_poll import PollWrite
from app.services.tenant import posts as posts_service


async def poll_audience(session: AsyncSession, post: Post) -> set[int]:
    """Who may answer this notice's question.

    The people the notice was shared with — the same set the publication
    notified and the read roster measures against. Unlike that roster the
    author is included: writing a notice is not reading it, but writing a
    question does not stop you answering it.
    """
    return await posts_service.audience_user_ids(session, post)


async def annotate_poll_state(
    session: AsyncSession, rows: Sequence[Post], *, user_id: int
) -> None:
    """Stamp every poll on this page with its tallies and this reader's ballot.

    One query for the page, the way the comment and read counts are done. It
    reads the ballots rather than aggregating in SQL because two of the three
    numbers it produces are not sums: the reader's own ballot, and the count of
    distinct people.

    ``_total_voters`` is people, not ticks: on a multiple-choice poll somebody
    who picked three answers is one voter, and the larger number would say
    nothing.
    """
    polls = {
        post.poll.id: post
        for post in rows
        if getattr(post, "poll", None) is not None and post.poll.id is not None
    }
    if not polls:
        return
    ballots = (
        await session.exec(
            select(
                PostPollVote.poll_id, PostPollVote.option_id, PostPollVote.user_id
            ).where(PostPollVote.poll_id.in_(tuple(polls)))
        )
    ).all()

    by_poll: dict[int, list[tuple[int, int]]] = {}
    for poll_id, option_id, voter_id in ballots:
        by_poll.setdefault(poll_id, []).append((option_id, voter_id))

    for poll_id, post in polls.items():
        counts: dict[int, int] = {}
        voters: set[int] = set()
        mine: set[int] = set()
        for option_id, voter_id in by_poll.get(poll_id, []):
            counts[option_id] = counts.get(option_id, 0) + 1
            voters.add(voter_id)
            if voter_id == user_id:
                mine.add(option_id)
        poll = post.poll
        object.__setattr__(poll, "_vote_counts", counts)
        object.__setattr__(poll, "_total_voters", len(voters))
        object.__setattr__(poll, "_my_option_ids", mine)
        # Whether anybody has answered — served even where the numbers are
        # withheld, because it is what says the question is now fixed.
        object.__setattr__(poll, "_has_votes", bool(voters))


async def _turnstile(session: AsyncSession, poll: PostPoll, guild_id: int) -> None:
    """Take this poll's turnstile for the rest of the transaction.

    An advisory lock rather than the poll's row: answering a question is not
    editing it, so a voter must not have to hold a lock that asks for write
    access on the notice. Editing and answering take the SAME turnstile, or
    they would not exclude each other at all.

    Keyed by guild as well as poll, because poll ids repeat across guild
    schemas. One key, always the same one, so there is no order for two of
    these to deadlock over.
    """
    await advisory_lock(session, LockNamespace.POST_POLL, f"{guild_id}:{poll.id}")


async def lock_poll(session: AsyncSession, poll: PostPoll, *, guild_id: int) -> None:
    """Hold this poll for the rest of the transaction.

    Held by every path that reads what has been answered and then acts on it,
    so the reading and the acting are one indivisible step.
    """
    await _turnstile(session, poll, guild_id)


async def lock_open_poll(
    session: AsyncSession, poll: PostPoll, *, guild_id: int
) -> bool:
    """Take the poll's turnstile, and answer whether it still takes votes.

    The close time is read once the lock is held — against the wall clock at
    that moment (see :func:`poll_is_open`), not the instant this request's
    transaction began, which is before it loaded the post and before it waited
    its turn. The ballot is then written inside the transaction still holding
    the lock, so one voter's ballots are written one after another and each is
    measured by the deadline in force as it lands.

    The turnstile is shared with the edit path, so a ballot and a rewrite of
    the deadline cannot both be in flight (see :func:`_turnstile`).
    """
    await _turnstile(session, poll, guild_id)
    row = (
        await session.exec(
            select(PostPoll.id).where(PostPoll.id == poll.id, poll_is_open())
        )
    ).first()
    return row is not None


async def open_lapsed_polls(
    session: AsyncSession, post_ids: Sequence[int], *, now: datetime
) -> None:
    """Clear the deadline of these posts' polls where it passed before the post
    went up: a poll is open when its post is published, and its author can set
    a new deadline."""
    if post_ids:
        await session.exec(
            sa_update(PostPoll)
            .where(PostPoll.post_id.in_(post_ids), PostPoll.closes_at <= now)
            .values(closes_at=None)
        )


async def has_votes(session: AsyncSession, poll: PostPoll) -> bool:
    """Whether anybody has answered yet — the gate on rewriting the options."""
    row = (
        await session.exec(
            select(PostPollVote.option_id)
            .where(PostPollVote.poll_id == poll.id)
            .limit(1)
        )
    ).first()
    return row is not None


def options_match(poll: PostPoll, data: PollWrite) -> bool:
    """Whether a rewrite leaves the choices exactly as they were.

    Compared by text in order, which is what a voter answered: an edit that
    only changes the question, the close time or a switch passes, and one that
    adds, removes, renames or reorders a choice does not.

    Asked twice, of two different questions with the same answer: whether to
    refuse the edit (once somebody has answered), and whether to touch the
    option rows at all (never, when nothing changed — see :func:`write_poll`).
    """
    existing = [
        option.text for option in sorted(poll.options or [], key=lambda o: o.position)
    ]
    return existing == [option.text.strip() for option in data.options]


def write_poll(
    post: Post, data: PollWrite, *, poll: PostPoll | None = None
) -> PostPoll:
    """Build or rewrite a post's poll from one payload.

    The option rows are replaced only when the choices actually changed.
    Replacing them is destructive in a way that is easy to miss: the
    relationship is ``delete-orphan``, so the old rows go, and every ballot
    cast for one goes with it on the cascade. An edit that only reworded the
    question would then quietly throw away the answers to it.

    So a rewrite whose choices are identical leaves them exactly where they
    are, ids and all — which is also what makes "everything but the choices
    stays editable" true rather than merely permitted.
    """
    now = datetime.now(UTC)
    if poll is None:
        poll = PostPoll(post_id=post.id, created_at=now)
    poll.question = (data.question or "").strip() or None
    poll.allows_multiple = data.allows_multiple
    poll.is_anonymous = data.is_anonymous
    poll.hide_results = data.hide_results
    poll.closes_at = data.closes_at
    poll.updated_at = now
    if not options_match(poll, data):
        poll.options = [
            PostPollOption(position=index, text=option.text.strip())
            for index, option in enumerate(data.options)
        ]
    return poll


async def cast_vote(
    session: AsyncSession, poll: PostPoll, *, user_id: int, option_ids: Sequence[int]
) -> None:
    """Record this person's answer, replacing whatever they answered before.

    The ids are checked against the poll's own options rather than trusted, so
    a ballot cannot name a choice from somebody else's question. An empty list
    is a retraction, which is what the DELETE route sends.
    """
    valid = {option.id for option in poll.options or []}
    chosen = [option_id for option_id in option_ids if option_id in valid]
    await retract_vote(session, poll, user_id=user_id)
    if not chosen:
        return
    now = datetime.now(UTC)
    for option_id in chosen:
        session.add(
            PostPollVote(
                poll_id=poll.id, option_id=option_id, user_id=user_id, created_at=now
            )
        )


async def retract_vote(session: AsyncSession, poll: PostPoll, *, user_id: int) -> None:
    """Take this person's whole ballot off the poll. Silent when there was
    none: asking for a state a thing is already in is not an error."""
    await session.exec(
        sa_delete(PostPollVote).where(
            PostPollVote.poll_id == poll.id, PostPollVote.user_id == user_id
        )
    )


async def list_voters(
    session: AsyncSession, post: Post, poll: PostPoll
) -> tuple[dict[int, list[Any]], list[int]]:
    """Who chose what, and who has not answered.

    Returns the voters grouped by option (carrying their profiles) and the ids
    of everybody still to answer. Every ballot is named — the same rows the
    tallies count, so the roster adds up to the number above it — and the
    waiting side is the notice's current audience minus whoever has answered.
    """
    ballots = (
        (
            await session.exec(
                select(PostPollVote)
                .where(PostPollVote.poll_id == poll.id)
                .options(selectinload(PostPollVote.voter))
                .order_by(PostPollVote.created_at.asc())
            )
        )
        .unique()
        .all()
    )
    by_option: dict[int, list[Any]] = {
        option.id: [] for option in poll.options or [] if option.id is not None
    }
    answered: set[int] = set()
    for ballot in ballots:
        answered.add(ballot.user_id)
        if ballot.voter is None:
            continue
        by_option.setdefault(ballot.option_id, []).append(ballot.voter)
    waiting = await poll_audience(session, post) - answered
    return by_option, sorted(waiting)
