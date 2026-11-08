"""The plug-in API's document: the routes an installed plug-in may call, as it calls
them.

The main document marks each operation a plug-in may call with ``x-plugin-scope``,
read from the route's scope dependency (:func:`mark_plugin_scopes`). The plug-in's
document (:func:`build_plugin_openapi`) is cut from it:

- only the marked operations, and the component schemas they reach;
- every identity field (``x-identity``) is a string, the install's reference;
- every shape that draws a person (``x-person``) is ``PluginPerson``, which is
  what an install receives in its place;
- every field that mentions people (``x-mentions``) says how it names them,
  and that a stored file it shows comes without its path;
- every field holding a file's path (``x-upload``) says that a stored file
  comes as an empty string;
- paths start after ``/api/v1/c/{community_id}``, served from ``/api/v1/c/0``: an
  install's community comes from its token;
- each operation is named after its route;
- the one credential is the installation's access token;
- its version is the plug-in API contract this build serves
  (:data:`~app.services.marketplace.plugin_api.PLUGIN_API_VERSION`), not this
  release's: a plug-in is built against an SDK version, and the SDK publishes
  this document at its own.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.routing import APIRoute, iter_route_contexts

from app.api.deps import route_plugin_scope_declaration
from app.core.config import API_V1_STR, PLUGIN_SERVER_URL
from app.core.identity_boundary import MentionForm
from app.schemas.platform.user import PluginPerson
from app.services.marketplace.plugin_api import PLUGIN_API_VERSION

#: The prefix every route a plug-in may call starts with.
COMMUNITY_PREFIX = f"{API_V1_STR}/c/{{community_id}}"

_SCHEMA_REF = "#/components/schemas/"
_PLUGIN_PERSON = PluginPerson.__name__
_SECURITY_SCHEME = "PluginToken"

#: What a field that mentions people says about them, by its ``x-mentions``.
_MENTIONS = {
    MentionForm.markdown.value: (
        "A person is mentioned as `@[](<reference>)`, by your reference for "
        "them, with no name: read who they are from the members search "
        "(`members:read`). Write a mention the same way. A stored file comes "
        "without its path: `![alt]()`, `[name]()`."
    ),
    MentionForm.lexical.value: (
        "A Lexical editor state. A person is mentioned by a node whose "
        "`mentionUserId` is your reference for them, with `mentionName` and "
        "`text` empty: read who they are from the members search "
        "(`members:read`). Write a mention the same way. A stored file comes "
        "without its path: an image's `src` and a link's `url` are empty."
    ),
}

#: What a field holding a file's path (``x-upload``) says about it.
_UPLOAD = (
    "A stored file comes as an empty string, without its path. A URL from "
    "elsewhere comes as it is."
)


def _scoped_operations(
    openapi_schema: dict[str, Any], routes: Iterable[Any]
) -> Iterator[tuple[str, str, str, Any, dict[str, Any]]]:
    """Each operation of a route that declares a plug-in scope: the route's
    name, its path, the method, the declaration and the operation. A route in
    an included router is read as FastAPI runs it, with the router's prefix
    and dependencies."""
    paths = openapi_schema["paths"]
    for route in iter_route_contexts(list(routes)):
        original, path = route.original_route, route.path_format
        if (
            not isinstance(original, APIRoute)
            or path is None
            or not route.include_in_schema
        ):
            continue
        declaration = route_plugin_scope_declaration(route)
        if declaration is None:
            continue
        for method in sorted(route.methods or ()):
            yield (
                original.name,
                path,
                method.lower(),
                declaration,
                paths[path][method.lower()],
            )


def mark_plugin_scopes(openapi_schema: dict[str, Any], routes: Iterable[Any]) -> None:
    """Set ``x-plugin-scope`` on each operation a plug-in may call, as its route's
    dependency declares it."""
    for *_, declaration, operation in _scoped_operations(openapi_schema, routes):
        operation["x-plugin-scope"] = declaration


def _schema_refs(node: Any) -> Iterator[str]:
    """The component schema names ``node`` refers to."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                if not value.startswith(_SCHEMA_REF):
                    raise ValueError(f"unexpected reference {value}")
                yield value.removeprefix(_SCHEMA_REF)
            else:
                yield from _schema_refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _schema_refs(item)


