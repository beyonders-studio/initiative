"""The importable JSON every tool exports, written one way for all of them.

A tool's envelope is the model its importer reads
(``schemas.tenant.import_envelopes.tool_envelope``), so the export writes it by
reading that same model field by field, off the tool's row:

* ``type`` and ``schema_version`` are the tool's;
* ``tags`` are the row's tag names, sorted, and ``properties`` its fields'
  values (``property_values.exported_properties``);
* ``external_ref`` is the row's ``<kind>:<id>``, what a reference to it is
  pointed at across one import;
* a column of the row's table is its value, as JSON holds it;
* a list of envelopes the row holds as a relationship is its child rows, each
  written the same way.

Whatever else a model declares is either the tool's to say (``fields``: a
value its row does not hold as it is, such as a wiki page's parent by slug) or
is not carried (the mention handles, which the export fills in afterwards).
The envelope is machine data: never localized, since translating a key or a
value would break the import.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from types import NoneType
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from sqlalchemy import inspect

from app.core.tools import KIND_BY_TABLE, Tool, tool_envelope_type
from app.schemas.tenant.import_envelopes import (
    CURRENT_SCHEMA_VERSION,
    _EnvelopeBase,
    tool_envelope,
)
from app.schemas.tenant.tag import annotated_tags
from app.services.export import values
from app.services.export.property_values import exported_properties


def envelope(tool: Tool, row: Any, /, **fields: Any) -> dict[str, Any]:
    """``row`` as the envelope ``tool`` exports, with ``fields`` for what the
    row does not hold as it is."""
    return {
        "type": tool_envelope_type(tool),
        "schema_version": CURRENT_SCHEMA_VERSION,
        **record(tool_envelope(tool), row, **fields),
    }


def record(model: type[BaseModel], row: Any, /, **fields: Any) -> dict[str, Any]:
    """``row`` written as ``model`` reads it, in the model's field order:
    ``fields`` first, then what the row holds (see the module docstring)."""
    unknown = fields.keys() - model.model_fields.keys()
    if unknown:
        raise ValueError(f"{model.__name__} has no fields {sorted(unknown)}")
    columns = {column.key for column in row.__table__.columns}
    relationships = inspect(type(row)).relationships
    written: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        if name in _EnvelopeBase.model_fields:
            continue
        if name in fields:
            written[name] = fields[name]
        elif name == "tags":
            written[name] = sorted(tag.name for tag in annotated_tags(row))
        elif name == "properties":
            written[name] = exported_properties(row)
        elif name == "external_ref":
            written[name] = f"{KIND_BY_TABLE[row.__tablename__].value}:{row.id}"
        elif name in columns:
            value = getattr(row, name)
            if value is None and NoneType not in get_args(info.annotation):
                # The model's default stands in for a value the row has none of.
                value = deepcopy(info.default)
            written[name] = _json(value)
        elif name in relationships and (child := _child_model(info.annotation)):
            written[name] = [record(child, each) for each in getattr(row, name)]
    return written


def _child_model(annotation: Any) -> type[BaseModel] | None:
    """The model of a list of envelopes, or ``None`` for any other field."""
    if get_origin(annotation) is not list:
        return None
    (item,) = get_args(annotation)
    return item if isinstance(item, type) and issubclass(item, BaseModel) else None


def _json(value: Any) -> Any:
    """A column's value as JSON holds it: an enum by its value, a number as a
    spreadsheet keeps it (``values.number``), a moment in ISO form, and a
    container as a copy."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Decimal, float)):
        return values.number(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value
