"""This server's registration with BeyondersStudio's push relay.

The relay sends pushes to the official app for any server: iPhone pushes
always, and Android pushes for a server with no Firebase service account of
its own. Its send call is FCM's own, so ``push_notifications`` builds the same
message either way and only the address and the credential differ.

A server registers once (``POST /v1/servers``) and is issued an id and a key.
They are kept beside the service account on ``app_setting_secrets`` (the key
Fernet-encrypted), read and written on the system engine, and cached in this
process. Registering happens when the app first asks for the push settings
(``GET /settings/fcm-config``) or on the first push that needs the relay,
whichever comes first, so a server whose operator never switches push on
never contacts it.

A server never holds a device's own token for a relay platform. The app
registers that token with the relay for this server's id and is given a
*handle* (``rh_`` and 43 base64url characters), which is what it registers
here and what a send names. A handle reaches only the device that chose this
server, and the relay answers ``404`` for one it does not know, so the row is
deleted like any other dead token. A new registration means a new id: the
app sees it in the push settings on its next launch and asks for a new handle.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

import httpx2
from cryptography.fernet import InvalidToken
from sqlalchemy import update
from sqlmodel import select

from app.core.encryption import SALT_PUSH_RELAY_KEY, decrypt_field, encrypt_field
from app.models.platform.app_setting_secret import AppSettingSecret

logger = logging.getLogger(__name__)

#: The relay's public address.
PUSH_RELAY_URL = "https://push-relay.beyonders.studio"

#: How long after a failed registration this process waits before trying
#: again. The relay allows a few registrations a day per address.
REGISTRATION_RETRY_SECONDS = 300.0

#: How long the relay's Android settings are kept once fetched, and how long a
#: failed fetch is remembered before the next one is tried.
ANDROID_CONFIG_TTL_SECONDS = 3600.0
ANDROID_CONFIG_RETRY_SECONDS = 300.0

#: What the relay hands the app for a device token: ``rh_`` and the unpadded
#: base64url of a SHA-256 HMAC.
_HANDLE = re.compile(r"rh_[A-Za-z0-9_-]{43}")

#: The settings singleton's id, which its credentials row shares.
_ROW_ID = 1

_TABLE = AppSettingSecret.__table__
_SERVER_ID = _TABLE.c.push_relay_server_id
_KEY = _TABLE.c.push_relay_key_encrypted


@dataclass(frozen=True)
class AndroidConfig:
    """The Firebase settings the Android app starts with on a relay server."""

    project_id: str
    application_id: str
    api_key: str
    sender_id: str


_credentials: tuple[str, str] | None = None
_lock = asyncio.Lock()
_last_failed_registration: float | None = None

_android: tuple[float, AndroidConfig | None] | None = None
_android_lock = asyncio.Lock()


def is_handle(push_token: str) -> bool:
    """Whether a registered token is a relay handle rather than a device's own."""
    return _HANDLE.fullmatch(push_token) is not None


async def current_server_id(client: httpx2.AsyncClient) -> str | None:
    """This server's relay id, registering first if it has none; the app asks
    the relay for a handle under it. None while registering fails."""
    held = await credentials(client)
    return held[0] if held is not None else None


def send_url(project_id: str | None) -> str:
    """The relay's send call. The project in the path is not read by it."""
    return f"{PUSH_RELAY_URL}/v1/projects/{project_id or 'relay'}/messages:send"


def authorization(server_id: str, key: str) -> str:
    return f"Bearer {server_id}.{key}"


#: What every server tells the relay it is called. The relay needs a name, not
#: this one's: its address would tell BeyondersStudio where it runs.
SERVER_NAME = "Initiative server"


async def _load_stored() -> tuple[str, str] | None:
    """The stored credential, or None. One that no longer decrypts under
    ``SECRET_KEY`` is cleared, so the next registration can replace it."""
    from app.db import session as db_session

    async with db_session.SystemSessionLocal() as system_session:
        row = (
            await system_session.exec(
                select(_SERVER_ID, _KEY).where(_TABLE.c.id == _ROW_ID)
            )
        ).one_or_none()
    if row is None or not row[0] or not row[1]:
        return None
    server_id, encrypted = row
    try:
        return server_id, decrypt_field(encrypted, SALT_PUSH_RELAY_KEY)
    except InvalidToken:
        logger.error(
            "push relay: the stored key does not decrypt under SECRET_KEY; "
            "this server will register with the relay again."
        )
        await _clear_stored(server_id)
        return None


async def _store(server_id: str, key: str) -> tuple[str, str] | None:
    """Keep a new registration unless another process already kept one, and
    answer whichever is stored."""
    from app.db import session as db_session
    from app.services.platform.app_settings import (
        _ensure_secrets_row,
    )

    async with db_session.SystemSessionLocal() as system_session:
        await _ensure_secrets_row(system_session)
        await system_session.exec(
            update(_TABLE)
            .where(_TABLE.c.id == _ROW_ID, _SERVER_ID.is_(None))
            .values(
                {
                    _SERVER_ID: server_id,
                    _KEY: encrypt_field(key, SALT_PUSH_RELAY_KEY),
                }
            )
        )
        await system_session.commit()
    return await _load_stored()


