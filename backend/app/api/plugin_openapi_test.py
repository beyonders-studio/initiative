"""The plug-in API's document, held to the routes it is cut from."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import AsyncClient

from app.api.deps import ActorContext, plugin_scope, route_plugin_scope_declaration
from app.api.plugin_openapi import COMMUNITY_PREFIX, build_plugin_openapi
from app.db.search_index import written_columns
from app.main import app, plugin_openapi
from app.services.marketplace.plugin_api import PLUGIN_API_VERSION
from app.services.tenant.attachments import _upload_columns

_APP_DIR = Path(__file__).resolve().parent.parent
_BACKEND = _APP_DIR.parent
_SCHEMA_REF = "#/components/schemas/"

#: Where a person is written for an installed plug-in.
_PLUGIN_PERSON_WRITES = {
    # Every shape the plug-in API's document types as ``PluginPerson``.
    "schemas/platform/user.py:PersonShape._as_plugin_person",
    # ``value`` holds whatever the property's type stores; a person for a
    # ``user_reference`` property, which the field's description states.
    "schemas/tenant/property.py:PropertySummary._value_out",
}

#: What says who a person is, beside the reference that names them.
_PERSON_DETAILS = {
    "username",
    "discriminator",
    "display_name",
    "avatar_url",
    "name",
    "full_name",
    "email",
}


def _nodes(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from _nodes(item)


@pytest.mark.always
def test_every_plugin_route_is_in_the_plugin_document_once_with_its_scope():
    main = app.openapi()
    expected: dict[str, tuple[str, str, Any]] = {}
    for route in iter_route_contexts(app.routes):
        original, full_path = route.original_route, route.path_format
        if (
            not isinstance(original, APIRoute)
            or full_path is None
            or not route.include_in_schema
        ):
            continue
        declaration = route_plugin_scope_declaration(route)
        for method in route.methods or ():
            operation = main["paths"][full_path][method.lower()]
            assert operation.get("x-plugin-scope") == declaration, full_path
            if declaration is not None:
                path = full_path.removeprefix(COMMUNITY_PREFIX)
                expected[original.name] = (method.lower(), path, declaration)

    published = [
        (operation["operationId"], (method, path, operation["x-plugin-scope"]))
        for path, item in plugin_openapi()["paths"].items()
        for method, operation in item.items()
    ]
    assert dict(published) == expected
    assert len(published) == len(expected)
    shapes = {type(scope).__name__ for _, _, scope in expected.values()}
    assert shapes == {"str", "dict"}


@pytest.mark.always
def test_the_plugin_document_is_versioned_as_the_vendored_sdk():
    """A plug-in is built against an SDK version, which is the contract this
    build serves: the version the vendored kit records, not this release's."""
    vendored = (_BACKEND / "vendor" / "plugin-kit" / "KIT_VERSION").read_text()
    assert PLUGIN_API_VERSION == vendored.strip()
    assert plugin_openapi()["info"]["version"] == PLUGIN_API_VERSION


def test_the_export_script_writes_the_plugin_document(tmp_path, monkeypatch):
    path = _BACKEND / "scripts" / "export_openapi.py"
    spec = importlib.util.spec_from_file_location("export_openapi", path)
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = tmp_path / "plugin.json"
    monkeypatch.setattr(sys, "argv", ["export_openapi.py", "--plugin", str(out)])
    script.main()
    exported = json.loads(out.read_text())
    assert exported["info"]["version"] == PLUGIN_API_VERSION
    assert exported == json.loads(json.dumps(plugin_openapi()))


@pytest.mark.always
def test_the_plugin_document_names_no_community_and_no_row_id():
    document = plugin_openapi()
    assert document["servers"] == [{"url": "/api/v1/c/0"}]
    for item in document["paths"].values():
        for operation in item.values():
            names = {p["name"] for p in operation.get("parameters", ())}
            assert "community_id" not in names, operation["operationId"]
    identities = [node for node in _nodes(document) if "x-identity" in node]
    assert identities
    assert all(node["type"] == "string" for node in identities)


