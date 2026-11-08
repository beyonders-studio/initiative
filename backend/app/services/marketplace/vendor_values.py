"""What an operator supplies for a plug-in's vendor client.

A plug-in's manifest may declare a ``vendor`` block: the values its vendor's own
client needs on this deployment, such as a client id, a client secret or a
signing key. Initiative runs the plug-in's connection flows with them, so they are
held on the plug-in's registration (``vendor_values``), one Fernet ciphertext per
field, and never on an install.

They arrive three ways, all on the system engine:

* the operator's registration form (``plugins.manage``), which may also set them
  on a registration the registry brought;
* ``vendor_env`` on an ``PLUGIN_SERVICES_CONFIG`` entry, which names environment
  variables read at boot, so rotating one is changing the variable and
  restarting;
* nowhere else. A manifest declares the fields and never carries a value.

A secret leaves this module in one direction only: decrypted for the flow that
uses it (:func:`load_vendor_values`). The operator's form is told which fields
hold a value, and sees the plain value of a non-secret one.

``vendor_required`` is kept in step with the listing's latest manifest here,
and the database computes ``vendor_ready`` from it, which is part of whether a
registration is live.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from fastapi import status as http_status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_PLUGIN_VENDOR, decrypt_field, encrypt_field
from app.core.messages import PluginServiceMessages
from app.db import session as db_session
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.plugin_service_registration import PluginServiceRegistration

logger = logging.getLogger(__name__)

__all__ = [
    "MAX_VENDOR_VALUE_LENGTH",
    "VendorView",
    "apply_vendor_env",
    "apply_vendor_values",
    "listing_definitions",
    "load_vendor_values",
    "required_keys",
    "sync_required",
    "sync_required_for_listing",
    "vendor_fields",
    "vendor_view",
]

#: What one value may hold. Large enough for a PEM private key.
MAX_VENDOR_VALUE_LENGTH = 16_000


def vendor_fields(definition: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """The fields a manifest's ``vendor`` block declares, in order."""
    vendor = (definition or {}).get("vendor")
    if not isinstance(vendor, dict):
        return []
    fields = vendor.get("fields")
    if not isinstance(fields, list):
        return []
    return [
        field
        for field in fields
        if isinstance(field, dict) and isinstance(field.get("key"), str)
    ]


def required_keys(definition: Mapping[str, Any] | None) -> list[str]:
    """The keys a manifest's ``vendor`` block marks required, sorted."""
    return sorted(
        {
            field["key"]
            for field in vendor_fields(definition)
            if field.get("required") is True
        }
    )


# --- the listing's manifest -------------------------------------------------


async def listing_definitions(
    session: AsyncSession, listing_uids: Iterable[str | None]
) -> dict[str, dict[str, Any]]:
    """Each listing's latest definition, by uid, in one statement."""
    wanted = {uid for uid in listing_uids if uid}
    if not wanted:
        return {}
    rows = (
        await session.exec(
            select(MarketplaceListing.uid, MarketplaceListingVersion.definition)
            .join(
                MarketplaceListingVersion,
                MarketplaceListingVersion.id == MarketplaceListing.latest_version_id,
            )
            .where(MarketplaceListing.uid.in_(wanted))
        )
    ).all()
    return {uid: dict(definition or {}) for uid, definition in rows}


async def sync_required(session: AsyncSession, row: PluginServiceRegistration) -> None:
    """Bring ``vendor_required`` in line with the listing's latest manifest.

    A registration whose listing is not in the catalog yet requires nothing
    until it is; publishing the listing brings it in line
    (:func:`sync_required_for_listing`).
    """
    definitions = await listing_definitions(session, [row.listing_uid])
    wanted = required_keys(definitions.get(row.listing_uid or ""))
    if list(row.vendor_required or []) != wanted:
        row.vendor_required = wanted
        session.add(row)


async def sync_required_for_listing(
    session: AsyncSession, listing_uid: str, definition: Mapping[str, Any] | None
) -> None:
    """Bring every registration speaking for a listing in line with a newly
    published version of it."""
    wanted = required_keys(definition)
    rows = (
        await session.exec(
            select(PluginServiceRegistration).where(
                PluginServiceRegistration.listing_uid == listing_uid
            )
        )
    ).all()
    for row in rows:
        if list(row.vendor_required or []) != wanted:
            row.vendor_required = wanted
            session.add(row)


# --- writing ----------------------------------------------------------------


def _bad(detail: str) -> HTTPException:
    logger.debug("vendor value refused: %s", detail)
    return HTTPException(
        status_code=http_status.HTTP_400_BAD_REQUEST,
        detail=PluginServiceMessages.INVALID_VENDOR_VALUE,
    )


def _checked(field: Mapping[str, Any] | None, value: str) -> str:
    text = value.strip()
    if not text:
        raise _bad("empty value")
    if len(text) > MAX_VENDOR_VALUE_LENGTH:
        raise _bad("value too long")
    if (
        field is not None
        and field.get("type") == "url"
        and (not text.startswith(("https://", "http://")) or " " in text)
    ):
        raise _bad("not a URL")
    return text


