"""Server-side verification for the registration captcha.

Three providers are supported, selected via the ``CAPTCHA_PROVIDER``
env var:

  - ``"hcaptcha"``    → https://hcaptcha.com/
  - ``"turnstile"``   → Cloudflare Turnstile
  - ``"recaptcha"``   → Google reCAPTCHA v2/v3 (verify endpoint is
                        the same for both versions; v3 score is not
                        gated here — set a low threshold via the
                        provider's own console if you need one).

All three accept the same form-encoded POST shape (``secret``,
``response``, optional ``remoteip``) and return JSON with
``success: bool``. The helper is provider-agnostic above that.

Silent disable: with no provider or no secret configured,
``verify_or_raise`` is a no-op so registration works exactly as
before. The register endpoint also short-circuits on the
bootstrap-first-user path so a fresh deployment isn't blocked by a
captcha it hasn't been told to require.

Where the configuration comes from: ``app.services.captcha_config``,
which resolves the settings row and the stored secret and falls back
to the ``CAPTCHA_*`` env values before the first database load. The
env vars are a first-boot seed now, not the configuration itself --
an owner changes any of this in Settings without a redeploy.
"""

from __future__ import annotations

import logging

import httpx2
from fastapi import HTTPException, status

from app.core.config import CaptchaProvider
from app.core.messages import AuthMessages
from app.services import captcha_config
from app.services.captcha_config import ResolvedCaptchaConfig

logger = logging.getLogger(__name__)


# Provider → siteverify URL. Names match the public ``CAPTCHA_PROVIDER``
# env value so operators can read the var and immediately know what's
# being called.
_VERIFY_URLS: dict[str, str] = {
    CaptchaProvider.hcaptcha: "https://hcaptcha.com/siteverify",
    CaptchaProvider.turnstile: "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    CaptchaProvider.recaptcha: "https://www.google.com/recaptcha/api/siteverify",
}

#: Provider → the script that draws its widget, as the web app loads it
#: (``frontend/src/lib/captchaProviders.ts``).
SCRIPT_URLS: dict[str, str] = {
    CaptchaProvider.hcaptcha: "https://js.hcaptcha.com/1/api.js?render=explicit",
    CaptchaProvider.turnstile: "https://challenges.cloudflare.com/turnstile/v0/api.js",
    CaptchaProvider.recaptcha: "https://www.google.com/recaptcha/api.js?render=explicit",
}


def is_configured(cfg: ResolvedCaptchaConfig | None = None) -> bool:
    """Captcha enforcement is on iff a known provider AND a secret are
    set. Site key is also required for the SPA to render a widget, but
    the server can verify without it — we still gate on it so the
    config-endpoint half can't drift from the verifier half.

    ``cfg`` defaults to the cached snapshot, for a synchronous caller.
    An async one passes the freshly resolved config it already holds."""
    resolved = cfg or captcha_config.current_captcha_config()
    return bool(
        resolved.provider
        and resolved.provider in _VERIFY_URLS
        and resolved.secret_key
        and resolved.site_key
    )


async def public_config() -> tuple[str, str] | None:
    """``(provider, site_key)`` for the SPA, or None when captcha is off.

    The one place the "is this deployment running a captcha" question is
    answered for a client. It used to be answered twice — here and inline
    in the config endpoint — which is the drift :func:`is_configured`
    warns about, written into the code.
    """
    cfg = await captcha_config.ensure_captcha_config_fresh()
    if not is_configured(cfg) or not cfg.provider or not cfg.site_key:
        return None
    return cfg.provider, cfg.site_key


def _count_refusal(remote_ip: str | None) -> None:
    """A refused captcha is counted by the security rules, never written down
    one by one. A provider we couldn't reach is our trouble, not theirs, and
    is not counted."""
    from app.core.security_rules import Signal
    from app.services.platform import security_signals

    security_signals.signal(Signal.captcha_rejected, source_ip=remote_ip)


async def verify_or_raise(token: str | None, *, remote_ip: str | None) -> None:
    """Verify a captcha ``token`` against the configured provider.

    No-op when captcha isn't configured. Raises ``400 CAPTCHA_REQUIRED``
    when configured but the token is missing/blank, and
    ``400 CAPTCHA_INVALID`` when the provider rejects the token (or a
    network error prevents verification — fail-closed, since silently
    accepting on outbound provider failure would defeat the point).
    """
    cfg = await captcha_config.ensure_captcha_config_fresh()
    if not is_configured(cfg):
        return

    cleaned = (token or "").strip()
    if not cleaned:
        _count_refusal(remote_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CAPTCHA_REQUIRED,
        )

    provider = cfg.provider
    # ``is_configured`` already checked this, but ``assert`` would be
    # stripped under ``python -O`` (some production images run that
    # way). Re-check explicitly so a config that drifts between the
    # two reads doesn't surface as a 500 from a ``KeyError`` lookup.
    if provider is None or provider not in _VERIFY_URLS:
        return
    verify_url = _VERIFY_URLS[provider]

    payload: dict[str, str] = {
        "secret": cfg.secret_key or "",
        "response": cleaned,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        async with httpx2.AsyncClient(timeout=10) as client:
            resp = await client.post(verify_url, data=payload)
            resp.raise_for_status()
            body = resp.json()
    except (httpx2.HTTPError, ValueError) as exc:
        # Fail-closed — if we can't reach the provider, treat as
        # invalid rather than letting a registration through unchecked.
        logger.warning("Captcha verification request to %s failed: %s", provider, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CAPTCHA_INVALID,
        ) from exc

    if not isinstance(body, dict) or not body.get("success"):
        # Provider error codes (if present) are intentionally not
        # forwarded to the client — they're vendor-specific and not
        # actionable for the end user. Log them for ops debugging.
        if isinstance(body, dict):
            logger.info(
                "Captcha rejected by %s: error_codes=%s",
                provider,
                body.get("error-codes") or body.get("errorCodes"),
            )
        _count_refusal(remote_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.CAPTCHA_INVALID,
        )
