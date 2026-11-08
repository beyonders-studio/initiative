"""The community's activity feed."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api import resource_access
from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.models.platform.user import User
from app.schemas.ai_generation import AIStreamEvent
from app.schemas.tenant.activity import (
    ActivityEntry,
    ActivityFeedPage,
    ActivityQuery,
    CatchUpRequest,
)
from app.services import ai_generation
from app.services.tenant import activity_feed

router = APIRouter()


@router.get("/", response_model=ActivityFeedPage)
async def read_activity(
    session: RLSSessionDep,
    guild_context: GuildContextDep,
    query: Annotated[ActivityQuery, Query()],
) -> ActivityFeedPage:
    """What people changed lately in what the reader can open, one entry per
    item, ordered for the reader."""
    entries, has_next = await activity_feed.feed(
        session,
        reader_id=guild_context.user_id,
        view=query.view,
        initiative_id=query.initiative_id,
        tool=query.tool,
        tool_id=query.tool_id,
        page=query.page,
        page_size=query.page_size,
    )
    return ActivityFeedPage(
        items=[ActivityEntry.model_validate(entry) for entry in entries],
        page=query.page,
        page_size=query.page_size,
        has_next=has_next,
    )


@router.post(
    "/catch-up",
    response_class=ai_generation.AIStreamResponse,
    responses={200: {"model": AIStreamEvent}},
)
async def catch_up(
    request: CatchUpRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ai_generation.AIStreamResponse:
    """What changed that the reader can see since they were last here, in the
    community or in one tool, streamed as it is written."""
    initiative_id = None
    if request.tool is not None and request.tool_id is not None:
        tool = await resource_access.load_authorized(
            session, request.tool, request.tool_id, current_user, guild_context
        )
        initiative_id = tool.initiative_id
    return ai_generation.AIStreamResponse(
        await ai_generation.catch_up(
            session,
            current_user,
            guild_context.guild_id,
            since=request.since,
            tool=request.tool,
            tool_id=request.tool_id,
            initiative_id=initiative_id,
        )
    )
