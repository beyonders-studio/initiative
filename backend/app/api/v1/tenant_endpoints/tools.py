"""Generic per-tool endpoints — the ``Tool`` enum is the path parameter.

One route serves every tool, so a new ``Tool`` member gets the surface with no
per-tool endpoint: loading + authorization go through the unified
resource-access registry, tag assignment through the tag-link registry, and the
comment switch through the column every tool carries.
Only the content-level extras (tasks, queue items) keep hand-written tag
routes — they are sub-resources of a tool, not tools themselves.
"""

from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    RLSSessionDep,
    get_current_active_user,
    GuildContextDep,
)
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.tag import Tag
from app.schemas.tenant.comment import ToolCommentSettings
from app.schemas.tenant.tag import TagSetRequest, TagSummary
from app.services.content_sockets import sockets
from app.services.tenant import required_fields
from app.services.tenant import tags as tags_service

router = APIRouter()


@router.put("/{tool}/{tool_id}/tags", response_model=List[TagSummary])
async def set_tool_tags(
    tool: Tool,
    tool_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[TagSummary]:
    """Set tags on any tool entity. Replaces all existing tags with the
    provided list and returns the entity's new tags. Requires write access."""
    row = await resource_access.load_authorized(
        session,
        tool,
        tool_id,
        current_user,
        guild_context,
        access="write",
    )
    required = await required_fields.required_of(session, guild_context, row)
    tag_ids = await tags_service.set_entity_tags(
        session,
        tags_service.TOOL_TAG_LINKS[tool],
        guild_id=guild_context.guild_id,
        entity_id=row.id,
        tag_ids=tags_in.tag_ids,
    )
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await required_fields.refuse_emptied(session, required)
    await session.commit()

    sockets.signal(guild_context.guild_id, tool, row.id, "updated")

    if not tag_ids:
        return []
    # Re-read under the session-wide soft-delete filter. A tag trashed by a
    # concurrent request between the write above and this read is filtered out
    # here — skip it rather than KeyError (the tag service drops an assignment
    # whose tag is gone the same way), so the race returns a clean list, never
    # a 500.
    tags_by_id = {
        tag.id: tag
        for tag in (await session.exec(select(Tag).where(Tag.id.in_(tag_ids)))).all()
    }
    return [
        TagSummary(id=tag.id, name=tag.name, color=tag.color)
        for tag_id in tag_ids
        if (tag := tags_by_id.get(tag_id)) is not None
    ]


@router.put("/{tool}/{tool_id}/comments", response_model=ToolCommentSettings)
async def set_tool_comment_settings(
    tool: Tool,
    tool_id: int,
    settings_in: ToolCommentSettings,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ToolCommentSettings:
    """Turn the comment thread on any tool entity on or off. Requires write
    access, the same level that posting to the thread takes.

    Turning it off keeps the comments that are already there — nothing is
    deleted; the thread stops being readable or writable until it is turned
    back on. A task's thread is its own and is never affected by its project's
    switch.
    """
    row = await resource_access.load_authorized(
        session,
        tool,
        tool_id,
        current_user,
        guild_context,
        access="write",
    )
    row.comments_enabled = settings_in.comments_enabled
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()

    sockets.signal(guild_context.guild_id, tool, row.id, "updated")

    return ToolCommentSettings(comments_enabled=row.comments_enabled)
