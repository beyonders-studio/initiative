"""Resolved push-notification (FCM) configuration with a process-wide cache.

``app.services.platform.push_notifications`` mints an FCM access token from
``_get_fcm_access_token``, which holds no database session — and the credential it needs is the service-account JSON on
``app_setting_secrets``, which no request-path role may read. So the resolved
configuration is a process-level snapshot here, the same shape
``app.services.storage_config`` and ``app.services.captcha_config`` use.

Push is dispatched from background work as often as from a request, which is
why :func:`ensure_push_config_fresh` opens its own system-engine session rather
than taking one: there is frequently no caller session to borrow.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_FCM_SERVICE_ACCOUNT, decrypt_field

#: How long a snapshot is trusted before a dispatch reloads it. The 30 seconds
#: its sibling modules use.
_TTL_SECONDS = 30.0

_resolved: ResolvedPushConfig | None = None
_loaded_at: float = 0.0


@dataclass(frozen=True)
class ResolvedPushConfig:
    """The effective push configuration."""

    enabled: bool
    project_id: str | None
    application_id: str | None
    api_key: str | None
    sender_id: str | None
    service_account_json: str | None  # decrypted plaintext, or None when unset


async def resolve_saved_service_account() -> str | None:
    """Decrypt the stored service-account JSON, or None when unset."""
    from app.services.platform.app_settings import (
        load_app_setting_secrets,
    )

    row = await load_app_setting_secrets()
    if not row.fcm_service_account_json_encrypted:
        return None
    return decrypt_field(
        row.fcm_service_account_json_encrypted, SALT_FCM_SERVICE_ACCOUNT
    )


async def refresh_push_config(session: AsyncSession) -> ResolvedPushConfig:
    """Reload the snapshot from ``app_settings`` and the stored credential."""
    global _resolved, _loaded_at
    from app.services.platform.app_settings import get_app_settings

    row = await get_app_settings(session)
    _resolved = ResolvedPushConfig(
        enabled=bool(row.fcm_enabled),
        project_id=row.fcm_project_id,
        application_id=row.fcm_application_id,
        api_key=row.fcm_api_key,
        sender_id=row.fcm_sender_id,
        service_account_json=await resolve_saved_service_account(),
    )
    _loaded_at = time.monotonic()
    return _resolved


async def ensure_push_config_fresh() -> ResolvedPushConfig:
    """Reload if stale or never loaded, on a session of its own."""
    if _resolved is not None and (time.monotonic() - _loaded_at) <= _TTL_SECONDS:
        return _resolved
    from app.db import session as db_session

    async with db_session.SystemSessionLocal() as system_session:
        return await refresh_push_config(system_session)


def reset_for_tests() -> None:
    """Drop the snapshot so the next read resolves again."""
    global _resolved, _loaded_at
    _resolved = None
    _loaded_at = 0.0
