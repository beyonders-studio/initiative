"""Custom-property serialization for export envelopes.

One flat, by-NAME encoding shared by every envelope that carries properties
(each tool row and each row inside one — the project envelope's values use the
same type→field rules via its own pydantic model), so an import reads them all
with one rule set:

- text/url/select  → ``value_text``
- number, currency, scale → ``value_number``, and a currency's code as
  ``currency``
- checkbox         → ``value_boolean``
- date/datetime    → ``value_text`` (ISO 8601)
- multi_select     → ``value_json``
- user_reference   → ``value_handle``, and ``value_name`` beside it

Reads the ``PropertySummary`` list every row carries once
``properties_service.annotate_properties`` has run — the same values its read
shows.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core import usernames
from app.schemas.tenant.property import PropertySummary, annotated_properties


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def property_export_dict(summary: PropertySummary) -> dict:
    prop_type = (
        summary.type.value if hasattr(summary.type, "value") else str(summary.type)
    )
    value = summary.value
    record: dict = {"property_name": summary.name, "property_type": prop_type}
    if prop_type in ("text", "url", "select"):
        record["value_text"] = value
    elif prop_type in ("number", "currency", "scale"):
        record["value_number"] = float(value) if value is not None else None
    elif prop_type == "checkbox":
        record["value_boolean"] = value
    elif prop_type in ("date", "datetime"):
        record["value_text"] = _iso(value)
    elif prop_type == "multi_select":
        record["value_json"] = value
    elif prop_type == "user_reference":
        known = isinstance(value, dict) and value.get("username")
        record["value_handle"] = (
            usernames.format_handle(value["username"], value["discriminator"])
            if known
            else None
        )
        # What the community calls them, for a reader; the handle is what an
        # import matches on.
        record["value_name"] = (
            (value.get("display_name") or record["value_handle"]) if known else None
        )
    if summary.currency is not None:
        record["currency"] = summary.currency.value
    return record


def exported_properties(row: Any) -> list[dict]:
    """Every value ``row`` carries, in the flat by-name encoding."""
    return [property_export_dict(summary) for summary in annotated_properties(row)]
