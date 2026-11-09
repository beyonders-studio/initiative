"""The vendored contract, and the manifest this build actually accepts.

The vocabulary is declared once, in the plugin-kit, and vendored here. The kit
generates a JSON Schema from the same file. So there are three things that must
agree, and this module is where they are made to:

* **Derivation** — every vocabulary and cap this validator enforces reads from
  the vendored contract, and the vendored schema was built from that same
  contract. A schema and contract vendored from different kit revisions fail
  here.
* **Agreement** — a corpus of manifests run through both. Anything the validator
  accepts must satisfy the schema, or an author would be told their working
  manifest is wrong; anything the schema rejects for a reason it *can* express
  must be refused by the validator too, or the schema would be inventing a rule.

The asymmetry is deliberate: schema-valid is necessary, not sufficient. The
cases at the bottom pin the specific rules that only the validator enforces, so
that boundary is written down rather than discovered.

The field inventory — every term the contract declares having a handler here,
and every handler having a term — lives in :mod:`contract_coverage_test`.
"""

import pytest
from jsonschema import Draft202012Validator

from app.core.plugin_scopes import ALL_SCOPES
from app.services.marketplace import contract
from app.services.marketplace.definitions import normalize_listing_definition
from app.services.marketplace.manifest_values import (
    MAX_IDENTIFIER_LENGTH,
    MAX_PATH_LENGTH,
    MAX_PUBLIC_ID_LENGTH,
)
from app.services.marketplace.service_plugins import (
    ACTOR_KINDS,
    CONNECTION_SCOPES,
    DIRECTIONS,
    FEATURES,
    FIELD_TYPES,
    MAX_CONNECTIONS,
    MAX_ENDPOINTS,
    MAX_PAGES,
    MAX_RETURNS_PER_ENDPOINT,
    MAX_WIDGETS,
    PAGE_CAPABILITIES,
    PARAM_TYPES,
    PLUGIN_PROTOCOL_VERSIONS,
    RETURN_TYPES,
    SURFACE_SCOPES,
)
from app.services.marketplace.widget_meta import MAX_LOCALES, MAX_TEXT_LENGTH

pytestmark = pytest.mark.always


def platform_accepts(manifest) -> None:
    """Run a manifest through the whole plug-in path, not the service normalizer.

    `plugin_kind` is read by the dispatcher rather than by
    `normalize_service_plugin_definition`, so a case that varies it has to enter
    where a published manifest actually enters.
    """
    normalize_listing_definition("plugin", manifest)


# Unannotated on purpose: `jsonschema` builds its validator classes at runtime,
# so the name is not a type the checker can resolve.
@pytest.fixture(scope="module")
def validator():
    schema = contract.manifest_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _manifest(**overrides):
    """A minimal manifest the platform accepts, for a case to vary one thing of."""
    body = {
        "plugin_kind": "service",
        "service": {"public_id": "acme.tracker", "protocol": 1},
        "features": [],
    }
    body.update(overrides)
    return body


# --- the schema is a schema -------------------------------------------------


def test_the_schema_is_a_valid_2020_12_document():
    Draft202012Validator.check_schema(contract.manifest_schema())


def test_every_ref_resolves():
    """A `$ref` naming a definition that isn't there fails at use rather than at
    load, so it would survive a test that only validated the happy path."""
    schema = contract.manifest_schema()
    defs = set(schema["$defs"])

    def walk(node):
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                assert ref.startswith("#/$defs/"), ref
                assert ref.removeprefix("#/$defs/") in defs, ref
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


def test_the_vendored_pair_came_from_one_contract():
    """The schema is generated from the contract, so the two are vendored as a
    pair. Refreshing one without the other leaves this build enforcing a
    vocabulary the schema does not describe."""
    schema_caps = {
        contract.cap("connections"): contract.manifest_schema()["properties"][
            "connections"
        ]["maxItems"],
        contract.cap("endpoints"): contract.manifest_schema()["properties"][
            "endpoints"
        ]["maxItems"],
    }
    for from_contract, from_schema in schema_caps.items():
        assert from_contract == from_schema


