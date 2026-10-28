"""Every field the contract declares is one this build reads.

The vocabulary now arrives from the plugin-kit rather than being declared here, and
a kit release can reach an author before it reaches a deployment. That makes one
failure possible that could not happen while this build owned both sides: the
contract declares a field, the normalizer does not read it, and the field is
dropped on publish.

It matters because several of them are not descriptions — they are restrictions
an author is asking this build to enforce. ``admin_only``, ``requires``,
``actors`` and ``connection.scope`` all narrow who or what reaches something,
and a narrowing that is dropped does not fail loudly at the moment it is lost.

So the inventory is checked in both directions:

* every field the contract declares survives a publish, and
* every key a published definition carries is one the contract declares —
  otherwise this build stores a term no author can discover.

The manifests below are deliberately maximal: they exist to populate every
field once, not to be realistic plug-ins. A plug-in is a container or declarative and
never both, so there are two, and each object is measured across both. A field
added to the contract and to nothing else fails here.
"""

import pytest

from app.services.marketplace import contract, service_plugins
from app.services.marketplace.definitions import normalize_listing_definition
from app.services.tenant import metadata as metadata_service

pytestmark = pytest.mark.always

#: The endpoint a widget binds and a sample is keyed by, written once.
READ_ENDPOINT = "plugin.acme.tracker.read"
#: The declarative plug-in's listing, which names it.
DECLARATIVE_ID = "acme.issues"


