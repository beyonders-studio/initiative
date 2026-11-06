"""Channel routing for push notifications.

The Android channel a notification lands on is chosen here and sent to FCM in
the payload; the app can only honour a channel it already created. Nothing at
runtime reconciles the two, so these tests hold the backend map and the app's
registered channels together.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from app.models.platform.notification import Notification, NotificationType
from app.services.platform.push_notifications import (
    DEFAULT_CHANNEL,
    PUSH_CHANNELS,
    channel_for,
)

_ANDROID_CHANNELS = (
    Path(__file__).resolve().parents[3]
    / ".."
    / "frontend"
    / "android"
    / "app"
    / "src"
    / "main"
    / "java"
    / "studio"
    / "beyonders"
    / "initiative"
    / "NotificationChannelManager.java"
)

# Types that only ever become an in-app notification — no push is sent for
# them, so they need no channel of their own.
_IN_APP_ONLY = {
    NotificationType.export_ready,
    NotificationType.export_failed,
    NotificationType.import_ready,
    NotificationType.import_failed,
    # Sent when a moderator takes a profile picture down. It belongs in the
    # inbox, where it can be read next to the settings page that acts on it,
    # rather than as an interruption on a device.
    NotificationType.avatar_removed,
    # The other three moderation notices, for the same reason: they belong in
    # the inbox next to the settings page they are about, and none of them is
    # urgent enough to interrupt someone on a device.
    NotificationType.username_changed,
    NotificationType.profile_field_cleared,
    NotificationType.account_suspended,
    NotificationType.account_unsuspended,
    # A community put on hold: an inbox notice beside its email, about paying
    # for it, which is no reason to interrupt someone on a device.
    NotificationType.community_on_hold,
    # A trial ending or ended, or a new community's plan to choose: the same
    # errand as a hold, told the same way.
    NotificationType.community_trial_ending,
    NotificationType.community_trial_ended,
    NotificationType.community_pause_reminder,
    NotificationType.community_welcome,
    # A plug-in asking a member to consent: answered on the plug-in's settings, where
    # it waits until they get to it.
    NotificationType.plugin_consent_requested,
    # A version of an installed plug-in waiting for the seat: it waits on the
    # settings page until they get to it, so nothing is gained by interrupting
    # them on a device.
    NotificationType.plugin_update_pending,
}


def test_every_pushed_notification_type_has_a_channel():
    """A new notification type that pushes must pick a channel. Defaulting is
    silent — the notification still arrives, just filed under "General" where
    the user can't mute it separately from everything else."""
    assert set(PUSH_CHANNELS) == set(NotificationType) - _IN_APP_ONLY


def test_in_app_only_types_fall_back_to_the_general_channel():
    for notification_type in _IN_APP_ONLY:
        assert channel_for(notification_type) == DEFAULT_CHANNEL
    assert channel_for(None) == DEFAULT_CHANNEL


@pytest.mark.always
def test_channels_are_registered_by_the_android_app():
    """Every channel the backend routes to must be one the app creates on
    launch. A channel id the app never created is not an error anywhere — the
    notification quietly lands in Firebase's own fallback channel instead."""
    source = _ANDROID_CHANNELS.read_text(encoding="utf-8")
    # Each channel is declared as `String CHANNEL_X = "<id>";`
    registered = set(re.findall(r'String CHANNEL_\w+ = "([^"]+)"', source))
    assert registered, "no channel constants found — did the Java file move?"

    missing = (set(PUSH_CHANNELS.values()) | {DEFAULT_CHANNEL}) - registered
    assert not missing, f"channels missing from the Android app: {sorted(missing)}"

    # Each declared constant must also be passed to createChannel(), or it is
    # a name the app never actually registers.
    created = set(re.findall(r"CHANNEL_(\w+),", source))
    declared = set(re.findall(r"String CHANNEL_(\w+) = ", source))
    assert declared - created == set(), (
        f"declared but never created: {sorted(declared - created)}"
    )


@pytest.mark.always
def test_the_manifest_falls_back_to_a_channel_the_app_creates():
    """The web bundle updates over the air; channels ship with the APK.

    So a server that has moved on can address a channel an installed build has
    never registered. Firebase then uses the manifest's fallback — and if that
    names nothing real either, it invents a "Miscellaneous" channel outside the
    app's own notification settings, where nothing the user has muted applies.
    """
    manifest = (
        _ANDROID_CHANNELS.parent.parent.parent.parent.parent / "AndroidManifest.xml"
    )
    source = manifest.read_text(encoding="utf-8")
    declared = re.search(
        r'android:name="com\.google\.firebase\.messaging\.default_notification_channel_id"\s*'
        r'android:value="([^"]+)"',
        source,
    )
    assert declared, "no Firebase fallback channel declared in the manifest"

    registered = set(
        re.findall(
            r'String CHANNEL_\w+ = "([^"]+)"',
            _ANDROID_CHANNELS.read_text(encoding="utf-8"),
        )
    )
    assert declared.group(1) in registered, (
        f"manifest falls back to {declared.group(1)!r}, which the app never creates"
    )


