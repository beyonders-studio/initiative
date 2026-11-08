"""A deployment with a captcha configured, for a test about what it refuses."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

from app.services import captcha_config


@contextmanager
def captcha_switched_on() -> Generator[None, None, None]:
    """Resolve the captcha configuration as hCaptcha for the duration.

    The provider and its keys live on the settings row, behind a process-wide
    snapshot, so this patches the resolved answer rather than seeding the row
    and the cache.
    """
    configured = captcha_config.ResolvedCaptchaConfig(
        provider="hcaptcha", site_key="site", secret_key="secret"
    )
    with (
        patch.object(
            captcha_config,
            "ensure_captcha_config_fresh",
            AsyncMock(return_value=configured),
        ),
        patch.object(captcha_config, "current_captcha_config", return_value=configured),
    ):
        yield
