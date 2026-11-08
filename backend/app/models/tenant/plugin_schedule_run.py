"""When each of an install's schedules last ran, and when it runs next.

A plug-in's manifest may declare ``schedules``: intervals at which Initiative
calls its ``schedule`` hook, once for each community that installed it. A row
here is one install's schedule, kept in step with the install's pinned
definition (:func:`app.services.tenant.plugin_schedules.reconcile`) and run when
its timer comes due (:func:`app.services.tenant.plugin_schedules.run_due`).

Written and read by the system engine alone.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlmodel import Field, SQLModel


class PluginScheduleRun(SQLModel, table=True):
    __tablename__ = "plugin_schedule_runs"

    #: The install. Its rows go with it.
    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    #: The schedule's id in the pinned definition, a manifest identifier.
    schedule_id: str = Field(sa_column=Column(String(length=64), primary_key=True))
    #: When the last call that succeeded started: the hook's ``since``.
    last_success_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    next_due_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    #: Calls that have failed since the last success.
    failures: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, default=0)
    )
    #: Set while a worker is calling the plug-in, so no other claims the row.
    claimed_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
