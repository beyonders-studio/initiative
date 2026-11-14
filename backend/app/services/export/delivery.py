"""Where a large archive goes instead of down an HTTP connection.

An export the app serves is read back through this process for as long as the
client's connection lasts, which is fine for a report and not fine for a whole
community. Past ``EXPORT_MAX_DOWNLOAD_BYTES`` the worker writes the archive to
a **destination** the operator configured and records where it landed; the app
never holds it and never serves it.

The destination is a directory on this host — ``EXPORT_DESTINATION_DIR`` — and
deliberately nothing else. Any mount the operator can write to works, so a NAS
share or an encrypted volume is a destination without the deployment needing
credentials for anything, an account anywhere, or a route to the internet. It
is operator-global for the same reason the mail sender is: it is the
deployment's own storage, and a community administrator should not be holding
a path into it.

Unset is the default, and means delivery is not available: an archive over the
download bound is refused rather than built with nowhere to put it.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings

__all__ = ["deliver", "destination_root", "is_configured"]


def destination_root() -> Path | None:
    """The configured destination directory, or ``None`` when unset."""
    configured = (settings.EXPORT_DESTINATION_DIR or "").strip()
    return Path(configured) if configured else None


def is_configured() -> bool:
    return destination_root() is not None


def deliver(source: Path, *, guild_id: int, filename: str) -> str:
    """Move a finished archive into the destination and return where it went.

    Laid out one directory per community (``<root>/guild_<id>/<filename>``),
    matching how the storage backends already namespace a guild's blobs, so an
    operator sweeping up one community's exports has one directory to look in.

    ``filename`` is built by the engine from the source name and the date, not
    from user text. The basename is taken anyway, so a name can only ever
    land directly in the community's own directory.

    The returned string is recorded on the job as ``destination_ref``. It is a
    path on the server, shown to administrators so they know where to collect
    the archive; it is never a URL and the app never serves it.
    """
    import shutil

    root = destination_root()
    if root is None:
        raise RuntimeError("export destination is not configured")
    target_dir = root / f"guild_{guild_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / Path(filename).name
    # copy then unlink rather than move: the source is a temp file that may be
    # on a different filesystem from the destination mount.
    shutil.copyfile(source, target)
    return str(target)
