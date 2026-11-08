"""What one account may dress its profile in, beyond what ships with the app.

A row is one decoration one person has. It is written when a marketplace pack
is installed and removed when that pack goes; grants are issued rather than
self-served, so the request path holds SELECT on this table and no write verb.

Own-row by policy: a library is the person's, and the only question anyone else
asks about it has already been answered by the profile they are looking at.
"""

from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlmodel import Field, SQLModel


class UserDecoration(SQLModel, table=True):
    __tablename__ = "user_decorations"
    __table_args__ = (
        # Granting and revoking happen a pack at a time, for one person.
        Index("ix_user_decorations_source", "user_id", "source"),
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
    #: The catalog id — ``core.aurora``, or whatever a pack published.
    decoration_id: str = Field(sa_column=Column(String(64), primary_key=True))
    #: Which slot it goes in: banner, frame or trophy. Recorded on the grant
    #: rather than looked up, because the catalog that defines a pack's
    #: decorations is the pack's, and it may be gone by the time this is read.
    kind: str = Field(sa_column=Column(String(16), nullable=False))
    #: The pack this came from, for granting and revoking as one. NULL means it
    #: was granted on its own.
    source: str | None = Field(
        default=None, sa_column=Column(String(120), nullable=True)
    )
    acquired_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
