"""Unit tests for guarded outbound egress.

The key property: a request is aimed at the address that was validated,
not the hostname — so the resolution used to check the target and the
resolution used to connect cannot differ.
"""

from __future__ import annotations

import gzip
import logging
from unittest.mock import patch

import httpx2
import pytest

from app.services.safe_http import (
    PinnedTransport,
    ResponseTooLargeError,
    build_validated_request,
    request_public_target,
)
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)


def _resolves_to(ip: str):
    """Patch DNS so any hostname resolves to a single ``ip``."""
    infos = [(2, 0, 0, "", (ip, 0))]  # AF_INET
    return patch(
        "app.services.webhook_target_url.socket.getaddrinfo", return_value=infos
    )


async def test_request_targets_validated_ip_and_keeps_hostname():
    with _resolves_to("93.184.216.34"):
        request = await build_validated_request(
            "POST",
            "https://hooks.example.com/deliver?x=1",
            headers={"Content-Type": "application/json"},
            content=b"{}",
        )
    # Connection target is the resolved address, not the hostname.
    assert request.url.host == "93.184.216.34"
    # Path and query are preserved.
    assert request.url.raw_path == b"/deliver?x=1"
    # Hostname is preserved for the Host header and TLS.
    assert request.headers["host"] == "hooks.example.com"
    assert request.extensions["sni_hostname"] == "hooks.example.com"


async def test_host_header_includes_explicit_port():
    with _resolves_to("93.184.216.34"):
        request = await build_validated_request(
            "POST", "https://hooks.example.com:8443/x", content=b""
        )
    assert request.url.host == "93.184.216.34"
    assert request.url.port == 8443
    assert request.headers["host"] == "hooks.example.com:8443"


async def test_private_resolution_is_refused():
    with _resolves_to("10.0.0.5"), pytest.raises(WebhookTargetUrlPrivateError):
        await build_validated_request(
            "POST", "https://internal.example.com/x", content=b""
        )


async def test_send_connects_to_pinned_ip():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["host"] = request.url.host
        seen["host_header"] = request.headers.get("host")
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx2.Response(200, json={"ok": True})

    with _resolves_to("93.184.216.34"):
        response = await request_public_target(
            "POST",
            "https://hooks.example.com/deliver",
            headers={"Content-Type": "application/json"},
            content=b"{}",
            timeout=5.0,
            transport=httpx2.MockTransport(handler),
        )

    assert response.status_code == 200
    assert seen == {
        "host": "93.184.216.34",
        "host_header": "hooks.example.com",
        "sni": "hooks.example.com",
    }


async def test_redirects_are_not_followed():
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request.url.host)
        return httpx2.Response(
            302, headers={"Location": "https://elsewhere.example.com/"}
        )

    with _resolves_to("93.184.216.34"):
        response = await request_public_target(
            "GET",
            "https://hooks.example.com/deliver",
            timeout=5.0,
            transport=httpx2.MockTransport(handler),
        )

    assert response.status_code == 302
    assert calls == ["93.184.216.34"]  # only the pinned host was contacted


async def test_dev_flag_pins_private_local_target(monkeypatch):
    """With the dev flag on, a local target is allowed *and* still pinned
    to the resolved address — the round-trip works and pinning holds."""
    from app.core import config as config_module

    monkeypatch.setattr(config_module.settings, "WEBHOOK_ALLOW_PRIVATE_TARGETS", True)

    with _resolves_to("127.0.0.1"):
        request = await build_validated_request(
            "POST", "http://localhost:8201/api/v1/webhooks/initiative", content=b"{}"
        )
    assert request.url.host == "127.0.0.1"
    assert request.url.scheme == "http"
    assert request.headers["host"] == "localhost:8201"


async def test_falls_back_to_next_validated_address(caplog):
    """If the first validated address is unreachable, the request retries
    the other validated addresses instead of failing outright. Each attempt
    writes one line naming the target's origin, a failure at ``INFO``."""
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.host)
        if request.url.host == "93.184.216.34":
            raise httpx2.ConnectError("refused", request=request)
        return httpx2.Response(200, json={"ok": True})

    infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),
        (2, 0, 0, "", ("93.184.216.35", 0)),
    ]
    with (
        patch("app.services.webhook_target_url.socket.getaddrinfo", return_value=infos),
        caplog.at_level(logging.DEBUG, logger="app.services.safe_http"),
    ):
        response = await request_public_target(
            "POST",
            "https://cdn.example.com/deliver?key=abc",
            content=b"{}",
            timeout=5.0,
            transport=httpx2.MockTransport(handler),
        )

    assert response.status_code == 200
    assert seen == ["93.184.216.34", "93.184.216.35"]
    lines = [
        (r.levelno, r.getMessage().rsplit(" ", 2)[0])
        for r in caplog.records
        if r.name == "app.services.safe_http"
    ]
    assert lines == [
        (logging.INFO, "POST https://cdn.example.com ConnectError"),
        (logging.DEBUG, "POST https://cdn.example.com 200"),
    ]


