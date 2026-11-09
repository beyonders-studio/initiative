"""The transport endpoints: keys in, ciphertext through, nothing kept.

The assertions worth keeping are about what the server *cannot* do and what a
sender *cannot* learn: that a stranger gets no keys, that an ignored sender is
answered exactly like an un-ignored one while nothing arrives, and that a
collected message stops existing.
"""

import base64
from datetime import UTC, datetime

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import text

from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore


def _registration(user_id: int, seed: int = 1) -> dict:
    """A registration as a device sends it, signed by its own key."""
    registration = _signed_registration(user_id, seed)
    registration.pop("_device")
    return registration


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode().rstrip("=")


def _signed_registration(user_id: int, seed: int = 1, *, sign: bool = True) -> dict:
    """A registration from a real device key, signed the way the ratchet signs
    (``crypto/src/lib.rs``). ``sign=False`` leaves every signature off, as a
    device registered before signing did."""
    device = Ed25519PrivateKey.generate()
    fingerprint = device.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    identity = bytes([seed % 251]) * 32

    def published(key_id: str, raw: bytes, tag: bytes) -> dict:
        key = {"key_id": key_id, "public_key": _b64(raw)}
        return {**key, "signature": _b64(device.sign(tag + raw))} if sign else key

    registration = {
        "identity_key": _b64(identity),
        "fingerprint_key": _b64(fingerprint),
        "fallback_key": published(
            "fb", bytes([seed + 2]) * 32, b"initiative-dm-fallback-v1\0"
        ),
        "one_time_keys": [
            published("otk-1", bytes([seed + 3]) * 32, b"initiative-dm-otk-v1\0")
        ],
    }
    if sign:
        registration["signature"] = _b64(
            device.sign(
                b"initiative-dm-device-v1\0"
                + user_id.to_bytes(8, "big")
                + identity
                + fingerprint
            )
        )
    return {**registration, "_device": device}


async def _set_policy(session, user, policy: DmPolicy) -> None:
    await session.exec(
        text(
            "UPDATE public.user_dm_settings SET dm_policy = CAST(:p AS user_dm_policy) "
            "WHERE user_id = :u"
        ).bindparams(p=policy.value, u=user.id)
    )
    await session.commit()


async def _connect(session, a, b) -> None:
    """The mutual link a connection request earns, applied directly.

    A ``private`` account is reachable only by one of these — a message grant
    does not satisfy that policy, which is the whole point of it.
    """
    low, high = (a.id, b.id) if a.id < b.id else (b.id, a.id)
    await session.exec(
        text(
            "INSERT INTO public.contact_grants "
            "(user_id_low, user_id_high, kind, state, requested_by, created_at) "
            "VALUES (:lo, :hi, 'connection', 'accepted', :by, now()) "
            "ON CONFLICT DO NOTHING"
        ).bindparams(lo=low, hi=high, by=a.id)
    )
    await session.commit()


async def _open_channel(session, a, b) -> None:
    """The accepted message grant a request earns, applied directly."""
    low, high = (a.id, b.id) if a.id < b.id else (b.id, a.id)
    await session.exec(
        text(
            "INSERT INTO public.contact_grants "
            "(user_id_low, user_id_high, kind, state, requested_by, created_at) "
            "VALUES (:lo, :hi, 'message', 'accepted', :by, now()) "
            "ON CONFLICT DO NOTHING"
        ).bindparams(lo=low, hi=high, by=a.id)
    )
    await session.commit()


FIREFOX_ON_LINUX = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
)


async def _register(client, actor, seed=1, user_agent=FIREFOX_ON_LINUX) -> str:
    response = await client.post(
        "/api/v1/me/dm/devices",
        json=_registration(actor.user.id, seed),
        headers={**actor.headers, "user-agent": user_agent},
    )
    assert response.status_code == 201, response.text
    return response.json()["device_id"]


# ------------------------------------------------------------------ devices ---


async def test_a_device_publishes_only_public_keys(client, acting_user):
    a = await acting_user()

    device_id = await _register(client, a)
    listed = await client.get("/api/v1/me/dm/devices", headers=a.headers)

    body = listed.json()["devices"][0]
    assert body["id"] == device_id
    # Named by what connected, not by what the client asked to be called, and
    # in words a person recognises rather than as the raw user agent.
    assert body["label"] == "Firefox on Linux"
    assert body["one_time_key_count"] == 1
    # The account's own public keys, which is what it needs to recognise a
    # message arriving from another of its own clients. Both are public halves;
    # nothing here could open anything.
    assert body["identity_key"]
    assert body["fingerprint_key"]


async def test_a_malformed_key_is_refused(client, acting_user):
    a = await acting_user()
    payload = _registration(a.user.id)
    payload["identity_key"] = "not-base64!!"

    response = await client.post(
        "/api/v1/me/dm/devices", json=payload, headers=a.headers
    )
    assert response.status_code == 422


async def test_keys_are_handed_back_the_way_the_ratchet_writes_them(
    client, session, acting_user
):
    """A client finds who sent a pre-key message by comparing the identity it
    names with the one the directory lists, as text. The ratchet writes keys
    without padding, so every key goes back that way, however it was published.
    """
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    written = _signed_registration(b.user.id, seed=45)
    written.pop("_device")
    otk = written["one_time_keys"][0]

    def padded(value: str) -> str:
        return value + "=" * (-len(value) % 4)

    published = {
        **written,
        "identity_key": padded(written["identity_key"]),
        "fingerprint_key": padded(written["fingerprint_key"]),
        "signature": padded(written["signature"]),
        "one_time_keys": [
            {
                **otk,
                "public_key": padded(otk["public_key"]),
                "signature": padded(otk["signature"]),
            }
        ],
    }
    registered = await client.post(
        "/api/v1/me/dm/devices", json=published, headers=b.headers
    )
    assert registered.status_code == 201, registered.text

    directory = await client.get(
        f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
    )
    claimed = await client.post(
        f"/api/v1/users/{b.user.id}/dm/session-keys", headers=a.headers
    )
    for device in (
        registered.json()["devices"][0],
        directory.json()["devices"][0],
        claimed.json()["devices"][0],
    ):
        assert device["identity_key"] == written["identity_key"]
        assert device["fingerprint_key"] == written["fingerprint_key"]
        assert device["signature"] == written["signature"]
    assert (
        claimed.json()["devices"][0]["one_time_key"]["public_key"]
        == (otk["public_key"])
    )
    assert (
        claimed.json()["devices"][0]["one_time_key"]["signature"] == (otk["signature"])
    )


