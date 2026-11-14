from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, Relationship, SQLModel

from app.models.tenant._mixins import CreatedByMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.tenant.post import Post


#: A poll asks one question, so the shortest useful one offers a choice.
MIN_POLL_OPTIONS = 2
#: And a board is read at a glance: past ten choices it stops being a question
#: and starts being a form.
MAX_POLL_OPTIONS = 10
#: One line of an answer. Anything longer belongs in the notice above it.
MAX_POLL_OPTION_CHARS = 200


class PostPoll(CreatedByMixin, table=True):
    """The question one notice asks.

    A post has at most one poll — the unique key on ``post_id`` says so — which
    is what lets the whole thing be addressed as ``/posts/{id}/poll`` and lets a
    card render the question under the body without asking which of several it
    means. A notice that needs two questions is two notices.

    A table of its own rather than columns on ``posts`` because a poll is five
    settings and a list of options that most notices do not have, and the board
    reads ``posts`` on every page. It carries no ``initiative_id``: it is
    reached through its post, and that is also how RLS resolves it.

    The four switches are the ones a poll actually needs, and each is a
    different question:

    * ``allows_multiple`` — whether a voter picks one answer or several.
    * ``closes_at`` — when voting stops. NULL means it stays open; the value is
      compared to the clock rather than swept, so nothing has to run for a poll
      to close.
    * ``is_anonymous`` — whether the roster names who chose what. Counts are
      shown either way; what this hides is the names behind them.
    * ``hide_results`` — whether the counts themselves wait until the reader
      has voted (or the poll has closed), so early answers do not steer later
      ones.
    """

    __tablename__ = "post_polls"
    __table_args__ = (UniqueConstraint("post_id", name="uq_post_polls_post_id"),)

    id: int | None = Field(default=None, primary_key=True)
    post_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    #: The question, when the headline is not already it. A notice that reads
    #: "Which night works?" needs nothing here.
    question: str | None = Field(default=None, nullable=True, max_length=255)
    allows_multiple: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    is_anonymous: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    hide_results: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    #: When voting stops. NULL leaves it open for as long as the notice stands.
    closes_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    post: Optional["Post"] = Relationship(back_populates="poll")
    options: list["PostPollOption"] = Relationship(
        back_populates="poll",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "PostPollOption.position",
        },
    )

    def is_closed(self, now: datetime | None = None) -> bool:
        """Whether voting has stopped — the Python side of
        :func:`poll_is_open`, for a poll already loaded."""
        if self.closes_at is None:
            return False
        return self.closes_at <= (now or datetime.now(UTC))


class PostPollOption(CreatedByMixin, table=True):
    """One answer somebody may pick.

    ``position`` is the order the author wrote them in, kept rather than sorted
    so "Yes / No / Maybe" does not come back alphabetised. Deleting the poll
    takes its options and, through them, its votes.

    The unique key on ``(poll_id, id)`` is redundant against the primary key on
    its own; it exists so a vote can carry a foreign key over BOTH columns and
    the database — not the service — guarantees a vote's ``poll_id`` names the
    same poll its option belongs to.
    """

    __tablename__ = "post_poll_options"
    __table_args__ = (
        UniqueConstraint("poll_id", "id", name="uq_post_poll_options_poll_id_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    #: Optional in Python, ``NOT NULL`` in the database: an option is built as
    #: part of its poll and the relationship fills this on flush, so requiring
    #: it in the constructor would only mean flushing the poll first to learn
    #: an id the same statement is about to assign.
    poll_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("post_polls.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default=text("0")),
    )
    text: str = Field(nullable=False, max_length=MAX_POLL_OPTION_CHARS)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    poll: PostPoll | None = Relationship(back_populates="options")


class PostPollVote(SQLModel, table=True):
    """One person picked one answer.

    A multiple-choice poll is several rows for the same voter, which is why the
    key is ``(option_id, user_id)`` rather than ``(poll_id, user_id)`` — the
    "only one" rule of a single-choice poll is the service's, applied by
    clearing the voter's rows before writing the new ones, because it is a rule
    that can be switched off.

    ``poll_id`` is stored beside the option rather than joined to: it is how the
    voter's whole ballot is read and cleared in one statement, and how RLS
    reaches the post in two hops instead of three. It cannot drift from the
    option — the foreign key spans both columns.

    No FK to ``users``: that table is in ``public`` and this one is per-guild.
    """

    __tablename__ = "post_poll_votes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["poll_id", "option_id"],
            ["post_poll_options.poll_id", "post_poll_options.id"],
            ondelete="CASCADE",
            name="fk_post_poll_votes_option",
        ),
    )

    poll_id: int = Field(nullable=False, index=True)
    option_id: int = Field(primary_key=True, nullable=False)
    user_id: int = Field(primary_key=True, nullable=False, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Who voted, for the roster. Spelled out because the target is a view and
    # carries no foreign key — the same join the receipt's reader uses.
    voter: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(PostPollVote.user_id) == MemberProfile.id",
            "viewonly": True,
        },
    )


def poll_is_open():
    """The SQL predicate for "this poll still takes votes".

    Written once so the vote endpoint and anything that lists open polls cannot
    disagree about the boundary case of a close time that has just passed.

    ``clock_timestamp()``, not ``now()``. Postgres fixes ``now()`` at the start
    of the transaction, and a ballot's transaction starts well before it reaches
    this predicate — it has a post to load and authorize first, and then a row
    to wait its turn for. Measuring against the transaction's own beginning
    would judge the deadline by when the request arrived rather than by when it
    is about to write. The wall clock is what a deadline means.

    The cost is that this is not stable across a statement, so it belongs on a
    write gate deciding one row and not in a listing, where two rows either side
    of the instant would make an inconsistent page. ``pin_is_live`` is the
    listing case and keeps ``now()`` for exactly that reason.
    """
    from sqlalchemy import func, or_

    return or_(
        PostPoll.closes_at.is_(None),
        PostPoll.closes_at > func.clock_timestamp(),
    )
