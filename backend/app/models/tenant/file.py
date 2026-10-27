from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    case,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import column_property, deferred
from sqlmodel import Field, Relationship

from app.core.file_types import FileType
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


#: The body, in its two views. Both are deferred so a list or an access check
#: loads the row without them; a loader that reads the body asks for it with
#: ``undefer``, and a read through one that did not raises instead of loading.
_CONTENT = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
_YJS_STATE = Column(LargeBinary, nullable=True)


class File(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    __tablename__ = "files"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__ = (
        # What a collection's entries name a file by, with its initiative.
        UniqueConstraint("id", "initiative_id", name="uq_files_id_initiative"),
        {"implicit_returning": False},
    )
    __mapper_args__ = {
        "properties": {
            "content": deferred(_CONTENT, raiseload=True),
            "yjs_state": deferred(_YJS_STATE, raiseload=True),
        }
    }

    id: Optional[int] = Field(default=None, primary_key=True)
    initiative_id: int = Field(
        foreign_key="initiatives.id", ondelete="CASCADE", nullable=False
    )
    name: str = Field(nullable=False, index=True, max_length=255)
    content: dict = Field(default_factory=dict, sa_column=_CONTENT)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    featured_image_url: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=512), nullable=True),
    )
    is_template: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    yjs_state: Optional[bytes] = Field(default=None, sa_column=_YJS_STATE)
    yjs_updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    #: The file's format (:mod:`app.core.file_types`); an uploaded file's is
    #: its current version's.
    file_type: FileType = Field(
        default=FileType.lexical,
        sa_column=Column(Text, nullable=False, server_default=text("'lexical'")),
    )
    #: An uploaded file's current version; ``NULL`` for every other type. The
    #: two tables point at each other, so the key is added once both exist
    #: (``use_alter``) and the pointer is written after the version row
    #: (``post_update``). A version a file points at cannot be deleted
    #: until it points elsewhere; deleting the file takes its versions.
    current_version_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey(
                "file_versions.id",
                use_alter=True,
                name="files_current_version_id_fkey",
            ),
            nullable=True,
            index=True,
        ),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="files")
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == File.id, "
                "ResourceGrant.resource_type == 'file')"
            ),
            "viewonly": True,
        }
    )
    versions: List["FileVersion"] = Relationship(
        back_populates="file",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "FileVersion.version_number",
            "foreign_keys": "FileVersion.file_id",
        },
    )
    #: Loaded with the row wherever a file is, so a list reads its file
    #: in one more query for the whole page.
    current_version: Optional["FileVersion"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "File.current_version_id",
            "post_update": True,
            "lazy": "selectin",
        }
    )


class FileVersion(CreatedByMixin, table=True):
    """A single uploaded version of an uploaded file.

    Every uploaded file has at least one row here, and the ``files`` row
    names the current one (``current_version_id``). ``created_by`` is null
    for a version a plug-in acting as its community uploaded.
    """

    __tablename__ = "file_versions"
    __table_args__ = (
        UniqueConstraint("file_id", "version_number", name="uq_fv_file_version"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    file_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    version_number: int = Field(nullable=False)
    file_url: str = Field(sa_column=Column(String(length=512), nullable=False))
    #: What its bytes were read as (``attachments.validate_file``): it
    #: decides the file's type.
    file_content_type: str = Field(
        sa_column=Column(String(length=128), nullable=False),
    )
    file_size: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, nullable=True),
    )
    original_filename: Optional[str] = Field(
        default=None,
        sa_column=Column(String(length=255), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    file: Optional["File"] = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={"foreign_keys": "FileVersion.file_id"},
    )


attach_actions(File, Tool.file)

# The address a link file points at, read out of its body in the row's own
# SELECT so a card can draw the provider's mark without loading the body.
# Deferred like ``actions``; the list loader asks for it.
File.__mapper__.add_property(  # type: ignore[attr-defined]
    "smart_link_url",
    column_property(
        case(
            (
                File.__table__.c.file_type == FileType.url.value,
                _CONTENT["url"].astext,
            )
        ),
        deferred=True,
        raiseload=True,
    ),
)
