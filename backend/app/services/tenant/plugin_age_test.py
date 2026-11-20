"""The age decision's edges; the handoff tests in ``guild_plugins_platform_test``
hold who opens an age-limited plug-in where."""

import pytest
from starlette.requests import Request

from app.core.config import settings
from app.services.tenant.plugin_age import (
    AgeViewer,
    age_allows,
    minimum_for,
    request_country,
)

pytestmark = pytest.mark.always

AUTO = {"minimum_age": {"default": 16, "US": 13}}


def _request(headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


def test_an_unknown_country_takes_the_highest_declared_age():
    # Not knowing where somebody is must never let them in younger.
    assert minimum_for(AUTO, None) == 16
    assert minimum_for({"minimum_age": {"US": 13, "KR": 14}}, None) == 14
    assert age_allows(AUTO, AgeViewer(age=16, country=None)) is True


def test_a_country_with_no_entry_and_no_default_has_no_limit():
    assert minimum_for({"minimum_age": {"US": 13}}, "FR") is None


def test_the_country_comes_from_the_configured_header_only(monkeypatch):
    monkeypatch.setattr(settings, "CLIENT_COUNTRY_HEADER", None)
    assert request_country(_request({"CF-IPCountry": "US"})) is None

    monkeypatch.setattr(settings, "CLIENT_COUNTRY_HEADER", "CF-IPCountry")
    assert request_country(_request({"CF-IPCountry": "us"})) == "US"
    assert request_country(_request({})) is None


@pytest.mark.parametrize("value", ["XX", "T1", "USA", "1", ""])
def test_a_header_value_naming_no_country_is_unknown(monkeypatch, value):
    monkeypatch.setattr(settings, "CLIENT_COUNTRY_HEADER", "CF-IPCountry")
    assert request_country(_request({"CF-IPCountry": value})) is None