# --- the recipient's devices ---------------------------------------------------


async def test_delivery_reads_stamps_and_prunes_the_devices(session, monkeypatch):
    """The recipient's rows are read, the delivered one stamped and the dead
    one dropped. A device whose session has ended, or that names no sign-in,
    is not sent to and is dropped too. The same value registered by another
    account is left alone. Each send carries the recipient's unread count."""
    from app.models.platform.push_token import PushToken
    from app.services.platform import push_notifications, push_tokens
    from app.testing import create_user

    # FCM's switch moved onto the settings row in 0368, so the gate is the
    # resolved config rather than the env var. Patched here instead of seeded
    # through the cache so this test still asserts only what it is about --
    # which devices are sent to and kept.
    from app.services.platform import push_config

    async def _enabled():
        return push_config.ResolvedPushConfig(
            enabled=True,
            project_id="test-project",
            application_id=None,
            api_key=None,
            sender_id=None,
            service_account_json=None,
        )

    monkeypatch.setattr(push_config, "ensure_push_config_fresh", _enabled)

    badges: list[int | None] = []

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
        badges.append(badge)
        return (True, False) if push_token == "live" else (False, True)

    monkeypatch.setattr(push_notifications, "send_push_notification", _send)

    from app.services.auth import sessions as session_service

    recipient = await create_user(session)
    bystander = await create_user(session)
    # A sign-in holds one registration, so the live and the dead device are
    # two phones.
    signed_in, other_phone, signed_out, elsewhere = [
        (
            await session_service.create_session(
                session, user_id=user.id, amr=["pwd"], satisfied_providers=[]
            )
        ).session.id
        for user in (recipient, recipient, recipient, bystander)
    ]
    await session_service.revoke_session(session, session_id=signed_out)
    for user, value, sid in (
        (recipient, "live", signed_in),
        (recipient, "gone", other_phone),
        (recipient, "signed-out", signed_out),
        (recipient, "unlinked", None),
        (bystander, "gone", elsewhere),
    ):
        await push_tokens.register_push_token(
            session,
            user_id=user.id,
            push_token=value,
            platform="android",
            session_id=sid,
        )
    recipient_id, bystander_id = recipient.id, bystander.id
    for read_at in (None, None, datetime.now(timezone.utc)):
        session.add(
            Notification(
                user_id=recipient_id,
                type=NotificationType.mention,
                data={},
                read_at=read_at,
            )
        )
    await session.flush()

    again = await push_notifications.send_pushes(
        session,
        [push_notifications.Push(recipient_id, NotificationType.mention, "t", "b", {})],
    )
    await session.commit()
    assert again == [False]
    assert badges == [2, 2]

    session.expire_all()
    rows = (
        await session.exec(
            select(PushToken).where(PushToken.user_id.in_([recipient_id, bystander_id]))
        )
    ).all()
    held = {(row.user_id, row.push_token): row for row in rows}
    assert set(held) == {
        (recipient_id, "live"),
        (bystander_id, "gone"),
    }
    assert held[(recipient_id, "live")].last_used_at is not None
    assert held[(bystander_id, "gone")].last_used_at is None


async def test_access_token_is_reused_until_it_lapses(monkeypatch):
    """One credential per service account: refreshed when it is not valid,
    reused while it is, and rebuilt when the configured account changes."""
    from app.services.platform import push_config, push_notifications

    built: list[dict] = []
    made: list["_Credentials"] = []

    class _Credentials:
        def __init__(self, info):
            built.append(info)
            made.append(self)
            self.valid = False
            self.token = None
            self.refreshes = 0

        def refresh(self, _request):
            self.refreshes += 1
            self.valid = True
            self.token = f"token-{len(built)}"

    monkeypatch.setattr(
        push_notifications.service_account.Credentials,
        "from_service_account_info",
        lambda info, scopes: _Credentials(info),
    )
    monkeypatch.setattr(push_notifications, "_credentials", None)

    def _cfg(account: str) -> push_config.ResolvedPushConfig:
        return push_config.ResolvedPushConfig(
            enabled=True,
            project_id="p",
            application_id=None,
            api_key=None,
            sender_id=None,
            service_account_json=f'{{"account": "{account}"}}',
        )

    assert await push_notifications._get_fcm_access_token(_cfg("a")) == "token-1"
    assert await push_notifications._get_fcm_access_token(_cfg("a")) == "token-1"
    assert made[0].refreshes == 1

    made[0].valid = False
    assert await push_notifications._get_fcm_access_token(_cfg("a")) == "token-1"
    assert made[0].refreshes == 2

    assert await push_notifications._get_fcm_access_token(_cfg("b")) == "token-2"
    assert built == [{"account": "a"}, {"account": "b"}]


