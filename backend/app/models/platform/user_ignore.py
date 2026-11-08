"""The accounts one person has chosen not to hear from.

A row is one account on one account's list. It is private and one-directional:
the list is the holder's, and who has ignored *you*
is not a question this table answers for anybody on the request path.

What it governs is arrival, not permission — an ignored account's messages,
requests and mentions do not reach the holder, and the holder's own reach is
untouched. The rule that reads the other direction is
``public.dm_deliverable``, which returns a boolean and never a row.

There is nothing on the row to edit, so no UPDATE policy and no UPDATE grant:
a row is (who, whom, when), and stopping is a delete.
"""

from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
)
from sqlmodel import Field, SQLModel


class UserIgnore(SQLModel, table=True):
    __tablename__ = "user_ignores"
    __table_args__ = (
        CheckConstraint("user_id <> ignored_user_id", name="ck_user_ignores_not_self"),
        # The primary key covers ``user_id`` as a prefix, which is the read the
        # page makes. This is the other direction: which of a set of accounts
        # ignores one actor, which the notification fan-out asks.
        Index("ix_user_ignores_ignored_user", "ignored_user_id"),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    ignored_user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