def maximal_manifest() -> dict:
    """One manifest carrying every field the contract declares.

    Two fields cannot appear beside their neighbours and are covered elsewhere in
    the document: a ``requires`` names exactly one operator, so ``all_of`` and
    ``any_of`` are used in different places; and an emitting endpoint carries
    none of the caller-side fields, so those sit on the read endpoint.
    """
    return {
        "plugin_kind": "service",
        "service": {
            "public_id": "acme.tracker",
            "protocol": 1,
            "scopes": ["projects:write", "comments:read", "plugins:acme.github"],
            "calls_plugins": True,
        },
        "features": [
            "endpoints",
            "widgets",
            "pages",
            "dashboards",
            "fields",
            "parts",
            "actions",
        ],
        "default_name": "Acme Tracker",
        "minimum_age": {"default": 16, "US": 13},
        "help": {"en": "Link the tracker's issues to tasks."},
        "settings": [
            {
                "key": "prefix",
                "type": "string",
                "label": {"en": "Prefix"},
                "description": {"en": "What references start with"},
                "unique": True,
                "assigned": "community_name",
            }
        ],
        "min_plugin_api": "4.2",
        "vendor": {
            "label": {"en": "Acme client"},
            "fields": [
                {
                    "key": "client_id",
                    "type": "string",
                    "required": True,
                    "label": {"en": "Client id"},
                },
                {"key": "private_key", "type": "secret", "label": {"en": "Key"}},
            ],
            "setup": {
                "kind": "github_app_manifest",
                "app": {
                    "name": "Acme Tracker",
                    "url": "https://acme.test",
                    "public": True,
                    "default_permissions": {"issues": "write"},
                    "default_events": ["issues"],
                },
                "values": {"client_id": "client_id", "private_key": "pem"},
            },
        },
        "connections": [
            {
                "id": "vendor",
                "scope": "static",
                "label": {"en": "Vendor"},
                "fields": [
                    {
                        "key": "choice",
                        "type": "select",
                        "label": {"en": "Choice"},
                        "required": True,
                        "options": ["a", "b"],
                        "managed": True,
                    }
                ],
                "flow": {
                    "type": "oauth2",
                    "authorize_url": "https://acme.test/oauth/authorize",
                    "token_url": "https://acme.test/oauth/token",
                    "client_id": "{vendor.client_id}",
                    "client_secret": "{vendor.private_key}",
                    "scopes": ["read"],
                    "pkce": True,
                    "authorize_params": {"prompt": "consent"},
                    "install_url": "https://acme.test/install",
                    "after_connect": True,
                    "revoke": "rfc7009",
                    "revoke_url": "https://acme.test/oauth/revoke",
                },
                "token": {
                    "type": "jwt_bearer",
                    "exchange_url": "https://acme.test/installs/{choice}/token",
                    "iss": "{vendor.client_id}",
                    "key": "{vendor.private_key}",
                    "alg": "RS256",
                    "lifetime": 300,
                    "exchange_body": {
                        "repositories": ["{choice}"],
                        "permissions": {"issues": "read"},
                    },
                },
                "access_hint": {"api": "Acme API", "scopes": ["read"]},
            },
            {
                "id": "other",
                "scope": "static",
                "label": {"en": "Other"},
                "fields": [
                    {"key": "token", "type": "secret", "label": {"en": "Token"}}
                ],
            },
        ],
        "webhooks": {
            "verify": {
                "scheme": "hmac_sha256",
                "header": "X-Acme-Signature",
                "prefix": "sha256=",
                "encoding": "hex",
                "secret": "{vendor.private_key}",
            },
            "dedup": "X-Acme-Delivery",
            "route": {"path": "install.id", "connection": "vendor", "field": "choice"},
        },
        "schedules": [{"id": "sync", "every": "15m"}],
        "endpoints": [
            {
                "id": READ_ENDPOINT,
                "direction": "read",
                "label": {"en": "Read"},
                "description": {"en": "Reads something"},
                "returns": [
                    {
                        "key": "count",
                        "type": "int",
                        "label": {"en": "Count"},
                        "list": True,
                    },
                    {
                        "key": "labels",
                        "type": "string",
                        "label": {"en": "Labels"},
                        "list": True,
                    },
                    # A figure counted against its ceiling, so a summary can
                    # draw the two as one measure.
                    {"key": "used", "type": "int", "of": "allowed"},
                    {"key": "allowed", "type": "int"},
                ],
                "group": "reports",
                "needs_subject": "tasks",
                "params": [
                    {
                        "key": "choice",
                        "type": "select",
                        "label": {"en": "Choice"},
                        "required": False,
                        "options": ["a", "b"],
                        "list": True,
                        # Values only the plug-in can enumerate, and the sibling
                        # answer it has to be told to enumerate them.
                        "options_from": {
                            "endpoint": READ_ENDPOINT,
                            "key": "count",
                            "label_key": "labels",
                            "needs": {"scope": "scope"},
                        },
                    },
                    {
                        "key": "scope",
                        "type": "string",
                        "label": {"en": "Scope"},
                    },
                ],
                "actors": ["member", "installation"],
                "requires": {"all_of": ["vendor"]},
                "cache_ttl_seconds": 60,
                "admin_only": True,
                "public": True,
            },
            {
                "id": "plugin.acme.tracker.written",
                "direction": "write",
                "label": {"en": "Written"},
                "params": [{"key": "note", "type": "string", "label": {"en": "Note"}}],
                "returns": [{"key": "number", "type": "int"}],
                # The same kind and key the emission about it declares, so a
                # consumer resolves both to one address.
                "identity": {"kind": "issue", "key": ["number"]},
            },
            {
                "id": "plugin.acme.tracker.emitted",
                "direction": "emit",
                "label": {"en": "Emitted"},
                "returns": [{"key": "number", "type": "int"}],
                "identity": {"kind": "issue", "key": ["number"]},
            },
        ],
        "community_summary": READ_ENDPOINT,
        "widgets": [
            {
                "id": "tile",
                "meta": {"name": {"en": "Tile"}},
                "module_source": "export default () => null;",
                "endpoints": [READ_ENDPOINT],
                # Keyed by the endpoints the widget declared; anything else is
                # dropped, so this is the only key that survives.
                "sample_data": {READ_ENDPOINT: {"count": [1], "labels": ["one"]}},
                "requires": {"any_of": ["vendor"]},
            }
        ],
        "pages": [
            {
                "id": "panel",
                "path": "/panel",
                "name": {"en": "Panel"},
                "scopes": ["community", "initiative"],
                "admin_only": True,
                "capabilities": ["camera"],
                "requires": {"all_of": ["other"]},
            }
        ],
        "fields": [
            {
                "key": "demo.link",
                "name": {"en": "Demo"},
                "kind": "badge",
                "list": True,
                "on": ["task", "queue_item"],
                "description": {"en": "The item's demo"},
                "tone": "accent",
                "states": {
                    "status": {
                        "name": {"en": "Status"},
                        "values": {
                            "open": {"label": {"en": "Open"}, "tone": "positive"}
                        },
                    }
                },
                "requires": {"all_of": ["vendor"]},
            },
            {
                "key": "demo.stage",
                "name": {"en": "Stage"},
                "kind": "select",
                "on": ["task"],
                "options": [
                    {"value": "won", "label": {"en": "Won"}, "color": "#22aa55"}
                ],
            },
            {
                "key": "demo.price",
                "name": {"en": "Price"},
                "kind": "currency",
                "on": ["task"],
                "currency": "EUR",
            },
        ],
        "actions": [
            {
                "id": "new-link",
                "name": {"en": "New link"},
                "endpoint": "plugin.acme.tracker.written",
                "params": ["note"],
                "on": ["task"],
                "confirm": {"en": "Make a new link?"},
                "menu": True,
                "admin_only": True,
                "requires": {"any_of": ["vendor"]},
            }
        ],
        # Every component once, each with every prop it takes.
        "parts": [
            {
                "id": "demo",
                "name": {"en": "Demo"},
                "on": ["task"],
                "description": {"en": "The task's demo"},
                "requires": {"all_of": ["other"]},
                "tree": {
                    "type": "section",
                    "props": {"title": {"en": "Demo"}, "collapsed": True},
                    "children": [
                        {"type": "field", "props": {"field": "demo.link"}},
                        {
                            "type": "stack",
                            "props": {"direction": "row", "gap": "small", "wrap": True},
                            "children": [
                                {"type": "value", "props": {"field": "demo.link"}},
                                {
                                    "type": "text",
                                    "props": {
                                        "text": {"en": "opened"},
                                        "tone": "muted",
                                    },
                                },
                            ],
                        },
                        {
                            "type": "button",
                            "props": {"action": "new-link", "variant": "primary"},
                        },
                    ],
                },
            }
        ],
        "dashboards": [
            {
                "uid": "0123456789ABCD",
                "public_id": "acme.board",
                "name": "Board",
                "description": "A ready-made arrangement",
                "layout": {"columns": 6},
                "widgets": [
                    {
                        "id": "w1",
                        "type": "tile",
                        "title": "Tile",
                        "grid": {"x": 0, "y": 0, "w": 3, "h": 2},
                        "binding": {
                            "endpoint_id": READ_ENDPOINT,
                            "params": {"choice": "a"},
                        },
                    }
                ],
            }
        ],
    }