async def test_a_renewed_session_carries_its_device(session):
    """A refresh moves the device to the row that succeeds its session."""
    from app.services.auth import sessions as session_service
    from app.services.platform import push_tokens
    from app.testing import create_user

    user = await create_user(session)
    user_id = user.id
    issued = await session_service.create_session(
        session, user_id=user_id, amr=["pwd"], satisfied_providers=[]
    )
    await push_tokens.register_push_token(
        session,
        user_id=user_id,
        push_token="phone",
        platform="android",
        session_id=issued.session.id,
    )
    rotated = await session_service.rotate_session(
        session, raw_refresh_token=issued.refresh_token
    )
    renewed_id = rotated.issued.session.id
    await session.commit()

    (row,) = await push_tokens.get_push_tokens_for_user(session, user_id=user_id)
    await session.refresh(row)
    assert row.session_id == renewed_id


# --- where a push goes: FCM or the push relay ---------------------------------

_RELAY = "https://relay.test"
#: Relay handles, which is all a server holds for a device the relay serves.
_IOS_HANDLE = "rh_" + "A" * 43
_ANDROID_HANDLE = "rh_" + "b" * 43


def _push_cfg(*, service_account: bool, project_id: str | None = "own-project"):
    from app.services.platform import push_config

    return push_config.ResolvedPushConfig(
        enabled=True,
        project_id=project_id,
        application_id=None,
        api_key=None,
        sender_id=None,
        service_account_json='{"type": "service_account"}' if service_account else None,
    )


class _Wire:
    """Every request a push makes, answered with ``status`` (or, for a
    registration, a new credential)."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.sends: list[httpx.Request] = []
        self.registrations = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/servers":
            self.registrations += 1
            n = self.registrations
            return httpx.Response(
                201, json={"server_id": f"srv_new{n}", "server_key": f"new-{n}"}
            )
        self.sends.append(request)
        if self.status == 200:
            return httpx.Response(200, json={"name": "projects/p/messages/1"})
        return httpx.Response(self.status, json={"error": {"code": self.status}})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def push_wire(monkeypatch):
    """A deployment with push on, holding relay credential ``srv_1.key-1``,
    and an FCM access token for when it has a service account."""
    from app.services.platform import push_config, push_notifications, push_relay

    monkeypatch.setattr(push_relay, "PUSH_RELAY_URL", _RELAY)
    push_relay.reset_for_tests()
    monkeypatch.setattr(push_relay, "_credentials", ("srv_1", "key-1"))

    async def _token(cfg):
        return "google-token"

    monkeypatch.setattr(push_notifications, "_get_fcm_access_token", _token)

    def configure(cfg) -> None:
        async def _fresh():
            return cfg

        monkeypatch.setattr(push_config, "ensure_push_config_fresh", _fresh)

    yield configure
    push_relay.reset_for_tests()


async def _send_one(wire: _Wire, *, token: str, platform: str) -> tuple[bool, bool]:
    from app.services.platform import push_notifications

    async with wire.client() as client:
        return await push_notifications.send_push_notification(
            client,
            push_token=token,
            title="t",
            body="b",
            data={"target_path": "/tasks/1"},
            channel_id="mention",
            platform=platform,
        )


@pytest.mark.parametrize(
    ("token", "platform"),
    [(_IOS_HANDLE, "ios"), (_ANDROID_HANDLE, "android")],
)
async def test_only_an_iphone_is_sent_the_badge(push_wire, token, platform):
    """An Android launcher counts the tray's notifications itself."""
    from app.services.platform import push_notifications

    push_wire(_push_cfg(service_account=False))
    wire = _Wire()

    async with wire.client() as client:
        await push_notifications.send_push_notification(
            client, push_token=token, title="t", body="b", platform=platform, badge=3
        )

    (request,) = wire.sends
    message = json.loads(request.content)["message"]
    if platform == "ios":
        assert message["apns"] == {"payload": {"aps": {"badge": 3}}}
    else:
        assert "apns" not in message


@pytest.mark.parametrize("service_account", [True, False])
async def test_an_iphone_always_goes_through_the_relay(push_wire, service_account):
    push_wire(_push_cfg(service_account=service_account))
    wire = _Wire()

    assert await _send_one(wire, token=_IOS_HANDLE, platform="ios") == (True, False)

    (request,) = wire.sends
    assert str(request.url) == f"{_RELAY}/v1/projects/own-project/messages:send"
    assert request.headers["authorization"] == "Bearer srv_1.key-1"
    # The relay reads the platform from the handle's own record.
    assert "x-push-platform" not in request.headers
    message = json.loads(request.content)["message"]
    assert message["token"] == _IOS_HANDLE
    assert message["notification"] == {"title": "t", "body": "b"}
    assert message["data"] == {"target_path": "/tasks/1"}


