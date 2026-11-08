"""Whether the plug-in API this build serves still serves a published one.

A plug-in's client is generated from the plug-in API document the SDK publishes
at its version (the contract version), never from an Initiative release. So
whatever that document names, this build must still serve, the same way:

- every path and method;
- every parameter, by name and location, with a type that still takes what a
  client sends, and no parameter the client does not know of now required;
- every request body media type, its schema still taking what a client sends,
  with no property the client does not know of now required;
- every response the published document lists, by status and media type, each
  property it names still there, still always there if it was, and of a type
  the client still reads.

Additions are fine: a new operation, field or optional parameter is a minor
version of the contract. Removing or changing anything is not.

Schemas are compared through ``$ref`` on each side (each against its own
document's components), so a component that was renamed or inlined compares by
what it holds. Types compare in the direction data flows: what the server
sends must be something the client reads (the served type a subset of the
published one), and what the client sends must be something the server takes
(the published type a subset of the served one). An ``integer`` is a
``number``, and a schema with no type is any.

:func:`missing_from` names each difference, so a failure says what moved.
"""

from __future__ import annotations

from typing import Any, Literal

__all__ = ["missing_from"]

#: Which way data flows through a schema: to the client, or to the server.
Direction = Literal["response", "request"]

_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_SCHEMA_REF = "#/components/"
_ALL_TYPES = frozenset(
    {"string", "number", "integer", "boolean", "array", "object", "null"}
)


class _Side:
    """One document, for resolving its references."""

    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document

    def resolve(self, node: Any) -> tuple[Any, str | None]:
        """``node`` with its ``$ref`` followed, and the last reference taken."""
        ref: str | None = None
        seen: set[str] = set()
        while isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith(_SCHEMA_REF):
                raise ValueError(f"unexpected reference {ref!r}")
            if ref in seen:
                raise ValueError(f"reference cycle at {ref}")
            seen.add(ref)
            target: Any = self.document
            for part in ref.removeprefix("#/").split("/"):
                target = target.get(part) if isinstance(target, dict) else None
            if target is None:
                raise ValueError(f"unresolved reference {ref}")
            node = target
        return node, ref

    def flatten(self, schema: Any) -> tuple[dict[str, Any], str | None]:
        """``schema`` resolved, with an ``allOf`` merged into one object."""
        resolved, ref = self.resolve(schema)
        if not isinstance(resolved, dict):
            return {}, ref
        if "allOf" not in resolved:
            return resolved, ref
        merged: dict[str, Any] = {
            key: value for key, value in resolved.items() if key != "allOf"
        }
        properties = dict(merged.get("properties", {}))
        required = list(merged.get("required", []))
        types: frozenset[str] | None = self.types(merged) if "type" in merged else None
        for part in resolved["allOf"]:
            flat, _ = self.flatten(part)
            properties.update(flat.get("properties", {}))
            required += flat.get("required", [])
            part_types = self.types(flat)
            if part_types is not None:
                types = part_types if types is None else types & part_types
            for key, value in flat.items():
                if key not in ("properties", "required", "type", "anyOf", "oneOf"):
                    merged.setdefault(key, value)
            for key in ("anyOf", "oneOf", "items"):
                if key in flat:
                    merged.setdefault(key, flat[key])
        if properties:
            merged["properties"] = properties
        if required:
            merged["required"] = sorted(set(required))
        if types is not None:
            merged["type"] = sorted(types)
        return merged, ref

    def types(self, schema: Any) -> frozenset[str] | None:
        """The JSON types ``schema`` allows, or ``None`` for any."""
        flat, _ = self.flatten(schema) if isinstance(schema, dict) else ({}, None)
        variants = flat.get("anyOf", flat.get("oneOf"))
        if variants is not None:
            union: set[str] = set()
            for variant in variants:
                variant_types = self.types(variant)
                if variant_types is None:
                    return None
                union |= variant_types
            return frozenset(union)
        declared = flat.get("type")
        if declared is None:
            if "const" in flat:
                return _value_types([flat["const"]])
            if "enum" in flat:
                return _value_types(flat["enum"])
            if "properties" in flat:
                return frozenset({"object"})
            if "items" in flat:
                return frozenset({"array"})
            return None
        found = {declared} if isinstance(declared, str) else set(declared)
        if flat.get("nullable"):
            found.add("null")
        return frozenset(found & _ALL_TYPES)


