"""The inbox's own frames.

Routing — which socket a frame reaches — belongs to the shared transport and
is pinned in ``user_stream_test``. What is left here is the inbox's half:

* a frame is emitted only after the writing transaction commits — never on
  flush, and never at all if the transaction rolls back,
* a frame stays content-free: an envelope, never a notification's payload,
* the notification service pokes the right person at the right moment.
"""

from typing import ClassVar

from sqlmodel import select

from app.models.platform.notification import Notification, NotificationType
from app.services.platform import user_notifications
from app.services.platform.notification_stream import queue_signal
from app.testing import create_user
from app.testing.sockets import settle


async def test_frame_carries_no_notification_content(session, account_socket) -> None:
    """An id envelope, and the inbox needs no ids — so nothing but the shape."""
    user = await create_user(session)
    tab = account_socket(user.id)

    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await session.commit()
    await settle()

    frame = tab.sent[0]
    assert frame["resource"] == "notification"
    assert frame["action"] == "created"
    assert frame["ids"] == {}
    assert set(frame) == {"resource", "action", "ids", "timestamp"}


# ---------------------------------------------------------------------------
# Commit coupling
# ---------------------------------------------------------------------------


async def test_no_frame_before_the_commit(session, account_socket) -> None:
    """A flushed-but-uncommitted notification must not poke anyone: the client
    would refetch an inbox that does not yet contain it, and nothing polls
    behind the signal any more."""
    user = await create_user(session)
    tab = account_socket(user.id)

    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await settle()

    assert tab.sent == []


async def test_frame_goes_out_on_commit(session, account_socket) -> None:
    user = await create_user(session)
    tab = account_socket(user.id)

    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await session.commit()
    await settle()

    assert [frame["action"] for frame in tab.sent] == ["created"]


async def test_rollback_pokes_nobody(session, account_socket) -> None:
    user = await create_user(session)
    tab = account_socket(user.id)

    await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await session.rollback()
    await settle()

    assert tab.sent == []


async def test_several_notifications_in_one_transaction_send_one_frame(
    session, account_socket
) -> None:
    """The frame says "refetch", so a batch of notifications for one recipient
    is one refetch, not one per row."""
    user = await create_user(session)
    tab = account_socket(user.id)

    for task_id in (1, 2, 3):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.task_assignment,
            data={"task_id": task_id},
        )
    await session.commit()
    await settle()

    assert len(tab.sent) == 1


async def test_a_batch_pokes_each_recipient_once(session, account_socket) -> None:
    alice = await create_user(session)
    bob = await create_user(session)
    alice_tab = account_socket(alice.id)
    bob_tab = account_socket(bob.id)

    for user_id in (alice.id, bob.id, alice.id):
        await user_notifications.create_notification(
            session,
            user_id=user_id,
            notification_type=NotificationType.task_assignment,
            data={"task_id": 1},
        )
    await session.commit()
    await settle()

    assert len(alice_tab.sent) == 1
    assert len(bob_tab.sent) == 1


async def test_marking_read_pokes_the_users_other_tabs(session, account_socket) -> None:
    """The badge on a second device is otherwise stale until something else
    happens."""
    user = await create_user(session)
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.task_assignment,
        data={"task_id": 1},
    )
    await session.commit()
    await settle()  # let the "created" frame go out before we listen

    tab = account_socket(user.id)
    await user_notifications.mark_notification_read(
        session, user_id=user.id, notification_id=notification.id
    )
    await settle()

    assert [frame["action"] for frame in tab.sent] == ["read"]


async def test_mark_all_read_pokes_once(session, account_socket) -> None:
    user = await create_user(session)
    for task_id in (1, 2):
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.task_assignment,
            data={"task_id": task_id},
        )
    await session.commit()
    await settle()  # let the "created" frame go out before we listen

    tab = account_socket(user.id)
    await user_notifications.mark_all_notifications_read(session, user_id=user.id)
    await settle()

    assert [frame["action"] for frame in tab.sent] == ["read"]
    unread = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
            )
        )
    ).all()
    assert unread == []


async def test_rolling_a_line_up_pokes_the_recipient(session, account_socket) -> None:
    """A rolled-up reaction rewrites the existing line rather than adding one,
    so the rewrite is the only trace the second event leaves — and with no poll
    behind the signal, an unsignalled rewrite is an invisible one."""
    user = await create_user(session)
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_reaction,
        data={"target_id": 7, "count": 1},
    )
    await session.commit()
    await settle()

    tab = account_socket(user.id)
    await user_notifications.refresh_notification(
        session, notification, data={"target_id": 7, "count": 2}
    )
    await session.commit()
    await settle()

    assert [frame["action"] for frame in tab.sent] == ["updated"]


async def test_a_withdrawal_pokes_without_claiming_to_be_news(
    session, account_socket
) -> None:
    user = await create_user(session)
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_reaction,
        data={"target_id": 7, "count": 2},
    )
    await session.commit()
    await settle()

    tab = account_socket(user.id)
    await user_notifications.refresh_notification(
        session, notification, data={"target_id": 7, "count": 1}, bump=False
    )
    await session.commit()
    await settle()

    assert [frame["action"] for frame in tab.sent] == ["withdrawn"]


async def test_deleting_a_line_pokes_the_recipient(session, account_socket) -> None:
    """The last reaction being taken back removes the line outright; a bell
    still showing it is what this prevents."""
    user = await create_user(session)
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.comment_reaction,
        data={"target_id": 7, "count": 1},
    )
    await session.commit()
    await settle()

    tab = account_socket(user.id)
    await user_notifications.delete_notification(session, notification)
    await session.commit()
    await settle()

    assert [frame["action"] for frame in tab.sent] == ["withdrawn"]


async def test_lines_announced_together_share_one_alert(
    session, account_socket
) -> None:
    """The alert names its lines and nothing about them, in its own frame
    beside the inbox's."""
    user = await create_user(session)
    tab = account_socket(user.id)

    lines = [
        await user_notifications.create_notification(
            session,
            user_id=user.id,
            notification_type=NotificationType.task_assignment,
            data={"task_id": task_id},
        )
        for task_id in (1, 2)
    ]
    for line in lines:
        assert line is not None
        await user_notifications.announce_on_desktop(session, line)
    await session.commit()
    await settle()

    alert = next(frame for frame in tab.sent if frame["resource"] == "alert")
    assert alert["ids"] == {"notifications": [line.id for line in lines if line]}
    assert set(alert) == {"resource", "action", "ids", "timestamp"}
    assert [frame["resource"] for frame in tab.sent].count("notification") == 1


async def test_queue_signal_ignores_a_missing_recipient() -> None:
    """Defensive: a caller with no user id queues nothing rather than erroring
    inside someone else's transaction."""

    class Session:
        info: ClassVar[dict] = {}

    session = Session()
    queue_signal(session, None)
    assert session.info == {}
