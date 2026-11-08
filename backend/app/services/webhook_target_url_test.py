"""Unit tests for outbound target-URL validation.

These assert the target policy: only https, only public unicast
addresses. A regression that lets any of these pass would allow an
outbound request to a non-public destination.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
    assert_target_url_is_public_async,
    resolve_validated_target,
)


def test_accepts_public_https_literal():
    """An IPv4 literal in public unicast space is fine."""
    resolve_validated_target("https://93.184.216.34/hook")


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hook",
        "https://127.255.255.254/hook",
        "https://[::1]/hook",
    ],
)
def test_rejects_loopback(url: str):
    with pytest.raises(WebhookTargetUrlPrivateError):
        resolve_validated_target(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://10.0.0.1/hook",
        "https://172.16.0.1/hook",
        "https://192.168.1.1/hook",
        "https://[fc00::1]/hook",
        "https://100.64.0.1/hook",
        "https://100.100.100.200/hook",
    ],
)
def test_rejects_rfc1918_ula_and_shared(url: str):
    with pytest.raises(WebhookTargetUrlPrivateError):
        resolve_validated_target(url)


def test_rejects_link_local():
    with pytest.raises(WebhookTargetUrlPrivateError):
        resolve_validated_target("https://169.254.169.254/latest/meta-data/")


@pytest.mark.parametrize(
    "url",
    [
        "https://[::ffff:127.0.0.1]/hook",
        "https://[::ffff:10.0.0.1]/hook",
    ],
)
def test_rejects_ipv4_mapped_ipv6(url: str):
    """An IPv4-mapped IPv6 literal is classified by its embedded IPv4."""
    with pytest.raises(WebhookTargetUrlPrivateError):
        resolve_validated_target(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/in",
        "ftp://example.com/hook",
        "file:///etc/passwd",
        "gopher://example.com/_GET",
        "javascript:alert(1)",
    ],
)
def test_rejects_non_https_schemes(url: str):
    """Only https is accepted."""
    with pytest.raises(WebhookTargetUrlError):
        resolve_validated_target(url)


def test_rejects_missing_hostname():
    with pytest.raises(WebhookTargetUrlError):
        resolve_validated_target("https:///hook")


def test_rejects_when_hostname_resolves_to_private():
    """A public-looking hostname that resolves to a private address is
    rejected."""
    fake_infos = [(2, 0, 0, "", ("10.0.0.5", 0))]  # AF_INET, RFC1918
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=fake_infos
    ):
        with pytest.raises(WebhookTargetUrlPrivateError):
            resolve_validated_target("https://internal.example.com/hook")


def test_rejects_when_any_resolved_address_is_private():
    """If any resolved address is non-public, the whole host is rejected."""
    fake_infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),  # public
        (2, 0, 0, "", ("10.0.0.5", 0)),  # private
    ]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=fake_infos
    ):
        with pytest.raises(WebhookTargetUrlPrivateError):
            resolve_validated_target("https://mixed.example.com/hook")


def test_resolve_returns_validated_addresses():
    """The resolver returns the approved addresses so a caller can connect
    to the exact address that was checked."""
    fake_infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),
        (2, 0, 0, "", ("93.184.216.35", 0)),
    ]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=fake_infos
    ):
        target = resolve_validated_target("https://cdn.example.com/hook")
    assert target.hostname == "cdn.example.com"
    assert [str(a) for a in target.addresses] == ["93.184.216.34", "93.184.216.35"]
    assert target.pinned_ip == "93.184.216.34"


def test_literal_public_is_its_own_validated_address():
    target = resolve_validated_target("https://93.184.216.34/hook")
    assert target.pinned_ip == "93.184.216.34"
    assert target.hostname == "93.184.216.34"


async def test_async_variant_accepts_public_literal():
    await assert_target_url_is_public_async("https://93.184.216.34/hook")


async def test_async_variant_rejects_private_literal():
    with pytest.raises(WebhookTargetUrlPrivateError):
        await assert_target_url_is_public_async("https://10.0.0.1/hook")


async def test_async_variant_resolves_off_the_event_loop():
    """The async variant hands DNS resolution to a thread."""
    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo",
        return_value=fake_infos,
    ) as mock:
        await assert_target_url_is_public_async("https://hooks.example.com/in")
    assert mock.called


# ── Local-dev escape hatch ────────────────────────────────────────────


def _enable_dev_flag(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "WEBHOOK_ALLOW_PRIVATE_TARGETS", True)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8201/api/v1/webhooks/initiative",
        "http://127.0.0.1:8201/hook",
        "http://10.0.0.5/hook",
        "https://127.0.0.1/hook",
    ],
)
def test_dev_flag_allows_local_targets(monkeypatch, url: str):
    """With the flag on, http and private/loopback targets are accepted
    for local round-trips."""
    _enable_dev_flag(monkeypatch)
    resolve_validated_target(url)


def test_http_to_private_flag_off_is_invalid_scheme():
    """Flag off: http is rejected on the scheme (invalid) before the
    address is considered. The endpoint maps this to a different error
    code than a private https target, so pin the exact type."""
    with pytest.raises(WebhookTargetUrlError) as exc_info:
        resolve_validated_target("http://10.0.0.1/hook")
    assert type(exc_info.value) is WebhookTargetUrlError


def test_https_to_private_flag_off_is_private():
    """Flag off: https to a private address is rejected as private (the
    scheme is fine, the address is not)."""
    with pytest.raises(WebhookTargetUrlPrivateError):
        resolve_validated_target("https://10.0.0.1/hook")


def test_dev_flag_still_rejects_http_to_public(monkeypatch):
    """The dev flag's scope is local/private targets; plain http to a
    public host stays rejected even with it on."""
    _enable_dev_flag(monkeypatch)
    fake_infos = [(2, 0, 0, "", ("93.184.216.34", 0))]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=fake_infos
    ):
        with pytest.raises(WebhookTargetUrlError):
            resolve_validated_target("http://hooks.example.com/in")


def test_dev_flag_rejects_http_to_mixed_public_private(monkeypatch):
    """Dev flag on: a host resolving to both public and private addresses
    over http is rejected — http is only allowed when no resolved address
    is public (any address in the set may be connected to)."""
    _enable_dev_flag(monkeypatch)
    fake_infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),  # public
        (2, 0, 0, "", ("10.0.0.5", 0)),  # private
    ]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=fake_infos
    ):
        with pytest.raises(WebhookTargetUrlError):
            resolve_validated_target("http://mixed.example.com/hook")


def test_dev_flag_allows_https_to_mixed(monkeypatch):
    """Dev flag on: https to a mixed public/private set is fine — the
    scheme guarantees encryption regardless of which address is used."""
    _enable_dev_flag(monkeypatch)
    fake_infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),
        (2, 0, 0, "", ("10.0.0.5", 0)),
    ]
    with patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=fake_infos
    ):
        resolve_validated_target("https://mixed.example.com/hook")
