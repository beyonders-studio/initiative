"""Whether a message actually reaches a phone nobody is looking at.

The bell line and the email are covered next door, in ``dm_notifications_test``.
This file is about the third channel, which is the only one that works when the
app is closed — and about the join it depends on, which is the part that had
nothing holding it up.

A push reaches an installation only where two rows agree about which one it is:
the account's message key store (``dm_devices``) and its push registration
(``push_tokens``) both have to name the same sign-in. The assertions here are
the ones that fail if either half stops being recorded, or stops following the
sign-in when it is renewed.
"""

import base64
import uuid
from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.api.v1.platform_endpoints.dm_transport_test import (
    _open_channel,
    _registration,
    _set_policy,
)
from app.models.platform.auth_session import AuthSession
from app.models.platform.dm_device import DmDevice
from app.models.platform.push_token import PushToken
from app.models.platform.user_dm_settings import DmPolicy
from app.services.auth import sessions as session_service
from app.testing import (
    drain_notices,
    get_auth_token,
    push_switched_on,
    set_notification_prefs,
    signed_in_headers,
)
from app.testing.sockets import settle


@pytest.fixture(autouse=True)
def fcm_configured():
    """A deployment with push switched on. Off is the default and its own short
    circuit, which would make every assertion below pass for the wrong reason."""
    with push_switched_on():
        yield


async def _install(
    client, session, actor, *, seed: int, headers: dict[str, str] | None = None
) -> tuple[str, dict[str, str]]:
    """One phone: a message key store and a push registration, both made over
    the same sign-in (a fresh one unless ``headers`` names it)."""
    headers = headers or await signed_in_headers(session, actor.user)
    registered = await client.post(
        "/api/v1/me/dm/devices",
        json=_registration(actor.user.id, seed),
        headers=headers,
    )
    assert registered.status_code == 201, registered.text
    push = await client.post(
        "/api/v1/push/register",
        json={"push_token": f"fcm-token-{seed}", "platform": "android"},
        headers=headers,
    )
    assert push.status_code == 200, push.text
    return registered.json()["devices"][-1]["id"], headers


async def _channel(client, session, a, b, *, seed=44, recipient_headers=None):
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    sender_device, sender_headers = await _install(client, session, a, seed=1)
    device_id, _ = await _install(
        client, session, b, seed=seed, headers=recipient_headers
    )
    created = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    assert created.status_code in (200, 201), created.text
    return created.json()["id"], device_id, sender_device, sender_headers


async def _send(client, actor, conversation_id, device_id, **extra):
    """Send one message, then run the notice worker that pushes it."""
    response = await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": device_id,
                    "message_type": 0,
                    "payload": base64.b64encode(b"x").decode(),
                }
            ],
            **extra,
        },
        headers=actor.headers,
    )
    await drain_notices()
    return response