async def test_android_goes_to_fcm_with_a_service_account(push_wire):
    push_wire(_push_cfg(service_account=True))
    wire = _Wire()

    assert await _send_one(wire, token="fcm-token", platform="android") == (
        True,
        False,
    )

    (request,) = wire.sends
    assert str(request.url) == (
        "https://fcm.googleapis.com/v1/projects/own-project/messages:send"
    )
    assert request.headers["authorization"] == "Bearer google-token"
    assert "x-push-platform" not in request.headers


async def test_android_goes_through_the_relay_without_a_service_account(push_wire):
    """No project id is needed either: the relay sends through its own."""
    push_wire(_push_cfg(service_account=False, project_id=None))
    wire = _Wire()

    assert await _send_one(wire, token=_ANDROID_HANDLE, platform="android") == (
        True,
        False,
    )

    (request,) = wire.sends
    assert str(request.url) == f"{_RELAY}/v1/projects/relay/messages:send"
    assert request.headers["authorization"] == "Bearer srv_1.key-1"
    assert "x-push-platform" not in request.headers
    assert json.loads(request.content)["message"]["token"] == _ANDROID_HANDLE


@pytest.mark.parametrize(
    ("service_account", "token", "platform"),
    [
        # A device token from before the app asked the relay for handles.
        (False, "ab" * 32, "ios"),
        (False, "fcm-token", "android"),
        # A handle the device registered before the operator added a service
        # account, which FCM cannot address.
        (True, _ANDROID_HANDLE, "android"),
    ],
)
async def test_a_token_of_the_wrong_kind_is_dropped_unsent(
    push_wire, service_account, token, platform
):
    push_wire(_push_cfg(service_account=service_account))
    wire = _Wire()

    assert await _send_one(wire, token=token, platform=platform) == (False, True)
    assert wire.sends == []


async def test_a_token_the_relay_does_not_know_is_deleted(push_wire):
    push_wire(_push_cfg(service_account=False))
    assert await _send_one(_Wire(404), token=_IOS_HANDLE, platform="ios") == (
        False,
        True,
    )


async def test_a_refused_relay_key_is_forgotten_and_replaced(push_wire, session):
    """A 401 keeps the token, drops the key, and the next push registers."""
    from app.services.platform import app_settings as app_settings_service

    await app_settings_service.seed_app_settings(session)
    await session.commit()
    push_wire(_push_cfg(service_account=False))

    refused = _Wire(401)
    assert await _send_one(refused, token=_IOS_HANDLE, platform="ios") == (
        False,
        False,
    )
    assert refused.registrations == 0

    wire = _Wire()
    assert await _send_one(wire, token=_IOS_HANDLE, platform="ios") == (True, False)
    assert wire.registrations == 1
    assert wire.sends[0].headers["authorization"] == "Bearer srv_new1.new-1"


async def test_a_suspended_server_does_not_register_again(push_wire):
    from app.services.platform import push_relay

    push_wire(_push_cfg(service_account=False))
    wire = _Wire(403)

    assert await _send_one(wire, token=_IOS_HANDLE, platform="ios") == (False, False)
    assert await _send_one(wire, token=_IOS_HANDLE, platform="ios") == (False, False)

    assert wire.registrations == 0
    assert push_relay._credentials == ("srv_1", "key-1")


async def test_no_relay_credential_sends_nothing(push_wire, monkeypatch):
    from app.services.platform import push_relay

    async def _none(client):
        return None

    monkeypatch.setattr(push_relay, "credentials", _none)
    push_wire(_push_cfg(service_account=False))
    wire = _Wire()

    assert await _send_one(wire, token=_IOS_HANDLE, platform="ios") == (False, False)
    assert wire.sends == []


async def test_each_device_is_sent_on_its_own_platform(monkeypatch):
    from app.models.platform.push_token import PushToken
    from app.services.platform import push_notifications

    seen: dict[str, str] = {}

    async def _send(client, *, push_token, platform, **_):
        seen[push_token] = platform
        return (True, False)

    monkeypatch.setattr(push_notifications, "send_push_notification", _send)
    tokens = [
        PushToken(id=1, user_id=1, push_token="phone", platform="ios"),
        PushToken(id=2, user_id=1, push_token="tablet", platform="android"),
    ]
    async with httpx.AsyncClient() as client:
        outcome = await push_notifications._send_to_devices(
            client, tokens, title="t", body="b", data=None, channel_id="default"
        )

    assert seen == {"phone": "ios", "tablet": "android"}
    assert outcome.delivered_ids == [1, 2]
