"""The pictures a listing uses: uploaded to the marketplace, and copied into
the community that installs it.

A listing's pictures are never taken from a community. What a community stores
is its own, whoever is sharing from it, so a share reads nothing from its
storage and the publish profile drops every reference into it. A picture a
listing shows is one somebody **uploaded to the marketplace** for it: a
member's images when they share, or the files the owner uploads for a listing
of their own. Each is a new file in the marketplace's media (``media``), named
by the digest of its bytes.

Installing copies each picture the listing names into the installing
community's storage as a new upload of the member installing, and names the
copy there. That is how an owner-published listing arrives with its pictures.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.marketplace import media

__all__ = [
    "MAX_IMAGE_BYTES",
    "MAX_LISTING_IMAGES",
    "UploadedImageError",
    "copy_assets_in",
    "media_paths_in",
    "store_uploaded_image",
]

#: The largest picture somebody may upload to a listing.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
#: How many pictures a member may upload with one share.
MAX_LISTING_IMAGES = 8


class UploadedImageError(ValueError):
    """An uploaded file the marketplace will not keep as a picture."""


async def store_uploaded_image(session: AsyncSession, data: bytes) -> str:
    """Keep one uploaded picture in the marketplace's media, and return the
    path it is served from.

    Raster images only, read from the bytes rather than from what the upload
    claimed to be, and no larger than :data:`MAX_IMAGE_BYTES`.
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise UploadedImageError("image is too large")
    content_type = media.image_type_of(data)
    if content_type is None:
        raise UploadedImageError("not an image the marketplace keeps")
    return await media.store_media(session, data, content_type=content_type)


_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _walk_strings(value: Any, visit: Callable[[str], None]) -> None:
    if isinstance(value, str):
        visit(value)
    elif isinstance(value, dict):
        for child in value.values():
            _walk_strings(child, visit)
    elif isinstance(value, list):
        for child in value:
            _walk_strings(child, visit)


def _replace_strings(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, dict):
        return {
            key: _replace_strings(child, replacements) for key, child in value.items()
        }
    if isinstance(value, list):
        return [_replace_strings(child, replacements) for child in value]
    return value


def media_paths_in(envelope: Any) -> list[str]:
    """Every catalogue media path an envelope names, first-seen order."""
    found: list[str] = []

    def visit(value: str) -> None:
        if media.digest_of(value) is not None and value not in found:
            found.append(value)

    _walk_strings(envelope, visit)
    return found


async def copy_assets_in(
    session: AsyncSession,
    *,
    envelope: dict[str, Any],
    guild_id: int,
    user_id: int,
    initiative_id: int,
) -> dict[str, Any]:
    """``envelope`` with each picture it names copied into this guild's
    storage as a new upload of ``user_id``'s, kept for ``initiative_id``, and
    named there.

    The copies count against the guild's storage like any upload, and the
    whole install is refused if they do not fit. A path naming nothing the
    catalogue keeps is left as it is; the importer treats the picture as
    missing.
    """
    from app.db import session as db_session
    from app.services.tenant.attachments import (
        enforce_storage_quota,
        new_upload_filename,
        store_upload,
    )

    paths = media_paths_in(envelope)
    if not paths:
        return envelope

    # The catalogue's media is read on the system engine: a guild-routed
    # session holds no grant on it.
    kept: dict[str, tuple[bytes, str]] = {}
    async with db_session.SystemSessionLocal() as catalog:
        for path in paths:
            digest = media.digest_of(path)
            found = await media.read_media(catalog, digest) if digest else None
            if found is not None:
                kept[path] = found

    await enforce_storage_quota(
        session,
        guild_id=guild_id,
        incoming_bytes=sum(len(data) for data, _ in kept.values()),
    )

    to_url: dict[str, str] = {}
    for path, (data, content_type) in kept.items():
        key = new_upload_filename(_EXTENSIONS.get(content_type, ""))
        to_url[path] = await store_upload(
            session,
            guild_id=guild_id,
            filename=key,
            data=data,
            content_type=content_type,
            created_by=user_id,
            initiative_id=initiative_id,
        )
    await session.flush()
    return _replace_strings(envelope, to_url)
