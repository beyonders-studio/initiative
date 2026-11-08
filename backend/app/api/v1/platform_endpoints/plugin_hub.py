"""An installed plug-in calling another plug-in through Initiative.

``POST /plugin-platform/plugins/{public_id}/endpoints/{endpoint_id}`` takes the
caller's installation token, or a member token to call on a member's behalf.
The install seam admits the token (``establish_install_access``); the rest of
the checks, and the call itself, are :mod:`app.services.marketplace.plugin_hub`'s.
The answer is the plug-in's own, passed back as it sent it.

Limited per calling install, and per calling install and plug-in called. Every
call the seam admits is written to the audit stream as ``plugin_hub.call``, with
how it ended and none of its parameters.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    CREDENTIAL_INSTALL,
    InstallAccessError,
    SessionDep,
    SystemSessionDep,
    VerifiedInstall,
    establish_install_access,
    oauth2_scheme,
)
from app.core import audit_context
from app.core.audit_events import AuditEventType
from app.core.identify import bearer_plugin_token
from app.core.messages import AuthMessages, PluginDataMessages
from app.core.plugin_access_token import InstallAccessToken
from app.core.rate_limit import (
    PLUGIN_HUB_CALLS_PER_INSTALL,
    PLUGIN_HUB_CALLS_PER_TARGET,
    take_allowance,
)
from app.db.session import clear_rls_context
from app.schemas.platform.plugin_hub import PluginHubCall
from app.services import audit as audit_service
from app.services.marketplace import plugin_hub as hub_service
from app.services.marketplace.plugin_data import PluginDataError

# Not part of the OpenAPI document: only plug-in services call it, never the SPA.
router = APIRouter(include_in_schema=False)


#: The counter namespace for this route's allowances.
_LIMIT_NAMESPACE = "plugin-hub"

#: How a call ended, in the audit line, when it was answered.
OUTCOME_OK = "ok"


def _refuse() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def hub_caller(
    request: Request,
    session: SessionDep,
    # Declares the scheme for the API description; read by ``bearer_plugin_token``.
    bearer: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> hub_service.HubCaller:
    """The plug-in the request's installation or member token names, or 401.

    The seam computes the install's standing: the community is in use, the
    install and its registration are live, and for a member token the member
    still belongs and still consents. The request's own session is left
    unrouted afterwards; the call runs on the system engine.
    """
    token = bearer_plugin_token(request)
    if not isinstance(token, InstallAccessToken):
        raise _refuse()
    try:
        context = await establish_install_access(
            session,
            VerifiedInstall(
                guild_id=token.guild_id,
                install_id=token.install_id,
                client_id=token.client_id,
                scopes=token.scopes,
                initiative_id=token.initiative_id,
                user_id=token.user_id,
                purpose=token.purpose,
            ),
        )
    except InstallAccessError as exc:
        raise _refuse() from exc
    clear_rls_context(session)
    await session.rollback()

    request.state.credential = CREDENTIAL_INSTALL
    audit_context.note_install(
        plugin=context.client_id,
        guild_id=context.guild_id,
        install_id=context.install_id,
    )
    # Whose request this is, for the rate limiter's key.
    request.state.plugin_install = (
        context.client_id,
        context.guild_id,
        context.install_id,
    )
    return hub_service.HubCaller(
        guild_id=context.guild_id,
        install_id=context.install_id,
        client_id=context.client_id,
        token_scopes=context.token_scopes,
        initiative_id=context.scope_initiative_id,
        member_user_id=context.member_user_id,
        purpose=context.purpose,
    )


HubCallerDep = Annotated[hub_service.HubCaller, Depends(hub_caller)]


def _audit(
    caller: hub_service.HubCaller,
    *,
    target: str,
    endpoint_id: str,
    outcome: str,
    direction: str | None = None,
) -> None:
    detail: dict[str, Any] = {
        "caller": caller.client_id,
        "target": target,
        "endpoint": endpoint_id,
        "actor": caller.actor,
        "outcome": outcome,
    }
    if direction is not None:
        detail["direction"] = direction
    if caller.initiative_id is not None:
        detail["initiative_id"] = caller.initiative_id
    audit_service.emit(
        event_type=AuditEventType.PLUGIN_HUB_CALL,
        actor_user_id=caller.member_user_id,
        guild_id=caller.guild_id,
        detail=detail,
    )


@router.post("/plugins/{public_id}/endpoints/{endpoint_id}")
async def call_plugin_endpoint(
    public_id: str,
    endpoint_id: str,
    payload: PluginHubCall,
    caller: HubCallerDep,
    session: SystemSessionDep,
) -> JSONResponse:
    """Call one of another plug-in's public endpoints, as the community or as the
    member the token acts for.

    Refusals answer with an OAuth-style ``detail``: ``insufficient_scope``,
    ``target_not_installed``, ``endpoint_not_public``,
    ``actor_not_supported`` or ``target_not_placed``, or the data proxy's code
    for a missing endpoint, bad parameters, a missing connection or a plug-in
    that did not answer. Past either allowance the answer is 429.
    """
    install_key = f"{caller.client_id}:{caller.guild_id}:{caller.install_id}"
    if not await take_allowance(
        PLUGIN_HUB_CALLS_PER_INSTALL, _LIMIT_NAMESPACE, f"install:{install_key}"
    ) or not await take_allowance(
        PLUGIN_HUB_CALLS_PER_TARGET,
        _LIMIT_NAMESPACE,
        f"target:{install_key}:{public_id}",
    ):
        _audit(
            caller,
            target=public_id,
            endpoint_id=endpoint_id,
            outcome=PluginDataMessages.RATE_LIMITED,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=PluginDataMessages.RATE_LIMITED,
        )

    try:
        answer = await hub_service.call_plugin(
            session,
            caller,
            target_public_id=public_id,
            endpoint_id=endpoint_id,
            params=payload.params,
        )
    except PluginDataError as exc:
        _audit(caller, target=public_id, endpoint_id=endpoint_id, outcome=exc.code)
        raise

    _audit(
        caller,
        target=public_id,
        endpoint_id=endpoint_id,
        outcome=OUTCOME_OK,
        direction=answer.direction,
    )
    return JSONResponse(content=answer.body)
