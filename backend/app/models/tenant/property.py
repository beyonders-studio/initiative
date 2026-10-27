from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional, TYPE_CHECKING

from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    and_,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum, Field, Relationship, SQLModel

from app.db.registry_checks import FROM_REGISTRY
from app.models.tenant._mixins import CreatedByMixin

from app.core.tools import PROPERTY_TARGETS

if TYPE_CHECKING:  # pragma: no cover
    from app.models.tenant.initiative import Initiative
    from app.models.platform.user_profile_view import MemberProfile


class PropertyType(str, Enum):
    """Supported value types for a property definition."""

    text = "text"
    number = "number"
    checkbox = "checkbox"
    date = "date"
    datetime = "datetime"
    url = "url"
    select = "select"
    multi_select = "multi_select"
    user_reference = "user_reference"
    #: An amount of money in the currency its definition names.
    currency = "currency"
    #: 1 to 100, which a layout shows as a number, stars or a bar. Only a
    #: collection's own fields are ratings.
    rating = "rating"


class PropertyDefinition(CreatedByMixin, table=True):
    """Initiative-scoped custom property definition.

    A definition belongs to one initiative and applies to everything in it:
    any tool or sub-tool there may carry a value for it (``PropertyValue``).

    One with a ``collection_id`` is that collection's own field instead: its
    values sit on the collection's files, it is never one of the initiative's
    properties, and it goes with the collection. ``initiative_id`` is the
    collection's, which the key holds.
    """

    __tablename__ = "property_definitions"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "initiative_id"],
            ["collections.id", "collections.initiative_id"],
            ondelete="CASCADE",
            name="fk_property_definitions_collection",
        ),
        CheckConstraint(
            "type <> 'rating' OR collection_id IS NOT NULL",
            name="ck_property_definitions_rating_in_collection",
        ),
        CheckConstraint(
            "(type = 'currency') = (currency IS NOT NULL)",
            name="ck_property_definitions_currency",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    collection_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    name: str = Field(
        sa_column=Column(String(length=100), nullable=False),
    )
    type: PropertyType = Field(
        sa_column=Column(
            SQLEnum(
                PropertyType,
                name="property_type",
                create_type=False,
                values_callable=lambda e: [item.value for item in e],
            ),
            nullable=False,
        ),
    )
    # NUMERIC(20, 10) on the DB side; ``asdecimal=False`` keeps the Python
    # value a plain ``float`` so downstream serializers (Pydantic/Orval) don't
    # have to juggle Decimal. Exact representation in Postgres avoids float
    # precision rounding when drag-reorder sets midpoint positions.
    position: float = Field(
        default=0.0,
        sa_column=Column(
            Numeric(20, 10, asdecimal=False), nullable=False, server_default="0"
        ),
    )
    color: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=9), nullable=True),
    )
    options: Optional[List[dict]] = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    #: The ISO 4217 code a ``currency`` definition's amounts are in; None for
    #: every other type.
    currency: Optional[str] = Field(
        default=None, sa_column=Column(String(length=3), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship()

    @classmethod
    def of_initiative(cls, initiative_id: int) -> Any:
        """The initiative's properties, which are no collection's fields."""
        return and_(
            cls.initiative_id == initiative_id,
            cls.__table__.c.collection_id.is_(None),
        )


_TARGET_VALUES = ", ".join(f"'{target}'" for target in PROPERTY_TARGETS)

#: The typed columns a value is stored in, one per kind of value.
VALUE_COLUMNS: tuple[str, ...] = (
    "value_text",
    "value_number",
    "value_boolean",
    "value_date",
    "value_datetime",
    "value_user_id",
    "value_json",
)

#: The columns a property filter compares, each indexed by definition.
_FILTERED_COLUMNS: tuple[str, ...] = (
    "value_text",
    "value_number",
    "value_date",
    "value_datetime",
    "value_user_id",
)


class PropertyValue(SQLModel, table=True):
    """One property's value on one thing in an initiative.

    The thing is named by ``(entity_type, entity_id)``, where ``entity_type`` is
    one of ``PROPERTY_TARGETS``: every tool and sub-tool. There is no foreign key
    to it — the value belongs to the initiative, so removing the thing removes
    its values explicitly (the purge, a move across initiatives) rather than by
    cascade. Who may read or write a value is what may be asked of the thing,
    through ``entity_access``.

    A value of a collection's field is on a file in that collection: read by
    whoever sees the collection and can open the file, and written by whoever
    may change the collection.
    """

    __tablename__ = "property_values"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN ({_TARGET_VALUES})",
            name="ck_property_values_entity_type",
            info={FROM_REGISTRY: True},
        ),
        *(
            Index(
                f"ix_property_values_{column}",
                "property_id",
                column,
                postgresql_where=text(f"{column} IS NOT NULL"),
            )
            for column in _FILTERED_COLUMNS
        ),
        Index(
            "ix_property_values_value_json",
            "value_json",
            postgresql_using="gin",
            postgresql_ops={"value_json": "jsonb_path_ops"},
            postgresql_where=text("value_json IS NOT NULL"),
        ),
    )

    entity_type: str = Field(sa_column=Column(String(32), primary_key=True))
    entity_id: int = Field(sa_column=Column(Integer, primary_key=True))
    property_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("property_definitions.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
    )
    value_text: Optional[str] = Field(default=None, sa_type=Text, nullable=True)
    value_number: Optional[Decimal] = Field(
        default=None, sa_type=Numeric, nullable=True
    )
    value_boolean: Optional[bool] = Field(default=None, sa_type=Boolean, nullable=True)
    value_date: Optional[date] = Field(default=None, sa_type=Date, nullable=True)
    value_datetime: Optional[datetime] = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
    value_user_id: Optional[int] = Field(default=None, nullable=True)
    value_json: Optional[Any] = Field(default=None, sa_type=JSONB, nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=DateTime(timezone=True),
        nullable=False,
    )

    property_definition: Optional[PropertyDefinition] = Relationship()
    value_user: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(PropertyValue.value_user_id) == MemberProfile.id",
            "viewonly": True,
        },
    )
