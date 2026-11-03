"""Read a raster image's format and pixel dimensions from its header bytes.

Deliberately not Pillow. The callers here validate images a user just uploaded,
in the request path, and a full decoder is a much larger surface than the
question being asked — which is only ever "what is this, and how big is it".
Reading the handful of header fields that answer it never decompresses pixel
data, so a malformed or hostile body costs a few bounds-checked slices.

Raster formats only, and no SVG anywhere: an SVG is a scriptable document, and
every caller here renders its result in an ``<img>`` rather than offering it as
a download, so the force-download escape hatch that makes an SVG attachment
safe does not apply.

Which of these formats a given upload may actually be is the caller's decision:
each surface states it in an :class:`ImageSpec`, and :func:`validate_image`
holds an upload to one — a guild image and an avatar allow different sets.

``read_image_header`` returns ``None`` for anything it does not recognize or
cannot parse, so callers treat "not a supported image" and "corrupt header" the
same way.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from fastapi import Response

from app.core.errors import CodedError
from app.core.messages import ImageMessages

#: JPEG frame markers that carry dimensions. The other ``FF Cx`` markers are
#: huffman/arithmetic tables and restart intervals, which do not.
_JPEG_SOF_MARKERS = frozenset(
    {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
)


#: Every format ``read_image_header`` recognizes.
RASTER_CONTENT_TYPES: frozenset[str] = frozenset(
    {"image/webp", "image/png", "image/jpeg", "image/gif"}
)

#: How far an image may drift from its spec's proportions. Wide enough for the
#: rounding a browser's canvas does, narrow enough that a differently-shaped
#: image is refused.
ASPECT_TOLERANCE = 0.02

#: The most pixels a picture may hold before a decoder refuses it: well above
#: any canvas or photo, well below what would exhaust a worker's memory
#: decompressing it.
MAX_IMAGE_PIXELS = 89_478_485


@dataclass(frozen=True)
class ImageSpec:
    """What an uploaded image must be.

    One of ``content_types``, at most ``max_bytes``, and no larger than
    ``width`` by ``height``. With ``keep_aspect`` it must also be that box's
    shape, within :data:`ASPECT_TOLERANCE`; without it, any shape that fits.
    """

    width: int
    height: int
    max_bytes: int
    content_types: frozenset[str]
    keep_aspect: bool = True


@dataclass(frozen=True)
class ValidatedImage:
    """An upload that met its spec, described by its header, ready to store.

    ``content_type`` is the one the header proves, never the one the client
    claimed, because it is served back in a ``Content-Type``.
    """

    data: bytes
    sha256: str
    content_type: str
    width: int
    height: int

    @property
    def byte_size(self) -> int:
        return len(self.data)


class ImageRejected(CodedError):
    """An upload that does not meet its spec, carrying the code naming why."""


def validate_image(spec: ImageSpec, data: bytes) -> ValidatedImage:
    """Hold ``data`` to ``spec`` and describe it, or raise ``ImageRejected``."""
    if not data:
        raise ImageRejected(ImageMessages.IMAGE_EMPTY)
    if len(data) > spec.max_bytes:
        raise ImageRejected(ImageMessages.IMAGE_TOO_LARGE)
    header = read_image_header(data)
    if header is None or header.content_type not in spec.content_types:
        raise ImageRejected(ImageMessages.IMAGE_INVALID)
    if header.width > spec.width or header.height > spec.height:
        raise ImageRejected(ImageMessages.IMAGE_WRONG_SIZE)
    if spec.keep_aspect:
        # Both shapes on one scale, the gap measured against the larger, so an
        # image a little wide and one a little tall get the same allowance.
        shown, wanted = header.width * spec.height, header.height * spec.width
        if abs(shown - wanted) > max(shown, wanted) * ASPECT_TOLERANCE:
            raise ImageRejected(ImageMessages.IMAGE_WRONG_RATIO)
    return ValidatedImage(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        content_type=header.content_type,
        width=header.width,
        height=header.height,
    )


def image_response(data: bytes, content_type: str, *, shared: bool) -> Response:
    """Serve stored image bytes addressed by their digest.

    The digest is in the URL, so these bytes are these bytes forever and the
    response is cached for a year. ``shared`` is whether every caller gets the
    same answer: a shared cache may then hand it on, and otherwise only the
    browser that asked keeps it.
    """
    scope = "public" if shared else "private"
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": f"{scope}, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )


@dataclass(frozen=True)
class ImageHeader:
    """What a header says the image is."""

    content_type: str
    width: int
    height: int


def read_image_header(data: bytes) -> ImageHeader | None:
    """Identify ``data`` and read its dimensions, or ``None``."""
    if len(data) < 16:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return _png(data)
    if data[:2] == b"\xff\xd8":
        return _jpeg(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp(data)
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return _gif(data)
    return None


def _png(data: bytes) -> ImageHeader | None:
    # The IHDR chunk is required to come first, so width/height sit at a fixed
    # offset: 8 signature + 4 length + 4 type.
    if data[12:16] != b"IHDR" or len(data) < 24:
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return _build("image/png", width, height)


def _jpeg(data: bytes) -> ImageHeader | None:
    # Walk the segment chain to the first start-of-frame, which is the only
    # segment carrying the dimensions. Every segment is FF <marker> <2-byte
    # length>, so the chain is followed without decoding anything.
    i = 2
    end = len(data)
    while i + 9 < end:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        # Padding between segments is written as repeated FF bytes.
        if marker == 0xFF:
            i += 1
            continue
        # Standalone markers: no length field, nothing to skip.
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if length < 2:
            return None
        if marker in _JPEG_SOF_MARKERS:
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return _build("image/jpeg", width, height)
        i += 2 + length
    return None


def _webp(data: bytes) -> ImageHeader | None:
    # WebP is a RIFF container with three encodings, each storing the canvas
    # size differently.
    tag = data[12:16]
    if tag == b"VP8X" and len(data) >= 30:
        # Extended: 24-bit little-endian, stored as size-1.
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return _build("image/webp", width, height)
    if tag == b"VP8 " and len(data) >= 30:
        # Lossy: a 3-byte start code precedes the 14-bit dimensions.
        if data[23:26] != b"\x9d\x01\x2a":
            return None
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return _build("image/webp", width, height)
    if tag == b"VP8L" and len(data) >= 25:
        # Lossless: 14 bits each, packed little-endian after the signature
        # byte, both stored as size-1.
        if data[20] != 0x2F:
            return None
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return _build("image/webp", width, height)
    return None


def _gif(data: bytes) -> ImageHeader | None:
    # The logical screen descriptor follows the 6-byte signature, little-endian.
    width = int.from_bytes(data[6:8], "little")
    height = int.from_bytes(data[8:10], "little")
    return _build("image/gif", width, height)


def _build(content_type: str, width: int, height: int) -> ImageHeader | None:
    """Reject the degenerate sizes a truncated or crafted header produces."""
    if width <= 0 or height <= 0:
        return None
    return ImageHeader(content_type=content_type, width=width, height=height)
