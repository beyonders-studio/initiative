from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Index, SmallInteger, Text
from sqlmodel import Field, SQLModel

from app.core.tools import CONTENT_KINDS
from app.db.registry_checks import FROM_REGISTRY

#: The highest level an item reaches, however many people engage with it.
LEVEL_MAX = 7

_ENTITY_TYPE_VALUES = ", ".join(f"'{kind}'" for kind in CONTENT_KINDS)


class EngagementLevel(SQLModel, table=True):
    """How many people engaged with one item lately, as a coarse level.

    Written by the hourly pass (``app.services.tenant.engagement_levels``) and
    by nothing else. It names no person and holds no count: an item has a row
    only once enough people engaged with it, and an item without one is at
    level 0. The row is read like the item it names.
    """

    __tablename__ = "engagement_levels"
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN ({_ENTITY_TYPE_VALUES})",
            name="ck_engagement_levels_entity_type",
            info={FROM_REGISTRY: True},
        ),
        CheckConstraint(
            f"level BETWEEN 1 AND {LEVEL_MAX}",
            name="ck_engagement_levels_level",
            info={FROM_REGISTRY: True},
        ),
        # Read highest first by a picker, which stops at its limit.
        Index("ix_engagement_levels_level", "level", "entity_type", "entity_id"),
    )

    entity_type: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    entity_id: int = Field(primary_key=True)
    level: int = Field(sa_column=Column(SmallInteger, nullable=False))
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
