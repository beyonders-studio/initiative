"""What the announcements service decides: live, for whom, and already dealt with."""

from __future__ import annotations

import asyncio
import struct
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import builtin_announcements as builtins_module
from app.core.builtin_announcements import BuiltinAnnouncement
from app.models.platform.announcement import (
    AnnouncementAudienceAccounts,
    AnnouncementCategory,
    AnnouncementImage,
    AnnouncementReadReceipt,
)
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import UserRole
from app.schemas.platform.announcement import (
    AnnouncementSection,
    AnnouncementWrite,
)
from app.services.platform import announcements as service
from app.services.platform import app_settings as app_settings_service
from app.testing.factories import create_guild, create_guild_membership, create_user
from app.testing.notices import drain_notices


@pytest.fixture(autouse=True)
def _no_shipped_builtins(monkeypatch):
    """Start every test from an empty builtin registry.

    What this build ships changes with each release; a suite that asserted on
    "no announcements" would start failing the day a notice was added. Tests
    that want a builtin patch one in themselves.
    """
    monkeypatch.setattr(builtins_module, "BUILTIN_ANNOUNCEMENTS", ())
    monkeypatch.setattr(service, "BUILTIN_ANNOUNCEMENTS", ())


def _png(width: int = 8, height: int = 8, padding: int = 0) -> bytes:
    """A PNG whose header states these dimensions. Nothing decodes the body."""
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        + b"\x00" * padding
    )


def _write(**overrides) -> AnnouncementWrite:
    payload = {
        "title": "Board view is new",
        "category": AnnouncementCategory.feature,
        "sections": [AnnouncementSection(heading="Look", body="At this")],
        "published_at": datetime.now(UTC) - timedelta(minutes=1),
    }
    payload.update(overrides)
    return AnnouncementWrite(**payload)


async def _publish(session, author, **overrides):
    announcement = await service.create(session, payload=_write(**overrides))
    await session.commit()
    return announcement


async def test_an_expired_notice_stops_being_shown_anywhere(session):
    """An end date retires a notice from the archive as well as the queue."""
    author = await create_user(session, role=UserRole.owner)
    reader = await create_user(session)
    await _publish(
        session,
        author,
        published_at=datetime.now(UTC) - timedelta(days=2),
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )

    assert await service.list_for_user(session, user=reader) == []
    assert (
        await service.list_for_user(session, user=reader, include_dismissed=True) == []
    )


async def test_a_platform_rung_filters_the_audience(session):
    author = await create_user(session, role=UserRole.owner)
    member = await create_user(session, role=UserRole.member)
    operator = await create_user(session, role=UserRole.operator)
    await _publish(session, author, min_platform_role=UserRole.operator)

    assert await service.list_for_user(session, user=member) == []
    assert len(await service.list_for_user(session, user=operator)) == 1


async def test_guild_admins_only_needs_an_admin_membership_somewhere(session):
    author = await create_user(session, role=UserRole.owner)
    plain = await create_user(session)
    admin = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=plain, guild=guild, role=CommunityRole.member
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    await session.commit()
    await _publish(session, author, community_admins_only=True)

    assert await service.list_for_user(session, user=plain) == []
    assert len(await service.list_for_user(session, user=admin)) == 1


@pytest.mark.parametrize(
    "audience,reaches",
    [
        (AnnouncementAudienceAccounts.existing, {"was_here"}),
        (AnnouncementAudienceAccounts.new, {"arrived_since"}),
        (AnnouncementAudienceAccounts.everyone, {"was_here", "arrived_since"}),
    ],
)
async def test_the_audience_is_read_from_when_the_account_was_made(
    session, audience, reaches
):
    """A breaking change is about a transition somebody has to have made; an
    onboarding tip is the other way round; everyone is still everyone."""
    author = await create_user(session, role=UserRole.owner)
    published = datetime.now(UTC) - timedelta(days=7)

    accounts = {
        "was_here": await create_user(session),
        "arrived_since": await create_user(session),
    }
    accounts["was_here"].created_at = published - timedelta(days=30)
    accounts["arrived_since"].created_at = published + timedelta(days=1)
    session.add_all(accounts.values())
    await session.commit()

    await _publish(session, author, published_at=published, audience_accounts=audience)

    reached = {
        name
        for name, user in accounts.items()
        if await service.list_for_user(session, user=user)
    }
    assert reached == reaches


