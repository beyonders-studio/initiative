"""Storing, serving and removing the picture on a user's profile.

The bytes live in ``public.user_avatars`` and are addressed by their own
digest, so a profile payload carries a URL rather than the image and the
browser fetches each picture exactly once.

Validation is header-only — format and dimensions are read out of the first
bytes and the body is capped before it is buffered — so nothing here decodes an
image. ``app.core.image_headers`` explains why.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from app.core.config import API_V1_STR, PLUGIN_SERVER_URL
from app.core.image_headers import ImageRejected, ValidatedImage, validate_image
from app.core.messages import ImageMessages, UserMessages
from app.models.platform.user_avatar import AVATAR_SPEC, UserAvatar

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user import User

#: Where an avatar is served from. Same-origin by construction and addressed by
#: the digest of the bytes, so the URL is stable and cacheable forever.
AVATAR_URL_PREFIX = f"{API_V1_STR}/users/"

_HEX_DIGITS = frozenset("0123456789abcdef")
_DIGEST_LENGTH = 64


#: The profile picture's own wording for the refusals ``validate_image`` names.
AVATAR_REJECTIONS: dict[str, str] = {
    ImageMessages.IMAGE_INVALID: UserMessages.AVATAR_INVALID_IMAGE,
    ImageMessages.IMAGE_WRONG_SIZE: UserMessages.AVATAR_TOO_LARGE_DIMENSIONS,
    ImageMessages.IMAGE_WRONG_RATIO: UserMessages.AVATAR_NOT_SQUARE,
}


def validate_avatar(data: bytes) -> ValidatedImage:
    """Hold ``data`` to the profile-picture spec, refusing in the picture's
    own wording."""
    try:
        return validate_image(AVATAR_SPEC, data)
    except ImageRejected as rejected:
        raise ImageRejected(
            AVATAR_REJECTIONS.get(rejected.code, rejected.code)
        ) from None


def avatar_url(user_id: int, sha256: str) -> str:
    """The serving path for one stored avatar."""
    return f"{AVATAR_URL_PREFIX}{user_id}/avatar/{sha256}"


def uploaded_digest(user_id: int, url: str | None) -> str | None:
    """The digest of ``user_id``'s uploaded picture when ``url`` serves it, or
    ``None`` for a picture hosted somewhere else, or none."""
    digest = (url or "").removeprefix(avatar_url(user_id, ""))
    return digest if digest != url and is_valid_digest(digest) else None


def member_avatar_url(person: str, sha256: str) -> str:
    """Where an installed plug-in is served a member's uploaded picture: under the
    plug-in API, by the install's ``person`` reference rather than the row id."""
    return f"{PLUGIN_SERVER_URL}/members/{person}/avatar/{sha256}"


def is_avatar_url(value: str) -> bool:
    """Whether ``value`` is a path this API serves rather than an external one.

    The write side of ``avatar_url`` means "a picture hosted somewhere else", so
    a read payload handed back unchanged must not be stored as though it were.
    """
    return value.startswith(AVATAR_URL_PREFIX)


def is_valid_digest(value: str) -> bool:
    return len(value) == _DIGEST_LENGTH and all(c in _HEX_DIGITS for c in value)


async def get_avatar(session: AsyncSession, *, user_id: int) -> UserAvatar | None:
    return (
        await session.exec(select(UserAvatar).where(UserAvatar.user_id == user_id))
    ).first()


async def store_avatar(
    session: AsyncSession, *, user: User, avatar: ValidatedImage
) -> str:
    """Write ``avatar`` as the user's picture, replacing any it had.

    One row per user, so a replacement overwrites in place and there is never
    an orphan set of bytes to sweep. Returns the stored digest.

    ``users.avatar_url`` is set to the serving path in the same transaction.
    That column already meant "where this user's picture is", and an uploaded
    picture and a linked external one were already alternatives — so recording
    ours there keeps every payload that carries a user able to name the image
    without a second query, and leaves exactly one field for a client to read.
    """
    # Upsert rather than read-then-write: the row is keyed by user alone, so
    # two uploads landing together (a double-click, two tabs) would otherwise
    # both find nothing and both insert. Last writer wins, which is what
    # "replace my picture" means.
    values = {
        "user_id": user.id,
        "sha256": avatar.sha256,
        "content_type": avatar.content_type,
        "byte_size": avatar.byte_size,
        "width": avatar.width,
        "height": avatar.height,
        "data": avatar.data,
        "created_at": datetime.now(UTC),
    }
    statement = pg_insert(UserAvatar).values(**values)
    await session.exec(
        statement.on_conflict_do_update(
            index_elements=[UserAvatar.user_id],
            set_={k: v for k, v in values.items() if k != "user_id"},
        )
    )
    user.avatar_url = avatar_url(user.id, avatar.sha256)
    session.add(user)
    await session.flush()
    return values["sha256"]


async def delete_avatar(
    session: AsyncSession, *, user_id: int, user: User | None = None
) -> bool:
    """Remove the user's picture. True when there was one.

    The bytes are destroyed rather than soft-deleted: this is also the
    moderation path, and retaining the offending image would defeat it.

    Clears ``users.avatar_url`` when it points at the row being removed, so the
    pair cannot drift into naming bytes that are gone. An externally hosted
    picture is left alone — it is a different thing, and callers that mean to
    take that down as well say so themselves.
    """
    result = await session.exec(delete(UserAvatar).where(UserAvatar.user_id == user_id))
    if user is not None and user.avatar_url and is_avatar_url(user.avatar_url):
        user.avatar_url = None
        session.add(user)
    return bool(result.rowcount)