async def test_a_fallback_key_may_reuse_a_prekey_id(client, acting_user):
    """Fallback keys are numbered in their own sequence on the client, so the
    same id string can arrive on both -- registration must not collide."""
    a = await acting_user()
    payload = _registration(a.user.id)
    payload["fallback_key"]["key_id"] = "AAAAAAAAAAA"
    payload["one_time_keys"][0]["key_id"] = "AAAAAAAAAAA"

    response = await client.post(
        "/api/v1/me/dm/devices", json=payload, headers=a.headers
    )
    assert response.status_code == 201


async def test_a_short_key_is_refused(client, acting_user):
    a = await acting_user()
    payload = _registration(a.user.id)
    payload["identity_key"] = base64.b64encode(b"tooshort").decode()

    response = await client.post(
        "/api/v1/me/dm/devices", json=payload, headers=a.headers
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "DM_MALFORMED_KEY"


async def test_removing_a_device_takes_its_queue_with_it(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    b_device = await _register(client, b, seed=20)
    await _register(client, a, seed=1)

    conversation = await client.post(
        "/api/v1/me/dm/conversations",
        json={"user_id": b.user.id},
        headers=a.headers,
    )
    conversation_id = conversation.json()["id"]
    await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": b_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"ciphertext").decode(),
                }
            ]
        },
        headers=a.headers,
    )

    removed = await client.delete(
        f"/api/v1/me/dm/devices/{b_device}", headers=b.headers
    )
    assert removed.status_code == 204
    remaining = (
        await session.exec(text("SELECT count(*) FROM public.dm_queue"))
    ).scalar_one()
    assert remaining == 0


# ---------------------------------------------------------------- directory ---


