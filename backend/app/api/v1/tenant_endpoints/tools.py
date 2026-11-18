"""Generic per-tool endpoints — the ``Tool`` enum is the path parameter.

One route serves every tool, so a new ``Tool`` member gets the surface with no
per-tool endpoint: loading + authorization go through the unified
resource-access registry, and the comment switch through the column every tool
carries.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api import resource_access
from app.api.deps import (
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
)
from app.core.tools import Tool
from app.models.platform.user import User
from app.schemas.tenant.comment import ToolCommentSettings
from app.services.content_sockets import sockets

router = APIRouter()


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
    row.updated_at = datetime.now(UTC)
    session.add(row)
    await session.commit()

    sockets.signal(guild_context.guild_id, tool, row.id, "updated")

    return ToolCommentSettings(comments_enabled=row.comments_enabled)
