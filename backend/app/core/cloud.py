"""Initiative Cloud, the hosted service, as a server knows it.

Its address is the ``CLOUD_ORIGIN`` file at the project root. The app's build
reads the same file (``frontend/vite.config.ts``), so the address is written
once.
"""

from __future__ import annotations

from functools import cache

from app.core.config import settings
from app.core.version import root_file


@cache
def _cloud_origin() -> str:
    return root_file("CLOUD_ORIGIN").read_text().strip()


def is_cloud() -> bool:
    """Whether this server is Initiative Cloud: its ``APP_URL`` has Cloud's
    origin."""
    return settings.app_origin == _cloud_origin()