# --- derived, not restated --------------------------------------------------


def test_vocabularies_come_from_the_validator():
    schema = contract.manifest_schema()
    props = schema["properties"]
    defs = schema["$defs"]

    assert set(props["features"]["items"]["enum"]) == FEATURES
    assert set(props["service"]["properties"]["protocol"]["enum"]) == (
        PLUGIN_PROTOCOL_VERSIONS
    )
    assert set(defs["connection"]["properties"]["scope"]["enum"]) == CONNECTION_SCOPES
    assert set(defs["connectionField"]["properties"]["type"]["enum"]) == FIELD_TYPES
    assert set(defs["endpointParam"]["properties"]["type"]["enum"]) == PARAM_TYPES
    assert set(defs["endpointReturn"]["properties"]["type"]["enum"]) == RETURN_TYPES
    assert set(defs["endpoint"]["properties"]["direction"]["enum"]) == DIRECTIONS
    assert set(defs["endpoint"]["properties"]["actors"]["items"]["enum"]) == ACTOR_KINDS
    scope_items = props["service"]["properties"]["scopes"]["items"]["anyOf"]
    assert set(scope_items[0]["enum"]) == set(ALL_SCOPES)
    assert scope_items[1] == {"$ref": "#/$defs/pluginScope"}
    assert defs["page"]["properties"]["admin_only"]["type"] == "boolean"
    assert defs["endpoint"]["properties"]["admin_only"]["type"] == "boolean"
    assert set(defs["page"]["properties"]["scopes"]["items"]["enum"]) == SURFACE_SCOPES
    assert set(defs["page"]["properties"]["capabilities"]["items"]["enum"]) == (
        PAGE_CAPABILITIES
    )


def test_caps_come_from_the_validator():
    props = contract.manifest_schema()["properties"]
    assert props["connections"]["maxItems"] == MAX_CONNECTIONS
    assert props["endpoints"]["maxItems"] == MAX_ENDPOINTS
    assert (
        contract.manifest_schema()["$defs"]["endpoint"]["properties"]["returns"][
            "maxItems"
        ]
        == MAX_RETURNS_PER_ENDPOINT
    )
    assert props["widgets"]["maxItems"] == MAX_WIDGETS
    assert props["pages"]["maxItems"] == MAX_PAGES


def test_a_secret_is_not_a_query_parameter():
    """`secret` is a connection field type and deliberately not a param type;
    the schema must not blur the two by sharing one field definition."""
    defs = contract.manifest_schema()["$defs"]
    assert "secret" in defs["connectionField"]["properties"]["type"]["enum"]
    assert "secret" not in defs["endpointParam"]["properties"]["type"]["enum"]
    # And only a connection field is written back by the plug-in.
    assert "managed" in defs["connectionField"]["properties"]
    assert "managed" not in defs["endpointParam"]["properties"]


def test_lengths_come_from_the_validator():
    defs = contract.manifest_schema()["$defs"]
    assert defs["identifier"]["maxLength"] == MAX_IDENTIFIER_LENGTH
    assert defs["path"]["maxLength"] == MAX_PATH_LENGTH
    assert (
        contract.manifest_schema()["properties"]["service"]["properties"]["public_id"][
            "maxLength"
        ]
        == MAX_PUBLIC_ID_LENGTH
    )


def test_the_schema_names_itself_stably():
    """An author points a `$schema` at this and a generator keys a cache on it,
    so a drifting `$id` invalidates both."""
    assert (
        contract.manifest_schema()["$id"]
        == "https://initiativetasks.com/schemas/plugin-manifest-v1.json"
    )


# --- the two agree ----------------------------------------------------------