def maximal_declarative_manifest() -> dict:
    """One declarative manifest carrying every declarative term.

    A request sends a body or a GraphQL query, a cursor goes in a parameter or
    a variable, and a route reads a body path or a header, so those are spread
    over several requests. Only a write's request names a connection per actor.
    """
    api = '"https://api.tracker.example/issues"'
    paged = {
        "kind": "page_number",
        "page_param": "page",
        "per_page_param": "per_page",
        "per_page": 50,
        "items": "response.body",
        "max_pages": 5,
        "on_limit": "truncate",
    }
    return {
        "plugin_kind": "service",
        "features": ["endpoints", "fields", "parts", "actions"],
        "hosts": ["api.tracker.example", "*.tracker.example"],
        "auth": {"header": "X-Tracker-Token", "prefix": ""},
        "scopes": ["projects:read", "comments:read"],
        "vendor": {
            "fields": [
                {"key": "client_id", "type": "string", "label": {"en": "Client"}},
                {"key": "secret", "type": "secret", "label": {"en": "Secret"}},
            ]
        },
        "connections": [
            {
                "id": "workspace",
                "scope": "static",
                "label": {"en": "Workspace"},
                "fields": [
                    {
                        "key": "owner",
                        "type": "string",
                        "label": {"en": "Owner"},
                        "managed": True,
                    }
                ],
                "flow": {
                    "type": "oauth2",
                    "authorize_url": "https://tracker.example/authorize",
                    "token_url": "https://tracker.example/token",
                    "client_id": "{vendor.client_id}",
                    "after_connect": {
                        "request": {
                            "method": "GET",
                            "url": '"https://api.tracker.example/user"',
                            "paging": {
                                "kind": "link_header",
                                "items": "response.body",
                                "max_pages": 3,
                                "on_limit": "truncate",
                            },
                        },
                        "map": '{"values": {"owner": response.body[0].login}}',
                        "refuse_when": "$not($exists(result.values.owner))",
                        "code": "not-installed",
                    },
                },
                "health": {
                    "request": {
                        "method": "GET",
                        "url": '"https://api.tracker.example/" & connection.owner',
                    },
                    "every": "15m",
                    "states": [
                        {
                            "status": "4xx",
                            "when": 'response.body.reason = "gone"',
                            "state": "removed",
                        }
                    ],
                },
            },
            {
                "id": "profile",
                "scope": "interactive",
                "label": {"en": "Your profile"},
                "fields": [],
                "flow": {
                    "type": "oauth2",
                    "authorize_url": "https://tracker.example/authorize",
                    "token_url": "https://tracker.example/token",
                    "client_id": "{vendor.client_id}",
                    "after_connect": {
                        "steps": [
                            {
                                "name": "me",
                                "request": {
                                    "method": "GET",
                                    "url": '"https://api.tracker.example/user"',
                                },
                            },
                            {
                                "name": "home",
                                "request": {
                                    "method": "GET",
                                    "url": '"https://api.tracker.example/users/"'
                                    " & steps.me.body.login",
                                },
                            },
                        ],
                        "map": '{"account_label": steps.home.body.name}',
                    },
                },
            },
        ],
        "webhooks": {
            "verify": {
                "scheme": "hmac_sha256",
                "header": "X-Signature",
                "encoding": "hex",
                "secret": "{vendor.secret}",
            },
            "dedup": "X-Delivery",
            "route": {"header": "X-Owner", "connection": "workspace", "field": "owner"},
            "events": [
                {
                    "when": 'headers."x-event" = "opened"',
                    "emit": "plugin.acme.issues.opened",
                    "map": '{"number": payload.number}',
                    "write": (
                        '[{"target": {"holding": {"key": "issue", "value":'
                        ' $string(payload.number)}}, "set": {"state": "open"}}]'
                    ),
                },
                # A row may change the plug-in's values and emit nothing.
                {
                    "when": 'headers."x-event" = "closed"',
                    "write": (
                        '[{"target": {"kind": "task", "id": payload.task},'
                        ' "set": {"state": null}}]'
                    ),
                },
            ],
            "status": [
                {
                    "when": 'headers."x-event" = "suspend"',
                    "connection": "workspace",
                    "state": "suspended",
                }
            ],
        },
        "schedules": [
            {
                "id": "sync",
                "every": "15m",
                "endpoint": "plugin.acme.issues.list",
                "params": '{"since": since}',
                "write": '[{"target": {"install": true}, "set": {"synced": now}}]',
            }
        ],
        "endpoints": [
            {
                "id": "plugin.acme.issues.list",
                "direction": "read",
                "actors": ["installation"],
                "returns": [{"key": "titles", "type": "string", "list": True}],
                "unavailable": ["archived"],
                "request": {
                    "method": "GET",
                    "url": api,
                    "query": {"state": '"open"'},
                    "headers": {"Accept": '"application/json"'},
                    "connection": "workspace",
                    "paging": paged,
                },
                "map": '{"titles": response.body.title[]}',
                "errors": [
                    {"status": 410, "when": "response.status = 410", "code": "archived"}
                ],
            },
            {
                "id": "plugin.acme.issues.search",
                "direction": "read",
                "returns": [{"key": "ids", "type": "string", "list": True}],
                "request": {
                    "method": "POST",
                    "url": api,
                    "graphql": {
                        "query": "query($after: String) { ids(after: $after) }",
                        "variables": "{}",
                    },
                    "connection": "workspace",
                    "paging": {
                        "kind": "cursor",
                        "next": "response.body.cursor",
                        "more": "response.body.more",
                        "variable": "after",
                        "items": "response.body.ids",
                        "max_pages": 2,
                        "on_limit": "refuse",
                    },
                },
                "map": '{"ids": response.body[]}',
            },
            {
                "id": "plugin.acme.issues.label",
                "direction": "write",
                "actors": ["member", "installation"],
                "requires": {"all_of": ["workspace"]},
                "returns": [{"key": "number", "type": "int"}],
                "identity": {"kind": "issue", "key": ["number"]},
                "steps": [
                    {
                        "name": "current",
                        "request": {
                            "method": "GET",
                            "url": api,
                            "connection": "workspace",
                            "paging": {
                                "kind": "cursor",
                                "next": "response.body.next",
                                "more": "$exists(response.body.next)",
                                "param": "cursor",
                                "max_pages": 2,
                                "on_limit": "truncate",
                            },
                        },
                    },
                    {
                        "name": "set",
                        "request": {
                            "method": "PUT",
                            "url": api,
                            "body": '{"labels": steps.current.body.name}',
                            "connection": {
                                "member": "profile",
                                "installation": "workspace",
                            },
                        },
                    },
                ],
                "map": '{"number": steps.set.body.number}',
            },
            {
                "id": "plugin.acme.issues.opened",
                "direction": "emit",
                "returns": [{"key": "number", "type": "int"}],
            },
        ],
        "fields": [
            {
                "key": "issue",
                "name": {"en": "Issue"},
                "kind": "number",
                "list": True,
                "on": ["task"],
                "actions": ["refresh"],
            }
        ],
        "actions": [
            {
                "id": "label",
                "name": {"en": "Label"},
                "endpoint": "plugin.acme.issues.label",
                "write": '{"set": {"labelled": result.number}}',
                "on": ["task"],
            },
            # A read fetches what the action's write keeps.
            {
                "id": "refresh",
                "name": {"en": "Refresh"},
                "endpoint": "plugin.acme.issues.list",
                "write": '{"set": {"titles": result.titles}}',
                "on": ["task"],
            },
        ],
        "parts": [
            {
                "id": "issue",
                "name": {"en": "Issue"},
                "on": ["task"],
                "tree": {
                    "type": "stack",
                    "children": [
                        {"type": "field", "props": {"field": "issue"}},
                        {"type": "button", "props": {"action": "label"}},
                    ],
                },
            }
        ],
    }


