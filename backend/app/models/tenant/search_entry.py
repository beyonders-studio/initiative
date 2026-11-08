"""The guild-wide search index — one row per searchable chunk of content.

Derived data: every row is written by ``public.refresh_search_entry()`` from the
table it describes, never by application code. See ``app/db/search_index.py``
for the registry that renders those triggers.

The row carries two independent identities. ``(entity_type, entity_id)`` names
what was found, so a hit resolves to a detail route. ``(dac_tool, dac_id)`` names
the resource whose sharing governs it, which is often a *parent* — a task is
governed by its project, a calendar event by its calendar — so the query filters
on the sharing decision without re-walking those joins.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlmodel import Field, SQLModel

from app.core.search import SearchEntityType
from app.db.registry_checks import FROM_REGISTRY

_ENTITY_TYPE_VALUES = ", ".join(f"'{kind.value}'" for kind in SearchEntityType)


class SearchEntry(SQLModel, table=True):
    """One indexed chunk of one entity.

    Composite primary key is ``(entity_type, entity_id, chunk_ix)``. Long text is
    split into several chunks; everything else is a single ``chunk_ix = 0`` row,
    by the same code path.
    """

    __tablename__ = "search_entries"
    __table_args__ = (
        CheckConstraint(
            f"entity_type IN ({_ENTITY_TYPE_VALUES})",
            name="ck_search_entries_entity_type",
            info={FROM_REGISTRY: True},
        ),
    )

    entity_type: str = Field(sa_column=Column(Text, primary_key=True, nullable=False))
    entity_id: int = Field(primary_key=True)
    chunk_ix: int = Field(
        sa_column=Column(
            SmallInteger, primary_key=True, nullable=False, server_default=text("0")
        )
    )
    #: The initiative gating this row, or NULL for guild-level content (tags, a
    #: guild calendar) where the initiative gate has nothing to decide.
    initiative_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    #: The ``Tool`` whose sharing governs this row, and the resource id to test
    #: against ``resource_grants``. NULL for rows carrying no sharing gate.
    dac_tool: str | None = Field(sa_column=Column(Text, nullable=True))
    dac_id: int | None = Field(sa_column=Column(Integer, nullable=True))
    #: Whether the source row is archived. Archived work stays indexed so it
    #: can still be found on purpose, and is left out of the answers nobody
    #: asked it for — pickers, and a search that did not opt in.
    archived: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    #: Whether the source row is a template rather than an instance of one.
    template: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    title: str = Field(sa_column=Column(Text, nullable=False))
    body: str | None = Field(sa_column=Column(Text, nullable=True))
    #: When this row's *searchable text* last changed — not the source row's
    #: ``updated_at``, which moves on writes the index deliberately ignores.
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    tsv: str | None = Field(default=None, sa_column=Column(TSVECTOR, nullable=False))
