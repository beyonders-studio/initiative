"""Central egress helper for outbound HTTP to caller-influenced URLs.

Webhook delivery and the AI providers send requests to URLs a community or
the operator can set. They go through :func:`request_public_target`, or
through :class:`PinnedTransport` for a client that builds its own requests,
so the target policy (see :mod:`app.services.webhook_target_url`) is enforced
in one place and the request connects to the address that was validated.

The host is resolved once; the request is aimed at the resulting address
while the original hostname is preserved for TLS SNI, certificate
verification, and the ``Host`` header. Redirects are not followed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any, BinaryIO

import httpx

from app.services.webhook_target_url import resolve_validated_target_async

logger = logging.getLogger(__name__)


class ResponseTooLargeError(Exception):
    """The response body, decoded, ran past the caller's ``max_bytes``.

    ``status_code`` is the status the response carried, for a caller that
    only needed that."""

    def __init__(self, max_bytes: int, *, status_code: int | None = None):
        super().__init__(max_bytes)
        self.status_code = status_code


def _log_sent(
    method: str,
    url: httpx.URL,
    began: float,
    *,
    status: int | None = None,
    failure: BaseException | None = None,
) -> None:
    """One line per request sent: the method, the target's origin, what it
    answered and how long it took. A failure or a non-2xx answer is ``INFO``,
    a success ``DEBUG``."""
    ok = failure is None and status is not None and 200 <= status < 300
    logger.log(
        logging.DEBUG if ok else logging.INFO,
        "%s %s://%s %s %.0f ms",
        method,
        url.scheme,
        _authority(url),
        type(failure).__name__ if failure is not None else status,
        (time.perf_counter() - began) * 1000,
    )


def _authority(url: httpx.URL) -> str:
    """``host[:port]`` for the ``Host`` header, bracketing IPv6 literals
    and including the port only when the URL specified one."""
    host = url.host
    bracketed = f"[{host}]" if ":" in host else host
    port = url.port
    return f"{bracketed}:{port}" if port is not None else bracketed


async def build_validated_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    json: Any = None,
    allow_private: bool = False,
) -> httpx.Request:
    """Resolve and validate ``url``, then build a request whose connection
    target is the validated address, keeping the hostname for TLS SNI,
    certificate verification, and the ``Host`` header. ``allow_private``
    permits private/loopback targets (still pinned) for operator-configured
    destinations.

    Raises :class:`~app.services.webhook_target_url.WebhookTargetUrlError`
    or :class:`~app.services.webhook_target_url.WebhookTargetUrlPrivateError`
    for a disallowed target.
    """
    original = httpx.URL(url)
    target = await resolve_validated_target_async(url, allow_private=allow_private)
    return _pin_request(
        method,
        original,
        target.pinned_ip,
        target.hostname,
        headers=headers,
        content=content,
        json=json,
    )


def _pin_request(
    method: str,
    original: httpx.URL,
    ip: str,
    hostname: str,
    *,
    headers: Mapping[str, str] | None,
    content: bytes | None = None,
    json: Any = None,
    stream: httpx.AsyncByteStream | None = None,
    extensions: Mapping[str, Any] | None = None,
) -> httpx.Request:
    """Build a request aimed at ``ip`` while keeping ``hostname`` for TLS
    SNI, certificate verification, and the ``Host`` header."""
    merged = {k: v for k, v in (headers or {}).items() if k.lower() != "host"}
    merged["Host"] = _authority(original)
    return httpx.Request(
        method,
        original.copy_with(host=ip),
        headers=merged,
        content=content,
        json=json,
        stream=stream,
        extensions={**(extensions or {}), "sni_hostname": hostname},
    )


class _BoundedStream(httpx.AsyncByteStream):
    """A response body that stops at ``max_bytes``."""

    def __init__(self, inner: Any, max_bytes: int, status_code: int) -> None:
        self._inner = inner
        self._max_bytes = max_bytes
        self._status_code = status_code

    async def __aiter__(self):
        read = 0
        async for chunk in self._inner:
            read += len(chunk)
            if read > self._max_bytes:
                raise ResponseTooLargeError(
                    self._max_bytes, status_code=self._status_code
                )
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()


class PinnedTransport(httpx.AsyncBaseTransport):
    """A transport that sends every request to a validated address of its
    host, as :func:`request_public_target` does, for a client that builds
    its own requests (an SDK's). A redirect it follows is a new request,
    validated the same way.

    It sends nothing about the server beyond the request itself: an SDK's
    ``x-stainless-*`` headers, which name the platform and its versions, are
    dropped. ``max_bytes`` bounds a response body: an uncompressed one is
    asked for, a compressed one is refused, and reading stops past the bound
    with :class:`ResponseTooLargeError`."""

    def __init__(
        self,
        *,
        allow_private: bool = False,
        max_bytes: int | None = None,
        inner: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allow_private = allow_private
        self._max_bytes = max_bytes
        self._inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        original = request.url
        target = await resolve_validated_target_async(
            str(original), allow_private=self._allow_private
        )
        headers = {
            name: value
            for name, value in request.headers.items()
            if not name.lower().startswith("x-stainless")
        }
        if self._max_bytes is not None:
            headers["accept-encoding"] = "identity"
        last_exc: httpx.ConnectError | None = None
        for address in target.addresses:
            pinned = _pin_request(
                request.method,
                original,
                str(address),
                target.hostname,
                headers=headers,
                stream=request.stream,  # type: ignore[arg-type]
                extensions=request.extensions,
            )
            began = time.perf_counter()
            try:
                response = await self._inner.handle_async_request(pinned)
            except httpx.ConnectError as exc:
                _log_sent(request.method, original, began, failure=exc)
                last_exc = exc
                continue
            except httpx.HTTPError as exc:
                _log_sent(request.method, original, began, failure=exc)
                raise
            _log_sent(request.method, original, began, status=response.status_code)
            return await self._bounded(response)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"no validated address to connect to for {original!r}")

    async def _bounded(self, response: httpx.Response) -> httpx.Response:
        if self._max_bytes is None:
            return response
        encoding = response.headers.get("content-encoding", "identity").lower()
        if encoding not in ("", "identity"):
            # Its decoded size is not known until it is decoded.
            await response.aclose()
            raise ResponseTooLargeError(
                self._max_bytes, status_code=response.status_code
            )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            stream=_BoundedStream(
                response.stream, self._max_bytes, response.status_code
            ),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


async def request_public_target(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    json: Any = None,
    timeout: httpx.Timeout | float,
    transport: httpx.AsyncBaseTransport | None = None,
    allow_private: bool = False,
    max_bytes: int | None = None,
    sink: BinaryIO | None = None,
) -> httpx.Response:
    """Send a request to a validated public target. The host is resolved
    once; the request connects to a validated address and, if one fails
    fast (connection refused / unreachable), falls back to the other
    validated addresses. A connect *timeout* is not retried — it has
    already consumed the caller's budget — so total wall time stays bounded
    by ``timeout``. ``allow_private`` permits private/loopback targets (still
    pinned) for operator-configured destinations. ``transport`` is injectable
    for tests.

    ``max_bytes`` bounds the body as it is read, counted after any content
    decoding, and raises :class:`ResponseTooLargeError` past it. Unset, the
    body is read whole. With ``sink`` as well, the body is written to it from
    its start rather than held, and the response carries none."""
    original = httpx.URL(url)
    target = await resolve_validated_target_async(url, allow_private=allow_private)
    last_exc: httpx.ConnectError | None = None
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, transport=transport
    ) as client:
        for address in target.addresses:
            request = _pin_request(
                method,
                original,
                str(address),
                target.hostname,
                headers=headers,
                content=content,
                json=json,
            )
            began = time.perf_counter()
            try:
                response = await client.send(request, stream=max_bytes is not None)
            except httpx.ConnectError as exc:
                # Fast failure for this validated address; try the next one.
                _log_sent(method, original, began, failure=exc)
                last_exc = exc
                continue
            except httpx.HTTPError as exc:
                _log_sent(method, original, began, failure=exc)
                raise
            if max_bytes is not None:
                try:
                    response = await _read_bounded(response, max_bytes, sink)
                except (httpx.HTTPError, ResponseTooLargeError) as exc:
                    _log_sent(method, original, began, failure=exc)
                    raise
            _log_sent(method, original, began, status=response.status_code)
            return response
    if last_exc is not None:
        raise last_exc
    # Unreachable: resolve_validated_target_async guarantees at least one
    # address, so the loop always sets last_exc on total failure.
    raise RuntimeError(f"no validated address to connect to for {url!r}")


async def _read_bounded(
    response: httpx.Response, max_bytes: int, sink: BinaryIO | None = None
) -> httpx.Response:
    """A streamed response read up to ``max_bytes`` decoded bytes: into
    memory, or written to ``sink`` from its start, emptied first, so that
    after a retry or a redirect it holds the last response's body.

    Returned as a plain response holding the decoded body, or none when it
    went to ``sink``, so the encoding headers that described the wire form
    are dropped with it.
    """
    body = bytearray()
    read = 0
    if sink is not None:
        sink.seek(0)
        sink.truncate()
    try:
        async for chunk in response.aiter_bytes():
            read += len(chunk)
            if read > max_bytes:
                raise ResponseTooLargeError(max_bytes, status_code=response.status_code)
            if sink is None:
                body += chunk
            else:
                sink.write(chunk)
    finally:
        await response.aclose()
    headers = [
        (name, value)
        for name, value in response.headers.multi_items()
        if name.lower()
        not in ("content-encoding", "content-length", "transfer-encoding")
    ]
    return httpx.Response(
        response.status_code,
        headers=headers,
        content=bytes(body),
        request=response.request,
    )
