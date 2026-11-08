"""Resolve an OIDC provider's signing key from its JWKS.

Given a trusted ``jwks_uri`` and a raw token, fetch the provider's JSON Web Key
Set and return the ``PyJWK`` whose ``kid`` matches the token header, for the
verifier (:mod:`app.services.auth.oidc.id_token`) to check the signature against.

Fetched with httpx2 (async) rather than PyJWT's blocking ``PyJWKClient``, so the
request is controlled directly:

* the ``jwks_uri`` must be ``https`` (rejected before any request otherwise);
* the response body is read under a fixed size cap;
* the key set is cached (TTL); an unknown ``kid`` triggers at most one refetch
  per interval.

Parsing uses PyJWT (``PyJWKSet``); the fetch does not. Any failure raises
:class:`JwksResolutionError` — fail-closed, so an unresolved key blocks login.
See the auth design doc for the rationale.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import jwt

from app.services.auth.oidc._http import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    DEFAULT_MAX_RESPONSE_BYTES,
    ClientFactory,
    OidcHttpError,
    fetch_json,
)

DEFAULT_CACHE_TTL_SECONDS: float = 300.0
DEFAULT_MIN_REFETCH_INTERVAL_SECONDS: float = 10.0


class JwksResolutionError(Exception):
    """The provider's signing key could not be resolved; verification must not
    proceed (fail-closed)."""


@dataclass
class _CachedKeySet:
    key_set: jwt.PyJWKSet
    fetched_at: float  # monotonic clock


class JwksResolver:
    """Fetches + caches provider JWKS and resolves a token's signing key.

    Hold one instance per process (the cache is shared across requests). The
    network client is built per fetch via ``client_factory`` so tests can inject
    an ``httpx2.MockTransport`` without patching globals.
    """

    def __init__(
        self,
        *,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        min_refetch_interval_seconds: float = DEFAULT_MIN_REFETCH_INTERVAL_SECONDS,
        http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._cache_ttl = cache_ttl_seconds
        self._min_refetch_interval = min_refetch_interval_seconds
        self._timeout = http_timeout_seconds
        self._max_bytes = max_response_bytes
        self._client_factory = client_factory  # None → fetch_json builds a default
        self._cache: dict[str, _CachedKeySet] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def resolve_signing_key(self, raw_token: str, *, jwks_uri: str) -> jwt.PyJWK:
        """Return the ``PyJWK`` for ``raw_token``'s ``kid`` from the JWKS at
        ``jwks_uri`` (fetching/caching as needed), or raise
        :class:`JwksResolutionError`.

        The ``kid`` is read from the token's *unverified* header — it only
        selects which key to check against; authenticity comes from the
        signature check, not the header.
        """
        try:
            header = jwt.get_unverified_header(raw_token)
        except jwt.PyJWTError as exc:
            raise JwksResolutionError(f"unreadable token header: {exc}") from exc
        kid = header.get("kid")

        key_set = await self._get_key_set(jwks_uri)
        key = _select_key(key_set, kid)
        if key is None and kid is not None:
            # A specific kid isn't in the cached set — keys may have rotated. One
            # rate-limited refetch, then give up. (A no-kid token that didn't
            # resolve is ambiguous, not stale, so refetching wouldn't help.)
            key = _select_key(await self._refetch(jwks_uri), kid)
        if key is None:
            raise JwksResolutionError(
                f"no signing key for kid={kid!r} in JWKS at {jwks_uri}"
            )
        return key

    async def _get_key_set(self, jwks_uri: str) -> jwt.PyJWKSet:
        cached = self._cache.get(jwks_uri)
        if cached is not None and self._fresh(cached):
            return cached.key_set
        async with self._lock_for(jwks_uri):
            # Double-check: another coroutine may have fetched while we waited, so
            # concurrent cold-cache callers make a single outbound fetch.
            cached = self._cache.get(jwks_uri)
            if cached is not None and self._fresh(cached):
                return cached.key_set
            return await self._fetch_and_cache(jwks_uri)

    async def _refetch(self, jwks_uri: str) -> jwt.PyJWKSet:
        """Lock-guarded, rate-limited refetch for a rotated ``kid``. Returns the
        current cached set unchanged when a refetch isn't due yet (or another
        coroutine just refreshed it)."""
        async with self._lock_for(jwks_uri):
            cached = self._cache.get(jwks_uri)
            if cached is not None:
                age = time.monotonic() - cached.fetched_at
                if age < self._min_refetch_interval:
                    return cached.key_set
            return await self._fetch_and_cache(jwks_uri)

    async def _fetch_and_cache(self, jwks_uri: str) -> jwt.PyJWKSet:
        key_set = await self._fetch(jwks_uri)
        self._cache[jwks_uri] = _CachedKeySet(
            key_set=key_set, fetched_at=time.monotonic()
        )
        return key_set

    def _fresh(self, cached: _CachedKeySet) -> bool:
        return (time.monotonic() - cached.fetched_at) < self._cache_ttl

    def _lock_for(self, jwks_uri: str) -> asyncio.Lock:
        # setdefault is atomic under the GIL, so concurrent callers converge on a
        # single lock per URI (a briefly-created extra Lock is harmless).
        lock = self._locks.get(jwks_uri)
        if lock is None:
            lock = self._locks.setdefault(jwks_uri, asyncio.Lock())
        return lock

    async def _fetch(self, jwks_uri: str) -> jwt.PyJWKSet:
        try:
            data = await fetch_json(
                jwks_uri,
                client_factory=self._client_factory,
                timeout_seconds=self._timeout,
                max_response_bytes=self._max_bytes,
            )
            return jwt.PyJWKSet.from_dict(data)
        except (OidcHttpError, jwt.PyJWTError) as exc:
            raise JwksResolutionError(
                f"could not load JWKS at {jwks_uri}: {exc}"
            ) from exc


def _select_key(key_set: jwt.PyJWKSet, kid: str | None) -> jwt.PyJWK | None:
    keys = key_set.keys
    if kid is not None:
        return next((k for k in keys if k.key_id == kid), None)
    # No kid in the token: only unambiguous when the set has exactly one key.
    return keys[0] if len(keys) == 1 else None
