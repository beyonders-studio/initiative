from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional, Sequence

from sqlalchemy import delete, func, tuple_, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import PERSONAL_TYPES, Channel, category_of
from app.models.platform.notification import Notification, NotificationType
from app.services import keyset_cursor
from app.services.platform import (
    notification_policy,
    notification_prefs,
    notification_stream,
)


def _int_or_none(value: object) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _place(data: Mapping[str, object]) -> dict[str, object]:
    """Where this happened, read off the payload that already carries it.

    Independently-optional levels: a direct message has none of them, a
    membership notice has only a guild, a comment on a task has all of them —
    community, initiative, tool, the tool's row and the task itself. Kept as
    columns so "where is there unread activity" is an index lookup.
    """
    # ``tool`` where the notifier states it outright, otherwise the entity type
    # it already carries. They differ for a task comment, whose entity is the
    # task and whose tool is the project list it lives in — and ``entity_type``
    # is what the link resolver reads, so it is not the place to say the other.
    tool = data.get("tool") or data.get("entity_type")
    return {
        "guild_id": _int_or_none(data.get("community_id")),
        "initiative_id": _int_or_none(data.get("initiative_id")),
        "tool": tool if isinstance(tool, str) and tool else None,
        "resource_id": _int_or_none(data.get("resource_id")),
        "subject_type": subject
        if isinstance(subject := data.get("subject_type"), str)
        else None,
        "subject_id": _int_or_none(data.get("subject_id")),
    }


async def create_notification(
    session: AsyncSession,
    *,
    user_id: int,
    notification_type: NotificationType,
    data: Mapping[str, object],
    prefs: Optional[Mapping[str, Any]] = None,
) -> Optional[Notification]:
    """Write one notification, unless its recipient has switched the bell off
    for that category.

    Every notification in the app is written through here, which is what makes
    this the one place the in-app channel can be honoured. It runs on the
    system engine: the notice worker calls it, and only a direct message and
    the suspension notice call it inline. A request that causes a notice writes
    it to ``notice_outbox`` instead, and holds no right to the bell. Returns ``None``
    when the recipient does not want it, so a caller can tell the difference
    between "wrote a line" and "there is nothing to point at".

    ``prefs`` is the recipient's settings document. Callers fanning out to an
    audience pass it from a batch load; a single-recipient caller leaves it
    None and this reads it.
    """
    place = _place(data)
    if prefs is None:
        prefs = await notification_prefs.load_prefs_for_delivery(user_id)
    if not notification_prefs.wants(
        prefs,
        category=category_of(notification_type),
        channel=Channel.in_app,
        guild_id=place["guild_id"],
    ):
        return None

    notification = Notification(
        user_id=user_id,
        type=notification_type,
        data=dict(data),
        **place,
    )
    session.add(notification)
    await session.flush()
    # This one call is also what puts the recipient's open tabs on the realtime
    # channel instead of a 30s poll. The frame itself waits for this session's
    # COMMIT (see ``notification_stream``), so a caller that rolls back pokes
    # nobody.
    notification_stream.queue_signal(session, user_id, "created")
    return notification


async def announce_on_desktop(session: AsyncSession, line: Notification) -> None:
    """Have the recipient's desktop apps show this line, unless the
    deployment or the line's community has switched push off.

    The caller has already asked whether the recipient wants it on the
    desktop. Redaction is applied when the app reads the line, under the
    switches as they stand then.
    """
    if line.id is None:
        return
    if (await notification_policy.for_send(session, line.guild_id)).push:
        notification_stream.queue_alert(session, line.user_id, line.id)


async def get_notification(
    session: AsyncSession, *, user_id: int, notification_id: int
) -> Optional[Notification]:
    """One of this account's lines, or ``None``."""
    result = await session.exec(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
    )
    row = result.one_or_none()
    return row[0] if isinstance(row, tuple) else row


async def find_unread_by_data(
    session: AsyncSession,
    *,
    user_id: int,
    notification_type: NotificationType,
    match: Mapping[str, object],
) -> Notification | None:
    """The newest UNREAD notification of this type whose ``data`` matches every
    key in ``match``, if there is one.

    This is what lets a notification stream roll up rather than repeat: a
    second event about the same thing updates the line the first one wrote
    instead of adding another. Unread is the whole window — once the recipient
    has seen a line, the next event starts a fresh one, which is what keeps
    "new" meaning something.
    """
    stmt = select(Notification).where(
        Notification.user_id == user_id,
        Notification.type == notification_type,
        Notification.read_at.is_(None),
    )
    for key, value in match.items():
        # ``->>`` compares as text, so the value is stringified to match how
        # Postgres renders it — an int in the payload reads back as "12".
        stmt = stmt.where(Notification.data[key].as_string() == str(value))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
        1
    )
    result = await session.exec(stmt)
    row = result.one_or_none()
    if row is None:
        return None
    return row[0] if isinstance(row, tuple) else row


