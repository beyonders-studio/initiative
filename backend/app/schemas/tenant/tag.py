from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from app.core.identity_boundary import GuildId
from app.core.tools import TAG_TARGETS
from app.schemas.base import SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.schemas.tenant.search import SearchHit


class TagBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#6366F1", pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Tag name cannot be empty")
        return v


class TagCreate(TagBase):
    name: TitleStr = Field(..., min_length=1, max_length=100)


class TagUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=100)
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Tag name cannot be empty")
        return v


class TagSummary(SanitizedBaseModel):
    """Lightweight tag representation for embedding in other schemas."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    color: str


def tag_summaries(tags) -> List[TagSummary]:
    """Serialize tag rows to ``TagSummary`` — the one serializer every taggable
    entity uses. The caller has already dropped anything trashed; this only
    shapes what is left."""
    return [TagSummary(id=tag.id, name=tag.name, color=tag.color) for tag in tags or []]


def annotated_tags(entity) -> List[TagSummary]:
    """The summaries ``tags_service.annotate_tags`` put on this entity.

    Read rather than recomputed: assignments live in one table now and are
    fetched for a whole page at once, so a serializer that went looking for
    them itself would be a query per card.
    """
    return list(getattr(entity, "tags", None) or [])


class TagRead(TagBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    community_id: GuildId = Field(
        validation_alias=AliasChoices("community_id", "guild_id")
    )
    created_at: datetime
    updated_at: datetime


def serialize_tag(tag, *, guild_id: int) -> TagRead:
    """The wire shape of one tag row.

    The row lives in its guild's schema and carries no guild column of its
    own, so the guild is handed in by whoever routed the session.
    """
    fields = {
        name: getattr(tag, name)
        for name in TagRead.model_fields
        if name != "community_id"
    }
    return TagRead(community_id=guild_id, **fields)


class TagSetRequest(SanitizedBaseModel):
    """Request body for setting tags on an entity."""

    tag_ids: List[int] = Field(default_factory=list, max_length=100)


# Derived, never re-declared: every Tool value plus the content-level extras
# (see TAG_TARGETS in app.core.tools). A new Tool lands here — and in the
# OpenAPI spec / generated frontend types — automatically.
TagTarget = Enum("TagTarget", {name: name for name in TAG_TARGETS}, type=str)
TagTarget.__doc__ = "Entity types a bulk tag edit can address."


class TagBulkEditRequest(SanitizedBaseModel):
    """Add and/or remove tags across many entities of one type, atomically."""

    target_type: TagTarget
    target_ids: List[int] = Field(min_length=1, max_length=500)
    add_tag_ids: List[int] = Field(default_factory=list, max_length=100)
    remove_tag_ids: List[int] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_an_operation(self) -> "TagBulkEditRequest":
        if not self.add_tag_ids and not self.remove_tag_ids:
            raise ValueError("add_tag_ids or remove_tag_ids must be non-empty")
        return self


class TagBulkEditResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    updated_count: int


class TaggedEntity(SearchHit):
    """One thing carrying a tag: a search hit's address, plus the name of the
    tool it lives in and when it last changed, which a table of them shows."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    tool_title: str = ""
    updated_at: Optional[datetime] = None


class TaggedEntitiesResponse(PageMeta):
    """Response for GET /tags/{id}/entities — one page of the things of one
    taggable kind carrying a tag."""

    items: List[TaggedEntity] = Field(default_factory=list)


class TagEntityCountsResponse(SanitizedBaseModel):
    """Response for GET /tags/{id}/counts — how many things of each taggable
    kind carry the tag, keyed by kind. A kind with none is absent."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    counts: Dict[str, int] = Field(default_factory=dict)
