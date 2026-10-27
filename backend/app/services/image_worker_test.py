"""The image worker's answers, asked in this process."""

from __future__ import annotations

import base64
import io

from PIL import Image

from app.services.image_worker import answer


def _picture(tmp_path, size: tuple[int, int], *, format: str = "PNG") -> str:
    path = tmp_path / f"picture.{format.lower()}"
    Image.new("RGB", size, (200, 40, 40)).save(path, format=format)
    return str(path)


def test_a_large_picture_is_drawn_to_the_edge(tmp_path):
    reply = answer({"path": _picture(tmp_path, (1600, 800)), "format": "PNG"}, 640)

    thumbnail = Image.open(io.BytesIO(base64.b64decode(reply["thumbnail"])))
    assert thumbnail.format == "WEBP"
    assert thumbnail.size == (640, 320) == (reply["width"], reply["height"])


def test_a_transparent_palette_picture_stays_transparent(tmp_path):
    path = tmp_path / "clear.png"
    picture = Image.new("P", (1000, 1000), 0)
    picture.putpalette([0, 0, 0, 255, 0, 0])
    picture.save(path, format="PNG", transparency=0)

    reply = answer({"path": str(path), "format": "PNG"}, 640)

    thumbnail = Image.open(io.BytesIO(base64.b64decode(reply["thumbnail"])))
    assert thumbnail.mode == "RGBA"
    assert thumbnail.getpixel((10, 10))[3] == 0


def test_a_small_picture_is_its_own_thumbnail(tmp_path):
    reply = answer({"path": _picture(tmp_path, (300, 200)), "format": "PNG"}, 640)

    assert reply == {"original": True}


def test_a_picture_opens_only_as_its_own_format(tmp_path):
    reply = answer({"path": _picture(tmp_path, (900, 900)), "format": "JPEG"}, 640)

    assert "error" in reply


def test_a_picture_past_the_pixel_cap_is_not_decoded(tmp_path, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10_000)

    reply = answer({"path": _picture(tmp_path, (900, 900)), "format": "PNG"}, 640)

    assert "error" in reply


def test_bytes_that_are_not_a_picture_are_an_error(tmp_path):
    path = tmp_path / "broken.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"not a picture" * 10)

    assert "error" in answer({"path": str(path), "format": "PNG"}, 640)


def test_always_draws_even_a_small_picture(tmp_path):
    path = _picture(tmp_path, (300, 200))

    reply = answer({"path": path, "format": "PNG", "always": True}, 640)

    assert (reply["width"], reply["height"]) == (300, 200)