async def test_a_stranger_gets_no_session_keys(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _register(client, b, seed=30)

    response = await client.post(
        f"/api/v1/users/{b.user.id}/dm/session-keys", headers=a.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "DM_NOT_REACHABLE"


async def test_claiming_spends_a_prekey_but_never_the_fallback(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    registration = _signed_registration(b.user.id, seed=40)
    registration.pop("_device")
    registered = await client.post(
        "/api/v1/me/dm/devices", json=registration, headers=b.headers
    )
    assert registered.status_code == 201, registered.text

    first = await client.post(
        f"/api/v1/users/{b.user.id}/dm/session-keys", headers=a.headers
    )
    assert first.status_code == 200, first.text
    device = first.json()["devices"][0]
    assert device["signature"]
    assert device["one_time_key"]["key_id"] == "otk-1"
    assert device["one_time_key"]["fallback"] is False
    assert device["one_time_key"]["signature"]

    # The pool is empty now, so the reusable last-resort key answers instead of
    # the account becoming unreachable. It is signed under its own tag.
    second = await client.post(
        f"/api/v1/users/{b.user.id}/dm/session-keys", headers=a.headers
    )
    fallback = second.json()["devices"][0]["one_time_key"]
    assert (fallback["key_id"], fallback["fallback"]) == ("fb", True)
    assert fallback["signature"]

    directory = await client.get(
        f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
    )
    assert directory.json()["devices"][0]["signature"] == device["signature"]

    # A sender that already holds a session with a device claims for the rest.
    other = await _register(client, b, seed=50)
    named = await client.post(
        f"/api/v1/users/{b.user.id}/dm/session-keys",
        json={"device_ids": [other]},
        headers=a.headers,
    )
    assert [row["device_id"] for row in named.json()["devices"]] == [other]


async def test_a_device_signs_its_keys(client, session, acting_user):
    """A signature must verify against the device's own key, a signed device's
    keys are signed too, an unsigned registration is refused, and a device
    registered before signing signs itself once."""
    a = await acting_user()

    wrong_key = _signed_registration(a.user.id)
    wrong_key.pop("_device")
    wrong_key["signature"] = _b64(Ed25519PrivateKey.generate().sign(b"x"))
    unsigned_key = _signed_registration(a.user.id)
    unsigned_key.pop("_device")
    unsigned_key["one_time_keys"][0].pop("signature")
    for body in (wrong_key, unsigned_key):
        refused = await client.post(
            "/api/v1/me/dm/devices", json=body, headers=a.headers
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["detail"] == "DM_INVALID_SIGNATURE"

    unsigned = _signed_registration(a.user.id, seed=20, sign=False)
    unsigned.pop("_device")
    refused = await client.post(
        "/api/v1/me/dm/devices", json=unsigned, headers=a.headers
    )
    assert refused.json()["detail"] == "DM_INVALID_SIGNATURE"

    # A device registered before signing: its row has no signature.
    legacy = _signed_registration(a.user.id, seed=7)
    device = legacy.pop("_device")
    registered = await client.post(
        "/api/v1/me/dm/devices", json=legacy, headers=a.headers
    )
    device_id = registered.json()["device_id"]
    await session.exec(
        text(
            "UPDATE public.dm_devices SET signature = NULL WHERE id = CAST(:id AS uuid)"
        ).bindparams(id=device_id)
    )
    await session.commit()
    signed = _signed_registration(a.user.id, seed=7)
    signed.pop("_device")
    fingerprint = base64.b64decode(legacy["fingerprint_key"] + "=")
    identity = base64.b64decode(legacy["identity_key"] + "=")
    tags = (b"initiative-dm-fallback-v1\0", b"initiative-dm-otk-v1\0")
    backfill = {
        "signature": _b64(
            device.sign(
                b"initiative-dm-device-v1\0"
                + a.user.id.to_bytes(8, "big")
                + identity
                + fingerprint
            )
        ),
        "fallback_key": {
            "key_id": "fb-2",
            "public_key": _b64(bytes([9]) * 32),
            "signature": _b64(device.sign(tags[0] + bytes([9]) * 32)),
        },
        "one_time_keys": [
            {
                "key_id": f"otk-{n}",
                "public_key": _b64(bytes([n]) * 32),
                "signature": _b64(device.sign(tags[1] + bytes([n]) * 32)),
            }
            for n in (10, 11)
        ],
    }
    url = f"/api/v1/me/dm/devices/{device_id}/signature"
    signed_itself = await client.put(url, json=backfill, headers=a.headers)
    assert signed_itself.status_code == 200, signed_itself.text
    listed = signed_itself.json()["devices"][0]
    assert listed["signature"] == backfill["signature"]
    assert listed["one_time_key_count"] == 2
    again = await client.put(url, json=backfill, headers=a.headers)
    assert again.json()["detail"] == "DM_INVALID_SIGNATURE"


# ------------------------------------------------------------ conversations ---


async def test_a_conversation_needs_an_accepted_grant(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)

    response = await client.post(
        "/api/v1/me/dm/conversations",
        json={"user_id": b.user.id},
        headers=a.headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "DM_NOT_REACHABLE"


async def test_asking_twice_returns_the_same_channel(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)

    first = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    second = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    assert first.json()["id"] == second.json()["id"]


class TestLeavingReleasesTheRoster:
    """A conversation down to one member gives its roster name back, so the two
    of them can open a channel again."""

    async def _channel(self, client, session, a, b) -> str:
        await _set_policy(session, a.user, DmPolicy.public)
        await _set_policy(session, b.user, DmPolicy.public)
        await _open_channel(session, a.user, b.user)
        opened = await client.post(
            "/api/v1/me/dm/conversations",
            json={"user_id": b.user.id},
            headers=a.headers,
        )
        assert opened.status_code == 201, opened.text
        return opened.json()["id"]

    async def test_the_one_who_stayed_can_open_a_fresh_channel(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        first = await self._channel(client, session, a, b)
        left = await client.delete(
            f"/api/v1/me/dm/conversations/{first}", headers=b.headers
        )
        assert left.status_code == 204, left.text

        again = await client.post(
            "/api/v1/me/dm/conversations",
            json={"user_id": b.user.id},
            headers=a.headers,
        )

        assert again.status_code == 201, again.text
        assert again.json()["id"] != first
        # And it is a real channel: both of them are on it.
        listed = await client.get("/api/v1/me/dm/conversations", headers=b.headers)
        assert again.json()["id"] in {c["id"] for c in listed.json()["conversations"]}

    async def test_the_one_who_left_can_open_a_fresh_channel(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        first = await self._channel(client, session, a, b)
        await client.delete(f"/api/v1/me/dm/conversations/{first}", headers=b.headers)

        again = await client.post(
            "/api/v1/me/dm/conversations",
            json={"user_id": a.user.id},
            headers=b.headers,
        )

        assert again.status_code == 201, again.text
        assert again.json()["id"] != first

    async def test_opening_again_is_still_refused_where_they_cannot_be_reached(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        first = await self._channel(client, session, a, b)
        await client.delete(f"/api/v1/me/dm/conversations/{first}", headers=b.headers)
        await _set_policy(session, b.user, DmPolicy.private)

        again = await client.post(
            "/api/v1/me/dm/conversations",
            json={"user_id": b.user.id},
            headers=a.headers,
        )

        assert again.status_code == 409
        assert again.json()["detail"] == "DM_NOT_REACHABLE"


async def test_two_requests_for_one_pair_both_get_the_channel(
    client, session, acting_user, monkeypatch
):
    """Losing the insert race means the thread exists, which is what was asked
    for -- so it is read back rather than returned as a constraint error."""
    from app.services.platform import dm_transport as service

    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    first = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    assert first.status_code == 201, first.text

    # The second request looks before the first has committed, so it finds
    # nothing and goes on to insert against a key that is already taken.
    real = service._conversation_with_roster
    looks = {"n": 0}

    async def blind_first_look(*args, **kwargs):
        looks["n"] += 1
        if looks["n"] == 1:
            return None
        return await real(*args, **kwargs)

    monkeypatch.setattr(service, "_conversation_with_roster", blind_first_look)

    second = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )

    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]


async def test_a_third_account_cannot_see_the_conversation(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    carol = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )

    listed = await client.get("/api/v1/me/dm/conversations", headers=carol.headers)
    assert listed.json()["conversations"] == []


# ------------------------------------------------------------------- queue ---


async def _conversation_with_devices(client, session, a, b):
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    a_device = await _register(client, a, seed=1)
    b_device = await _register(client, b, seed=60)
    created = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    return created.json()["id"], a_device, b_device


async def test_a_send_to_your_own_devices_leaves_the_other_party_alone(
    client, session, acting_user
):
    """Two devices of one account talk through a conversation because it is the
    only channel there is. The other member has no part in that."""
    from sqlmodel import select as sqlmodel_select

    from app.models.platform.notification import Notification

    a = await acting_user()
    b = await acting_user()
    conversation_id, _a_device, _b_device = await _conversation_with_devices(
        client, session, a, b
    )
    second = await _register(client, a, seed=120)

    sent = await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": second,
                    "message_type": 1,
                    "payload": base64.b64encode(b"history").decode(),
                }
            ]
        },
        headers=a.headers,
    )
    assert sent.status_code == 200, sent.text

    lines = (
        await session.exec(
            sqlmodel_select(Notification).where(Notification.user_id == b.user.id)
        )
    ).all()
    assert lines == []


async def test_a_silent_send_leaves_no_bell_line(client, session, acting_user):
    """A client reporting that it collected or read something is not a person
    saying anything, so it rolls into nobody's notifications."""
    from sqlmodel import select as sqlmodel_select

    from app.models.platform.notification import Notification

    a = await acting_user()
    b = await acting_user()
    conversation_id, _a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )

    body = {
        "messages": [
            {
                "recipient_device_id": b_device,
                "message_type": 1,
                "payload": base64.b64encode(b"a receipt").decode(),
            }
        ],
        "silent": True,
    }
    sent = await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json=body,
        headers=a.headers,
    )
    assert sent.status_code == 200, sent.text

    lines = (
        await session.exec(
            sqlmodel_select(Notification).where(Notification.user_id == b.user.id)
        )
    ).all()
    assert lines == []


