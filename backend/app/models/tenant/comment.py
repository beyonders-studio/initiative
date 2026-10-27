from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlmodel import Field, Relationship

from app.core.tools import COMMENT_TARGETS
from app.models.tenant._mixins import CreatedByMixin, HoldMixin, SoftDeleteMixin
from app.models.platform.user_profile_view import MemberProfile


#: The comment columns naming a parent — one per tool plus the content-level
#: extras — as the single-parent CHECK spells them. Derived from the registry
#: so the constraint and the columns below cannot name different sets.
COMMENT_PARENT_COLUMN_SQL = ", ".join(f"{target}_id" for target in COMMENT_TARGETS)


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
        # A comment hangs off exactly ONE parent: one tool entity, or one of
        # the content-level extras. The column list is derived from
        # ``COMMENT_TARGETS``, so a new parent's column joins the rule by
        # existing rather than by being remembered here.
        CheckConstraint(
            f"num_nonnulls({COMMENT_PARENT_COLUMN_SQL}) = 1",
            name="ck_comments_single_parent",
        ),
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

    id: Optional[int] = Field(default=None, primary_key=True)
    content: str = Field(sa_column=Column(Text, nullable=False))
    task_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
        ),
    )
    file_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=True
        ),
    )
    # Tool-entity parents: every Tool is commentable (drift-tested against the
    # enum in comments_test), one nullable FK per tool alongside the original
    # task/file pair. ``project_id`` means a comment ON the project itself;
    # a task comment reports its task's project through the read schema only.
    project_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
        ),
    )
    queue_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("queues.id", ondelete="CASCADE"), nullable=True
        ),
    )
    counter_group_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("counter_groups.id", ondelete="CASCADE"), nullable=True
        ),
    )
    calendar_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("calendars.id", ondelete="CASCADE"), nullable=True
        ),
    )
    dashboard_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("dashboards.id", ondelete="CASCADE"), nullable=True
        ),
    )
    post_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=True
        ),
    )
    wiki_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("wikis.id", ondelete="CASCADE"), nullable=True
        ),
    )
    # A wiki's conversation happens on its pages: a note about the rota belongs
    # on the rota. The wiki's own column above stays a parent so the tool is
    # commentable like every other, but the thread people use is this one.
    wiki_page_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("wiki_pages.id", ondelete="CASCADE"), nullable=True
        ),
    )
    collection_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=True
        ),
    )
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
    imported_author_name: Optional[str] = Field(
        default=None,
        sa_column=Column(String(200), nullable=True),
    )
    # A pointer to the comment this answers, not a parent: a reply is its
    # writer's words, so it stays when the comment it answers is deleted —
    # under a tombstone — and is never taken to the trash or frozen with it.
    parent_comment_id: Optional[int] = Field(
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
    system_kind: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=SYSTEM_KIND_LENGTH), nullable=True),
    )
    #: When it became a tombstone: its words gone, its place in the thread
    #: kept for the replies under it. Set by a moderator's removal, and by its
    #: author's own deletion once the trash lets go of it with replies still
    #: under it. Nobody edits a tombstone, or reacts to it.
    removed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    #: A ``RemovalReason``. Null on one its author deleted.
    removed_reason: Optional[str] = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    #: The moderation log row that took it down, where a moderator did; that
    #: row holds the words. Null on one its author deleted.
    removal_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    # The API calls this the author; the column is the schema-wide
    # ``created_by``, which is what a comment's author IS. The join is spelled
    # out because the target is a view, which carries no foreign key.
    author: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(Comment.created_by) == MemberProfile.id",
            "viewonly": True,
        },
    )


def in_thread():
    """The comments that make up a thread, its counts and its feeds: all but
    the conversation with whoever filed an operations case, which the case
    shows on its own."""
    return Comment.audience == CommentAudience.members
