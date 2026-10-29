"""The rules the deployment and each community store. See ``app.core.rules``."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    UniqueConstraint,
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
    """One of a community's rules that says something other than its default,
    for the whole community or for one member of it.

    Goes with its community, and a member's with their membership.
    """

    __tablename__ = "community_rules"
    __table_args__ = (
        CheckConstraint(_ONE_SLOT, name="ck_community_rules_one_slot"),
        ForeignKeyConstraint(
            ["guild_id", "user_id"],
            ["guild_memberships.guild_id", "guild_memberships.user_id"],
            ondelete="CASCADE",
            name="fk_community_rules_member",
        ),
        UniqueConstraint(
            "guild_id",
            "key",
            "user_id",
            name="uq_community_rules_subject",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, Identity(), primary_key=True)
    )
    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
        )
    )
    key: str = Field(sa_column=Column(String(64), nullable=False))
    #: The member the row is about, or ``None`` for the whole community.
    user_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    enabled: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    amount: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), sa_column=_updated_at()
    )
