"""Tests for the resolved storage-config cache.

Covers the env fallback before the DB is loaded (DB values overriding env after
a save are held by the Storage settings endpoint's own tests), the S3 client's
checksum settings, and the connection test.
"""

from __future__ import annotations

import pytest

from app.core.config import settings as app_config
from app.core.messages import SettingsMessages
from app.services import storage_config


@pytest.fixture(autouse=True)
def _reset_cache():
    storage_config.reset_for_tests()
    yield
    storage_config.reset_for_tests()


def test_current_config_falls_back_to_env_before_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no snapshot loaded, the resolver reads env settings — identical to the
    original env-only behavior (so CLI/scripts and boot-before-refresh work)."""
    monkeypatch.setattr(app_config, "STORAGE_BACKEND", "local", raising=False)
    monkeypatch.setattr(app_config, "S3_BUCKET", "env-bucket", raising=False)

    cfg = storage_config.current_storage_config()
    assert cfg.backend == "local"
    assert cfg.bucket == "env-bucket"


async def test_test_connection_local_is_noop() -> None:
    """A local backend has no remote to reach, so the connection test passes."""
    cfg = storage_config.ResolvedStorageConfig(
        backend="local",
        bucket=None,
        region="us-east-1",
        endpoint_url=None,
        access_key_id=None,
        secret_access_key=None,
        use_path_style=False,
        local_fallback=False,
    )
    ok, _message = await storage_config.test_connection(cfg)
    assert ok is True


def test_build_s3_client_disables_flexible_checksums() -> None:
    """Regression: botocore >=1.36's default flexible checksums break many
    S3-compatible stores (signature/AccessDenied, classically on GetObject). The
    client must pin both checksum knobs to "when_required" for interop."""
    from app.services.storage import build_s3_client

    cfg = storage_config.ResolvedStorageConfig(
        backend="s3",
        bucket="b",
        region="garage",
        endpoint_url="http://localhost:3900",
        access_key_id="GK",
        secret_access_key="x",
        use_path_style=True,
        local_fallback=False,
    )
    client = build_s3_client(cfg)
    assert client.meta.config.request_checksum_calculation == "when_required"
    assert client.meta.config.response_checksum_validation == "when_required"


async def test_test_connection_s3_requires_bucket() -> None:
    cfg = storage_config.ResolvedStorageConfig(
        backend="s3",
        bucket=None,
        region="us-east-1",
        endpoint_url=None,
        access_key_id=None,
        secret_access_key=None,
        use_path_style=False,
        local_fallback=False,
    )
    ok, message = await storage_config.test_connection(cfg)
    assert ok is False
    assert message == SettingsMessages.STORAGE_BUCKET_REQUIRED
