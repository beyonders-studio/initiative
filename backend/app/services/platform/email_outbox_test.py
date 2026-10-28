"""The outbox: written down, timed, composed, sent once.

The worker is the only thing that sends notification email, so these cover the
four decisions it makes — what is due, what has been superseded, what the
account still wants, and whether one message or several.
"""

import re
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import hash_email
from app.core.notification_categories import NotificationCategory
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.notification import NotificationType
from app.models.platform.user_token import UserToken, UserTokenPurpose
from app.services import email as email_service
from app.services.auth import account_changes, addresses
from app.services.platform import email_outbox, user_notifications
from app.testing import create_guild, create_user, set_notification_prefs
from app.services.platform import rules


def _pieces(
    body: str = "<strong>Alice</strong> mentioned you",
) -> email_service.EmailPieces:
    return email_service.EmailPieces(
        subject="You were mentioned",
        headline="You were mentioned",
        body=body,
        link="https://example.test/x",
    )


async def _rows(session: AsyncSession, user_id: int) -> list[EmailOutboxItem]:
    result = await session.exec(
        select(EmailOutboxItem)
        .where(EmailOutboxItem.user_id == user_id)
        .order_by(EmailOutboxItem.id)
    )
    return [row[0] if isinstance(row, tuple) else row for row in result.all()]


@pytest.fixture
def configured(monkeypatch):
    """A deployment that can send mail."""
    monkeypatch.setattr(email_service, "email_configured", AsyncMock(return_value=True))


@pytest.fixture
def sent(monkeypatch):
    """Capture what actually goes on the wire."""
    calls: list[dict] = []

    async def _deliver(
        session,
        user,
        *,
        subject,
        html_body,
        text_body,
        every_address=False,
        recipient=None,
    ):
        calls.append(
            {
                "user_id": user.id,
                "subject": subject,
                "html": html_body,
                "text": text_body,
                "every_address": every_address,
                "recipient": recipient,
            }
        )

    monkeypatch.setattr(email_service, "deliver", _deliver)
    monkeypatch.setattr(
        email_service, "email_context", AsyncMock(return_value=(None, "#123456"))
    )
    return calls


async def test_an_install_with_no_mail_server_queues_nothing(
    session: AsyncSession, monkeypatch
):
    """Otherwise it grows a table nothing will ever drain."""
    monkeypatch.setattr(
        email_service, "email_configured", AsyncMock(return_value=False)
    )
    user = await create_user(session, email="no-smtp@example.com")
    wrote = await email_outbox.enqueue(
        session, user, category=NotificationCategory.mentions, pieces=_pieces()
    )
    await session.commit()
    assert wrote is False
    assert await _rows(session, user.id) == []


async def test_instant_is_due_immediately(session: AsyncSession, configured):
    user = await create_user(session, email="instant@example.com")
    before = datetime.now(timezone.utc)
    assert await email_outbox.enqueue(
        session, user, category=NotificationCategory.mentions, pieces=_pieces()
    )
    await session.commit()
    (row,) = await _rows(session, user.id)
    assert row.deliver_after <= before + timedelta(seconds=5)


async def test_a_cadence_defers_the_row(session: AsyncSession, configured):
    user = await create_user(session, email="cadence@example.com", timezone="UTC")
    await set_notification_prefs(
        session, user, {"email": {"cadence": "daily", "at": "08:00"}}
    )
    # A comment is not addressed to anybody, so the lane does not carry it.
    assert await email_outbox.enqueue(
        session, user, category=NotificationCategory.subscriptions, pieces=_pieces()
    )
    await session.commit()
    (row,) = await _rows(session, user.id)
    assert row.deliver_after > datetime.now(timezone.utc)
    assert row.deliver_after.astimezone(timezone.utc).hour == 8


async def test_one_row_goes_out_as_one_message(session: AsyncSession, configured, sent):
    user = await create_user(session, email="single@example.com")
    await email_outbox.enqueue(
        session, user, category=NotificationCategory.mentions, pieces=_pieces()
    )
    await session.commit()

    await email_outbox._run_pass(session, now=datetime.now(timezone.utc))
    assert len(sent) == 1
    assert sent[0]["subject"] == "You were mentioned"
    assert "mentioned you" in sent[0]["html"]
    (row,) = await _rows(session, user.id)
    assert row.sent_at is not None


async def test_several_rows_go_out_as_one_digest(
    session: AsyncSession, configured, sent
):
    user = await create_user(session, email="digest@example.com")
    guild = await create_guild(session, creator=user)
    for body in ("<strong>Alpha</strong> happened", "<strong>Beta</strong> happened"):
        await email_outbox.enqueue(
            session,
            user,
            category=NotificationCategory.subscriptions,
            guild_id=guild.id,
            pieces=_pieces(body),
        )
    await session.commit()

    await email_outbox._run_pass(session, now=datetime.now(timezone.utc))
    assert len(sent) == 1
    html = sent[0]["html"]
    # One message, both lines, grouped under the community they happened in.
    assert "Alpha" in html and "Beta" in html
    assert guild.name in html
    assert "2" in sent[0]["subject"]


