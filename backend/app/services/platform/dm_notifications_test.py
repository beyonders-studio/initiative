"""The bell line a direct message produces.

One rolled-up line per (recipient, conversation) — the same shape reactions use.
The assertions worth keeping are that a flurry is one line rather than twenty,
that reading it makes the next message a *new* line, and that the line names the
sender and counts the messages without ever carrying one.
"""

import base64
from datetime import UTC
from unittest.mock import AsyncMock, patch

from sqlalchemy import text

from app.api.v1.platform_endpoints.dm_transport_test import (
    _open_channel,
    _register,
    _set_policy,
)
from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore
from app.testing import set_notification_prefs


async def _lines(session, user_id: int) -> list[dict]:
    rows = (
        await session.exec(
            text(
                "SELECT data, read_at FROM public.notifications "
                "WHERE user_id = :u AND type = 'direct_message' "
                "ORDER BY created_at"
            ).bindparams(u=user_id)
        )
    ).all()
    return [{"data": row[0], "read_at": row[1]} for row in rows]


async def _channel(client, session, a, b):
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    await _register(client, a, seed=1)
    b_device = await _register(client, b, seed=80)
    created = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    return created.json()["id"], b_device


async def _send(client, actor, conversation_id, device_id, text_bytes=b"x"):
    return await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": device_id,
                    "message_type": 0,
                    "payload": base64.b64encode(text_bytes).decode(),
                }
            ]
        },
        headers=actor.headers,
    )


async def _read_thread(client, actor, conversation_id):
    return await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/read", headers=actor.headers
    )


