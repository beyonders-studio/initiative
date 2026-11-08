"""This server's registration with the push relay, and the relay's Android
settings.

The relay is stood in for by an ``httpx2.MockTransport``; the credential is
stored for real, on ``app_setting_secrets``, through the system engine.
"""

from __future__ import annotations

import json

import httpx2
import pytest
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.encryption import SALT_PUSH_RELAY_KEY, decrypt_field, encrypt_field
from app.models.platform.app_setting_secret import AppSettingSecret
from app.services.platform import app_settings as app_settings_service
from app.services.platform import push_relay

RELAY = "https://relay.test"


class FakeRelay:
    """The relay's registration and Android-settings routes."""

    def __init__(self) -> None:
        self.registrations: list[dict] = []
        self.register_status = 201
        self.android_status = 200
        self.android_auth: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/v1/servers":
            if self.register_status != 201:
                return httpx2.Response(
                    self.register_status,
                    json={"error": {"message": "RELAY_REGISTRATION_LIMIT"}},
                )
            self.registrations.append(json.loads(request.content))
            n = len(self.registrations)
            return httpx2.Response(
                201, json={"server_id": f"srv_{n}", "server_key": f"key-{n}"}
            )
        if request.url.path == "/v1/android-config":
            self.android_auth.append(request.headers.get("authorization", ""))
            if self.android_status != 200:
                return httpx2.Response(
                    self.android_status, json={"error": {"message": "nope"}}
                )
            return httpx2.Response(
                200,
                json={
                    "project_id": "beyonders-studio-app",
                    "application_id": "1:2:android:3",
                    "api_key": "relay-api-key",
                    "sender_id": "42",
                },
            )
        return httpx2.Response(404)

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def _relay_address(monkeypatch):
    monkeypatch.setattr(push_relay, "PUSH_RELAY_URL", RELAY)
    push_relay.reset_for_tests()
    yield
    push_relay.reset_for_tests()


@pytest.fixture
async def settings_row(session: AsyncSession) -> None:
    """The settings singleton the credentials row hangs off, as boot leaves it."""
    await app_settings_service.seed_app_settings(session)
    await session.commit()


async def _stored(session: AsyncSession) -> tuple[str | None, str | None]:
    session.expire_all()
    row = (
        await session.exec(
            select(
                AppSettingSecret.push_relay_server_id,
                AppSettingSecret.push_relay_key_encrypted,
            )
        )
    ).one_or_none()
    return (row[0], row[1]) if row else (None, None)


async def test_registers_once_and_keeps_the_key_encrypted(
    session: AsyncSession, settings_row, monkeypatch
):
    """The first call registers under the server's host name; the key is kept
    encrypted beside the service account, and a later process loads it
    rather than registering again."""
    monkeypatch.setattr(app_config, "APP_URL", "https://tasks.example.org/app")
    relay = FakeRelay()
    async with relay.client() as client:
        assert await push_relay.credentials(client) == ("srv_1", "key-1")
        assert await push_relay.credentials(client) == ("srv_1", "key-1")

        server_id, encrypted = await _stored(session)
        assert server_id == "srv_1"
        assert encrypted and "key-1" not in encrypted
        assert decrypt_field(encrypted, SALT_PUSH_RELAY_KEY) == "key-1"

        push_relay.reset_for_tests()  # another process, same database
        assert await push_relay.credentials(client) == ("srv_1", "key-1")

    # A name, never the server's address: the relay need not know where it runs.
    assert relay.registrations == [{"name": "Initiative server"}]


async def test_a_registration_that_loses_the_race_takes_the_stored_one(
    session: AsyncSession, settings_row, monkeypatch
):
    """Two replicas registering at once converge on the one stored first."""
    relay = FakeRelay()
    real_register = push_relay._register

    async def _register_while_another_replica_stores(client):
        await push_relay._store("srv_other", "key-other")
        return await real_register(client)

    monkeypatch.setattr(push_relay, "_register", _register_while_another_replica_stores)
    async with relay.client() as client:
        assert await push_relay.credentials(client) == ("srv_other", "key-other")

    assert (await _stored(session))[0] == "srv_other"
    assert len(relay.registrations) == 1