@pytest.fixture(scope="module")
def published() -> dict:
    """The maximal manifest as this build would store it."""
    return normalize_listing_definition("plugin", maximal_manifest())


@pytest.fixture(scope="module")
def declarative() -> dict:
    """The maximal declarative manifest as this build would store it."""
    return normalize_listing_definition(
        "plugin", maximal_declarative_manifest(), public_id=DECLARATIVE_ID
    )


@pytest.fixture(scope="module")
def nodes(published, declarative) -> list[tuple[str, dict]]:
    return _nodes(published, declarative)


def _nodes(published: dict, declarative: dict) -> list[tuple[str, dict]]:
    """Each contract object beside the published node that should carry it,
    measured across both manifests where neither alone carries every field."""
    connection, other = published["connections"]
    read, written, _emitted = published["endpoints"]
    widget = published["widgets"][0]
    dashboard = published["dashboards"][0]
    workspace, profile = declarative["connections"]
    after = workspace["flow"]["after_connect"]
    listed, searched, labelled, _opened = declarative["endpoints"]
    current, setting = labelled["steps"]
    hooks = declarative["webhooks"]
    part = published["parts"][0]
    section = part["tree"]
    field_node, stack, button = section["children"]
    value_node, text = stack["children"]
    return [
        ("manifest", {**published, **declarative}),
        ("connection", {**connection, **workspace}),
        ("connectionField", connection["fields"][0]),
        ("connectionFlow", connection["flow"]),
        ("connectionToken", connection["token"]),
        ("vendor", published["vendor"]),
        ("vendorField", published["vendor"]["fields"][0]),
        ("githubAppManifestSetup", published["vendor"]["setup"]),
        ("githubAppManifest", published["vendor"]["setup"]["app"]),
        ("webhooks", {**published["webhooks"], **hooks}),
        ("webhookVerify", published["webhooks"]["verify"]),
        ("webhookRoute", {**published["webhooks"]["route"], **hooks["route"]}),
        # A container's schedule names its interval, a declarative plug-in's
        # the read it makes and what it writes from the answer.
        ("schedule", {**published["schedules"][0], **declarative["schedules"][0]}),
        ("accessHint", connection["access_hint"]),
        # A read carries the caller-side fields and a write carries the
        # identity; no single direction carries every field, so the two are
        # measured together.
        ("endpoint", {**read, **written, **listed, **labelled}),
        ("endpointParam", read["params"][0]),
        # `list` and `of` never share a return: a list has no one figure to
        # count against anything.
        ("endpointReturn", {**read["returns"][0], **read["returns"][2]}),
        ("widget", widget),
        ("page", published["pages"][0]),
        ("bundledDashboard", dashboard),
        ("bundledDashboardWidget", dashboard["widgets"][0]),
        # `requires` names one operator at a time, so the two are covered from
        # the two places that use them.
        ("requires", {**read["requires"], **widget["requires"]}),
        ("endpointIdentity", written["identity"]),
        ("vendorAuth", declarative["auth"]),
        (
            "vendorRequest",
            {**listed["request"], **searched["request"], **setting["request"]},
        ),
        ("actorConnections", setting["request"]["connection"]),
        ("graphqlRequest", searched["request"]["graphql"]),
        ("requestStep", current),
        ("pageNumberPaging", listed["request"]["paging"]),
        ("linkHeaderPaging", after["request"]["paging"]),
        (
            "cursorPaging",
            {**searched["request"]["paging"], **current["request"]["paging"]},
        ),
        ("errorRule", listed["errors"][0]),
        # A call is one request or its steps, so the two after_connects are
        # measured together.
        ("afterConnect", {**after, **profile["flow"]["after_connect"]}),
        ("connectionHealth", workspace["health"]),
        ("healthState", workspace["health"]["states"][0]),
        ("webhookEvent", hooks["events"][0]),
        ("webhookStatus", hooks["status"][0]),
        # Only a declarative plug-in's list field offers its elements actions.
        # A select's options and money's currency are terms of those kinds.
        (
            "field",
            {
                **published["fields"][0],
                **declarative["fields"][0],
                **published["fields"][1],
                **published["fields"][2],
            },
        ),
        ("fieldOption", published["fields"][1]["options"][0]),
        ("stateFacet", published["fields"][0]["states"]["status"]),
        ("stateValue", published["fields"][0]["states"]["status"]["values"]["open"]),
        ("setting", published["settings"][0]),
        # Only a declarative plug-in's action carries a write.
        ("action", {**published["actions"][0], **declarative["actions"][0]}),
        ("part", part),
        ("sectionNode", section),
        ("stackNode", stack),
        ("fieldNode", field_node),
        ("valueNode", value_node),
        ("textNode", text),
        ("buttonNode", button),
        ("other", other),
    ]