async def test_a_message_names_the_sender_and_counts_one(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    conversation_id, b_device = await _channel(client, session, a, b)

    await _send(client, a, conversation_id, b_device)

    lines = await _lines(session, b.user.id)
    assert len(lines) == 1
    assert lines[0]["data"]["count"] == 1
    assert lines[0]["data"]["sender_id"] == a.user.id
    assert lines[0]["data"]["conversation_id"] == conversation_id
    # The line says who and how many. It never says what.
    assert "payload" not in lines[0]["data"]
    assert "body" not in lines[0]["data"]


async def test_a_flurry_is_one_line(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    conversation_id, b_device = await _channel(client, session, a, b)

    for _ in range(4):
        await _send(client, a, conversation_id, b_device)

    lines = await _lines(session, b.user.id)
    assert len(lines) == 1
    assert lines[0]["data"]["count"] == 4


async def test_reading_the_line_makes_the_next_message_a_new_one(
    client, session, acting_user
):
    """Once read, "new" has to start meaning something again."""
    a = await acting_user()
    b = await acting_user()
    conversation_id, b_device = await _channel(client, session, a, b)
    await _send(client, a, conversation_id, b_device)

    read = await _read_thread(client, b, conversation_id)
    assert read.status_code == 204, read.text

    await _send(client, a, conversation_id, b_device)

    lines = await _lines(session, b.user.id)
    assert len(lines) == 2
    assert lines[1]["data"]["count"] == 1
    assert lines[1]["read_at"] is None


async def test_an_ignored_sender_produces_no_line(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    conversation_id, b_device = await _channel(client, session, a, b)
    session.add(UserIgnore(user_id=b.user.id, ignored_user_id=a.user.id))
    await session.commit()

    sent = await _send(client, a, conversation_id, b_device)
    assert sent.status_code == 200, sent.text

    assert await _lines(session, b.user.id) == []


class TestChannels:
    """Both channels fire once per unread conversation, and neither carries the
    message."""

    async def test_email_names_the_sender_and_never_the_message(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)

        with patch(
            "app.services.platform.email_outbox.enqueue", new_callable=AsyncMock
        ) as send:
            await _send(client, a, conversation_id, b_device, b"a secret")

        assert send.await_count == 1
        pieces = send.await_args.kwargs["pieces"]
        assert b.user.username in pieces.body or a.user.username in pieces.body
        assert pieces.link.endswith("/messages")
        # A name and a link. Nothing in the call could carry a message: what
        # this announces is encrypted, and the server holds no key to it.
        assert b"a secret" not in repr(send.await_args).encode()

    async def test_a_flurry_is_one_email(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)

        with patch(
            "app.services.platform.email_outbox.enqueue", new_callable=AsyncMock
        ) as send:
            for _ in range(4):
                await _send(client, a, conversation_id, b_device)

        assert send.await_count == 1

    async def test_turning_the_preference_off_stops_it(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)
        await set_notification_prefs(
            session,
            b.user,
            {"categories": {"direct_messages": {"email": False}}},
        )

        with patch(
            "app.services.platform.email_outbox.enqueue", new_callable=AsyncMock
        ) as send:
            await _send(client, a, conversation_id, b_device)

        assert send.await_count == 0


class TestReadingTheThread:
    """The recipient's own client is the only thing that can close a line, and
    closing it is what lets the next message be announced."""

    async def test_reading_closes_the_line(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)
        await _send(client, a, conversation_id, b_device)

        read = await _read_thread(client, b, conversation_id)
        assert read.status_code == 204, read.text

        lines = await _lines(session, b.user.id)
        assert len(lines) == 1
        assert lines[0]["read_at"] is not None

    async def test_only_the_named_conversation_closes(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        first, b_device = await _channel(client, session, a, b)
        await _set_policy(session, c.user, DmPolicy.public)
        await _open_channel(session, c.user, b.user)
        await _register(client, c, seed=160)
        second = (
            await client.post(
                "/api/v1/me/dm/conversations",
                json={"user_id": b.user.id},
                headers=c.headers,
            )
        ).json()["id"]
        await _send(client, a, first, b_device)
        await _send(client, c, second, b_device)

        await _read_thread(client, b, first)

        by_conversation = {
            line["data"]["conversation_id"]: line["read_at"]
            for line in await _lines(session, b.user.id)
        }
        assert by_conversation[first] is not None
        assert by_conversation[second] is None

    async def test_reading_the_sender_side_changes_nothing(
        self, client, session, acting_user
    ):
        """The sender has no line of their own to close."""
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)
        await _send(client, a, conversation_id, b_device)

        await _read_thread(client, a, conversation_id)

        assert await _lines(session, a.user.id) == []
        assert (await _lines(session, b.user.id))[0]["read_at"] is None

    async def test_a_thread_with_nothing_waiting_answers_anyway(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, _b_device = await _channel(client, session, a, b)

        answer = await _read_thread(client, b, conversation_id)

        assert answer.status_code == 204
        assert await _lines(session, b.user.id) == []

    async def test_after_a_read_a_fresh_message_announces_itself(
        self, client, session, acting_user
    ):
        """A flurry is one email; a flurry after a read is a second one."""
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)

        with patch(
            "app.services.platform.email_outbox.enqueue", new_callable=AsyncMock
        ) as send:
            await _send(client, a, conversation_id, b_device)
            await _send(client, a, conversation_id, b_device)
            assert send.await_count == 1

            await _read_thread(client, b, conversation_id)
            await _send(client, a, conversation_id, b_device)
            assert send.await_count == 2


class TestLeaving:
    async def test_leaving_takes_the_line_down(self, client, session, acting_user):
        """The line names a thread that is no longer in the list."""
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)
        await _send(client, a, conversation_id, b_device)
        assert await _lines(session, b.user.id) != []

        left = await client.delete(
            f"/api/v1/me/dm/conversations/{conversation_id}", headers=b.headers
        )
        assert left.status_code == 204, left.text

        assert await _lines(session, b.user.id) == []

    async def test_leaving_leaves_the_other_side_alone(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)
        await _send(client, a, conversation_id, b_device)

        await client.delete(
            f"/api/v1/me/dm/conversations/{conversation_id}", headers=a.headers
        )

        assert await _lines(session, b.user.id) != []


class TestAGroupLine:
    """A group thread has no name, so the line is named by who is on it."""

    async def _group(self, client, session, members):
        from datetime import datetime

        from app.models.platform.dm_conversation import (
            DmConversation,
            DmConversationKind,
            DmConversationMember,
            roster_key,
        )

        for actor in members:
            await _set_policy(session, actor.user, DmPolicy.public)
        for i, first in enumerate(members):
            for second in members[i + 1 :]:
                await _open_channel(session, first.user, second.user)
        devices = {
            actor.user.id: await _register(client, actor, seed=1 + 40 * i)
            for i, actor in enumerate(members)
        }
        now = datetime.now(UTC)
        conversation = DmConversation(
            kind=DmConversationKind.group,
            roster_key=roster_key(actor.user.id for actor in members),
        )
        session.add(conversation)
        await session.flush()
        for actor in members:
            session.add(
                DmConversationMember(
                    conversation_id=conversation.id,
                    user_id=actor.user.id,
                    accepted_at=now,
                )
            )
        await session.commit()
        return str(conversation.id), devices

    async def test_the_line_names_everybody_but_the_reader(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        conversation_id, devices = await self._group(client, session, [a, b, c])

        await _send(client, a, conversation_id, devices[b.user.id])

        lines = await _lines(session, b.user.id)
        assert len(lines) == 1
        names = lines[0]["data"]["member_names"]
        # A and C, not B: listing the reader back to themselves would be naming
        # the one person who already knows they are there.
        assert len(names) == 2
        assert all(isinstance(name, str) and name for name in names)
        assert lines[0]["data"]["sender_id"] == a.user.id

    async def test_a_pair_carries_no_roster(self, client, session, acting_user):
        """Nothing changes for two people: the line already names the sender."""
        a = await acting_user()
        b = await acting_user()
        conversation_id, b_device = await _channel(client, session, a, b)

        await _send(client, a, conversation_id, b_device)

        assert "member_names" not in (await _lines(session, b.user.id))[0]["data"]

    async def test_the_line_still_carries_no_message(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        conversation_id, devices = await self._group(client, session, [a, b, c])

        await _send(client, a, conversation_id, devices[b.user.id], b"a group secret")

        data = (await _lines(session, b.user.id))[0]["data"]
        assert b"a group secret" not in repr(data).encode()
        assert "payload" not in data and "body" not in data
