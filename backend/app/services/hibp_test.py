"""Unit tests for the HaveIBeenPwned k-anonymity client.

These tests stub the outbound HTTP call with ``httpx.MockTransport`` so
they don't touch the real HIBP API.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from app.services import hibp

#: The client itself, before the suite-wide stub replaces it.
_LOOKUP = hibp.is_password_breached


def _sha1(password: str) -> str:
    # ``usedforsecurity=False`` mirrors the production call in
    # ``hibp.is_password_breached`` — without it, this helper raises
    # ValueError on FIPS-enforcing OpenSSL builds before any test
    # body runs.
    return (
        hashlib.sha1(password.encode("utf-8"), usedforsecurity=False)
        .hexdigest()
        .upper()
    )


@pytest.fixture
def enable_hibp(monkeypatch):
    """Put the client back — the global conftest fixture stubs it so other
    tests don't make network calls. These tests exercise the client."""
    monkeypatch.setattr(hibp, "is_password_breached", _LOOKUP)


def _install_transport(monkeypatch, handler):
    """Patch ``httpx.AsyncClient`` to use a ``MockTransport`` so the
    real HIBP API is never contacted.

    The HIBP client constructs the AsyncClient inline; patching at the
    class level forwards our handler into that instance.
    """
    original_init = httpx.AsyncClient.__init__

    def init_with_transport(self, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init_with_transport)


class TestIsPasswordBreached:
    async def test_returns_false_for_empty_password(self, enable_hibp):
        assert await hibp.is_password_breached("") is False

    async def test_sends_k_anonymity_prefix(self, enable_hibp, monkeypatch):
        """The first 5 hex chars of the SHA-1 hash MUST be all that
        leaves the server."""
        password = "correct-horse-battery-staple"
        expected_prefix = _sha1(password)[:5]
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            # No match for the suffix → not breached.
            return httpx.Response(200, text="0000000000000000000000000000000000A:5\r\n")

        _install_transport(monkeypatch, handler)

        result = await hibp.is_password_breached(password)
        assert result is False
        assert str(captured["url"]).endswith(f"/range/{expected_prefix}")
        # No part of the full SHA-1 — only the 5-char prefix — must be
        # in the URL or headers.
        full_hash = _sha1(password)
        assert full_hash not in str(captured["url"])
        # Header presence: padding + UA.
        headers = captured["headers"]
        assert headers.get("add-padding") == "true"
        assert "initiative" in (headers.get("user-agent") or "").lower()

    async def test_returns_true_when_suffix_matches_with_positive_count(
        self, enable_hibp, monkeypatch
    ):
        password = "supersecretvalue"
        suffix = _sha1(password)[5:]

        def handler(request: httpx.Request) -> httpx.Response:
            body = f"{suffix}:42\r\n"
            return httpx.Response(200, text=body)

        _install_transport(monkeypatch, handler)
        assert await hibp.is_password_breached(password) is True

    async def test_returns_false_when_suffix_matches_with_zero_count(
        self, enable_hibp, monkeypatch
    ):
        """Padding rows are returned with count 0 to defeat traffic
        analysis. The client must skip them or every password would
        look breached."""
        password = "supersecretvalue"
        suffix = _sha1(password)[5:]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=f"{suffix}:0\r\n")

        _install_transport(monkeypatch, handler)
        assert await hibp.is_password_breached(password) is False

    async def test_returns_false_when_no_suffix_match(self, enable_hibp, monkeypatch):
        password = "supersecretvalue"

        def handler(request: httpx.Request) -> httpx.Response:
            # Plausible-looking but non-matching suffix.
            return httpx.Response(
                200,
                text="0000000000000000000000000000000000A:5\r\nFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFE:1\r\n",
            )

        _install_transport(monkeypatch, handler)
        assert await hibp.is_password_breached(password) is False

    async def test_fails_open_on_network_error(self, enable_hibp, monkeypatch):
        """A flaky HIBP outage must not block password changes — the
        length floor still applies as a hard gate."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unreachable")

        _install_transport(monkeypatch, handler)
        assert await hibp.is_password_breached("anything-long-enough") is False

    async def test_fails_open_on_http_error(self, enable_hibp, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="oops")

        _install_transport(monkeypatch, handler)
        assert await hibp.is_password_breached("anything-long-enough") is False
