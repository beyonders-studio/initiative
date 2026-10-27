"""Gzip for the responses it shrinks: text-like ones.

Starlette's ``GZipMiddleware`` compresses every response but an event stream.
Most of what this app serves by size is already compressed (pictures, video,
audio, Office and zip files), and compressing it again costs CPU for nothing,
so here only a text-like type is compressed: JSON, text, SVG, scripts. A
partial response (``206``) is never compressed, since its ``Content-Range``
counts the bytes as stored.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.middleware.gzip import (
    DEFAULT_EXCLUDED_CONTENT_TYPES,
    GZipMiddleware,
    GZipResponder,
)
from starlette.types import Message, Receive, Scope, Send

#: Text-like types that are not ``text/*``.
_TEXT_LIKE = frozenset(
    {
        "application/json",
        "application/javascript",
        "application/xml",
        "image/svg+xml",
    }
)


def compressible(content_type: str) -> bool:
    """Whether a response of ``content_type`` shrinks when gzipped."""
    media = content_type.split(";", 1)[0].strip().lower()
    if media.startswith(DEFAULT_EXCLUDED_CONTENT_TYPES):
        return False
    return (
        media.startswith("text/")
        or media in _TEXT_LIKE
        or media.endswith(("+json", "+xml"))
    )


def takes_gzip(accept_encoding: str) -> bool:
    """Whether an ``Accept-Encoding`` header takes gzip: named, or covered by
    ``*``, with a quality above zero."""
    qualities: dict[str, float] = {}
    for part in accept_encoding.split(","):
        name, *params = (piece.strip() for piece in part.split(";"))
        quality = 1.0
        for param in params:
            key, _, value = param.partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        if name:
            qualities[name.lower()] = quality
    return qualities.get("gzip", qualities.get("*", 0.0)) > 0


class _TextResponder(GZipResponder):
    async def send_with_compression(self, message: Message) -> None:
        await super().send_with_compression(message)
        if message["type"] == "http.response.start":
            headers = Headers(raw=message["headers"])
            self.content_type_is_excluded = message[
                "status"
            ] == 206 or not compressible(headers.get("content-type", ""))


class TextCompressionMiddleware(GZipMiddleware):
    """``GZipMiddleware`` for text-like responses only."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and takes_gzip(
            Headers(scope=scope).get("accept-encoding", "")
        ):
            responder = _TextResponder(
                self.app, self.minimum_size, compresslevel=self.compresslevel
            )
            await responder(scope, receive, send)
            return
        await self.app(scope, receive, send)
