"""Tests for the resolved push-config cache.

The stored row wins over env once saved, plus the one thing specific to this
credential: the service-account JSON is big enough that the column it is stored
in had to be sized for it, so a round trip is asserted on a realistic document
rather than on a short string.
"""

from __future__ import annotations

import json

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.services.platform import app_settings as app_settings_service
from app.services.platform import push_config


def _service_account(project: str = "demo-project") -> str:
    """A service account the shape Google issues, padded to a realistic size.

    The private key is what makes the document over 2 kB, and the size is the
    point: Fernet takes it past the 2000 characters every other credential
    column is sized for.
    """
    return json.dumps(
        {
            "type": "service_account",
            "project_id": project,
            "private_key_id": "0" * 40,
            "private_key": "-----BEGIN PRIVATE KEY-----\n"
            + "\n".join(["A" * 64] * 32)
            + "\n-----END PRIVATE KEY-----\n",
            "client_email": f"push@{project}.iam.gserviceaccount.com",
            "client_id": "1" * 21,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


@pytest.fixture(autouse=True)
def _reset_cache():
    push_config.reset_for_tests()
    yield
    push_config.reset_for_tests()


async def test_refresh_loads_db_over_env(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After a save the snapshot is the stored row, env ignored."""
    monkeypatch.setattr(app_config, "FCM_ENABLED", False, raising=False)
    monkeypatch.setattr(app_config, "FCM_PROJECT_ID", "env-project", raising=False)

    await app_settings_service.update_push_settings(
        session,
        system_session=session,
        enabled=True,
        project_id="db-project",
        application_id="1:2:android:3",
        api_key="db-api-key",
        sender_id="123456",
        service_account_json=_service_account("db-project"),
        secret_provided=True,
    )

    cfg = await push_config.ensure_push_config_fresh()
    assert cfg.enabled is True
    assert cfg.project_id == "db-project"
    assert cfg.api_key == "db-api-key"
    assert cfg.sender_id == "123456"


async def test_credential_is_kept_when_not_sent(session: AsyncSession) -> None:
    """Toggling the switch without re-pasting the JSON keeps the JSON, and a
    realistic service account comes back byte-identical, and parses.

    Stored truncated it would encrypt and save without complaint and then fail at
    ``json.loads`` on the next push — a long way from the settings page that
    accepted it. That is why the column is 8000 and not 2000.
    """
    account = _service_account()
    assert len(account) > 2000, "the fixture must exercise the wide column"
    await app_settings_service.update_push_settings(
        session,
        system_session=session,
        enabled=True,
        project_id="p",
        application_id=None,
        api_key=None,
        sender_id=None,
        service_account_json=account,
        secret_provided=True,
    )
    await app_settings_service.update_push_settings(
        session,
        system_session=session,
        enabled=False,
        project_id="p",
        application_id=None,
        api_key=None,
        sender_id=None,
        service_account_json=None,
        secret_provided=False,
    )

    cfg = await push_config.ensure_push_config_fresh()
    assert cfg.enabled is False
    assert cfg.service_account_json == account
    assert json.loads(cfg.service_account_json or "{}")["project_id"] == "demo-project"
