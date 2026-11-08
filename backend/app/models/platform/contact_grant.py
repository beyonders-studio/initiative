"""What two accounts have agreed between them.

One unordered pair, one row per ``kind``. A **connection** is a mutual link
that satisfies every ``DmPolicy``; a **message** grant is the accepted request
that actually opens the channel. Both are needed to message on ``private``, and
they are separate rows because a connection request may be raised while a
message grant is already accepted.

The pair is canonical (``user_id_low < user_id_high``), so a pair holds at most
one grant of each kind by constraint rather than by handler — and a crossing
request (B asking while A's is pending) collides on the primary key, which the
handler turns into an accept.

Declining deletes the row: there is no ``declined`` state, because the pair is
back where it started and either may ask again.
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import ConfigDict
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
)
from sqlmodel import Enum as SQLEnum
from sqlmodel import Field, SQLModel


class ContactGrantKind(str, Enum):
    #: Mutual link. Satisfies every ``DmPolicy``; opens nothing on its own.
    connection = "connection"
    #: The accepted ask that opens the channel.
    message = "message"


class ContactGrantState(str, Enum):
    pending = "pending"
    accepted = "accepted"


def canonical_pair(a: int, b: int) -> tuple[int, int]:
    """The pair as this table stores it, smaller id first."""
    return (a, b) if a < b else (b, a)


class ContactGrant(SQLModel, table=True):
    __tablename__ = "contact_grants"
    __table_args__ = (
        CheckConstraint(
            "user_id_low < user_id_high", name="ck_contact_grants_ordered_pair"
        ),
        CheckConstraint(
            "requested_by IN (user_id_low, user_id_high)",
            name="ck_contact_grants_requester_in_pair",
        ),
        # The primary key covers the low side as a prefix; this is the other
        # direction, which every "my pending requests" read needs.
        Index("ix_contact_grants_user_high", "user_id_high"),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id_low: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    user_id_high: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    kind: ContactGrantKind = Field(
        sa_column=Column(
            SQLEnum(ContactGrantKind, name="contact_grant_kind"),
            primary_key=True,
        )
    )
    state: ContactGrantState = Field(
        default=ContactGrantState.pending,
        sa_column=Column(
            SQLEnum(ContactGrantState, name="contact_grant_state"),
            nullable=False,
            server_default=ContactGrantState.pending.value,
        ),
    )
    requested_by: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    responded_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
