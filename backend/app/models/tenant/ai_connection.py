"""Guild-owned AI connections (guild config mode).

Used when ``ai_config_mode == "community"``: a guild admin configures the
guild's AI providers here (guild schema). Guild-level table (guild-wide
config, schema-boundary protected). ``base_url`` is validated public-only —
a guild admin can never persist a private/internal target.

A connection's shared key is in ``guild_ai_connection_keys``, which the seat
and the system engine read. A trigger keeps ``has_api_key`` in step with it,
so what a member reads is whether the connection has a key.
"""

from pydantic import ConfigDict
from sqlalchemy import Column, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_AI_API_KEY
from app.models.platform.ai_connection import AIConnectionColumns
from app.models.tenant._mixins import CreatedByMixin


class GuildAIConnection(AIConnectionColumns, CreatedByMixin, table=True):
    __tablename__ = "guild_ai_connections"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    has_api_key: bool = Field(
        default=False, nullable=False, sa_column_kwargs={"server_default": "false"}
    )


class GuildAIConnectionKey(SQLModel, table=True):
    """The shared key of one guild AI connection. No row means no key."""

    __tablename__ = "guild_ai_connection_keys"

    connection_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_ai_connections.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        )
    )
    api_key_encrypted: str = Field(
        sa_column=Column(
            String(2000), nullable=False, info={FERNET_SALT: SALT_AI_API_KEY}
        )
    )
