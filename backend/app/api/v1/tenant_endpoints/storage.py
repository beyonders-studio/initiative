"""Guild storage usage for the SPA's usage panel.

The seat's Usage tab shows storage used against the operator-set cap
(the community's ``max_storage_bytes`` rule). The number is the same
``SUM(uploads.size_bytes)`` that ``enforce_storage_quota`` enforces against,
summed over every upload the guild stores; it renders regardless of whether an
external billing URL is configured.

Read on the settings surface, by its admin rung — the same authority as the
caps it is shown against (``GET /communities/{id}``): an administrator, or a
settings grant at either rung, which is how support holding the seat sees the
tab. Not disclosed to regular members, like ``status``.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import AliasChoices, Field

from app.api.deps import SettingsAdminContextDep
from app.schemas.base import SanitizedBaseModel
from app.services.tenant.attachments import get_guild_storage_usage

router = APIRouter()


class CommunityStorageUsageRead(SanitizedBaseModel):
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    usage_bytes: int


@router.get("/usage", response_model=CommunityStorageUsageRead)
async def read_storage_usage(
    guild_context: SettingsAdminContextDep,
) -> CommunityStorageUsageRead:
    # Summed on the guild-wide session of its own; the settings rung is only
    # the question of who may read the total.
    usage_bytes = await get_guild_storage_usage(guild_context.guild_id)
    return CommunityStorageUsageRead(
        community_id=guild_context.guild_id, usage_bytes=usage_bytes
    )