async def test_a_builtin_with_a_floor_skips_a_fresh_install(session, monkeypatch):
    """No previous version is the answer, not a missing one."""
    reader = await create_user(session)
    builtin = BuiltinAnnouncement(
        slug="test-upgrade-floor",
        title="Something moved in 0.65",
        category=AnnouncementCategory.breaking,
        published_at=datetime.now(UTC) - timedelta(hours=1),
        sections=(AnnouncementSection(body="It moved."),),
        only_upgrading_from_below="0.65.0",
    )
    monkeypatch.setattr(builtins_module, "BUILTIN_ANNOUNCEMENTS", (builtin,))
    monkeypatch.setattr(service, "BUILTIN_ANNOUNCEMENTS", (builtin,))

    # Fresh install: nothing was ever running before this.
    assert await service.list_for_user(session, user=reader) == []

    # Upgraded from below the floor: this deployment is who it is for.
    await app_settings_service.record_running_version(session, version="0.64.3")
    await app_settings_service.record_running_version(session, version="0.70.0")
    assert len(await service.list_for_user(session, user=reader)) == 1


async def test_a_builtin_with_a_floor_skips_a_deployment_already_past_it(
    session, monkeypatch
):
    reader = await create_user(session)
    builtin = BuiltinAnnouncement(
        slug="test-upgrade-floor-past",
        title="Something moved in 0.65",
        category=AnnouncementCategory.breaking,
        published_at=datetime.now(UTC) - timedelta(hours=1),
        sections=(AnnouncementSection(body="It moved."),),
        only_upgrading_from_below="0.65.0",
    )
    monkeypatch.setattr(builtins_module, "BUILTIN_ANNOUNCEMENTS", (builtin,))
    monkeypatch.setattr(service, "BUILTIN_ANNOUNCEMENTS", (builtin,))

    await app_settings_service.record_running_version(session, version="0.66.0")
    await app_settings_service.record_running_version(session, version="0.70.0")

    assert await service.list_for_user(session, user=reader) == []


async def test_the_version_pair_only_moves_when_the_version_does(session):
    assert (
        await app_settings_service.record_running_version(session, version="0.64.0")
        is None
    )
    # Restarting on the same version is not an upgrade.
    assert (
        await app_settings_service.record_running_version(session, version="0.64.0")
        is None
    )
    assert (
        await app_settings_service.record_running_version(session, version="0.65.0")
    ) == "0.64.0"
    assert await app_settings_service.previous_running_version(session) == "0.64.0"


async def test_two_tabs_dismissing_at_once_do_not_collide(session, engine):
    """Two connections, neither aware of the other, both dismissing.

    The read-then-write this used to be would either collide on the primary
    key (both finding no row) or lose one of the increments.
    """
    author = await create_user(session, role=UserRole.owner)
    reader = await create_user(session)
    announcement = await _publish(session, author, dismissals_required=2)
    key = f"db:{announcement.id}"

    async def dismiss_on_its_own_connection() -> None:
        async with AsyncSession(engine, expire_on_commit=False) as other:
            await service.record_receipt(
                other, user_id=reader.id, key=key, dismissed=True
            )
            await other.commit()

    await asyncio.gather(
        dismiss_on_its_own_connection(), dismiss_on_its_own_connection()
    )

    receipt = await session.get(AnnouncementReadReceipt, (reader.id, key))
    await session.refresh(receipt)
    assert receipt.dismiss_count == 2
    assert await service.list_for_user(session, user=reader) == []


async def test_dismissals_stop_counting_at_what_was_asked_for(session):
    """A client that keeps posting cannot run the counter away."""
    author = await create_user(session, role=UserRole.owner)
    reader = await create_user(session)
    announcement = await _publish(session, author, dismissals_required=2)
    key = f"db:{announcement.id}"

    for _ in range(5):
        await service.record_receipt(
            session, user_id=reader.id, key=key, dismissed=True
        )
    await session.commit()

    receipt = await session.get(AnnouncementReadReceipt, (reader.id, key))
    assert receipt.dismiss_count == 2


