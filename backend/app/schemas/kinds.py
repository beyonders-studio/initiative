"""A kind a universal route takes: one of its built-in kinds, or a tool
plug-in's.

The universal routes (archive, trash, comments, tags, links, sharing, search,
export) each take a kind, declared as an enum of the built-in kinds. A tool
plug-in's kind (``<key>.<uid>``, ``app.db.plugin_tools``) is taken there too,
in the form it has; whether the community has that tool is the route's to
ask, of the community's tool set, and a kind it does not have is not found.

What a client sends is published as the enum until the plug-in API's kinds
widen. What it is sent may name a tool plug-in's kind, so an answer
publishes the enum or a string.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any

from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

from app.db.plugin_tools import is_plugin_kind


@dataclass(frozen=True)
class _Kinds:
    """Takes ``enum``'s values and a tool plug-in's kind, as a ``str``."""

    enum: type[Enum]

    def check(self, value: Any) -> str:
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, str) and (
            value in self.enum._value2member_map_ or is_plugin_kind(value)
        ):
            return value
        raise ValueError(f"not a kind: {value!r}")

    def __get_pydantic_core_schema__(
        self, _source: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        published = handler.generate_schema(self.enum)
        return core_schema.no_info_plain_validator_function(
            self.check,
            json_schema_input_schema=published,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str,
                return_schema=core_schema.union_schema(
                    [published, core_schema.str_schema()]
                ),
            ),
        )


def with_installed(enum: type[Enum]) -> Any:
    """``enum``'s values, and a tool plug-in's kind, as a ``str``."""
    return Annotated[str, _Kinds(enum)]
