"""Drawing a picture smaller, in a worker process, for :mod:`worker_host`.

The host loads this module by path and calls :func:`start` with ``<edge>
<pixels> <address space bytes>``; this imports the standard library and
Pillow and nothing of Initiative.

A request is ``{"path", "format"}``: a stored picture's path on disk and the
one Pillow format it may be opened as. The answer is ``{"thumbnail",
"width", "height"}`` (a WebP, base64), ``{"original": true}`` for a picture
already no larger than the edge, or ``{"error"}`` for bytes Pillow will not
draw. A picture with more than ``<pixels>`` pixels is refused before it is
decoded, and the process's address space is bounded where the platform
allows it; a decode that runs out of memory is answered with
``"replace": true``, and the worker exits.
"""

from __future__ import annotations

import base64
import io
import warnings
from typing import Any, Callable

from PIL import Image, ImageOps


def answer(request: dict[str, Any], edge: int) -> dict[str, Any]:
    """What one request answers: a thumbnail, the original, or an error."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(request["path"], formats=[request["format"]]) as opened:
                picture = ImageOps.exif_transpose(opened) or opened
                if max(picture.size) <= edge:
                    return {"original": True}
                picture.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                # WebP takes RGB or RGBA; palette and greyscale pictures are
                # converted, and an animation keeps its first frame.
                if picture.mode not in ("RGB", "RGBA"):
                    picture = picture.convert(
                        "RGBA" if "A" in picture.getbands() else "RGB"
                    )
                out = io.BytesIO()
                picture.save(out, format="WEBP", quality=80, method=4)
                width, height = picture.size
    except MemoryError:
        return {"error": "the picture ran out of memory", "replace": True}
    except Exception as error:  # noqa: BLE001 - every decode failure is one answer
        return {"error": str(error) or type(error).__name__}
    return {
        "thumbnail": base64.b64encode(out.getvalue()).decode("ascii"),
        "width": width,
        "height": height,
    }


def start(arguments: list[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Set the process's bounds, and answer requests within them."""
    edge, pixels, address_space = (int(value) for value in arguments)
    Image.MAX_IMAGE_PIXELS = pixels
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    except (ImportError, ValueError, OSError):
        pass
    return lambda request: answer(request, edge)
