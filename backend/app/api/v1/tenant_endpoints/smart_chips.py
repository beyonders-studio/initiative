"""`/api/v1/c/{community_id}/smart-chips` — what a file's chips say now.

Guild-scoped like any other content read: the guild comes from the path and
``RLSSessionDep`` routes into its schema, so a chip answers under the same
gates as the thing it is about.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import GuildContextDep, RLSSessionDep, get_current_active_user
from app.models.platform.user import User
from app.schemas.tenant.smart_chip import (
    EmbedRead,
    ReferenceEmbedList,
    ReferenceRead,
    SmartChipStateList,
)
from app.services.tenant import smart_chips as smart_chips_service

router = APIRouter()


@router.post("/", response_model=SmartChipStateList)
async def read_smart_chips(
    body: ReferenceRead,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildContextDep,
) -> SmartChipStateList:
    """Read every chip on one page in one request.

    A reference that names something gone, or something this caller may not
    see, is absent from the answer — the two are the same reply, and the chip
    falls back to the words the file stored beside it.
    """
    return SmartChipStateList(
        items=await smart_chips_service.read_smart_chips(
            session,
            user_id=current_user.id,
            refs=body.refs,
        )
    )


@router.post("/embeds", response_model=ReferenceEmbedList)
async def read_reference_embeds(
    body: EmbedRead,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _guild_context: GuildContextDep,
) -> ReferenceEmbedList:
    """What an embedded reference shows: the thing's name, and its description
    or, for prose, its body.

    Absent for anything gone or out of this caller's reach, as a chip is.
    """
    return ReferenceEmbedList(
        items=await smart_chips_service.read_embeds(
            session, user_id=current_user.id, refs=body.refs
        )
    )
