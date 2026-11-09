"""Native (Capacitor) over-the-air bundle endpoints.

Each Docker image bundles the Capacitor-flavored web build (a zip with ``index.html`` at
its root) under ``/app/ota`` so the native app can download the web bundle that matches the
backend it is talking to. The native app polls ``/native/bundle/manifest`` and, when the
served version differs from the bundle it is running, downloads ``/native/bundle/download``
and swaps it in via ``@capgo/capacitor-updater`` (manual mode).

See ``backend/app/main.py`` for the analogous static/upload ``FileResponse`` patterns.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import API_V1_STR
from app.core.messages import NativeMessages
from app.core.version import __version__

router = APIRouter()

# Docker layout: /app/app/api/v1/endpoints/native.py -> parents[4] == /app
# The Dockerfile copies the OTA artifacts to /app/ota (see Dockerfile stage 2).
# In a local dev checkout this directory does not exist, so the endpoints 404 — the OTA
# flow is only exercised against a built image.
_OTA_DIR = Path(__file__).resolve().parents[4] / "ota"
_BUNDLE_PATH = _OTA_DIR / "bundle.zip"
_STATEMENT_PATH = _OTA_DIR / "statement.json"
_SIGNATURE_PATH = _OTA_DIR / "statement.sig"


@router.get("/native/bundle/manifest")
def get_bundle_manifest() -> dict[str, object]:
    """Describe the OTA bundle this backend serves.

    Returns the bundle ``version`` (equal to the app version) and a ``url`` the client
    joins to its server origin to download the zip. A release image also carries
    ``statement`` — the bundle's version, sha256 digest and app floors as JSON — and its
    ``signature``, made with the project's release key when the image was built. The app
    installs only a bundle whose statement verifies against a key it was built with, and
    refuses one whose floor is above its installed app (prompting a store update).
    """
    if not _BUNDLE_PATH.is_file():
        raise HTTPException(
            status_code=404, detail=NativeMessages.OTA_BUNDLE_NOT_AVAILABLE
        )
    manifest: dict[str, object] = {
        "version": __version__,
        "url": f"{API_V1_STR}/native/bundle/download",
    }
    if _STATEMENT_PATH.is_file() and _SIGNATURE_PATH.is_file():
        manifest["statement"] = _STATEMENT_PATH.read_text()
        manifest["signature"] = _SIGNATURE_PATH.read_text().strip()
    return manifest


@router.get("/native/bundle/download")
def download_bundle() -> FileResponse:
    """Serve the Capacitor web bundle zip (immutable per version)."""
    if not _BUNDLE_PATH.is_file():
        raise HTTPException(
            status_code=404, detail=NativeMessages.OTA_BUNDLE_NOT_AVAILABLE
        )
    return FileResponse(
        _BUNDLE_PATH,
        media_type="application/zip",
        filename=f"initiative-{__version__}.zip",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
