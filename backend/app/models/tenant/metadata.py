import builtins
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Enum as SQLEnum
from sqlmodel import Field, Relationship, SQLModel

from app.core.tools import INSTALL_METADATA_KIND, PROPERTY_TARGETS
from app.db.registry_checks import FROM_REGISTRY
from app.models.tenant._mixins import CreatedByMixin

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.tenant.file import File
    from app.models.tenant.initiative import Initiative


class MetadataType(str, Enum):
    """What a metadata definition's values are.

    The property types, which every owner may define, and beside them the
    kinds only a plug-in's definitions take: ``link`` and ``badge``, and
    ``json`` for a key its manifest declares no field for.
    """

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
    #: 0 to 100, which a layout shows as a number, stars or a bar.
    scale = "scale"
    #: A number people step up and down, by the step its definition's
    #: ``counter`` names and within its bounds, which a layout shows as a
    #: number, a bar or a clock.
    counter = "counter"
    #: One file of the item's initiative, by its id.
    file = "file"
    #: Who signed the item and when, and the name they typed. Written only by
    #: the signer, as themselves.
    signature = "signature"
    #: ``{url, text?}``.
    link = "link"
    #: ``{text, tone?}``.
    badge = "badge"
    #: Any JSON value: a plug-in's key that no field of its manifest declares.
    json = "json"


#: The types whose value names a person, by ``value_user_id``, which a filter
#: compares.
PERSON_TYPES: frozenset[MetadataType] = frozenset(
    {MetadataType.user_reference, MetadataType.signature}
)

#: The types only a plug-in's definitions take.
PLUGIN_ONLY_TYPES: frozenset[MetadataType] = frozenset(
    {MetadataType.link, MetadataType.badge, MetadataType.json}
)
_PLUGIN_ONLY = ", ".join(f"'{kind.value}'" for kind in sorted(PLUGIN_ONLY_TYPES))