async def refresh_notification(
    session: AsyncSession,
    notification: Notification,
    *,
    data: Mapping[str, object],
    bump: bool = True,
) -> Notification:
    """Rewrite a notification's payload in place.

    ``bump`` says the line has something new to say, so it returns to the top
    of the inbox AND to unread. Unread matters for more than tidiness: the
    recipient can mark the line read between the lookup that found it and this
    write, and a rolled-up event landing on an already-read line would never be
    seen. Clearing the stamp is a no-op on the line this was meant for — it was
    unread when it was found — and the right answer when it is not.

    A withdrawal passes ``bump=False``: taking something away is not news, and
    must not resurrect a line the recipient has already dealt with.
    """
    notification.data = dict(data)
    if bump:
        notification.created_at = datetime.now(timezone.utc)
        notification.read_at = None
    session.add(notification)
    await session.flush()
    # A rolled-up line is the only trace a second event leaves, so it has to
    # reach the bell the same way a new row does — there is no poll behind the
    # signal to notice the rewrite later.
    notification_stream.queue_signal(
        session, notification.user_id, "updated" if bump else "withdrawn"
    )
    return notification


async def delete_notification(
    session: AsyncSession, notification: Notification
) -> None:
    """Remove a notification outright — used when every event it rolled up has
    been taken back, so the line has nothing left to say."""
    user_id = notification.user_id
    await session.delete(notification)
    await session.flush()
    # Read the recipient off before the delete — the instance is expunged, and
    # a bell still showing a withdrawn line is the thing this prevents.
    notification_stream.queue_signal(session, user_id, "withdrawn")


async def list_notifications(
    session: AsyncSession,
    *,
    user_id: int,
    limit: int = 50,
    cursor: str | None = None,
    unread_only: bool = False,
    guild_id: int | None = None,
    personal_only: bool = False,
) -> tuple[list[Notification], int | None, str | None]:
    """One page of the inbox, newest first, plus the unread total.

    Returns the cursor for the next page, or None at the end. The popover asks
    for ``unread_only`` and takes every page; the inbox page takes them as it
    is scrolled. The total is counted on the first page only — a later page
    answers None — since it is one figure for the whole inbox.
    """
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if guild_id is not None:
        stmt = stmt.where(Notification.guild_id == guild_id)
    if personal_only:
        stmt = stmt.where(Notification.type.in_(sorted(PERSONAL_TYPES)))
    position = keyset_cursor.decode(cursor)
    if position is not None:
        stamp, last_id = position
        stmt = stmt.where(
            tuple_(Notification.created_at, Notification.id) < (stamp, last_id)
        )
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(
        limit + 1
    )
    result = await session.exec(stmt)
    rows = result.all()
    notifications = [row[0] if isinstance(row, tuple) else row for row in rows]
    # One more than asked for is how "is there another page" is answered
    # without a second count query.
    next_cursor = None
    if len(notifications) > limit:
        last = notifications[limit - 1]
        next_cursor = keyset_cursor.encode(last.created_at, last.id)
    notifications = notifications[:limit]
    unread = await unread_count(session, user_id=user_id) if position is None else None
    return notifications, unread, next_cursor


async def unread_places(session: AsyncSession, *, user_id: int) -> list[dict[str, Any]]:
    """The distinct places this account has unread activity.

    One index-only scan over the partial index, returning a handful of rows —
    a node in the navigation lights when any of them names it or something
    beneath it, all the way down to the item. There is nothing to count: a dot
    says "look here", and the popover says how much. A row with no guild at all
    is still a member of this set, so "is anything unread" is the set being
    non-empty and needs no second question.
    """
    stmt = (
        select(
            Notification.guild_id,
            Notification.initiative_id,
            Notification.tool,
            Notification.resource_id,
            Notification.subject_type,
            Notification.subject_id,
        )
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .distinct()
    )
    result = await session.exec(stmt)
    return [dict(row._mapping) for row in result.all()]


