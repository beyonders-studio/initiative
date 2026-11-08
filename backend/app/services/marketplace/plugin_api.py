"""The plug-in API contract this build serves, and whether a plug-in can run on it.

A plug-in shares one thing with Initiative: a version of the plug-in SDK. The
SDK publishes the plug-in API's OpenAPI document at its own version, and a
plug-in's client is generated from that document, never from an Initiative
release. So the **contract version is the SDK's version**, and what this build
serves is the SDK version it vendors (``backend/vendor/plugin-kit/KIT_VERSION``):
:data:`PLUGIN_API_VERSION`, which is the plug-in document's ``info.version``.

A listing may say which contract it needs, as ``min_plugin_api``
(``MAJOR.MINOR``). A build serving ``S`` runs a plug-in needing ``N`` when they
share a major and ``S`` is at least ``N``'s minor: a minor only adds, and a
major removes or changes. A listing that says nothing runs anywhere.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.marketplace import contract

__all__ = [
    "MAX_MIN_PLUGIN_API",
    "PLUGIN_API_VERSION",
    "check_min_plugin_api",
    "serves_plugin_api",
]

#: The plug-in API contract this build serves: the SDK version it vendors.
PLUGIN_API_VERSION = contract.KIT_VERSION

#: The shape of ``min_plugin_api``, as the SDK's manifest schema states it.
_MIN_PLUGIN_API = r"[0-9]+\.[0-9]+"

#: The longest ``min_plugin_api`` stored; the column holds as much.
MAX_MIN_PLUGIN_API = 32


def check_min_plugin_api(value: Any) -> str | None:
    """``value`` as a stored ``min_plugin_api``, ``None`` when it is absent.
    Raises ``ValueError`` when it is not ``MAJOR.MINOR``."""
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > MAX_MIN_PLUGIN_API
        or not re.fullmatch(_MIN_PLUGIN_API, value)
    ):
        raise ValueError(
            f"min_plugin_api must be MAJOR.MINOR, such as '4.1' (got {value!r})"
        )
    return value


def _major_minor(version: str) -> tuple[int, int]:
    """The major and minor of ``MAJOR.MINOR[.PATCH][-pre][+build]``."""
    head = version.split("-", 1)[0].split("+", 1)[0]
    major, minor, *_ = head.split(".")
    return int(major), int(minor)


def serves_plugin_api(
    min_plugin_api: str | None, served: str = PLUGIN_API_VERSION
) -> bool:
    """Whether a server serving contract ``served`` can run a plug-in that needs
    ``min_plugin_api``. A value that cannot be read is not one it can run."""
    if not min_plugin_api:
        return True
    try:
        needed = _major_minor(check_min_plugin_api(min_plugin_api) or "")
        serving = _major_minor(served)
    except ValueError:
        return False
    return serving[0] == needed[0] and serving >= needed