@pytest.mark.always
def test_every_reference_in_the_plugin_document_resolves_in_it():
    document = plugin_openapi()
    schemas = document["components"]["schemas"]
    refs = {node["$ref"] for node in _nodes(document) if "$ref" in node}
    assert refs
    unresolved = {
        ref
        for ref in refs
        if not (
            ref.startswith(_SCHEMA_REF) and ref.removeprefix(_SCHEMA_REF) in schemas
        )
    }
    assert not unresolved


def test_json_query_parameters_are_published_as_json():
    (operation,) = [
        operation
        for item in plugin_openapi()["paths"].values()
        for operation in item.values()
        if operation["operationId"] == "list_tasks"
    ]
    parameters = {p["name"]: p for p in operation["parameters"]}
    items = {
        "conditions": {
            "anyOf": [
                {"$ref": f"{_SCHEMA_REF}FilterCondition"},
                {"$ref": f"{_SCHEMA_REF}FilterGroup"},
            ]
        },
        "sorting": {"$ref": f"{_SCHEMA_REF}SortField"},
    }
    for name, item in items.items():
        assert "schema" not in parameters[name]
        assert parameters[name]["content"] == {
            "application/json": {"schema": {"type": "array", "items": item}}
        }


def test_two_plugin_routes_with_one_name_fail_the_build():
    probe = FastAPI()

    async def handler(
        actor: Annotated[ActorContext, Depends(plugin_scope("projects:read"))],
    ) -> None:
        return None

    probe.add_api_route(f"{COMMUNITY_PREFIX}/a", handler, name="same")
    probe.add_api_route(f"{COMMUNITY_PREFIX}/b", handler, name="same")
    with pytest.raises(RuntimeError, match="GET /a and GET /b"):
        build_plugin_openapi(probe.openapi(), probe.routes)


def _names_a_person(field: Any) -> bool:
    return any(node.get("x-identity") == "person" for node in _nodes(field))


def _draws_a_person(properties: dict[str, Any]) -> bool:
    """Whether an object with ``properties`` names a person and says who they
    are. ``name`` beside an ``id`` of the object's own is the object's name."""
    details = _PERSON_DETAILS & set(properties)
    if "id" in properties and not _names_a_person(properties["id"]):
        details.discard("name")
    return bool(details) and any(map(_names_a_person, properties.values()))


@pytest.mark.always
def test_every_person_in_the_plugin_document_is_a_plugin_person():
    schemas = plugin_openapi()["components"]["schemas"]
    drawn = {
        name
        for name, schema in schemas.items()
        for node in _nodes(schema)
        if _draws_a_person(node.get("properties", {}))
    }
    assert drawn == {"PluginPerson"}
    assert not [name for name, schema in schemas.items() if schema.get("x-person")]


def _mention_forms(field: Any, schemas: dict[str, Any]) -> set[str]:
    """How ``field`` mentions people: its own mark, or its items' fields'."""
    nodes = list(_nodes(field))
    for node in list(nodes):
        if "$ref" in node:
            nodes.extend(_nodes(schemas[node["$ref"].removeprefix(_SCHEMA_REF)]))
    return {node["x-mentions"] for node in nodes if "x-mentions" in node}


@pytest.mark.always
def test_every_field_holding_written_text_carries_its_mentions():
    """A column somebody writes in may mention a person, and is where the
    erasure scrubs mentions (``mention_parser.anonymize_user_mentions``). Each
    field of the plug-in's document named for one says how it mentions people:
    an editor state as Lexical, text as markdown. Its schema describes it."""
    columns = {column for written in written_columns().values() for column in written}
    schemas = plugin_openapi()["components"]["schemas"]
    found: dict[tuple[str, str], set[str]] = {}
    expected: dict[tuple[str, str], set[str]] = {}
    for name, schema in schemas.items():
        for field, value in schema.get("properties", {}).items():
            if field not in columns:
                continue
            editor_state = any(node.get("type") == "object" for node in _nodes(value))
            expected[(name, field)] = {"lexical" if editor_state else "markdown"}
            found[(name, field)] = _mention_forms(value, schemas)
    assert expected
    assert found == expected
    marked = [node for node in _nodes(schemas) if "x-mentions" in node]
    assert all(node.get("description") for node in marked)


