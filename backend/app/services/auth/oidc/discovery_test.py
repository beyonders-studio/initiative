"""Tests for OIDC provider discovery.

Outbound fetches are stubbed with ``httpx2.MockTransport`` (injected via
``client_factory`` — no network), so metadata parsing, the issuer-match check,
the https guards, and caching are exercised in isolation.
"""

from __future__ import annotations

import asyncio

import httpx2
import pytest

from app.services.auth.oidc.discovery import (
    DiscoveryError,
    OidcDiscovery,
)

ISSUER = "https://idp.example.com"


def _doc(**overrides) -> dict:
    doc = {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/authorize",
        "token_endpoint": f"{ISSUER}/token",
        "jwks_uri": f"{ISSUER}/jwks",
        "id_token_signing_alg_values_supported": ["RS256", "ES256"],
    }
    for key, value in overrides.items():
        if value is None:
            doc.pop(key, None)
        else:
            doc[key] = value
    return doc


class _Endpoint:
    """A MockTransport handler that counts calls and can change its response."""

    def __init__(self, response):
        self.calls = 0
        self._response = response

    def set_response(self, response) -> None:
        self._response = response

    def factory(self):
        def handler(request: httpx2.Request) -> httpx2.Response:
            self.calls += 1
            resp = self._response
            return resp(request) if callable(resp) else resp

        return lambda: httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def _json(payload) -> httpx2.Response:
    return httpx2.Response(200, json=payload)


# --- happy path -------------------------------------------------------------


async def test_fetches_and_parses_metadata():
    endpoint = _Endpoint(_json(_doc()))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    meta = await discovery.fetch(ISSUER)
    assert meta.issuer == ISSUER
    assert meta.authorization_endpoint == f"{ISSUER}/authorize"
    assert meta.token_endpoint == f"{ISSUER}/token"
    assert meta.jwks_uri == f"{ISSUER}/jwks"
    assert meta.id_token_signing_alg_values_supported == ("RS256", "ES256")


async def test_requests_the_well_known_url():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        return _json(_doc())

    discovery = OidcDiscovery(
        client_factory=lambda: httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        )
    )
    # A trailing slash on the configured issuer must not double up the path.
    await discovery.fetch(f"{ISSUER}/")
    assert seen["url"] == f"{ISSUER}/.well-known/openid-configuration"


async def test_already_well_known_issuer_not_doubled():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        return _json(_doc())

    discovery = OidcDiscovery(
        client_factory=lambda: httpx2.AsyncClient(
            transport=httpx2.MockTransport(handler)
        )
    )
    await discovery.fetch(f"{ISSUER}/.well-known/openid-configuration")
    assert seen["url"] == f"{ISSUER}/.well-known/openid-configuration"


async def test_missing_optional_algs_is_none():
    endpoint = _Endpoint(_json(_doc(id_token_signing_alg_values_supported=None)))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    meta = await discovery.fetch(ISSUER)
    assert meta.id_token_signing_alg_values_supported is None


async def test_metadata_keeps_the_provider_spelling():
    """A trailing slash is ignored when matching, and kept in the metadata."""
    endpoint = _Endpoint(_json(_doc(issuer=f"{ISSUER}/")))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    meta = await discovery.fetch(ISSUER)
    assert meta.issuer == f"{ISSUER}/"


# --- issuer-match + validation ---------------------------------------------


async def test_issuer_mismatch_rejected():
    """A document that claims a different issuer must not be trusted."""
    endpoint = _Endpoint(_json(_doc(issuer="https://evil.example.com")))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    with pytest.raises(DiscoveryError):
        await discovery.fetch(ISSUER)


@pytest.mark.parametrize(
    "field", ["authorization_endpoint", "token_endpoint", "jwks_uri"]
)
async def test_missing_required_endpoint_rejected(field):
    endpoint = _Endpoint(_json(_doc(**{field: None})))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    with pytest.raises(DiscoveryError):
        await discovery.fetch(ISSUER)


@pytest.mark.parametrize(
    "field", ["authorization_endpoint", "token_endpoint", "jwks_uri"]
)
async def test_non_https_endpoint_rejected(field):
    endpoint = _Endpoint(_json(_doc(**{field: "http://idp.example.com/x"})))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    with pytest.raises(DiscoveryError):
        await discovery.fetch(ISSUER)


async def test_non_https_issuer_refused_without_fetching():
    endpoint = _Endpoint(_json(_doc()))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    with pytest.raises(DiscoveryError):
        await discovery.fetch("http://idp.example.com")
    assert endpoint.calls == 0


async def test_non_object_document_rejected():
    endpoint = _Endpoint(_json(["not", "an", "object"]))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    with pytest.raises(DiscoveryError):
        await discovery.fetch(ISSUER)


async def test_http_error_raises_discovery_error():
    endpoint = _Endpoint(httpx2.Response(500, text="down"))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    with pytest.raises(DiscoveryError):
        await discovery.fetch(ISSUER)


async def test_response_size_cap_passes_through():
    """The per-instance size cap reaches the shared fetch, and the cap error
    surfaces as itself (not masked into a generic fetch failure)."""
    endpoint = _Endpoint(_json(_doc(padding="x" * 5000)))
    discovery = OidcDiscovery(client_factory=endpoint.factory(), max_response_bytes=256)

    with pytest.raises(DiscoveryError, match="byte cap"):
        await discovery.fetch(ISSUER)


# --- caching ----------------------------------------------------------------


async def test_metadata_cached_within_ttl():
    endpoint = _Endpoint(_json(_doc()))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    await discovery.fetch(ISSUER)
    await discovery.fetch(ISSUER)
    assert endpoint.calls == 1


async def test_concurrent_cold_fetches_make_one_request():
    endpoint = _Endpoint(_json(_doc()))
    discovery = OidcDiscovery(client_factory=endpoint.factory())

    results = await asyncio.gather(*(discovery.fetch(ISSUER) for _ in range(8)))
    assert all(m.token_endpoint == f"{ISSUER}/token" for m in results)
    assert endpoint.calls == 1