class TestTheLink:
    """Which installation a key store belongs to, and how it learns."""

    async def test_a_key_store_and_its_push_row_name_the_calling_sign_in(
        self, client, session, acting_user
    ):
        a = await acting_user()
        await _install(client, session, a, seed=3)

        signed_in = (
            await session.exec(
                select(AuthSession.id).where(AuthSession.user_id == a.user.id)
            )
        ).one()
        device = (
            await session.exec(select(DmDevice).where(DmDevice.user_id == a.user.id))
        ).one()
        token = (
            await session.exec(select(PushToken).where(PushToken.user_id == a.user.id))
        ).one()
        assert device.session_id == signed_in
        assert token.session_id == signed_in

    async def test_collecting_relinks_the_key_store_to_the_request_s_sign_in(
        self, client, session, acting_user
    ):
        """A device registers once and never again, so registration cannot be the
        only place the link is written — one that has signed in again since, or
        one made before there was a link to write, would stay unwakeable for the
        rest of its life."""
        a = await acting_user()
        device_id, _ = await _install(client, session, a, seed=7)
        await session.exec(text("UPDATE public.dm_devices SET session_id = NULL"))
        await session.commit()

        for _ in range(2):
            # Signed in afresh each time: unlinked first, then linked elsewhere.
            issued = await session_service.create_session(
                session, user_id=a.user.id, amr=["pwd"], satisfied_providers=[]
            )
            signed_in = issued.session.id
            headers = {
                "Authorization": f"Bearer {get_auth_token(a.user, session_id=signed_in)}"
            }
            await session.commit()

            collected = await client.get(
                f"/api/v1/me/dm/queue?device_id={device_id}", headers=headers
            )
            assert collected.status_code == 200, collected.text

            device = await session.get(DmDevice, uuid.UUID(device_id))
            await session.refresh(device)
            assert device.session_id == signed_in

    async def test_one_installation_is_named_by_one_key_store(
        self, client, session, acting_user
    ):
        """Taking the link moves it rather than copying it.

        Two key stores naming the same installation cannot both be woken by it —
        a push goes to the one installation either way — so the one that is no
        longer collecting under it would look linked and silently receive
        nothing.
        """
        a = await acting_user()
        first, headers = await _install(client, session, a, seed=13)
        # A second key store on the same account, collected under the first
        # installation's sign-in.
        registered = await client.post(
            "/api/v1/me/dm/devices",
            json=_registration(a.user.id, 21),
            headers=a.headers,
        )
        second = registered.json()["devices"][-1]["id"]

        collected = await client.get(
            f"/api/v1/me/dm/queue?device_id={second}", headers=headers
        )
        assert collected.status_code == 200, collected.text

        links = {
            row.id: row.session_id
            for row in (
                await session.exec(
                    select(DmDevice).where(DmDevice.user_id == a.user.id)
                )
            ).all()
        }
        await session.commit()
        assert links[uuid.UUID(second)] is not None
        assert links[uuid.UUID(first)] is None

    async def test_re_registering_takes_the_link_off_the_row_it_replaces(
        self, client, session, acting_user
    ):
        a = await acting_user()
        first, headers = await _install(client, session, a, seed=15)

        registered = await client.post(
            "/api/v1/me/dm/devices", json=_registration(a.user.id, 31), headers=headers
        )
        assert registered.status_code == 201, registered.text

        links = {
            row.id: row.session_id
            for row in (
                await session.exec(
                    select(DmDevice).where(DmDevice.user_id == a.user.id)
                )
            ).all()
        }
        await session.commit()
        assert links[uuid.UUID(first)] is None
        assert sum(1 for value in links.values() if value is not None) == 1