ACCEPTED = [
    pytest.param(_manifest(), id="minimal"),
    pytest.param(
        _manifest(
            service={
                "public_id": "acme.tracker",
                "protocol": 1,
                "scopes": ["projects:write", "comments:read"],
            }
        ),
        id="requested-scopes",
    ),
    pytest.param(
        _manifest(
            service={
                "public_id": "acme.tracker",
                "protocol": 1,
                "scopes": ["projects:read", "plugins:acme.github"],
            }
        ),
        id="requested-plugin-scope",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {
                    "id": "plugin.acme.tracker.open",
                    "direction": "write",
                    "public": True,
                    "actors": ["member"],
                }
            ],
        ),
        id="public-write-endpoint",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            connections=[
                {
                    "id": "api",
                    "scope": "static",
                    "label": {"en": "API key"},
                    "fields": [
                        {"key": "token", "type": "secret", "label": {"en": "Token"}}
                    ],
                    "access_hint": {"api": "GitHub", "scopes": ["repo:read"]},
                }
            ],
            endpoints=[
                {
                    "id": "plugin.acme.tracker.issues",
                    "direction": "read",
                    "cache_ttl_seconds": 300,
                    "params": [
                        {
                            "key": "state",
                            "type": "select",
                            "label": {"en": "State"},
                            "options": ["open", "closed"],
                        }
                    ],
                    "requires": {"all_of": ["api"]},
                }
            ],
        ),
        id="static-connection-and-read",
    ),
    pytest.param(
        _manifest(
            features=["pages"],
            vendor={
                "fields": [
                    {"key": "client_id", "type": "string", "label": {"en": "Id"}}
                ]
            },
            connections=[
                {
                    "id": "account",
                    "scope": "interactive",
                    "label": {"en": "Your account"},
                    "fields": [],
                    "flow": {
                        "type": "oauth2",
                        "authorize_url": "https://vendor.test/authorize",
                        "token_url": "https://vendor.test/token",
                        "client_id": "{vendor.client_id}",
                    },
                }
            ],
            pages=[
                {
                    "id": "board",
                    "path": "/page/board",
                    "name": {"en": "Board"},
                    "scopes": ["community", "initiative"],
                    "admin_only": True,
                    "capabilities": ["clipboard-write", "fullscreen"],
                    "requires": {"any_of": ["account"]},
                }
            ],
        ),
        id="interactive-connection-and-page",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {"id": "plugin.acme.tracker.issue-opened", "direction": "emit"},
                {
                    "id": "plugin.acme.tracker.issue-open",
                    "direction": "write",
                    "actors": ["member", "installation"],
                    "params": [
                        {"key": "title", "type": "string", "label": {"en": "T"}}
                    ],
                },
            ],
        ),
        id="every-direction-in-one-block",
    ),
    # The three the platform takes rather than refuses. Each was a real
    # over-strict rule in the first cut of this schema, caught in review: a
    # schema that rejects any of these tells an author their working manifest
    # is broken.
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {
                    "id": "plugin.acme.tracker.s",
                    "direction": "read",
                    "cache_ttl_seconds": 10_000_000,
                }
            ],
        ),
        id="cache-ttl-clamped-not-refused",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[{"id": "plugin.acme.tracker.s", "direction": "read"}],
            some_future_block={"whatever": True},
        ),
        id="unknown-keys-dropped-not-refused",
    ),
    pytest.param(
        _manifest(
            features=["pages"],
            pages=[
                {"id": "e", "path": "/e", "name": {"en": "N" * (MAX_TEXT_LENGTH + 50)}}
            ],
        ),
        id="over-long-label-truncated-not-refused",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            connections=[
                {
                    "id": "api",
                    "scope": "static",
                    "label": {"en": "API"},
                    "fields": [{"key": "t", "type": "secret", "label": {"en": "T"}}],
                }
            ],
            endpoints=[
                {
                    "id": "plugin.acme.tracker.s",
                    "direction": "read",
                    # One operator plus a key from a newer manifest revision.
                    # The platform reads the operator and drops the rest, so a
                    # rule that counted properties would refuse this.
                    "requires": {"all_of": ["api"], "from_a_newer_revision": True},
                }
            ],
        ),
        id="requires-alongside-an-unknown-key",
    ),
    pytest.param(
        _manifest(
            features=["endpoints", "widgets", "dashboards"],
            endpoints=[{"id": "plugin.acme.tracker.s", "direction": "read"}],
            widgets=[
                {
                    "id": "w",
                    "meta": {"name": {"en": "W"}},
                    "module_source": "export default () => ({});",
                    "endpoints": ["plugin.acme.tracker.s"],
                }
            ],
            dashboards=[
                {
                    "uid": "J9H7S9T7GP7FAG",
                    "public_id": "acme.tracker-overview",
                    "name": "Overview",
                    "description": "At a glance.",
                    "layout": {"columns": 12},
                    "widgets": [
                        {
                            "id": "one",
                            # Bare, with no uid: the platform stamps the plug-in's
                            # own on when it publishes.
                            "type": "w",
                            "title": "One",
                            "grid": {"x": 0, "y": 0, "w": 4, "h": 3},
                            "binding": {
                                "endpoint_id": "plugin.acme.tracker.s",
                                "params": {"label": "bug", "limit": 5, "open": True},
                            },
                        }
                    ],
                }
            ],
        ),
        id="a-dashboard-the-plugin-ships-with-itself",
    ),
    pytest.param(
        _manifest(
            features=["endpoints", "widgets", "dashboards"],
            endpoints=[{"id": "plugin.acme.tracker.s", "direction": "read"}],
            widgets=[
                {
                    "id": "w",
                    "meta": {"name": {"en": "W"}},
                    "module_source": "export default () => ({});",
                    "endpoints": ["plugin.acme.tracker.s"],
                }
            ],
            dashboards=[
                {
                    "uid": "J9H7S9T7GP7FAG",
                    "public_id": "acme.tracker-overview",
                    "name": "Overview",
                    # No description, layout, widget id or grid: a publisher who
                    # wants one tile per widget writes almost nothing.
                    "widgets": [
                        {
                            "type": "w",
                            "binding": {"endpoint_id": "plugin.acme.tracker.s"},
                        }
                    ],
                }
            ],
        ),
        id="a-bundled-dashboard-with-only-what-is-required",
    ),
]


