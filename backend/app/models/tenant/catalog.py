from datetime import datetime, timezone
from typing import ClassVar, List, Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    from app.models.platform.user_profile_view import MemberProfile


class Catalog(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    """A collection of pictures in an initiative.

    A catalog is a whole tool entity — its own sharing, its own comment thread,
    tags, the trash can, a URL — and its pictures are child rows the way a
    project's tasks are. That split is what the tool is for: a hundred canvases
    are one thing to share and one thing to open, and then browsed as many.

    ``name`` is the shared display column every tool spells the same;
    ``description`` is what a catalog is *of*, shown on its card and indexed
    for search.

    ``cover_item_id`` is the picture that stands for the catalog in a list.
    Nullable, because most catalogs never choose one: a list falls back to the
    newest picture, which is what a catalog someone is still filling looks like
    from outside. The foreign key is declared ``use_alter`` because the two
    tables point at each other — a catalog names its cover, a picture names its
    catalog — and one of the constraints has to be added after both exist.
    ``SET NULL`` so removing the chosen picture leaves the catalog with no cover
    rather than no catalog.
    """

    __tablename__ = "catalogs"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__ = {"implicit_returning": False}

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    name: str = Field(nullable=False, max_length=255)
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    cover_item_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "catalog_items.id",
                ondelete="SET NULL",
                use_alter=True,
                name="catalogs_cover_item_id_fkey",
            ),
            nullable=True,
        ),
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
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Catalog.id, "
                "ResourceGrant.resource_type == 'catalog')"
            ),
            "viewonly": True,
        }
    )
    # The pictures. Ordered newest first here because that is the one order
    # every surface wants — a catalog is a record of what arrived, and the
    # latest arrival is what somebody opening it came to see.
    items: List["CatalogItem"] = Relationship(
        back_populates="catalog",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "desc(CatalogItem.created_at)",
            "foreign_keys": "CatalogItem.catalog_id",
        },
    )
    cover_item: Optional["CatalogItem"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "Catalog.cover_item_id == CatalogItem.id",
            "foreign_keys": "Catalog.cover_item_id",
            "viewonly": True,
        }
    )


class CatalogItem(HoldMixin, CreatedByMixin, SoftDeleteMixin, table=True):
    """One picture in a catalog.

    ``current_version_id`` names the version the picture shows — its file,
    thumbnail and size live on :class:`CatalogItemVersion` — the same
    arrangement an uploaded file keeps, and the rest of the versions are the
    history. The two tables point at each other, so the key is added once both
    exist (``use_alter``) and the pointer is written after the version row
    (``post_update``).

    ``title`` is optional — most pictures are named by what they show — and
    surfaces fall back to the original filename, which is at least what the
    person who uploaded it called it.
    """

    __tablename__ = "catalog_items"
    # What labels a picture in a bare list of mixed things (the trash can).
    # Often empty, and the trash then shows the row with no name — which is
    # still the row, and still restorable.
    _display_field: ClassVar[str] = "title"

    id: Optional[int] = Field(default=None, primary_key=True)
    catalog_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("catalogs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    title: Optional[str] = Field(
        default=None, sa_column=Column(String(length=255), nullable=True)
    )
    caption: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    current_version_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "catalog_item_versions.id",
                use_alter=True,
                name="catalog_items_current_version_id_fkey",
            ),
            nullable=True,
            index=True,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    catalog: Optional[Catalog] = Relationship(
        back_populates="items",
        sa_relationship_kwargs={"foreign_keys": "CatalogItem.catalog_id"},
    )
    uploader: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(CatalogItem.created_by) == MemberProfile.id",
            "viewonly": True,
        }
    )
    versions: List["CatalogItemVersion"] = Relationship(
        back_populates="item",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "CatalogItemVersion.version_number",
            "foreign_keys": "CatalogItemVersion.catalog_item_id",
        },
    )
    #: Loaded with the row wherever a picture is, so a page of them reads its
    #: files in one more query.
    current_version: Optional["CatalogItemVersion"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "CatalogItem.current_version_id",
            "post_update": True,
            "lazy": "selectin",
        }
    )


class CatalogItemVersion(CreatedByMixin, table=True):
    """One uploaded rendition of a picture.

    Every picture has at least one row here, and the ``catalog_items`` row
    names the one it shows. The same shape an uploaded file's versions take,
    for the same reason: a design round replaces a canvas rather than adding
    one, and the earlier rounds are the story of how it got there.

    ``width`` and ``height`` are read from the file's header at upload, and
    they are what lets a masonry layout reserve the right space for a picture
    before its bytes arrive. ``thumbnail_url`` is a smaller rendition made at
    upload for the grid; ``NULL`` where none could be made, and the grid then
    shows the picture itself.
    """

    __tablename__ = "catalog_item_versions"
    __table_args__ = (
        UniqueConstraint(
            "catalog_item_id", "version_number", name="uq_civ_item_version"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    catalog_item_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("catalog_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    version_number: int = Field(nullable=False)
    file_url: str = Field(sa_column=Column(String(length=512), nullable=False))
    thumbnail_url: Optional[str] = Field(
        default=None, sa_column=Column(String(length=512), nullable=True)
    )
    #: One of ``catalogs.PICTURE_EXTENSIONS``: it decides how the picture is
    #: shown.
    file_content_type: str = Field(sa_column=Column(String(length=128), nullable=False))
    file_size: Optional[int] = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )
    original_filename: Optional[str] = Field(
        default=None, sa_column=Column(String(length=255), nullable=True)
    )
    width: Optional[int] = Field(default=None, nullable=True)
    height: Optional[int] = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    item: Optional[CatalogItem] = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={"foreign_keys": "CatalogItemVersion.catalog_item_id"},
    )


attach_actions(Catalog, Tool.catalog)
