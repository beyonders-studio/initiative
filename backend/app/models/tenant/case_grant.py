"""Which access grant serves which operations case.

A grant is a row in ``public.access_grants``, read before any routing; the
case it serves is a task in the operations community
(``app_settings.operations_guild_id``). The link between them is kept here,
under the task, so deleting the task takes its links with it. ``grant_id``
names the grant with no key, as a row in a community's schema names a shared
row.

In every community's schema, like every community table; only the operations
community's holds rows. Read and written by the system engine alone
(``app.db.tenancy.LEDGER_TABLES``), through ``services.platform.grant_cases``.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class CaseGrant(SQLModel, table=True):
    """One grant, and the case it serves."""

    __tablename__ = "case_grants"

    #: The grant, in ``public.access_grants``. A grant serves one case at most.
    grant_id: int = Field(
        sa_column=Column(Integer, primary_key=True, autoincrement=False)
    )
    task_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
