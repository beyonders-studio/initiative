"""Unit tests for avatar validation.

Fixtures are hand-built headers rather than encoder output: there is no image
library in the runtime (deliberately — see ``app.core.image_headers``), and
writing the bytes out documents the layout the parser depends on.
"""

import struct
import zlib

import pytest

from app.core.image_headers import ImageRejected, read_image_header, validate_image
from app.models.platform.user_avatar import AVATAR_SPEC
from app.services.platform import user_avatars as service


def png(width: int, height: int, *, pad: int = 0) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    chunk = b"IHDR" + ihdr
    out = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr))
        + chunk
        + struct.pack(">I", zlib.crc32(chunk))
    )
    return out + b"\x00" * pad


def jpeg(width: int, height: int) -> bytes:
    sof = b"\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x00" * 9
    return (
        b"\xff\xd8"
        + b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00"
        + b"\x00" * 9
        + b"\xff\xc0"
        + struct.pack(">H", len(sof) + 2)
        + sof
    )


def webp(width: int, height: int) -> bytes:
    body = (
        b"VP8 "
        + struct.pack("<I", 20)
        + b"\x00\x00\x00"
        + b"\x9d\x01\x2a"
        + struct.pack("<HH", width, height)
    )
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body


@pytest.mark.parametrize(
    "builder,expected",
    [(png, "image/png"), (jpeg, "image/jpeg"), (webp, "image/webp")],
)
def test_accepts_each_supported_format(builder, expected) -> None:
    """The recorded type is served back in a Content-Type, so it is the one the
    bytes prove rather than anything a client asserted."""
    validated = validate_image(AVATAR_SPEC, builder(256, 256))

    assert validated.content_type == expected
    assert (validated.width, validated.height) == (256, 256)


def test_digest_is_of_these_exact_bytes() -> None:
    import hashlib

    data = png(128, 128)

    assert validate_image(AVATAR_SPEC, data).sha256 == hashlib.sha256(data).hexdigest()


def test_refuses_a_gif_even_though_it_is_a_raster() -> None:
    gif = b"GIF89a" + struct.pack("<HH", 256, 256) + b"\x00" * 20

    with pytest.raises(ImageRejected):
        validate_image(AVATAR_SPEC, gif)


def test_allows_a_pixel_of_rounding_off_square() -> None:
    """A canvas resize lands on 1:1; the tolerance is for images prepared
    elsewhere, so one pixel out is not a refusal, and the allowance is a share
    of the longer side whichever side that is."""
    assert validate_image(AVATAR_SPEC, png(256, 255)).width == 256
    assert validate_image(AVATAR_SPEC, png(200, 196)).width == 200
    assert validate_image(AVATAR_SPEC, png(196, 200)).width == 196


def test_refuses_a_truncated_header() -> None:
    with pytest.raises(ImageRejected):
        validate_image(AVATAR_SPEC, png(256, 256)[:12])


def test_riff_that_is_not_webp_is_not_an_image() -> None:
    assert read_image_header(b"RIFF" + b"\x00" * 4 + b"AVI " + b"\x00" * 20) is None


def test_serving_url_carries_the_digest() -> None:
    url = service.avatar_url(7, "ab" * 32)

    assert url == f"/api/v1/users/7/avatar/{'ab' * 32}"
    assert service.is_avatar_url(url)


def test_an_external_url_is_not_one_of_ours() -> None:
    assert not service.is_avatar_url("https://idp.example/pic.png")


@pytest.mark.parametrize("value", ["", "xyz", "AB" * 32, "ab" * 31, "ab" * 33])
def test_rejects_a_malformed_digest(value: str) -> None:
    assert not service.is_valid_digest(value)
