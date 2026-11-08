"""Integration tests for the runtime config endpoint.

The SPA fetches /api/v1/config at boot to learn deployment-specific
settings (e.g. the optional captcha or billing portal). The endpoint is
unauthenticated, so the relevant invariants are about *what* it returns
under each operator config, not about access control.
"""

from __future__ import annotations

import pytest
from httpx2 import AsyncClient

from app.core.config import CAPACITOR_NATIVE_ORIGINS, settings
from app.core.version import get_min_desktop_version, get_min_native_version
from app.services import captcha_config
from app.services.captcha_config import ResolvedCaptchaConfig
from app.services.tenant.attachments import MAX_FILE_SIZE


async def test_config_exposes_upload_cap(client: AsyncClient):
    """The SPA reads the server-enforced upload cap from config so the limit
    has a single source of truth (no mirrored frontend constant)."""
    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["max_upload_bytes"] == MAX_FILE_SIZE


async def test_config_exposes_native_version_floor(client: AsyncClient):
    """The landing page builds its Android and desktop download links from the
    releases those apps were last rebuilt for, the floors this server ships."""
    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["min_native_version"] == get_min_native_version()
    assert response.json()["min_desktop_version"] == get_min_desktop_version()


async def test_config_omits_billing_when_url_unset(client: AsyncClient, monkeypatch):
    """Self-host default: no BILLING_URL ⇒ ``billing: null`` so the SPA hides
    every tier/upgrade/manage surface (the usage panel still renders)."""
    monkeypatch.setattr(settings, "BILLING_URL", None)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["billing"] is None


@pytest.mark.parametrize(
    ("case", "provider", "secret"),
    [
        ("no provider", None, "secret-key"),
        # Provider and site key but no secret is half-configured: nothing could
        # validate the tokens the widget would produce.
        ("no secret", "hcaptcha", None),
        # A typo in the provider name must not render an unknown widget.
        ("unrecognised provider", "definitely-not-real", "secret-key"),
    ],
    ids=lambda v: v if isinstance(v, str) and " " in v else "",
)
async def test_config_reports_no_captcha_unless_it_is_fully_configured(
    client: AsyncClient, monkeypatch, case: str, provider, secret
):
    """The SPA gets ``captcha: null`` and skips the widget, matching the
    verifier's own silent-disable behaviour."""
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", provider)
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", "site-key")
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", secret)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["captcha"] is None


async def test_config_exposes_billing_url_when_set(client: AsyncClient, monkeypatch):
    """With a URL configured, the SPA gets the base URL to build its
    link-out buttons. The operator route reports itself unavailable until the
    handoff key is configured."""
    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example.com")
    monkeypatch.setattr(settings, "HANDOFF_SIGNING_PRIVATE_KEY_PEM", None)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["billing"] == {
        "url": "https://billing.example.com",
        "operator_handoff": False,
        "manages_plans": False,
        "insights": False,
        "contracts": False,
        "directory": False,
        "control": False,
    }


async def test_config_reports_operator_handoff_when_signing_configured(
    client: AsyncClient, monkeypatch, handoff_signing_key
):
    """A portal and the handoff key ⇒ the admin Guilds tab may render its
    control."""
    monkeypatch.setattr(settings, "BILLING_URL", "https://billing.example.com")

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["billing"]["operator_handoff"] is True


async def test_config_endpoint_is_unauthenticated(client: AsyncClient):
    """The SPA needs to read this before any user is logged in. No
    cookie, no Authorization header — must still return 200."""
    # No auth headers, no cookies
    response = await client.get("/api/v1/config")

    assert response.status_code == 200


# --- Captcha exposure -----------------------------------------------------


@pytest.mark.parametrize("provider", ["hcaptcha", "turnstile", "recaptcha"])
async def test_config_captcha_exposes_provider_and_site_key(
    client: AsyncClient, monkeypatch, provider: str
):
    """All three supported providers round-trip through the config
    endpoint with their public site key. The secret key never appears
    in the response."""
    # The captcha configuration moved onto the settings row in 0368, so the
    # endpoint resolves it rather than reading these env vars -- which are now
    # only the first-boot seed. Patched to match anyway, so a failure here
    # cannot be ambiguous about which source the endpoint read.
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", provider)
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", "public-site-key")
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", "very-private-secret")

    async def _resolved() -> ResolvedCaptchaConfig:
        return ResolvedCaptchaConfig(
            provider=provider,
            site_key="public-site-key",
            secret_key="very-private-secret",
        )

    monkeypatch.setattr(captcha_config, "ensure_captcha_config_fresh", _resolved)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    body = response.json()
    assert body["captcha"] == {"provider": provider, "site_key": "public-site-key"}
    # Belt-and-braces: the secret must never appear in the public payload.
    assert "very-private-secret" not in response.text


async def test_captcha_frame_draws_the_widget_for_the_apps(
    client: AsyncClient, monkeypatch
):
    """The apps frame this page, so it carries the site key and the provider's
    script, may be framed by the apps alone, and never names the secret."""

    async def _resolved() -> ResolvedCaptchaConfig:
        return ResolvedCaptchaConfig(
            provider="turnstile",
            site_key="public-site-key",
            secret_key="very-private-secret",
        )

    monkeypatch.setattr(captcha_config, "ensure_captcha_config_fresh", _resolved)

    response = await client.get("/api/v1/config/captcha")

    assert response.status_code == 200
    assert "public-site-key" in response.text
    assert "https://challenges.cloudflare.com/turnstile/v0/api.js" in response.text
    assert "very-private-secret" not in response.text
    policy = response.headers["content-security-policy"]
    assert "frame-ancestors " + " ".join(CAPACITOR_NATIVE_ORIGINS) in policy
    assert "x-frame-options" not in response.headers


async def test_captcha_frame_is_absent_without_a_captcha(client: AsyncClient):
    response = await client.get("/api/v1/config/captcha")

    assert response.status_code == 404


async def test_config_says_cookie_consent_and_guests_are_off_by_default(
    client: AsyncClient,
):
    """The SPA reads the switches here: the cookie notice is for somebody who
    has not signed in, and a deployment without guests shows nothing about
    them. Off unless an owner turned them on."""
    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["cookie_consent_enabled"] is False
    assert response.json()["guests_enabled"] is False


async def test_config_asks_about_nothing_a_deployment_does_not_do(
    client: AsyncClient, monkeypatch
):
    """The chooser offers a switch per category here. Self-host default:
    nothing optional is configured, so there is nothing to offer."""
    monkeypatch.setattr(settings, "FARO_COLLECTOR_URL", None)

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["cookie_categories"] == []
    assert response.json()["faro_collector_url"] is None


async def test_config_names_the_collector_and_asks_about_analytics(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "FARO_COLLECTOR_URL", "/collect")

    response = await client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json()["faro_collector_url"] == "/collect"
    assert response.json()["cookie_categories"] == ["analytics"]


async def test_config_asks_for_page_views_only_where_metrics_are_read(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)
    assert (await client.get("/api/v1/config")).json()["count_page_views"] is False

    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret-token")
    assert (await client.get("/api/v1/config")).json()["count_page_views"] is True
