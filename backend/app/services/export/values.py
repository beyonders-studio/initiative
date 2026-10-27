"""A list's values as table cells, written by the kind of value they are.

Every table export (tasks, a project's report, a queue, a counter group)
draws ``columns`` and fills each cell from its row: one :class:`Column` per
field, named for the field as the field registry names it (``fields.<name>``
in the exports catalogue). What a cell holds is decided by the kind of value,
once, here: a date as a date, a person by name, an option by its label. So the
same field reads the same in every export.

Cells are text, except numbers, which stay numbers so a spreadsheet keeps them
typed.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date as Date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.core.user_display import display_name
from app.core.user_input_validators import resolve_zone
from app.models.tenant.property import PropertyType
from app.services.export.i18n import et


@dataclass(frozen=True)
class Column:
    """One column of a table export: its key in a row, its header, how wide
    the PDF draws it, and what fills its cell from a row."""

    key: str
    label: str
    cell: Callable[[Any], Any]
    width: str = "1fr"


def head(columns: Sequence[Column]) -> list[dict[str, str]]:
    """The ``columns`` a template draws."""
    return [{"key": c.key, "label": c.label, "width": c.width} for c in columns]


def cells(columns: Sequence[Column], row: Any) -> dict[str, Any]:
    """One row's cells, by column key; a value there is none of empty."""
    return {
        column.key: "" if (value := column.cell(row)) is None else value
        for column in columns
    }


def label(field: str, locale: str) -> str:
    """A field's header, by the name the field registry gives it."""
    return et(f"fields.{field}", locale)


def text(value: Any) -> str:
    return "" if value is None else str(value)


def number(value: Any) -> int | float | None:
    """A number as a spreadsheet keeps it: integral values as ints, the rest
    as floats. ``NUMERIC`` arrives as ``Decimal``, which neither JSON nor a
    sheet takes, and reads badly as text (``5.0000000000``)."""
    if value is None or isinstance(value, bool):
        return None
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    if decimal == decimal.to_integral_value():
        return int(decimal)
    return float(decimal)


def date(value: Any) -> str:
    """A date, or the day a moment falls on, as ``YYYY-MM-DD``."""
    if isinstance(value, (datetime, Date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str) and value:
        return value[:10]
    return ""


def yes_no(value: Any, locale: str) -> str:
    return et("values.yes" if value else "values.no", locale)


def moment(value: Any, tz: str | None) -> str:
    """A moment in the reader's zone, named: ``YYYY-MM-DD HH:MM`` and the zone."""
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return str(value)
    if not isinstance(value, datetime):
        return ""
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(resolve_zone(tz)).strftime("%Y-%m-%d %H:%M %Z")


def property_value(summary: Any, locale: str, tz: str | None) -> Any:
    """A custom property's value as its type shows it: an option by its
    label, a person by name, a checkbox as yes or no, a moment with its
    time."""
    if summary is None or summary.value is None:
        return None
    value = summary.value
    labels = {o.value: o.label for o in summary.options or ()}
    kind = summary.type
    if kind is PropertyType.select:
        return labels.get(value, value)
    if kind is PropertyType.multi_select:
        return ", ".join(labels.get(each, each) for each in value)
    if kind is PropertyType.user_reference:
        if not isinstance(value, dict):
            return None
        return display_name(
            SimpleNamespace(
                username=value.get("username") or "",
                discriminator=value.get("discriminator") or 0,
                display_name=value.get("display_name"),
            )
        )
    if kind is PropertyType.checkbox:
        return yes_no(value, locale)
    if kind is PropertyType.date:
        return date(value)
    if kind is PropertyType.datetime:
        return moment(value, tz)
    if kind in (PropertyType.number, PropertyType.currency, PropertyType.rating):
        # An amount stays a number a sheet can add up; its currency is the
        # property's.
        return number(value)
    return text(value)


#: The plug-in field kinds whose value is one scalar, which a value kept
#: beside a state, and a list's element, hold in ``value``.
_SCALAR_KINDS = frozenset({"text", "number", "date", "datetime", "checkbox"})


def plugin_value(value: Any, kind: str, locale: str, tz: str | None) -> Any:
    """A plug-in field's value as the page draws it, by its kind: a badge by
    its text, a link by its title, progress out of its most, a list's
    elements one after another. A value of another shape draws nothing, as on
    the page."""
    if isinstance(value, list):
        return ", ".join(
            str(cell)
            for cell in (plugin_value(v, kind, locale, tz) for v in value)
            if cell not in (None, "")
        )
    if kind in _SCALAR_KINDS and isinstance(value, dict):
        value = value.get("value")
    if kind in ("badge", "link", "progress"):
        if not isinstance(value, dict):
            return None
        if kind == "badge":
            return value.get("text") if isinstance(value.get("text"), str) else None
        if kind == "link":
            url = value.get("url")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                return None
            title = value.get("title")
            return title if isinstance(title, str) and title else url
        done, most = value.get("value"), value.get("max")
        if not (_is_number(done) and _is_number(most) and most > 0):
            return None
        return f"{number(done)}/{number(most)}"
    if kind == "checkbox":
        return yes_no(value, locale) if isinstance(value, bool) else None
    if kind == "number":
        return number(value) if _is_number(value) else None
    if not isinstance(value, str) or not value:
        return None
    if kind == "date":
        return date(value)
    if kind == "datetime":
        return moment(value, tz)
    return value


def _is_number(value: Any) -> bool:
    """A finite number, as a plug-in's number reads one; ``True`` is not."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )
