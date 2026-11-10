"""What this deployment publishes under ``/.well-known``.

``security.txt`` (RFC 9116) says where to report a security problem with this
server: its security contact, and the in-app form where security reports are
taken. It is a 404 where no address is set, rather than naming nobody.

The association files are what a phone reads before an app may run a passkey
ceremony for this deployment.

Both are served only when the deployment's address can carry a passkey at all
(``site_refusal``): a phone would refuse an IP address or plain http anyway.
They are JSON at their exact paths with no redirect, which is what Apple's and
Google's verifiers fetch; every other ``/.well-known`` path answers 404 (the
SPA catch-all reserves the prefix in ``app.main``).

``openid-configuration`` is Sign in with Initiative's provider metadata, for
plug-ins that people open at their own address.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core import native_apps
from app.services.auth import passkeys as passkey_service

router = APIRouter(prefix="/.well-known", include_in_schema=False)

#: The verifiers cache these files themselves; an hour keeps a change close.
_CACHE = {"Cache-Control": "public, max-age=3600"}


_ANDROID_RELATIONS = [
    "delegate_permission/common.get_login_creds",
    "delegate_permission/common.handle_all_urls",
]


@router.get("/assetlinks.json")
async def android_asset_links() -> JSONResponse:
    """The Android apps that may sign in to this deployment with a passkey.

    ``get_login_creds`` is the relation Google's Credential Manager reads;
    ``handle_all_urls`` is the one Bitwarden reads instead. Naming it opens no
    links in the app, which verifies no https host of its own.
    """
    if passkey_service.site_refusal() is not None:
        raise HTTPException(status_code=404)
    return JSONResponse(
        [
            {
                "relation": _ANDROID_RELATIONS,
                "target": {
                    "namespace": "android_app",
                    "package_name": package,
                    "sha256_cert_fingerprints": list(fingerprints),
                },
            }
            for package, fingerprints in native_apps.android_apps()
        ],
        headers=_CACHE,
    )


@router.get("/apple-app-site-association")
async def apple_app_site_association() -> JSONResponse:
    """The iOS apps that may sign in to this deployment with a passkey."""
    if passkey_service.site_refusal() is not None or not native_apps.IOS_APP_IDS:
        raise HTTPException(status_code=404)
    return JSONResponse(
        {"webcredentials": {"apps": list(native_apps.IOS_APP_IDS)}}, headers=_CACHE
    )


@router.get("/openid-configuration")
async def openid_configuration() -> JSONResponse:
    """Sign in with Initiative's provider metadata (OpenID Connect Discovery
    1.0): where a plug-in's library finds the endpoints and keys."""
    from app.services.marketplace import plugin_sign_in

    return JSONResponse(plugin_sign_in.discovery_document(), headers=_CACHE)


@router.get("/security.txt")
async def security_txt() -> PlainTextResponse:
    """Where to report a security problem with this server."""
    from app.core.config import settings
    from app.core.intake import IntakeStream
    from app.db import cohorts
    from app.services.platform import disclosure
    from app.services.platform.intake import contact_for, stream_is_bound

    async with cohorts.system_session(None) as session:
        contact = await contact_for(session, IntakeStream.security)
    form = (
        f"{settings.APP_URL.rstrip('/')}/my-tickets?report=security"
        if await stream_is_bound(IntakeStream.security)
        else None
    )
    body = disclosure.security_txt(contact=contact, form_url=form)
    if body is None:
        raise HTTPException(status_code=404)
    return PlainTextResponse(body, headers=_CACHE)
