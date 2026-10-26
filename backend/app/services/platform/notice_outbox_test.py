"""The notice worker: a notice waits for the request that caused it, is
delivered once, says no more than the community allows, and a push nobody
answered is tried again without a second bell line."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import category_of
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import Notification, NotificationType
from app.services import notifications
from app.services.platform import (
    email_outbox,
    notice_outbox,
    notification_policy,
    push_notifications,
)
from app.testing import (
    create_guild,
    create_push_token,
    create_user,
    push_switched_on,
    set_notification_prefs,
)
from app.testing.sockets import settle


@pytest.fixture
def fcm(monkeypatch):
    """FCM, answering however the test says, and what was put on the wire:
    each title, and each data payload and badge under ``answer["data"]`` and
    ``answer["badge"]``."""
    calls: list[str] = []
    answer: dict = {"now": (True, False), "data": [], "badge": []}

    async def _send(
        client,
        push_token,
        title,
        body,
        data=None,
        channel_id=None,
        platform=None,
        badge=None,
    ):
        calls.append(title)
        answer["data"].append(data)
        answer["badge"].append(badge)
        return answer["now"]

    monkeypatch.setattr(push_notifications, "send_push_notification", _send)
    with push_switched_on():
        yield calls, answer


async def _mention(session: AsyncSession, guild_id: int, recipient, actor) -> None:
    await set_rls_context(session, SystemGuild(guild_id))
    await notifications.notify(
        session,
        NotificationType.mention,
        [recipient.id],
        about=None,
        key="mention.comment",
        values={"actor": "Ana", "context": "Q3 budget"},
        actor=actor,
    )


async def _deliver(session: AsyncSession, at: datetime) -> None:
    await set_rls_context(session, Unattributed())
    await notice_outbox._run_pass(session, now=at)


async def _lines(session: AsyncSession, user_id: int) -> list[Notification]:
    await set_rls_context(session, Unattributed())
    rows = await session.exec(
        select(Notification).where(Notification.user_id == user_id)
    )
    return list(rows.all())


async def _waiting(session: AsyncSession) -> list[NoticeOutboxItem]:
    await set_rls_context(session, Unattributed())
    return list((await session.exec(select(NoticeOutboxItem))).all())


async def test_a_notice_is_delivered_once_and_only_if_its_request_commits(
    session: AsyncSession, fcm, monkeypatch
):
    pushed, answer = fcm
    mailed: list[tuple[int, int | None]] = []

    async def _mail(_session, recipient, *, notification_id=None, **_rest):
        mailed.append((recipient.id, notification_id))
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _mail)
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    await create_push_token(session, recipient)
    await session.commit()
    guild_id = guild.id

    # A request that rolls back tells nobody.
    await _mention(session, guild_id, recipient, actor)
    await session.rollback()
    await set_rls_context(session, Unattributed())
    for user in (recipient, actor):
        await session.refresh(user)
    await _deliver(session, datetime.now(timezone.utc))
    assert await _lines(session, recipient.id) == []
    assert pushed == [] and mailed == []

    await _mention(session, guild_id, recipient, actor)
    await session.commit()
    await _deliver(session, datetime.now(timezone.utc))
    await _deliver(session, datetime.now(timezone.utc))

    [line] = await _lines(session, recipient.id)
    assert mailed == [(recipient.id, line.id)]
    assert pushed == ["You were mentioned"]
    # The badge counts the line the push announces.
    assert answer["badge"] == [1]
    assert await _waiting(session) == []


async def test_a_redacting_community_writes_down_no_more_than_it_will_say(
    session: AsyncSession,
):
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    guild.redact_notification_content = True
    session.add(guild)
    await session.commit()

    with push_switched_on():
        await _mention(session, guild.id, recipient, actor)
    await session.commit()

    [row] = await _waiting(session)
    title, body = notification_policy.redacted_line(
        category_of(NotificationType.mention), "en"
    )
    assert (row.push_title, row.push_body) == (title, body)
    assert row.email_subject == title
    assert "Q3 budget" not in f"{row.push_body} {row.email_body} {row.email_subject}"


async def test_a_push_of_its_own_writes_no_line(session: AsyncSession, fcm):
    """A digest or a hold summary is a push and nothing else: the bell already
    holds what it counts. It goes under the switches of the communities it
    gathers from as they stand when it is sent: while one of them still sends
    push it goes, saying only the kind of thing once another has stopped, and
    carrying no more data than where tapping it opens."""
    pushed, answer = fcm
    recipient = await create_user(session)
    guild = await create_guild(session, creator=recipient)
    sending = await create_guild(session, creator=recipient)
    await create_push_token(session, recipient)
    await notice_outbox.enqueue(
        session,
        [
            await notice_outbox.notice(
                session,
                recipient,
                NotificationType.overdue_tasks,
                {},
                guild_id=None,
                push=("2 tasks overdue", "Q3 budget and 1 more"),
                push_data={"target_path": "/", "count": "2"},
                communities={guild.id, sending.id},
                kind="push",
            )
        ],
    )
    guild.allow_push_notifications = False
    session.add(guild)
    await session.commit()

    await _deliver(session, datetime.now(timezone.utc))

    title, _body = notification_policy.redacted_line(
        category_of(NotificationType.overdue_tasks), "en"
    )
    assert pushed == [title]
    assert answer["data"] == [{"target_path": "/"}]
    assert await _lines(session, recipient.id) == []
    assert await _waiting(session) == []


async def test_a_push_nobody_answered_is_tried_again_without_a_second_line(
    session: AsyncSession, fcm
):
    """…and given up once it has waited out every step."""
    pushed, answer = fcm
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    await create_push_token(session, recipient)
    answer["now"] = (False, False)
    await _mention(session, guild.id, recipient, actor)
    await session.commit()
    start = datetime.now(timezone.utc)
    await _deliver(session, start)
    [row] = await _waiting(session)
    assert row.attempts == 1 and row.bell_written_at is not None
    await _deliver(session, start)  # not due yet
    assert len(pushed) == 1

    answer["now"] = (True, False)
    await _deliver(session, start + timedelta(seconds=31))
    assert len(pushed) == 2
    assert await _waiting(session) == []
    assert len(await _lines(session, recipient.id)) == 1

    answer["now"] = (False, False)
    await _mention(session, guild.id, recipient, actor)
    await session.commit()
    at = start + timedelta(seconds=31)
    for wait in (*notice_outbox.BACKOFF_SECONDS, 0):
        await _deliver(session, at)
        at += timedelta(seconds=wait + 1)
    assert await _waiting(session) == []
    assert len(pushed) == 2 + len(notice_outbox.BACKOFF_SECONDS) + 1
    assert len(await _lines(session, recipient.id)) == 2


async def test_a_retry_follows_the_communitys_switches_as_they_stand_then(
    session: AsyncSession, fcm
):
    """A community that starts redacting gets the kind of thing that
    happened; one that turns push off gets nothing more."""
    pushed, answer = fcm
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    await create_push_token(session, recipient)
    await session.commit()

    answer["now"] = (False, False)
    for _ in range(2):
        await _mention(session, guild.id, recipient, actor)
    await session.commit()
    start = datetime.now(timezone.utc)
    await _deliver(session, start)
    assert len(pushed) == 2

    guild.redact_notification_content = True
    session.add(guild)
    await session.commit()
    answer["now"] = (True, False)
    await _deliver(session, start + timedelta(seconds=31))
    title, _body = notification_policy.redacted_line(
        category_of(NotificationType.mention), "en"
    )
    assert pushed[2:] == [title, title]

    answer["now"] = (False, False)
    await _mention(session, guild.id, recipient, actor)
    await session.commit()
    at = datetime.now(timezone.utc)
    await _deliver(session, at)
    guild.allow_push_notifications = False
    session.add(guild)
    await session.commit()
    await _deliver(session, at + timedelta(seconds=31))
    assert len(pushed) == 5
    assert await _waiting(session) == []


async def test_a_bell_line_that_cannot_be_written_is_never_given_up(
    session: AsyncSession, fcm, monkeypatch
):
    """…and once it is written, its push has every attempt of its own."""
    pushed, answer = fcm
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    await create_push_token(session, recipient)
    await session.commit()

    async def _broken(*_args, **_kwargs):
        raise RuntimeError("the bell is down")

    working = notifications.deliver_notices
    monkeypatch.setattr(notifications, "deliver_notices", _broken)
    await _mention(session, guild.id, recipient, actor)
    await session.commit()
    at = datetime.now(timezone.utc)
    for wait in (*notice_outbox.BACKOFF_SECONDS, notice_outbox.BACKOFF_SECONDS[-1]):
        await _deliver(session, at)
        at += timedelta(seconds=wait + 1)

    [row] = await _waiting(session)
    assert row.attempts == len(notice_outbox.BACKOFF_SECONDS) + 1
    assert row.bell_written_at is None

    monkeypatch.setattr(notifications, "deliver_notices", working)
    answer["now"] = (False, False)
    await _deliver(session, at)
    [row] = await _waiting(session)
    assert row.bell_written_at is not None and row.attempts == 1
    assert len(pushed) == 1


async def test_a_reaction_taken_back_while_its_line_waits_leaves_nothing(
    session: AsyncSession, monkeypatch
):
    """A reaction whose line failed to write waits out a backoff; taking it
    back meanwhile must not leave the retry to write it anyway. Reaction ids
    are each community's own, so another community's reaction with the same
    id is left to arrive."""
    recipient = await create_user(session)
    here = await create_guild(session, creator=recipient)
    elsewhere = await create_guild(session, creator=recipient)
    await session.commit()
    target = {"target_type": "comment", "target_id": 5}

    async def _enqueue(guild_id: int, kind: str, data: dict) -> None:
        await set_rls_context(session, SystemGuild(guild_id))
        await notice_outbox.enqueue(
            session,
            [
                notice_outbox.row(
                    recipient.id,
                    guild_id,
                    NotificationType.comment_reaction,
                    {**target, **data},
                    kind=kind,
                )
            ],
        )
        await session.commit()

    working = notifications._roll_up_reaction

    async def _broken(*_args, **_kwargs):
        raise RuntimeError("the bell is down")

    monkeypatch.setattr(notifications, "_roll_up_reaction", _broken)
    for guild_id in (here.id, elsewhere.id):
        await _enqueue(
            guild_id, "reaction", {"entry": {"id": 7, "emoji": "+1", "reactor_id": 3}}
        )
    now = datetime.now(timezone.utc)
    await _deliver(session, now)
    monkeypatch.setattr(notifications, "_roll_up_reaction", working)

    await _enqueue(
        here.id, "withdraw", {"reaction_id": 7, "reactor_id": 3, "emoji": "+1"}
    )
    await _deliver(session, datetime.now(timezone.utc))
    await _deliver(session, now + timedelta(seconds=31))

    assert await _waiting(session) == []
    assert [line.guild_id for line in await _lines(session, recipient.id)] == [
        elsewhere.id
    ]


def _alerts(socket) -> list[dict]:
    return [frame for frame in socket.sent if frame.get("resource") == "alert"]


async def test_a_delivered_line_is_announced_to_the_desktop(
    session: AsyncSession, account_socket
):
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    await session.commit()
    app = account_socket(recipient.id)

    await _mention(session, guild.id, recipient, actor)
    await session.commit()
    await _deliver(session, datetime.now(timezone.utc))
    await settle()

    [line] = await _lines(session, recipient.id)
    [alert] = _alerts(app)
    assert alert["ids"] == {"notifications": [line.id]}


@pytest.mark.parametrize("refusal", ["desktop-off", "push-switched-off"])
async def test_no_desktop_alert_where_it_is_refused(
    session: AsyncSession, account_socket, refusal
):
    actor = await create_user(session)
    recipient = await create_user(session)
    guild = await create_guild(session, creator=actor)
    if refusal == "desktop-off":
        await set_notification_prefs(
            session, recipient, {"categories": {"mentions": {"desktop": False}}}
        )
    else:
        guild.allow_push_notifications = False
        session.add(guild)
    await session.commit()
    app = account_socket(recipient.id)

    await _mention(session, guild.id, recipient, actor)
    await session.commit()
    await _deliver(session, datetime.now(timezone.utc))
    await settle()

    assert len(await _lines(session, recipient.id)) == 1
    assert _alerts(app) == []


async def test_a_reaction_alerts_the_desktop_once_per_line(
    session: AsyncSession, account_socket
):
    """Phones hear about reactions in a digest; the desktop when the line
    opens, and not again for each reaction that joins it."""
    recipient = await create_user(session)
    guild = await create_guild(session, creator=recipient)
    await session.commit()
    app = account_socket(recipient.id)

    for reaction_id in (7, 8):
        await set_rls_context(session, SystemGuild(guild.id))
        await notice_outbox.enqueue(
            session,
            [
                notice_outbox.row(
                    recipient.id,
                    guild.id,
                    NotificationType.comment_reaction,
                    {
                        "target_type": "comment",
                        "target_id": 5,
                        "entry": {"id": reaction_id, "emoji": "+1", "reactor_id": 3},
                    },
                    kind="reaction",
                )
            ],
        )
        await session.commit()
        await _deliver(session, datetime.now(timezone.utc))
    await settle()

    [line] = await _lines(session, recipient.id)
    assert [alert["ids"] for alert in _alerts(app)] == [{"notifications": [line.id]}]
