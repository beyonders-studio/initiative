"""Resolved object-storage configuration with a process-wide cache.

The storage backend (``app/services/storage.py``) is built by synchronous,
session-less functions, so it can't read the DB-backed config (``AppSetting``)
on every call. This module owns a small process-level snapshot of the *resolved*
storage config and the rules for refreshing it:

- :func:`current_storage_config` is the sync accessor the storage module reads.
  Before the first DB load (and in CLI scripts / tests) it falls back to the env
  ``settings``, so behavior is identical to the pre-DB-config world.
- :func:`refresh_storage_config` reloads the snapshot from ``app_settings``
  and the secret key from ``app_setting_secrets`` (decrypted, read on a
  system-engine session of its own), and drops the cached boto3 client so it
  rebuilds with the new credentials. Called at startup and after every
  settings update.
- :func:`ensure_storage_config_fresh` re-loads if the snapshot is older than
  ``_TTL_SECONDS`` — bounds staleness across worker processes that didn't handle
  the update request themselves.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.encryption import SALT_S3_SECRET_KEY, decrypt_field
from app.core.messages import SettingsMessages

logger = logging.getLogger(__name__)

# How long a cached snapshot is trusted before a request-path access reloads it
# from the DB (covers multi-worker deploys; same-process updates refresh eagerly).
_TTL_SECONDS = 30.0

_resolved: ResolvedStorageConfig | None = None
_loaded_at: float = 0.0


@dataclass(frozen=True)
class ResolvedStorageConfig:
    """The effective storage config the backend factory builds from."""

    backend: str
    bucket: str | None
    region: str
    endpoint_url: str | None
    access_key_id: str | None
    secret_access_key: str | None  # decrypted plaintext (or None for ambient chain)
    use_path_style: bool
    local_fallback: bool


def _from_env() -> ResolvedStorageConfig:
    """Build the resolved config straight from env settings (the bootstrap /
    pre-DB-load fallback — preserves the original env-only behavior)."""
    return ResolvedStorageConfig(
        backend=(app_config.STORAGE_BACKEND or "local").lower(),
        bucket=app_config.S3_BUCKET,
        region=app_config.S3_REGION or "us-east-1",
        endpoint_url=app_config.S3_ENDPOINT_URL,
        access_key_id=app_config.S3_ACCESS_KEY_ID,
        secret_access_key=app_config.S3_SECRET_ACCESS_KEY,
        use_path_style=bool(app_config.S3_USE_PATH_STYLE),
        local_fallback=bool(app_config.S3_LOCAL_FALLBACK),
    )


def current_storage_config() -> ResolvedStorageConfig:
    """Return the cached resolved config, or the env fallback if not yet loaded."""
    if _resolved is not None:
        return _resolved
    return _from_env()


async def refresh_storage_config(session: AsyncSession) -> ResolvedStorageConfig:
    """Reload the snapshot from ``app_settings`` and reset the cached S3 client.

    ``session`` reads the settings row; the secret key is read on the system
    engine, whatever ``session`` is.
    """
    global _resolved, _loaded_at
    # Imported here (not at module top) to avoid an import cycle: app_settings ->
    # storage_config (in update_storage_settings) and back.
    from app.services import storage
    from app.services.platform.app_settings import get_app_settings

    row = await get_app_settings(session)
    secret = await resolve_saved_secret()
    _resolved = ResolvedStorageConfig(
        backend=(row.storage_backend or "local").lower(),
        bucket=row.s3_bucket,
        region=row.s3_region or "us-east-1",
        endpoint_url=row.s3_endpoint_url,
        access_key_id=row.s3_access_key_id,
        secret_access_key=secret,
        use_path_style=bool(row.s3_use_path_style),
        local_fallback=bool(row.s3_local_fallback),
    )
    _loaded_at = time.monotonic()
    # Force the boto3 client to rebuild with the new endpoint/region/credentials.
    storage.reset_s3_client()
    return _resolved


async def ensure_storage_config_fresh(session: AsyncSession) -> None:
    """Reload the snapshot if it has gone stale (or was never loaded)."""
    if _resolved is None or (time.monotonic() - _loaded_at) > _TTL_SECONDS:
        await refresh_storage_config(session)


async def resolve_saved_secret() -> str | None:
    """Decrypt the persisted S3 secret access key (or None if unset).

    Read on a system-engine session of its own: ``app_setting_secrets`` is
    granted to no request-path role.
    """
    from app.services.platform.app_settings import (
        load_app_setting_secrets,
    )

    row = await load_app_setting_secrets()
    if not row.s3_secret_access_key_encrypted:
        return None
    return decrypt_field(row.s3_secret_access_key_encrypted, SALT_S3_SECRET_KEY)


async def test_connection(cfg: ResolvedStorageConfig) -> tuple[bool, str]:
    """Validate that ``cfg`` can reach its bucket (``head_bucket``).

    Returns ``(ok, message)``; a failure's message is a message code, and its
    cause is logged. boto3 is synchronous, so the call runs in a worker thread.
    """
    if cfg.backend != "s3":
        return True, "Using local filesystem storage; no S3 connection to test."
    if not cfg.bucket:
        return False, SettingsMessages.STORAGE_BUCKET_REQUIRED

    import anyio

    from app.services import storage

    client = storage.build_s3_client(cfg)

    def _head() -> None:
        client.head_bucket(Bucket=cfg.bucket)

    try:
        await anyio.to_thread.run_sync(_head)
    except Exception as exc:  # report failure to the owner
        logger.warning("storage connection test failed: %s", exc)
        return False, SettingsMessages.STORAGE_CONNECTION_FAILED
    return True, "Connection successful."


def reset_for_tests() -> None:
    """Drop the cached snapshot so the next access reloads (test helper)."""
    global _resolved, _loaded_at
    _resolved = None
    _loaded_at = 0.0
