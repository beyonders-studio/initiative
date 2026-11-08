"""``POST /api/v1/billing/notices``: billing asks for fixed notices to reach
communities' owners.

Pinned: the v2 envelope (one-shot ``jti``); exactly-once per ``key`` via
``billing_event_log``; only the fixed kinds; the owner billing names while
they are still a member, else the community's superadmins; nothing for a
deleted community; each notice in a batch answered on its own; and the letter
in each recipient's own language.
"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.notification_categories import NotificationCategory
from app.models.platform.billing import BillingEventLog
from app.models.platform.guild import CommunityRole, CommunityStatus
from app.models.platform.identity_ref import IdentityEntity
from app.models.platform.notification import Notification, NotificationType
from app.services.platform import email_outbox, identity_refs, notice_outbox
from app.testing import (
    billing_boundary,
    billing_guild_ref,
    create_guild,
    create_guild_membership,
    create_user,
    drain_notices,
)


@pytest.fixture(autouse=True)
def _configure_billing(monkeypatch):
    billing_boundary.configure(monkeypatch)


class _Answer:
    """One notice's answer in a batch, shaped like the response it was."""

    def __init__(self, response):
        self.status_code = response.status_code
        self.text = response.text
        self._body = response.json()

    def json(self) -> dict:
        if "results" not in self._body:
            return self._body
        (result,) = self._body["results"]
        return {k: v for k, v in result.items() if k != "key"}


async def _post(client, _verb: str, payload: dict, **claims) -> _Answer:
    return _Answer(
        await billing_boundary.post(client, "notices", {"notices": [payload]}, **claims)
    )


@pytest.fixture
def letters(monkeypatch) -> list[dict]:
    """The letters the notice worker hands the email outbox, by recipient."""
    sent: list[dict] = []

    async def _enqueue(_session, recipient, *, category, pieces, **kwargs):
        sent.append({"user_id": recipient.id, "category": category, "pieces": pieces})
        return True

    monkeypatch.setattr(email_outbox, "enqueue", _enqueue)
    return sent


async def _community(session: AsyncSession):
    """A community with an owner (superadmin), a second superadmin and an
    admin, and somebody who used to be in it."""
    guild = await create_guild(session, name="Acme")
    owner = await create_user(session, email="owner@example.com")
    other_seat = await create_user(session, email="seat@example.com", locale="de")
    admin = await create_user(session, email="admin@example.com")
    gone = await create_user(session, email="gone@example.com")
    await create_guild_membership(
        session, user=owner, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=other_seat, guild=guild, role=CommunityRole.superadmin
    )
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    return guild.id, owner.id, other_seat.id, admin.id, gone.id


async def _notice(guild_id: int, **fields) -> dict:
    return {
        "community_ref": await billing_guild_ref(guild_id),
        "key": fields.pop("key", f"notice-{secrets.token_hex(6)}"),
        "kind": fields.pop("kind", "trial_ending"),
        "recipient_user_ref": fields.pop("recipient_user_ref", None),
        "day": fields.pop("day", "2026-10-08"),
        **fields,
    }


async def _told(session: AsyncSession, user_id: int) -> list[Notification]:
    """The trial lines in this person's bell, once the outbox has run."""
    session.expire_all()
    await drain_notices()
    return list(
        (
            await session.exec(
                select(Notification).where(
                    Notification.user_id == user_id,
                    Notification.type.in_(  # type: ignore[union-attr]
                        [
                            NotificationType.community_trial_ending,
                            NotificationType.community_trial_ended,
                            NotificationType.community_pause_reminder,
                        ]
                    ),
                )
            )
        ).all()
    )


async def test_the_owner_billing_names_is_told(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, other_seat_id, admin_id, _ = await _community(session)
    owner_ref = await identity_refs.billing_ref(IdentityEntity.user, owner_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, recipient_user_ref=owner_ref),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"delivered": True}
    (line,) = await _told(session, owner_id)
    assert line.type == NotificationType.community_trial_ending
    assert line.data == {
        "community": "Acme",
        "trial_ends_on": "2026-10-08",
        "community_id": guild_id,
        "target_path": "/settings/usage",
    }
    assert await _told(session, other_seat_id) == []
    assert await _told(session, admin_id) == []
    (letter,) = letters
    assert letter["user_id"] == owner_id
    # An account letter, filed under no community.
    assert letter["category"] is NotificationCategory.account
    pieces = letter["pieces"]
    assert pieces.subject == "Acme's trial ends on 8 October 2026"
    # Already subscribed through Paddle's trial: the letter leads to the plan
    # they have, and says it carries on.
    assert pieces.link is not None and pieces.link.endswith(
        f"/c/{guild_id}/billing?page=manage"
    )
    assert "billed to the payment method on file" in pieces.body


