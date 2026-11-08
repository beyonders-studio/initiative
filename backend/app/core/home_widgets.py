"""What a home page can hold: the widgets a home layout may place.

A home page is the reader's own, and its layout lives in their preferences,
which the server never reads. This registry exists for the one place the server
*does* handle a layout: a marketplace listing of one, which has to be checked
before anybody can add it to their home.

It mirrors ``frontend/src/lib/home/widgetTypes.ts``, the client's list, and
``home_widgets_test`` holds the two together. Each widget states its smallest
size, whether a page may hold more than one, and which of its options a
published layout may carry. An option that only means something on one
person's page — a community, a list, a note — is never published: it would
point at nothing on anybody else's.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import available_timezones

from app.core.tools import Tool

#: Columns on the home grid, as on a dashboard's.
HOME_GRID_COLUMNS = 12
#: The tallest a widget may be, in rows.
HOME_MAX_ROWS = 40
#: More than anyone arranges on one page.
MAX_HOME_WIDGETS = 24


class HomeOptionError(ValueError):
    """An option a published layout may not carry, or a value it may not take."""


def _one_of(*allowed: Any) -> Callable[[Any], Any]:
    def check(value: Any) -> Any:
        if value not in allowed:
            raise HomeOptionError(f"must be one of {list(allowed)}")
        return value

    return check


def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise HomeOptionError("must be true or false")
    return value


_TOOLS = {tool.value for tool in Tool}


def _tools(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise HomeOptionError("must be a non-empty list of tools")
    if not all(isinstance(each, str) for each in value):
        raise HomeOptionError("must name each tool as text")
    unknown = [each for each in value if each not in _TOOLS]
    if unknown:
        raise HomeOptionError(f"names no tool: {unknown}")
    # In registry order, once each, as the client keeps it.
    return [tool.value for tool in Tool if tool.value in value]


#: At most this many other time zones on a clock.
MAX_CLOCK_ZONES = 3


def _zones(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_CLOCK_ZONES:
        raise HomeOptionError(f"must be a list of at most {MAX_CLOCK_ZONES} time zones")
    if not all(isinstance(each, str) for each in value):
        raise HomeOptionError("must name each time zone as text")
    known = available_timezones() | {"UTC"}
    unknown = [each for each in value if each not in known]
    if unknown:
        raise HomeOptionError(f"names no time zone: {unknown}")
    zones: list[str] = list(dict.fromkeys(str(zone) for zone in value))
    return zones


#: The longest a timer may run, in seconds: a day.
MAX_TIMER_SECONDS = 24 * 60 * 60


def _timer(value: Any) -> dict[str, int]:
    # Only how long it is: when a published timer started is nobody's business.
    if not isinstance(value, dict) or set(value) - {"duration"}:
        raise HomeOptionError("may only say its duration")
    duration = value.get("duration")
    if not isinstance(duration, int) or isinstance(duration, bool):
        raise HomeOptionError("duration must be a whole number of seconds")
    if not 60 <= duration <= MAX_TIMER_SECONDS:
        raise HomeOptionError(
            f"duration must be between 60 and {MAX_TIMER_SECONDS} seconds"
        )
    return {"duration": duration}


@dataclass(frozen=True)
class HomeWidgetSpec:
    min_w: int
    min_h: int
    #: At most one on a page: it keeps its state in one place of the reader's own.
    single: bool = False
    #: The options a published layout may carry, each with its check.
    options: dict[str, Callable[[Any], Any]] = field(default_factory=dict)


HOME_WIDGET_SPECS: dict[str, HomeWidgetSpec] = {
    "greeting": HomeWidgetSpec(4, 2, single=True, options={"yonder": _boolean}),
    "gettingStarted": HomeWidgetSpec(4, 4, single=True),
    "focus": HomeWidgetSpec(4, 3, single=True),
    "tasks": HomeWidgetSpec(5, 5),
    "comingUp": HomeWidgetSpec(3, 4, options={"days": _one_of(3, 7, 14, 30)}),
    "calendar": HomeWidgetSpec(5, 7, single=True),
    "recent": HomeWidgetSpec(
        3, 3, options={"mode": _one_of("viewed", "changed"), "tools": _tools}
    ),
    "bookmarks": HomeWidgetSpec(3, 3, options={"tools": _tools}),
    "activity": HomeWidgetSpec(3, 4, options={"view": _one_of("all", "yours")}),
    "communities": HomeWidgetSpec(4, 5, single=True),
    "progress": HomeWidgetSpec(4, 2, single=True),
    "clock": HomeWidgetSpec(
        2,
        3,
        options={
            "mode": _one_of("clock", "timer"),
            "zones": _zones,
            "timer": _timer,
            "muted": _boolean,
        },
    ),
}
