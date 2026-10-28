"""What a notification may leave the app carrying.

Two levels answer three questions, and the stricter of each pair binds. The
tests below cover the resolution itself and then where it is applied — as a
push and a notification email are written down — because a switch that
resolves correctly and is not read anywhere is not a switch.
"""

from unittest.mock import AsyncMock

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import NotificationCategory, category_of
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.notification import NotificationType
from app.services import email as email_service
from app.services.platform import (
    email_outbox,
    notice_outbox,
    notification_policy,
)
from app.testing import (
    create_guild,
    create_user,
    push_switched_on,
)
from app.services.platform import rules


async def _platform(session: AsyncSession, **fields: bool) -> None:
    """Set the deployment's answers, as an owner's PUT would."""
    for name, value in fields.items():
        await rules.put(session, name, value)
    await session.commit()


def _pieces() -> email_service.EmailPieces:
    return email_service.EmailPieces(
        subject="Ana mentioned you in Q3 budget",
        headline="Ana mentioned you in Q3 budget",
        body="<strong>Ana</strong> mentioned you in <strong>Q3 budget</strong>",
        link="https://example.test/x",
    )


@pytest.fixture
def configured(monkeypatch):
    """A deployment that can send mail."""
    monkeypatch.setattr(email_service, "email_configured", AsyncMock(return_value=True))


# --- resolution --------------------------------------------------------------


async def test_a_fresh_deployment_restricts_nothing(session: AsyncSession) -> None:
    """The shape the app had before any of this existed."""
    guild = await create_guild(session)
    assert await notification_policy.resolve(session, guild.id) == (
        notification_policy.UNRESTRICTED
    )
    assert await notification_policy.resolve(session, None) == (
        notification_policy.UNRESTRICTED
    )


async def test_the_deployment_binds_every_community(session: AsyncSession) -> None:
    guild = await create_guild(session)
    await _platform(session, push_notifications_enabled=False)

    assert (await notification_policy.resolve(session, guild.id)).push is False
    assert (await notification_policy.resolve(session, None)).push is False


async def test_a_community_answers_only_for_itself(session: AsyncSession) -> None:
    quiet = await create_guild(session)
    other = await create_guild(session)
    await rules.put(session, "allow_push_notifications", False, guild_id=quiet.id)
    await rules.put(session, "redact_notification_content", True, guild_id=quiet.id)
    await session.commit()

    here = await notification_policy.resolve(session, quiet.id)
    assert here.push is False
    assert here.redact is True

    elsewhere = await notification_policy.resolve(session, other.id)
    assert elsewhere == notification_policy.UNRESTRICTED
    # A notification belonging to no community is the deployment's answer alone.
    assert await notification_policy.resolve(session, None) == (
        notification_policy.UNRESTRICTED
    )


async def test_the_stricter_of_the_pair_binds(session: AsyncSession) -> None:
    """A community may narrow what the deployment permits, never widen it."""
    guild = await create_guild(session)
    await rules.put(session, "allow_push_notifications", True, guild_id=guild.id)
    await rules.put(session, "allow_email_notifications", True, guild_id=guild.id)
    await rules.put(session, "redact_notification_content", False, guild_id=guild.id)
    await session.commit()
    await _platform(
        session,
        push_notifications_enabled=False,
        email_notifications_enabled=False,
        redact_notification_content=True,
    )

    resolved = await notification_policy.resolve(session, guild.id)
    assert (resolved.push, resolved.email, resolved.redact) == (False, False, True)


async def test_resolve_many_answers_each_community(session: AsyncSession) -> None:
    """What a cross-guild digest needs: one answer per community it gathered
    from, and one for the items belonging to none."""
    quiet = await create_guild(session)
    loud = await create_guild(session)
    await rules.put(session, "allow_email_notifications", False, guild_id=quiet.id)
    await session.commit()

    answers = await notification_policy.resolve_many(session, [quiet.id, loud.id, None])

    assert answers[quiet.id].email is False
    assert answers[loud.id].email is True
    assert answers[None].email is True


async def test_a_community_that_no_longer_exists_is_answered_by_the_deployment(
    session: AsyncSession,
) -> None:
    """A row's community can be deleted between the write and the send."""
    await _platform(session, redact_notification_content=True)
    resolved = await notification_policy.resolve(session, 10_000_000)
    assert resolved.redact is True
    assert resolved.push is True


# --- the redacted wording ----------------------------------------------------


async def test_a_redacted_line_says_the_kind_of_thing_and_stops() -> None:
    title, body = notification_policy.redacted_line(
        category_of(NotificationType.mention), "en"
    )
    assert title == "You were mentioned or answered"
    assert body == "Open Initiative to see where."


async def test_every_category_has_a_redacted_line() -> None:
    """A category with no line of its own would push its own key at somebody."""
    for category in NotificationCategory:
        subject, body = notification_policy.redacted_line(category, "en")
        assert not subject.startswith("redacted."), category
        assert not body.startswith("redacted."), category


# --- the push seam -----------------------------------------------------------


@pytest.fixture
def push_on():
    """A deployment wired to FCM."""
    with push_switched_on():
        yield


async def _mention_push(session: AsyncSession, user, guild_id: int) -> tuple:
    """The push a notice of a mention writes down for ``user``."""
    row = await notice_outbox.notice(
        session,
        user,
        NotificationType.mention,
        {},
        guild_id=guild_id,
        push=(
            "Ana mentioned you in Q3 budget",
            "Ana mentioned you in a comment on Q3 budget",
        ),
    )
    return row["push_title"], row["push_body"]


async def test_a_community_that_declines_push_gets_none(
    session: AsyncSession, push_on
) -> None:
    guild = await create_guild(session)
    await rules.put(session, "allow_push_notifications", False, guild_id=guild.id)
    await session.commit()
    user = await create_user(session, email="declines-push@example.com")

    assert await _mention_push(session, user, guild.id) == (None, None)