def test_every_declared_field_survives_a_publish(nodes):
    """A field the contract declares that nothing here reads is a restriction an
    author asked for and this build would discard without saying so."""
    for owner, node in nodes:
        if owner == "other":
            continue
        missing = [field for field in contract.fields(owner) if field not in node]
        assert not missing, f"{owner} lost {missing}"


def test_nothing_is_stored_that_the_contract_does_not_declare(nodes):
    """The other direction: a key this build writes but the contract does not
    name is one no author can discover, and no schema describes."""
    for owner, node in nodes:
        if owner in {"requires", "other"}:
            continue
        declared = set(contract.fields(owner))
        assert not set(node) - declared, f"{owner} carries undeclared keys"


def test_every_service_field_survives_a_publish(published):
    """``service`` is written inline rather than as a named object, so the
    inventory above does not reach it; its fields are measured here."""
    declared = contract.manifest_schema()["properties"]["service"]["properties"]
    assert set(declared) == set(published["service"])
    assert published["service"]["scopes"] == [
        "comments:read",
        "plugins:acme.github",
        "projects:write",
    ]


def test_every_node_prop_survives_a_publish(published):
    """A node's props are written inline, so the inventory above does not reach
    them; they are measured here, for every component the contract offers."""
    section = published["parts"][0]["tree"]
    stack = section["children"][1]
    stored = {
        node["type"]: node.get("props", {})
        for node in (section, *section["children"], *stack["children"])
    }
    assert set(stored) == set(service_plugins.PART_NODES)
    for node_type, props in stored.items():
        name = service_plugins.PART_NODES[node_type]
        declared = contract.objects()[name]["properties"]["props"]["properties"]
        assert set(props) == set(declared), node_type


