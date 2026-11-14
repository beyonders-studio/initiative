"""Tests for the JWKS signing-key resolver.

Outbound fetches are stubbed with ``httpx2.MockTransport`` (injected via
``client_factory`` — no global patching, no real network), so key selection,
caching, the rate-limited refetch, and the https/size guards are all exercised
in isolation. The happy path composes with the id_token verifier to prove the
two halves fit.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app.services.auth.oidc.id_token import verify_id_token
from app.services.auth.oidc.jwks import JwksResolutionError, JwksResolver

JWKS_URI = "https://idp.example.com/jwks"
ISSUER = "https://idp.example.com"
AUDIENCE = "client-123"
NONCE = "nonce-abc"

# Two RSA keys, generated once; tests assign them kids as needed.
RSA1 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem_private(priv) -> str:
    return priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def _jwk(priv, *, kid: str, extra: dict | None = None) -> dict:
    data = json.loads(RSAAlgorithm.to_jwk(priv.public_key()))
    data.update({"kid": kid, "alg": "RS256", "use": "sig"})
    if extra:
        data.update(extra)
    return data


def _jwks(*entries: dict) -> dict:
    return {"keys": list(entries)}


def _sign(priv, *, kid: str | None = None, **claim_overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": AUDIENCE,
        "exp": now + timedelta(minutes=5),
        "iat": now,
        "nonce": NONCE,
    }
    claims.update(claim_overrides)
    headers = {"kid": kid} if kid is not None else None
    return jwt.encode(claims, _pem_private(priv), algorithm="RS256", headers=headers)


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


def _json_response(payload: dict) -> httpx2.Response:
    return httpx2.Response(200, json=payload)


# --- resolution + composition ----------------------------------------------


async def test_resolves_kid_and_verifies_end_to_end():
    """The resolved key verifies the token — resolver + verifier compose."""
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid="k1")

    key = await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)
    assert key.key_id == "k1"
    claims = verify_id_token(
        token, signing_key=key, issuer=ISSUER, audience=AUDIENCE, nonce=NONCE
    )
    assert claims["sub"] == "user-1"


async def test_selects_correct_key_among_many():
    endpoint = _Endpoint(
        _json_response(_jwks(_jwk(RSA1, kid="k1"), _jwk(RSA2, kid="k2")))
    )
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA2, kid="k2")

    key = await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)
    # Resolved k2's key: it verifies the RSA2-signed token.
    verify_id_token(
        token, signing_key=key, issuer=ISSUER, audience=AUDIENCE, nonce=NONCE
    )
    assert key.key_id == "k2"


async def test_no_kid_uses_sole_key():
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid=None)  # no kid header

    key = await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)
    assert key.key_id == "k1"


async def test_no_kid_with_multiple_keys_is_ambiguous():
    endpoint = _Endpoint(
        _json_response(_jwks(_jwk(RSA1, kid="k1"), _jwk(RSA2, kid="k2")))
    )
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid=None)

    with pytest.raises(JwksResolutionError):
        await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)


async def test_no_kid_ambiguous_does_not_refetch():
    """An unresolved no-kid token is ambiguous, not stale — no refetch, even
    when the rate limit would allow one."""
    endpoint = _Endpoint(
        _json_response(_jwks(_jwk(RSA1, kid="k1"), _jwk(RSA2, kid="k2")))
    )
    resolver = JwksResolver(
        client_factory=endpoint.factory(), min_refetch_interval_seconds=0
    )
    with pytest.raises(JwksResolutionError):
        await resolver.resolve_signing_key(_sign(RSA1, kid=None), jwks_uri=JWKS_URI)
    assert endpoint.calls == 1  # the initial fetch only, no spurious refetch


async def test_unknown_kid_raises():
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid="does-not-exist")

    with pytest.raises(JwksResolutionError):
        await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)


# --- https-only ------------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    [
        "http://idp.example.com/jwks",
        "file:///etc/passwd",
        "data:application/json,{}",
        "ftp://idp.example.com/jwks",
        "https://",  # no host
    ],
)
async def test_non_https_uri_refused_without_fetching(uri):
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid="k1")

    with pytest.raises(JwksResolutionError):
        await resolver.resolve_signing_key(token, jwks_uri=uri)
    assert endpoint.calls == 0  # refused before any request


# --- caching + rate-limited refetch ----------------------------------------


async def test_key_set_is_cached_within_ttl():
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid="k1")

    await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)
    await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)
    assert endpoint.calls == 1  # second resolve served from cache


async def test_concurrent_cold_resolves_make_one_fetch():
    """A burst of concurrent resolves against a cold cache collapses to a single
    outbound fetch (per-URI lock + double-check), not one per caller."""
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid="k1")

    keys = await asyncio.gather(
        *(resolver.resolve_signing_key(token, jwks_uri=JWKS_URI) for _ in range(8))
    )
    assert all(k.key_id == "k1" for k in keys)
    assert endpoint.calls == 1


async def test_unknown_kid_triggers_one_refetch_when_allowed():
    """A rotated key (new kid) is picked up by exactly one refetch."""
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    # min_refetch_interval=0 → the refetch is permitted immediately.
    resolver = JwksResolver(
        client_factory=endpoint.factory(), min_refetch_interval_seconds=0
    )
    # Prime the cache with the k1-only set.
    await resolver.resolve_signing_key(_sign(RSA1, kid="k1"), jwks_uri=JWKS_URI)
    assert endpoint.calls == 1

    # Provider rotates in k2; a k2 token misses the cache then refetches.
    endpoint.set_response(
        _json_response(_jwks(_jwk(RSA1, kid="k1"), _jwk(RSA2, kid="k2")))
    )
    key = await resolver.resolve_signing_key(_sign(RSA2, kid="k2"), jwks_uri=JWKS_URI)
    assert key.key_id == "k2"
    assert endpoint.calls == 2


async def test_unknown_kid_refetch_is_rate_limited():
    """With a fresh cache and a long refetch interval, an unknown kid does NOT
    refetch — the amplification guard (a flood of random kids can't hammer the
    JWKS endpoint)."""
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    resolver = JwksResolver(
        client_factory=endpoint.factory(),
        min_refetch_interval_seconds=3600,
    )
    await resolver.resolve_signing_key(_sign(RSA1, kid="k1"), jwks_uri=JWKS_URI)
    assert endpoint.calls == 1

    with pytest.raises(JwksResolutionError):
        await resolver.resolve_signing_key(
            _sign(RSA2, kid="flood-kid"), jwks_uri=JWKS_URI
        )
    assert endpoint.calls == 1  # no extra fetch


# --- hostile / broken endpoints --------------------------------------------


async def test_response_size_cap_enforced():
    padded = _jwks(_jwk(RSA1, kid="k1", extra={"junk": "x" * 5000}))
    endpoint = _Endpoint(_json_response(padded))
    resolver = JwksResolver(client_factory=endpoint.factory(), max_response_bytes=256)
    token = _sign(RSA1, kid="k1")

    # The cap error surfaces as itself, not masked into a generic fetch failure.
    with pytest.raises(JwksResolutionError, match="byte cap"):
        await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)


async def test_http_error_raises_resolution_error():
    endpoint = _Endpoint(httpx2.Response(500, text="down"))
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid="k1")

    with pytest.raises(JwksResolutionError):
        await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)


async def test_invalid_jwks_body_raises():
    endpoint = _Endpoint(httpx2.Response(200, text="not json"))
    resolver = JwksResolver(client_factory=endpoint.factory())
    token = _sign(RSA1, kid="k1")

    with pytest.raises(JwksResolutionError):
        await resolver.resolve_signing_key(token, jwks_uri=JWKS_URI)


async def test_malformed_token_header_raises():
    endpoint = _Endpoint(_json_response(_jwks(_jwk(RSA1, kid="k1"))))
    resolver = JwksResolver(client_factory=endpoint.factory())

    with pytest.raises(JwksResolutionError):
        await resolver.resolve_signing_key("not-a-jwt", jwks_uri=JWKS_URI)
    assert endpoint.calls == 0  # bail before fetching