async def test_an_owner_moved_off_the_seat_falls_back_to_the_superadmins(
    client: AsyncClient, session: AsyncSession, letters
):
    """Still a member, no longer the seat: the plan is not theirs to act on."""
    guild_id, _, other_seat_id, admin_id, _ = await _community(session)
    admin_ref = await identity_refs.billing_ref(IdentityEntity.user, admin_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, recipient_user_ref=admin_ref),
    )

    assert response.json() == {"delivered": True}
    assert await _told(session, admin_id) == []
    assert len(await _told(session, other_seat_id)) == 1


async def test_a_notice_that_could_not_be_written_is_not_recorded(
    client: AsyncClient, session: AsyncSession, letters, monkeypatch
):
    """Nothing is claimed until the notice is written down, so billing's retry
    of the same event delivers it."""
    guild_id, owner_id, *_ = await _community(session)
    payload = await _notice(guild_id, key="evt-retry")
    real_enqueue = notice_outbox.enqueue

    async def _broken(*_args, **_kwargs):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr(notice_outbox, "enqueue", _broken)
    failed = await _post(client, "community-notice", payload)
    assert failed.status_code == 200, failed.text
    assert failed.json() == {"error": "BILLING_NOTICE_NOT_DELIVERED"}
    assert (
        await session.exec(
            select(BillingEventLog.event_id).where(
                BillingEventLog.event_id == "evt-retry"
            )
        )
    ).all() == []
    assert await _told(session, owner_id) == []

    monkeypatch.setattr(notice_outbox, "enqueue", real_enqueue)
    retried = await _post(client, "community-notice", payload)
    assert retried.json() == {"delivered": True}
    assert len(await _told(session, owner_id)) == 1
    again = await _post(client, "community-notice", payload)
    assert again.json() == {"delivered": False}
    assert len(await _told(session, owner_id)) == 1


async def test_an_owner_who_left_falls_back_to_the_superadmins(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, other_seat_id, admin_id, gone_id = await _community(session)
    gone_ref = await identity_refs.billing_ref(IdentityEntity.user, gone_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, kind="trial_ended", recipient_user_ref=gone_ref),
    )

    assert response.json() == {"delivered": True}
    assert await _told(session, gone_id) == []
    assert len(await _told(session, owner_id)) == 1
    assert len(await _told(session, other_seat_id)) == 1
    assert await _told(session, admin_id) == []


@pytest.mark.parametrize(
    "recipient_user_ref", [None, "not-a-reference", "guild"], ids=str
)
async def test_nobody_named_falls_back_to_the_superadmins(
    client: AsyncClient, session: AsyncSession, letters, recipient_user_ref
):
    guild_id, owner_id, other_seat_id, _, _ = await _community(session)
    if recipient_user_ref == "guild":
        # A reference billing holds, but for the guild rather than a person.
        recipient_user_ref = await billing_guild_ref(guild_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, recipient_user_ref=recipient_user_ref),
    )

    assert response.json() == {"delivered": True}
    assert len(await _told(session, owner_id)) == 1
    assert len(await _told(session, other_seat_id)) == 1


