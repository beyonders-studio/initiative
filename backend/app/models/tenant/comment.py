from collections.abc import Iterable
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    ColumnElement,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    and_,
)
from sqlmodel import Field, Relationship

from app.core.tools import COMMENT_TARGETS
from app.db.registry_checks import FROM_REGISTRY, listed
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant._mixins import CreatedByMixin, HoldMixin, SoftDeleteMixin


#: The kinds a comment may be said on, as the CHECK spells them.
def _subject_check(subjects: Iterable[str]) -> str:
    return f"subject_type IN ({listed(subjects)})"


class CommentAudience(str, Enum):
    """Who a comment is said to.

    Every comment is said to the people who can read its thread. A comment on
    an operations case can also be said to the person who filed the case, who
    is not one of them: that is the conversation with them, and it is the only
    part of the case they are ever shown. It is kept apart from the thread:
    the case shows it on its own, and the thread, its counts and its feeds
    never carry it.
    """

    members = "members"
    filer = "filer"


#: The audiences, as the CHECK spells them.
_AUDIENCE_SQL = ", ".join(f"'{a.value}'" for a in CommentAudience)

#: Longest name of what the platform's writer posted a comment as.
SYSTEM_KIND_LENGTH = 32


class Comment(HoldMixin, CreatedByMixin, SoftDeleteMixin, table=True):
    __tablename__ = "comments"
    _display_field = "content"
    __table_args__ = (
        CheckConstraint(
            _subject_check(COMMENT_TARGETS),
            name="ck_comments_subject_type",
            info={FROM_REGISTRY: lambda tools: _subject_check(tools.comment_targets)},
        ),
        # Every read of a thread, a count or a lifecycle walk names one kind
        # and the ids of that kind, so the id leads.
        Index("ix_comments_subject", "subject_id", "subject_type"),
        CheckConstraint(f"audience IN ({_AUDIENCE_SQL})", name="ck_comments_audience"),
    )
    # An import may attribute a comment to the account its author was matched
    # to, and only that: the match is made by a person, one row at a time, in
    # the import wizard's people step. Nothing infers it, and nothing else
    # reassigns authorship — a comment is first-person speech, so outside that
    # confirmed mapping ``created_by`` is never moved to somebody else. An
    # author nobody matched is carried as ``imported_author_name`` instead,
    # which names them without crediting an account here. If the original
    # author has left, the restore goes through and the comment renders as
    # "Deleted user #N" via the existing user-display helpers.

    id: int | None = Field(default=None, primary_key=True)
    content: str = Field(sa_column=Column(Text, nullable=False))
    #: What the comment is said on, as the pair a reaction or an edge names
    #: its end by: a kind from ``COMMENT_TARGETS`` and that row's id. No
    #: foreign key holds the id; the comment's row policy asks the kind's own
    #: table about it, and purging the subject deletes its comments
    #: (``soft_delete``).
    subject_type: str = Field(sa_column=Column(String(32), nullable=False))
    subject_id: int = Field(sa_column=Column(Integer, nullable=False))
    #: Who said this where it came from, when an import could not match them
    #: to an account here. Display text and nothing more: it names a person
    #: without claiming they have an account, so the comment carries no avatar
    #: and no profile link. Null on everything written in this app, which is
    #: almost every comment.
    #:
    #: ``created_by`` still names the import that wrote the row, because
    #: something did write it and every guild-content row says what. The two
    #: together are the honest reading: this app's record of who made the row,
    #: and the source's record of who spoke.
    imported_author_name: str | None = Field(
        default=None,
        sa_column=Column(String(200), nullable=True),
    )
    # A pointer to the comment this answers, not a parent: a reply is its
    # writer's words, so it stays when the comment it answers is deleted —
    # under a tombstone — and is never taken to the trash or frozen with it.
    parent_comment_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("comments.id", ondelete="SET NULL"), nullable=True
        ),
    )
    #: Who it is said to. Members unless somebody chose otherwise when they
    #: wrote it, so nothing reaches the person who filed a case by default.
    audience: CommentAudience = Field(
        default=CommentAudience.members,
        sa_column=Column(
            String(length=16),
            nullable=False,
            server_default=CommentAudience.members.value,
        ),
    )
    #: What the platform posted this as, when the platform posted it — a
    #: repeat noted on an operations case, say. Null on everything a person or
    #: a plug-in wrote; it is what tells the platform's notes from a plug-in's, since
    #: neither names an author.
    system_kind: str | None = Field(
        default=None,
        sa_column=Column(String(length=SYSTEM_KIND_LENGTH), nullable=True),
    )
    #: When it became a tombstone: its words gone, its place in the thread
    #: kept for the replies under it. Set by a moderator's removal, and by its
    #: author's own deletion once the trash lets go of it with replies still
    #: under it. Nobody edits a tombstone, or reacts to it.
    removed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    #: A ``RemovalReason``. Null on one its author deleted.
    removed_reason: str | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    #: The moderation log row that took it down, where a moderator did; that
    #: row holds the words. Null on one its author deleted.
    removal_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # The API calls this the author; the column is the schema-wide
    # ``created_by``, which is what a comment's author IS. The join is spelled
    # out because the target is a view, which carries no foreign key.
    author: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(Comment.created_by) == MemberProfile.id,"
                " Comment.created_by_kind == 'member')"
            ),
            "viewonly": True,
        },
    )


def in_thread():
    """The comments that make up a thread, its counts and its feeds: all but
    the conversation with whoever filed an operations case, which the case
    shows on its own."""
    return Comment.audience == CommentAudience.members


def said_on(kind: str, ids: Any) -> ColumnElement[bool]:
    """The comments said on one subject, or on any of several of one kind: a
    fixed kind and the ids, which is what the subject index is read by.

    ``ids`` is one id (a value or a column to correlate on), or a collection
    of them.
    """
    if isinstance(ids, (list, tuple, set, frozenset)):
        return and_(Comment.subject_type == kind, Comment.subject_id.in_(tuple(ids)))
    return and_(Comment.subject_type == kind, Comment.subject_id == ids)
