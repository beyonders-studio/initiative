"""Where an installed plug-in appears, and who may open it there.

One row per (install, initiative): the plug-in's initiative-scoped surfaces appear
in that initiative, and the initiative roles in ``role_ids`` may open them. An
initiative with no row is one the plug-in is not placed in. The guild-wide surfaces
are not placed; they belong to the community as a whole.

``role_ids`` is an array rather than a join table. A deleted role's id is never
reused, so a stale id matches nothing, and the array keeps one table's catalog
entries out of every guild schema.

Rows are written by the community's seat, or by the system engine, which
places a mandatory install in every initiative there is when it installs it.
The row names no person: a placement is a fact about the install.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field, SQLModel


class PluginPlacement(SQLModel, table=True):
    __tablename__ = "plugin_placements"

    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        )
    )
    #: The initiative roles allowed to open the plug-in's surfaces here.
    role_ids: list[int] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Integer), nullable=False, server_default=text("'{}'")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
