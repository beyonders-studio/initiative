"""Guild-scoped AI config endpoints, mounted under ``/c/{community_id}/settings``.

Two surfaces:
- **The seat** — CRUD of ``guild_ai_connections`` (used when the global mode
  is ``community``). A connection's ``base_url`` is validated public-only, so a
  community can never persist a private/internal target.
- **Any member** — whether AI is available to them (``/ai/resolved``). Members
  configure nothing.

The global mode + operator connections (``platform`` mode) live in
``platform_endpoints/ai_settings.py``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import require_surface_open
from app.core.rules import SURFACE_AI_CONNECTIONS
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    SettingsRLSSessionDep,
    get_guild_membership,
    require_guild_roles,
    CurrentUser,
)
from app.models.platform.guild import CommunityRole
from app.schemas.ai_settings import (
    AIConnectionCreate,
    AIConnectionResponse,
    AIConnectionTestResponse,
    AIConnectionUpdate,
    AIModelsResponse,
    ResolvedAISettingsResponse,
)
from app.services import ai_settings as ai_settings_service

router = APIRouter()

#: Configuring this surface, which the deployment may close for one community.
_SURFACE_OPEN = Depends(require_surface_open(SURFACE_AI_CONNECTIONS))

# Connecting a community to an AI provider decides what leaves it, and for
# whom — the same kind of question as who may sign in, so it answers to the
# same seat rather than to running the community day to day. A settings grant
# at the superadmin rung stands in for the seat, as it does everywhere else.
GuildSeatContext = Annotated[
    GuildContext, Depends(require_guild_roles(CommunityRole.superadmin, settings=True))
]
# Changing a connection also asks a grantee for a read_write content grant
# beside the rung.
GuildSeatWriteContext = Annotated[
    GuildContext,
    Depends(require_guild_roles(CommunityRole.superadmin, settings=True, write=True)),
]
GuildMemberContext = Annotated[GuildContext, Depends(get_guild_membership)]


# --- Guild connections (guild admin — guild config mode) ---------------------
@router.get("/ai/connections", response_model=list[AIConnectionResponse])
async def list_community_connections(
    session: SettingsRLSSessionDep,
    _ctx: GuildSeatContext,
) -> list[AIConnectionResponse]:
    return await ai_settings_service.list_guild_connections(session)


@router.post(
    "/ai/connections", response_model=AIConnectionResponse, dependencies=[_SURFACE_OPEN]
)
async def create_community_connection(
    payload: AIConnectionCreate,
    session: SettingsRLSSessionDep,
    ctx: GuildSeatWriteContext,
    user: CurrentUser,
) -> AIConnectionResponse:
    return await ai_settings_service.create_guild_connection(
        session, ctx.guild_id, user.id, payload, actor_user_id=user.id
    )


@router.put(
    "/ai/connections/{connection_id}",
    response_model=AIConnectionResponse,
    dependencies=[_SURFACE_OPEN],
)
async def update_community_connection(
    connection_id: int,
    payload: AIConnectionUpdate,
    session: SettingsRLSSessionDep,
    _ctx: GuildSeatWriteContext,
    user: CurrentUser,
) -> AIConnectionResponse:
    return await ai_settings_service.update_guild_connection(
        session, connection_id, payload, actor_user_id=user.id
    )


@router.delete(
    "/ai/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_SURFACE_OPEN],
)
async def delete_community_connection(
    connection_id: int,
    session: SettingsRLSSessionDep,
    _ctx: GuildSeatWriteContext,
    user: CurrentUser,
) -> None:
    await ai_settings_service.delete_guild_connection(
        session, connection_id, actor_user_id=user.id
    )


@router.post(
    "/ai/connections/{connection_id}/test", response_model=AIConnectionTestResponse
)
async def test_community_connection(
    connection_id: int,
    session: SettingsRLSSessionDep,
    _ctx: GuildSeatContext,
) -> AIConnectionTestResponse:
    return await ai_settings_service.test_guild_connection(session, connection_id)


@router.post("/ai/connections/{connection_id}/models", response_model=AIModelsResponse)
async def fetch_community_connection_models(
    connection_id: int,
    session: SettingsRLSSessionDep,
    _ctx: GuildSeatContext,
) -> AIModelsResponse:
    return await ai_settings_service.fetch_guild_connection_models(
        session, connection_id
    )


# --- Resolved settings (any authenticated guild member) ----------------------
@router.get("/ai/resolved", response_model=ResolvedAISettingsResponse)
async def get_resolved_ai_settings(
    session: RLSSessionDep,
    ctx: GuildMemberContext,
) -> ResolvedAISettingsResponse:
    """Resolved (effective) AI settings for the member, without the API key."""
    return await ai_settings_service.get_resolved_ai_settings_response(
        session, ctx.guild_id
    )