def test_the_maximal_manifests_really_are_maximal(nodes):
    """The two tests above pass trivially if the fixtures stopped covering
    something, so the fixtures themselves are checked: every object the
    contract defines with fields is one these manifests reach. A change, and
    a list's element, is what a ``write`` answers rather than a term a
    manifest stores, and the changes engine holds an answer to it
    (``metadata.apply_changes``), an element's every term."""
    reached = {owner for owner, _ in nodes} - {"other"}
    with_fields = {name for name in contract.objects() if contract.fields(name)}
    assert with_fields - reached == {"change", "targetedChange", "listElement"}
    assert set(metadata_service._ELEMENT_TERMS) == set(contract.fields("listElement"))


def test_an_emitting_endpoint_keeps_what_describes_it(published):
    """An emission is the one endpoint chosen without ever being called, so the
    fields that describe it must survive even though the caller-side ones are
    refused on it."""
    emitted = published["endpoints"][2]
    assert emitted["label"] == {"en": "Emitted"}
    assert emitted["direction"] == "emit"
    for caller_side in (
        "params",
        "requires",
        "cache_ttl_seconds",
        "actors",
        "admin_only",
        "public",
    ):
        assert caller_side not in emitted


# --- values a stored column depends on --------------------------------------


def test_the_uid_shape_matches_the_contract():
    """The uid's length and alphabet are the contract's, and they are also a
    column width.

    Deliberately checked rather than read: `models.platform.marketplace` sizes a
    Postgres column with `UID_LENGTH`, so adopting a new value automatically
    would change a stored column without a migration. A cap that reaches the
    database has to break the build and be moved by hand.
    """
    from app.models.platform.marketplace import UID_ALPHABET, UID_LENGTH

    assert UID_LENGTH == contract.cap("uidLength")
    assert frozenset(UID_ALPHABET) == contract.charset("uid")


def test_the_metadata_columns_match_the_contract():
    """A plug-in's metadata key and an element's ref are column widths, and
    the items it keeps values on are the table's CHECK, so each is checked against
    the contract rather than read from it, as the uid is. So are a setting's
    key and a unique setting's value, which an install claims."""
    from app.core.tools import ITEM_KINDS
    from app.models.platform.plugin_install import (
        SETTING_KEY_LENGTH,
        SETTING_VALUE_LENGTH,
    )
    from app.models.tenant.metadata import REF_LENGTH, MetadataDefinition

    assert MetadataDefinition.__table__.c.key.type.length == contract.cap(
        "metadataKeyLength"
    )
    assert REF_LENGTH == contract.cap("metadataLookupLength")
    assert frozenset(ITEM_KINDS) == contract.enum("itemKind")
    assert SETTING_KEY_LENGTH == contract.cap("identifierLength")
    assert SETTING_VALUE_LENGTH == contract.cap("uniqueSettingValueLength")


# --- what the registrar reports -------------------------------------------


def test_a_term_the_contract_does_not_name_is_reported():
    """The whole point of the report: a newer plug-in's extra terms are named."""
    served = maximal_manifest()
    served["rate_limit"] = 5
    served["endpoints"][0]["retries"] = 3
    assert contract.discarded_terms(served) == ["endpoints.0.retries", "rate_limit"]


def test_a_term_nested_in_an_inline_object_is_reported():
    """Not every object a manifest carries is a named definition — `service`,
    `layout`, `grid` and `binding` are written inline — and a term added inside
    one is exactly as invisible as a term added at the top.

    This is walked from the contract's own structure rather than from a list of
    where things nest, because that list is the kind of second copy the contract
    exists to remove: it was one, it missed all four of these, and nothing said
    so.
    """
    served = maximal_manifest()
    served["service"]["region"] = "eu"
    served["dashboards"][0]["layout"]["gutter"] = 4
    served["dashboards"][0]["widgets"][0]["grid"]["z"] = 9
    served["dashboards"][0]["widgets"][0]["binding"]["timeout"] = 30

    assert contract.discarded_terms(served) == [
        "dashboards.0.layout.gutter",
        "dashboards.0.widgets.0.binding.timeout",
        "dashboards.0.widgets.0.grid.z",
        "service.region",
    ]


def test_an_object_the_contract_leaves_open_reports_nothing():
    """A widget's `meta` and `sample_data` are opaque to the contract, and a
    binding's `params` are named by the author. Keys inside them are nobody's
    to declare, so reporting them would be noise on every honest manifest."""
    served = maximal_manifest()
    served["widgets"][0]["meta"]["whatever"] = 1
    served["widgets"][0]["sample_data"][READ_ENDPOINT] = {"anything": 2}
    served["dashboards"][0]["widgets"][0]["binding"]["params"]["choice"] = "b"

    assert contract.discarded_terms(served) == []