def _as_plugin_people(node: Any, people: set[str]) -> Any:
    """``node`` copied, with each reference to a schema in ``people`` a
    reference to ``PluginPerson``."""
    if isinstance(node, dict):
        return {
            key: (
                f"{_SCHEMA_REF}{_PLUGIN_PERSON}"
                if key == "$ref" and value.removeprefix(_SCHEMA_REF) in people
                else _as_plugin_people(value, people)
            )
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_as_plugin_people(item, people) for item in node]
    return node


def _as_references(node: Any) -> Any:
    """``node`` copied, with each identity field a string and each field that
    mentions people or holds a file's path described: what an install sends
    and receives."""
    if isinstance(node, dict):
        identity = node.get("x-identity")
        if identity is not None:
            kept = {key: node[key] for key in ("title", "description") if key in node}
            return {**kept, "type": "string", "x-identity": identity}
        copied = {key: _as_references(value) for key, value in node.items()}
        mentions = node.get("x-mentions")
        if mentions is not None:
            copied.setdefault("description", _MENTIONS[mentions])
        if node.get("x-upload"):
            copied.setdefault("description", _UPLOAD)
        return copied
    if isinstance(node, list):
        return [_as_references(item) for item in node]
    return node


def build_plugin_openapi(
    openapi_schema: dict[str, Any], routes: Iterable[Any]
) -> dict[str, Any]:
    """The plug-in's document, cut from the main one (``openapi_schema``, already
    marked by :func:`mark_plugin_scopes`). Raises on a route a plug-in may call
    outside a community, or on two such routes with one name."""
    paths: dict[str, dict[str, Any]] = {}
    named: dict[str, str] = {}
    for name, full_path, method, _, operation in _scoped_operations(
        openapi_schema, routes
    ):
        if not full_path.startswith(f"{COMMUNITY_PREFIX}/"):
            raise RuntimeError(f"{full_path} is not a community route")
        path = full_path.removeprefix(COMMUNITY_PREFIX)
        where = f"{method.upper()} {path}"
        if name in named:
            raise RuntimeError(
                f"two plug-in routes are named {name}: {named[name]} and {where}"
            )
        named[name] = where
        parameters = [
            parameter
            for parameter in operation.get("parameters", ())
            if not (parameter["in"] == "path" and parameter["name"] == "community_id")
        ]
        rewritten = {
            **operation,
            "security": [{_SECURITY_SCHEME: []}],
        }
        rewritten.pop("parameters", None)
        if parameters:
            rewritten["parameters"] = parameters
        paths.setdefault(path, {})[method] = rewritten

    schemas = {
        **openapi_schema["components"]["schemas"],
        _PLUGIN_PERSON: PluginPerson.model_json_schema(mode="serialization"),
    }
    people = {name for name, schema in schemas.items() if schema.get("x-person")}
    paths = _as_plugin_people(paths, people)
    reached: dict[str, Any] = {}
    pending = list(_schema_refs(paths))
    while pending:
        name = pending.pop()
        if name not in reached:
            reached[name] = _as_plugin_people(schemas[name], people)
            pending.extend(_schema_refs(reached[name]))

    return _as_references(
        {
            "openapi": openapi_schema["openapi"],
            "info": {"title": "Initiative plug-in API", "version": PLUGIN_API_VERSION},
            "servers": [{"url": PLUGIN_SERVER_URL}],
            "paths": paths,
            "components": {
                "schemas": dict(sorted(reached.items())),
                "securitySchemes": {
                    _SECURITY_SCHEME: {
                        "type": "http",
                        "scheme": "bearer",
                        "description": "The installation's access token.",
                    }
                },
            },
        }
    )
