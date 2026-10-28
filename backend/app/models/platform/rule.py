"""The rules the deployment and each community store. See ``app.core.rules``."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlmodel import Field, SQLModel

#: A row holds its value in exactly one slot; ``app.core.rules`` says which.
_ONE_SLOT = "num_nonnulls(enabled, amount) = 1"


def _updated_at() -> Column:
    return Column(
        DateTime(timezone=True),
        nullable=False,
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PlatformRule(SQLModel, table=True):
    """One of the deployment's rules that says something other than its
    default."""

    __tablename__ = "platform_rules"
    __table_args__ = (CheckConstraint(_ONE_SLOT, name="ck_platform_rules_one_slot"),)

    key: str = Field(sa_column=Column(String(64), primary_key=True))
    enabled: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    amount: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), sa_column=_updated_at()
    )


class CommunityRule(SQLModel, table=True):
    """One of a community's rules that says something other than its default.

    Goes with its community.
    """

    __tablename__ = "community_rules"
    __table_args__ = (CheckConstraint(_ONE_SLOT, name="ck_community_rules_one_slot"),)

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    key: str = Field(sa_column=Column(String(64), primary_key=True))
    enabled: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    amount: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), sa_column=_updated_at()
    )