@pytest.mark.parametrize("manifest", ACCEPTED)
def test_what_the_platform_accepts_satisfies_the_schema(manifest, validator):
    """The direction that matters most: an author whose manifest installs must
    never be told by the schema that it is malformed."""
    platform_accepts(manifest)
    assert list(validator.iter_errors(manifest)) == []


REFUSED_BY_BOTH = [
    # An endpoint is closed: a term it does not declare, a retired one
    # included, is refused rather than dropped.
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {"id": "plugin.acme.tracker.s", "direction": "read", "retries": 3}
            ],
        ),
        id="endpoint-term-the-contract-does-not-name",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {
                    "id": "plugin.acme.tracker.s",
                    "direction": "read",
                    "visibility": "member",
                }
            ],
        ),
        id="endpoint-naming-a-retired-audience-term",
    ),
    pytest.param(
        {"service": {"public_id": "acme.x"}, "features": []}, id="no-plugin-kind"
    ),
    pytest.param(_manifest(plugin_kind="tool_instance"), id="wrong-plugin-kind"),
    pytest.param(
        _manifest(service={"public_id": "no-dot"}), id="public-id-without-dot"
    ),
    pytest.param(_manifest(service={"public_id": "Acme.Tracker"}), id="uppercase-id"),
    pytest.param(_manifest(features=["telepathy"]), id="unknown-feature"),
    pytest.param(
        _manifest(service={"public_id": "acme.x", "protocol": 99}),
        id="unspoken-protocol",
    ),
    pytest.param(
        _manifest(service={"public_id": "acme.x", "scopes": ["everything:write"]}),
        id="scope-outside-the-vocabulary",
    ),
    pytest.param(
        _manifest(
            service={"public_id": "acme.x", "scopes": ["tags:read", "tags:read"]}
        ),
        id="scope-named-twice",
    ),
    pytest.param(
        _manifest(service={"public_id": "acme.x", "scopes": ["members:write"]}),
        id="write-on-a-read-only-resource",
    ),
    pytest.param(
        _manifest(service={"public_id": "acme.x", "scopes": ["plugins:github"]}),
        id="plugin-scope-without-a-public-id",
    ),
    pytest.param(
        _manifest(service={"public_id": "acme.x", "scopes": ["plugins:Acme.github"]}),
        id="plugin-scope-out-of-charset",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {"id": "plugin.acme.tracker.s", "direction": "read", "public": 1}
            ],
        ),
        id="endpoint-public-not-a-boolean",
    ),
    pytest.param(
        _manifest(
            features=["pages"],
            pages=[{"id": "e", "path": "/e", "name": {"en": "E"}, "admin_only": "yes"}],
        ),
        id="admin-only-not-a-boolean",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {"id": "plugin.acme.tracker.s", "direction": "read", "admin_only": 1}
            ],
        ),
        id="endpoint-admin-only-not-a-boolean",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            # Direction decides who may call it and whether an answer may be
            # cached, so a value outside the closed set is not a nuance the
            # platform could resolve later.
            endpoints=[{"id": "plugin.acme.tracker.s", "direction": "sideways"}],
        ),
        id="direction-outside-the-vocabulary",
    ),
    pytest.param(
        _manifest(features=["endpoints"], endpoints=[{"id": "plugin.acme.tracker.s"}]),
        id="path-climbing-out",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"], endpoints=[{"id": "UPPER", "direction": "read"}]
        ),
        id="identifier-out-of-charset",
    ),
    pytest.param(
        _manifest(
            features=["pages"],
            pages=[
                {
                    "id": "e",
                    "path": "/e",
                    "name": {"en": "E"},
                    "capabilities": ["payment"],
                }
            ],
        ),
        id="capability-not-on-offer",
    ),
    # The two shapes `oneOf` has to keep refusing now that the object no longer
    # counts its properties.
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {
                    "id": "plugin.acme.tracker.s",
                    "direction": "read",
                    "requires": {"all_of": ["a"], "any_of": ["b"]},
                }
            ],
        ),
        id="requires-naming-both-operators",
    ),
    pytest.param(
        _manifest(
            features=["endpoints"],
            endpoints=[
                {"id": "plugin.acme.tracker.s", "direction": "read", "requires": {}}
            ],
        ),
        id="requires-naming-no-operator",
    ),
]


