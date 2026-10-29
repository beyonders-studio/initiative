"""Platform-level AI config endpoints.

App-wide AI config gated on ``config.manage`` (owner only), mounted top-level
under ``/settings`` — NOT guild-scoped. This owns the global **mode**
(``platform`` / ``guild`` / ``disabled``) and, in ``platform`` mode, the
operator's AI **connections** (the destination every guild uses). Guild-mode
connections and the member surface live in ``tenant_endpoints/ai_settings.py``.
"""

from fastapi import APIRouter, status

from app.api.deps import UserSessionDep
from app.api.v1.platform_endpoints.operator import ConfigManageDep
from app.schemas.ai_settings import (
    AIConnectionCreate,
    AIConnectionResponse,
    AIConnectionTestResponse,
    AIConnectionUpdate,
    AIModelsResponse,
    PlatformAIModeResponse,
    PlatformAIModeUpdate,
)
from app.services import ai_settings as ai_settings_service
from app.services.platform import auth_posture

platform_router = APIRouter()


# --- Global mode -------------------------------------------------------------
@platform_router.get("/ai/platform/mode", response_model=PlatformAIModeResponse)
async def get_platform_ai_mode(
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> PlatformAIModeResponse:
    """Get the global AI config mode (``config.manage`` — owner only)."""
    return await ai_settings_service.get_platform_ai_mode(session)


@platform_router.put("/ai/platform/mode", response_model=PlatformAIModeResponse)
async def update_platform_ai_mode(
    payload: PlatformAIModeUpdate,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> PlatformAIModeResponse:
    """Set the global AI config mode (``config.manage`` — owner only)."""
    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner),
        {"ai_config_mode": payload.mode},
    )
    return await ai_settings_service.get_platform_ai_mode(session)


# --- Operator connections (platform mode) ------------------------------------
@platform_router.get(
    "/ai/platform/connections", response_model=list[AIConnectionResponse]
)
async def list_platform_connections(
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> list[AIConnectionResponse]:
    return await ai_settings_service.list_platform_connections(session)


@platform_router.post("/ai/platform/connections", response_model=AIConnectionResponse)
async def create_platform_connection(
    payload: AIConnectionCreate,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> AIConnectionResponse:
    return await ai_settings_service.create_platform_connection(
        session, payload, actor_user_id=owner.id
    )


@platform_router.put(
    "/ai/platform/connections/{connection_id}", response_model=AIConnectionResponse
)
async def update_platform_connection(
    connection_id: int,
    payload: AIConnectionUpdate,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> AIConnectionResponse:
    return await ai_settings_service.update_platform_connection(
        session, connection_id, payload, actor_user_id=owner.id
    )


@platform_router.delete(
    "/ai/platform/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_platform_connection(
    connection_id: int,
    session: UserSessionDep,
    owner: ConfigManageDep,
) -> None:
    await ai_settings_service.delete_platform_connection(
        session, connection_id, actor_user_id=owner.id
    )


@platform_router.post(
    "/ai/platform/connections/{connection_id}/test",
    response_model=AIConnectionTestResponse,
)
async def test_platform_connection(
    connection_id: int,
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> AIConnectionTestResponse:
    """Test a stored operator connection (uses its stored key + destination —
    never a request body destination)."""
    return await ai_settings_service.test_platform_connection(session, connection_id)


@platform_router.post(
    "/ai/platform/connections/{connection_id}/models",
    response_model=AIModelsResponse,
)
async def fetch_platform_connection_models(
    connection_id: int,
    session: UserSessionDep,
    _owner: ConfigManageDep,
) -> AIModelsResponse:
    return await ai_settings_service.fetch_platform_connection_models(
        session, connection_id
    )
