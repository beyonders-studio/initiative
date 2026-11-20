"""Tests for the resolved captcha-config cache.

The precedence that makes the captcha settings page safe, and the one that makes
it safe to *move* the captcha off environment variables: env before the database
is loaded, the stored row afterwards.
"""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.services import captcha as captcha_service
from app.services import captcha_config
from app.services.platform import app_settings as app_settings_service


@pytest.fixture(autouse=True)
def _reset_cache():
    captcha_config.reset_for_tests()
    yield
    captcha_config.reset_for_tests()


def test_current_config_falls_back_to_env_before_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no snapshot loaded the resolver reads env — so a CLI script, a test,
    and the window before boot's refresh all behave as they did when the env vars
    WERE the configuration."""
    monkeypatch.setattr(app_config, "CAPTCHA_PROVIDER", "turnstile", raising=False)
    monkeypatch.setattr(app_config, "CAPTCHA_SITE_KEY", "env-site", raising=False)
    monkeypatch.setattr(app_config, "CAPTCHA_SECRET_KEY", "env-secret", raising=False)

    cfg = captcha_config.current_captcha_config()
    assert cfg.provider == "turnstile"
    assert cfg.site_key == "env-site"
    assert cfg.secret_key == "env-secret"
    assert captcha_service.is_configured(cfg) is True


async def test_refresh_loads_db_over_env(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a save, the snapshot is the stored row and the env is ignored.

    This is the whole contract of the move: an owner changes the captcha in
    Settings and the next registration verifies against the new secret, with no
    redeploy and without the env value coming back.
    """
    monkeypatch.setattr(app_config, "CAPTCHA_PROVIDER", "recaptcha", raising=False)
    monkeypatch.setattr(app_config, "CAPTCHA_SITE_KEY", "env-site", raising=False)
    monkeypatch.setattr(app_config, "CAPTCHA_SECRET_KEY", "env-secret", raising=False)

    await app_settings_service.update_captcha_settings(
        session,
        system_session=session,
        provider="turnstile",
        site_key="db-site",
        secret_key="db-secret",
        secret_provided=True,
    )

    cfg = captcha_config.current_captcha_config()
    assert cfg.provider == "turnstile"
    assert cfg.site_key == "db-site"
    assert cfg.secret_key == "db-secret"  # decrypted
    assert captcha_service.is_configured(cfg) is True


async def test_secret_is_kept_when_not_sent(session: AsyncSession) -> None:
    """Editing the site key without re-typing the secret keeps the secret.

    An owner cannot read the stored secret back, so a save that omitted it and
    cleared it would be a trap: enforcement would silently stop.
    """
    await app_settings_service.update_captcha_settings(
        session,
        system_session=session,
        provider="hcaptcha",
        site_key="first",
        secret_key="keep-me",
        secret_provided=True,
    )
    await app_settings_service.update_captcha_settings(
        session,
        system_session=session,
        provider="hcaptcha",
        site_key="second",
        secret_key=None,
        secret_provided=False,
    )

    cfg = captcha_config.current_captcha_config()
    assert cfg.site_key == "second"
    assert cfg.secret_key == "keep-me"


async def test_secret_is_cleared_when_sent_empty(session: AsyncSession) -> None:
    """An explicit empty secret clears it, and enforcement stops with it."""
    await app_settings_service.update_captcha_settings(
        session,
        system_session=session,
        provider="hcaptcha",
        site_key="site",
        secret_key="to-clear",
        secret_provided=True,
    )
    await app_settings_service.update_captcha_settings(
        session,
        system_session=session,
        provider="hcaptcha",
        site_key="site",
        secret_key="",
        secret_provided=True,
    )

    cfg = captcha_config.current_captcha_config()
    assert cfg.secret_key is None
    assert captcha_service.is_configured(cfg) is False