@pytest.mark.parametrize("manifest", REFUSED_BY_BOTH)
def test_what_the_schema_refuses_the_platform_refuses_too(manifest, validator):
    """The other direction, for the rules a schema *can* express: the schema
    must not invent a constraint the platform would have allowed."""
    assert list(validator.iter_errors(manifest)) != [], "schema accepted it"
    with pytest.raises(ValueError):
        platform_accepts(manifest)


@pytest.mark.parametrize(
    "name,why",
    [
        ({"en": "N", "fr": 7}, "a value that is not a string is skipped"),
        ({"en": "N", "not a tag": "x"}, "a key that is not a language tag is skipped"),
        (
            {"en": "N", **{f"x{i}": "y" for i in range(MAX_LOCALES + 5)}},
            "entries past the locale cap are never inspected",
        ),
    ],
)
def test_a_localized_entry_the_platform_ignores_is_not_an_error(name, why, validator):
    """Ignored is not refused. The object stands on its usable entries, so the
    document installs — and a schema that rejected it would be telling an author
    their working manifest is broken."""
    manifest = _manifest(
        features=["pages"],
        pages=[{"id": "e", "path": "/e", "name": name}],
    )
    platform_accepts(manifest)
    assert list(validator.iter_errors(manifest)) == [], why


def test_a_localized_object_with_nothing_usable_is_refused(validator):
    """The one thing that does fail, and the only rule left on the type."""
    manifest = _manifest(
        features=["pages"],
        pages=[{"id": "e", "path": "/e", "name": {}}],
    )
    assert list(validator.iter_errors(manifest)) != []
    with pytest.raises(ValueError):
        platform_accepts(manifest)