async def test_a_message_reaches_the_recipient_and_the_senders_own_device(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    conversation_id, a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )

    sent = await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": b_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"for-bob").decode(),
                },
                {
                    "recipient_device_id": a_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"for-my-other-tab").decode(),
                },
            ]
        },
        headers=a.headers,
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["accepted"] == 2

    collected = await client.get(
        f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
    )
    items = collected.json()["items"]
    assert len(items) == 1
    assert base64.b64decode(items[0]["payload"]) == b"for-bob"


async def test_a_collection_pages_past_what_it_leaves_behind(
    client, session, acting_user, monkeypatch
):
    """A device leaves a message it cannot read yet where it is, so the queue
    is read a page at a time rather than the same first page every time."""
    from app.services.platform import dm_transport

    monkeypatch.setattr(dm_transport, "QUEUE_PAGE", 2)
    a = await acting_user()
    b = await acting_user()
    conversation_id, _, b_device = await _conversation_with_devices(
        client, session, a, b
    )
    for body in (b"one", b"two", b"three"):
        sent = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/messages",
            json={
                "messages": [
                    {
                        "recipient_device_id": b_device,
                        "message_type": 0,
                        "payload": base64.b64encode(body).decode(),
                    }
                ]
            },
            headers=a.headers,
        )
        assert sent.status_code == 200, sent.text

    url = f"/api/v1/me/dm/queue?device_id={b_device}"
    first = (await client.get(url, headers=b.headers)).json()
    after = first["items"][-1]["id"]
    second = (await client.get(f"{url}&after={after}", headers=b.headers)).json()

    read = [base64.b64decode(i["payload"]) for i in first["items"] + second["items"]]
    assert read == [b"one", b"two", b"three"]
    assert (first["more"], second["more"]) == (True, False)


async def test_an_ignored_sender_is_answered_the_same_and_reaches_nobody(
    client, session, acting_user
):
    """The whole point of the ignore, on the wire.

    The send succeeds, the response is identical, and nothing lands in the
    recipient's queue. Identical includes the count: it says what the sender
    handed over, so it does not move when a copy is dropped.
    """
    a = await acting_user()
    b = await acting_user()
    conversation_id, a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )
    session.add(UserIgnore(user_id=b.user.id, ignored_user_id=a.user.id))
    await session.commit()

    sent = await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": b_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"unheard").decode(),
                },
                {
                    "recipient_device_id": a_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"my own copy").decode(),
                },
            ]
        },
        headers=a.headers,
    )
    assert sent.status_code == 200, sent.text
    # Two handed over, two accepted -- the same answer somebody who is not
    # ignored gets, which is what makes the ignore invisible rather than
    # merely quiet.
    assert sent.json()["accepted"] == 2

    collected = await client.get(
        f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
    )
    assert collected.json()["items"] == []
    # The sender's own outbox copy still lands, so their other tabs render it.
    own = await client.get(
        f"/api/v1/me/dm/queue?device_id={a_device}", headers=a.headers
    )
    assert len(own.json()["items"]) == 1


