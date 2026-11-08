from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, Text
from sqlmodel import Field, SQLModel


class CommunityTimer(SQLModel, table=True):
    """When a background sweep next has work in a community.

    A wake and nothing more: the community, the sweep's name and a time. What
    the work is, the sweep reads from the community's own schema when the
    timer comes due (``app.services.sweep_timers``). Armed by the triggers in
    each community's schema (``app.db.timers``) in the transaction that made
    the work, and by the worker after each visit. A community's sessions only
    ever add rows, for their own community; the worker on the system engine
    claims, runs and deletes them.
    """

    __tablename__ = "community_timers"
    __table_args__ = (
        # The worker's scan: what has come due.
        Index("ix_community_timers_due", "due_at"),
    )

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    community_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=True
        ),
    )
    kind: str = Field(sa_column=Column(Text, nullable=False))
    due_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
