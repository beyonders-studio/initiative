"""A kind a universal route takes: one of its built-in kinds, or a tool
plug-in's.

The universal routes (archive, trash, comments, tags, links, sharing, search,
export) each take a kind as a parameter, declared as an enum of the built-in
kinds. A tool plug-in's kind (``<key>.<uid>``, ``app.db.plugin_tools``) is
taken there too, in the form it has; whether the community has that tool is
the route's to ask, of the community's tool set, and a kind it does not have
is not found. Until the plug-in API's kinds widen, the published schema stays
the enum.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any

from pydantic import PlainSerializer, PlainValidator

from app.db.plugin_tools import is_plugin_kind


def with_installed(enum: type[Enum]) -> Any:
    """``enum``'s values, and a tool plug-in's kind, as a ``str``."""
    members = frozenset(str(member.value) for member in enum)  # type: ignore[attr-defined]

    def check(value: Any) -> str:
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, str) and (value in members or is_plugin_kind(value)):
            return value
        raise ValueError(f"not a kind: {value!r}")

    return Annotated[
        str,
        PlainValidator(check, json_schema_input_type=enum),
        PlainSerializer(str, return_type=enum),
    ]
