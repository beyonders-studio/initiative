"""Version utilities for reading application version."""

from pathlib import Path


def root_file(name: str) -> Path:
    """A file at the project root, which the image copies beside the app."""
    # Docker: /app/app/core/version.py -> /app/<name>
    path = Path(__file__).parent.parent.parent / name
    if not path.exists():
        # Development: backend/app/core/version.py -> repo_root/<name>
        path = Path(__file__).parent.parent.parent.parent / name
    return path


def _read_root_file(name: str) -> str:
    """A version file at the project root, or ``"0.0.0"`` when there is none."""
    try:
        return root_file(name).read_text().strip()
    except FileNotFoundError:
        return "0.0.0"


def get_version() -> str:
    """Read version from VERSION file at project root."""
    return _read_root_file("VERSION")


def get_min_native_version() -> str:
    """Read the minimum native app version from the MIN_NATIVE_VERSION file at project root.

    This is the semver of the release in which the native shell last changed (Capacitor
    plugins or config). The OTA flow refuses a web bundle whose ``minNativeVersion`` exceeds
    the installed native app version, prompting a store/APK update instead — because a newer
    web bundle may call a native API the older shell lacks.
    """
    return _read_root_file("MIN_NATIVE_VERSION")


def get_min_desktop_version() -> str:
    """The desktop app's floor, from MIN_DESKTOP_VERSION: what ``get_min_native_version``
    is for the phone app, kept apart so a change to one app asks nobody to reinstall the
    other."""
    return _read_root_file("MIN_DESKTOP_VERSION")


def is_dev_image() -> bool:
    """Whether this is a dev image, which the dev build marks in
    IMAGE_CHANNEL. Anything else, an unmarked checkout included, is not."""
    return _read_root_file("IMAGE_CHANNEL") == "dev"


def _parts(version: str) -> tuple[int, int, int]:
    """``"0.64.3"`` -> ``(0, 64, 3)``. Anything unparseable sorts as ``0.0.0``.

    Tolerant on purpose: a version read back from a database was written by an
    older build, and a pre-release suffix ("1.2.3-rc1") should compare on the
    numbers rather than raise.
    """
    numbers: list[int] = []
    for piece in version.strip().lstrip("v").split(".")[:3]:
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return (numbers[0], numbers[1], numbers[2])


def compare_versions(left: str, right: str) -> int:
    """-1, 0 or 1 — the sign of ``left - right`` read as semver."""
    a, b = _parts(left), _parts(right)
    return (a > b) - (a < b)


__version__ = get_version()
