from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile


class PostRead(SQLModel, table=True):
    """One person has read one notice.

    A row exists only once somebody has read the post, so the table is the set
    of (post, reader) pairs rather than a grid of every member against every
    notice — an unread post is the absence of a row, which is also what makes
    "mark unread" a delete rather than a second state to keep consistent.

    The board marks a notice read when it has been on screen, which means this
    is written far more often than it is read and almost always as a batch: the
    endpoint takes a list of ids and upserts them in one statement.

    Reading is not editing, so a row records nothing about the notice itself.
    Deleting the post takes its receipts with it (``ON DELETE CASCADE``), which
    is right: they were facts about a thing that no longer exists.
    """

    __tablename__ = "post_reads"

    post_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    #: No FK to ``users``: that table is in ``public`` and this one is per-guild,
    #: the same shape every other reader-scoped column here takes.
    user_id: int = Field(primary_key=True, nullable=False, index=True)
    read_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Who read it, for the roster. Spelled out because the target is a view and
    # carries no foreign key — the same join the reaction's reactor uses.
    reader: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(PostRead.user_id) == MemberProfile.id",
            "viewonly": True,
        },
    )