async def read_subject(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int,
    subject_type: str,
    subject_id: int,
) -> tuple[list[int], datetime | None]:
    """Mark every unread line about one item read, because its reader opened it.

    Returns what was unread there, for the page to show: the comments those
    lines named (a mention, a reply, the comment reacted to), and ``since`` —
    the earliest a rolled-up comment line began collecting, every comment after
    which is one it stood for.
    """
    rows = (
        (
            await session.exec(
                update(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.guild_id == guild_id,
                    Notification.subject_type == subject_type,
                    Notification.subject_id == subject_id,
                    Notification.read_at.is_(None),
                )
                .values(read_at=datetime.now(timezone.utc))
                .returning(Notification.data)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return [], None
    comment_ids: set[int] = set()
    opened: list[datetime] = []
    for data in rows:
        named = data.get("comment_id")
        if data.get("target_type") == "comment":
            named = data.get("target_id")
        if isinstance(named, int):
            comment_ids.add(named)
        if isinstance(stamp := data.get("opened_at"), str):
            opened.append(datetime.fromisoformat(stamp))
    notification_stream.queue_signal(session, user_id, "read")
    await session.commit()
    return sorted(comment_ids), min(opened, default=None)


async def mark_notification_read(
    session: AsyncSession,
    *,
    user_id: int,
    notification_id: int,
) -> Notification | None:
    notification = await get_notification(
        session, user_id=user_id, notification_id=notification_id
    )
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        session.add(notification)
        # The tab that clicked already knows; this is for the user's *other*
        # tabs and devices, whose badge would otherwise keep the stale count.
        notification_stream.queue_signal(session, user_id, "read")
        await session.commit()
        await session.refresh(notification)
    return notification


async def mark_notification_unread(
    session: AsyncSession,
    *,
    user_id: int,
    notification_id: int,
) -> Notification | None:
    """Put a line back. Reading is a statement about the reader, and one made
    by accident should be retractable."""
    notification = await get_notification(
        session, user_id=user_id, notification_id=notification_id
    )
    if notification is None:
        return None
    if notification.read_at is not None:
        notification.read_at = None
        session.add(notification)
        notification_stream.queue_signal(session, user_id, "unread")
        await session.commit()
        await session.refresh(notification)
    return notification


async def dismiss_notification(
    session: AsyncSession,
    *,
    user_id: int,
    notification_id: int,
) -> bool:
    """Remove one line outright."""
    notification = await get_notification(
        session, user_id=user_id, notification_id=notification_id
    )
    if notification is None:
        return False
    await session.delete(notification)
    notification_stream.queue_signal(session, user_id, "withdrawn")
    await session.commit()
    return True


async def mark_all_notifications_read(
    session: AsyncSession,
    *,
    user_id: int,
    guild_id: int | None = None,
) -> int:
    """Clear the unread set, or just one community's part of it."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    if guild_id is not None:
        stmt = stmt.where(Notification.guild_id == guild_id)
    result = await session.exec(stmt)
    notification_stream.queue_signal(session, user_id, "read")
    await session.commit()
    return result.rowcount or 0


async def unread_count(session: AsyncSession, *, user_id: int) -> int:
    return (await unread_counts(session, [user_id])).get(user_id, 0)


async def unread_counts(
    session: AsyncSession, user_ids: Sequence[int]
) -> dict[int, int]:
    """Each account's unread count, in one statement. An account with nothing
    unread is absent."""
    if not user_ids:
        return {}
    result = await session.exec(
        select(Notification.user_id, func.count())
        .where(
            Notification.user_id.in_(list(user_ids)),
            Notification.read_at.is_(None),
        )
        .group_by(Notification.user_id)
    )
    return {user_id: count for user_id, count in result.all()}


#: How long a notification is kept once it has been read. Unread ones are never
#: swept: a notice nobody has seen yet is still doing its job.
READ_RETENTION = timedelta(days=30)
#: Rows deleted per statement, so one sweep never holds a long lock or a large
#: transaction however far behind it starts.
PRUNE_BATCH = 5000


async def prune_read(session: AsyncSession, *, now: datetime) -> int:
    """Delete notifications read more than :data:`READ_RETENTION` ago.

    Runs on the system engine. Batched and committed per batch until nothing
    is left, and returns how many went.
    """
    cutoff = now - READ_RETENTION
    total = 0
    while True:
        batch = (
            select(Notification.id)
            .where(Notification.read_at.is_not(None), Notification.read_at < cutoff)
            .limit(PRUNE_BATCH)
            .scalar_subquery()
        )
        result = await session.exec(
            delete(Notification).where(Notification.id.in_(batch))
        )
        await session.commit()
        deleted = result.rowcount or 0
        total += deleted
        if deleted < PRUNE_BATCH:
            return total