def _received(document: dict[str, Any]) -> set[str]:
    """The component schemas an operation's response reaches."""
    schemas = document["components"]["schemas"]
    pending = [
        node["$ref"]
        for item in document["paths"].values()
        for operation in item.values()
        for node in _nodes(operation["responses"])
        if "$ref" in node
    ]
    reached: set[str] = set()
    while pending:
        name = pending.pop().removeprefix(_SCHEMA_REF)
        if name not in reached:
            reached.add(name)
            pending.extend(n["$ref"] for n in _nodes(schemas[name]) if "$ref" in n)
    return reached


@pytest.mark.always
def test_every_field_in_the_plugin_document_holding_a_stored_file_s_path_says_so():
    """A column that holds a stored file's path, beside the ones people write
    in (``attachments._upload_columns``), comes to a plug-in as an empty string
    in place of the path. Each field of a shape a plug-in receives named for one
    carries ``x-upload``, which is where the path is emptied, and says so; every
    ``x-upload`` mark sits on a field of its own. A column people write in
    carries its ``Mentions`` mark instead (the test above), which leaves the
    path of each stored file it shows empty."""
    written = {column for columns in written_columns().values() for column in columns}
    paths = {column for _, column in _upload_columns()} - written
    document = plugin_openapi()
    schemas = document["components"]["schemas"]
    held = [
        schemas[name]["properties"][field]
        for name in _received(document)
        for field in schemas[name].get("properties", {})
        if field in paths
    ]
    assert paths
    assert held
    assert all(field.get("x-upload") for field in held)
    assert all("empty string" in field["description"] for field in held)
    main = app.openapi()["components"]["schemas"]
    marks = [node for node in _nodes(main) if "x-upload" in node]
    fields = [
        field
        for schema in main.values()
        for field in schema.get("properties", {}).values()
        if "x-upload" in field
    ]
    assert marks
    assert len(marks) == len(fields)


def _plugin_person_writes(node: ast.AST, scope: tuple[str, ...] = ()) -> Iterator[str]:
    """Where under ``node`` ``for_install`` is called, by the names of the
    classes and functions around each call."""
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        scope = (*scope, node.name)
    if isinstance(node, ast.Call):
        called = node.func
        name = called.attr if isinstance(called, ast.Attribute) else None
        if isinstance(called, ast.Name):
            name = called.id
        if name == "for_install":
            yield ".".join(scope)
    for child in ast.iter_child_nodes(node):
        yield from _plugin_person_writes(child, scope)


@pytest.mark.always
def test_every_plugin_person_write_is_listed():
    found = {
        f"{path.relative_to(_APP_DIR).as_posix()}:{where}"
        for path in _APP_DIR.rglob("*.py")
        if not path.name.endswith("_test.py")
        for where in _plugin_person_writes(ast.parse(path.read_text()))
    }
    assert found == _PLUGIN_PERSON_WRITES


async def test_the_plugin_document_and_its_page_are_served(client: AsyncClient):
    document = await client.get("/api/v1/plugin-platform/openapi.json")
    assert document.status_code == 200
    assert document.json() == plugin_openapi()
    assert document.json()["info"]["version"] == PLUGIN_API_VERSION
    page = await client.get("/api/v1/plugin-platform/docs")
    assert page.status_code == 200
    assert "/api/v1/plugin-platform/openapi.json" in page.text
    assert "https://cdn.jsdelivr.net" in page.headers["content-security-policy"]