async def test_connect_timeout_does_not_fall_back():
    """A connect timeout is not retried across addresses — it has already
    consumed the caller's budget — so the request fails without multiplying
    the timeout over every validated address."""
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.host)
        raise httpx2.ConnectTimeout("timed out", request=request)

    infos = [
        (2, 0, 0, "", ("93.184.216.34", 0)),
        (2, 0, 0, "", ("93.184.216.35", 0)),
    ]
    with (
        patch("app.services.webhook_target_url.socket.getaddrinfo", return_value=infos),
        pytest.raises(httpx2.ConnectTimeout),
    ):
        await request_public_target(
            "POST",
            "https://cdn.example.com/deliver",
            content=b"{}",
            timeout=5.0,
            transport=httpx2.MockTransport(handler),
        )

    assert seen == ["93.184.216.34"]  # stopped after the timeout; no fallback


async def test_allow_private_permits_and_pins_private_target():
    """allow_private lets an operator-configured internal target through,
    still pinned to the resolved address with the hostname preserved."""
    with _resolves_to("10.0.0.5"):
        request = await build_validated_request(
            "POST",
            "https://ollama.internal/api/chat",
            content=b"{}",
            allow_private=True,
        )
    assert request.url.host == "10.0.0.5"
    assert request.headers["host"] == "ollama.internal"


async def test_allow_private_permits_http_to_private():
    """With allow_private an operator ``http://internal`` target is accepted
    and pinned (Ollama on a private host with no TLS)."""
    with _resolves_to("10.0.0.5"):
        request = await build_validated_request(
            "POST",
            "http://ollama.internal:11434/api/chat",
            content=b"{}",
            allow_private=True,
        )
    assert request.url.host == "10.0.0.5"
    assert request.url.scheme == "http"


async def test_allow_private_still_rejects_http_to_public():
    """allow_private does not relax the http-to-public prohibition."""
    with _resolves_to("93.184.216.34"), pytest.raises(WebhookTargetUrlError):
        await build_validated_request(
            "POST", "http://hooks.example.com/in", content=b"", allow_private=True
        )


async def test_private_target_still_refused_without_allow_private():
    """Default (allow_private=False) still refuses a private target."""
    with _resolves_to("10.0.0.5"), pytest.raises(WebhookTargetUrlPrivateError):
        await build_validated_request(
            "POST", "https://internal.example.com/x", content=b""
        )


def _gzipped(body: bytes):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"Content-Encoding": "gzip", "Content-Type": "application/json"},
            content=gzip.compress(body),
        )

    return httpx2.MockTransport(handler)


async def test_a_bounded_read_is_counted_after_decoding(caplog):
    """A small compressed body that inflates past the bound is refused, and
    the request's line says so."""
    with (
        _resolves_to("93.184.216.34"),
        caplog.at_level(logging.DEBUG, logger="app.services.safe_http"),
        pytest.raises(ResponseTooLargeError),
    ):
        await request_public_target(
            "GET",
            "https://site.example.com/big",
            timeout=5.0,
            transport=_gzipped(b"0" * 10_000),
            max_bytes=1_000,
        )
    [line] = [r for r in caplog.records if r.name == "app.services.safe_http"]
    assert line.levelno == logging.INFO
    assert "ResponseTooLargeError" in line.getMessage()


async def test_a_bounded_read_within_its_bound_reads_as_usual():
    with _resolves_to("93.184.216.34"):
        response = await request_public_target(
            "GET",
            "https://site.example.com/small",
            timeout=5.0,
            transport=_gzipped(b'{"ok": true}'),
            max_bytes=1_000,
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert "content-encoding" not in response.headers


async def test_a_bounded_read_into_a_sink_replaces_what_it_held():
    """With a sink the decoded body is written there rather than held, over
    whatever an earlier answer left in it."""
    import io

    sink = io.BytesIO(b"an earlier answer, longer than this one")
    with _resolves_to("93.184.216.34"):
        response = await request_public_target(
            "GET",
            "https://site.example.com/file",
            timeout=5.0,
            transport=_gzipped(b"the file"),
            max_bytes=1_000,
            sink=sink,
        )

    assert response.status_code == 200
    assert response.content == b""
    assert sink.getvalue() == b"the file"


async def test_a_pinned_client_sends_nothing_about_the_server_and_reads_a_bounded_reply():
    """An SDK's platform headers are dropped and an uncompressed reply is asked
    for; a compressed reply is refused, and a long one stops at the bound."""
    seen: list[httpx2.Request] = []
    replies = [
        httpx2.Response(200, content=b"ok"),
        httpx2.Response(200, headers={"Content-Encoding": "gzip"}, content=b"x"),
        httpx2.Response(200, content=b"0" * 2_000),
    ]

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return replies[len(seen) - 1]

    transport = PinnedTransport(max_bytes=1_000, inner=httpx2.MockTransport(handler))
    headers = {"X-Stainless-OS": "Linux", "X-Stainless-Runtime-Version": "3.12"}
    async with httpx2.AsyncClient(transport=transport) as client:
        with _resolves_to("93.184.216.34"):
            ok = await client.get("https://llm.example.com/v1/models", headers=headers)
            with pytest.raises(ResponseTooLargeError):
                await client.get("https://llm.example.com/v1/models")
            with pytest.raises(ResponseTooLargeError):
                await client.get("https://llm.example.com/v1/models")

    assert ok.content == b"ok"
    assert seen[0].url.host == "93.184.216.34"
    assert not [name for name in seen[0].headers if name.startswith("x-stainless")]
    assert seen[0].headers["accept-encoding"] == "identity"
