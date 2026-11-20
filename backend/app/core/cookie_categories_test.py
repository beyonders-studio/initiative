"""What the cookie chooser is allowed to ask about on a given deployment."""

from __future__ import annotations

from app.core.config import settings
from app.core.cookie_categories import (
    CATEGORY_IN_USE,
    CookieCategory,
    active_cookie_categories,
)


def test_a_deployment_using_none_of_them_is_asked_about_none(monkeypatch):
    """The default: nothing optional ships configured, so there is nothing to
    put a switch beside."""
    monkeypatch.setattr(settings, "FARO_COLLECTOR_URL", None)

    assert active_cookie_categories(settings) == []


def test_a_named_collector_is_asked_about_as_analytics(monkeypatch):
    monkeypatch.setattr(settings, "FARO_COLLECTOR_URL", "/collect")

    assert active_cookie_categories(settings) == [CookieCategory.analytics]


def test_the_offer_is_read_from_configuration_each_time(monkeypatch):
    """A category is offered only while something uses it, read without a
    restart and without anybody's stored answer being involved."""
    in_use = {"on": True}
    monkeypatch.setitem(
        CATEGORY_IN_USE, CookieCategory.marketing, lambda _: in_use["on"]
    )

    assert active_cookie_categories(settings) == [CookieCategory.marketing]

    in_use["on"] = False
    assert active_cookie_categories(settings) == []


def test_categories_are_offered_in_one_order(monkeypatch):
    """So the chooser does not shuffle its switches between page loads."""
    for category in CookieCategory:
        monkeypatch.setitem(CATEGORY_IN_USE, category, lambda _: True)

    assert active_cookie_categories(settings) == list(CookieCategory)