def _value_types(values: list[Any]) -> frozenset[str]:
    found: set[str] = set()
    for value in values:
        if value is None:
            found.add("null")
        elif isinstance(value, bool):
            found.add("boolean")
        elif isinstance(value, int):
            found.add("integer")
        elif isinstance(value, float):
            found.add("number")
        elif isinstance(value, str):
            found.add("string")
        elif isinstance(value, list):
            found.add("array")
        else:
            found.add("object")
    return frozenset(found)


def _within(inner: frozenset[str] | None, outer: frozenset[str] | None) -> bool:
    """Whether every value of the types ``inner`` is one of ``outer``."""
    if outer is None:
        return True
    if inner is None:
        return False
    widened = set(outer) | ({"integer"} if "number" in outer else set())
    return inner <= widened


def _describe(types: frozenset[str] | None) -> str:
    return "any" if types is None else "|".join(sorted(types)) or "nothing"


def _is_union(schema: dict[str, Any]) -> bool:
    return "anyOf" in schema or "oneOf" in schema


def _members(schema: dict[str, Any], side: _Side) -> list[Any]:
    """A union's members other than ``null``; anything else is its one member."""
    if not _is_union(schema):
        return [schema]
    variants = schema.get("anyOf", schema.get("oneOf", []))
    return [v for v in variants if side.types(v) != frozenset({"null"})]


def _ref_name(schema: Any) -> str | None:
    if isinstance(schema, dict) and isinstance(schema.get("$ref"), str):
        return schema["$ref"].rsplit("/", 1)[-1]
    return None


