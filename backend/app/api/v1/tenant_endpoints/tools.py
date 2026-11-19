"""Generic per-tool endpoints — a tool's kind is the path parameter.

One route serves every tool in the community's tool set, built-in or a tool
plug-in's, so a new tool gets the surface with no per-tool endpoint: loading
+ authorization go through the unified resource-access loader, tag assignment
through the tag-link registry, and the comment switch through the column
every tool carries.
Only tasks keep hand-written tag routes — they are a tool's sub-resources,
not tools themselves.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
)
from app.core.tools import Tool
from app.db.tool_rows import table_of
from app.models.platform.user import User
from app.models.tenant.tag import Tag
from app.schemas.kinds import require_kind
from app.schemas.tenant.comment import ToolCommentSettings
from app.schemas.tenant.tag import TagSetRequest, TagSummary
from app.services.content_sockets import sockets
from app.services.tenant import required_fields
from app.services.tenant import tags as tags_service
from app.services.tenant.lifecycle_tree import set_columns

router = APIRouter()


@router.put("/{tool}/{tool_id}/tags", response_model=list[TagSummary])
async def set_tool_tags(
    tool: str,
    tool_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[TagSummary]:
    """Set tags on any tool entity. Replaces all existing tags with the
    provided list and returns the entity's new tags. Requires write access."""
    tools = guild_context.tools
    require_kind(tools, tool, Tool, items=False)
    row = await resource_access.load_kind(
        session, tool, tool_id, current_user, guild_context, access="write"
    )
    required = await required_fields.required_of(session, guild_context, row)
    tag_ids = await tags_service.set_entity_tags(
        session,
        tags_service.tag_links(tools)[tool],
        guild_id=guild_context.guild_id,
        entity_id=row.id,
        tag_ids=tags_in.tag_ids,
    )
    await set_columns(
        session, table_of(row), [row.id], {"updated_at": datetime.now(UTC)}
    )
    await required_fields.refuse_emptied(session, required)
    await session.commit()

    sockets.signal(guild_context.guild_id, tools.by_kind[tool], row.id, "updated")

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
    tool: str,
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
    require_kind(guild_context.tools, tool, Tool, items=False)
    row = await resource_access.load_kind(
        session, tool, tool_id, current_user, guild_context, access="write"
    )
    await set_columns(
        session,
        table_of(row),
        [row.id],
        {
            "comments_enabled": settings_in.comments_enabled,
            "updated_at": datetime.now(UTC),
        },
    )
    await session.commit()

    sockets.signal(
        guild_context.guild_id, guild_context.tools.by_kind[tool], row.id, "updated"
    )

    return ToolCommentSettings(comments_enabled=settings_in.comments_enabled)
