"""A vendor's own flow for making a plug-in's vendor client.

A plug-in's manifest may declare ``vendor.setup``: a flow at the vendor that
creates the client the plug-in's connections use on this deployment, and answers
with its values. Initiative runs it from the operator's browser and writes the
answers into the registration's vendor values through the write the settings
form uses, so none is typed or copied.

``github_app_manifest`` is the one flow. GitHub creates a GitHub App from a
manifest the browser posts to it, sends the operator back with a code, and
exchanges that code once for the new GitHub App's id, slug, client id and secret,
webhook secret and private key.

* :func:`start` builds the manifest, the plug-in's own declaration with the
  addresses Initiative already knows filled in, and a state for the operator's
  browser to carry to GitHub and back.
* :func:`complete` checks the state, exchanges the code, and writes each value
  to the vendor field the manifest names.

The state seals what the setup was started with: the registration, its
listing and listing version, and which vendor field each answer is written to.
It is recorded as an ``auth_challenges`` row naming the operator who started
the setup, answered by the registration it is for. It lasts an hour, and the
first completion by that operator for that registration spends it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from fastapi import status as http_status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_PLUGIN_VENDOR_SETUP, decrypt_field, encrypt_field
from app.core.messages import PluginServiceMessages
from app.models.platform.marketplace import MarketplaceListing
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.services.auth import challenges as challenge_service
from app.services.marketplace import registrations as registrations_service
from app.services.marketplace import vendor_values as vendor_values_service
from app.services.marketplace.manifest_values import ListingDefinitionError
from app.services.marketplace.service_plugins import (
    GITHUB_APP_MANIFEST,
    check_setup_values,
)
from app.services.safe_http import ResponseTooLargeError, request_public_target
from app.services.tenant import plugin_connection_flows as flows_service
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "STATE_TTL",
    "VendorSetupStart",
    "complete",
    "redirect_url",
    "setup_kind",
    "start",
]

#: How long an operator has to confirm the GitHub App on GitHub and come back.
STATE_TTL = timedelta(hours=1)

GITHUB_URL = "https://github.com"
GITHUB_API_URL = "https://api.github.com"
#: What the conversion may take and answer with.
TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 64 * 1024

#: A GitHub account name: letters, digits and hyphens, at most 39.
_ORGANIZATION_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
)
_MAX_ORGANIZATION = 39
#: What a code GitHub returns is made of.
_CODE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)
_MAX_CODE = 128

#: Injectable for tests: the transport the conversion uses.
http_transport: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class VendorSetupStart:
    """Where the operator's browser posts the manifest, and what it carries."""

    #: The page at GitHub that takes the manifest, without the state.
    action: str
    #: The manifest, as the JSON text the form field holds.
    manifest: str
    state: str


def setup_kind(definition: Mapping[str, Any] | None) -> str | None:
    """The vendor setup flow a manifest declares, when it is one this build
    runs."""
    setup = ((definition or {}).get("vendor") or {}).get("setup")
    if isinstance(setup, dict) and setup.get("kind") == GITHUB_APP_MANIFEST:
        return GITHUB_APP_MANIFEST
    return None


def redirect_url(registration_id: int) -> str:
    """The settings page GitHub sends the operator back to with its code."""
    return (
        f"{settings.APP_URL.rstrip('/')}/settings/platform/integrations"
        f"/vendor-setup/{registration_id}"
    )


async def _manifest(
    session: AsyncSession, row: PluginServiceRegistration
) -> tuple[int | None, dict[str, Any]]:
    """The registration's listing version and its manifest, as they are now."""
    version = (
        await session.exec(
            select(MarketplaceListing.latest_version_id).where(
                MarketplaceListing.uid == row.listing_uid
            )
        )
    ).first()
    definition = (
        await vendor_values_service.listing_definitions(session, [row.listing_uid])
    ).get(row.listing_uid or "")
    return version, definition or {}


def _organization(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if (
        len(cleaned) > _MAX_ORGANIZATION
        or any(char not in _ORGANIZATION_CHARS for char in cleaned)
        or cleaned.startswith("-")
    ):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=PluginServiceMessages.VENDOR_SETUP_INVALID_ORGANIZATION,
        )
    return cleaned


