"""Unit tests for the captcha verification helper.

Mocks the outbound httpx2 call so the suite doesn't hit the real
hCaptcha / Cloudflare / Google endpoints. The provider-specific
URL lookup and the fail-closed-on-network-error behaviour are the
load-bearing invariants.
"""

from __future__ import annotations

from typing import Self

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services import captcha as captcha_service
from app.services import captcha_config
from app.services.captcha_config import ResolvedCaptchaConfig


class _FakeResponse:
    """Minimal stand-in for ``httpx2.Response`` covering just the bits
    ``verify_or_raise`` touches."""

    def __init__(self, body: dict | None, *, raise_for_status: Exception | None = None):
        self._body = body
        self._raise = raise_for_status

    def raise_for_status(self) -> None:
        if self._raise is not None:
            raise self._raise

    def json(self) -> dict | None:
        return self._body


class _FakeAsyncClient:
    def __init__(
        self, *, response: _FakeResponse | None, raise_on_post: Exception | None = None
    ):
        self._response = response
        self._raise_on_post = raise_on_post
        self.last_url: str | None = None
        self.last_data: dict | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def post(self, url: str, data: dict) -> _FakeResponse:
        self.last_url = url
        self.last_data = data
        if self._raise_on_post is not None:
            raise self._raise_on_post
        assert self._response is not None
        return self._response


def _configure(
    monkeypatch,
    *,
    provider: str | None,
    secret: str | None = "s",
    site: str | None = "k",
):
    """Put the verifier in a given configuration, without a database.

    The configuration moved onto the settings row in 0368, so these tests set
    the RESOLVED value rather than the env vars that now only seed it. The env
    vars are patched to match anyway: they are what
    ``current_captcha_config`` falls back to, and leaving them disagreeing with
    the resolved config would make a failure here ambiguous about which one the
    code read.
    """
    cfg = ResolvedCaptchaConfig(provider=provider, site_key=site, secret_key=secret)
    monkeypatch.setattr(settings, "CAPTCHA_PROVIDER", provider)
    monkeypatch.setattr(settings, "CAPTCHA_SECRET_KEY", secret)
    monkeypatch.setattr(settings, "CAPTCHA_SITE_KEY", site)

    async def _resolved() -> ResolvedCaptchaConfig:
        return cfg

    # Patched rather than seeded through the cache so no test here opens a
    # database session: this file is unit-marked, and the resolver's own
    # behaviour is covered in captcha_config_test.py.
    monkeypatch.setattr(captcha_config, "ensure_captcha_config_fresh", _resolved)
    monkeypatch.setattr(captcha_config, "current_captcha_config", lambda: cfg)


async def test_no_op_when_provider_unset(monkeypatch):
    """Silent disable: missing CAPTCHA_PROVIDER must not raise even
    when the caller doesn't supply a token."""
    _configure(monkeypatch, provider=None)
    await captcha_service.verify_or_raise(None, remote_ip=None)
    await captcha_service.verify_or_raise("", remote_ip="1.2.3.4")


async def test_no_op_when_secret_missing(monkeypatch):
    """Half-configured (provider set, secret absent) is treated as
    disabled — same call shape as fully-disabled."""
    _configure(monkeypatch, provider="hcaptcha", secret=None)
    await captcha_service.verify_or_raise("ignored", remote_ip=None)


async def test_missing_token_when_configured(monkeypatch):
    """When configured, an empty / blank / missing token surfaces as
    400 CAPTCHA_REQUIRED so the SPA can replace the toast appropriately."""
    _configure(monkeypatch, provider="hcaptcha")
    for empty in (None, "", "   "):
        with pytest.raises(HTTPException) as exc:
            await captcha_service.verify_or_raise(empty, remote_ip=None)
        assert exc.value.status_code == 400
        assert exc.value.detail == "CAPTCHA_REQUIRED"


@pytest.mark.parametrize(
    "provider, expected_url",
    [
        ("hcaptcha", "https://hcaptcha.com/siteverify"),
        ("turnstile", "https://challenges.cloudflare.com/turnstile/v0/siteverify"),
        ("recaptcha", "https://www.google.com/recaptcha/api/siteverify"),
    ],
)
async def test_provider_routes_to_correct_url(
    monkeypatch, provider: str, expected_url: str
):
    """Each known provider hits its own siteverify endpoint and forwards
    secret / response / remoteip in the form-encoded body."""
    _configure(monkeypatch, provider=provider, secret="super-secret")

    fake_client = _FakeAsyncClient(response=_FakeResponse({"success": True}))

    def _factory(*_args, **_kwargs):
        return fake_client

    monkeypatch.setattr(captcha_service.httpx2, "AsyncClient", _factory)

    await captcha_service.verify_or_raise("token-value", remote_ip="9.9.9.9")
    assert fake_client.last_url == expected_url
    assert fake_client.last_data == {
        "secret": "super-secret",
        "response": "token-value",
        "remoteip": "9.9.9.9",
    }


async def test_omits_remote_ip_when_unknown(monkeypatch):
    """When the request has no client IP (test client, internal call),
    don't send the field — the providers treat it as optional."""
    _configure(monkeypatch, provider="hcaptcha")
    fake_client = _FakeAsyncClient(response=_FakeResponse({"success": True}))
    monkeypatch.setattr(
        captcha_service.httpx2, "AsyncClient", lambda *a, **k: fake_client
    )

    await captcha_service.verify_or_raise("tok", remote_ip=None)
    assert "remoteip" not in (fake_client.last_data or {})


async def test_provider_rejection_surfaces_as_400_invalid(monkeypatch):
    """``success: false`` from the provider → 400 CAPTCHA_INVALID."""
    _configure(monkeypatch, provider="turnstile")
    fake_client = _FakeAsyncClient(
        response=_FakeResponse(
            {"success": False, "error-codes": ["timeout-or-duplicate"]}
        )
    )
    monkeypatch.setattr(
        captcha_service.httpx2, "AsyncClient", lambda *a, **k: fake_client
    )

    from app.services.platform import security_signals

    security_signals.discard()
    with pytest.raises(HTTPException) as exc:
        await captcha_service.verify_or_raise("tok", remote_ip="192.0.2.44")
    assert exc.value.status_code == 400
    assert exc.value.detail == "CAPTCHA_INVALID"
    # Counted against the address, for the security rules.
    try:
        assert "captcha_burst" in security_signals._counts.rules
    finally:
        security_signals.discard()


async def test_network_error_fails_closed(monkeypatch):
    """If the verifier is unreachable we don't want to silently let a
    registration through — that would defeat the captcha. Surface as
    ``CAPTCHA_INVALID`` (the user can retry; ops gets a log line)."""
    import httpx2

    _configure(monkeypatch, provider="recaptcha")
    fake_client = _FakeAsyncClient(
        response=None, raise_on_post=httpx2.ConnectError("DNS failure")
    )
    monkeypatch.setattr(
        captcha_service.httpx2, "AsyncClient", lambda *a, **k: fake_client
    )

    with pytest.raises(HTTPException) as exc:
        await captcha_service.verify_or_raise("tok", remote_ip=None)
    assert exc.value.status_code == 400
    assert exc.value.detail == "CAPTCHA_INVALID"


async def test_unrecognised_provider_treated_as_disabled(monkeypatch):
    """A typo in CAPTCHA_PROVIDER shouldn't blow up registration —
    ``is_configured`` returns False so the verifier short-circuits."""
    _configure(monkeypatch, provider="not-a-real-provider")
    # Should not raise even though no token is supplied.
    await captcha_service.verify_or_raise(None, remote_ip=None)
