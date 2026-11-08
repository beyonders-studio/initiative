from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship

from app.core.tools import Tool
from app.models.tenant._mixins import (
    ArchiveMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    HoldMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    attach_actions,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.post_poll import PostPoll
    from app.models.tenant.resource_grant import ResourceGrant


class Post(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    """One notice on an initiative's bulletin board.

    A post is a whole tool entity rather than a child row, which is what gives
    it the surfaces a notice needs and a child row never has: its own sharing
    (``resource_grants``), its own comment thread with the per-entity switch
    every tool carries, tags, the trash can, and a URL to link at. The board
    itself is the initiative's post list — newest first, with the pinned ones
    lifted above.

    ``name`` is the headline (the shared display column every tool spells the
    same) and ``body`` is a Lexical editor state, the same shape a native
    file stores. That is what buys a post inline images and real smart
    chips — a chip shows a fact ABOUT the thing it names (a task's column, a
    counter's reading) and keeps showing the current one, which the reference
    syntax comment text uses cannot do.

    A board renders bodies, not headlines, so the list endpoint returns them
    and pages small. ``excerpt`` (derived, never stored) is for the surfaces
    that show a post in one line — recents, search, the guild table.

    Pinning is deliberately three columns rather than a boolean. ``pinned_at``
    orders the pinned band among itself, ``pinned_by`` records who lifted it,
    and ``pin_expires_at`` lets a notice about a date stop shouting after it.
    A pin is live while ``pinned_at`` is set and the expiry is unset or still
    in the future — ``pin_is_live`` renders that one rule for SQL, and
    ``is_pinned_now`` answers it in Python for a row already loaded.

    **Publication is two columns: an intention and a fact.** ``scheduled_for``
    is when the author asked for it to go up; ``published_at`` is when it
    actually did. A notice posted now is written with ``published_at`` already
    set and no schedule. A scheduled one is written with neither, and the
    publication sweep stamps ``published_at`` when its time comes.

    Splitting them is what makes every other surface simple. "Is this live?" is
    ``published_at IS NOT NULL`` and nothing has to compare a stored time to
    the clock; the sweep claims a due post by writing a column that was NULL,
    so a claim is atomic and can only happen once; and because the stamp is a
    real write to the row, the search index — which cannot fire on the passage
    of time — is refreshed by the same statement that publishes.
    """

    __tablename__ = "posts"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__: ClassVar[dict[str, bool]] = {"implicit_returning": False}

    id: int | None = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    # The counterpart to ``comments_enabled``: a notice people read without
    # reacting to it. On posts rather than in a mixin, because reactions hang
    # off comments and off posts and off nothing else.
    reactions_enabled: bool = Field(
        default=True,
        nullable=False,
        sa_column_kwargs={"server_default": "true"},
    )
    body: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    # Set when a manager lifts the post above the feed; NULL is the normal
    # state. The pair below is meaningless while this is NULL.
    pinned_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    pinned_by: int | None = Field(default=None, nullable=True)
    pin_expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # When the author asked for it to go up. NULL on a notice posted straight
    # away — there was nothing to schedule.
    scheduled_for: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    # When it went up. NULL means it has not yet: only people who can write it
    # can see it, and it is in no board, count, or search index.
    published_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship()
    creator: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(Post.created_by) == MemberProfile.id",
            "viewonly": True,
        }
    )
    grants: list["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Post.id, "
                "ResourceGrant.resource_type == 'post')"
            ),
            "viewonly": True,
        }
    )
    # The question this notice asks, if it asks one. At most one — a notice
    # that needs two questions is two notices — so the relationship is
    # singular and the uniqueness is a key on the child table.
    poll: Optional["PostPoll"] = Relationship(
        back_populates="post",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )

    @property
    def is_published(self) -> bool:
        """Whether this notice is live — the Python side of
        :func:`is_published_clause`."""
        return self.published_at is not None

    def is_pinned_now(self, now: datetime | None = None) -> bool:
        """Whether this row's pin is live — the Python side of
        :func:`pin_is_live`, for a post already loaded."""
        if self.pinned_at is None:
            return False
        if self.pin_expires_at is None:
            return True
        return self.pin_expires_at > (now or datetime.now(UTC))


def pin_is_live():
    """The SQL predicate for "this post's pin is still in force".

    Written once and used by every ordering and filter, so the board, the
    counts, and the serializer cannot disagree about what is pinned. An expiry
    that has passed reads exactly like no pin at all — nothing sweeps the
    columns, because a lapsed pin is still a record of who pinned it and when.
    """
    from sqlalchemy import and_, func, or_

    return and_(
        Post.pinned_at.is_not(None),
        or_(
            Post.pin_expires_at.is_(None),
            Post.pin_expires_at > func.now(),
        ),
    )


def is_published_clause():
    """The SQL predicate for "this notice is live".

    One column test, because publishing is recorded as a fact rather than
    inferred by comparing a schedule to the clock. Every board, count and
    listing appends this, so none of them can disagree with the sweep about
    which notices exist yet.
    """
    return Post.published_at.is_not(None)


def board_time():
    """The instant a board sorts a post by.

    Its publication for a live notice; for a draft — which only its writers
    see — the time it is due, so a scheduled notice previews where it will
    land. ``created_at`` is the floor for a draft with no schedule at all.
    """
    from sqlalchemy import func

    return func.coalesce(Post.published_at, Post.scheduled_for, Post.created_at)


attach_actions(Post, Tool.post)