async def start(
    session: AsyncSession,
    registration_id: int,
    *,
    organization: str | None,
    actor_user_id: int,
) -> VendorSetupStart:
    """Build the manifest for the plug-in's GitHub App, owned by ``organization``
    or by the operator's own account, and open the state that brings the
    operator back."""
    row = await registrations_service.get_registration(session, registration_id)
    version, definition = await _manifest(session, row)
    if setup_kind(definition) is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=PluginServiceMessages.VENDOR_SETUP_UNAVAILABLE,
        )
    setup = definition["vendor"]["setup"]
    owner = _organization(organization)
    action = (
        f"{GITHUB_URL}/organizations/{owner}/settings/apps/new"
        if owner
        else f"{GITHUB_URL}/settings/apps/new"
    )
    manifest = {
        **setup["app"],
        "redirect_url": redirect_url(row.id),
        "callback_urls": [flows_service.callback_url()],
        "setup_url": flows_service.setup_url(),
        "hook_attributes": {
            "url": flows_service.webhook_url(row.public_id),
            "active": True,
        },
    }
    state = encrypt_field(
        json.dumps(
            {
                "listing_uid": row.listing_uid,
                "version": version,
                "values": setup["values"],
            }
        ),
        SALT_PLUGIN_VENDOR_SETUP,
    )
    await challenge_service.create(
        session,
        user_id=actor_user_id,
        purpose=challenge_service.ChallengePurpose.plugin_vendor_setup,
        value=state,
        answer=str(row.id),
        ttl=STATE_TTL,
    )
    await session.commit()
    return VendorSetupStart(action=action, manifest=json.dumps(manifest), state=state)


def _expired() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_400_BAD_REQUEST,
        detail=PluginServiceMessages.VENDOR_SETUP_EXPIRED,
    )


def _failed() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_502_BAD_GATEWAY,
        detail=PluginServiceMessages.VENDOR_SETUP_FAILED,
    )


async def _spend_state(
    session: AsyncSession, *, registration_id: int, state: str, actor_user_id: int
) -> dict[str, Any]:
    """Spend the state when this operator opened it for this registration,
    and read what it sealed. A state that does not match is refused and left
    for the completion it belongs to."""
    spent = await challenge_service.spend_answered(
        session,
        value=state,
        purpose=challenge_service.ChallengePurpose.plugin_vendor_setup,
        user_id=actor_user_id,
        answer=str(registration_id),
    )
    await session.commit()
    if not spent:
        raise _expired()
    try:
        sealed = json.loads(decrypt_field(state, SALT_PLUGIN_VENDOR_SETUP))
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise _expired() from exc
    if not isinstance(sealed, dict) or not isinstance(sealed.get("values"), dict):
        raise _expired()
    return sealed


async def _convert(code: str) -> dict[str, Any]:
    """GitHub's answer for the code: the new GitHub App's values."""
    if not code or len(code) > _MAX_CODE or any(c not in _CODE_CHARS for c in code):
        raise _failed()
    url = f"{GITHUB_API_URL}/plugin-manifests/{quote(code, safe='')}/conversions"
    try:
        response = await request_public_target(
            "POST",
            url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=TIMEOUT_SECONDS,
            transport=http_transport,
            max_bytes=MAX_RESPONSE_BYTES,
        )
        body = response.json() if response.status_code < 400 else None
    except (
        httpx.HTTPError,
        ResponseTooLargeError,
        WebhookTargetUrlError,
        WebhookTargetUrlPrivateError,
        ValueError,
    ) as exc:
        logger.warning("plug-in services: the GitHub App conversion failed (%s)", exc)
        raise _failed() from exc
    if not isinstance(body, dict):
        logger.warning(
            "plug-in services: GitHub answered the conversion with %s",
            response.status_code,
        )
        raise _failed()
    return body


async def complete(
    session: AsyncSession,
    registration_id: int,
    *,
    code: str,
    state: str,
    actor_user_id: int,
) -> PluginServiceRegistration:
    """Finish the setup GitHub sent the operator back from: exchange its code,
    and write each value GitHub answers with to the vendor field the setup
    named when it started, all of them in one write or none.

    Refused without writing when the registration's listing is another one
    now, or when a newer version of it no longer declares a named field, or
    no longer as a secret where a secret is written."""
    sealed = await _spend_state(
        session,
        registration_id=registration_id,
        state=state,
        actor_user_id=actor_user_id,
    )
    mapping: dict[str, Any] = sealed["values"]
    row = await registrations_service.get_registration(session, registration_id)
    if row.listing_uid != sealed.get("listing_uid"):
        raise _expired()
    version, definition = await _manifest(session, row)
    if version != sealed.get("version"):
        try:
            check_setup_values(
                mapping, fields=vendor_values_service.vendor_fields(definition)
            )
        except ListingDefinitionError as exc:
            logger.info("plug-in services: a vendor setup no longer fits (%s)", exc)
            raise _expired() from exc
    answer = await _convert(code)
    values: dict[str, str | None] = {}
    for key, name in mapping.items():
        value = answer.get(name)
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise _failed()
        if not str(value).strip():
            raise _failed()
        values[key] = str(value)
    return await registrations_service.update_registration(
        session, registration_id, vendor_values=values, actor_user_id=actor_user_id
    )
