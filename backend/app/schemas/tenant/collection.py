from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Optional, TYPE_CHECKING

from pydantic import AliasChoices, ConfigDict, Field

from app.core.file_types import FileType
from app.core.identity_boundary import UPLOAD_PATH, GuildId, PersonId
from app.schemas.base import MentionStr, SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.schemas.tenant.archive import ContentCan
from app.schemas.tenant.file import FileSummary
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertySummary,
    annotated_properties,
)
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import from_row

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.collection import Collection
    from app.models.tenant.file import File

#: The most files one request adds to or takes out of a collection.
MAX_FILES_PER_CHANGE = 500


class CollectionFiles(SanitizedBaseModel):
    """Files to put in a collection or take out of it."""

    file_ids: List[int] = Field(min_length=1, max_length=MAX_FILES_PER_CHANGE)


class CollectionCreate(CollectionFiles, PropertiesOnCreate):
    """A new collection, made with the files it starts with: a collection is
    never empty."""

    initiative_id: int
    name: TitleStr = Field(..., min_length=1, max_length=255)
    description: Optional[MentionStr] = Field(default=None, max_length=2000)
    tag_ids: Optional[List[int]] = None


class CollectionUpdate(PropertiesOnUpdate):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[MentionStr] = Field(default=None, max_length=2000)
    #: The file that stands for it on a card, one of its own. ``null`` clears
    #: the choice, and a card shows the file added most recently.
    cover_file_id: Optional[int] = None
    tag_ids: Optional[List[int]] = None
    comments_enabled: Optional[bool] = None


class CollectionCover(SanitizedBaseModel):
    """The file a card shows for a collection."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    file_id: int
    name: str
    file_type: FileType
    #: The current version's file, for an uploaded file, and what a file's
    #: card reads of it: its thumbnail and its size (``FileSummary``'s).
    file_url: Annotated[Optional[str], UPLOAD_PATH] = None
    file_content_type: Optional[str] = None
    thumbnail_url: Annotated[Optional[str], UPLOAD_PATH] = None
    width: Optional[int] = None
    height: Optional[int] = None


def collection_cover(file: Optional["File"]) -> Optional[CollectionCover]:
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
    """A file as its collection lists it: with when it was added there."""

    added_at: datetime


class CollectionFileListResponse(PageMeta):
    items: List[CollectionFileSummary]


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
    description: Optional[MentionStr] = None
    cover_file_id: Optional[int] = None
    cover: Optional[CollectionCover] = None
    file_count: int = 0
    created_by: PersonId | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: Optional[datetime] = None
    comments_enabled: bool = True
    comments_locked_at: Optional[datetime] = None
    comment_count: int = 0
    tags: List[TagSummary] = Field(default_factory=list)
    properties: List[PropertySummary] = Field(default_factory=list)
    #: Whether the reader may rename it, change what is in it, or trash it.
    can: ContentCan = Field(default_factory=ContentCan)


class CollectionListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[CollectionRead]


def serialize_collection(
    row: "Collection",
    *,
    context: "ActorContext",
    file_count: int,
    cover: Optional["File"],
    can_edit: bool,
) -> CollectionRead:
    return from_row(
        CollectionRead,
        row,
        guild_id=context.guild_id,
        cover=collection_cover(cover),
        file_count=file_count,
        tags=annotated_tags(row),
        properties=annotated_properties(row),
        can=ContentCan(edit=can_edit),
    )
