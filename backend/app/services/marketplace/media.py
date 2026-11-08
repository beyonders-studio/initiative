"""The marketplace's own media: the pictures its listings use.

Every picture a listing names is a file here, in ``marketplace_media``, keyed
by the SHA-256 of its bytes and served from one same-origin path. Two writers
put them here: the registry refresh, which copies a signed index's images, and
a member's share, which copies the pictures an item uses out of its community.
Either way the file is the marketplace's, not a view of somewhere else's; both
go through :func:`store_media`, so the same bytes are stored once.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import API_V1_STR
from app.models.platform.marketplace_registry import MarketplaceMedia

__all__ = [
    "IMAGE_TYPES",
    "MEDIA_URL_PREFIX",
    "digest_of",
    "image_type_of",
    "is_image_of_type",
    "media_path",
    "read_media",
    "store_media",
]

#: Where kept images are served from. Same-origin by construction, and
#: addressed by the digest of the bytes, so the URL is stable and cacheable.
MEDIA_URL_PREFIX = f"{API_V1_STR}/marketplace/media/"

#: Image types the catalogue keeps, each with the leading bytes a file of that
#: type starts with. Raster formats only — an image renders in a plain
#: ``<img>`` and carries no document of its own.
_IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    # WebP is a RIFF container; the format tag sits at offset 8 and is checked
    # separately below.
    "image/webp": (b"RIFF",),
}

IMAGE_TYPES: frozenset[str] = frozenset(_IMAGE_MAGIC)

_HEX_DIGITS = frozenset("0123456789abcdef")
_DIGEST_LENGTH = 64


def media_path(digest: str) -> str:
    """The same-origin path a kept image is served from."""
    return f"{MEDIA_URL_PREFIX}{digest}"


def digest_of(path: object) -> str | None:
    """The digest a media path names, or ``None`` when it names none."""
    if not isinstance(path, str) or not path.startswith(MEDIA_URL_PREFIX):
        return None
    digest = path[len(MEDIA_URL_PREFIX) :]
    if len(digest) != _DIGEST_LENGTH or any(c not in _HEX_DIGITS for c in digest):
        return None
    return digest


def is_image_of_type(data: bytes, content_type: object) -> bool:
    """Whether the bytes are an image of the named type."""
    if not isinstance(content_type, str) or content_type not in _IMAGE_MAGIC:
        return False
    if not any(data.startswith(prefix) for prefix in _IMAGE_MAGIC[content_type]):
        return False
    return content_type != "image/webp" or data[8:12] == b"WEBP"


def image_type_of(data: bytes) -> str | None:
    """The image type the bytes are, read from the bytes, or ``None``."""
    for content_type in _IMAGE_MAGIC:
        if is_image_of_type(data, content_type):
            return content_type
    return None


async def store_media(
    session: AsyncSession,
    data: bytes,
    *,
    content_type: str,
    source_url: str | None = None,
    now: datetime | None = None,
) -> str:
    """Keep ``data`` and return the path it is served from.

    The caller has already checked it is an image of ``content_type``. Keyed
    on the digest, so bytes already kept are not kept twice.
    """
    digest = hashlib.sha256(data).hexdigest()
    existing = (
        await session.exec(
            select(MarketplaceMedia.id).where(MarketplaceMedia.sha256 == digest)
        )
    ).first()
    if existing is None:
        session.add(
            MarketplaceMedia(
                sha256=digest,
                content_type=content_type,
                byte_size=len(data),
                data=data,
                source_url=(source_url or "")[:2000] or None,
                created_at=now or datetime.now(UTC),
            )
        )
        await session.flush()
    return media_path(digest)


async def read_media(session: AsyncSession, digest: str) -> tuple[bytes, str] | None:
    """The bytes kept under ``digest`` and their type, or ``None``."""
    row = (
        await session.exec(
            select(MarketplaceMedia).where(MarketplaceMedia.sha256 == digest)
        )
    ).first()
    if row is None:
        return None
    return bytes(row.data), row.content_type