class MetadataDefinition(CreatedByMixin, table=True):
    """A typed custom value's definition, and who owns it.

    A definition has at most one owner, which says who may define it, who
    writes its values, and what removes it:

    * none — the initiative's **property**: it applies to everything in the
      initiative, any tool or sub-tool there carrying a value for it;
    * ``project_id`` — that project's metadata, its values on the project's
      tasks; it goes with the project;
    * ``collection_id`` — that collection's metadata, its values on the
      collection's files; it goes with the collection;
    * ``install_id`` — an installed plug-in's metadata, declared by its
      manifest rather than typed in, one per ``key`` the install keeps. It
      belongs to no initiative, and goes when the plug-in is uninstalled.

    ``initiative_id`` is the initiative of every owner but a plug-in, and the
    project's or collection's key carries it.
    """

    __tablename__ = "metadata_definitions"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["collection_id", "initiative_id"],
            ["collections.id", "collections.initiative_id"],
            ondelete="CASCADE",
            name="fk_metadata_definitions_collection",
        ),
        ForeignKeyConstraint(
            ["project_id", "initiative_id"],
            ["projects.id", "projects.initiative_id"],
            ondelete="CASCADE",
            name="fk_metadata_definitions_project",
        ),
        CheckConstraint(
            "(type = 'currency') = (currency IS NOT NULL)",
            name="ck_metadata_definitions_currency",
        ),
        CheckConstraint(
            "(type = 'counter') = (counter IS NOT NULL)",
            name="ck_metadata_definitions_counter",
        ),
        CheckConstraint(
            "num_nonnulls(project_id, collection_id, install_id) <= 1",
            name="ck_metadata_definitions_one_owner",
        ),
        CheckConstraint(
            "(install_id IS NULL) = (initiative_id IS NOT NULL)"
            " AND (install_id IS NULL) = (key IS NULL)",
            name="ck_metadata_definitions_plugin",
        ),
        CheckConstraint(
            f"install_id IS NOT NULL OR type::text NOT IN ({_PLUGIN_ONLY})",
            name="ck_metadata_definitions_plugin_types",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    initiative_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    project_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    collection_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    install_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    #: A plug-in's metadata key, unique per install.
    key: str | None = Field(
        default=None, sa_column=Column(String(length=64), nullable=True)
    )
    #: A plug-in's list field: several values, each named by its ``ref``.
    list: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    #: The item kinds a plug-in's pinned manifest declares the key as a field
    #: on: whoever can read an item of one of them reads its value there.
    shown_on: builtins.list[str] = Field(
        default_factory=builtins.list,
        sa_column=Column(
            ARRAY(String(length=32)), nullable=False, server_default=text("'{}'")
        ),
    )
    name: str = Field(
        sa_column=Column(String(length=100), nullable=False),
    )
    type: MetadataType = Field(
        sa_column=Column(
            SQLEnum(
                MetadataType,
                name="metadata_type",
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
    color: str | None = Field(
        default=None,
        sa_column=Column(String(length=9), nullable=True),
    )
    options: builtins.list[dict] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )
    #: The ISO 4217 code a ``currency`` definition's amounts are in; None for
    #: every other type.
    currency: str | None = Field(
        default=None, sa_column=Column(String(length=3), nullable=True)
    )
    #: A ``counter`` definition's ``{step, min, max, initial}``
    #: (``CounterSettings``); None for every other type.
    counter: dict | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship()

    @classmethod
    def of_initiative(cls, initiative_id: int) -> Any:
        """The initiative's properties, which no project or collection owns."""
        return and_(
            cls.initiative_id == initiative_id,
            cls.__table__.c.project_id.is_(None),
            cls.__table__.c.collection_id.is_(None),
        )


_TARGET_VALUES = ", ".join(
    f"'{target}'" for target in (*PROPERTY_TARGETS, INSTALL_METADATA_KIND)
)

#: The longest ``ref`` a plug-in list's element is named by.
REF_LENGTH = 255

#: The typed columns a value is stored in, one per kind of value.
VALUE_COLUMNS: tuple[str, ...] = (
    "value_text",
    "value_number",
    "value_boolean",
    "value_date",
    "value_datetime",
    "value_user_id",
    "value_file_id",
    "value_json",
)

#: The columns a filter compares, each indexed by definition.
_FILTERED_COLUMNS: tuple[str, ...] = (
    "value_text",
    "value_number",
    "value_date",
    "value_datetime",
    "value_user_id",
)


class MetadataValue(SQLModel, table=True):
    """One definition's value on one thing.

    The thing is named by ``(entity_type, entity_id)``, where ``entity_type`` is
    one of ``PROPERTY_TARGETS`` (every tool and sub-tool), or ``plugin`` for an
    install's values on itself, named by its id. There is no foreign key to
    the thing: removing it removes its values explicitly (the purge, a move
    across initiatives) rather than by cascade. ``property_id`` names the
    definition, whoever owns it, and a value goes with it.

    The value is in the typed column its definition's type keeps it in. A
    file field's names its file by a foreign key, so purging the file empties
    the field. A signature's signer is in ``value_user_id``, when they signed
    in ``value_datetime`` and the name they typed in ``value_text``. A link or
    a badge is kept whole in ``value_json`` and its words, which a
    filter compares, in ``value_text``. A plug-in's list field holds a value
    per element, each named by its ``ref``; every other value's ``ref`` is
    ``''``. ``state`` is the facets a plug-in's value is in, by facet id.

    Who may read or write a value is what may be asked of the thing, through
    ``entity_access``, and then what its definition's owner adds: a
    collection's are read by whoever sees the collection and written by
    whoever may change it; a project's are on its tasks; a plug-in's are
    written by its install alone, and read by others only where its manifest
    shows them (``app.db.initiative_rls``).
    """

    __tablename__ = "metadata_values"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN ({_TARGET_VALUES})",
            name="ck_metadata_values_entity_type",
            info={FROM_REGISTRY: True},
        ),
        *(
            Index(
                f"ix_metadata_values_{column}",
                "property_id",
                column,
                postgresql_where=text(f"{column} IS NOT NULL"),
            )
            for column in _FILTERED_COLUMNS
        ),
        Index(
            "ix_metadata_values_value_json",
            "value_json",
            postgresql_using="gin",
            postgresql_ops={"value_json": "jsonb_path_ops"},
            postgresql_where=text("value_json IS NOT NULL"),
        ),
        Index(
            "ix_metadata_values_value_file_id",
            "value_file_id",
            postgresql_where=text("value_file_id IS NOT NULL"),
        ),
        Index(
            "ix_metadata_values_ref",
            "property_id",
            "ref",
            postgresql_where=text("ref <> ''"),
        ),
    )

    entity_type: str = Field(sa_column=Column(String(32), primary_key=True))
    entity_id: int = Field(sa_column=Column(Integer, primary_key=True))
    property_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("metadata_definitions.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        ),
    )
    #: Which element of a plug-in list's value the row holds; ``''`` for any
    #: other value.
    ref: str = Field(
        default="",
        sa_column=Column(
            String(REF_LENGTH), primary_key=True, server_default=text("''")
        ),
    )
    value_text: str | None = Field(default=None, sa_type=Text, nullable=True)
    value_number: Decimal | None = Field(default=None, sa_type=Numeric, nullable=True)
    value_boolean: bool | None = Field(default=None, sa_type=Boolean, nullable=True)
    value_date: date | None = Field(default=None, sa_type=Date, nullable=True)
    value_datetime: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
    value_user_id: int | None = Field(default=None, nullable=True)
    #: A file field's file. Purging the file empties it.
    value_file_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "files.id",
                ondelete="SET NULL",
                name="fk_metadata_values_value_file_id",
            ),
            nullable=True,
        ),
    )
    value_json: Any | None = Field(default=None, sa_type=JSONB, nullable=True)
    state: dict | None = Field(default=None, sa_type=JSONB, nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_type=DateTime(timezone=True),
        nullable=False,
    )

    definition: MetadataDefinition | None = Relationship()
    value_file: Optional["File"] = Relationship(
        sa_relationship_kwargs={"viewonly": True},
    )
    value_user: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(MetadataValue.value_user_id) == MemberProfile.id",
            "viewonly": True,
        },
    )