async def test_the_first_dismissal_leaves_one_read_line_in_the_bell(session):
    """The bell is where a dismissed notice is found again: one line, read."""
    author = await create_user(session, role=UserRole.owner)
    reader = await create_user(session)
    announcement = await _publish(session, author, dismissals_required=2)
    key = f"db:{announcement.id}"

    await service.record_receipt(session, user_id=reader.id, key=key, dismissed=False)
    for _ in range(3):
        await service.record_receipt(
            session, user_id=reader.id, key=key, dismissed=True
        )
        await session.commit()
        await drain_notices()

    lines = (
        await session.exec(
            select(Notification).where(Notification.user_id == reader.id)
        )
    ).all()
    assert [
        (line.type, line.data["announcement_key"], line.data["title"]) for line in lines
    ] == [(NotificationType.announcement, key, "Board view is new")]
    assert lines[0].read_at is not None


async def test_a_builtin_notice_is_merged_in_and_can_be_dismissed(session, monkeypatch):
    reader = await create_user(session)
    builtin = BuiltinAnnouncement(
        slug="test-breaking-change",
        title="Something moved",
        category=AnnouncementCategory.breaking,
        published_at=datetime.now(UTC) - timedelta(hours=1),
        sections=(AnnouncementSection(body="It moved over there."),),
    )
    monkeypatch.setattr(builtins_module, "BUILTIN_ANNOUNCEMENTS", (builtin,))
    monkeypatch.setattr(service, "BUILTIN_ANNOUNCEMENTS", (builtin,))

    items = await service.list_for_user(session, user=reader)
    assert [item.key for item in items] == ["builtin:test-breaking-change"]
    assert items[0].is_builtin is True

    assert await service.announcement_exists(session, key=builtin.key) is True
    await service.record_receipt(
        session, user_id=reader.id, key=builtin.key, dismissed=True
    )
    await session.commit()

    assert await service.list_for_user(session, user=reader) == []


async def test_the_pruner_keeps_referenced_pictures_and_drops_the_rest(session):
    used = await service.store_image(session, data=_png(padding=1))
    orphan = await service.store_image(session, data=_png(padding=2))
    # Both predate the grace period; only one is pointed at.
    long_ago = datetime.now(UTC) - timedelta(days=30)
    used.created_at = long_ago
    orphan.created_at = long_ago
    session.add(used)
    session.add(orphan)
    await session.commit()

    await service.create(
        session,
        payload=_write(
            sections=[
                AnnouncementSection(
                    body="see", image_url=service.image_url(used.sha256)
                )
            ]
        ),
    )
    await session.commit()

    removed = await service.prune_unreferenced_images(session)
    await session.commit()

    assert removed == 1
    assert await session.get(AnnouncementImage, used.sha256) is not None
    assert await session.get(AnnouncementImage, orphan.sha256) is None


async def test_re_uploading_an_old_orphan_survives_the_next_sweep(session):
    """Re-using a screenshot is somebody wanting it again, not an orphan.

    The upload path prunes on its way out, so a dedupe that kept the original
    timestamp would hand back a URL that same sweep had just deleted.
    """
    data = _png(padding=7)
    first = await service.store_image(session, data=data)
    first.created_at = datetime.now(UTC) - timedelta(days=30)
    session.add(first)
    await session.commit()

    again = await service.store_image(session, data=data)
    removed = await service.prune_unreferenced_images(session)
    await session.commit()

    assert removed == 0
    assert await session.get(AnnouncementImage, again.sha256) is not None


async def test_the_janitor_sweeps_what_no_write_would_have(session):
    """An editor that uploaded and was closed leaves bytes no save will reach."""
    abandoned = await service.store_image(session, data=_png(padding=9))
    abandoned.created_at = datetime.now(UTC) - timedelta(days=30)
    session.add(abandoned)
    await session.commit()

    await service.process_announcement_image_purge()

    # The janitor ran on its own session; expire this one's view of the row so
    # the assertion reads the database rather than the identity map.
    session.expunge_all()
    assert await session.get(AnnouncementImage, abandoned.sha256) is None


async def test_the_pruner_leaves_a_freshly_uploaded_picture_alone(session):
    image = await service.store_image(session, data=_png(padding=3))
    await session.commit()

    assert await service.prune_unreferenced_images(session) == 0
    assert await session.get(AnnouncementImage, image.sha256) is not None