async def test_a_line_read_in_the_app_is_not_emailed(
    session: AsyncSession, configured, sent
):
    """A digest is what is still waiting."""
    user = await create_user(session, email="superseded@example.com")
    notification = await user_notifications.create_notification(
        session,
        user_id=user.id,
        notification_type=NotificationType.mention,
        data={},
    )
    assert notification is not None
    await email_outbox.enqueue(
        session,
        user,
        category=NotificationCategory.mentions,
        notification_id=notification.id,
        pieces=_pieces(),
    )
    notification.read_at = datetime.now(timezone.utc)
    await session.commit()

    await email_outbox._run_pass(session, now=datetime.now(timezone.utc))
    assert sent == []
    assert await _rows(session, user.id) == []


async def test_a_row_with_no_bell_line_is_never_superseded(
    session: AsyncSession, configured, sent
):
    """A category whose bell is switched off has nothing that could supersede
    its email."""
    user = await create_user(session, email="no-bell@example.com")
    await email_outbox.enqueue(
        session, user, category=NotificationCategory.mentions, pieces=_pieces()
    )
    await session.commit()
    await email_outbox._run_pass(session, now=datetime.now(timezone.utc))
    assert len(sent) == 1


async def test_a_channel_switched_off_after_writing_is_not_delivered(
    session: AsyncSession, configured, sent
):
    """By the recipient or by the row's community, which may also have started
    redacting since; a security letter goes regardless, on its own."""
    user = await create_user(session, email="switched-off@example.com")
    quiet = await create_guild(session, creator=user)
    redacting = await create_guild(session, creator=user)
    await email_outbox.enqueue(
        session, user, category=NotificationCategory.mentions, pieces=_pieces()
    )
    for guild in (quiet, redacting):
        await email_outbox.enqueue(
            session,
            user,
            category=NotificationCategory.subscriptions,
            guild_id=guild.id,
            pieces=_pieces(body="<strong>Alice</strong> replied on Q3 budget"),
        )
    await set_notification_prefs(
        session,
        user,
        {"categories": {"mentions": {"email": False}, "account": {"email": False}}},
    )
    await rules.put(session, "allow_email_notifications", False, guild_id=quiet.id)
    await rules.put(session, "redact_notification_content", True, guild_id=redacting.id)
    session.add_all([quiet, redacting])
    await session.commit()
    await email_outbox.enqueue_account_letter(
        user, _pieces(body="Your password was changed")
    )

    await email_outbox._run_pass(session, now=datetime.now(timezone.utc))
    letter, reply = sent
    assert letter["recipient"] == "switched-off@example.com"
    assert "Your password was changed" in letter["html"]
    assert reply["subject"] == "Something you subscribed to changed"
    assert "Q3 budget" not in reply["html"]
    assert [row.sent_at is not None for row in await _rows(session, user.id)] == [
        True,
        True,
    ]


