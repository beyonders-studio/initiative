"""Where a plug-in service asks for an access token, and learns its installs.

``POST /plugin-platform/oauth/token`` is an OAuth 2.0 token endpoint (RFC 6749):
form-encoded in, JSON out, and its errors are the protocol's own
``{"error", "error_description"}`` bodies rather than this API's ``detail``
codes, because the reader is an OAuth client. The plug-in authenticates with a JWT
it signs (RFC 7523 §2.2), or, for a member token, presents one as the grant
itself (RFC 7523 §2.1); see :mod:`app.services.marketplace.plugin_oauth`.

``GET /plugin-platform/installations`` takes a **plug-in token** and lists the plug-in's
installs, a page at a time, each named by the reference the plug-in asks for an
installation token with.

Both run on the system engine: the caller is a plug-in rather than a person, and
what they read is registrations, spent assertions and, for the listing, the
install index (``plugin_installs``).
"""

from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import SystemSessionDep
from app.core.identify import bearer_plugin_token
from app.core.messages import AuthMessages
from app.core.plugin_access_token import PluginAccessToken
from app.core.plugin_scopes import InstallLevel
from app.schemas.platform.plugin_oauth import (
    PluginAccessTokenResponse,
    PluginInstallationRead,
    PluginOAuthErrorResponse,
)
from app.services.marketplace import plugin_installs, plugin_oauth, registration_lookup

router = APIRouter()

#: RFC 6749 §5.1: a token response is never cached.
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"

#: The parameters this endpoint reads. Each may appear once.
_PARAMETERS = (
    "grant_type",
    "client_assertion_type",
    "client_assertion",
    "client_id",
    "installation",
    "scope",
    "resource",
    "level",
    "assertion",
)

_TOKEN_REQUEST_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            _FORM_CONTENT_TYPE: {
                "schema": {
                    "type": "object",
                    "required": ["grant_type"],
                    "properties": {
                        "grant_type": {
                            "type": "string",
                            "enum": [
                                plugin_oauth.GRANT_CLIENT_CREDENTIALS,
                                plugin_oauth.GRANT_JWT_BEARER,
                            ],
                        },
                        "client_assertion_type": {
                            "type": "string",
                            "enum": [plugin_oauth.ASSERTION_TYPE],
                        },
                        "client_assertion": {"type": "string"},
                        "client_id": {"type": "string"},
                        "installation": {"type": "string"},
                        "scope": {"type": "string"},
                        "resource": {"type": "string"},
                        "level": {
                            "type": "string",
                            "enum": [level.value for level in InstallLevel],
                        },
                        "assertion": {"type": "string"},
                    },
                }
            }
        },
    }
}


def _oauth_error(exc: plugin_oauth.OAuthError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "error_description": exc.description},
        headers=_NO_STORE,
    )


async def _read_form(request: Request) -> dict[str, str | None]:
    """The token request's parameters, each read once.

    Refuses anything but a form-encoded body, and a parameter sent twice
    (RFC 6749 §3.2). ``resource`` may be repeated under RFC 8707; this endpoint
    narrows to one initiative, so a second one is the target it cannot serve.
    """
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", 1)[0].strip().lower() != _FORM_CONTENT_TYPE:
        raise plugin_oauth.OAuthError(
            "invalid_request", f"the body must be {_FORM_CONTENT_TYPE}"
        )
    try:
        form = await request.form()
    except Exception as exc:
        raise plugin_oauth.OAuthError(
            "invalid_request", "the body could not be read"
        ) from exc
    values: dict[str, str | None] = {}
    for name in _PARAMETERS:
        entries = form.getlist(name)
        if len(entries) > 1:
            if name == "resource":
                raise plugin_oauth.OAuthError(
                    "invalid_target", "name at most one resource"
                )
            raise plugin_oauth.OAuthError("invalid_request", f"{name} is repeated")
        if not entries:
            values[name] = None
            continue
        value = entries[0]
        if not isinstance(value, str):
            raise plugin_oauth.OAuthError("invalid_request", f"{name} must be text")
        values[name] = value
    return values


@router.post(
    "/oauth/token",
    response_model=PluginAccessTokenResponse,
    responses={
        400: {"model": PluginOAuthErrorResponse},
        401: {"model": PluginOAuthErrorResponse},
    },
    openapi_extra=_TOKEN_REQUEST_BODY,
)
async def issue_plugin_access_token(
    request: Request, session: SystemSessionDep
) -> JSONResponse:
    """Issue a plug-in token, an installation token for one of the plug-in's
    installs, or a member token for a member who consented. See the module
    docstring for the parameters."""
    try:
        params = await _read_form(request)
        issued = await plugin_oauth.issue_token(
            session,
            grant_type=params["grant_type"],
            client_assertion_type=params["client_assertion_type"],
            client_assertion=params["client_assertion"],
            client_id=params["client_id"],
            installation=params["installation"],
            scope=params["scope"],
            resource=params["resource"],
            level=params["level"],
            assertion=params["assertion"],
        )
    except plugin_oauth.OAuthError as exc:
        return _oauth_error(exc)
    body = PluginAccessTokenResponse(
        access_token=issued.access_token,
        token_type="Bearer",
        expires_in=issued.expires_in,
        scope=issued.scope,
    )
    return JSONResponse(content=body.model_dump(), headers=_NO_STORE)


def _refuse() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _plugin_token(request: Request) -> PluginAccessToken:
    """The plug-in token this request carries, or 401. Reads nothing from the
    database."""
    unsealed = bearer_plugin_token(request)
    if not isinstance(unsealed, PluginAccessToken):
        raise _refuse()
    return unsealed


@router.get("/installations", response_model=list[PluginInstallationRead])
async def list_plugin_installations(
    request: Request,
    response: Response,
    limit: int = Query(
        default=plugin_installs.PAGE_LIMIT, ge=1, le=plugin_installs.PAGE_LIMIT
    ),
    cursor: str | None = Query(default=None, max_length=512),
) -> list[PluginInstallationRead]:
    """The calling plug-in's installs, a page at a time. Takes a plug-in token.

    The next page, when there is one, is named in a ``Link`` header
    (RFC 8288, ``rel="next"``) carrying the ``cursor`` to ask with.
    """
    token = _plugin_token(request)
    client = (await registration_lookup.load_registrations()).get(token.client_id)
    if client is None or not client.live:
        raise _refuse()
    listings, next_cursor = await plugin_oauth.list_installations(
        client, cursor=cursor, limit=limit
    )
    if next_cursor is not None:
        query = urlencode({"cursor": next_cursor, "limit": limit})
        response.headers["Link"] = f'<?{query}>; rel="next"'
    return [
        PluginInstallationRead(installation=listing.installation, active=listing.active)
        for listing in listings
    ]
