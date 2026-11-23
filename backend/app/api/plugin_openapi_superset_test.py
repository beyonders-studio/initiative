"""The plug-in API this build serves still serves the one the SDK publishes.

A plug-in is generated from the plug-in API document the SDK publishes at its
version, vendored here as ``vendor/plugin-kit/plugin-api.json``. Whatever that
names, this build must still serve; additions are fine. The comparator itself
is held to small documents first, so a pass means something.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.api.plugin_openapi_superset import missing_from
from app.main import plugin_openapi
from app.services.marketplace import contract

_REF = "#/components/schemas/"


def _document() -> dict[str, Any]:
    """A small plug-in API: a list read with a query parameter, and a create."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "4.1.0"},
        "paths": {
            "/projects/": {
                "get": {
                    "operationId": "list_projects",
                    "parameters": [
                        {
                            "name": "page",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        },
                        {
                            "name": "archived",
                            "in": "query",
                            "required": False,
                            "schema": {
                                "anyOf": [{"type": "boolean"}, {"type": "null"}]
                            },
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": f"{_REF}ProjectList"}
                                }
                            },
                        }
                    },
                },
                "post": {
                    "operationId": "create_project",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": f"{_REF}ProjectCreate"}
                            }
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": f"{_REF}Project"}
                                }
                            },
                        }
                    },
                },
            }
        },
        "components": {
            "schemas": {
                "ProjectList": {
                    "type": "object",
                    "required": ["items"],
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {"$ref": f"{_REF}Project"},
                        }
                    },
                },
                "Project": {
                    "type": "object",
                    "required": ["id", "name", "owner"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "count": {"type": "number"},
                        "owner": {
                            "anyOf": [{"$ref": f"{_REF}Person"}, {"type": "null"}]
                        },
                    },
                },
                "Person": {
                    "type": "object",
                    "required": ["id"],
                    "properties": {
                        "id": {"type": "string"},
                        "manager": {
                            "anyOf": [{"$ref": f"{_REF}Person"}, {"type": "null"}]
                        },
                    },
                },
                "ProjectCreate": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "kind": {"type": "string", "enum": ["a", "b"]},
                    },
                },
            }
        },
    }


def _schemas(document: dict[str, Any]) -> dict[str, Any]:
    return document["components"]["schemas"]


def _list_operation(document: dict[str, Any]) -> dict[str, Any]:
    return document["paths"]["/projects/"]["get"]


def _add(document):
    document["paths"]["/tasks/"] = {"get": {"responses": {}}}
    document["paths"]["/projects/"]["delete"] = {"responses": {}}
    _list_operation(document)["parameters"].append(
        {"name": "q", "in": "query", "schema": {"type": "string"}}
    )
    _schemas(document)["Project"]["properties"]["color"] = {"type": "string"}
    _schemas(document)["ProjectCreate"]["properties"]["color"] = {"type": "string"}
    _schemas(document)["ProjectCreate"]["properties"]["kind"]["enum"].append("c")
    _list_operation(document)["responses"]["404"] = {"description": "no"}


def _rename_and_inline(document):
    schemas = _schemas(document)
    schemas["Owner"] = schemas.pop("Person")
    text = json.dumps(document).replace(f"{_REF}Person", f"{_REF}Owner")
    document.clear()
    document.update(json.loads(text))
    create = document["paths"]["/projects/"]["post"]["requestBody"]
    create["content"]["application/json"]["schema"] = copy.deepcopy(
        _schemas(document)["ProjectCreate"]
    )


def _project(**properties):
    return lambda d: _schemas(d)["Project"]["properties"].update(properties)


def _parameter(index: int, **changes):
    return lambda d: _list_operation(d)["parameters"][index].update(changes)


_LIST = "GET /projects/ response 200 application/json.items[]"