async def test_each_letter_is_in_its_readers_language(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, other_seat_id, *_ = await _community(session)

    await _post(client, "community-notice", await _notice(guild_id, kind="trial_ended"))
    await _told(session, owner_id)

    by_recipient = {letter["user_id"]: letter["pieces"] for letter in letters}
    assert set(by_recipient) == {owner_id, other_seat_id}
    assert by_recipient[owner_id].subject == "Acme's trial has ended"
    assert by_recipient[owner_id].link.endswith(f"/c/{guild_id}/billing?page=upgrade")
    german = by_recipient[other_seat_id]
    assert german.subject == "Die Testphase von Acme ist beendet"
    assert "schreibgeschützt" in german.body


async def test_a_replayed_event_tells_nobody_twice(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, *_ = await _community(session)
    payload = await _notice(guild_id, key="evt-notice-dup")

    first = await _post(client, "community-notice", payload)
    again = await _post(client, "community-notice", payload)

    assert first.json() == {"delivered": True}
    assert again.status_code == 200, again.text
    assert again.json() == {"delivered": False}
    assert len(await _told(session, owner_id)) == 1
    assert len(letters) == 2  # one letter for each seat, once
    rows = (
        await session.exec(
            select(BillingEventLog).where(BillingEventLog.event_id == "evt-notice-dup")
        )
    ).all()
    assert [(row.op, row.source) for row in rows] == [("community_notice", "billing")]


@pytest.mark.parametrize("status", [CommunityStatus.deleted, CommunityStatus.suspended])
async def test_a_deleted_or_suspended_community_is_recorded_and_told_nothing(
    client: AsyncClient, session: AsyncSession, letters, status
):
    guild_id, owner_id, *_ = await _community(session)
    from app.models.platform.guild import Guild

    guild = (await session.exec(select(Guild).where(Guild.id == guild_id))).one()
    guild.status = status.value
    session.add(guild)
    await session.commit()

    response = await _post(
        client, "community-notice", await _notice(guild_id, key="evt-gone")
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"delivered": False}
    assert await _told(session, owner_id) == []
    assert letters == []
    assert (
        await session.exec(
            select(BillingEventLog.event_id).where(
                BillingEventLog.event_id == "evt-gone"
            )
        )
    ).all() == ["evt-gone"]


async def test_a_paused_plan_is_told_when_it_goes_on_hold(
    client: AsyncClient, session: AsyncSession, letters
):
    """A pause reminder names the day the community goes on hold, and its
    button leads to the plan, where it is resumed."""
    guild_id, owner_id, _, _, _ = await _community(session)
    owner_ref = await identity_refs.billing_ref(IdentityEntity.user, owner_id)

    response = await _post(
        client,
        "community-notice",
        await _notice(
            guild_id,
            kind="pause_reminder",
            day="2027-04-17",
            recipient_user_ref=owner_ref,
        ),
    )

    assert response.status_code == 200, response.text
    (line,) = await _told(session, owner_id)
    assert line.type == NotificationType.community_pause_reminder
    assert line.data["holds_on"] == "2027-04-17"
    (letter,) = letters
    pieces = letter["pieces"]
    assert pieces.subject == "Acme's plan is paused until you resume it"
    assert "17 April 2027" in pieces.body
    assert pieces.link.endswith(f"/c/{guild_id}/billing?page=manage")


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"kind": "trial_extended"}, "BILLING_INVALID_PAYLOAD"),
        ({"kind": "trial_ending", "message": "free text"}, None),
        ({"day": "soon"}, "BILLING_INVALID_PAYLOAD"),
        ({"key": "x" * 129}, "BILLING_INVALID_PAYLOAD"),
    ],
)
async def test_only_the_fixed_notices_are_taken(
    client: AsyncClient, session: AsyncSession, letters, fields, code
):
    guild_id, owner_id, *_ = await _community(session)

    response = await _post(
        client,
        "community-notice",
        await _notice(guild_id, **{"key": "evt-x", **fields}),
    )

    if code is None:
        # An unknown field carries nothing anywhere: the words are ours.
        assert response.status_code == 200, response.text
        (line,) = await _told(session, owner_id) or [None]
        assert line is not None and "message" not in line.data
        return
    assert response.status_code == 200, response.text
    assert response.json() == {"error": code}
    assert await _told(session, owner_id) == []
    assert (
        await session.exec(
            select(BillingEventLog.event_id).where(BillingEventLog.event_id == "evt-x")
        )
    ).all() == []


async def test_the_envelope_is_every_verbs(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, *_ = await _community(session)
    payload = await _notice(guild_id)

    unsigned = await client.post("/api/v1/billing/notices", json={"notices": [payload]})
    assert unsigned.status_code == 403
    assert unsigned.json()["detail"] == "BILLING_MISSING_SIGNATURE"

    wrong_audience = await _post(client, "notices", payload, aud="initiative:other")
    assert wrong_audience.status_code == 403

    first = await _post(client, "notices", payload, jti="notice-once")
    assert first.status_code == 200, first.text
    replayed = await _post(
        client, "notices", await _notice(guild_id), jti="notice-once"
    )
    assert replayed.status_code == 403
    assert replayed.json()["detail"] == "BILLING_REPLAYED_TOKEN"
    assert len(await _told(session, owner_id)) == 1


async def test_each_notice_in_a_batch_is_answered_on_its_own(
    client: AsyncClient, session: AsyncSession, letters
):
    guild_id, owner_id, *_ = await _community(session)
    good = await _notice(guild_id, key="good")
    unknown = {
        **(await _notice(guild_id)),
        "community_ref": "gbil_nobody",
        "key": "nobody",
    }
    malformed = {**(await _notice(guild_id)), "kind": "made_up", "key": "bad"}

    response = await billing_boundary.post(
        client, "notices", {"notices": [unknown, good, malformed]}
    )

    assert response.status_code == 200, response.text
    assert response.json()["results"] == [
        {"key": "nobody", "error": "BILLING_COMMUNITY_NOT_FOUND"},
        {"key": "good", "delivered": True},
        {"key": "bad", "error": "BILLING_INVALID_PAYLOAD"},
    ]
    assert len(await _told(session, owner_id)) == 1
