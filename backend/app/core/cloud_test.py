import pytest

from app.core import cloud
from app.core.config import settings
from app.core.version import root_file

# Reads the CLOUD_ORIGIN file at the project root, outside backend/.
pytestmark = pytest.mark.always


def test_a_server_is_cloud_when_its_app_url_has_clouds_origin(monkeypatch):
    origin = root_file("CLOUD_ORIGIN").read_text().strip()
    assert origin.startswith("https://")

    for app_url in (
        origin,
        f"{origin}/",
        f"{origin.upper()}/welcome",
        f"{origin}:443",
    ):
        monkeypatch.setattr(settings, "APP_URL", app_url)
        assert cloud.is_cloud(), app_url

    for app_url in (
        "http://localhost:5173",
        origin.replace("https://", "https://demo."),
        origin.replace("https://", "http://"),
    ):
        monkeypatch.setattr(settings, "APP_URL", app_url)
        assert not cloud.is_cloud(), app_url


def test_a_dev_server_on_this_machine_is_cloud_only_with_dev_as_cloud(monkeypatch):
    origin = root_file("CLOUD_ORIGIN").read_text().strip()
    monkeypatch.setattr(settings, "DEV_AS_CLOUD", True)

    for app_url in (
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://[::1]:5173",
    ):
        monkeypatch.setattr(settings, "APP_URL", app_url)
        assert cloud.is_cloud(), app_url

    for app_url in (
        "https://initiative.example.com",
        "http://192.168.1.20:8173",
        origin.replace("https://", "https://demo."),
    ):
        monkeypatch.setattr(settings, "APP_URL", app_url)
        assert not cloud.is_cloud(), app_url

    monkeypatch.setattr(settings, "DEV_AS_CLOUD", False)
    monkeypatch.setattr(settings, "APP_URL", "http://localhost:5173")
    assert not cloud.is_cloud()