@pytest.mark.parametrize(
    ("change", "found"),
    [
        pytest.param(lambda d: None, [], id="the-same-document"),
        pytest.param(_add, [], id="additions"),
        pytest.param(
            lambda d: d["paths"].pop("/projects/"),
            ["GET /projects/: removed", "POST /projects/: removed"],
            id="removed-path",
        ),
        pytest.param(
            lambda d: d["paths"]["/projects/"].pop("post"),
            ["POST /projects/: removed"],
            id="removed-method",
        ),
        pytest.param(
            lambda d: _schemas(d)["Person"]["properties"].pop("id"),
            [f"{_LIST}.owner.id: removed"],
            id="removed-property-through-its-references",
        ),
        pytest.param(
            _project(name={"type": "integer"}),
            [f"{_LIST}.name: type string is now integer"],
            id="changed-type",
        ),
        # A component is compared once, where it is first reached.
        pytest.param(
            _project(name={"anyOf": [{"type": "string"}, {"type": "null"}]}),
            [f"{_LIST}.name: type string is now null|string"],
            id="response-field-may-now-be-null",
        ),
        pytest.param(
            lambda d: _schemas(d)["Project"]["required"].remove("name"),
            [f"{_LIST}.name: no longer always sent"],
            id="response-field-no-longer-always-sent",
        ),
        pytest.param(
            _project(count={"type": "integer"}, owner={"$ref": f"{_REF}Person"}),
            [],
            id="narrower-response-type",
        ),
        pytest.param(
            lambda d: _list_operation(d)["parameters"].pop(0),
            ["GET /projects/ query parameter page: removed"],
            id="removed-parameter",
        ),
        pytest.param(
            _parameter(0, **{"in": "header"}),
            ["GET /projects/ query parameter page: removed"],
            id="parameter-moved",
        ),
        pytest.param(
            _parameter(0, schema={"type": "string"}),
            ["GET /projects/ query parameter page: type integer is now string"],
            id="parameter-of-another-type",
        ),
        pytest.param(
            _parameter(1, schema={"type": "boolean"}),
            [
                (
                    "GET /projects/ query parameter archived: "
                    "type boolean|null is now boolean"
                )
            ],
            id="parameter-no-longer-takes-null",
        ),
        pytest.param(
            _parameter(0, schema={"type": "number"}), [], id="parameter-takes-more"
        ),
        pytest.param(
            lambda d: _list_operation(d)["parameters"].append(
                {
                    "name": "scope",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                }
            ),
            ["GET /projects/ query parameter scope: new and required"],
            id="new-required-parameter",
        ),
        pytest.param(
            lambda d: _schemas(d)["ProjectCreate"]["required"].append("kind"),
            ["POST /projects/ request body application/json.kind: now required"],
            id="request-property-now-required",
        ),
        pytest.param(
            lambda d: _schemas(d)["ProjectCreate"]["properties"]["kind"].update(
                enum=["a"]
            ),
            [
                (
                    "POST /projects/ request body application/json.kind: "
                    "no longer takes ['b']"
                )
            ],
            id="request-value-no-longer-taken",
        ),
        pytest.param(
            lambda d: d["paths"]["/projects/"]["post"].update(
                responses={"200": d["paths"]["/projects/"]["post"]["responses"]["201"]}
            ),
            ["POST /projects/ response 201: removed"],
            id="removed-response",
        ),
        pytest.param(_rename_and_inline, [], id="component-inlined-or-renamed"),
    ],
)
def test_the_comparator_finds_what_the_served_document_no_longer_serves(change, found):
    """What it finds when the served document is changed and the published one
    is not: additions and narrower answers are fine, and a component compares
    by what it holds, not its name."""
    served = _document()
    change(served)
    assert missing_from(served, _document()) == found


@pytest.mark.always
def test_this_build_serves_the_plugin_api_the_sdk_publishes():
    """Everything the vendored SDK document names, this build still serves.
    The SDK version this build vendors is the contract it says it serves, so a
    removal or change here breaks plug-ins built against it: restore what moved,
    or move to an SDK major that drops it."""
    if not contract.PLUGIN_API_PATH.exists():
        pytest.skip(
            f"{contract.PLUGIN_API_PATH.name} is not vendored: kit "
            f"{contract.KIT_VERSION} publishes no plug-in API document. "
            "Refresh with scripts/refresh_plugin_kit.py to a kit release that does."
        )
    published = json.loads(contract.PLUGIN_API_PATH.read_text(encoding="utf-8"))
    assert published["info"]["version"] == contract.KIT_VERSION
    assert published.get("paths")
    assert missing_from(plugin_openapi(), published) == []
