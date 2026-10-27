"""The ``thumbnails`` sweep's visit, drawing through the real image worker."""

from __future__ import annotations

import io

import pytest
from PIL import Image
from sqlalchemy import func
from sqlalchemy.orm import undefer
from sqlmodel import select

from app.core.config import settings
from app.models.tenant.event_outbox import EventOutbox
from app.models.tenant.file import File, FileVersion
from app.models.tenant.upload import Upload
from app.services.storage import get_guild_storage
from app.services.tenant import attachments, thumbnails
from app.testing import (
    create_file,
    create_guild,
    create_initiative,
    create_user,
    route_session_to_guild,
)


def _png(size: tuple[int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (30, 90, 160)).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def stored(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))
    yield
    thumbnails.shutdown()


async def _picture(session, data: bytes):
    """A community holding one uploaded picture, stored and pending."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    key = attachments.new_upload_filename(".png")
    get_guild_storage(guild.id).write(key, data, content_type="image/png")
    file = await create_file(
        session,
        initiative,
        user,
        file_url=f"/uploads/{guild.id}/{key}",
        file_content_type="image/png",
    )
    await route_session_to_guild(session, guild.id)
    return guild, file


async def _version(session, file) -> FileVersion:
    return (
        await session.exec(
            select(FileVersion)
            .where(FileVersion.file_id == file.id)
            .execution_options(populate_existing=True)
        )
    ).one()


async def _changes(session) -> int:
    return (await session.exec(select(func.count()).select_from(EventOutbox))).one()


async def test_a_large_picture_gets_a_thumbnail_no_limit_counts(session, stored):
    guild, file = await _picture(session, _png((1600, 1200)))
    assert (await _version(session, file)).thumbnail_state == "pending"
    usage = await attachments.get_guild_storage_usage(guild.id)
    changes = await _changes(session)

    await thumbnails.draw_pending(session, guild.id)

    version = await _version(session, file)
    assert version.thumbnail_state == "ready"
    name = version.thumbnail_url.rsplit("/", 1)[-1]
    assert name.startswith(attachments.THUMBNAIL_PREFIX)
    upload = (await session.exec(select(Upload).where(Upload.filename == name))).one()
    assert upload.content_type == "image/webp"
    assert upload.initiative_id == file.initiative_id
    with Image.open(get_guild_storage(guild.id).open_readable(name).path) as drawn:
        assert max(drawn.size) == thumbnails.EDGE
    # Stored, but counted toward no limit, and news to nobody.
    assert await attachments.get_guild_storage_usage(guild.id) == usage
    assert await _changes(session) == changes
    assert await session.scalar(thumbnails.next_due(None)) is None


async def test_an_archived_picture_gets_its_thumbnail_too(session, stored):
    """Archived content takes no writes, but a thumbnail of what is already
    there is not one."""
    from datetime import datetime, timezone

    guild, file = await _picture(session, _png((1600, 1200)))
    archived = (await session.exec(select(File).where(File.id == file.id))).one()
    archived.archived_at = datetime.now(timezone.utc)
    session.add(archived)
    await session.commit()

    await thumbnails.draw_pending(session, guild.id)

    assert (await _version(session, file)).thumbnail_state == "ready"


async def test_a_small_picture_is_its_own_thumbnail(session, stored):
    guild, file = await _picture(session, _png((200, 120)))

    await thumbnails.draw_pending(session, guild.id)

    version = await _version(session, file)
    assert (version.thumbnail_state, version.thumbnail_url) == (
        "ready",
        version.file_url,
    )


async def test_a_picture_that_cannot_be_drawn_fails(session, stored):
    guild, file = await _picture(session, b"\x89PNG\r\n\x1a\n" + b"broken" * 20)
    assert await session.scalar(thumbnails.next_due(None)) is not None

    await thumbnails.draw_pending(session, guild.id)

    version = await _version(session, file)
    assert (version.thumbnail_state, version.thumbnail_url) == ("failed", None)


async def test_a_purged_file_takes_its_thumbnail(session, stored):
    guild, file = await _picture(session, _png((1600, 1200)))
    await thumbnails.draw_pending(session, guild.id)
    version = await _version(session, file)
    thumbnail = attachments.upload_names([version.thumbnail_url])

    doomed = (
        await session.exec(
            select(File).where(File.id == file.id).options(undefer(File.content))
        )
    ).one()
    released = await attachments.purge_file_uploads(session, [doomed])

    assert thumbnail <= released
