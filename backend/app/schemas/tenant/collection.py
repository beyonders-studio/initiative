from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Annotated

from pydantic import AliasChoices, ConfigDict, Field, model_validator

from app.core.collection_shapes import SHAPES, FieldDisplay
from app.core.file_types import FileType
from app.core.identity_boundary import UPLOAD_PATH, GuildId, PersonId
from app.models.tenant.metadata import MetadataType
from app.schemas.base import MentionStr, SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.schemas.tenant.archive import ContentCan
from app.schemas.tenant.file import FileSummary
from app.schemas.tenant.property import (
    CurrencyCode,
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertyDefinitionRead,
    PropertySummary,
    PropertyValueInput,
    annotated_properties,
)
from app.schemas.tenant.share_request import HiddenFiles
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import from_row
from app.schemas.tenant.tool_layout import ListLayoutKind

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.collection import Collection
    from app.models.tenant.file import File

#: The most files one request adds to or takes out of a collection.
MAX_FILES_PER_CHANGE = 500


class CollectionFiles(SanitizedBaseModel):
    """Files to put in a collection or take out of it."""

    file_ids: list[int] = Field(min_length=1, max_length=MAX_FILES_PER_CHANGE)


class CollectionFilesAdd(CollectionFiles):
    """Files to put in a collection, and the values of the collection's
    metadata each one it takes starts with: what its file page requires."""

    metadata: list[PropertyValueInput] = Field(default_factory=list)


#: A ready-made shape, by its key (``app.core.collection_shapes``).
CollectionShapeKey = Enum(
    "CollectionShapeKey", {shape.key: shape.key for shape in SHAPES}, type=str
)
CollectionShapeKey.__doc__ = "A ready-made shape a collection can start as."


class CollectionCreate(CollectionFiles, PropertiesOnCreate):
    """A new collection, made with the files it starts with: a collection is
    never empty. It starts blank (its grid and table, and no metadata of its
    own), as a ready-made ``shape``, or with the metadata and lists of another
    collection in the initiative (``shape_from``), none of its values."""

    initiative_id: int
    name: TitleStr = Field(..., min_length=1, max_length=255)
    description: MentionStr | None = Field(default=None, max_length=2000)
    tag_ids: list[int] | None = None
    shape: CollectionShapeKey | None = None
    #: The collection whose shape this one starts with.
    shape_from: int | None = None

    @model_validator(mode="after")
    def _one_shape(self) -> CollectionCreate:
        if self.shape is not None and self.shape_from is not None:
            raise ValueError("a collection starts as a shape or as another's")
        return self


class CollectionUpdate(PropertiesOnUpdate):
    name: TitleStr | None = Field(default=None, min_length=1, max_length=255)
    description: MentionStr | None = Field(default=None, max_length=2000)
    #: The file that stands for it on a card, one of its own. ``null`` clears
    #: the choice, and a card shows the file added most recently.
    cover_file_id: int | None = None
    tag_ids: list[int] | None = None
    comments_enabled: bool | None = None


class CollectionCover(SanitizedBaseModel):
    """The file a card shows for a collection."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    file_id: int
    name: str
    file_type: FileType
    #: The current version's file, for an uploaded file, and what a file's
    #: card reads of it: its thumbnail and its size (``FileSummary``'s).
    file_url: Annotated[str | None, UPLOAD_PATH] = None
    file_content_type: str | None = None
    thumbnail_url: Annotated[str | None, UPLOAD_PATH] = None
    width: int | None = None
    height: int | None = None


def collection_cover(file: File | None) -> CollectionCover | None:
    if file is None or file.id is None:
        return None
    version = file.current_version
    return CollectionCover(
        file_id=file.id,
        name=file.name,
        file_type=file.file_type,
        **{
            name: getattr(version, name, None)
            for name in (
                "file_url",
                "file_content_type",
                "thumbnail_url",
                "width",
                "height",
            )
        },
    )


class CollectionFileSummary(FileSummary):
    """A file as its collection lists it: with when it was added there, and
    its values of the collection's metadata."""

    added_at: datetime
    metadata: list[PropertySummary] = Field(default_factory=list)


class CollectionFileListResponse(PageMeta):
    items: list[CollectionFileSummary]


class CollectionCan(ContentCan):
    """What the caller may do to a collection
    (``resource_access.may_change``)."""

    #: Take it back out of the archive. False for a collection archived along
    #: with its initiative, which comes back with the initiative.
    unarchive: bool = False


class CollectionRead(SanitizedBaseModel):
    """A collection as its reader sees it: only the files they can open are
    counted, and the cover is one of those."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    initiative_id: int
    community_id: GuildId = Field(
        validation_alias=AliasChoices("community_id", "guild_id")
    )
    name: str
    description: MentionStr | None = None
    cover_file_id: int | None = None
    cover: CollectionCover | None = None
    file_count: int = 0
    #: Its files the reader knows are there and can't open, which they may
    #: ask for.
    hidden_files: HiddenFiles = Field(default_factory=HiddenFiles)
    created_by: PersonId | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    comments_enabled: bool = True
    comments_locked_at: datetime | None = None
    comment_count: int = 0
    tags: list[TagSummary] = Field(default_factory=list)
    properties: list[PropertySummary] = Field(default_factory=list)
    #: Its metadata, in order, whose values its files carry here.
    metadata: list[PropertyDefinitionRead] = Field(default_factory=list)
    #: Whether the reader may rename it, change what is in it, or trash it.
    can: CollectionCan = Field(default_factory=CollectionCan)


class CollectionShapeMetadata(SanitizedBaseModel):
    """Metadata a ready-made shape brings, in the reader's language."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    type: MetadataType
    #: For a scale, how the shape's lists show it.
    display: FieldDisplay | None = None
    #: For money, the currency it starts in.
    currency: CurrencyCode | None = None


class CollectionShapeEntry(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    key: CollectionShapeKey
    name: str
    hint: str
    #: The lists it shows, in order; it opens on the first.
    lists: list[ListLayoutKind]
    metadata: list[CollectionShapeMetadata]


class CollectionShapeGroup(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    key: str
    name: str
    entries: list[CollectionShapeEntry]


class CollectionListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[CollectionRead]


def serialize_collection(
    row: Collection,
    *,
    context: ActorContext,
    file_count: int,
    hidden_files: HiddenFiles,
    cover: File | None,
    can: CollectionCan,
) -> CollectionRead:
    return from_row(
        CollectionRead,
        row,
        guild_id=context.guild_id,
        cover=collection_cover(cover),
        file_count=file_count,
        hidden_files=hidden_files,
        tags=annotated_tags(row),
        properties=annotated_properties(row),
        can=can,
    )
