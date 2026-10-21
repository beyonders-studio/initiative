"""Guild-scoped AI config endpoints, mounted under ``/c/{community_id}/settings``.

Two surfaces:
- **Guild admin** — CRUD of ``guild_ai_connections`` (used when the global mode
  is ``guild``). A connection's ``base_url`` is validated public-only, so a
  guild admin can never persist a private/internal target.
- **Member** (any authenticated guild member) — attach an own key + pick a
  connection (``/ai/me``). Members never set a destination.

The global mode + operator connections (``platform`` mode) live in
``platform_endpoints/ai_settings.py``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    NotDemoSample,
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
    CommunityMemberAIKey,
    ConnectionScope,
    MemberAIKeyUpdate,
    MemberAIPrefUpdate,
    MemberAIView,
    ResolvedAISettingsResponse,
)
from app.services import ai_settings as ai_settings_service

router = APIRouter()

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


@router.post("/ai/connections", response_model=AIConnectionResponse)
async def create_community_connection(
    payload: AIConnectionCreate,
    session: SettingsRLSSessionDep,
    ctx: GuildSeatWriteContext,
    user: CurrentUser,
) -> AIConnectionResponse:
    return await ai_settings_service.create_guild_connection(
        session, ctx.guild_id, user.id, payload, actor_user_id=user.id
    )


@router.put("/ai/connections/{connection_id}", response_model=AIConnectionResponse)
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
    "/ai/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT
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


@router.get("/ai/members/keys", response_model=list[CommunityMemberAIKey])
async def list_community_member_keys(
    session: SettingsRLSSessionDep,
    _ctx: GuildSeatContext,
) -> list[CommunityMemberAIKey]:
    """Who gave which of the community's AI connections a key. Never a key."""
    return await ai_settings_service.list_community_member_keys(session)


@router.delete(
    "/ai/members/{user_id}/keys/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_community_member_key(
    user_id: int,
    connection_id: int,
    session: SettingsRLSSessionDep,
    _ctx: GuildSeatWriteContext,
    user: CurrentUser,
) -> None:
    """Take back the key a member gave one of the community's AI connections."""
    await ai_settings_service.revoke_community_member_key(
        session, user_id, connection_id, actor_user_id=user.id
    )


# --- Member surface (any authenticated guild member) -------------------------
@router.get("/ai/me", response_model=MemberAIView)
async def get_member_ai(
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> MemberAIView:
    """List the connections available to the member (no keys), whether they've
    attached their own key to each, and which one is selected."""
    return await ai_settings_service.get_member_ai_view(session, user, ctx.guild_id)


@router.put("/ai/me/key", response_model=MemberAIView, dependencies=[NotDemoSample])
async def set_member_key(
    payload: MemberAIKeyUpdate,
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> MemberAIView:
    """Attach/replace the member's own key for a connection."""
    return await ai_settings_service.set_member_key(
        session, user, ctx.guild_id, payload
    )


@router.delete("/ai/me/key/{scope}/{connection_id}", response_model=MemberAIView)
async def delete_member_key(
    scope: ConnectionScope,
    connection_id: int,
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> MemberAIView:
    return await ai_settings_service.delete_member_key(
        session, user, ctx.guild_id, scope, connection_id
    )


@router.put("/ai/me/pref", response_model=MemberAIView)
async def set_member_pref(
    payload: MemberAIPrefUpdate,
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> MemberAIView:
    """Pick the connection the member uses and whether AI is on for them."""
    return await ai_settings_service.set_member_pref(
        session, user, ctx.guild_id, payload
    )


@router.post("/ai/me/test", response_model=AIConnectionTestResponse)
async def test_member_ai(
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> AIConnectionTestResponse:
    """Test the member's currently-selected connection with their effective key."""
    return await ai_settings_service.test_member_connection(session, user, ctx.guild_id)


# --- Resolved settings (any authenticated guild member) ----------------------
@router.get("/ai/resolved", response_model=ResolvedAISettingsResponse)
async def get_resolved_ai_settings(
    session: RLSSessionDep,
    ctx: GuildMemberContext,
    user: CurrentUser,
) -> ResolvedAISettingsResponse:
    """Resolved (effective) AI settings for the member, without the API key."""
    return await ai_settings_service.get_resolved_ai_settings_response(
        session, user, ctx.guild_id
    )
