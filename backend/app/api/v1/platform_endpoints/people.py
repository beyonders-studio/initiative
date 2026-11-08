"""People — the personal, cross-guild directory of who the reader could message.

Everything here is served on ``UserSessionDep``: the guild rosters through the
per-guild routing loop every other ``/me`` aggregate uses. No system engine on
any path.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import UserSessionDep, get_current_active_user
from app.models.platform.user import User
from app.schemas.platform.people import PeopleSectionsResponse
from app.services.platform import people as people_service

me_router = APIRouter()


SearchQuery = Annotated[
    str | None,
    Query(
        max_length=128,
        description=(
            "Narrows every section. Matches the handle, plus the real name in "
            "a guild that shows names; type a whole handle (`foobar#1234`) to "
            "pin one person."
        ),
    ),
]


@me_router.get("/people", response_model=PeopleSectionsResponse)
async def list_people_sections(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    search: SearchQuery = None,
    guild_ids: Annotated[list[int] | None, Query(alias="community_ids")] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=people_service.DEFAULT_PAGE_SIZE, ge=1, le=100),
) -> PeopleSectionsResponse:
    """Every guild the caller is in, each with a page of its members.

    Sections come back in the caller's own rail order
    (``GuildMembership.position``), and each is paged **within** the guild —
    the response is grouped, so a flat offset across a merged list would not
    mean anything. Pass one ``guild_ids`` value to page a single section.

    A guild reachable only through a live PAM or break-glass grant has no
    section here: like every other ``/me`` aggregate, this walks real
    memberships.
    """
    guilds = await people_service.ordered_member_guilds(
        session, user_id=current_user.id
    )
    if guild_ids:
        wanted = set(guild_ids)
        guilds = [row for row in guilds if row[0] in wanted]

    sections = await people_service.guild_sections(
        session,
        user_id=current_user.id,
        guilds=guilds,
        search=search,
        page=page,
        page_size=page_size,
    )
    if search and search.strip():
        sections = [section for section in sections if section.items]
    return PeopleSectionsResponse(sections=sections, page=page, page_size=page_size)