class TestDelivery:
    """What the join is for."""

    async def test_a_message_pushes_the_phone_that_can_read_it(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, device_id, _, _ = await _channel(client, session, a, b)

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await _send(client, a, conversation_id, device_id)

        assert send.await_count == 1
        kwargs = send.await_args.kwargs
        # It names the sender so the notification shade is worth reading, and
        # carries a path so tapping it lands somewhere.
        assert kwargs["title"]
        assert kwargs["data"]["target_path"] == "/messages"
        # Nothing about which conversation: that would put who-talks-to-whom
        # through a push service, which is the one thing this is built not to do.
        assert conversation_id not in repr(send.await_args)

    async def test_the_phone_is_still_woken_after_its_sign_in_is_renewed(
        self, client, session, acting_user
    ):
        """A renewal moves the key store and the push row to the new session
        together, so they go on naming the same sign-in."""
        a = await acting_user()
        b = await acting_user()
        issued = await session_service.create_session(
            session,
            user_id=b.user.id,
            amr=["pwd"],
            satisfied_providers=[],
            install_id=uuid.uuid4(),
        )
        headers = {
            "Authorization": f"Bearer {get_auth_token(b.user, session_id=issued.session.id)}"
        }
        await session.commit()
        conversation_id, device_id, _, _ = await _channel(
            client, session, a, b, recipient_headers=headers
        )

        renewed = await session_service.rotate_session(
            session, raw_refresh_token=issued.refresh_token
        )
        assert renewed.ok
        renewed_id = renewed.issued.session.id
        await session.commit()

        device = await session.get(DmDevice, uuid.UUID(device_id))
        await session.refresh(device)
        token = (
            await session.exec(select(PushToken).where(PushToken.user_id == b.user.id))
        ).one()
        assert device.session_id == renewed_id
        assert token.session_id == renewed_id

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await _send(client, a, conversation_id, device_id)

        assert send.await_count == 1
        assert send.await_args.kwargs["push_token"] == "fcm-token-44"

    async def test_every_message_pushes(
        self, client, session, acting_user, account_socket
    ):
        """A reply is the thing somebody is waiting for.

        The bell line rolls up and the email fires once, but the push is the
        channel a conversation actually happens on, and a phone that is told
        about the first message and then goes quiet is not usable. The desktop
        is told each time too, about the one line.
        """
        a = await acting_user()
        b = await acting_user()
        conversation_id, device_id, _, _ = await _channel(client, session, a, b)
        desktop = account_socket(b.user.id)

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            for _ in range(4):
                await _send(client, a, conversation_id, device_id)
        await settle()

        assert send.await_count == 4
        alerts = [frame for frame in desktop.sent if frame["resource"] == "alert"]
        assert len(alerts) == 4
        assert len({str(frame["ids"]) for frame in alerts}) == 1

    async def test_a_message_after_a_read_still_pushes(
        self, client, session, acting_user
    ):
        """Reading closes the line; it does not quieten the next message."""
        a = await acting_user()
        b = await acting_user()
        conversation_id, device_id, _, _ = await _channel(client, session, a, b)
        # Both messages are delivered, so the first does not prune the device.
        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await _send(client, a, conversation_id, device_id)
            await client.post(
                f"/api/v1/me/dm/conversations/{conversation_id}/read",
                headers=b.headers,
            )
            send.reset_mock()
            await _send(client, a, conversation_id, device_id)

        assert send.await_count == 1

    async def test_an_installation_with_no_key_store_is_not_woken(
        self, client, session, acting_user
    ):
        """A push wakes a client so it can fetch and decrypt. An installation
        holding no keys would be woken for something it cannot read."""
        a = await acting_user()
        b = await acting_user()
        conversation_id, device_id, _, _ = await _channel(client, session, a, b)
        # A second phone signed in, push registered, but no message key store.
        other = await signed_in_headers(session, b.user)
        await client.post(
            "/api/v1/push/register",
            json={"push_token": "fcm-keyless", "platform": "android"},
            headers=other,
        )

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await _send(client, a, conversation_id, device_id)

        assert send.await_count == 1
        assert send.await_args.kwargs["push_token"] != "fcm-keyless"

    async def test_turning_the_preference_off_stops_it(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, device_id, _, _ = await _channel(client, session, a, b)
        await set_notification_prefs(
            session, b.user, {"categories": {"direct_messages": {"push": False}}}
        )

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await _send(client, a, conversation_id, device_id)

        assert send.await_count == 0

    async def test_a_silent_send_wakes_nobody(self, client, session, acting_user):
        """A client reporting that it read something is not news."""
        a = await acting_user()
        b = await acting_user()
        conversation_id, device_id, _, _ = await _channel(client, session, a, b)

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await _send(client, a, conversation_id, device_id, silent=True)

        assert send.await_count == 0


class TestWakingOwnDevices:
    """The one envelope an account sends itself that a person has to answer."""

    async def test_a_history_ask_wakes_the_account_s_other_phone(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, _, sender_device, sender_headers = await _channel(
            client, session, a, b
        )
        # The sender's second installation — the one holding the history.
        _, _ = await _install(client, session, a, seed=9)

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            response = await client.post(
                f"/api/v1/me/dm/conversations/{conversation_id}/messages",
                json={
                    "messages": [
                        {
                            "recipient_device_id": sender_device,
                            "message_type": 0,
                            "payload": base64.b64encode(b"ask").decode(),
                        }
                    ],
                    "silent": True,
                    "wake_own_devices": True,
                },
                headers=sender_headers,
            )
        assert response.status_code == 200, response.text

        assert send.await_count == 1
        # The device that asked is already showing the notice, so its sign-in is
        # skipped; it is the other one that has to be picked up.
        assert send.await_args.kwargs["push_token"] == "fcm-token-9"
        assert send.await_args.kwargs["data"]["target_path"] == "/messages"

    async def test_a_wake_obeys_the_message_push_preference(
        self, client, session, acting_user
    ):
        """It rides the messages channel and is the account's own notice to
        itself, so somebody who switched message push off has said it about this
        too."""
        a = await acting_user()
        b = await acting_user()
        conversation_id, _, sender_device, sender_headers = await _channel(
            client, session, a, b
        )
        await _install(client, session, a, seed=17)
        await set_notification_prefs(
            session, a.user, {"categories": {"direct_messages": {"push": False}}}
        )

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await client.post(
                f"/api/v1/me/dm/conversations/{conversation_id}/messages",
                json={
                    "messages": [
                        {
                            "recipient_device_id": sender_device,
                            "message_type": 0,
                            "payload": base64.b64encode(b"ask").decode(),
                        }
                    ],
                    "silent": True,
                    "wake_own_devices": True,
                },
                headers=sender_headers,
            )

        assert send.await_count == 0

    async def test_a_wake_is_not_held_back_by_quiet_hours(
        self, client, session, acting_user
    ):
        """The one notification in the app that quiet hours do not hold.

        Everywhere else suppression only defers: the bell line is still written
        and the morning summary collects it. This wake writes no bell line and
        is sent once, because a device asks for its history once and never
        again — so holding it back does not move the interruption to the
        morning, it deletes it and leaves the new device waiting on an approval
        nobody was told to give.
        """
        a = await acting_user()
        b = await acting_user()
        conversation_id, _, sender_device, sender_headers = await _channel(
            client, session, a, b
        )
        await _install(client, session, a, seed=19)
        # A window covering every hour, so the test does not depend on when it
        # is run.
        await set_notification_prefs(
            session, a.user, {"quiet_hours": {"start": "00:00", "end": "23:59"}}
        )

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await client.post(
                f"/api/v1/me/dm/conversations/{conversation_id}/messages",
                json={
                    "messages": [
                        {
                            "recipient_device_id": sender_device,
                            "message_type": 0,
                            "payload": base64.b64encode(b"ask").decode(),
                        }
                    ],
                    "silent": True,
                    "wake_own_devices": True,
                },
                headers=sender_headers,
            )

        assert send.await_count == 1

    async def test_an_ordinary_silent_send_still_wakes_nobody(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        conversation_id, _, sender_device, sender_headers = await _channel(
            client, session, a, b
        )
        await _install(client, session, a, seed=11)

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await client.post(
                f"/api/v1/me/dm/conversations/{conversation_id}/messages",
                json={
                    "messages": [
                        {
                            "recipient_device_id": sender_device,
                            "message_type": 0,
                            "payload": base64.b64encode(b"receipt").decode(),
                        }
                    ],
                    "silent": True,
                },
                headers=sender_headers,
            )

        assert send.await_count == 0


class TestAGroupPush:
    """Which conversation first, then who spoke -- the way a lock screen reads."""

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
        devices = {}
        for i, actor in enumerate(members):
            device_id, _headers = await _install(
                client, session, actor, seed=1 + 40 * i
            )
            devices[actor.user.id] = device_id
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

    async def test_the_title_is_the_thread_and_the_body_is_the_sender(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        conversation_id, devices = await self._group(client, session, [a, b, c])

        with patch(
            "app.services.platform.push_notifications.send_push_notification",
            new_callable=AsyncMock,
            return_value=(True, False),
        ) as send:
            await _send(client, a, conversation_id, devices[b.user.id])

        assert send.await_count == 1
        kwargs = send.await_args.kwargs
        # The title names the other people on it, so the reader knows which
        # thread before they know who spoke.
        assert "," in kwargs["title"]
        assert kwargs["body"]
        # Still nothing about which conversation, and nothing of what was said.
        assert conversation_id not in repr(send.await_args)
        assert kwargs["data"]["target_path"] == "/messages"