def test_a_manifest_this_build_fully_understands_reports_nothing():
    """The ordinary case. A report on a plug-in written against this contract
    would be a false alarm on every verification."""
    assert contract.discarded_terms(maximal_manifest()) == []


# --- what only the plug-in can know --------------------------------------------


def test_an_identity_must_name_single_returns_of_its_own_endpoint():
    """Nothing downstream refuses a bad address — it resolves to nothing, and a
    fire somebody was waiting on is dropped without a word. So it is refused
    here, at the one moment somebody can still fix it."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    def publish(**endpoint):
        body = maximal_manifest()
        body["endpoints"][1].update(endpoint)
        return normalize_listing_definition("plugin", body)

    with pytest.raises(ListingDefinitionError):
        publish(identity={"kind": "issue", "key": ["nothing_returned"]})

    with pytest.raises(ListingDefinitionError):
        publish(
            returns=[{"key": "numbers", "type": "int", "list": True}],
            identity={"kind": "issue", "key": ["numbers"]},
        )


def test_a_read_endpoint_has_no_identity():
    """It touched nothing, so there is nothing for it to address."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    body = maximal_manifest()
    body["endpoints"][0]["identity"] = {"kind": "issue", "key": ["count"]}
    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("plugin", body)


# --- a vendor's own setup flow ---------------------------------------------


@pytest.mark.parametrize(
    "values",
    [
        {"client_id": "pem"},
        {"client_id": "client_id", "private_key": "client_id"},
        {"nothing": "id"},
        {"client_id": "token"},
        {},
    ],
    ids=["secret-to-plain", "twice", "undeclared", "unknown", "empty"],
)
def test_a_setup_writes_each_answer_once_and_secrets_only_to_a_secret(values):
    """What GitHub answers with is written to the fields the setup names, so a
    secret one meeting a plain field would be shown on the settings form."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    body = maximal_manifest()
    body["vendor"]["setup"]["values"] = values
    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("plugin", body)


# --- container or declarative ----------------------------------------------


def _member_request_not_required(body: dict) -> None:
    """A request on a member's connection the endpoint does not require."""
    body["connections"].append(
        {
            "id": "account",
            "scope": "interactive",
            "label": {"en": "Your account"},
            "fields": [],
            "flow": {
                "type": "oauth2",
                "authorize_url": "https://tracker.example/authorize",
                "token_url": "https://tracker.example/token",
                "client_id": "{vendor.client_id}",
            },
        }
    )
    body["endpoints"][0]["request"]["connection"] = "account"


def _with(build, change):
    body = build()
    change(body)
    return body


def _labelled_on(connection) -> dict:
    """The maximal declarative manifest, its write's second request naming
    ``connection``."""
    body = maximal_declarative_manifest()
    body["endpoints"][2]["steps"][1]["request"]["connection"] = connection
    return body


