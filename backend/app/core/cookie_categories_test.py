"""What the cookie chooser is allowed to ask about on a given deployment."""

from __future__ import annotations

from app.core.config import settings
from app.core.cookie_categories import (
    CATEGORY_IN_USE,
    CookieCategory,
    active_cookie_categories,
)


def test_the_vocabulary_is_what_the_frontend_has_labels_for():
    """Mirrored by `frontend/src/lib/consent.test.ts`, which checks the same
    values have a name and a description in every locale. A category the
    chooser cannot label is one it cannot honestly ask about."""
    assert [c.value for c in CookieCategory] == ["analytics", "marketing"]


def test_a_deployment_using_none_of_them_is_asked_about_none(monkeypatch):
    """The default: nothing optional ships configured, so there is nothing to
    put a switch beside."""
    monkeypatch.setattr(settings, "FARO_COLLECTOR_URL", None)

    assert active_cookie_categories(settings) == []


def test_a_named_collector_is_asked_about_as_analytics(monkeypatch):
    monkeypatch.setattr(settings, "FARO_COLLECTOR_URL", "/collect")

    assert active_cookie_categories(settings) == [CookieCategory.analytics]


def test_a_category_with_nothing_behind_it_is_never_offered(monkeypatch):
    """Naming a category is not the same as using one. Until something says
    this deployment uses it, it is not asked about."""
    monkeypatch.setitem(CATEGORY_IN_USE, CookieCategory.analytics, lambda _: False)

    assert active_cookie_categories(settings) == []


def test_a_configured_category_is_offered(monkeypatch):
    monkeypatch.setitem(CATEGORY_IN_USE, CookieCategory.analytics, lambda _: True)

    assert active_cookie_categories(settings) == [CookieCategory.analytics]


def test_the_offer_is_read_from_configuration_each_time(monkeypatch):
    """An operator turning something off stops it being asked about, without a
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
