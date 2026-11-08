"""Resolved captcha configuration with a process-wide cache.

``app.services.captcha`` verifies a token from two places that hold no database
session: ``is_configured`` is synchronous, and ``verify_or_raise`` is called
from the register endpoint with the caller's own session, which is the wrong one
to read ``app_setting_secrets`` on (no request-path role is granted it). So the
resolved configuration is kept as a process-level snapshot here, exactly as
``app.services.storage_config`` does for the storage backend, and for the same
reason.

- :func:`current_captcha_config` is the synchronous accessor. Before the first
  database load — and in CLI scripts and tests — it falls back to the env
  ``settings``, so behaviour matches the pre-database world.
- :func:`refresh_captcha_config` reloads it from ``app_settings`` and the secret
  from ``app_setting_secrets``. Called at startup and after every settings
  update.
- :func:`ensure_captcha_config_fresh` reloads once the snapshot is older than
  :data:`_TTL_SECONDS`, on a system-engine session of its own so a caller with
  no session can still get a current answer. That bounds how long a worker
  process that did not handle the update keeps enforcing the old secret.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.encryption import SALT_CAPTCHA_SECRET_KEY, decrypt_field

#: How long a snapshot is trusted before a request-path access reloads it.
#: The same 30 seconds storage_config uses — a captcha secret that has just
#: been rotated should start being used about as promptly as a new S3 key.
_TTL_SECONDS = 30.0

_resolved: ResolvedCaptchaConfig | None = None
_loaded_at: float = 0.0


@dataclass(frozen=True)
class ResolvedCaptchaConfig:
    """The effective captcha configuration."""

    provider: str | None
    site_key: str | None
    secret_key: str | None  # decrypted plaintext, or None when unset


def _from_env() -> ResolvedCaptchaConfig:
    """Straight from env settings — the bootstrap / pre-database fallback."""
    return ResolvedCaptchaConfig(
        provider=app_config.CAPTCHA_PROVIDER,
        site_key=app_config.CAPTCHA_SITE_KEY,
        secret_key=app_config.CAPTCHA_SECRET_KEY,
    )


def current_captcha_config() -> ResolvedCaptchaConfig:
    """The cached configuration, or the env fallback if not yet loaded."""
    if _resolved is not None:
        return _resolved
    return _from_env()


async def resolve_saved_secret() -> str | None:
    """Decrypt the stored verification secret, or None when unset.

    On a system-engine session of its own: ``app_setting_secrets`` is granted to
    no request-path role.
    """
    from app.services.platform.app_settings import (
        load_app_setting_secrets,
    )

    row = await load_app_setting_secrets()
    if not row.captcha_secret_key_encrypted:
        return None
    return decrypt_field(row.captcha_secret_key_encrypted, SALT_CAPTCHA_SECRET_KEY)


async def refresh_captcha_config(session: AsyncSession) -> ResolvedCaptchaConfig:
    """Reload the snapshot from ``app_settings`` and the stored secret.

    ``session`` reads the settings row; the secret is read on the system engine
    whatever ``session`` is.
    """
    global _resolved, _loaded_at
    from app.services.platform.app_settings import get_app_settings

    row = await get_app_settings(session)
    _resolved = ResolvedCaptchaConfig(
        provider=row.captcha_provider,
        site_key=row.captcha_site_key,
        secret_key=await resolve_saved_secret(),
    )
    _loaded_at = time.monotonic()
    return _resolved


async def ensure_captcha_config_fresh() -> ResolvedCaptchaConfig:
    """Reload if stale or never loaded, on a session of its own.

    Session-less by design: the verifier is reached from paths that hold either
    no session or a guild-routed one, and neither can read the credential.
    """
    if _resolved is not None and (time.monotonic() - _loaded_at) <= _TTL_SECONDS:
        return _resolved
    from app.db import session as db_session

    async with db_session.SystemSessionLocal() as system_session:
        return await refresh_captcha_config(system_session)


def reset_for_tests() -> None:
    """Drop the snapshot so the next read resolves again."""
    global _resolved, _loaded_at
    _resolved = None
    _loaded_at = 0.0
