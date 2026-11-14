"""Tests for the inbox helpers that back rolled-up notifications.

A rolled-up line is read and then rewritten, so what the rewrite does to the
read stamp is the whole correctness question: the recipient can mark the line
read in between, and an event landing on an already-read line would never be
seen.
"""

from datetime import UTC, datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.notification import NotificationType
from app.services.platform import user_notifications
from app.testing import create_guild, create_user


async def _line(session: AsyncSession, user_id: int, *, guild_id: int, **data):
    return await user_notifications.create_notification(
        session,
        user_id=user_id,
        notification_type=NotificationType.comment_reaction,
        data={
            "community_id": guild_id,
            "target_type": "comment",
            "target_id": 5,
            **data,
        },
    )


class TestRefreshNotification:
    async def test_news_returns_a_read_line_to_the_top_and_to_unread(
        self, session: AsyncSession
    ):
        user = await create_user(session, email="rollup-read-race@example.com")
        guild = await create_guild(session, creator=user)
        line = await _line(session, user.id, guild_id=guild.id, count=1)
        line.read_at = datetime.now(UTC)
        await session.flush()

        await user_notifications.refresh_notification(
            session, line, data={**line.data, "count": 2}
        )
        assert line.read_at is None

    async def test_a_withdrawal_leaves_a_read_line_read(self, session: AsyncSession):
        user = await create_user(session, email="rollup-withdraw-read@example.com")
        guild = await create_guild(session, creator=user)
        line = await _line(session, user.id, guild_id=guild.id, count=2)
        read_at = datetime.now(UTC)
        line.read_at = read_at
        await session.flush()

        await user_notifications.refresh_notification(
            session, line, data={**line.data, "count": 1}, bump=False
        )
        assert line.read_at == read_at


async def test_find_unread_by_data_matches_every_key(session: AsyncSession):
    """The match is what decides which line a reaction joins, so a near miss on
    any one key must start a new line rather than land on the wrong comment."""
    user = await create_user(session, email="rollup-match@example.com")
    guild = await create_guild(session, creator=user)
    wanted = await _line(session, user.id, guild_id=guild.id, count=1)
    await _line(session, user.id, guild_id=guild.id, target_id=6, count=1)

    found = await user_notifications.find_unread_by_data(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_reaction,
        match={"community_id": guild.id, "target_type": "comment", "target_id": 5},
    )
    assert found is not None and found.id == wanted.id

    assert (
        await user_notifications.find_unread_by_data(
            session,
            user_id=user.id,
            notification_type=NotificationType.comment_reaction,
            match={
                "community_id": guild.id + 1,
                "target_type": "comment",
                "target_id": 5,
            },
        )
        is None
    )

    wanted.read_at = datetime.now(UTC)
    await session.flush()
    assert (
        await user_notifications.find_unread_by_data(
            session,
            user_id=user.id,
            notification_type=NotificationType.comment_reaction,
            match={"community_id": guild.id, "target_type": "comment", "target_id": 5},
        )
        is None
    )
