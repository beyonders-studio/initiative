from datetime import date, datetime, timezone
from typing import ClassVar, List, Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
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


class Library(
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

    A library is a whole tool entity — its own sharing, its own comment thread,
    tags, the trash can, a URL — and its pictures are child rows the way a
    project's tasks are. That split is what the tool is for: a hundred canvases
    are one thing to share and one thing to open, and then browsed as many.

    ``name`` is the shared display column every tool spells the same;
    ``description`` is what a library is *of*, shown on its card and indexed
    for search.

    ``cover_item_id`` is the picture that stands for the library in a list.
    Nullable, because most libraries never choose one: a list falls back to the
    newest picture, which is what a library someone is still filling looks like
    from outside. The foreign key is declared ``use_alter`` because the two
    tables point at each other — a library names its cover, a picture names its
    library — and one of the constraints has to be added after both exist.
    ``SET NULL`` so removing the chosen picture leaves the library with no cover
    rather than no library.
    """

    __tablename__ = "libraries"
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
                "library_items.id",
                ondelete="SET NULL",
                use_alter=True,
                name="libraries_cover_item_id_fkey",
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
                "and_(foreign(ResourceGrant.resource_id) == Library.id, "
                "ResourceGrant.resource_type == 'library')"
            ),
            "viewonly": True,
        }
    )
    # The pictures. Ordered newest first here because that is the one order
    # every surface wants — a library is a record of what arrived, and the
    # latest arrival is what somebody opening it came to see.
    items: List["LibraryItem"] = Relationship(
        back_populates="library",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "desc(LibraryItem.created_at)",
            "foreign_keys": "LibraryItem.library_id",
        },
    )
    cover_item: Optional["LibraryItem"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "Library.cover_item_id == LibraryItem.id",
            "foreign_keys": "Library.cover_item_id",
            "viewonly": True,
        }
    )


class LibraryItem(HoldMixin, CreatedByMixin, SoftDeleteMixin, table=True):
    """One picture in a library.

    ``current_version_id`` names the version the picture shows — its file,
    thumbnail and size live on :class:`LibraryItemVersion` — the same
    arrangement an uploaded file keeps, and the rest of the versions are the
    history. The two tables point at each other, so the key is added once both
    exist (``use_alter``) and the pointer is written after the version row
    (``post_update``).

    ``title`` is optional — most pictures are named by what they show — and
    surfaces fall back to the original filename, which is at least what the
    person who uploaded it called it.

    ``occurred_on`` is the day the item is about — a visit, a photo, a bottle
    opened — and the day it was added until somebody says otherwise. Every
    list of a library is in that order.
    """

    __tablename__ = "library_items"
    __table_args__ = (
        Index(
            "ix_library_items_library_order",
            "library_id",
            "occurred_on",
            "created_at",
            "id",
        ),
    )
    # What labels a picture in a bare list of mixed things (the trash can).
    # Often empty, and the trash then shows the row with no name — which is
    # still the row, and still restorable.
    _display_field: ClassVar[str] = "title"

    id: Optional[int] = Field(default=None, primary_key=True)
    library_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("libraries.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    title: Optional[str] = Field(
        default=None, sa_column=Column(String(length=255), nullable=True)
    )
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    occurred_on: date = Field(
        default_factory=lambda: datetime.now(timezone.utc).date(),
        sa_column=Column(Date, nullable=False),
    )
    current_version_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "library_item_versions.id",
                use_alter=True,
                name="library_items_current_version_id_fkey",
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

    library: Optional[Library] = Relationship(
        back_populates="items",
        sa_relationship_kwargs={"foreign_keys": "LibraryItem.library_id"},
    )
    uploader: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(LibraryItem.created_by) == MemberProfile.id",
            "viewonly": True,
        }
    )
    versions: List["LibraryItemVersion"] = Relationship(
        back_populates="item",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "LibraryItemVersion.version_number",
            "foreign_keys": "LibraryItemVersion.library_item_id",
        },
    )
    #: Loaded with the row wherever a picture is, so a page of them reads its
    #: files in one more query.
    current_version: Optional["LibraryItemVersion"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "LibraryItem.current_version_id",
            "post_update": True,
            "lazy": "selectin",
        }
    )


class LibraryItemVersion(CreatedByMixin, table=True):
    """One uploaded rendition of a picture.

    Every picture has at least one row here, and the ``library_items`` row
    names the one it shows. The same shape an uploaded file's versions take,
    for the same reason: a design round replaces a canvas rather than adding
    one, and the earlier rounds are the story of how it got there.

    ``width`` and ``height`` are read from the file's header at upload, and
    they are what lets a masonry layout reserve the right space for a picture
    before its bytes arrive. ``thumbnail_url`` is a smaller rendition made at
    upload for the grid; ``NULL`` where none could be made, and the grid then
    shows the picture itself.
    """

    __tablename__ = "library_item_versions"
    __table_args__ = (
        UniqueConstraint(
            "library_item_id", "version_number", name="uq_liv_item_version"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    library_item_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("library_items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    version_number: int = Field(nullable=False)
    file_url: str = Field(sa_column=Column(String(length=512), nullable=False))
    thumbnail_url: Optional[str] = Field(
        default=None, sa_column=Column(String(length=512), nullable=True)
    )
    #: One of ``libraries.PICTURE_EXTENSIONS``: it decides how the picture is
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

    item: Optional[LibraryItem] = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={"foreign_keys": "LibraryItemVersion.library_item_id"},
    )


attach_actions(Library, Tool.library)
