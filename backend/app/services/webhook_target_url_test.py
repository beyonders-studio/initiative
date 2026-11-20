"""Outbound target-URL validation: only https, only public unicast addresses,
unless the local-dev flag opens private targets."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
    assert_target_url_is_public_async,
    resolve_validated_target,
)

PUBLIC = (2, 0, 0, "", ("93.184.216.34", 0))
PRIVATE = (2, 0, 0, "", ("10.0.0.5", 0))


def _resolving_to(*infos):
    return patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=list(infos)
    )


@pytest.fixture
def dev_flag(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "WEBHOOK_ALLOW_PRIVATE_TARGETS", True)


def test_a_public_literal_is_its_own_validated_address():
    target = resolve_validated_target("https://93.184.216.34/hook")
    assert target.pinned_ip == "93.184.216.34"
    assert target.hostname == "93.184.216.34"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hook",
        "https://127.255.255.254/hook",
        "https://[::1]/hook",
        "https://10.0.0.1/hook",
        "https://172.16.0.1/hook",
        "https://192.168.1.1/hook",
        "https://[fc00::1]/hook",
        "https://100.64.0.1/hook",
        "https://100.100.100.200/hook",
        "https://169.254.169.254/latest/meta-data/",
        # An IPv4-mapped IPv6 literal is classified by its embedded IPv4.
        "https://[::ffff:127.0.0.1]/hook",
        "https://[::ffff:10.0.0.1]/hook",
    ],
)
def test_a_non_public_address_is_private(url: str):
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
        "https:///hook",
    ],
)
def test_a_non_https_or_hostless_url_is_invalid(url: str):
    with pytest.raises(WebhookTargetUrlError):
        resolve_validated_target(url)


def test_http_to_a_private_address_is_invalid_rather_than_private():
    """The scheme is judged before the address; the endpoint maps the two to
    different error codes, so the exact type is pinned."""
    with pytest.raises(WebhookTargetUrlError) as exc_info:
        resolve_validated_target("http://10.0.0.1/hook")
    assert type(exc_info.value) is WebhookTargetUrlError


@pytest.mark.parametrize("infos", [[PRIVATE], [PUBLIC, PRIVATE]])
def test_a_hostname_resolving_to_any_private_address_is_private(infos):
    with _resolving_to(*infos), pytest.raises(WebhookTargetUrlPrivateError):
        resolve_validated_target("https://internal.example.com/hook")


def test_resolve_returns_validated_addresses():
    """The resolver returns the approved addresses so a caller can connect
    to the exact address that was checked."""
    with _resolving_to(PUBLIC, (2, 0, 0, "", ("93.184.216.35", 0))):
        target = resolve_validated_target("https://cdn.example.com/hook")
    assert target.hostname == "cdn.example.com"
    assert [str(a) for a in target.addresses] == ["93.184.216.34", "93.184.216.35"]
    assert target.pinned_ip == "93.184.216.34"


async def test_the_async_variant_resolves_off_the_event_loop():
    await assert_target_url_is_public_async("https://93.184.216.34/hook")
    with pytest.raises(WebhookTargetUrlPrivateError):
        await assert_target_url_is_public_async("https://10.0.0.1/hook")
    with _resolving_to(PUBLIC) as mock:
        await assert_target_url_is_public_async("https://hooks.example.com/in")
    assert mock.called


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8201/api/v1/webhooks/initiative",
        "http://127.0.0.1:8201/hook",
        "http://10.0.0.5/hook",
        "https://127.0.0.1/hook",
    ],
)
def test_dev_flag_allows_local_targets(dev_flag, url: str):
    resolve_validated_target(url)


def test_dev_flag_allows_https_to_mixed(dev_flag):
    """https to a mixed public/private set is fine: the scheme guarantees
    encryption regardless of which address is used."""
    with _resolving_to(PUBLIC, PRIVATE):
        resolve_validated_target("https://mixed.example.com/hook")


@pytest.mark.parametrize("infos", [[PUBLIC], [PUBLIC, PRIVATE]])
def test_dev_flag_still_refuses_http_reaching_a_public_address(dev_flag, infos):
    """http is allowed only when no resolved address is public, since any
    address in the set may be connected to."""
    with _resolving_to(*infos), pytest.raises(WebhookTargetUrlError):
        resolve_validated_target("http://mixed.example.com/hook")