# --- where the schema stops -------------------------------------------------


@pytest.mark.parametrize(
    "manifest,why",
    [
        (
            _manifest(features=["endpoints"]),
            "a declared feature with no block behind it",
        ),
        (
            _manifest(
                features=["pages"],
                pages=[
                    {
                        "id": "e",
                        "path": "/e",
                        "name": {"en": "E"},
                        "visibility": "guild_admin",
                    }
                ],
            ),
            "a surface naming the audience term an earlier contract used",
        ),
        (
            _manifest(
                features=["widgets", "endpoints"],
                endpoints=[{"id": "plugin.acme.tracker.known", "direction": "read"}],
                widgets=[
                    {
                        "id": "w",
                        "meta": {"name": {"en": "W"}},
                        "module_source": "export default () => ({})",
                        "endpoints": ["plugin.acme.tracker.absent"],
                    }
                ],
            ),
            "a widget binding a read endpoint that does not exist",
        ),
        (
            _manifest(
                features=["endpoints"],
                endpoints=[{"id": "plugin.someone-else.thing", "direction": "emit"}],
            ),
            "an endpoint namespaced under another plug-in",
        ),
        (
            _manifest(
                features=["endpoints"],
                endpoints=[{"id": "plugin.acme.tracker.known", "direction": "read"}],
                community_summary="plugin.acme.tracker.absent",
            ),
            "a community summary naming an endpoint that does not exist",
        ),
        (
            _manifest(
                features=["endpoints"],
                endpoints=[{"id": "plugin.acme.tracker.told", "direction": "emit"}],
                community_summary="plugin.acme.tracker.told",
            ),
            "a community summary naming an endpoint that is not a read",
        ),
        (
            _manifest(
                features=["endpoints"],
                endpoints=[
                    {
                        "id": "plugin.acme.tracker.standing",
                        "direction": "read",
                        "returns": [{"key": "used", "type": "int", "of": "allowed"}],
                    }
                ],
            ),
            "a return counted against one the endpoint does not return",
        ),
        (
            _manifest(
                features=["endpoints"],
                endpoints=[
                    {
                        "id": "plugin.acme.tracker.standing",
                        "direction": "read",
                        "returns": [
                            {"key": "used", "type": "int", "of": "allowed"},
                            {"key": "allowed", "type": "int", "list": True},
                        ],
                    }
                ],
            ),
            "a return counted against a list, which has no one figure",
        ),
    ],
)
def test_the_platform_enforces_what_the_schema_cannot(manifest, why, validator):
    """Schema-valid is necessary, not sufficient — written down as cases so the
    boundary is a fact about this build rather than a caveat in a docstring."""
    assert list(validator.iter_errors(manifest)) == [], f"schema caught it: {why}"
    with pytest.raises(ValueError):
        platform_accepts(manifest)


def test_a_return_is_not_a_control():
    """A select is a control, and the value behind one is a string — so it is a
    param type and never a return type. The schema must not blur the two."""
    defs = contract.manifest_schema()["$defs"]
    assert "select" in defs["endpointParam"]["properties"]["type"]["enum"]
    assert "select" not in defs["endpointReturn"]["properties"]["type"]["enum"]
    assert "secret" not in defs["endpointReturn"]["properties"]["type"]["enum"]