class TestProposingAGroup:
    """A roster is proposed to everybody on it, and nobody is added."""

    async def _reachable(self, session, actors):
        for actor in actors:
            await _set_policy(session, actor.user, DmPolicy.public)
        for i, first in enumerate(actors):
            for second in actors[i + 1 :]:
                await _open_channel(session, first.user, second.user)

    async def _propose(self, client, actor, others):
        return await client.post(
            "/api/v1/me/dm/conversations/group",
            json={"user_ids": [o.user.id for o in others]},
            headers=actor.headers,
        )

    async def test_everybody_named_is_asked_and_nobody_is_added(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await self._reachable(session, [a, b, c])

        made = await self._propose(client, a, [b, c])

        assert made.status_code == 201, made.text
        conversation_id = made.json()["id"]
        # The one who proposed it has answered by proposing.
        mine = await client.get("/api/v1/me/dm/conversations", headers=a.headers)
        entry = next(
            c for c in mine.json()["conversations"] if c["id"] == conversation_id
        )
        assert entry["kind"] == "group"
        assert entry["pending"] is False
        assert sorted(entry["member_ids"]) == sorted([b.user.id, c.user.id])
        # The others have an invitation, not a membership.
        theirs = await client.get("/api/v1/me/dm/conversations", headers=b.headers)
        waiting = next(
            c for c in theirs.json()["conversations"] if c["id"] == conversation_id
        )
        assert waiting["pending"] is True

    async def test_a_pending_invitee_receives_nothing(
        self, client, session, acting_user
    ):
        """Named on a roster is not on the conversation."""
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await self._reachable(session, [a, b, c])
        b_device = await _register(client, b, seed=60)
        await _register(client, a, seed=1)
        made = await self._propose(client, a, [b, c])
        conversation_id = made.json()["id"]

        sent = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/messages",
            json={
                "messages": [
                    {
                        "recipient_device_id": b_device,
                        "message_type": 0,
                        "payload": base64.b64encode(b"early").decode(),
                    }
                ]
            },
            headers=a.headers,
        )
        assert sent.status_code == 200, sent.text

        collected = await client.get(
            f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
        )
        assert collected.json()["items"] == []

    async def test_answering_puts_them_on_it(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await self._reachable(session, [a, b, c])
        b_device = await _register(client, b, seed=60)
        await _register(client, a, seed=1)
        conversation_id = (await self._propose(client, a, [b, c])).json()["id"]

        answered = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/accept", headers=b.headers
        )
        assert answered.status_code == 204, answered.text

        sent = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/messages",
            json={
                "messages": [
                    {
                        "recipient_device_id": b_device,
                        "message_type": 0,
                        "payload": base64.b64encode(b"now you are on it").decode(),
                    }
                ]
            },
            headers=a.headers,
        )
        assert sent.status_code == 200, sent.text
        collected = await client.get(
            f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
        )
        assert len(collected.json()["items"]) == 1

    async def test_the_proposal_answers_with_the_roster_it_made(
        self, client, session, acting_user
    ):
        """The same shape the list answers with, so a client can use it as-is."""
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await self._reachable(session, [a, b, c])

        made = await self._propose(client, a, [b, c])

        body = made.json()
        assert body["kind"] == "group"
        assert body["member_ids"] == sorted([b.user.id, c.user.id])
        assert body["other_user_id"] == min(b.user.id, c.user.id)
        assert body["pending"] is False
        # And it matches what the list says about the same conversation.
        listed = await client.get("/api/v1/me/dm/conversations", headers=a.headers)
        entry = next(
            row for row in listed.json()["conversations"] if row["id"] == body["id"]
        )
        assert entry["member_ids"] == body["member_ids"]
        assert entry["kind"] == body["kind"]

    async def test_the_list_names_who_is_on_a_thread(
        self, client, session, acting_user
    ):
        """A group has no name, so it is named by its roster -- and drawn by it
        too, which needs the picture as well as the handle.

        Every account here is an ordinary member. ``users`` is own-row for the
        request path below moderator, so a platform tier that can read the whole
        table would pass this for a reason no ordinary account has.
        """
        a = await acting_user("member")
        b = await acting_user("member")
        c = await acting_user("member")
        await self._reachable(session, [a, b, c])
        conversation_id = (await self._propose(client, a, [b, c])).json()["id"]

        listed = await client.get("/api/v1/me/dm/conversations", headers=a.headers)

        entry = next(
            row
            for row in listed.json()["conversations"]
            if row["id"] == conversation_id
        )
        members = entry["members"]
        assert [member["user_id"] for member in members] == sorted(
            [b.user.id, c.user.id]
        )
        assert all(member["username"] for member in members)
        # The picture and what is worn around it, so a roster draws a person the
        # way every other list of people does.
        assert all("avatar_url" in member for member in members)
        assert all("profile_decorations" in member for member in members)
        # In the same order as the ids, so the two can be read together.
        assert entry["member_ids"] == sorted([b.user.id, c.user.id])

    async def test_strangers_can_make_a_group_and_use_it(
        self, client, session, acting_user
    ):
        """Nobody here has ever messaged anybody one-to-one.

        Agreeing to a roster is the ask and the answer in one, so the group is
        the accepted ask: no prior message request between any pair.
        """
        a = await acting_user("member")
        b = await acting_user("member")
        c = await acting_user("member")
        # Reachable, but with no grant between any pair.
        for actor in (a, b, c):
            await _set_policy(session, actor.user, DmPolicy.public)
        a_device = await _register(client, a, seed=1)
        b_device = await _register(client, b, seed=60)
        await _register(client, c, seed=120)

        made = await self._propose(client, a, [b, c])
        assert made.status_code == 201, made.text
        conversation_id = made.json()["id"]
        for actor in (b, c):
            answered = await client.post(
                f"/api/v1/me/dm/conversations/{conversation_id}/accept",
                headers=actor.headers,
            )
            assert answered.status_code == 204, answered.text

        # Their keys are readable, which is what a first message needs.
        directory = await client.get(
            f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
        )
        assert directory.status_code == 200, directory.text

        sent = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/messages",
            json={
                "messages": [
                    {
                        "recipient_device_id": b_device,
                        "message_type": 0,
                        "payload": base64.b64encode(b"hello strangers").decode(),
                    }
                ]
            },
            headers=a.headers,
        )
        assert sent.status_code == 200, sent.text
        collected = await client.get(
            f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
        )
        assert len(collected.json()["items"]) == 1
        assert a_device

    async def test_an_unanswered_invitation_is_not_an_accepted_ask(
        self, client, session, acting_user
    ):
        """Being named on a roster carries nothing until it is answered."""
        a = await acting_user("member")
        b = await acting_user("member")
        c = await acting_user("member")
        for actor in (a, b, c):
            await _set_policy(session, actor.user, DmPolicy.public)
        await self._propose(client, a, [b, c])

        # B has not answered, so A has no way to reach B's keys.
        directory = await client.get(
            f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
        )
        assert directory.status_code == 409
        assert directory.json()["detail"] == "DM_NOT_REACHABLE"

    async def test_leaving_an_accepted_group_revokes_transport_access(
        self, client, session, acting_user
    ):
        """Leaving takes back what being on the roster gave.

        The two halves are different answers on purpose. Reading somebody's
        devices is a question about that account, and it is refused. A copy
        addressed to a device that is no longer on the roster is dropped
        instead: the send is for everybody still on it, and one name having
        gone is not the rest of them going unheard.
        """
        a = await acting_user("member")
        b = await acting_user("member")
        c = await acting_user("member")
        for actor in (a, b, c):
            await _set_policy(session, actor.user, DmPolicy.public)
        a_device = await _register(client, a, seed=1)
        b_device = await _register(client, b, seed=60)
        conversation_id = (await self._propose(client, a, [b, c])).json()["id"]
        for actor in (b, c):
            answered = await client.post(
                f"/api/v1/me/dm/conversations/{conversation_id}/accept",
                headers=actor.headers,
            )
            assert answered.status_code == 204, answered.text

        left = await client.delete(
            f"/api/v1/me/dm/conversations/{conversation_id}", headers=b.headers
        )
        assert left.status_code == 204, left.text

        directory = await client.get(
            f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
        )
        assert directory.status_code == 409
        assert directory.json()["detail"] == "DM_NOT_REACHABLE"
        sent = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/messages",
            json={
                "messages": [
                    {
                        "recipient_device_id": b_device,
                        "message_type": 0,
                        "payload": base64.b64encode(b"after leave").decode(),
                    }
                ]
            },
            headers=a.headers,
        )
        # The conversation is still there and still has people on it, so the
        # send is taken.
        assert sent.status_code == 200, sent.text
        # And nothing was written for the person who left.
        collected = await client.get(
            f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
        )
        assert collected.json()["items"] == []
        assert a_device

    async def test_somebody_still_deciding_cannot_send(
        self, client, session, acting_user
    ):
        """Seeing a conversation and being on it are different things."""
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await self._reachable(session, [a, b, c])
        a_device = await _register(client, a, seed=1)
        await _register(client, b, seed=60)
        conversation_id = (await self._propose(client, a, [b, c])).json()["id"]
        # B can see it -- that is how they decide.
        listed = await client.get("/api/v1/me/dm/conversations", headers=b.headers)
        assert conversation_id in {row["id"] for row in listed.json()["conversations"]}

        sent = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/messages",
            json={
                "messages": [
                    {
                        "recipient_device_id": a_device,
                        "message_type": 0,
                        "payload": base64.b64encode(b"before answering").decode(),
                    }
                ]
            },
            headers=b.headers,
        )

        assert sent.status_code == 404
        assert sent.json()["detail"] == "DM_CONVERSATION_NOT_FOUND"
        collected = await client.get(
            f"/api/v1/me/dm/queue?device_id={a_device}", headers=a.headers
        )
        assert collected.json()["items"] == []

    async def test_answering_twice_is_refused(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await self._reachable(session, [a, b, c])
        conversation_id = (await self._propose(client, a, [b, c])).json()["id"]
        await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/accept", headers=b.headers
        )

        again = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/accept", headers=b.headers
        )

        assert again.status_code == 404
        assert again.json()["detail"] == "DM_NO_INVITATION"

    async def test_a_roster_that_cannot_reach_itself_is_refused(
        self, client, session, acting_user
    ):
        """B and C are strangers to each other, whatever A is to both."""
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await _set_policy(session, a.user, DmPolicy.public)
        await _set_policy(session, b.user, DmPolicy.public)
        # C admits only the accounts it is connected to, and that is A alone.
        await _set_policy(session, c.user, DmPolicy.private)
        await _connect(session, a.user, c.user)

        made = await self._propose(client, a, [b, c])

        assert made.status_code == 409
        assert made.json()["detail"] == "DM_ROSTER_NOT_REACHABLE"

    async def test_the_check_names_the_pair_before_anybody_commits(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await _set_policy(session, a.user, DmPolicy.public)
        await _set_policy(session, b.user, DmPolicy.public)
        await _set_policy(session, c.user, DmPolicy.private)
        await _connect(session, a.user, c.user)

        checked = await client.post(
            "/api/v1/me/dm/roster-check",
            json={"user_ids": [b.user.id, c.user.id]},
            headers=a.headers,
        )

        assert checked.status_code == 200, checked.text
        assert checked.json()["unreachable_pair"] == sorted([b.user.id, c.user.id])
        assert checked.json()["too_large"] is False

        # Asked by somebody who cannot reach C, the answer is their own pair.
        d = await acting_user()
        await _set_policy(session, d.user, DmPolicy.public)
        asked = await client.post(
            "/api/v1/me/dm/roster-check",
            json={"user_ids": [b.user.id, c.user.id]},
            headers=d.headers,
        )
        assert asked.json()["unreachable_pair"] == sorted([d.user.id, c.user.id])

    async def test_a_reachable_roster_checks_clean(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await self._reachable(session, [a, b, c])

        checked = await client.post(
            "/api/v1/me/dm/roster-check",
            json={"user_ids": [b.user.id, c.user.id]},
            headers=a.headers,
        )

        assert checked.json()["unreachable_pair"] == []
        assert checked.json()["max_members"] == 40

    async def test_two_people_are_not_a_group(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        await self._reachable(session, [a, b])

        made = await self._propose(client, a, [b])

        assert made.status_code == 422, made.text

    async def test_proposing_the_same_roster_asks_whoever_is_not_on_it(
        self, client, session, acting_user
    ):
        """Somebody who declined may have changed their mind, or their settings."""
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        await self._reachable(session, [a, b, c])
        conversation_id = (await self._propose(client, a, [b, c])).json()["id"]
        # C declines, which is the ordinary leave.
        left = await client.delete(
            f"/api/v1/me/dm/conversations/{conversation_id}", headers=c.headers
        )
        assert left.status_code == 204, left.text

        again = await self._propose(client, a, [b, c])

        assert again.status_code == 201, again.text
        assert again.json()["id"] == conversation_id
        theirs = await client.get("/api/v1/me/dm/conversations", headers=c.headers)
        asked = next(
            row
            for row in theirs.json()["conversations"]
            if row["id"] == conversation_id
        )
        assert asked["pending"] is True


class TestAGroupSend:
    """Three people on one conversation. Nothing can make one through the API
    yet, so the roster is written directly — the send path is what is under
    test, and it is already meant to carry any roster."""

    async def _group(self, client, session, members):

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

    async def _send_to(self, client, actor, conversation_id, device_ids):
        return await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/messages",
            json={
                "messages": [
                    {
                        "recipient_device_id": device_id,
                        "message_type": 0,
                        "payload": base64.b64encode(b"for the group").decode(),
                    }
                    for device_id in device_ids
                ]
            },
            headers=actor.headers,
        )

    async def _waiting(self, client, actor, device_id) -> int:
        collected = await client.get(
            f"/api/v1/me/dm/queue?device_id={device_id}", headers=actor.headers
        )
        return len(collected.json()["items"])

    async def test_one_message_reaches_every_member(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        conversation_id, devices = await self._group(client, session, [a, b, c])

        sent = await self._send_to(
            client, a, conversation_id, [devices[b.user.id], devices[c.user.id]]
        )

        assert sent.status_code == 200, sent.text
        assert sent.json()["accepted"] == 2
        assert sent.json()["queue_full_for"] == []
        assert await self._waiting(client, b, devices[b.user.id]) == 1
        assert await self._waiting(client, c, devices[c.user.id]) == 1

    async def test_one_member_ignoring_does_not_stop_the_others(
        self, client, session, acting_user
    ):
        """Delivery is asked per recipient, and the sender is answered the same."""
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        conversation_id, devices = await self._group(client, session, [a, b, c])
        session.add(UserIgnore(user_id=b.user.id, ignored_user_id=a.user.id))
        await session.commit()

        sent = await self._send_to(
            client, a, conversation_id, [devices[b.user.id], devices[c.user.id]]
        )

        assert sent.status_code == 200, sent.text
        # Unmoved, so the ignore is invisible here exactly as it is for a pair.
        assert sent.json()["accepted"] == 2
        assert sent.json()["queue_full_for"] == []
        assert await self._waiting(client, b, devices[b.user.id]) == 0
        assert await self._waiting(client, c, devices[c.user.id]) == 1

    async def test_a_device_nobody_on_the_roster_owns_is_dropped(
        self, client, session, acting_user
    ):
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        outsider = await acting_user()
        conversation_id, devices = await self._group(client, session, [a, b, c])
        await _set_policy(session, outsider.user, DmPolicy.public)
        await _open_channel(session, a.user, outsider.user)
        theirs = await _register(client, outsider, seed=200)

        sent = await self._send_to(
            client, a, conversation_id, [devices[b.user.id], theirs]
        )

        assert sent.status_code == 200, sent.text
        assert await self._waiting(client, b, devices[b.user.id]) == 1
        assert await self._waiting(client, outsider, theirs) == 0


class TestAFullMailbox:
    """The ceiling refuses a send it cannot keep. What differs with a roster is
    that one full mailbox is not everybody's."""

    async def _fill(self, session, user_id: int) -> None:
        """Put this account over its ceiling, without moving a real message."""
        from app.services.platform.dm_transport import QUEUE_CEILING_BYTES

        await session.exec(
            text(
                "INSERT INTO public.dm_queue "
                "(conversation_id, recipient_device_id, message_type, payload, created_at) "
                "SELECT c.id, d.id, 1, repeat('x', :n)::bytea, now() "
                "  FROM public.dm_devices d "
                "  JOIN public.dm_conversation_members m ON m.user_id = d.user_id "
                "  JOIN public.dm_conversations c ON c.id = m.conversation_id "
                " WHERE d.user_id = :u LIMIT 1"
            ).bindparams(n=QUEUE_CEILING_BYTES, u=user_id)
        )
        await session.commit()

    async def test_a_pair_is_refused(self, client, session, acting_user):
        a = await acting_user()
        b = await acting_user()
        conversation_id, _a_device, b_device = await _conversation_with_devices(
            client, session, a, b
        )
        await self._fill(session, b.user.id)

        sent = await client.post(
            f"/api/v1/me/dm/conversations/{conversation_id}/messages",
            json={
                "messages": [
                    {
                        "recipient_device_id": b_device,
                        "message_type": 0,
                        "payload": base64.b64encode(b"too much").decode(),
                    }
                ]
            },
            headers=a.headers,
        )

        assert sent.status_code == 507
        assert sent.json()["detail"] == "DM_RECIPIENT_QUEUE_FULL"

    async def test_a_group_delivers_to_the_rest_and_says_who_missed_it(
        self, client, session, acting_user
    ):
        """One abandoned phone is not a reason the others hear nothing."""
        group = TestAGroupSend()
        a = await acting_user()
        b = await acting_user()
        c = await acting_user()
        conversation_id, devices = await group._group(client, session, [a, b, c])
        await self._fill(session, b.user.id)

        sent = await group._send_to(
            client, a, conversation_id, [devices[b.user.id], devices[c.user.id]]
        )

        assert sent.status_code == 200, sent.text
        assert sent.json()["queue_full_for"] == [b.user.id]
        assert await group._waiting(client, c, devices[c.user.id]) == 1


async def test_collecting_then_acknowledging_removes_the_row(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    conversation_id, _a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )
    await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": b_device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"collect me").decode(),
                }
            ]
        },
        headers=a.headers,
    )
    collected = await client.get(
        f"/api/v1/me/dm/queue?device_id={b_device}", headers=b.headers
    )
    message_id = collected.json()["items"][0]["id"]

    acked = await client.post(
        "/api/v1/me/dm/queue/ack",
        json={"device_id": b_device, "message_ids": [message_id]},
        headers=b.headers,
    )
    assert acked.status_code == 204

    remaining = (
        await session.exec(text("SELECT count(*) FROM public.dm_queue"))
    ).scalar_one()
    assert remaining == 0


