"""One notice for one person, written down instead of delivered.

``notifications.notify`` decides who hears about something and what it says,
and writes one row here per recipient in the request that caused it. A worker
then writes the bell line, queues the email and sends the push. That split
keeps delivery off the request path: a post that reaches a thousand people
costs its request one insert rather than a thousand bell writes and FCM calls.

A row holds what the notice says, already rendered in the recipient's language
and already narrowed by the deployment's and the community's switches — so it
never carries more than the notice will. Whether each channel is wanted is
decided at delivery, from the recipient's settings as they stand then.

The request path appends and never reads; the worker owns the rest, and the
grants say exactly that. A row is deleted once it has been delivered: the bell
line is the record.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class NoticeOutboxItem(SQLModel, table=True):
    __tablename__ = "notice_outbox"
    __table_args__ = (
        # The worker's scan: whose notices are due.
        Index("ix_notice_outbox_due", "deliver_after", "user_id"),
    )

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        )
    )
    guild_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=True
        ),
    )
    #: What the worker does with it: ``notice`` writes or joins a bell line,
    #: ``reaction`` rolls a reaction into the line for what was reacted to,
    #: ``withdraw`` takes one back out, ``push`` is a push with no line of
    #: its own — a digest's or a hold summary's — and ``record`` writes a line
    #: already read, with nothing else. One recipient's rows apply in order.
    kind: str = Field(
        default="notice",
        sa_column=Column(String(16), nullable=False, server_default="notice"),
    )
    #: A ``NotificationType`` value.
    type: str = Field(sa_column=Column(String(64), nullable=False))
    #: The bell line's payload, as ``notify`` built it; for a push of its own,
    #: the ``communities`` it gathers from.
    data: dict[str, Any] = Field(sa_column=Column(JSONB, nullable=False))
    #: The thread a rolled-up line belongs to, and who it names; null for a
    #: notice that is a line of its own.
    rollup_key: str | None = Field(default=None, sa_column=Column(Text))
    actor_id: int | None = Field(default=None, sa_column=Column(Integer))
    actor_name: str | None = Field(default=None, sa_column=Column(Text))
    #: What the push says; null when no push may go.
    push_title: str | None = Field(default=None, sa_column=Column(Text))
    push_body: str | None = Field(default=None, sa_column=Column(Text))
    push_data: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    #: The email's pieces; null when no email may go.
    email_subject: str | None = Field(default=None, sa_column=Column(Text))
    email_headline: str | None = Field(default=None, sa_column=Column(Text))
    email_body: str | None = Field(default=None, sa_column=Column(Text))
    email_link: str | None = Field(default=None, sa_column=Column(Text))
    email_link_label: str | None = Field(default=None, sa_column=Column(Text))
    #: Whether reading the bell line makes the email unnecessary.
    email_names_line: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: The earliest the worker may take it: now, or later after a failed push.
    deliver_after: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: Held by the pass delivering it. Older than the lease means that pass
    #: never finished, and another may take it.
    claimed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    #: Set once the bell line and the email are written, so a push that has to
    #: be tried again does not write them twice.
    bell_written_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
