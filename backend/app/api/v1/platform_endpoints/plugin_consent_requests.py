"""Where an installed plug-in asks a member to let it act as them.

``POST /plugin-platform/consent-requests`` takes an **installation token** and
names the member by the reference this install holds for them, a ``purpose``
(the plug-in's own id for what it wants to do; absent for app-wide consent), a
``label`` in the plug-in's own words, optionally the initiative the purpose is
bound to, and ``access`` (``read`` or ``read_write``).

The request is routed and stood up by the install seam
(``establish_install_access``), whose standing statement also resolves the
member's reference in the install's own sector, and admits the install only
while it may act. Asking again for the same member and purpose returns the
request as it stands (``200``); a new one is ``201`` and the member is
notified. The member answers on their own consent screen; the plug-in learns the
answer here, or from the token endpoint (``consent_required``).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import (
    InstallAccessError,
    SessionDep,
    VerifiedInstall,
    establish_install_access,
    oauth2_scheme,
)
from app.core.identify import bearer_plugin_token
from app.core.messages import AuthMessages, PluginMessages
from app.core.plugin_access_token import InstallAccessToken
from app.core.rate_limit import (
    CONSENT_REQUESTS_PER_INSTALL,
    NEW_CONSENT_REQUESTS_PER_MEMBER,
    allowance_left,
    take_allowance,
)
from app.db.session import clear_rls_context
from app.models.platform.identity_ref import IdentityEntity
from app.models.tenant.plugin_member_consent import ConsentStatus
from app.schemas.platform.plugin_oauth import (
    PluginConsentRequestCreate,
    PluginConsentRequestRead,
)
from app.services.marketplace import plugin_consent_requests

router = APIRouter()

#: The counter namespace for this endpoint's allowances.
_LIMIT_NAMESPACE = "plugin-consent-requests"


def _refuse() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _limited() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=PluginMessages.CONSENT_RATE_LIMITED,
    )


def _installation_token(request: Request) -> InstallAccessToken:
    """The installation token this request carries, or 401. A member token
    acts for somebody and asks nobody. Reads nothing from the database."""
    token = bearer_plugin_token(request)
    if not isinstance(token, InstallAccessToken) or token.user_id is not None:
        raise _refuse()
    return token


@router.post(
    "/consent-requests",
    response_model=PluginConsentRequestRead,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": PluginConsentRequestRead}},
)
async def request_member_consent(
    request: Request,
    response: Response,
    payload: PluginConsentRequestCreate,
    session: SessionDep,
    # Declares the scheme for the API description; read by ``bearer_plugin_token``.
    bearer: Annotated[str | None, Depends(oauth2_scheme)] = None,
) -> PluginConsentRequestRead:
    """Ask a member to let this plug-in act as them, for one purpose.

    Takes an installation token. ``200`` returns a request already made for
    that member and purpose, as it stands; ``201`` a new one, and the member is
    told. A token narrowed to one initiative asks only for a purpose bound to
    it, and a purpose is bound only to an initiative the install is placed in.

    Limited per install (30 a minute, repeats included) and per install and
    member (5 new requests an hour); past either the answer is 429.
    """
    token = _installation_token(request)
    try:
        context = await establish_install_access(
            session,
            VerifiedInstall(
                guild_id=token.guild_id,
                install_id=token.install_id,
                client_id=token.client_id,
                scopes=token.scopes,
                initiative_id=token.initiative_id,
            ),
            [payload.member],
        )
    except InstallAccessError as exc:
        raise _refuse() from exc
    # The standing is all this request reads on its own session.
    clear_rls_context(session)
    await session.rollback()

    # Counted by the install, whatever it asks.
    install_key = f"{context.client_id}:{context.guild_id}:{context.install_id}"
    if not await take_allowance(
        CONSENT_REQUESTS_PER_INSTALL, _LIMIT_NAMESPACE, f"install:{install_key}"
    ):
        raise _limited()

    member_id = next(
        (
            entity_id
            for ref, entity_type, entity_id in context.named_refs
            if ref == payload.member and entity_type == IdentityEntity.user.value
        ),
        None,
    )
    if member_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PluginMessages.REFERENCE_UNKNOWN,
        )
    if (
        context.scope_initiative_id is not None
        and payload.initiative_id != context.scope_initiative_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=PluginMessages.CONSENT_OUTSIDE_TOKEN,
        )
    if (
        payload.initiative_id is not None
        and payload.initiative_id not in context.member_initiatives
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PluginMessages.CONSENT_INITIATIVE_NOT_PLACED,
        )

    # New requests of one member are counted apart; repeating one already
    # made notifies nobody and is not.
    member_key = f"member:{install_key}:{member_id}"
    try:
        recorded = await plugin_consent_requests.record_request(
            guild_id=context.guild_id,
            install_id=context.install_id,
            user_id=member_id,
            purpose=payload.purpose,
            label=payload.label,
            initiative_id=payload.initiative_id,
            access=payload.access,
            may_create=await allowance_left(
                NEW_CONSENT_REQUESTS_PER_MEMBER, _LIMIT_NAMESPACE, member_key
            ),
        )
    except plugin_consent_requests.ConsentRequestLimited as exc:
        raise _limited() from exc
    except plugin_consent_requests.ConsentMemberNotInInitiative as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PluginMessages.CONSENT_MEMBER_NOT_IN_INITIATIVE,
        ) from exc
    if recorded is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=PluginMessages.REFERENCE_UNKNOWN,
        )
    if recorded.created:
        await take_allowance(
            NEW_CONSENT_REQUESTS_PER_MEMBER, _LIMIT_NAMESPACE, member_key
        )
    else:
        response.status_code = status.HTTP_200_OK
    return PluginConsentRequestRead(
        member=payload.member,
        purpose=recorded.purpose,
        label=recorded.label,
        initiative_id=recorded.initiative_id,
        requested_access=recorded.requested_access,
        status=recorded.status,
        granted_access=(
            recorded.granted_access
            if recorded.status is ConsentStatus.granted
            else None
        ),
        requested_at=recorded.requested_at,
    )
