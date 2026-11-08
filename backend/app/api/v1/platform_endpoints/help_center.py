"""The help center's search index, for the app's Help panel.

The image builds it from the help center's pages and puts it beside
``CHANGELOG.md`` (the Dockerfile's ``help-index`` stage,
``scripts/build_help_index.py``). Unauthenticated, like the help center
itself. A checkout that has not built one serves an empty index.
"""

from functools import cache
from pathlib import Path

from fastapi import APIRouter, Response

from app.schemas.platform.help_center import HelpIndex

router = APIRouter()

#: Docker: /app/app/api/v1/platform_endpoints/help_center.py -> /app/help-index.json.
#: A checkout: backend/help-index.json, written only by a local build.
INDEX_PATH = Path(__file__).resolve().parents[4] / "help-index.json"

#: The index changes only with the image.
_CACHE_CONTROL = {"Cache-Control": "public, max-age=3600"}


@cache
def _served() -> bytes:
    """The index as served: read, checked and encoded once per process."""
    try:
        raw = INDEX_PATH.read_bytes()
    except FileNotFoundError:
        return HelpIndex(items=[]).model_dump_json().encode()
    return HelpIndex.model_validate_json(raw).model_dump_json().encode()


@router.get("/index", response_model=HelpIndex)
def read_help_index() -> Response:
    """Every English page and heading of the help center, down to level 3:
    its title, where it sits, its address from the help center's root, and the
    start of its text. Empty where this server was not built with one."""
    return Response(
        content=_served(), media_type="application/json", headers=_CACHE_CONTROL
    )