async def test_a_failed_registration_waits_before_trying_again(
    session: AsyncSession, settings_row, monkeypatch
):
    relay = FakeRelay()
    relay.register_status = 429
    attempts = 0
    real_register = push_relay._register

    async def _counted(client):
        nonlocal attempts
        attempts += 1
        return await real_register(client)

    monkeypatch.setattr(push_relay, "_register", _counted)
    async with relay.client() as client:
        assert await push_relay.credentials(client) is None
        assert await push_relay.credentials(client) is None
        assert attempts == 1

        # The wait has passed, and the relay takes it this time.
        monkeypatch.setattr(push_relay, "REGISTRATION_RETRY_SECONDS", 0.0)
        relay.register_status = 201
        assert await push_relay.credentials(client) == ("srv_1", "key-1")
        assert attempts == 2

    assert (await _stored(session))[0] == "srv_1"


async def test_forget_clears_the_credential_so_the_next_call_registers(
    session: AsyncSession, settings_row
):
    relay = FakeRelay()
    async with relay.client() as client:
        assert await push_relay.credentials(client) == ("srv_1", "key-1")
        await push_relay.forget("srv_1")
        assert await _stored(session) == (None, None)
        assert await push_relay.credentials(client) == ("srv_2", "key-2")

    assert (await _stored(session))[0] == "srv_2"


async def test_forgetting_an_old_credential_keeps_a_newer_one(
    session: AsyncSession, settings_row
):
    """A late 401 for a key already replaced does not clear its replacement."""
    relay = FakeRelay()
    async with relay.client() as client:
        assert await push_relay.credentials(client) == ("srv_1", "key-1")
        await push_relay.forget("srv_0")
        assert await push_relay.credentials(client) == ("srv_1", "key-1")
    assert (await _stored(session))[0] == "srv_1"


async def test_a_key_that_no_longer_decrypts_is_replaced(
    session: AsyncSession, settings_row
):
    row = await app_settings_service.get_app_setting_secrets(session)
    row.push_relay_server_id = "srv_stale"
    row.push_relay_key_encrypted = encrypt_field("x", b"another-salt")
    session.add(row)
    await session.commit()

    relay = FakeRelay()
    async with relay.client() as client:
        assert await push_relay.credentials(client) == ("srv_1", "key-1")
    assert (await _stored(session))[0] == "srv_1"


# --- the relay's Android settings ---------------------------------------------


async def test_android_settings_are_fetched_with_the_relay_key_and_kept(
    session: AsyncSession, settings_row
):
    relay = FakeRelay()
    async with relay.client() as client:
        config = await push_relay.android_config(client)
        again = await push_relay.android_config(client)

    assert config == push_relay.AndroidConfig(
        project_id="beyonders-studio-app",
        application_id="1:2:android:3",
        api_key="relay-api-key",
        sender_id="42",
    )
    assert again == config
    assert relay.android_auth == ["Bearer srv_1.key-1"]


async def test_android_settings_the_relay_cannot_give_are_none(
    session: AsyncSession, settings_row
):
    relay = FakeRelay()
    relay.android_status = 404
    async with relay.client() as client:
        assert await push_relay.android_config(client) is None
        # Remembered for a while rather than asked again on every launch.
        assert await push_relay.android_config(client) is None
    assert len(relay.android_auth) == 1


async def test_android_settings_without_a_registration_are_none(
    session: AsyncSession, settings_row
):
    relay = FakeRelay()
    relay.register_status = 503
    async with relay.client() as client:
        assert await push_relay.android_config(client) is None
    assert relay.android_auth == []


async def test_a_refused_key_on_the_android_settings_is_forgotten(
    session: AsyncSession, settings_row
):
    relay = FakeRelay()
    relay.android_status = 401
    async with relay.client() as client:
        assert await push_relay.android_config(client) is None
    assert await _stored(session) == (None, None)
