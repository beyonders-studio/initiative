"""Operator-owned AI connections (platform config mode).

The single source of truth for ``ai_config_mode == "platform"``: the
operator configures one or more AI providers here (public table), and every
guild uses them. Read on the request path via an in-process cache, not per-request DB reads.
"""

from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_AI_API_KEY


class AIConnectionColumns(SQLModel):
    """The columns of an AI connection, shared by the operator's table here
    and a guild's own (``GuildAIConnection``).

    Declared without ``sa_column`` so each table builds its own Column.
    """

    id: int | None = Field(default=None, primary_key=True)
    label: str = Field(sa_type=String(100), nullable=False)
    provider: str = Field(sa_type=String(50), nullable=False)
    base_url: str | None = Field(default=None, sa_type=String(1000), nullable=True)
    model: str | None = Field(default=None, sa_type=String(500), nullable=True)
    enabled: bool = Field(
        default=True, nullable=False, sa_column_kwargs={"server_default": "true"}
    )
    is_default: bool = Field(
        default=False, nullable=False, sa_column_kwargs={"server_default": "false"}
    )
    # How its last request went: the message code it failed with, and since
    # when, until a request succeeds. What its owner reads in settings.
    last_error: str | None = Field(default=None, sa_type=String(64), nullable=True)
    last_error_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
        nullable=False,
    )


class PlatformAIConnection(AIConnectionColumns, table=True):
    __tablename__ = "platform_ai_connections"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    api_key_encrypted: str | None = Field(
        default=None,
        sa_type=String(2000),
        nullable=True,
        sa_column_kwargs={"info": {FERNET_SALT: SALT_AI_API_KEY}},
    )
    # The communities it serves, and only them; empty, it serves every
    # community no other connection is given to.
    community_ids: list[int] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Integer), nullable=False, server_default="{}"),
    )
