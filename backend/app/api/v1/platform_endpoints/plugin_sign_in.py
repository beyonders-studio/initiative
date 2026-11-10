"""Sign in with Initiative's own page: what the SPA's authorize page asks.

``GET /plugin-platform/oauth/authorize/client`` checks the plug-in and its exact
return address, and names it; it takes no credential, because the page shows
who is asking before anybody signs in. A request that fails that check is
answered here, with a ``detail`` code the page shows, and is never sent back.

``GET /plugin-platform/oauth/authorize/places`` lists where the signed-in person
may open the plug-in, and ``POST /plugin-platform/oauth/authorize`` sends them
back with a code for the place they chose. See
:mod:`app.services.marketplace.plugin_sign_in`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import AgeViewerDep, CurrentUser, UserSessionDep
from app.core.messages import PluginSignInMessages
from app.schemas.platform.plugin_sign_in import (
    PluginSignInAuthorize,
    PluginSignInClientRead,
    PluginSignInPlaceRead,
    PluginSignInPlacesRead,
    PluginSignInRedirect,
    PluginSignInRequest,
)
from app.services.marketplace import plugin_sign_in

router = APIRouter()


async def _client(request: PluginSignInRequest) -> plugin_sign_in.SignInClient:
    try:
        return await plugin_sign_in.resolve_client(
            request.client_id, request.redirect_uri
        )
    except plugin_sign_in.SignInRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.code
        ) from exc


async def _checked(
    request: PluginSignInRequest,
) -> plugin_sign_in.AuthorizeRequest:
    """The request, or a 400 naming what is wrong with it. A request whose
    client checks out but is itself malformed was already sent back by the
    page, which read ``refusal_redirect``."""
    checked = plugin_sign_in.check_request(await _client(request), request.model_dump())
    if isinstance(checked, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=PluginSignInMessages.INVALID_REQUEST,
        )
    return checked


@router.get("/oauth/authorize/client", response_model=PluginSignInClientRead)
async def read_sign_in_client(
    request: Annotated[PluginSignInRequest, Depends()],
) -> PluginSignInClientRead:
    """The plug-in asking, if it may ask; see the module docstring."""
    client = await _client(request)
    checked = plugin_sign_in.check_request(client, request.model_dump())
    return PluginSignInClientRead(
        name=client.name,
        listing_public_id=client.listing_public_id,
        refusal_redirect=checked if isinstance(checked, str) else None,
        cancel_redirect=plugin_sign_in.denied(client, request.state),
    )


@router.get("/oauth/authorize/places", response_model=PluginSignInPlacesRead)
async def read_sign_in_places(
    request: Annotated[PluginSignInRequest, Depends()],
    session: UserSessionDep,
    current_user: CurrentUser,
    viewer: AgeViewerDep,
) -> PluginSignInPlacesRead:
    """Where the signed-in person may open the plug-in."""
    checked = await _checked(request)
    places, installed = await plugin_sign_in.places_for(
        session, current_user, checked.client, viewer
    )
    return PluginSignInPlacesRead(
        places=[
            PluginSignInPlaceRead(
                community_id=place.community_id,
                community_name=place.community_name,
                initiative_id=place.initiative_id,
                initiative_name=place.initiative_name,
            )
            for place in places
        ],
        installed_community_ids=installed,
    )


@router.post("/oauth/authorize", response_model=PluginSignInRedirect)
async def authorize_sign_in(
    payload: PluginSignInAuthorize,
    current_user: CurrentUser,
    viewer: AgeViewerDep,
) -> PluginSignInRedirect:
    """Send the person back to the plug-in with a code for the place they
    chose, when they may open it there."""
    checked = await _checked(payload)
    redirect = await plugin_sign_in.authorize(
        current_user,
        checked,
        community_id=payload.community_id,
        initiative_id=payload.initiative_id,
        viewer=viewer,
    )
    return PluginSignInRedirect(redirect_to=redirect)
