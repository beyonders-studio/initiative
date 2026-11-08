"""AI work on text a member sends, mounted under ``/c/{community_id}/ai``.

Work on something in the community — a task, a file, a page — is a route of
that thing. These take only the text in the request, and read nothing else.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.models.platform.user import User
from app.schemas.ai_generation import AIStreamEvent, AIWriteRequest
from app.services import ai_generation

router = APIRouter()


@router.post(
    "/write",
    response_class=ai_generation.AIStreamResponse,
    responses={200: {"model": AIStreamEvent}},
)
async def write_with_ai(
    request: AIWriteRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ai_generation.AIStreamResponse:
    """Writing help for a selection in a document, streamed as it is
    written: rewritten, shortened, corrected, translated, or written on from."""
    return ai_generation.AIStreamResponse(
        await ai_generation.write(
            session, current_user, guild_context.guild_id, request
        )
    )
