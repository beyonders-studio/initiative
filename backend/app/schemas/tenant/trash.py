from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import AliasChoices, ConfigDict, Field

from app.core.tools import TRASH_TARGETS
from app.schemas.base import SanitizedBaseModel
from app.schemas.query import PageMeta

# Derived from the Tool enum plus the non-tool trashable extras, exactly the way
# TagTarget derives from TAG_TARGETS — a new tool reaches the trash can without
# this being edited.
EntityType = Enum("EntityType", {name: name for name in TRASH_TARGETS}, type=str)
EntityType.__doc__ = "Entity types the trash can holds."


class TrashItem(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    entity_type: EntityType
    entity_id: int
    # The guild the entity lives in. Within a single guild's trash this is
    # constant, but the cross-guild ``/me/trash`` view merges several guilds,
    # so the client needs it to address restore/purge (which are guild-scoped).
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    name: str
    deleted_at: datetime
    deleted_by_id: int | None = None
    deleted_by_display: str
    purge_at: datetime | None = None


class TrashListResponse(PageMeta):
    items: list[TrashItem]
    retention_days: int | None = None


class RestoreResponse(SanitizedBaseModel):
    """200 payload for a successful restore. The needs-reassignment case is a
    409 with :class:`RestoreNeedsReassignmentResponse` instead."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    restored: bool
