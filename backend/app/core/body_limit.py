"""ASGI body-size enforcement for every HTTP request.

A route marked with :func:`max_body` gets its own bound; every other request
gets :data:`DEFAULT_MAX_REQUEST_BYTES`, or :data:`MULTIPART_MAX_REQUEST_BYTES`
when it is a multipart upload. The route is the one the router will run
(:mod:`app.core.routing`), so the bound follows the route as it is declared.

A handler-level ``Content-Length`` check is too late: FastAPI resolves the
request body (and parses JSON) before any handler code runs, and a chunked
request carries no ``Content-Length`` at all. This middleware enforces the
bound at the transport seam instead — the declared length is rejected before
a byte is read, and a chunked/lying stream is cut off the moment it exceeds
the limit, so no more than ``limit`` bytes are ever buffered.

Pure ASGI (not ``BaseHTTPMiddleware``): it must wrap ``receive`` itself.
Limits are read per request, so test-time monkeypatches apply.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from starlette.datastructures import Headers

from app.core.messages import CommonMessages
from app.core.routing import route_endpoint

#: The most a request no route bounds may carry. The largest ordinary body is
#: a calendar import — two million characters of iCalendar text in JSON — and
#: this leaves it room to spare.
DEFAULT_MAX_REQUEST_BYTES = 4 * 1024 * 1024

#: Room a multipart body leaves for its framing around the file a route caps.
#: The handler's bounded read still enforces that cap exactly.
MULTIPART_SLACK_BYTES = 1_048_576

#: The most a multipart upload no route bounds may carry: the largest file any
#: upload route takes (an uploaded file, 50 MiB) and its framing.
MULTIPART_MAX_REQUEST_BYTES = 50 * 1024 * 1024 + MULTIPART_SLACK_BYTES

#: The most a file's content may carry. A whiteboard keeps its pictures
#: inline in the scene, so a board is far larger than any other JSON body.
DOCUMENT_MAX_REQUEST_BYTES = 64 * 1024 * 1024

_ATTRIBUTE = "max_request_body"

Endpoint = TypeVar("Endpoint", bound=Callable[..., Any])


@dataclass(frozen=True)
class BodyBound:
    """A route's own body bound: its limit, read when a request arrives, and
    the code a body past it is refused with."""

    limit: Callable[[], int]
    code: str


def max_body(
    limit: Callable[[], int], code: str = CommonMessages.REQUEST_TOO_LARGE
) -> Callable[[Endpoint], Endpoint]:
    """Give the decorated endpoint its own body bound in place of the default.

    ``limit`` is called per request, so the bound is whatever the setting it
    reads holds at that moment. Applied beneath the route decorator.
    """

    def mark(endpoint: Endpoint) -> Endpoint:
        setattr(endpoint, _ATTRIBUTE, BodyBound(limit=limit, code=code))
        return endpoint

    return mark


#: The bound of every route that writes a file's content: create, update, a
#: wiki page, and the edits a closing tab hands over to a room.
max_document_body = max_body(lambda: DOCUMENT_MAX_REQUEST_BYTES)


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        limit, code = _bound_for(scope, headers)

        # Fast path: an honest Content-Length is rejected before ANY body
        # bytes are read.
        declared = _content_length(headers)
        if declared is not None and declared > limit:
            await _send_413(send, code)
            return

        # Streaming backstop: count what actually arrives (chunked requests
        # declare nothing; a lying Content-Length under-declares).
        received = 0
        over_limit = False
        response_started = False
        replaced = False

        async def limited_receive():
            nonlocal received, over_limit
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    over_limit = True
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started, replaced
            # The framework converted the aborted body read into its own
            # error response (FastAPI reports a 400 body-parse failure);
            # the true cause is the size cap — answer 413 instead.
            if (
                over_limit
                and not response_started
                and message["type"] == "http.response.start"
            ):
                replaced = True
                response_started = True
                await _send_413(send, code)
                return
            if replaced and message["type"] == "http.response.body":
                return  # swallow the framework error body; ours already went
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            # The app propagated the aborted read without responding — answer
            # directly (if headers already went out the connection is
            # unsalvageable and closing it is the only honest signal).
            if not response_started:
                await _send_413(send, code)


def _bound_for(scope, headers: Headers) -> tuple[int, str]:
    """The limit and error code for this request: its route's own bound if
    it declares one, otherwise the default for its kind of body."""
    bound = getattr(route_endpoint(scope), _ATTRIBUTE, None)
    if isinstance(bound, BodyBound):
        return bound.limit(), bound.code
    if headers.get("content-type", "").lower().startswith("multipart/"):
        return MULTIPART_MAX_REQUEST_BYTES, CommonMessages.REQUEST_TOO_LARGE
    return DEFAULT_MAX_REQUEST_BYTES, CommonMessages.REQUEST_TOO_LARGE


def _content_length(headers: Headers) -> int | None:
    try:
        return int(headers["content-length"])
    except (KeyError, ValueError):
        return None


async def _send_413(send: Callable[..., Awaitable[None]], code: str) -> None:
    body = json.dumps({"detail": code}).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
