"""What a grant was used for, one row per request served through it.

Written by the request audit middleware on the system engine, read back into
the digests a grant's case receives. It holds ids and route templates, never
content: which grant, which route, what it answered, whether it changed
anything, and the thing it named.

Shared (``public``) because a grant is: its rows go with it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
)
from sqlmodel import Field, Index, SQLModel

#: Longest route template kept, and longest thing-kind.
ROUTE_LENGTH = 256
TARGET_TYPE_LENGTH = 64


class AccessGrantActivity(SQLModel, table=True):
    """One request served through an access grant."""

    __tablename__ = "access_grant_activity"
    __table_args__ = (
        Index("ix_access_grant_activity_grant_occurred", "grant_id", "occurred_at"),
    )

    id: int | None = Field(default=None, sa_column=Column(BigInteger, primary_key=True))
    grant_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("access_grants.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    method: str = Field(sa_column=Column(String(length=8), nullable=False))
    #: The route as it is written, never the path typed.
    route: str = Field(sa_column=Column(String(length=ROUTE_LENGTH), nullable=False))
    status: int = Field(sa_column=Column(SmallInteger, nullable=False))
    is_write: bool = Field(sa_column=Column(Boolean, nullable=False))
    #: The thing the route named, where it named one: its kind and id.
    target_type: str | None = Field(
        default=None,
        sa_column=Column(String(length=TARGET_TYPE_LENGTH), nullable=True),
    )
    target_id: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
