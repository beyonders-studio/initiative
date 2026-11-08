from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, ClassVar, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlmodel import Enum as SQLEnum
from sqlmodel import Field, Relationship

from app.core.tools import Tool
from app.models.tenant._mixins import (
    ArchiveMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    HoldMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    attach_actions,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant


class CounterViewMode(str, Enum):
    number = "number"
    progress_bar = "progress_bar"
    segmented_clock = "segmented_clock"


class CounterGroup(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    """Initiative-scoped container for a set of related counters."""

    __tablename__ = "counter_groups"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__: ClassVar[dict[str, bool]] = {"implicit_returning": False}

    id: int | None = Field(default=None, primary_key=True)
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
    name: str = Field(nullable=False, max_length=255)
    description: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="counter_groups")
    counters: list["Counter"] = Relationship(
        back_populates="group",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "Counter.position",
        },
    )
    grants: list["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == CounterGroup.id, "
                "ResourceGrant.resource_type == 'counter_group')"
            ),
            "viewonly": True,
        }
    )


#: How a counter's numbers are stored: twenty digits, ten after the point. A
#: request is held to it, and a step is held within it.
COUNTER_DIGITS = 20
COUNTER_PLACES = 10
COUNTER_NUMBER = Numeric(COUNTER_DIGITS, COUNTER_PLACES)
#: The largest number that fits, either side of zero.
COUNTER_LIMIT = (
    Decimal(10) ** (COUNTER_DIGITS - COUNTER_PLACES) - Decimal(10) ** -COUNTER_PLACES
)


class Counter(HoldMixin, CreatedByMixin, SoftDeleteMixin, table=True):
    """A single named numeric counter inside a counter group."""

    __tablename__ = "counters"

    id: int | None = Field(default=None, primary_key=True)
    counter_group_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("counter_groups.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    color: str | None = Field(
        default=None,
        sa_column=Column(String(length=32), nullable=True),
    )
    count: Decimal = Field(
        default=Decimal(0),
        sa_column=Column(COUNTER_NUMBER, nullable=False, server_default="0"),
    )
    min: Decimal | None = Field(
        default=None,
        sa_column=Column(COUNTER_NUMBER, nullable=True),
    )
    max: Decimal | None = Field(
        default=None,
        sa_column=Column(COUNTER_NUMBER, nullable=True),
    )
    step: Decimal = Field(
        default=Decimal(1),
        sa_column=Column(COUNTER_NUMBER, nullable=False, server_default="1"),
    )
    initial_count: Decimal = Field(
        default=Decimal(0),
        sa_column=Column(COUNTER_NUMBER, nullable=False, server_default="0"),
    )
    view_mode: CounterViewMode = Field(
        default=CounterViewMode.number,
        sa_column=Column(
            SQLEnum(
                CounterViewMode,
                name="counter_view_mode",
                create_type=False,
            ),
            nullable=False,
            server_default="number",
        ),
    )
    position: Decimal = Field(
        default=Decimal(0),
        sa_column=Column(COUNTER_NUMBER, nullable=False, server_default="0"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    group: CounterGroup | None = Relationship(back_populates="counters")


attach_actions(CounterGroup, Tool.counter_group)
