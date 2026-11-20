"""What a home-layout listing may publish."""

import copy

import pytest

from app.services.marketplace.definitions import normalize_listing_definition
from app.services.marketplace.home_layouts import normalize_home_layout_definition
from app.services.marketplace.manifest_values import ListingDefinitionError


def _layout(*widgets):
    return {"schema_version": 1, "kind": "home_layout", "widgets": list(widgets)}


def _widget(widget_id, widget_type, x=0, y=0, w=4, h=6, options=None):
    widget = {
        "id": widget_id,
        "type": widget_type,
        "grid": {"x": x, "y": y, "w": w, "h": h},
    }
    if options is not None:
        widget["options"] = options
    return widget


GOOD = _layout(
    _widget("greeting", "greeting", w=12, h=2, options={"yonder": False}),
    _widget(
        "clock", "clock", y=2, options={"mode": "timer", "timer": {"duration": 1500}}
    ),
    _widget(
        "recent",
        "recent",
        x=4,
        y=2,
        options={"tools": ["post", "project"], "mode": "changed"},
    ),
)


def test_a_good_layout_comes_back_canonical():
    out = normalize_home_layout_definition(copy.deepcopy(GOOD))
    # The tools a recent widget lists are kept in the registry's order.
    assert out["widgets"][2]["options"] == {
        "mode": "changed",
        "tools": ["project", "post"],
    }
    assert normalize_home_layout_definition(out) == out


def test_the_listing_kind_is_checked_by_this_validator():
    assert (
        normalize_listing_definition("home_layout", copy.deepcopy(GOOD))["kind"]
        == "home_layout"
    )


@pytest.mark.parametrize(
    "widgets, why",
    [
        ([_widget("a", "weather")], "not a home widget"),
        # Options that would point at one person's own things.
        (
            [_widget("a", "activity", options={"communityId": 4})],
            "carries no communityId",
        ),
        (
            [_widget("a", "tasks", w=12, h=10, options={"addTo": {"projectId": 9}})],
            "carries no addTo",
        ),
        (
            [_widget("a", "clock", options={"timer": {"duration": 600, "endsAt": 1}})],
            "only say its duration",
        ),
        ([_widget("a", "comingUp", options={"days": 5})], "must be one of"),
        ([_widget("a", "recent", options={"tools": ["spreadsheet"]})], "names no tool"),
        (
            [_widget("a", "clock", options={"zones": ["Mars/Olympus"]})],
            "names no time zone",
        ),
        # Not text at all: refused with a reason, not a server error.
        ([_widget("a", "recent", options={"tools": [{}]})], "each tool as text"),
        ([_widget("a", "clock", options={"zones": [[]]})], "each time zone as text"),
        ([_widget("a", "greeting", w=2, h=2)], "grid.w must be between"),
        ([_widget("a", "clock", x=10, w=4)], "grid.x must be between"),
        ([_widget("a b", "clock")], "short name"),
        ([_widget("a", "focus"), _widget("b", "focus", y=6)], "holds one focus"),
        ([_widget("a", "clock"), _widget("b", "clock", x=2, y=3)], "same cells"),
        ([], "at least one widget"),
    ],
)
def test_what_a_layout_may_not_carry_is_refused(widgets, why):
    with pytest.raises(ListingDefinitionError, match=why):
        normalize_home_layout_definition(_layout(*widgets))
