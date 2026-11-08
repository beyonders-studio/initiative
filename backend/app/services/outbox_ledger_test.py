"""The queue tables' shared rules: a claim is a lease, a recipient is served by
one pass at a time, and a schedule lists every wait before a row is given up."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import NotificationCategory
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.services import email as email_service
from app.services import outbox_ledger
from app.services.platform import email_outbox, notice_outbox
from app.testing import create_user


async def test_a_claim_is_held_for_its_lease_and_its_recipient_waits(
    session: AsyncSession,
):
    served = await create_user(session)
    waiting = await create_user(session)
    await notice_outbox.enqueue(
        session,
        [
            notice_outbox.row(user.id, None, NotificationType.mention, {})
            for user in (served, waiting)
        ],
    )
    await session.commit()
    now = datetime.now(UTC)

    [first] = await outbox_ledger.claim(session, NoticeOutboxItem, [served.id], now=now)
    assert (
        await outbox_ledger.claim(session, NoticeOutboxItem, [served.id], now=now) == []
    )
    due = await outbox_ledger.due_recipients(
        session, NoticeOutboxItem, now=now, limit=10
    )
    assert waiting.id in due and served.id not in due

    later = now + outbox_ledger.LEASE + timedelta(seconds=1)
    taken_back = await outbox_ledger.claim(
        session, NoticeOutboxItem, [served.id], now=later
    )
    assert [row.id for row in taken_back] == [first.id]


async def test_each_wait_is_waited_once_then_the_row_is_given_up(
    session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(email_service, "email_configured", AsyncMock(return_value=True))
    user = await create_user(session)
    await email_outbox.enqueue(
        session,
        user,
        category=NotificationCategory.mentions,
        pieces=email_service.EmailPieces(subject="s", headline="h", body="b"),
    )
    await session.commit()
    table = EmailOutboxItem.__table__
    now = datetime.now(UTC)
    fail = outbox_ledger.back_off(
        table, table.c.user_id == user.id, now=now, spent="failed_at"
    ).returning(table.c.deliver_after, table.c.failed_at)

    waits = []
    for _ in outbox_ledger.BACKOFF_SECONDS:
        due, failed = (await session.exec(fail)).one()
        assert failed is None
        waits.append((due - now).total_seconds())
    assert waits == [float(wait) for wait in outbox_ledger.BACKOFF_SECONDS]

    _due, failed = (await session.exec(fail)).one()
    assert failed == now