async def test_an_account_letter_goes_to_each_address_with_its_own_link(
    session: AsyncSession, configured, sent
):
    """One copy per proved address, each sent alone with a "This wasn't me"
    link of its own that records where it went. An address named beside them,
    which the account no longer holds, gets its copy with no link."""
    user = await create_user(session, email="first@example.com")
    addresses.record_address(
        session,
        user_id=user.id,
        email="second@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()
    await email_outbox.enqueue_account_letter(
        user,
        _pieces(body="A passkey was added"),
        change={"notice": "passkey.added"},
        also_to=["gone@example.com"],
    )

    await email_outbox._run_pass(session, now=datetime.now(timezone.utc))
    own = ["first@example.com", "second@example.com"]
    assert sorted(letter["recipient"] for letter in sent) == sorted(
        [*own, "gone@example.com"]
    )
    links = {
        letter["recipient"]: re.search(
            r"/account/not-me\?token=([\w-]+)", letter["html"]
        )
        for letter in sent
    }
    assert links["gone@example.com"] is None
    assert len({links[address].group(1) for address in own}) == 2

    tokens = (
        await session.exec(
            select(UserToken).where(
                UserToken.user_id == user.id,
                UserToken.purpose == UserTokenPurpose.account_change,
            )
        )
    ).all()
    assert sorted(
        account_changes.recipient_hash(token.change or {}) for token in tokens
    ) == sorted(hash_email(address) for address in own)
    assert {(token.change or {})["notice"] for token in tokens} == {"passkey.added"}


async def test_an_account_letter_without_a_notice_carries_no_link(
    session: AsyncSession, configured, sent
):
    """A lockout is not a change anybody made, so there is nothing to answer."""
    user = await create_user(session, email="locked@example.com")
    await email_outbox.enqueue_account_letter(user, _pieces(body="Locked"))

    await email_outbox._run_pass(session, now=datetime.now(timezone.utc))
    [letter] = sent
    assert "/account/not-me" not in letter["html"]


async def test_a_failed_send_backs_off_rather_than_vanishing(
    session: AsyncSession, configured, monkeypatch
):
    user = await create_user(session, email="retry@example.com")
    await email_outbox.enqueue(
        session, user, category=NotificationCategory.mentions, pieces=_pieces()
    )
    await session.commit()

    monkeypatch.setattr(
        email_service, "email_context", AsyncMock(return_value=(None, "#123456"))
    )
    monkeypatch.setattr(
        email_service, "deliver", AsyncMock(side_effect=RuntimeError("smtp down"))
    )
    now = datetime.now(timezone.utc)
    await email_outbox._run_pass(session, now=now)

    (row,) = await _rows(session, user.id)
    assert row.sent_at is None
    assert row.attempts == 1
    assert row.failed_at is None
    assert row.deliver_after > now
    assert row.claimed_at is None


async def test_changing_when_you_read_re_times_what_is_waiting(
    session: AsyncSession, configured
):
    """Resuming early has to release what the pause was holding."""
    user = await create_user(session, email="retime@example.com", timezone="UTC")
    until = datetime.now(timezone.utc) + timedelta(days=7)
    await set_notification_prefs(
        session,
        user,
        {
            "pause": {
                "since": datetime.now(timezone.utc).isoformat(),
                "until": until.isoformat(),
            }
        },
    )
    await email_outbox.enqueue(
        session, user, category=NotificationCategory.mentions, pieces=_pieces()
    )
    await session.commit()
    (row,) = await _rows(session, user.id)
    assert row.deliver_after >= until - timedelta(minutes=1)

    moved = await email_outbox.recompute_pending(
        session, user_id=user.id, prefs={}, tz_name="UTC"
    )
    await session.commit()
    assert moved == 1
    (row,) = await _rows(session, user.id)
    assert row.deliver_after <= datetime.now(timezone.utc) + timedelta(seconds=5)


async def test_settled_mail_is_swept_and_waiting_mail_is_not(
    session: AsyncSession, configured
):
    user = await create_user(session, email="sweep@example.com")
    for _ in range(2):
        await email_outbox.enqueue(
            session, user, category=NotificationCategory.mentions, pieces=_pieces()
        )
    await session.commit()
    rows = await _rows(session, user.id)
    old = datetime.now(timezone.utc) - timedelta(days=30)
    await session.exec(
        text(
            "UPDATE email_outbox SET sent_at = :old, created_at = :old WHERE id = :id"
        ).bindparams(old=old, id=rows[0].id)
    )
    await session.commit()

    dropped = await email_outbox.sweep_settled(session)
    await session.commit()
    assert dropped == 1
    assert [row.id for row in await _rows(session, user.id)] == [rows[1].id]


async def test_going_back_to_instant_releases_what_a_digest_was_holding(
    session: AsyncSession, configured
):
    """Choosing a digest and changing your mind has to let the mail out.

    Otherwise somebody who tried "once a week" on a Tuesday would wait until
    the following Monday to discover they had gone back to instant.
    """
    user = await create_user(
        session, email="back-to-instant@example.com", timezone="UTC"
    )
    weekly = {"email": {"cadence": "weekly", "at": "09:00", "weekday": 1}}
    await set_notification_prefs(session, user, weekly)
    await email_outbox.enqueue(
        session, user, category=NotificationCategory.subscriptions, pieces=_pieces()
    )
    await session.commit()

    # Held for the weekly slot rather than sent now. Asserted as "it *is* that
    # slot" rather than "it is more than a day away": the next Monday 09:00 is
    # eleven hours off if this runs on a Sunday evening, and the day-away form
    # then fails on the clock rather than on the behaviour.
    (row,) = await _rows(session, user.id)
    assert row.deliver_after > datetime.now(timezone.utc)
    assert row.deliver_after.weekday() == 0  # the configured weekday
    assert (row.deliver_after.hour, row.deliver_after.minute) == (9, 0)

    moved = await email_outbox.recompute_pending(
        session,
        user_id=user.id,
        prefs={"email": {"cadence": "instant"}},
        tz_name="UTC",
    )
    await session.commit()
    assert moved == 1
    (row,) = await _rows(session, user.id)
    assert row.deliver_after <= datetime.now(timezone.utc) + timedelta(seconds=5)
