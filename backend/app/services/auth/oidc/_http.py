"""Shared HTTPS JSON requests for the OIDC client (discovery, JWKS, token
endpoint).

One place for the network hardening every OIDC call needs — https-only, a fixed
response size cap, a timeout — so it is written and audited once rather than
copied. Callers add their own caching and wrap :class:`OidcHttpError` in a
domain-specific error.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from app.services.safe_http import ResponseTooLargeError, request_public_target
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

ClientFactory = Callable[[], httpx.AsyncClient]

DEFAULT_HTTP_TIMEOUT_SECONDS: float = 10.0
# A discovery doc / JWKS is a few KiB; 512 KiB is generous headroom.
DEFAULT_MAX_RESPONSE_BYTES: int = 512 * 1024
# Error bodies are logged, so keep only enough for the diagnostic payload.
_ERROR_SNIPPET_MAX_BYTES: int = 2048


class OidcHttpError(Exception):
    """An OIDC HTTPS fetch failed — non-https URL, transport/status error,
    oversized body, or invalid JSON. Callers wrap it in their own error."""


def _status_message(url: str, status: int, answer: Any) -> str:
    """An error status, with the OAuth ``error`` code (RFC 6749 §5.2) the
    answer carries, if it carries one."""
    code = answer.get("error") if isinstance(answer, dict) else None
    if isinstance(code, str) and code:
        return f"{url} returned {status} ({code[:64]})"
    return f"{url} returned {status}"


class OidcHttpStatusError(OidcHttpError):
    """The server answered, with an error status. ``body`` is what it said,
    parsed when it was JSON."""

    def __init__(self, message: str, *, status: int, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def require_https(url: str) -> None:
    # urlsplit lowercases the scheme, so ``HTTP`` etc. are covered; a missing host
    # (``https://``) is refused too.
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise OidcHttpError(f"refusing non-https URL: {url!r}")


async def fetch_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> Any:
    """GET ``url`` and return its parsed JSON, enforcing https and a response
    size cap. Raises :class:`OidcHttpError` on any failure (fail-closed).

    ``headers`` are sent verbatim (the userinfo endpoint needs a bearer token).
    ``client_factory`` builds the ``httpx.AsyncClient`` per call (tests inject a
    ``MockTransport``); it defaults to a timeout-configured client.
    """
    return await _request_json(
        "GET",
        url,
        headers=headers,
        client_factory=client_factory,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


async def post_form_json(
    url: str,
    data: dict[str, str],
    *,
    client_factory: ClientFactory | None = None,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> Any:
    """POST ``data`` as a form to ``url`` and return the parsed JSON response,
    with the same https / size-cap / fail-closed contract as :func:`fetch_json`.
    Used for the token-endpoint exchange."""
    return await _request_json(
        "POST",
        url,
        data=data,
        client_factory=client_factory,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
    )


async def _request_json(
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    client_factory: ClientFactory | None,
    timeout_seconds: float,
    max_response_bytes: int,
) -> Any:
    require_https(url)
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout_seconds))
    body = bytearray()
    # Failures are flagged and raised AFTER the stream context exits: raising
    # inside it would leave our exception exposed to replacement by a teardown
    # error from the abandoned body (the transport may fault when we stop
    # reading mid-stream).
    over_cap = False
    error_status: int | None = None
    try:
        async with (
            factory() as client,
            client.stream(method, url, data=data, headers=headers) as resp,
        ):
            if resp.status_code >= 400:
                # Read a bounded snippet of the error body for its OAuth
                # error code ({"error": "invalid_grant", ...}), the one
                # diagnostic the server operator needs in the logs.
                error_status = resp.status_code
                max_bytes = _ERROR_SNIPPET_MAX_BYTES
            else:
                max_bytes = max_response_bytes
            async for chunk in resp.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    over_cap = True
                    break
    except httpx.HTTPError as exc:
        raise OidcHttpError(f"fetch failed for {url}: {exc}") from exc
    if error_status is not None:
        try:
            answer = json.loads(body[:_ERROR_SNIPPET_MAX_BYTES])
        except ValueError:
            answer = None
        raise OidcHttpError(_status_message(url, error_status, answer))
    if over_cap:
        raise OidcHttpError(
            f"response from {url} exceeds the {max_response_bytes}-byte cap"
        )
    try:
        return json.loads(body)
    except ValueError as exc:
        raise OidcHttpError(f"invalid JSON from {url}: {exc}") from exc


async def post_form_json_pinned(
    url: str,
    data: dict[str, str],
    *,
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> Any:
    """POST ``data`` as a form to a vendor's https endpoint and return the
    parsed JSON response.

    The same contract as :func:`post_form_json`, with the connection made
    through :func:`app.services.safe_http.request_public_target`: the host is
    resolved once, checked against the egress policy, and connected to at
    that address. An error status raises :class:`OidcHttpStatusError` carrying
    what the server said. A form-encoded answer is read too, since some token
    endpoints answer in the encoding they were sent.
    """
    require_https(url)
    merged = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
        **(headers or {}),
    }
    try:
        response = await request_public_target(
            "POST",
            url,
            headers=merged,
            content=urlencode(data).encode("ascii"),
            timeout=timeout_seconds,
            transport=transport,
            max_bytes=max_response_bytes,
        )
    except ResponseTooLargeError as exc:
        raise OidcHttpError(
            f"response from {url} exceeds the {max_response_bytes}-byte cap"
        ) from exc
    except (WebhookTargetUrlError, WebhookTargetUrlPrivateError) as exc:
        raise OidcHttpError(f"refusing target {url!r}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise OidcHttpError(f"fetch failed for {url}: {exc}") from exc

    body = response.content
    parsed: Any
    try:
        parsed = json.loads(body) if body else None
    except ValueError:
        if "application/x-www-form-urlencoded" in response.headers.get(
            "content-type", ""
        ):
            parsed = dict(parse_qsl(body.decode("utf-8", errors="replace")))
        else:
            parsed = None
    if response.status_code >= 400:
        raise OidcHttpStatusError(
            _status_message(url, response.status_code, parsed),
            status=response.status_code,
            body=parsed,
        )
    if parsed is None:
        raise OidcHttpError(f"invalid JSON from {url}")
    return parsed