async def test_a_queue_belongs_to_its_device(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    _conversation_id, _a_device, b_device = await _conversation_with_devices(
        client, session, a, b
    )

    response = await client.get(
        f"/api/v1/me/dm/queue?device_id={b_device}", headers=a.headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "DM_DEVICE_NOT_FOUND"


async def test_messaging_yourself_is_refused(client, acting_user):
    a = await acting_user()

    response = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": a.user.id}, headers=a.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "DM_CANNOT_MESSAGE_SELF"


# ------------------------------------------------------- own devices ---


async def test_the_directory_hands_over_keys_without_claiming_one(
    client, session, acting_user
):
    """The route an inbound pre-key message is answered with.

    It reads; it must not spend. Reading it to decrypt somebody's message would
    otherwise cost a prekey per collection.
    """
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    await _register(client, b, seed=90)

    response = await client.get(
        f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
    )
    assert response.status_code == 200, response.text
    device = response.json()["devices"][0]
    assert device["identity_key"]
    assert device["one_time_key"] is None

    remaining = (
        await session.exec(
            text("SELECT count(*) FROM public.dm_one_time_keys WHERE fallback IS FALSE")
        )
    ).scalar_one()
    assert remaining == 1


async def test_a_stranger_reads_no_directory(client, session, acting_user):
    a = await acting_user()
    b = await acting_user()
    await _register(client, b, seed=91)

    response = await client.get(
        f"/api/v1/users/{b.user.id}/dm/devices", headers=a.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "DM_NOT_REACHABLE"


async def test_own_session_keys_skip_the_asking_device(client, acting_user):
    a = await acting_user()
    first = await _register(client, a, seed=92)
    second = await _register(client, a, seed=93)

    response = await client.post(
        "/api/v1/me/dm/session-keys", json={"device_id": first}, headers=a.headers
    )
    assert response.status_code == 200, response.text
    devices = response.json()["devices"]
    assert [device["device_id"] for device in devices] == [second]
    # A device of your own is a separate ratchet, so it costs a prekey like
    # anybody else's.
    assert devices[0]["one_time_key"]["key_id"] == "otk-1"


async def test_a_message_reaches_the_senders_other_device(client, session, acting_user):
    """The outbox, which is what makes a second client usable at all."""
    a = await acting_user()
    b = await acting_user()
    await _set_policy(session, a.user, DmPolicy.public)
    await _set_policy(session, b.user, DmPolicy.public)
    await _open_channel(session, a.user, b.user)
    a_laptop = await _register(client, a, seed=94)
    a_phone = await _register(client, a, seed=95)
    b_device = await _register(client, b, seed=96)

    created = await client.post(
        "/api/v1/me/dm/conversations", json={"user_id": b.user.id}, headers=a.headers
    )
    conversation_id = created.json()["id"]

    keys = await client.post(
        "/api/v1/me/dm/session-keys", json={"device_id": a_laptop}, headers=a.headers
    )
    targets = [device["device_id"] for device in keys.json()["devices"]]
    assert a_phone in targets

    await client.post(
        f"/api/v1/me/dm/conversations/{conversation_id}/messages",
        json={
            "messages": [
                {
                    "recipient_device_id": device,
                    "message_type": 0,
                    "payload": base64.b64encode(b"outbox").decode(),
                }
                for device in [b_device, a_phone]
            ]
        },
        headers=a.headers,
    )

    waiting = await client.get(
        f"/api/v1/me/dm/queue?device_id={a_phone}", headers=a.headers
    )
    assert len(waiting.json()["items"]) == 1


async def test_a_verification_message_is_collected_once_by_its_device(
    client, session, acting_user
):
    a = await acting_user()
    b = await acting_user()
    a_laptop = await _register(client, a, seed=97)
    a_phone = await _register(client, a, seed=98)
    b_device = await _register(client, b, seed=99)

    def send(to_device: str, body: str):
        return client.post(
            "/api/v1/me/dm/verification",
            json={"device_id": a_laptop, "to_device_id": to_device, "body": body},
            headers=a.headers,
        )

    def collect():
        return client.get(
            f"/api/v1/me/dm/verification?device_id={a_phone}", headers=a.headers
        )

    sent = await send(a_phone, '{"type":"start"}')
    assert sent.status_code == 204, sent.text
    first = await collect()
    assert first.status_code == 200, first.text
    [item] = first.json()["items"]
    assert item["sender_device_id"] == a_laptop
    assert item["body"] == '{"type":"start"}'
    assert (await collect()).json()["items"] == []

    # Another account's device is not one of yours.
    refused = await send(b_device, '{"type":"start"}')
    assert refused.status_code == 404
    assert refused.json()["detail"] == "DM_DEVICE_NOT_FOUND"

    # Past its ten minutes, a message is not delivered, and is cleared.
    await send(a_phone, '{"type":"stale"}')
    await session.exec(
        text(
            "UPDATE public.dm_verification_messages "
            "SET created_at = now() - interval '11 minutes'"
        )
    )
    await session.commit()
    assert (await collect()).json()["items"] == []
    remaining = (
        await session.exec(text("SELECT count(*) FROM public.dm_verification_messages"))
    ).scalar_one()
    assert remaining == 0
