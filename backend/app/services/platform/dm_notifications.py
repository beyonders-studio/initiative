"""Telling somebody they have a message, without saying what it is.

One rolled-up bell line per (recipient, conversation), exactly as reactions are
kept one line per (recipient, thing reacted to): a new message joins the
existing **unread** line and moves it back to the top, and once that line is
read the next message starts a fresh one, so "new" keeps meaning something.

Reading the *thread* is what reads the line -- :func:`mark_conversation_read`,
called by the recipient's own client once it has rendered what arrived. The
server has no other way to know: it holds no message and cannot tell that one
reached a screen.

The rollup governs the **line**, not the interruption. A push goes out for every
message; the email goes out when the line turns unread. The two differ because
they are read in different places -- a lock screen is where a conversation
happens, and a mailbox is where you find out you missed one.

The line names the sender and counts the messages. It never carries one, and
nothing here adds a way for it to: the payload it announces is opaque on this
side.

This runs on the system engine rather than the sender's session. Writing a
notification and reading push tokens are both things the recipient's account
owns, and the sender has no business reaching either. The push is written to
the notice outbox in the same transaction as the line, and its worker sends
it and tries again when it fails.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import translate
from app.core.notification_categories import Channel, NotificationCategory
from app.core.user_display import handle_of
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user import User
from app.services.platform import (
    dm_stream,
    notice_outbox,
    notification_policy,
    notification_prefs,
    notification_stream,
    push_notifications,
    user_notifications,
)

logger = logging.getLogger(__name__)


def _locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


async def reading_devices(
    session: AsyncSession, user_ids: Collection[int]
) -> dict[int, set[uuid.UUID]]:
    """The sign-ins of each of these accounts whose device could actually
    decrypt.

    A push wakes a client so it can fetch and decrypt. Sending one to a device
    with no key store would wake it for something it cannot read. Each key
    store names the sign-in it last collected under, taken to the live row its
    chain has reached, which is the one its push registration names too. One
    read for every account asked about.
    """
    from app.models.platform.dm_device import DmDevice
    from app.services.auth import sessions as session_service

    if not user_ids:
        return {}
    rows = (
        await session.exec(
            select(DmDevice.user_id, DmDevice.session_id).where(
                col(DmDevice.user_id).in_(list(user_ids)),
                col(DmDevice.session_id).is_not(None),
            )
        )
    ).all()
    tips = await session_service.live_chain_tips(
        session, session_ids={session_id for _, session_id in rows if session_id}
    )
    readers: dict[int, set[uuid.UUID]] = {}
    for user_id, session_id in rows:
        tip = tips.get(session_id) if session_id is not None else None
        if tip is not None:
            readers.setdefault(user_id, set()).add(tip)
    return readers


async def _roster_names(
    session: AsyncSession, *, conversation_id: uuid.UUID, recipient_id: int
) -> list[str]:
    """Who else is on this conversation, as the recipient would name them.

    Everybody but the reader, in id order so the same thread reads the same way
    every time. Handles rather than display names: a direct message happens
    outside any community, so there is no community whose naming applies.

    This is the roster the server had to resolve in order to route the message
    at all — the fact of who is talking, which is not the secret. What they
    said is, and nothing here can reach it.
    """
    from app.models.platform.dm_conversation import DmConversationMember

    rows = (
        await session.exec(
            select(User)
            .join(DmConversationMember, DmConversationMember.user_id == User.id)
            .where(
                DmConversationMember.conversation_id == conversation_id,
                DmConversationMember.user_id != recipient_id,
                DmConversationMember.accepted_at.is_not(None),
            )
            .order_by(User.id)
        )
    ).all()
    return [handle_of(user) for user in rows]


async def notify(
    *,
    recipient_id: int,
    sender: User,
    sender_name: str,
    conversation_id: uuid.UUID,
    group: bool = False,
) -> None:
    """Roll one message into the recipient's bell line, then wake their tabs.

    Failures here are logged and swallowed: the message is already delivered,
    and a bell line is not worth failing a send over.
    """
    from app.db.session import SystemSessionLocal

    try:
        async with SystemSessionLocal() as session:
            recipient = await session.get(User, recipient_id)
            if recipient is None:
                return
            others = (
                await _roster_names(
                    session,
                    conversation_id=conversation_id,
                    recipient_id=recipient_id,
                )
                if group
                else []
            )
            await _roll_up(
                session,
                recipient=recipient,
                sender=sender,
                sender_name=sender_name,
                conversation_id=conversation_id,
                others=others,
            )
            await session.commit()
    except Exception:
        logger.exception("direct-message notification failed")
    await dm_stream.signal_dm(recipient_id)


def _line_of(conversation_id: uuid.UUID):
    """Every rolled-up line this account holds for one conversation."""
    return (
        Notification.type == NotificationType.direct_message,
        Notification.data["conversation_id"].as_string() == str(conversation_id),
    )


async def mark_conversation_read(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> int:
    """Close this account's rolled-up line for one conversation.

    A line collects while it is unread, and the push and the email fire on the
    transition into unread rather than once per message. Closing the line is
    therefore what lets the next message announce itself at all, and reading the
    thread is what closes it -- there is nothing else that could, since the
    server cannot see a message arrive at a screen.

    Runs on the reader's own session: the line is theirs, and so is the claim
    that they have read it.
    """
    result = await session.exec(
        update(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            *_line_of(conversation_id),
        )
        .values(read_at=datetime.now(UTC))
    )
    closed = result.rowcount or 0
    if closed:
        # The tab that read the thread already knows; this is for the account's
        # other tabs and devices, whose badge would keep the stale count.
        notification_stream.queue_signal(session, user_id, "read")
    return closed


async def forget_conversation(
    session: AsyncSession, *, user_id: int, conversation_id: uuid.UUID
) -> int:
    """Take down the lines for a conversation this account has left.

    Read or unread alike: the line names a thread that is no longer in the list,
    and tapping it would arrive at nothing.
    """
    result = await session.exec(
        delete(Notification).where(
            Notification.user_id == user_id,
            *_line_of(conversation_id),
        )
    )
    removed = result.rowcount or 0
    if removed:
        notification_stream.queue_signal(session, user_id, "withdrawn")
    return removed


async def wake_own_devices(
    *, user_id: int, except_session_id: uuid.UUID | None
) -> None:
    """Push this account's other installations awake, saying nothing.

    One device has sent another something it cannot answer on its own -- a new
    install asking to be sent the history it arrived without. The far phone has
    to be picked up before anybody can approve it, so a frame on a socket that
    is not open will not do.

    No bell line: the ask is already on screen on the device that made it, and a
    second copy in the recipient's inbox would outlive the request. The one that
    sent it is skipped -- it is the device already showing the notice.

    The account's push preference applies: this rides the messages channel, and
    somebody who has said they do not want messages waking them has said it
    about this too.

    Quiet hours do not, and this is the one place in the app where they are
    skipped. Everywhere else a suppressed notification is only deferred -- the
    bell line is still written, and the "while you were away" summary collects
    it. This wake writes no bell line and is sent exactly once, because a device
    asks for its history once and never again, so suppressing it does not move
    the interruption to the morning; it deletes it, and leaves the new device
    waiting on an approval nobody was ever told to give. The person is also, by
    construction, awake and holding a device they signed into moments ago.
    """
    from app.db.session import SystemSessionLocal

    try:
        async with SystemSessionLocal() as session:
            user = await session.get(User, user_id)
            if user is None:
                return
            prefs = await notification_prefs.load_prefs(session, user_id)
            if not notification_prefs.wants(
                prefs,
                category=NotificationCategory.direct_messages,
                channel=Channel.push,
            ):
                return
            session_ids = (await reading_devices(session, [user_id])).get(
                user_id, set()
            )
            session_ids.discard(except_session_id)
            if not session_ids:
                return
            locale = _locale(user)
            shown = notification_policy.apply(
                await notification_policy.for_send(session, None),
                (
                    translate("deviceSync.title", locale, namespace="notifications"),
                    translate("deviceSync.body", locale, namespace="notifications"),
                ),
                category=NotificationCategory.direct_messages,
                locale=locale,
            )
            if shown is None:
                return
            await push_notifications.send_pushes(
                session,
                [
                    push_notifications.Push(
                        user_id,
                        NotificationType.direct_message,
                        *shown,
                        {"type": "dm_device_sync", "target_path": "/messages"},
                        session_ids=frozenset(session_ids),
                    )
                ],
            )
            await session.commit()
    except Exception:
        logger.exception("direct-message device wake failed")


async def _roll_up(
    session: AsyncSession,
    *,
    recipient: User,
    sender: User,
    sender_name: str,
    conversation_id: uuid.UUID,
    others: list[str],
) -> None:
    match = {"conversation_id": str(conversation_id)}
    await advisory_lock(
        session,
        LockNamespace.NOTIFICATION_LINE,
        f"dm-bell:{conversation_id}:{recipient.id}",
    )
    existing = await user_notifications.find_unread_by_data(
        session,
        user_id=recipient.id,
        notification_type=NotificationType.direct_message,
        match=match,
    )
    previous: Mapping[str, Any] = (existing.data if existing else None) or {}
    count = cast(int, previous.get("count", 0)) + 1
    line: dict[str, Any] = {
        "conversation_id": str(conversation_id),
        "sender_id": sender.id,
        "sender_name": sender_name,
        "count": count,
    }
    if others:
        # A group thread is named by who is on it, because it has no other name
        # and is not going to get one. Everybody but the reader: a line that
        # listed them back to themselves would be naming the one person who
        # already knows they are there.
        line["member_names"] = others
    prefs = await notification_prefs.load_prefs_for_delivery(recipient.id)
    written = existing
    if existing is None:
        written = await user_notifications.create_notification(
            session,
            user_id=recipient.id,
            notification_type=NotificationType.direct_message,
            data=line,
            prefs=prefs,
        )
    else:
        await user_notifications.refresh_notification(session, existing, data=line)

    def _wanted(channel: Channel) -> bool:
        return notification_prefs.reachable(
            prefs,
            category=NotificationCategory.direct_messages,
            channel=channel,
            tz_name=recipient.timezone,
            last_active_at=recipient.last_active_at,
        )

    # Push fires per message. A reply to a conversation somebody has already
    # been told about is the thing they are waiting for, and a messenger that
    # announces the first message and then goes quiet is not one anybody can
    # hold a conversation on. This is what every messenger does and what people
    # expect; the preference and quiet hours are where it is turned down.
    if _wanted(Channel.push):
        await _push(
            session, recipient=recipient, sender_name=sender_name, others=others
        )
    # The desktop is told per message for the same reason, and shows the line
    # as the bell words it.
    if written is not None and _wanted(Channel.desktop):
        await user_notifications.announce_on_desktop(session, written)

    # Email does not. It is the channel for somebody who is not there at all,
    # and one per message would be a mailbox nobody could use -- so it fires on
    # the transition into unread, and again once the line has been read. It is
    # asked of ``wants`` rather than ``reachable`` because a held email is
    # deferred rather than dropped; when it goes out is the outbox's to decide.
    if existing is None and notification_prefs.wants(
        prefs,
        category=NotificationCategory.direct_messages,
        channel=Channel.email,
    ):
        await _email(
            session, recipient=recipient, sender_name=sender_name, notification=written
        )


async def _email(
    session: AsyncSession,
    *,
    recipient: User,
    sender_name: str,
    notification: Notification | None,
) -> None:
    """Say a message is waiting. The name, and nothing else.

    Written to the outbox rather than sent, so it follows the account's own
    cadence and stands down while they are paused -- and so reading the thread
    before it goes withdraws it, which is the one thing a mailbox most wants.
    """
    from app.core.config import settings as app_config
    from app.services import email as email_service
    from app.services.platform import email_outbox

    link = f"{app_config.APP_URL.rstrip('/') or 'http://localhost:5173'}/messages"
    await email_outbox.enqueue(
        session,
        recipient,
        category=NotificationCategory.direct_messages,
        notification_id=notification.id if notification is not None else None,
        pieces=email_service.direct_message_pieces(
            recipient, sender_name=sender_name, link=link
        ),
    )


async def _push(
    session: AsyncSession, *, recipient: User, sender_name: str, others: list[str]
) -> None:
    """Write the message's push down for the notice worker, which sends it to
    the devices that can read it and tries again if it fails."""
    locale = _locale(recipient)
    if others:
        # The thread goes in the title and the sender in the body, which is how
        # a lock screen is read: which conversation first, then who spoke. The
        # roster is not shortened -- the platform truncates a long title on its
        # own, and picking a number of names to keep would be inventing a rule
        # about whose name matters.
        title = ", ".join(others)
        body = translate(
            "directMessageGroup.body",
            locale,
            namespace="notifications",
            sender=sender_name,
        )
    else:
        title = translate(
            "directMessage.title",
            locale,
            namespace="notifications",
            sender=sender_name,
        )
        body = translate("directMessage.body", locale, namespace="notifications")
    await notice_outbox.queue_push(
        session,
        recipient,
        push_notifications.Push(
            cast(int, recipient.id),
            NotificationType.direct_message,
            title,
            body,
            # Where tapping it goes, and nothing more. The conversation's id
            # would open the right thread, but it would also put a record of
            # who is talking to whom through a push service, which is the one
            # thing this feature is built not to do.
            {
                "type": NotificationType.direct_message.value,
                "target_path": "/messages",
            },
        ),
    )
