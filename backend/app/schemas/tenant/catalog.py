from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, List, Optional, Sequence, TYPE_CHECKING

from pydantic import AliasChoices, ConfigDict, Field

from app.core.identity_boundary import UPLOAD_PATH, GuildId, PersonId
from app.schemas.base import MentionStr, SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.schemas.tenant.comment import CommentAuthor
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertySummary,
    annotated_properties,
)
from app.schemas.tenant.plugin_data import PluginValueSummary
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import ToolSummaryBase

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.catalog import CatalogItem


class CatalogBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[MentionStr] = Field(default=None, max_length=2000)


class CatalogCreate(CatalogBase, PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    tag_ids: Optional[List[int]] = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # A catalog defaults to readable by the whole initiative: pictures are put
    # somewhere to be seen.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class CatalogUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[MentionStr] = Field(default=None, max_length=2000)
    #: The picture that stands for the catalog in a list. ``null`` clears the
    #: choice and the list falls back to the newest picture; a set value has
    #: to be one of this catalog's own.
    cover_item_id: Optional[int] = None


class CatalogCover(SanitizedBaseModel):
    """What a list draws for a catalog: one picture, at whichever size it has."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    item_id: int
    file_url: Annotated[str, UPLOAD_PATH]
    thumbnail_url: Annotated[Optional[str], UPLOAD_PATH] = None
    width: Optional[int] = None
    height: Optional[int] = None


class CatalogSummary(CatalogBase, ToolSummaryBase):
    #: The chosen cover, or ``null`` where none was chosen. ``cover`` is that
    #: picture; ``preview`` is the newest few, which is what a list draws —
    #: as a small grid — for a catalog nobody chose a cover for. Only a list
    #: asked for ``include_preview`` carries it.
    cover_item_id: Optional[int] = None
    cover: Optional[CatalogCover] = None
    preview: List[CatalogCover] = Field(default_factory=list)
    comment_count: int = 0

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        return {"cover": catalog_cover(row.cover_item)}


class CatalogRead(CatalogSummary):
    """A catalog on its own page. The same shape as its summary: the pictures
    are paged separately, because a catalog is browsed rather than read."""


class CatalogListResponse(PageMeta):
    items: List[CatalogSummary]


class CatalogItemUpdate(PropertiesOnUpdate):
    title: Optional[TitleStr] = Field(default=None, max_length=255)
    caption: Optional[MentionStr] = Field(default=None, max_length=2000)
    tag_ids: Optional[List[int]] = None
    #: The caption this was written over, as its writer saw it. Given, a
    #: write over a caption that has since changed is refused.
    caption_base: Optional[MentionStr] = None


class CatalogItemBulkDelete(SanitizedBaseModel):
    """The pictures to send to the trash together — a selection on the wall."""

    item_ids: List[int] = Field(min_length=1, max_length=500)


class CatalogItemBulkDeleteResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    deleted_count: int


class CatalogItemRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    catalog_id: int
    community_id: GuildId = Field(
        validation_alias=AliasChoices("community_id", "guild_id")
    )
    #: What somebody called it, if they did. Surfaces fall back to
    #: ``original_filename``, which is at least what the uploader called it.
    title: Optional[str] = None
    caption: Optional[MentionStr] = None
    #: The current version's file, served at ``/uploads/{guild}/{name}``.
    file_url: Annotated[str, UPLOAD_PATH]
    #: A smaller rendition for grids, or ``null`` where none was made — the
    #: grid then shows the picture itself.
    thumbnail_url: Annotated[Optional[str], UPLOAD_PATH] = None
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    #: Pixel size, read from the file's header at upload. What lets a layout
    #: reserve the right space for a picture before its bytes arrive.
    width: Optional[int] = None
    height: Optional[int] = None
    created_by: PersonId | None = None
    uploader: Optional[CommentAuthor] = None
    created_at: datetime
    updated_at: datetime
    #: How many renditions have been uploaded. One for most pictures; more
    #: than one is what says "this went through rounds".
    version_count: int = 1
    tags: List[TagSummary] = Field(default_factory=list)
    properties: List[PropertySummary] = Field(default_factory=list)
    #: The values installed plug-ins show on the picture, from the installs on
    #: and placed in its catalog's initiative. Its own read carries them; a
    #: wall of pictures does not.
    plugin_values: List[PluginValueSummary] = Field(default_factory=list)


class CatalogItemListResponse(PageMeta):
    items: List[CatalogItemRead]


class CatalogItemVersionRead(SanitizedBaseModel):
    """One stored rendition of a picture."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    version_number: int
    file_url: Annotated[str, UPLOAD_PATH]
    thumbnail_url: Annotated[Optional[str], UPLOAD_PATH] = None
    file_content_type: Optional[str] = None
    file_size: Optional[int] = None
    original_filename: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    created_by: PersonId | None = None
    created_at: datetime
    is_current: bool = False


#: What a picture reports of its current version.
_FILE_FIELDS = (
    "file_url",
    "thumbnail_url",
    "file_content_type",
    "file_size",
    "original_filename",
    "width",
    "height",
)


def catalog_cover(item: "CatalogItem | None") -> CatalogCover | None:
    version = item.current_version if item is not None else None
    if item is None or item.id is None or version is None:
        return None
    return CatalogCover(
        item_id=item.id,
        file_url=version.file_url,
        thumbnail_url=version.thumbnail_url,
        width=version.width,
        height=version.height,
    )


def serialize_catalog_item(
    item: "CatalogItem",
    *,
    context: ActorContext,
    plugin_values: Sequence[PluginValueSummary] = (),
) -> CatalogItemRead:
    return CatalogItemRead(
        id=item.id,
        catalog_id=item.catalog_id,
        community_id=context.guild_id,
        title=item.title,
        caption=item.caption,
        **{name: getattr(item.current_version, name, None) for name in _FILE_FIELDS},
        created_by=item.created_by,
        uploader=(
            CommentAuthor.model_validate(item.uploader)
            if item.uploader is not None
            else None
        ),
        created_at=item.created_at,
        updated_at=item.updated_at,
        version_count=int(getattr(item, "version_count", 1)),
        tags=annotated_tags(item),
        properties=annotated_properties(item),
        plugin_values=list(plugin_values),
    )
