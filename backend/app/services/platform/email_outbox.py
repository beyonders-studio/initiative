"""Notification email: written down, then sent.

Every notification email in the app is enqueued here and delivered by the
worker below. Three things follow from that, and they are the whole reason it
exists:

* **SMTP leaves the request path.** Creating a comment used to hold its
  transaction open across one SMTP connection per recipient.
* **A failed send is retried** rather than logged and lost. A row is claimed,
  attempted, and either settled or backed off by the rules every queue table
  shares (:mod:`app.services.outbox_ledger`).
* **Several rows for one person can arrive as one message.** That is what makes
  a cadence possible at all, and it is what a hold releases when it lifts.

When a row may go out is decided once, at enqueue, by
:func:`~app.services.platform.notification_prefs.email_due_at` — the account's
cadence, floored by whatever is holding them. Changing a setting rewrites the
due time of everything still pending, which is what lets somebody resume early.

The table is append-only from the request path and read by nothing else: there
is no endpoint over it, and what the recipient sees is the email.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Table, func, insert, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.email_i18n import email_t
from app.core.encryption import (
    SALT_EMAIL,
    decrypt_field,
    encrypt_field,
    hash_email,
    normalize_email,
)
from app.core.notification_categories import Channel, NotificationCategory
from app.db.request_context import Unattributed
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.models.platform.user_notification_prefs import EmailCadence
from app.models.platform.user_token import UserTokenPurpose
from app.services import email as email_service
from app.services import outbox_ledger
from app.services.auth import account_changes, addresses
from app.services.background_tasks import Loop
from app.services.platform import notification_policy, notification_prefs, user_tokens

logger = logging.getLogger(__name__)

#: How often the worker looks for due mail. Mail due at once wakes it
#: (:data:`CHANNEL`); this is for mail that comes due later, and a lost wake.
EMAIL_OUTBOX_POLL_SECONDS = 15

#: Where writing mail that is due at once wakes the worker.
CHANNEL = "email_outbox"

_TABLE: Table = EmailOutboxItem.__table__

#: The rows still waiting to go: a settled row is kept for a while after.
_OPEN = (_TABLE.c.sent_at.is_(None), _TABLE.c.failed_at.is_(None))

#: How long a settled row is kept. Bookkeeping once the mail has gone, but
#: worth having while somebody might still ask whether it did.
RETENTION = timedelta(days=7)

#: Recipients handled per pass. Not a cap on anybody's mail — only on how many
#: people one pass serves before the next one starts.
BATCH_RECIPIENTS = 50

#: How long the "This wasn't me" link in an account letter stays good: long
#: enough to be read after a weekend away.
ANSWER_LINK_MINUTES = 7 * 24 * 60


async def enqueue(
    session: AsyncSession,
    recipient: User,
    *,
    category: NotificationCategory,
    pieces: email_service.EmailPieces,
    guild_id: int | None = None,
    notification_id: int | None = None,
    prefs: Mapping[str, Any] | None = None,
) -> bool:
    """Write one notification email down.

    Runs on whatever session the notifier is already holding — a guild-routed
    request, usually — and appends to ``public.email_outbox``. An append, and
    only that: the row is the worker's from here on.

    The deployment's and the community's switches are applied here as well as
    at send: one of them declining writes nothing, and either of them asking
    for a redacted notification stores the kind of thing that happened instead
    of what it was about — so the row carries no more than the mail will.

    ``prefs`` is the recipient's settings document, which the caller has
    already loaded to decide the email was wanted at all. The switches are read
    once per transaction of ``session``, so a fan-out asks once.
    """
    shown = notification_policy.apply(
        await notification_policy.for_send(session, guild_id),
        pieces,
        category=category,
        locale=getattr(recipient, "locale", None) or "en",
    )
    if shown is None:
        return False
    pieces = shown
    if not await email_service.email_configured(session):
        # Nothing to drain it, so nothing is written. A caller holding a queue
        # keeps it rather than treating this as delivered.
        return False
    if prefs is None:
        prefs = await notification_prefs.load_prefs_for_delivery(recipient.id)

    due = notification_prefs.email_due_at(
        prefs,
        category=category,
        tz_name=recipient.timezone,
        last_active_at=getattr(recipient, "last_active_at", None),
    )
    # Written without reading the row back: the generated id is never used
    # here, and the row is the worker's from this point.
    await session.exec(
        insert(EmailOutboxItem)
        .values(
            user_id=recipient.id,
            notification_id=notification_id,
            category=category.value,
            guild_id=guild_id,
            locale=getattr(recipient, "locale", None) or "en",
            subject=pieces.subject,
            headline=pieces.headline,
            body=pieces.body,
            link=pieces.link,
            link_label=pieces.link_label,
            created_at=datetime.now(UTC),
            deliver_after=due,
        )
        .inline()
    )
    await _wake_if_due(session, due)
    return True


async def _wake_if_due(session: AsyncSession, due: datetime) -> None:
    """Wake the worker once ``session`` commits, when the mail is due now."""
    if due <= datetime.now(UTC):
        await session.exec(select(func.pg_notify(CHANNEL, "")))


async def enqueue_account_letter(
    user: User,
    pieces: email_service.EmailPieces,
    *,
    change: dict[str, Any] | None = None,
    also_to: Sequence[str] = (),
    session: AsyncSession | None = None,
) -> None:
    """Write down a letter the account is owed whatever its notification
    settings: about its own security, or a community whose seat it holds.

    Due at once and marked ``security``: the worker sends it on its own, and
    nothing in the account's notification settings holds or drops it. One row
    per address, so each copy retries on its own: every address the account
    has proved, and ``also_to`` beside them for an address it no longer holds.
    ``change`` names the account notice the letter is and what undoing it
    does; the worker decides, as it sends each copy, what that copy's link
    may do.

    Written on ``session``, a system-engine session the caller commits, where
    the letter belongs to the same transaction as what else it writes; on a
    system session of its own and committed there otherwise, for a letter
    raised once the change it reports has been committed.
    """
    if session is None:
        from app.db.session import SystemSessionLocal

        async with SystemSessionLocal() as own_session:
            await enqueue_account_letter(
                user, pieces, change=change, also_to=also_to, session=own_session
            )
            await own_session.commit()
        return
    now = datetime.now(UTC)
    if not await email_service.email_configured(session):
        return
    own = await addresses.proven_addresses(session, user_id=user.id)
    recipients = list(dict.fromkeys([*own, *also_to]))
    if not recipients:
        return
    await session.exec(
        insert(EmailOutboxItem)
        .values(
            [
                {
                    "user_id": user.id,
                    "category": NotificationCategory.account.value,
                    "security": True,
                    "recipient_encrypted": encrypt_field(address, SALT_EMAIL),
                    "change": change,
                    "locale": getattr(user, "locale", None) or "en",
                    "subject": pieces.subject,
                    "headline": pieces.headline,
                    "body": pieces.body,
                    "link": pieces.link,
                    "link_label": pieces.link_label,
                    "created_at": now,
                    "deliver_after": now,
                }
                for address in recipients
            ]
        )
        .inline()
    )
    await _wake_if_due(session, now)


async def recompute_pending(
    session: AsyncSession,
    *,
    user_id: int,
    prefs: Mapping[str, Any],
    tz_name: str | None,
    last_active_at: datetime | None = None,
) -> int:
    """Re-time everything this account has waiting.

    Called when a setting that decides *when* moves — the cadence, the clock,
    the weekday, the lane, a pause, the timezone. Without it, ending a pause
    early would leave a fortnight of mail sitting behind a date that has not
    arrived, which is not what "resume" can mean.

    Rows are re-timed from now rather than from when they were written: a
    message held for a week is news when the hold lifts, not a week late.
    """
    rows = (
        await session.exec(
            select(EmailOutboxItem).where(
                EmailOutboxItem.user_id == user_id,
                EmailOutboxItem.sent_at.is_(None),
                EmailOutboxItem.failed_at.is_(None),
            )
        )
    ).all()
    now = datetime.now(UTC)
    moved = 0
    soonest: datetime | None = None
    for row in rows:
        record = row[0] if isinstance(row, tuple) else row
        try:
            category = NotificationCategory(record.category)
        except ValueError:  # a category this build no longer has
            continue
        due = notification_prefs.email_due_at(
            prefs,
            category=category,
            tz_name=tz_name,
            last_active_at=last_active_at,
            now=now,
        )
        if due != record.deliver_after:
            record.deliver_after = due
            session.add(record)
            moved += 1
            soonest = due if soonest is None else min(soonest, due)
    if soonest is not None:
        await session.flush()
        await _wake_if_due(session, soonest)
    return moved


def _reason(
    rows: Sequence[EmailOutboxItem],
    *,
    prefs: Mapping[str, Any],
    tz_name: str | None,
    now: datetime,
) -> str:
    """Why this batch is going out now, as the digest's own copy needs it.

    A hold that released them says so; otherwise it is simply the cadence
    coming round.
    """
    lift = notification_prefs.last_lift(prefs, tz_name=tz_name, now=now)
    if lift is not None and any(row.created_at < lift.closed for row in rows):
        return "away"
    cadence = notification_prefs.email_schedule(prefs).cadence
    if cadence is EmailCadence.instant:
        # Several at once under an instant cadence is a flurry, not a schedule.
        return "recent"
    return cadence.value


async def _guild_names(
    session: AsyncSession, rows: Sequence[EmailOutboxItem]
) -> dict[int, str]:
    ids = sorted({row.guild_id for row in rows if row.guild_id is not None})
    if not ids:
        return {}
    found = (await session.exec(select(Guild).where(Guild.id.in_(ids)))).all()
    out: dict[int, str] = {}
    for row in found:
        guild = row[0] if isinstance(row, tuple) else row
        if guild.id is not None:
            out[guild.id] = guild.name
    return out


async def _discard(session: AsyncSession, ids: Sequence[int]) -> None:
    if not ids:
        return
    await session.exec(
        text("DELETE FROM email_outbox WHERE id = ANY(:ids)").bindparams(ids=list(ids))
    )


async def _already_read(
    session: AsyncSession, rows: Sequence[EmailOutboxItem]
) -> set[int]:
    """The rows whose bell line the recipient has since read.

    A digest is what is still waiting. Somebody who has already dealt with a
    mention in the app does not need to be told about it again by email — and a
    row with no bell line at all (the category's bell is switched off) has
    nothing that could supersede it.
    """
    ids = [row.notification_id for row in rows if row.notification_id is not None]
    if not ids:
        return set()
    result = await session.exec(
        text(
            "SELECT id FROM notifications WHERE id = ANY(:ids) AND read_at IS NOT NULL"
        ).bindparams(ids=ids)
    )
    read = {row.id for row in result.all()}
    return {
        row.id for row in rows if row.id is not None and row.notification_id in read
    }


async def _settle(session: AsyncSession, ids: Sequence[int], *, now: datetime) -> None:
    if not ids:
        return
    await session.exec(
        text(
            "UPDATE email_outbox SET sent_at = :now, claimed_at = NULL "
            "WHERE id = ANY(:ids)"
        ).bindparams(now=now, ids=list(ids))
    )


async def _send_one(
    session: AsyncSession,
    *,
    user: User,
    rows: list[EmailOutboxItem],
    now: datetime,
) -> None:
    """Compose and send one account's due mail, then settle it.

    A security letter goes on its own, to every address the account has proved,
    and nothing drops it. The rest is notification mail: anything read in the
    app on the way here, or switched off since it was written — by the
    recipient, the deployment or its community — is dropped, a row whose
    community has started redacting since says the kind of thing that
    happened, and what is left goes as one message or one digest.
    """
    letters = [row for row in rows if row.security]
    rows = [row for row in rows if not row.security]
    prefs = await notification_prefs.load_prefs(session, user.id)
    locale = getattr(user, "locale", None) or "en"
    if rows:
        stale = await _already_read(session, rows)
        policies = await notification_policy.for_send_many(
            session, {row.guild_id for row in rows}
        )
        refused = set()
        for row in rows:
            if row.id in stale:
                continue
            shown = (
                notification_policy.apply(
                    policies[row.guild_id],
                    email_service.EmailPieces(
                        subject=row.subject,
                        headline=row.headline,
                        body=row.body,
                        link=row.link,
                        link_label=row.link_label,
                    ),
                    category=NotificationCategory(row.category),
                    locale=row.locale or locale,
                )
                if _still_wanted(prefs, row)
                else None
            )
            if shown is None:
                refused.add(row.id)
                continue
            row.subject, row.headline, row.body, row.link_label = (
                shown.subject,
                shown.headline,
                shown.body,
                shown.link_label,
            )
        await _discard(session, sorted(stale | refused))
        rows = [row for row in rows if row.id not in stale and row.id not in refused]

    _settings, accent = await email_service.email_context(session)
    for batch in [[letter] for letter in letters] + ([rows] if rows else []):
        ids = [row.id for row in batch]
        try:
            recipient = None
            if len(batch) == 1:
                row = batch[0]
                row_locale = row.locale or locale
                link, link_label = row.link, row.link_label
                if row.recipient_encrypted is not None:
                    recipient = decrypt_field(row.recipient_encrypted, SALT_EMAIL)
                    if row.change is not None:
                        link = await _answer_link(
                            session, user=user, change=row.change, recipient=recipient
                        )
                        if link is not None:
                            link_label = email_t(
                                "accountNotice.notMe", locale=row_locale
                            )
                html_body, text_body = email_service.render_single(
                    email_service.EmailPieces(
                        subject=row.subject,
                        headline=row.headline,
                        body=row.body,
                        link=link,
                        link_label=link_label,
                    ),
                    user=user,
                    accent=accent,
                    locale=row_locale,
                )
                subject = row.subject
            else:
                subject, html_body, text_body = email_service.render_digest(
                    [
                        email_service.DigestLine(
                            category=row.category,
                            guild_id=row.guild_id,
                            body=row.body,
                            link=row.link,
                        )
                        for row in batch
                    ],
                    user=user,
                    accent=accent,
                    locale=locale,
                    reason=_reason(batch, prefs=prefs, tz_name=user.timezone, now=now),
                    guild_names=await _guild_names(session, batch),
                )
            await email_service.deliver(
                session,
                user,
                subject=subject,
                html_body=html_body,
                text_body=text_body,
                every_address=batch[0].security,
                recipient=recipient,
            )
        except Exception as exc:
            # Mail that was configured when these were written and is not now
            # is held the same way: nothing has been lost, and a later pass
            # finds them once it is configured again.
            if not isinstance(exc, email_service.EmailNotConfiguredError):
                logger.exception("email-outbox: send failed for user %s", user.id)
            await session.exec(
                outbox_ledger.back_off(
                    _TABLE, _TABLE.c.id.in_(ids), now=now, spent="failed_at"
                )
            )
            continue
        await _settle(session, ids, now=now)
        logger.info("email-outbox: sent %d item(s) to user %s", len(ids), user.id)


async def _answer_link(
    session: AsyncSession, *, user: User, change: dict[str, Any], recipient: str
) -> str | None:
    """The "This wasn't me" link for one copy of an account letter, or none.

    A copy to an address the account still holds proved may sign it out, and
    undo where :func:`account_changes.may_undo` allows. A copy to the address
    a removal took away may only put it back, and gets no link otherwise; nor
    does a copy to any other address the account no longer holds.

    Its own token, minted as the copy is sent so no raw token is ever stored,
    and committed first so the link never names one that was not kept. It
    records the address it went to and that address's proof time, which the
    link is held to when it is used: the address encrypted, as every stored
    address is, rather than as a hash of a key that may be rotated.
    """
    digest = hash_email(recipient)
    held = (
        await session.exec(
            select(UserEmail).where(
                UserEmail.user_id == user.id,
                UserEmail.email_hash == digest,
                UserEmail.verified_at.is_not(None),
            )
        )
    ).first()
    removed = account_changes.removed_address(change)
    if held is not None:
        proved_at, removed_copy = held.verified_at, False
    elif removed is not None and hash_email(removed) == digest:
        proved_at = datetime.fromisoformat(change["undo"]["proved_at"])
        removed_copy = True
    else:
        return None
    may_undo = account_changes.may_undo(
        change, proved_at=proved_at, removed_copy=removed_copy
    )
    if removed_copy and not may_undo:
        return None
    token = await user_tokens.create_token(
        session,
        user_id=user.id,
        purpose=UserTokenPurpose.account_change,
        expires_minutes=ANSWER_LINK_MINUTES,
        change={
            **change,
            "recipient": encrypt_field(normalize_email(recipient), SALT_EMAIL),
            "recipient_proved_at": proved_at.isoformat() if proved_at else None,
            "removed_copy": removed_copy,
            "may_undo": may_undo,
        },
    )
    return email_service.account_change_link(token)


def _still_wanted(prefs: Mapping[str, Any], row: EmailOutboxItem) -> bool:
    try:
        category = NotificationCategory(row.category)
    except ValueError:
        return False
    return notification_prefs.wants(
        prefs,
        category=category,
        channel=Channel.email,
        guild_id=row.guild_id,
    )


async def _run_pass(session: AsyncSession, *, now: datetime) -> None:
    """Send whatever is due, one recipient at a time.

    Recipients do not queue behind each other: unlike a webhook subscription
    there is no order to keep, so one account's failing mail server holds up
    only that account.
    """
    user_ids = await outbox_ledger.due_recipients(
        session,
        EmailOutboxItem,
        now=now,
        limit=BATCH_RECIPIENTS,
        still_open=_OPEN,
    )
    for user_id in user_ids:
        # One recipient at a time, held until their mail is settled.
        rows = await outbox_ledger.claim(
            session, EmailOutboxItem, [user_id], now=now, still_open=_OPEN
        )
        if not rows:
            continue
        user = (
            await session.exec(select(User).where(User.id == user_id))
        ).one_or_none()
        if user is None:
            # Deleted between the scan and the claim; the cascade will take
            # the rows, and there is nobody to send to meanwhile.
            await session.commit()
            continue
        await _send_one(session, user=user, rows=rows, now=now)
        await session.commit()


async def hint(_payload: str) -> None:
    """Mail due at once was written. Registered on :data:`CHANNEL`."""
    loop.wake()


async def process_email_outbox() -> None:
    from app.db.session import SystemSessionLocal, set_rls_context

    async with SystemSessionLocal() as session:
        await set_rls_context(session, Unattributed())
        await _run_pass(session, now=datetime.now(UTC))


async def sweep_settled(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Drop rows that have gone out, or run out of attempts, and are old enough
    that nobody is still asking about them."""
    cutoff = (now or datetime.now(UTC)) - RETENTION
    result = await session.exec(
        text(
            "DELETE FROM email_outbox "
            "WHERE (sent_at IS NOT NULL OR failed_at IS NOT NULL) "
            "  AND created_at < :cutoff"
        ).bindparams(cutoff=cutoff)
    )
    return result.rowcount or 0


#: The worker's loop: woken as mail due at once is written, and run every
#: :data:`EMAIL_OUTBOX_POLL_SECONDS` for the rest.
loop = Loop("email-outbox", interval=EMAIL_OUTBOX_POLL_SECONDS)