def test_every_direction_may_describe_itself_and_its_answer():
    """``label`` and ``returns`` sit on the endpoint rather than beside the
    caller-side keys, because an emission has neither caller nor response and
    still needs both — it is the one endpoint chosen without being called."""
    endpoint = contract.manifest_schema()["$defs"]["endpoint"]["properties"]
    for key in ("label", "description", "returns", "group", "needs_subject"):
        assert key in endpoint, key
    # None of them is required: a plug-in that says nothing is still a valid plug-in.
    assert set(contract.manifest_schema()["$defs"]["endpoint"]["required"]) == {
        "id",
        "direction",
    }


def test_a_param_says_what_it_takes_and_not_what_to_draw_for_it():
    """A manifest describes the API. The control a consumer draws is the
    consumer's, written in its own words — so nothing here names one."""
    defs = contract.manifest_schema()["$defs"]
    param = defs["endpointParam"]["properties"]
    assert "list" in param
    for drawn in ("picker", "resource", "source", "constraints"):
        assert drawn not in param, drawn
    # A credential is typed once; there is no list of them.
    assert "list" not in defs["connectionField"]["properties"]


# --- scopes and surfaces ----------------------------------------------------


def test_requested_scopes_are_stored_sorted_and_absent_when_none():
    """Canonical, so re-publishing the same manifest stores the same document;
    and left out when empty, so "does this plug-in ask for anything?" has one
    shape."""
    from app.services.marketplace.service_plugins import (
        normalize_service_plugin_definition,
    )

    cleaned = normalize_service_plugin_definition(
        _manifest(
            service={
                "public_id": "acme.tracker",
                "scopes": ["tags:write", "comments:read", "projects:read"],
            }
        )
    )
    assert cleaned["service"]["scopes"] == [
        "comments:read",
        "projects:read",
        "tags:write",
    ]
    bare = normalize_service_plugin_definition(_manifest())
    assert "scopes" not in bare["service"]


def test_plugin_scopes_are_stored_with_the_rest_and_bounded():
    from app.services.marketplace.service_plugins import (
        MAX_PLUGIN_SCOPES,
        normalize_service_plugin_definition,
    )

    cleaned = normalize_service_plugin_definition(
        _manifest(
            service={
                "public_id": "acme.tracker",
                "scopes": ["projects:read", "plugins:acme.github"],
            }
        )
    )
    assert cleaned["service"]["scopes"] == ["plugins:acme.github", "projects:read"]

    too_many = [f"plugins:acme.plugin{index}" for index in range(MAX_PLUGIN_SCOPES + 1)]
    with pytest.raises(ValueError):
        normalize_service_plugin_definition(
            _manifest(service={"public_id": "acme.tracker", "scopes": too_many})
        )


def test_public_is_stored_only_when_set_and_refused_on_an_emission():
    from app.services.marketplace.service_plugins import (
        normalize_service_plugin_definition,
    )

    def endpoint(**extra):
        return normalize_service_plugin_definition(
            _manifest(
                features=["endpoints"],
                endpoints=[{"id": "plugin.acme.tracker.s", **extra}],
            )
        )["endpoints"][0]

    assert endpoint(direction="write", public=True)["public"] is True
    assert "public" not in endpoint(direction="read")
    assert "public" not in endpoint(direction="read", public=False)
    with pytest.raises(ValueError):
        endpoint(direction="emit", public=True)


def test_admin_only_defaults_to_false_and_is_always_stored():
    from app.services.marketplace.service_plugins import (
        normalize_service_plugin_definition,
    )

    def page(**extra):
        body = _manifest(
            features=["pages"],
            pages=[{"id": "e", "path": "/e", "name": {"en": "E"}, **extra}],
        )
        return normalize_service_plugin_definition(body)["pages"][0]

    assert page()["admin_only"] is False
    assert page(admin_only=True)["admin_only"] is True
    assert "visibility" not in page()


