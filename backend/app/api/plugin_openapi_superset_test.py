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


def _changed(change) -> list[str]:
    """What the comparator finds when the served document is changed by
    ``change`` and the published one is not."""
    served = _document()
    change(served)
    return missing_from(served, _document())


def _schemas(document: dict[str, Any]) -> dict[str, Any]:
    return document["components"]["schemas"]


def _list_operation(document: dict[str, Any]) -> dict[str, Any]:
    return document["paths"]["/projects/"]["get"]


class TestTheComparator:
    def test_the_same_document_serves_itself(self):
        assert missing_from(_document(), _document()) == []

    def test_additions_are_fine(self):
        def add(document):
            document["paths"]["/tasks/"] = {"get": {"responses": {}}}
            document["paths"]["/projects/"]["delete"] = {"responses": {}}
            _list_operation(document)["parameters"].append(
                {"name": "q", "in": "query", "schema": {"type": "string"}}
            )
            _schemas(document)["Project"]["properties"]["color"] = {"type": "string"}
            _schemas(document)["ProjectCreate"]["properties"]["color"] = {
                "type": "string"
            }
            _schemas(document)["ProjectCreate"]["properties"]["kind"]["enum"].append(
                "c"
            )
            _list_operation(document)["responses"]["404"] = {"description": "no"}

        assert _changed(add) == []

    def test_a_removed_path_fails(self):
        assert _changed(lambda d: d["paths"].pop("/projects/")) == [
            "GET /projects/: removed",
            "POST /projects/: removed",
        ]

    def test_a_removed_method_fails(self):
        assert _changed(lambda d: d["paths"]["/projects/"].pop("post")) == [
            "POST /projects/: removed"
        ]

    def test_a_removed_property_fails_through_its_references(self):
        found = _changed(lambda d: _schemas(d)["Person"]["properties"].pop("id"))
        assert (
            "GET /projects/ response 200 application/json.items[].owner.id: removed"
            in found
        )

    def test_a_changed_type_fails(self):
        def change(document):
            _schemas(document)["Project"]["properties"]["name"] = {"type": "integer"}

        assert (
            "GET /projects/ response 200 application/json.items[].name: "
            "type string is now integer"
        ) in _changed(change)

    def test_a_response_field_that_may_now_be_null_fails(self):
        def change(document):
            _schemas(document)["Project"]["properties"]["name"] = {
                "anyOf": [{"type": "string"}, {"type": "null"}]
            }

        # A component is compared once, where it is first reached.
        assert _changed(change) == [
            (
                "GET /projects/ response 200 application/json.items[].name: "
                "type string is now null|string"
            )
        ]

    def test_a_response_field_no_longer_always_sent_fails(self):
        def change(document):
            _schemas(document)["Project"]["required"].remove("name")

        assert _changed(change) == [
            (
                "GET /projects/ response 200 application/json.items[].name: "
                "no longer always sent"
            )
        ]

    def test_a_narrower_response_type_is_fine(self):
        def change(document):
            _schemas(document)["Project"]["properties"]["count"] = {"type": "integer"}
            _schemas(document)["Project"]["properties"]["owner"] = {
                "$ref": f"{_REF}Person"
            }

        assert _changed(change) == []

    def test_a_removed_parameter_fails(self):
        def change(document):
            _list_operation(document)["parameters"].pop(0)

        assert _changed(change) == ["GET /projects/ query parameter page: removed"]

    def test_a_parameter_moved_to_another_location_fails(self):
        def change(document):
            _list_operation(document)["parameters"][0]["in"] = "header"

        assert _changed(change) == ["GET /projects/ query parameter page: removed"]

    def test_a_parameter_of_another_type_fails(self):
        def change(document):
            _list_operation(document)["parameters"][0]["schema"] = {"type": "string"}

        assert _changed(change) == [
            "GET /projects/ query parameter page: type integer is now string"
        ]

    def test_a_parameter_that_no_longer_takes_null_fails(self):
        def change(document):
            _list_operation(document)["parameters"][1]["schema"] = {"type": "boolean"}

        assert _changed(change) == [
            "GET /projects/ query parameter archived: type boolean|null is now boolean"
        ]

    def test_a_parameter_that_takes_more_is_fine(self):
        def change(document):
            _list_operation(document)["parameters"][0]["schema"] = {"type": "number"}

        assert _changed(change) == []

    def test_a_new_required_parameter_fails(self):
        def change(document):
            _list_operation(document)["parameters"].append(
                {
                    "name": "scope",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                }
            )

        assert _changed(change) == [
            "GET /projects/ query parameter scope: new and required"
        ]

    def test_a_request_property_now_required_fails(self):
        def change(document):
            _schemas(document)["ProjectCreate"]["required"].append("kind")

        assert _changed(change) == [
            "POST /projects/ request body application/json.kind: now required"
        ]

    def test_a_request_value_no_longer_taken_fails(self):
        def change(document):
            _schemas(document)["ProjectCreate"]["properties"]["kind"]["enum"] = ["a"]

        assert _changed(change) == [
            "POST /projects/ request body application/json.kind: no longer takes ['b']"
        ]

    def test_a_removed_response_fails(self):
        def change(document):
            document["paths"]["/projects/"]["post"]["responses"] = {
                "200": document["paths"]["/projects/"]["post"]["responses"]["201"]
            }

        assert _changed(change) == ["POST /projects/ response 201: removed"]

    def test_a_component_inlined_or_renamed_compares_by_what_it_holds(self):
        def change(document):
            schemas = _schemas(document)
            schemas["Owner"] = schemas.pop("Person")
            text = json.dumps(document).replace(f"{_REF}Person", f"{_REF}Owner")
            document.clear()
            document.update(json.loads(text))
            create = document["paths"]["/projects/"]["post"]["requestBody"]
            create["content"]["application/json"]["schema"] = copy.deepcopy(
                _schemas(document)["ProjectCreate"]
            )

        assert _changed(change) == []


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
