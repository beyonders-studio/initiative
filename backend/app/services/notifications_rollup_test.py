"""Comments roll up, the way reactions already do.

The volume reduction that needs nobody to change a setting: twenty comments on
one task are one unread line rather than twenty, and one interruption on the
reaching channels rather than twenty.
"""

from unittest.mock import AsyncMock, patch

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.notification import Notification, NotificationType
from app.services import notifications as notifications_service
from app.services.notifications import MAX_ROLLED_UP_COMMENTERS, _rolled_up_comment
from app.testing import create_user, drain_notices


async def _comment_on_task(session: AsyncSession, owner, talker, task_id: int) -> None:
    """A comment on a task, told to its assignee: the rolled-up kind."""
    await notifications_service.notify(
        session,
        NotificationType.comment_on_task,
        [owner.id],
        about=None,
        key="comment.onTask",
        values={"actor": talker.username, "task": f"Task {task_id}"},
        data={"task_id": task_id},
        actor=talker,
        rollup_key=f"task:{task_id}",
    )


async def _lines(session: AsyncSession, user_id: int) -> list[Notification]:
    rows = (
        await session.exec(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.id)
        )
    ).all()
    return [row[0] if isinstance(row, tuple) else row for row in rows]


def test_a_second_comment_extends_the_line():
    first = _rolled_up_comment(None, commenter_name="ana", commenter_id=1)
    assert first["comment_count"] == 1
    assert [c["name"] for c in first["commenters"]] == ["ana"]

    second = _rolled_up_comment(first, commenter_name="bo", commenter_id=2)
    assert second["comment_count"] == 2
    assert [c["name"] for c in second["commenters"]] == ["ana", "bo"]
    assert second["commenter_count"] == 2


def test_the_same_person_twice_is_one_commenter_and_two_comments():
    first = _rolled_up_comment(None, commenter_name="ana", commenter_id=1)
    again = _rolled_up_comment(first, commenter_name="ana", commenter_id=1)
    assert again["comment_count"] == 2
    assert again["commenter_count"] == 1
    assert [c["name"] for c in again["commenters"]] == ["ana"]


def test_the_roster_is_bounded_but_the_count_is_not():
    rolled = _rolled_up_comment(None, commenter_name="p0", commenter_id=0)
    for i in range(1, MAX_ROLLED_UP_COMMENTERS + 5):
        rolled = _rolled_up_comment(rolled, commenter_name=f"p{i}", commenter_id=i)
    assert rolled["comment_count"] == MAX_ROLLED_UP_COMMENTERS + 5
    assert len(rolled["commenters"]) == MAX_ROLLED_UP_COMMENTERS


async def test_many_comments_on_one_task_are_one_line(session: AsyncSession):
    owner = await create_user(session, email="rollup-owner@example.com")
    talkers = [
        await create_user(session, email=f"rollup-talker-{i}@example.com")
        for i in range(3)
    ]

    with patch(
        "app.services.platform.email_outbox.enqueue", new_callable=AsyncMock
    ) as email:
        for index, talker in enumerate(talkers):
            await _comment_on_task(session, owner, talker, 42)
        await session.commit()
        await drain_notices()

    lines = await _lines(session, owner.id)
    assert len(lines) == 1
    assert lines[0].data["comment_count"] == 3
    assert lines[0].data["commenter_count"] == 3
    # One interruption, not three: the flurry opens the window once.
    assert email.await_count == 1


async def test_a_different_task_gets_its_own_line(session: AsyncSession):
    owner = await create_user(session, email="rollup-two-tasks@example.com")
    talker = await create_user(session, email="rollup-two-talker@example.com")

    with patch("app.services.platform.email_outbox.enqueue", new_callable=AsyncMock):
        for task_id in (1, 2):
            await _comment_on_task(session, owner, talker, task_id)
        await session.commit()
        await drain_notices()

    assert len(await _lines(session, owner.id)) == 2


async def test_reading_the_line_starts_a_fresh_one(session: AsyncSession):
    """Unread is the window, as it is everywhere else — once somebody has
    looked, the next comment is news again."""
    owner = await create_user(session, email="rollup-read@example.com")
    talker = await create_user(session, email="rollup-read-talker@example.com")

    async def _comment(comment_id: int) -> None:
        await _comment_on_task(session, owner, talker, 7)

    with patch(
        "app.services.platform.email_outbox.enqueue", new_callable=AsyncMock
    ) as email:
        await _comment(1)
        await session.commit()
        await drain_notices()
        from app.services.platform import user_notifications

        line = (await _lines(session, owner.id))[0]
        await user_notifications.mark_notification_read(
            session, user_id=owner.id, notification_id=line.id
        )
        await _comment(2)
        await session.commit()
        await drain_notices()

    assert len(await _lines(session, owner.id)) == 2
    assert email.await_count == 2