class _Comparison:
    def __init__(self, served: dict[str, Any], published: dict[str, Any]) -> None:
        self.served = _Side(served)
        self.published = _Side(published)
        self.problems: list[str] = []
        self._seen: set[tuple[str, str, Direction]] = set()

    def schema(
        self, published: Any, served: Any, direction: Direction, where: str
    ) -> None:
        """Hold ``served`` to ``published``, in the ``direction`` data flows."""
        pub, pub_ref = self.published.flatten(published)
        srv, srv_ref = self.served.flatten(served)
        if pub_ref is not None and srv_ref is not None:
            key = (pub_ref, srv_ref, direction)
            if key in self._seen:
                return
            self._seen.add(key)

        pub_types = self.published.types(pub)
        srv_types = self.served.types(srv)
        compatible = (
            _within(srv_types, pub_types)
            if direction == "response"
            else _within(pub_types, srv_types)
        )
        if not compatible:
            self.problems.append(
                f"{where}: type {_describe(pub_types)} is now {_describe(srv_types)}"
            )
            return

        if _is_union(pub) or _is_union(srv):
            self._variants(pub, srv, direction, where)
            return

        if direction == "request" and "enum" in pub and "enum" in srv:
            dropped = [value for value in pub["enum"] if value not in srv["enum"]]
            if dropped:
                self.problems.append(f"{where}: no longer takes {dropped}")

        self._properties(pub, srv, direction, where)
        if "items" in pub and "items" in srv:
            self.schema(pub["items"], srv["items"], direction, f"{where}[]")
        pub_extra = pub.get("additionalProperties")
        srv_extra = srv.get("additionalProperties")
        if isinstance(pub_extra, dict) and isinstance(srv_extra, dict):
            self.schema(pub_extra, srv_extra, direction, f"{where}{{}}")

    def _variants(
        self, pub: dict[str, Any], srv: dict[str, Any], direction: Direction, where: str
    ) -> None:
        """Follow a union into its members where they pair up: one non-null
        member each side (``X | null`` against ``X``), or members named by one
        reference."""
        pub_members = _members(pub, self.published)
        srv_members = _members(srv, self.served)
        if len(pub_members) == 1 and len(srv_members) == 1:
            self.schema(pub_members[0], srv_members[0], direction, where)
            return
        served_by_name = {
            name: member
            for member in srv_members
            if (name := _ref_name(member)) is not None
        }
        for member in pub_members:
            name = _ref_name(member)
            if name is None:
                continue
            if name in served_by_name:
                self.schema(member, served_by_name[name], direction, f"{where}<{name}>")
            elif direction == "request":
                self.problems.append(f"{where}: no longer takes {name}")

    def _properties(
        self, pub: dict[str, Any], srv: dict[str, Any], direction: Direction, where: str
    ) -> None:
        pub_properties = pub.get("properties", {})
        srv_properties = srv.get("properties", {})
        pub_required = set(pub.get("required", ()))
        srv_required = set(srv.get("required", ()))
        for name, field in pub_properties.items():
            at = f"{where}.{name}"
            if name not in srv_properties:
                self.problems.append(f"{at}: removed")
                continue
            if direction == "response" and name in pub_required - srv_required:
                self.problems.append(f"{at}: no longer always sent")
            if direction == "request" and name in srv_required - pub_required:
                self.problems.append(f"{at}: now required")
            self.schema(field, srv_properties[name], direction, at)
        if direction == "request":
            for name in sorted(srv_required - set(pub_properties)):
                self.problems.append(f"{where}.{name}: new and required")

    def operation(
        self, where: str, published: dict[str, Any], served: dict[str, Any]
    ) -> None:
        self._parameters(where, published, served)
        self._request_body(where, published, served)
        self._responses(where, published, served)

    def _parameters(
        self, where: str, published: dict[str, Any], served: dict[str, Any]
    ) -> None:
        def keyed(side: _Side, operation: dict[str, Any]) -> dict[tuple[str, str], Any]:
            found = {}
            for raw in operation.get("parameters", ()):
                parameter, _ = side.resolve(raw)
                found[(parameter["in"], parameter["name"])] = parameter
            return found

        pub = keyed(self.published, published)
        srv = keyed(self.served, served)
        for (location, name), parameter in pub.items():
            at = f"{where} {location} parameter {name}"
            if (location, name) not in srv:
                self.problems.append(f"{at}: removed")
                continue
            now = srv[(location, name)]
            if now.get("required") and not parameter.get("required"):
                self.problems.append(f"{at}: now required")
            self.schema(
                _parameter_schema(parameter), _parameter_schema(now), "request", at
            )
        for (location, name), parameter in srv.items():
            if (location, name) not in pub and parameter.get("required"):
                self.problems.append(
                    f"{where} {location} parameter {name}: new and required"
                )

    def _request_body(
        self, where: str, published: dict[str, Any], served: dict[str, Any]
    ) -> None:
        pub, _ = self.published.resolve(published.get("requestBody"))
        srv, _ = self.served.resolve(served.get("requestBody"))
        if not srv:
            if pub:
                self.problems.append(f"{where} request body: removed")
            return
        if not pub:
            if srv.get("required"):
                self.problems.append(f"{where} request body: new and required")
            return
        if srv.get("required") and not pub.get("required"):
            self.problems.append(f"{where} request body: now required")
        for media, content in pub.get("content", {}).items():
            at = f"{where} request body {media}"
            served_content = srv.get("content", {}).get(media)
            if served_content is None:
                self.problems.append(f"{at}: no longer taken")
                continue
            self.schema(
                content.get("schema", {}),
                served_content.get("schema", {}),
                "request",
                at,
            )

    def _responses(
        self, where: str, published: dict[str, Any], served: dict[str, Any]
    ) -> None:
        srv_responses = served.get("responses", {})
        for status, raw in published.get("responses", {}).items():
            at = f"{where} response {status}"
            if status not in srv_responses:
                self.problems.append(f"{at}: removed")
                continue
            pub, _ = self.published.resolve(raw)
            srv, _ = self.served.resolve(srv_responses[status])
            for media, content in (pub.get("content") or {}).items():
                served_content = (srv.get("content") or {}).get(media)
                if served_content is None:
                    self.problems.append(f"{at} {media}: removed")
                    continue
                self.schema(
                    content.get("schema", {}),
                    served_content.get("schema", {}),
                    "response",
                    f"{at} {media}",
                )


def _parameter_schema(parameter: dict[str, Any]) -> Any:
    """A parameter's schema, whether given directly or by media type."""
    if "schema" in parameter:
        return parameter["schema"]
    for content in (parameter.get("content") or {}).values():
        return content.get("schema", {})
    return {}


def missing_from(served: dict[str, Any], published: dict[str, Any]) -> list[str]:
    """Each way ``served`` no longer serves what ``published`` names; empty
    when it is a superset of it."""
    comparison = _Comparison(served, published)
    served_paths = served.get("paths", {})
    for path, item in published.get("paths", {}).items():
        for method in _METHODS:
            if method not in item:
                continue
            where = f"{method.upper()} {path}"
            operation = served_paths.get(path, {}).get(method)
            if operation is None:
                comparison.problems.append(f"{where}: removed")
                continue
            comparison.operation(where, item[method], operation)
    return comparison.problems
