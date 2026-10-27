"""A member asking for access to something they can't open, or can't edit.

Shaped like ``resource_grants``, whose rows answering it makes: the resource
is a ``(resource_type, resource_id)`` pair with no foreign key, inert once the
resource is gone. The requester names the rung they want (``read`` or
``write``); whoever may share the resource answers, with the rung they give
and whether it goes to the requester alone or to the whole initiative.

One request is open per person and resource at a time; answered ones stay as
the record of what was asked and given. Requests made together share a
``batch_id``, which one notice names.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Uuid,
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

from app.core.tools import Tool


class ShareRequestStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    declined = "declined"


class ShareRequestScope(str, Enum):
    """Who an approval reached: the requester, or every member of the
    initiative."""

    user = "user"
    initiative = "initiative"


#: The most a note to the person asked may say.
MAX_MESSAGE_LENGTH = 1000


class ShareRequest(SQLModel, table=True):
    __tablename__ = "share_requests"
    __table_args__ = (
        CheckConstraint("level IN ('read', 'write')", name="ck_share_requests_level"),
        CheckConstraint(
            "granted_level IS NULL OR granted_level IN ('read', 'write')",
            name="ck_share_requests_granted_level",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'declined')",
            name="ck_share_requests_status",
        ),
        CheckConstraint(
            "scope IS NULL OR scope IN ('user', 'initiative')",
            name="ck_share_requests_scope",
        ),
        # An approval says what it gave and to whom; nothing else does.
        CheckConstraint(
            "(status = 'approved') = (granted_level IS NOT NULL AND scope IS NOT NULL)",
            name="ck_share_requests_answer",
        ),
        Index(
            "uq_share_requests_pending",
            "resource_type",
            "resource_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_share_requests_resource", "resource_type", "resource_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    resource_type: Tool = Field(sa_column=Column(String(length=32), nullable=False))
    resource_id: int = Field(sa_column=Column(Integer, nullable=False))
    user_id: int = Field(
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    )
    #: The requests made together — a collection's hidden files, asked for at
    #: once — which one notice tells each person asked about.
    batch_id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(Uuid, nullable=False, index=True),
    )
    #: The rung asked for.
    level: str = Field(sa_column=Column(String(length=16), nullable=False))
    status: str = Field(
        default=ShareRequestStatus.pending.value,
        sa_column=Column(
            String(length=16),
            nullable=False,
            server_default=ShareRequestStatus.pending.value,
        ),
    )
    #: What an approval gave, and to whom.
    granted_level: Optional[str] = Field(
        default=None, sa_column=Column(String(length=16), nullable=True)
    )
    scope: Optional[str] = Field(
        default=None, sa_column=Column(String(length=16), nullable=True)
    )
    #: A note from the requester to whoever answers.
    message: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    resolved_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    resolved_by: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=True),
    )
