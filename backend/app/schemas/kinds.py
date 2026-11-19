"""A kind a universal route takes: one of its built-in kinds, or a tool
plug-in's.

The universal routes (archive, trash, comments, tags, links, sharing, search,
export) each take a kind, declared as an enum of the built-in kinds. A tool
plug-in's kind (``<key>.<uid>``, ``app.db.plugin_tools``) is taken there too,
in the form it has; whether the community has that tool is the route's to
ask, of the community's tool set, and a kind it does not have is not found.

Both ways the kind is published as the enum until the plug-in API's kinds
widen (the tool plug-ins design, step 6): only a community with a tool
plug-in installed sends or is sent one of its kinds, and no client draws one
yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import core_schema

from app.db.plugin_tools import is_plugin_kind


@dataclass(frozen=True)
class WithInstalled:
    """``Annotated[str, WithInstalled(enum)]`` takes ``enum``'s values and a
    tool plug-in's kind, as a ``str``."""

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

    def __get_pydantic_json_schema__(
        self, schema: core_schema.CoreSchema, handler: GetJsonSchemaHandler
    ) -> JsonSchemaValue:
        # An answer is serialized as the enum or a string; it is published
        # as the enum, as a request is.
        found = handler(schema)
        return found["anyOf"][0] if "anyOf" in found else found
