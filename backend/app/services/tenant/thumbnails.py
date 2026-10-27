"""Thumbnails of uploaded pictures, drawn by the ``thumbnails`` sweep.

A new version of a picture the app draws smaller (a type with a
``picture_format``) is stored at once and marked ``pending``
(``file_versions._new_version``). The sweep, armed by that write, takes
pending versions one at a time and asks an image worker
(:mod:`app.services.image_worker`) for a thumbnail: decoding happens in that
process, never in the server's. The thumbnail is stored as an upload of its
own, under :data:`attachments.THUMBNAIL_PREFIX`, which no storage limit counts
and no backup carries. A picture already small enough is its own thumbnail,
and bytes the worker cannot draw leave the version ``failed``. A version
drawn either way keeps the picture's size, turned upright, which a wall lays
it out by.

A thumbnail goes with its version, as its file does: it is one of the columns
an upload is shown from.
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import exists, func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.file_types import spec_of, type_of_media
from app.models.tenant.file import File, FileVersion
from app.services.storage import get_guild_storage
from app.services.tenant import attachments
from app.services.worker_pool import Pool, PoolError

logger = logging.getLogger(__name__)

#: The longest side of a thumbnail: a card's width at 2x.
EDGE = 640
#: The most pixels a picture may have before the worker refuses to decode it.
#: Pillow's own default, stated so it is a decision.
MAX_PIXELS = 89_478_485
#: How long one picture may take.
TIME_MS = 20_000
#: How long a visit keeps drawing before it leaves the rest to the next one.
VISIT_SECONDS = 30

_HANDLER = Path(__file__).parent.parent / "image_worker.py"
_IDLE_SECONDS = 300
_ADDRESS_SPACE_BYTES = 1536 * 1024 * 1024

_pool: Optional[Pool] = None
_pool_lock = threading.Lock()


def _the_pool() -> Pool:
    global _pool
    with _pool_lock:
        if _pool is None:
            # The app's lifespan stops it; a process that has none stops it
            # on its way out.
            atexit.register(shutdown)
            _pool = Pool(
                handler=_HANDLER,
                arguments=[str(EDGE), str(MAX_PIXELS), str(_ADDRESS_SPACE_BYTES)],
                size=1,
                time_ms=TIME_MS,
                idle_seconds=_IDLE_SECONDS,
            )
        return _pool


def shutdown() -> None:
    """Stop the pool's worker; the next thumbnail starts a new pool."""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown()


def _draw(guild_id: int, key: str, picture_format: str) -> dict[str, Any]:
    """The worker's answer for the stored picture ``key``. Blocks; the worker
    reads the picture from disk, so one kept elsewhere is copied there first,
    within the time drawing it may take."""
    blob = get_guild_storage(guild_id).open_readable(key)
    if blob is None:
        return {"error": "the picture is not stored"}
    request = {"format": picture_format}
    if blob.path is not None:
        return _the_pool().ask({**request, "path": str(blob.path)})
    deadline = time.monotonic() + TIME_MS / 1000
    with tempfile.NamedTemporaryFile() as copy:
        for chunk in blob.stream or ():
            if time.monotonic() > deadline:
                return {"error": "the picture took too long to fetch"}
            copy.write(chunk)
        copy.flush()
        return _the_pool().ask({**request, "path": copy.name})


async def _keep(
    session: AsyncSession,
    guild_id: int,
    version: FileVersion,
    reply: dict[str, Any],
    initiative_id: int,
) -> None:
    """Store the worker's thumbnail as ``version``'s."""
    version.thumbnail_url = await attachments.store_upload(
        session,
        guild_id=guild_id,
        filename=attachments.new_upload_filename(
            ".webp", prefix=attachments.THUMBNAIL_PREFIX
        ),
        data=base64.b64decode(reply["thumbnail"]),
        content_type="image/webp",
        created_by=None,
        initiative_id=initiative_id,
    )
    version.thumbnail_state = "ready"


async def take_frame(
    session: AsyncSession,
    guild_id: int,
    version: FileVersion,
    initiative_id: int,
    data: bytes,
    picture_format: str,
) -> bool:
    """Make a frame a browser drew of a video ``version``'s thumbnail, drawn
    again by the worker whatever it is, as an upload would be. ``False`` for
    bytes the worker will not draw; the caller commits."""

    def draw() -> dict[str, Any]:
        with tempfile.NamedTemporaryFile() as frame:
            frame.write(data)
            frame.flush()
            return _the_pool().ask(
                {"path": frame.name, "format": picture_format, "always": True}
            )

    try:
        reply = await asyncio.to_thread(draw)
    except PoolError as exc:
        reply = {"error": str(exc)}
    if "thumbnail" not in reply:
        logger.info("frame_refused version=%s: %s", version.id, reply.get("error"))
        return False
    await _keep(session, guild_id, version, reply, initiative_id)
    session.add(version)
    return True


async def _draw_one(session: AsyncSession, guild_id: int) -> bool:
    """Draw the next pending thumbnail and commit it; ``False`` when none is
    pending."""
    row = (
        await session.exec(
            select(FileVersion, File.initiative_id)
            .join(File, col(File.id) == FileVersion.file_id)
            .where(FileVersion.thumbnail_state == "pending")
            .order_by(col(FileVersion.id).asc())
            .limit(1)
            .with_for_update(of=FileVersion, skip_locked=True)
        )
    ).first()
    if row is None:
        return False
    version, initiative_id = row
    picture_format = spec_of(type_of_media(version.file_content_type)).picture_format
    key = next(iter(attachments.upload_names([version.file_url])), None)
    reply: dict[str, Any]
    try:
        if picture_format is None or key is None:
            raise PoolError("not a picture the app draws")
        reply = await asyncio.to_thread(_draw, guild_id, key, picture_format)
    except Exception as exc:  # noqa: BLE001 - a picture that cannot be drawn fails
        reply = {"error": str(exc) or type(exc).__name__}
    if "thumbnail" in reply:
        await _keep(session, guild_id, version, reply, initiative_id)
    elif reply.get("original"):
        version.thumbnail_url = version.file_url
        version.thumbnail_state = "ready"
    else:
        logger.info("thumbnail_failed version=%s: %s", version.id, reply.get("error"))
        version.thumbnail_state = "failed"
    if version.thumbnail_state == "ready":
        version.width, version.height = reply["width"], reply["height"]
    session.add(version)
    await session.commit()
    return True


async def draw_pending(session: AsyncSession, guild_id: int) -> None:
    """The sweep's visit: draw pending thumbnails, one commit each, for up to
    :data:`VISIT_SECONDS`; the next visit takes the rest."""
    deadline = time.monotonic() + VISIT_SECONDS
    while time.monotonic() < deadline and await _draw_one(session, guild_id):
        pass


def next_due(_now: Any) -> Any:
    """Now, while a thumbnail is pending."""
    return select(func.now()).where(
        exists().where(FileVersion.thumbnail_state == "pending")
    )
