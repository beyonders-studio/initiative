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
