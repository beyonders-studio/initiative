"""Guild storage usage for the SPA's usage panel.

The seat's Usage tab shows storage used against the operator-set cap
(the community's ``max_storage_bytes`` rule). The number is the same
``SUM(uploads.size_bytes)`` that ``enforce_storage_quota`` enforces against,
summed over every upload the guild stores; it renders regardless of whether an
external billing URL is configured.

Read on the settings surface by whoever holds the community's usage page, or
a settings grant at either rung, which is how support holding the seat sees
the tab. Not disclosed to regular members, like ``status``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import AliasChoices, Field

from app.api.deps import GuildContext, require_surface
from app.models.platform.guild import AdminSurface
from app.schemas.base import SanitizedBaseModel
from app.services.tenant.attachments import get_guild_storage_usage

router = APIRouter()


class CommunityStorageUsageRead(SanitizedBaseModel):
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    usage_bytes: int


@router.get("/usage", response_model=CommunityStorageUsageRead)
async def read_storage_usage(
    guild_context: Annotated[
        GuildContext, Depends(require_surface(AdminSurface.usage, settings=True))
    ],
) -> CommunityStorageUsageRead:
    # Summed on the guild-wide session of its own; the guard is only the
    # question of who may read the total.
    usage_bytes = await get_guild_storage_usage(guild_context.guild_id)
    return CommunityStorageUsageRead(
        community_id=guild_context.guild_id, usage_bytes=usage_bytes
    )
