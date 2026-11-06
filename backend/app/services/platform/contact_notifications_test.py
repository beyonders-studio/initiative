"""Being told that somebody is asking to reach you.

Four moments — a connection asked for and answered, permission to message asked
for and answered — each of which is a decision waiting on a person. Before this
existed all four produced a stream frame and nothing else, so an account whose
app was closed was never told anything: the request sat in a list nobody opens
and the account that sent it read the silence as a refusal.

The assertions worth keeping are that each moment reaches the right person, that
one already answered by a connection announces nothing, and that an ignored
requester stays as invisible here as they are everywhere else.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore
from app.testing import (
    drain_notices,
    push_switched_on,
    set_notification_prefs,
    signed_in_headers,
)


@pytest.fixture(autouse=True)
def fcm_configured():
    with push_switched_on():
        yield


async def _reachable(session, *users) -> None:
    """Both ends open to being asked.

    Whether a request may be sent is a mutual test -- each account has to be
    reachable and each has to allow the other to ask -- so setting only the
    target's policy leaves the request refused for a reason that has nothing to
    do with what is under test here.
    """
    for user in users:
        await session.exec(
            text(
                "UPDATE public.user_dm_settings "
                "SET dm_policy = CAST(:p AS user_dm_policy) WHERE user_id = :u"
            ).bindparams(p=DmPolicy.public.value, u=user.id)
        )
    await session.commit()


async def _lines(session, user_id: int, kind: str) -> list[dict]:
    await drain_notices()
    rows = (
        await session.exec(
            text(
                "SELECT data FROM public.notifications "
                "WHERE user_id = :u AND type = :t ORDER BY created_at"
            ).bindparams(u=user_id, t=kind)
        )
    ).all()
    return [row[0] for row in rows]


async def _handle(session, user) -> tuple[str, str]:
    await session.refresh(user)
    return user.username, user.discriminator


class TestConnections:
    async def test_asking_tells_the_account_being_asked(
        self, client, session, acting_user
    ):
        ada = await acting_user()
        bo = await acting_user()
        username, discriminator = await _handle(session, bo.user)

        response = await client.post(
            "/api/v1/me/connections",
            json={"username": username, "discriminator": discriminator},
            headers=ada.headers,
        )
        assert response.status_code == 202, response.text

        lines = await _lines(session, bo.user.id, "connection_requested")
        assert len(lines) == 1
        assert lines[0]["actor_id"] == ada.user.id
        assert lines[0]["target_path"] == "/profile/privacy"
        # The one doing the asking is not told they asked.
        assert await _lines(session, ada.user.id, "connection_requested") == []

    async def test_accepting_tells_the_account_that_asked(
        self, client, session, acting_user
    ):
        ada = await acting_user()
        bo = await acting_user()
        username, discriminator = await _handle(session, bo.user)
        await client.post(
            "/api/v1/me/connections",
            json={"username": username, "discriminator": discriminator},
            headers=ada.headers,
        )

        accepted = await client.post(
            f"/api/v1/me/connections/{ada.user.id}/accept", headers=bo.headers
        )
        assert accepted.status_code == 200, accepted.text

        lines = await _lines(session, ada.user.id, "connection_accepted")
        assert len(lines) == 1
        assert lines[0]["actor_id"] == bo.user.id
        assert await _lines(session, bo.user.id, "connection_accepted") == []

    async def test_an_ignored_requester_is_as_invisible_here_as_anywhere(
        self, client, session, acting_user
    ):
        """The row is stored and stays out of their sight. A notification would
        say what the hidden row does not."""
        ada = await acting_user()
        bo = await acting_user()
        session.add(UserIgnore(user_id=bo.user.id, ignored_user_id=ada.user.id))
        await session.commit()
        username, discriminator = await _handle(session, bo.user)

        response = await client.post(
            "/api/v1/me/connections",
            json={"username": username, "discriminator": discriminator},
            headers=ada.headers,
        )
        assert response.status_code == 202, response.text

        assert await _lines(session, bo.user.id, "connection_requested") == []


class TestMessageRequests:
    async def test_asking_tells_the_account_being_asked(
        self, client, session, acting_user
    ):
        ada = await acting_user()
        bo = await acting_user()
        await _reachable(session, ada.user, bo.user)

        response = await client.post(
            "/api/v1/me/message-requests",
            json={"user_id": bo.user.id},
            headers=ada.headers,
        )
        assert response.status_code == 202, response.text

        lines = await _lines(session, bo.user.id, "message_request_received")
        assert len(lines) == 1
        assert lines[0]["actor_id"] == ada.user.id
        assert lines[0]["target_path"] == "/messages"

    async def test_accepting_tells_the_account_that_asked(
        self, client, session, acting_user
    ):
        ada = await acting_user()
        bo = await acting_user()
        await _reachable(session, ada.user, bo.user)
        await client.post(
            "/api/v1/me/message-requests",
            json={"user_id": bo.user.id},
            headers=ada.headers,
        )

        accepted = await client.post(
            f"/api/v1/me/message-requests/{ada.user.id}/accept", headers=bo.headers
        )
        assert accepted.status_code == 200, accepted.text

        lines = await _lines(session, ada.user.id, "message_request_accepted")
        assert len(lines) == 1
        assert lines[0]["actor_id"] == bo.user.id

    async def test_a_connected_pair_is_told_nothing(self, client, session, acting_user):
        """A connection already answered this question. Announcing the grant it
        opens would be a notification about a decision nobody made."""
        ada = await acting_user()
        bo = await acting_user()
        await _reachable(session, ada.user, bo.user)
        username, discriminator = await _handle(session, bo.user)
        await client.post(
            "/api/v1/me/connections",
            json={"username": username, "discriminator": discriminator},
            headers=ada.headers,
        )
        await client.post(
            f"/api/v1/me/connections/{ada.user.id}/accept", headers=bo.headers
        )
        # Closed, so asking again writes a grant rather than finding the one the
        # connection opened.
        closed = await client.delete(
            f"/api/v1/me/message-requests/{bo.user.id}", headers=ada.headers
        )
        assert closed.status_code == 204, closed.text

        response = await client.post(
            "/api/v1/me/message-requests",
            json={"user_id": bo.user.id},
            headers=ada.headers,
        )
        assert response.status_code == 202, response.text
        assert response.json()["state"] == "accepted"

        assert await _lines(session, bo.user.id, "message_request_received") == []


class TestPush:
    """The channel that works when the app is closed, which is the whole point."""

    async def test_a_request_pushes(self, client, session, acting_user):
        ada = await acting_user()
        bo = await acting_user()
        await _reachable(session, ada.user, bo.user)
        await client.post(
            "/api/v1/push/register",
            json={"push_token": "fcm-bo", "platform": "android"},
            headers=await signed_in_headers(session, bo.user),
        )

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await client.post(
                "/api/v1/me/message-requests",
                json={"user_id": bo.user.id},
                headers=ada.headers,
            )
            await drain_notices()

        assert send.await_count == 1
        kwargs = send.await_args.kwargs
        assert kwargs["push_token"] == "fcm-bo"
        assert kwargs["data"]["target_path"] == "/messages"

    async def test_every_installation_hears_it(self, client, session, acting_user):
        """Unlike a message, nothing here needs decrypting, so there is no reason
        to hold it back from an installation that has no key store."""
        ada = await acting_user()
        bo = await acting_user()
        await _reachable(session, ada.user, bo.user)
        # Two installations are two sign-ins, each holding its registration.
        for name in ("fcm-phone", "fcm-tablet"):
            await client.post(
                "/api/v1/push/register",
                json={"push_token": name, "platform": "android"},
                headers=await signed_in_headers(session, bo.user),
            )

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await client.post(
                "/api/v1/me/message-requests",
                json={"user_id": bo.user.id},
                headers=ada.headers,
            )
            await drain_notices()

        assert send.await_count == 2

    async def test_turning_the_preference_off_stops_it(
        self, client, session, acting_user
    ):
        ada = await acting_user()
        bo = await acting_user()
        await _reachable(session, ada.user, bo.user)
        await client.post(
            "/api/v1/push/register",
            json={"push_token": "fcm-bo", "platform": "android"},
            headers=await signed_in_headers(session, bo.user),
        )
        await set_notification_prefs(
            session, bo.user, {"categories": {"direct_messages": {"push": False}}}
        )

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await client.post(
                "/api/v1/me/message-requests",
                json={"user_id": bo.user.id},
                headers=ada.headers,
            )
            await drain_notices()

        assert send.await_count == 0
