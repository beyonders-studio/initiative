from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlmodel import Field, Relationship, SQLModel

from app.core.tools import Tool


class UserApiKey(SQLModel, table=True):
    __tablename__ = "user_api_keys"
    __table_args__ = (
        # A key limited to one tool resource is limited to its community and
        # reads only.
        CheckConstraint(
            "(resource_type IS NULL AND resource_id IS NULL) OR "
            "(resource_type IS NOT NULL AND resource_id IS NOT NULL "
            "AND guild_id IS NOT NULL AND read_only)",
            name="user_api_keys_resource_scope",
        ),
        # One per person per resource: making another replaces it.
        Index(
            "ix_user_api_keys_one_per_resource",
            "user_id",
            "guild_id",
            "resource_type",
            "resource_id",
            unique=True,
            postgresql_where=text("resource_type IS NOT NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        foreign_key="users.id", ondelete="CASCADE", nullable=False, index=True
    )
    name: str = Field(nullable=False, max_length=100)
    token_prefix: str = Field(nullable=False, max_length=16, index=True)
    token_hash: str = Field(nullable=False, unique=True, max_length=128)
    is_active: bool = Field(default=True, nullable=False)
    # Least-privilege scoping for machine credentials (e.g. an MCP server).
    # ``read_only`` keys may only issue safe HTTP methods; a ``guild_id``-bound
    # key is pinned to that one guild. Both default to the legacy full-access
    # behavior so existing keys are unchanged.
    read_only: bool = Field(default=False, nullable=False)
    guild_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    # The one tool resource a key reads, named as ``resource_grants`` names
    # it: that resource's feed, for a tool in ``FEED_TOOLS``, and no other
    # route. No FK — the row lives in the guild's schema.
    resource_type: Tool | None = Field(
        default=None, sa_column=Column(String(length=32), nullable=True)
    )
    resource_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    expires_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    user: Optional["User"] = Relationship(back_populates="api_keys")


from app.models.platform.user import User