@pytest.mark.parametrize(
    "body",
    [
        _with(maximal_manifest, lambda b: b.update(hosts=["api.acme.test"])),
        _with(
            maximal_manifest,
            lambda b: b["endpoints"][0].update(map='{"count": [1]}'),
        ),
        _with(
            maximal_manifest,
            lambda b: b["connections"][0]["flow"].update(
                after_connect=maximal_declarative_manifest()["connections"][0]["flow"][
                    "after_connect"
                ]
            ),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b.update(schedules=[{"id": "sync", "every": "15m"}]),
        ),
        # Declared as a feature too, so the kind is the only thing wrong.
        _with(
            maximal_declarative_manifest,
            lambda b: b.update(
                pages=[{"id": "panel", "path": "/panel", "name": {"en": "Panel"}}],
                features=[*b["features"], "pages"],
            ),
        ),
        *(
            _with(
                maximal_declarative_manifest,
                lambda b, scope=scope: b.update(scopes=[scope]),
            )
            for scope in (
                "projects:write",
                "initiatives:moderate",
                "community:admin",
                "plugins:acme.github",
            )
        ),
        _with(maximal_manifest, lambda b: b.update(scopes=["projects:read"])),
        _with(maximal_manifest, lambda b: b["actions"][0].pop("endpoint")),
        _with(maximal_manifest, lambda b: b["actions"][0].update(write='{"set": {}}')),
        _with(maximal_manifest, lambda b: b["schedules"][0].update(write="[]")),
        _with(
            maximal_declarative_manifest,
            lambda b: (b["actions"][0].pop("endpoint"), b["actions"][0].pop("write")),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["actions"][0].update(endpoint="plugin.acme.issues.opened"),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["actions"][0].update(write='{"set": '),
        ),
        _with(maximal_declarative_manifest, lambda b: b["schedules"][0].pop("write")),
        _with(
            maximal_declarative_manifest,
            lambda b: b["schedules"][0].update(endpoint="plugin.acme.issues.label"),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0].update(actors=["member"]),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["schedules"][0].update(id="workspace"),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["webhooks"]["events"][1].pop("write"),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["webhooks"]["events"][0].pop("map"),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["webhooks"]["events"][0].pop("emit"),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["webhooks"]["events"][1].update(write="["),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["connections"][0]["flow"].update(after_connect=True),
        ),
        _with(maximal_declarative_manifest, lambda b: b.pop("hosts")),
        _with(maximal_declarative_manifest, lambda b: b["endpoints"][0].pop("request")),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0].update(map="steps.later.body"),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["connections"][1]["flow"]["after_connect"].update(
                request={"method": "GET", "url": '"https://api.tracker.example/"'}
            ),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["connections"][1]["flow"]["after_connect"].update(
                map="steps.later.body"
            ),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0].update(map='{"titles": ['),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0]["request"].update(url='"https://x" &'),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0]["request"]["headers"].update(
                {"x-tracker-token": '"mine"'}
            ),
        ),
        _with(
            maximal_declarative_manifest, lambda b: b["endpoints"][0].update(retries=3)
        ),
        _with(maximal_declarative_manifest, _member_request_not_required),
        _with(
            maximal_declarative_manifest,
            lambda b: (
                b["endpoints"][2].update(requires={"all_of": ["workspace", "profile"]}),
                b["endpoints"][2]["steps"][1]["request"].update(connection="profile"),
            ),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["endpoints"][0]["request"].update(
                connection={"installation": "workspace"}
            ),
        ),
        _labelled_on({"member": "profile"}),
        _labelled_on({"member": "profile", "installation": "workspace", "owner": "x"}),
        _labelled_on({"member": "workspace", "installation": "workspace"}),
        _labelled_on({"member": "profile", "installation": "profile"}),
        _with(maximal_manifest, lambda b: b["fields"][0].update(actions=["new-link"])),
        _with(maximal_declarative_manifest, lambda b: b["fields"][0].pop("list")),
        _with(
            maximal_declarative_manifest,
            lambda b: b["fields"][0].update(actions=["gone"]),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: b["fields"][0].update(on=["post", "task"]),
        ),
        _with(
            maximal_declarative_manifest,
            lambda b: (
                b["actions"][0].pop("endpoint"),
                b["actions"][0].update(params=["number"]),
            ),
        ),
    ],
    ids=[
        "container-hosts",
        "container-map",
        "container-after-connect-request",
        "declarative-schedule-calls-no-hook",
        "declarative-pages",
        "declarative-write-scope",
        "declarative-moderator-scope",
        "declarative-admin-scope",
        "declarative-plugin-scope",
        "container-top-level-scopes",
        "container-action-without-endpoint",
        "container-action-write",
        "container-schedule-write",
        "declarative-action-names-nothing",
        "declarative-action-names-an-emission",
        "declarative-action-write-does-not-parse",
        "declarative-schedule-without-write",
        "declarative-schedule-names-a-write",
        "declarative-schedule-read-not-by-the-installation",
        "declarative-schedule-a-connections-id",
        "event-row-emits-and-writes-nothing",
        "event-row-emit-without-map",
        "event-row-map-without-emit",
        "event-row-write-does-not-parse",
        "declarative-after-connect-hook",
        "declarative-no-hosts",
        "declarative-no-request",
        "declarative-reads-a-later-step",
        "after-connect-request-and-steps",
        "after-connect-reads-a-later-step",
        "declarative-map-does-not-parse",
        "declarative-url-does-not-parse",
        "declarative-sets-the-credential",
        "unknown-endpoint-term",
        "member-connection-not-in-requires",
        "member-connection-the-installation-may-make",
        "connection-per-actor-on-a-read",
        "connection-per-actor-not-for-each-actor",
        "connection-per-actor-not-an-actor",
        "connection-per-actor-community-for-the-member",
        "connection-per-actor-members-for-the-installation",
        "container-element-actions",
        "element-actions-on-a-field-not-a-list",
        "element-action-not-declared",
        "element-action-not-where-the-field-is",
        "action-params-without-an-endpoint",
    ],
)
def test_one_plugin_is_one_kind_and_says_only_what_its_kind_says(body):
    """A plug-in is a container or declarative, never both, and a declarative
    plug-in's expressions parse and read only the steps before them. A
    declarative plug-in asks only for read scopes and has no pages; its actions
    name a write, a change, or both; its schedules make a read as the
    installation; and an event row emits, writes, or both. Only a declarative
    plug-in's list field offers actions on its elements, each declared and
    offered wherever the field is, and an action asks for the params of an
    endpoint it names. A request on a member's connection is one its endpoint
    requires and the installation does not make; a write's request naming a
    connection per actor names one for each of its actors, the member's own
    for the member and the community's for the installation. An endpoint is
    closed: a misspelt term is refused, not dropped."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("plugin", body, public_id=DECLARATIVE_ID)


def test_a_declarative_manifest_is_named_by_its_listing():
    """Its endpoints are namespaced under the listing's public id, since there
    is no service block to name it."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition("plugin", maximal_declarative_manifest())
    with pytest.raises(ListingDefinitionError):
        normalize_listing_definition(
            "plugin", maximal_declarative_manifest(), public_id="acme.other"
        )
    assert contract.discarded_terms(maximal_declarative_manifest()) == []
