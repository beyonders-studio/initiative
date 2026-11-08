from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, Integer
from sqlmodel import Field

from app.models.tenant._mixins import CreatedByMixin


class GuildSetting(CreatedByMixin, table=True):
    __tablename__ = "guild_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    # Trash retention. NULL means "never auto-purge". Default 90 days.
    retention_days: int | None = Field(
        default=90,
        sa_column=Column(Integer, nullable=True, server_default="90"),
    )
