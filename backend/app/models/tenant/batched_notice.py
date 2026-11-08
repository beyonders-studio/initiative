from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlmodel import Field, SQLModel


class BatchedNoticeKind(str, Enum):
    """What a queued line is about, and so which batch sends it."""

    task_assignment = "task_assignment"
    reaction = "reaction"


class BatchedNotice(SQLModel, table=True):
    """One queued line of a batched email and push.

    A row per (recipient, event), written beside the bell line, held until the
    flurry has settled, then sent with the others waiting for that person as
    one email and one push, marked processed and dropped after a week.
    Denormalized on purpose: the batch reads it after the fact and must not
    depend on what it describes still existing.
    """

    __tablename__ = "batched_notices"
    __table_args__ = (
        CheckConstraint(
            f"kind IN ({', '.join(repr(kind.value) for kind in BatchedNoticeKind)})",
            name="ck_batched_notices_kind",
        ),
        Index("ix_batched_notices_user_id_kind", "user_id", "kind"),
        Index(
            "idx_batched_notices_unprocessed",
            "processed_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False)
    kind: BatchedNoticeKind = Field(sa_column=Column(String(32), nullable=False))
    #: Who did it. Nullable: the line outlives their account.
    actor_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=True),
    )
    actor_name: str = Field(sa_column=Column(String(255), nullable=False))
    #: What it is about: the task assigned, or what was reacted to.
    target_type: str = Field(sa_column=Column(String(32), nullable=False))
    target_id: int = Field(sa_column=Column(Integer, nullable=False))
    #: Where the notice points, resolved when it was queued.
    target_path: str = Field(sa_column=Column(Text, nullable=False))
    #: The task's title, or the title of what the reacted-to thing is on.
    title: str = Field(sa_column=Column(String(255), nullable=False))
    #: An assignment's project.
    project_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
        ),
    )
    project_name: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    #: A reaction's own row, so un-reacting can withdraw a line that has not
    #: gone out yet.
    reaction_id: Optional[int] = Field(default=None, nullable=True, index=True)
    emoji: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    processed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
