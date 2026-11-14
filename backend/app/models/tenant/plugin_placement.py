"""Where an installed plug-in appears.

One row per (install, initiative): the plug-in's initiative-scoped surfaces appear
in that initiative. An initiative with no row is one the plug-in is not placed in.
The guild-wide surfaces are not placed; they belong to the community as a whole.
Who reaches them where they appear is the initiative's roles' answer, held as
they hold a tool's permissions (``initiative_rules`` rows naming the install).

Rows are written by the community's seat, or by the system engine, which
places a mandatory install in every initiative there is when it installs it.
The row names no person: a placement is a fact about the install.
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer
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
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