@pytest.mark.parametrize("where", ["page", "endpoint"])
def test_the_retired_audience_term_is_refused_by_name(where):
    """Every other unknown term is dropped and reported; this one narrowed who
    reached something, so it is refused and the author is told why."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    if where == "page":
        body = _manifest(
            features=["pages"],
            pages=[
                {"id": "e", "path": "/e", "name": {"en": "E"}, "visibility": "member"}
            ],
        )
    else:
        body = _manifest(
            features=["endpoints"],
            endpoints=[
                {
                    "id": "plugin.acme.tracker.s",
                    "direction": "read",
                    "visibility": "guild_admin",
                }
            ],
        )
    with pytest.raises(ListingDefinitionError, match="visibility"):
        platform_accepts(body)


def test_an_endpoint_admin_only_defaults_to_false_and_is_always_stored():
    from app.services.marketplace.service_plugins import (
        normalize_service_plugin_definition,
    )

    def endpoint(**extra):
        body = _manifest(
            features=["endpoints"],
            endpoints=[{"id": "plugin.acme.tracker.s", "direction": "read", **extra}],
        )
        return normalize_service_plugin_definition(body)["endpoints"][0]

    assert endpoint()["admin_only"] is False
    assert endpoint(admin_only=True)["admin_only"] is True


def test_an_emission_is_not_admin_only():
    """Nobody reads or calls an emission, so there is nobody to narrow."""
    from app.services.marketplace.manifest_values import ListingDefinitionError

    with pytest.raises(ListingDefinitionError, match="admin_only"):
        platform_accepts(
            _manifest(
                features=["endpoints"],
                endpoints=[
                    {
                        "id": "plugin.acme.tracker.told",
                        "direction": "emit",
                        "admin_only": False,
                    }
                ],
            )
        )


@pytest.mark.parametrize(
    "declared,expected",
    [
        ({}, False),
        ({"admin_only": False}, False),
        ({"admin_only": True}, True),
        (None, False),
    ],
)
def test_is_admin_only_reads_its_flag(declared, expected):
    from app.services.marketplace.service_plugins import is_admin_only

    assert is_admin_only(declared) is expected


@pytest.mark.parametrize(
    "minimum_age",
    [{"gdpr": 16}, {"us": 13}, {"USA": 13}, {"default": 12}, {"default": 22}, {}],
)
def test_a_minimum_age_is_by_country_and_bounded(minimum_age, validator):
    """A region is a country or ``default`` — GDPR is not one age — and an age
    the publisher declared for compliance is refused whole when wrong rather
    than quietly trimmed. The schema and the platform agree on every case."""
    manifest = _manifest(minimum_age=minimum_age)
    assert list(validator.iter_errors(manifest)) != []
    with pytest.raises(ValueError):
        platform_accepts(manifest)


def test_a_minimum_age_is_kept_as_declared(validator):
    manifest = _manifest(minimum_age={"default": 16, "US": 13, "FR": 15})
    assert list(validator.iter_errors(manifest)) == []
    stored = normalize_listing_definition("plugin", manifest)
    assert stored["minimum_age"] == {"default": 16, "US": 13, "FR": 15}


@pytest.mark.parametrize("min_plugin_api", ["4", "4.2.0", "v4.2", "4.x", "", 4.2])
def test_a_min_plugin_api_is_major_minor(min_plugin_api, validator):
    """The oldest contract a plug-in needs is ``MAJOR.MINOR``; anything else is
    refused by the schema and the platform alike."""
    manifest = _manifest(min_plugin_api=min_plugin_api)
    assert list(validator.iter_errors(manifest)) != []
    with pytest.raises(ValueError):
        platform_accepts(manifest)


def test_a_min_plugin_api_is_kept_as_declared(validator):
    manifest = _manifest(min_plugin_api="4.2")
    assert list(validator.iter_errors(manifest)) == []
    stored = normalize_listing_definition("plugin", manifest)
    assert stored["min_plugin_api"] == "4.2"
