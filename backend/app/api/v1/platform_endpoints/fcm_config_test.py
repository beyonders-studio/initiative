"""``GET /settings/fcm-config``: the Firebase settings the app starts with.

With a service account the server's own settings are served; without one
pushes go through the push relay, and the relay's Android settings are. A
phone whose pushes go through the relay (an iPhone always, Android without a
service account) is served the server's relay id too, to ask the relay for a
device handle under; nobody else is, and nobody else makes the server
register with the relay.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from app.services.platform import push_config, push_relay

URL = "/api/v1/settings/fcm-config"

_RELAY_ANDROID = push_relay.AndroidConfig(
    project_id="beyonders-studio-app",
    application_id="1:2:android:3",
    api_key="relay-api-key",
    sender_id="42",
)


def _configure(monkeypatch, *, enabled: bool, service_account: bool) -> None:
    cfg = push_config.ResolvedPushConfig(
        enabled=enabled,
        project_id="own-project",
        application_id="1:9:android:9",
        api_key="own-api-key",
        sender_id="9",
        service_account_json='{"type": "service_account"}' if service_account else None,
    )
    monkeypatch.setattr(
        push_config, "ensure_push_config_fresh", AsyncMock(return_value=cfg)
    )


_SERVER_ID = "srv_0123456789abcdef"


@pytest.fixture
def relay_android(monkeypatch) -> Iterator[AsyncMock]:
    fetch = AsyncMock(return_value=_RELAY_ANDROID)
    monkeypatch.setattr(push_relay, "android_config", fetch)
    push_relay.reset_for_tests()
    monkeypatch.setattr(push_relay, "_credentials", (_SERVER_ID, "key"))
    yield fetch
    push_relay.reset_for_tests()


async def test_push_off_serves_nothing(client, monkeypatch, relay_android):
    _configure(monkeypatch, enabled=False, service_account=False)

    response = await client.get(URL)

    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "project_id": None,
        "application_id": None,
        "api_key": None,
        "sender_id": None,
        "push_relay_server_id": None,
        "android_via_relay": False,
    }
    relay_android.assert_not_awaited()


async def test_a_service_account_serves_the_servers_own_settings(
    client, monkeypatch, relay_android
):
    _configure(monkeypatch, enabled=True, service_account=True)

    response = await client.get(URL, params={"platform": "ios"})

    assert response.json() == {
        "enabled": True,
        "project_id": "own-project",
        "application_id": "1:9:android:9",
        "api_key": "own-api-key",
        "sender_id": "9",
        # iPhones still go through the relay; Android goes to FCM directly.
        "push_relay_server_id": _SERVER_ID,
        "android_via_relay": False,
    }
    relay_android.assert_not_awaited()


@pytest.mark.parametrize("platform", ["android", None])
async def test_own_firebase_never_contacts_the_relay_for_android(
    client, session, monkeypatch, relay_android, platform
):
    """A server with its own Firebase sends Android straight to FCM, so an
    Android phone (or a caller that names no platform) is served no relay id,
    and the server does not register with the relay to answer it."""
    from app.services.platform import app_settings as app_settings_service

    await app_settings_service.seed_app_settings(session)
    await session.commit()
    _configure(monkeypatch, enabled=True, service_account=True)
    push_relay.reset_for_tests()
    register = AsyncMock(return_value=(_SERVER_ID, "issued-key"))
    monkeypatch.setattr(push_relay, "_register", register)

    params = {"platform": platform} if platform else {}
    response = await client.get(URL, params=params)

    assert response.json()["project_id"] == "own-project"
    assert response.json()["push_relay_server_id"] is None
    register.assert_not_awaited()
    relay_android.assert_not_awaited()


async def test_no_service_account_serves_the_relays_settings(
    client, monkeypatch, relay_android
):
    _configure(monkeypatch, enabled=True, service_account=False)

    response = await client.get(URL, params={"platform": "android"})

    assert response.json() == {
        "enabled": True,
        "project_id": "beyonders-studio-app",
        "application_id": "1:2:android:3",
        "api_key": "relay-api-key",
        "sender_id": "42",
        "push_relay_server_id": _SERVER_ID,
        "android_via_relay": True,
    }

    # The native shells ask only for the Firebase settings, and naming no
    # platform serves no relay id.
    response = await client.get(URL)

    assert response.json()["project_id"] == "beyonders-studio-app"
    assert response.json()["push_relay_server_id"] is None


async def test_relay_settings_unavailable_still_says_enabled(
    client, monkeypatch, relay_android
):
    """An iPhone needs only the relay id; Android gets no Firebase project."""
    _configure(monkeypatch, enabled=True, service_account=False)
    relay_android.return_value = None

    response = await client.get(URL, params={"platform": "ios"})

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "project_id": None,
        "application_id": None,
        "api_key": None,
        "sender_id": None,
        "push_relay_server_id": _SERVER_ID,
        "android_via_relay": True,
    }


@pytest.mark.parametrize("service_account", [True, False])
async def test_an_iphone_asking_registers_with_the_relay(
    client, session, monkeypatch, relay_android, service_account
):
    """The first iPhone to ask registers this server and keeps the
    credential; the next ask reads it back rather than registering again."""
    from app.services.platform import app_settings as app_settings_service

    await app_settings_service.seed_app_settings(session)
    await session.commit()
    _configure(monkeypatch, enabled=True, service_account=service_account)
    push_relay.reset_for_tests()
    register = AsyncMock(return_value=(_SERVER_ID, "issued-key"))
    monkeypatch.setattr(push_relay, "_register", register)

    first = await client.get(URL, params={"platform": "ios"})
    push_relay.reset_for_tests()
    second = await client.get(URL, params={"platform": "ios"})

    assert first.json()["push_relay_server_id"] == _SERVER_ID
    assert second.json()["push_relay_server_id"] == _SERVER_ID
    assert register.await_count == 1


async def test_a_failed_registration_serves_no_relay_id(
    client, monkeypatch, relay_android
):
    _configure(monkeypatch, enabled=True, service_account=True)
    monkeypatch.setattr(push_relay, "credentials", AsyncMock(return_value=None))

    response = await client.get(URL, params={"platform": "ios"})

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["push_relay_server_id"] is None


async def test_an_unknown_platform_is_refused(client, monkeypatch, relay_android):
    _configure(monkeypatch, enabled=True, service_account=True)

    response = await client.get(URL, params={"platform": "windows"})

    assert response.status_code == 422