async def test_a_redacting_community_sends_the_kind_of_thing(
    session: AsyncSession, push_on
) -> None:
    guild = await create_guild(session)
    await rules.put(session, "redact_notification_content", True, guild_id=guild.id)
    await session.commit()
    user = await create_user(session, email="redacts@example.com")

    assert await _mention_push(session, user, guild.id) == (
        "You were mentioned or answered",
        "Open Initiative to see where.",
    )


async def test_an_unrestricted_community_pushes_what_it_was_given(
    session: AsyncSession, push_on
) -> None:
    guild = await create_guild(session)
    user = await create_user(session, email="unrestricted-push@example.com")

    title, _body = await _mention_push(session, user, guild.id)
    assert title == "Ana mentioned you in Q3 budget"


async def test_a_redacted_push_reads_the_recipients_language(
    session: AsyncSession, push_on
) -> None:
    guild = await create_guild(session)
    await rules.put(session, "redact_notification_content", True, guild_id=guild.id)
    await session.commit()
    user = await create_user(session, email="french-push@example.com", locale="fr")

    title, _body = await _mention_push(session, user, guild.id)
    assert title == "Vous avez été mentionné ou on vous a répondu"


# --- the email seam ----------------------------------------------------------


async def _outbox(session: AsyncSession, user_id: int) -> list[EmailOutboxItem]:
    result = await session.exec(
        select(EmailOutboxItem).where(EmailOutboxItem.user_id == user_id)
    )
    return [row[0] if isinstance(row, tuple) else row for row in result.all()]


async def test_a_community_that_declines_email_writes_nothing(
    session: AsyncSession, configured
) -> None:
    guild = await create_guild(session)
    await rules.put(session, "allow_email_notifications", False, guild_id=guild.id)
    await session.commit()
    user = await create_user(session, email="declines-email@example.com")

    wrote = await email_outbox.enqueue(
        session,
        user,
        category=NotificationCategory.mentions,
        guild_id=guild.id,
        pieces=_pieces(),
    )
    await session.commit()

    assert wrote is False
    assert await _outbox(session, user.id) == []


async def test_a_redacting_community_stores_no_more_than_the_mail_will(
    session: AsyncSession, configured
) -> None:
    guild = await create_guild(session)
    await rules.put(session, "redact_notification_content", True, guild_id=guild.id)
    await session.commit()
    user = await create_user(session, email="redacted-email@example.com")

    assert await email_outbox.enqueue(
        session,
        user,
        category=NotificationCategory.mentions,
        guild_id=guild.id,
        pieces=_pieces(),
    )
    await session.commit()

    (row,) = await _outbox(session, user.id)
    assert row.subject == "You were mentioned or answered"
    assert row.body == "Open Initiative to see where."
    assert "Q3 budget" not in row.subject + row.headline + row.body
    # The way back is not the content, so it survives.
    assert row.link == "https://example.test/x"


async def test_the_deployment_can_decline_email_for_everybody(
    session: AsyncSession, configured
) -> None:
    guild = await create_guild(session)
    await _platform(session, email_notifications_enabled=False)
    user = await create_user(session, email="no-mail-anywhere@example.com")

    assert (
        await email_outbox.enqueue(
            session,
            user,
            category=NotificationCategory.mentions,
            guild_id=guild.id,
            pieces=_pieces(),
        )
        is False
    )
    # And for a notification belonging to no community.
    assert (
        await email_outbox.enqueue(
            session,
            user,
            category=NotificationCategory.direct_messages,
            pieces=_pieces(),
        )
        is False
    )


# --- one answer per send -----------------------------------------------------


@pytest.fixture
def reads(monkeypatch) -> list[int | None]:
    """Every time the switches are actually read, by community."""
    calls: list[int | None] = []
    real, real_many = notification_policy.load, notification_policy.load_many

    async def _load(guild_id):
        calls.append(guild_id)
        return await real(guild_id)

    async def _load_many(guild_ids):
        guild_ids = set(guild_ids)
        calls.extend(sorted(gid for gid in guild_ids if gid is not None))
        return await real_many(guild_ids)

    monkeypatch.setattr(notification_policy, "load", _load)
    monkeypatch.setattr(notification_policy, "load_many", _load_many)
    return calls


async def test_a_fan_out_reads_the_switches_once(
    session: AsyncSession, push_on, configured, reads
) -> None:
    """Fifty recipients in one transaction are one question, not a hundred."""
    guild = await create_guild(session)
    users = [
        await create_user(session, email=f"fan-out-{n}@example.com") for n in range(3)
    ]
    await session.exec(select(1))  # the sender's transaction

    for user in users:
        assert await email_outbox.enqueue(
            session,
            user,
            category=NotificationCategory.mentions,
            guild_id=guild.id,
            pieces=_pieces(),
        )
        title, _body = await _mention_push(session, user, guild.id)
        assert title == "Ana mentioned you in Q3 budget"

    assert reads == [guild.id]


async def test_the_next_transaction_reads_the_switches_again(
    session: AsyncSession, push_on, reads
) -> None:
    """A community that starts redacting is redacted from its next send on."""
    guild = await create_guild(session)
    user = await create_user(session, email="switch-between@example.com")

    await session.exec(select(1))
    first, _body = await _mention_push(session, user, guild.id)
    await rules.put(session, "redact_notification_content", True, guild_id=guild.id)
    await session.commit()
    await session.exec(select(1))
    second, _body = await _mention_push(session, user, guild.id)

    assert reads == [guild.id, guild.id]
    assert [first, second] == [
        "Ana mentioned you in Q3 budget",
        "You were mentioned or answered",
    ]