def apply_vendor_values(
    row: PluginServiceRegistration,
    submitted: Mapping[str, str | None],
    *,
    definition: Mapping[str, Any] | None,
) -> list[str]:
    """Set or clear values the listing's manifest declares.

    A key with ``None`` or an empty string clears the value; a key left out is
    untouched, so a form that leaves a secret alone keeps it. A key the
    manifest does not declare is refused. Returns the keys that changed.
    """
    fields = {field["key"]: field for field in vendor_fields(definition)}
    stored = dict(row.vendor_values or {})
    changed: list[str] = []
    for key, value in submitted.items():
        if key not in fields:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=PluginServiceMessages.UNKNOWN_VENDOR_FIELD,
            )
        if value is None or (isinstance(value, str) and not value.strip()):
            if key in stored:
                stored.pop(key)
                changed.append(key)
            continue
        if not isinstance(value, str):
            raise _bad("not a string")
        stored[key] = encrypt_field(_checked(fields[key], value), SALT_PLUGIN_VENDOR)
        changed.append(key)
    if changed:
        # Reassigned rather than mutated: a JSONB column is tracked by identity.
        row.vendor_values = stored
    return sorted(changed)


def apply_vendor_env(
    row: PluginServiceRegistration, vendor_env: Any, *, public_id: str
) -> list[str]:
    """Seal the environment variables an ``PLUGIN_SERVICES_CONFIG`` entry names.

    ``vendor_env`` maps a vendor key to the name of an environment variable.
    A variable that is unset or empty is logged and leaves that value as it
    was. Returns the keys whose value changed.
    """
    if vendor_env is None:
        return []
    if not isinstance(vendor_env, dict):
        logger.warning("plug-in services: %r vendor_env is not an object", public_id)
        return []
    stored = dict(row.vendor_values or {})
    current = _decrypt_all(stored, public_id=public_id)
    changed: list[str] = []
    for key, variable in vendor_env.items():
        if not isinstance(key, str) or not isinstance(variable, str) or not variable:
            logger.warning(
                "plug-in services: %r vendor_env entry %r is not a name", public_id, key
            )
            continue
        raw = os.environ.get(variable, "")
        if not raw.strip():
            logger.warning(
                "plug-in services: %r names %s for vendor value %r, which is not set",
                public_id,
                variable,
                key,
            )
            continue
        try:
            value = _checked(None, raw)
        except HTTPException:
            logger.warning(
                "plug-in services: %r vendor value %r from %s is too long",
                public_id,
                key,
                variable,
            )
            continue
        if current.get(key) == value:
            continue
        stored[key] = encrypt_field(value, SALT_PLUGIN_VENDOR)
        changed.append(key)
    if changed:
        row.vendor_values = stored
    return sorted(changed)


# --- reading ----------------------------------------------------------------


def _decrypt_all(stored: Mapping[str, Any], *, public_id: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, ciphertext in stored.items():
        if not isinstance(ciphertext, str):
            continue
        try:
            values[key] = decrypt_field(ciphertext, SALT_PLUGIN_VENDOR)
        except (InvalidToken, UnicodeDecodeError):
            logger.warning(
                "plug-in services: %r vendor value %r does not decrypt", public_id, key
            )
    return values


@dataclass(frozen=True)
class VendorView:
    """What the operator's form is shown about one registration's values."""

    #: The fields the listing's manifest declares, as it declares them.
    fields: list[dict[str, Any]]
    #: The plain values of the non-secret fields that hold one.
    values: dict[str, str]
    #: Every declared key that holds a value, secret or not.
    set_keys: list[str]


def vendor_view(
    row: PluginServiceRegistration, definition: Mapping[str, Any] | None
) -> VendorView:
    fields = vendor_fields(definition)
    stored = row.vendor_values or {}
    secret = {field["key"] for field in fields if field.get("type") == "secret"}
    plain = {
        key: ciphertext
        for key, ciphertext in stored.items()
        if key not in secret and any(field["key"] == key for field in fields)
    }
    return VendorView(
        fields=[
            {
                "key": field["key"],
                "type": field.get("type") or "string",
                "required": field.get("required") is True,
                "label": field.get("label") or {},
            }
            for field in fields
        ],
        values=_decrypt_all(plain, public_id=row.public_id),
        set_keys=sorted(key for key in stored if any(f["key"] == key for f in fields)),
    )


async def load_vendor_values(public_id: str) -> dict[str, str]:
    """The decrypted values for one plug-in, for the flow about to use them.

    Read on the system engine per call rather than cached, so a value an
    operator replaces is the one the next flow uses.
    """
    async with db_session.SystemSessionLocal() as session:
        row = (
            await session.exec(
                select(PluginServiceRegistration).where(
                    PluginServiceRegistration.public_id == public_id
                )
            )
        ).first()
    if row is None:
        return {}
    return _decrypt_all(row.vendor_values or {}, public_id=public_id)