async def _clear_stored(server_id: str) -> None:
    """Clear the stored credential, if it is still this one."""
    from app.db import session as db_session

    async with db_session.SystemSessionLocal() as system_session:
        await system_session.exec(
            update(_TABLE)
            .where(_TABLE.c.id == _ROW_ID, _SERVER_ID == server_id)
            .values({_SERVER_ID: None, _KEY: None})
        )
        await system_session.commit()


async def _register(client: httpx2.AsyncClient) -> tuple[str, str] | None:
    try:
        response = await client.post(
            f"{PUSH_RELAY_URL}/v1/servers", json={"name": SERVER_NAME}
        )
    except httpx2.HTTPError as exc:
        logger.warning("push relay: could not register: %s", exc)
        return None
    if response.status_code != 201:
        logger.error(
            "push relay: registration refused (status %s, %s byte answer)",
            response.status_code,
            len(response.content),
        )
        return None
    try:
        body = response.json()
        server_id, key = body["server_id"], body["server_key"]
    except (ValueError, KeyError, TypeError):
        logger.error("push relay: registration answered without a credential")
        return None
    if not (
        isinstance(server_id, str)
        and isinstance(key, str)
        and 0 < len(server_id) <= 64
        and key
    ):
        logger.error("push relay: registration answered without a credential")
        return None
    logger.info("push relay: registered as %s", server_id)
    return server_id, key


async def credentials(client: httpx2.AsyncClient) -> tuple[str, str] | None:
    """This server's relay id and key, registering first if it has none.

    None when there is no credential and registering failed; a later call
    tries again, at most once every :data:`REGISTRATION_RETRY_SECONDS`.
    """
    global _credentials, _last_failed_registration
    if _credentials is not None:
        return _credentials
    async with _lock:
        if _credentials is not None:
            return _credentials
        stored = await _load_stored()
        if stored is None:
            if (
                _last_failed_registration is not None
                and time.monotonic() - _last_failed_registration
                < REGISTRATION_RETRY_SECONDS
            ):
                return None
            registered = await _register(client)
            if registered is None:
                _last_failed_registration = time.monotonic()
                return None
            stored = await _store(*registered)
            if stored is None:  # pragma: no cover - the UPDATE landed or lost
                _last_failed_registration = time.monotonic()
                return None
        _last_failed_registration = None
        _credentials = stored
        return _credentials


async def forget(server_id: str) -> None:
    """Drop a credential the relay no longer accepts, here and where it is
    stored, so the next push registers again."""
    global _credentials, _last_failed_registration, _android
    async with _lock:
        if _credentials is not None and _credentials[0] == server_id:
            _credentials = None
        _last_failed_registration = None
        await _clear_stored(server_id)
    if _android is not None and _android[1] is None:
        _android = None
    logger.warning("push relay: %s is no longer accepted; registering again", server_id)


async def android_config(client: httpx2.AsyncClient) -> AndroidConfig | None:
    """The relay's Android Firebase settings, or None if it could not say."""
    global _android
    now = time.monotonic()
    if _android is not None and now < _android[0]:
        return _android[1]
    async with _android_lock:
        if _android is not None and time.monotonic() < _android[0]:
            return _android[1]
        config = await _fetch_android_config(client)
        ttl = (
            ANDROID_CONFIG_TTL_SECONDS
            if config is not None
            else ANDROID_CONFIG_RETRY_SECONDS
        )
        _android = (time.monotonic() + ttl, config)
        return config


async def _fetch_android_config(client: httpx2.AsyncClient) -> AndroidConfig | None:
    held = await credentials(client)
    if held is None:
        return None
    server_id, key = held
    try:
        response = await client.get(
            f"{PUSH_RELAY_URL}/v1/android-config",
            headers={"Authorization": authorization(server_id, key)},
        )
    except httpx2.HTTPError as exc:
        logger.warning("push relay: could not read the Android settings: %s", exc)
        return None
    if response.status_code == 401:
        await forget(server_id)
        return None
    if response.status_code != 200:
        logger.error(
            "push relay: Android settings unavailable (status %s, %s byte answer)",
            response.status_code,
            len(response.content),
        )
        return None
    try:
        body = response.json()
        return AndroidConfig(
            project_id=str(body["project_id"]),
            application_id=str(body["application_id"]),
            api_key=str(body["api_key"]),
            sender_id=str(body["sender_id"]),
        )
    except (ValueError, KeyError, TypeError):
        logger.error("push relay: the Android settings were not readable")
        return None


def reset_for_tests() -> None:
    """Drop everything this process holds, so the next call starts over."""
    global _credentials, _last_failed_registration, _android, _lock, _android_lock
    _credentials = None
    _last_failed_registration = None
    _android = None
    _lock = asyncio.Lock()
    _android_lock = asyncio.Lock()
