"""What a listing may declare, and what it is refused for.

These are pure-function tests: no database, no session, nothing to seed. The
validator is the whole boundary between a manifest someone wrote and a document
this build stores and later hands to a guild, so most of what matters is
expressed as "this is refused, by name" and "what is stored is canonical".

Three properties get the most attention, because they are the ones an
implementation could quietly lose:

* a definition never carries an address — only paths, joined later to a base URL
  the deployment supplies;
* what a manifest *declares* and what it *ships* cannot disagree;
* content this build assigns no meaning to (widget modules, sample rows, the
  automation block) is bounded and stored verbatim, never interpreted.
"""

import pytest

from app.services.marketplace import service_plugins
from app.services.marketplace.definitions import (
    GUILD_INSTALLABLE_PLUGIN_KINDS,
    KIND_AUDIENCE,
    LISTING_AUDIENCES,
    LISTING_KINDS,
    LISTING_SOURCES,
    PLUGIN_KINDS,
    ListingDefinitionError,
    kinds_for_audience,
    normalize_listing_definition,
    normalize_publisher,
    plugin_widget_type,
    published_by_us,
    reserved_prefix_problem,
)
from app.services.marketplace.manifest_values import IDENTIFIER_CHARS
from app.services.marketplace.service_plugins import PAGE_CAPABILITIES


def _label(text: str = "A label") -> dict[str, str]:
    return {"en": text}


#: What an operator supplies for the vendor client, as a manifest declares it.
VENDOR = {
    "label": {"en": "Widget vendor"},
    "fields": [
        {"key": "client_id", "type": "string", "required": True, "label": {"en": "Id"}},
        {"key": "client_secret", "type": "secret", "label": {"en": "Secret"}},
        {"key": "app_slug", "type": "string", "label": {"en": "Slug"}},
    ],
}

#: A flow Initiative runs, naming the vendor's client.
FLOW = {
    "type": "oauth2",
    "authorize_url": "https://vendor.test/oauth/authorize",
    "token_url": "https://vendor.test/oauth/token",
    "client_id": "{vendor.client_id}",
    "client_secret": "{vendor.client_secret}",
    "after_connect": True,
}


def _managed(key: str = "owner") -> dict:
    return {"key": key, "type": "string", "label": _label(), "managed": True}


def _service(**overrides) -> dict:
    """A minimal service plug-in: declares nothing, ships nothing, and is valid.

    A plug-in with no local features is a legitimate install — an integration that
    exists to give an external system a foothold in a guild has nothing to
    render — so the smallest valid manifest is the right starting point.
    """
    definition = {
        "plugin_kind": "service",
        "service": {"public_id": "tests.widget-co", "protocol": 1},
        "features": [],
    }
    definition.update(overrides)
    return definition


def _normalize(**overrides) -> dict:
    return normalize_listing_definition("plugin", _service(**overrides))


class TestAttribution:
    """Every listing states who publishes it, in one required name."""

    @pytest.mark.parametrize(
        ("value", "problem"),
        [
            (None, "publisher is required"),
            ("   ", "publisher"),
            # It is rendered on one line beside the listing; a value carrying
            # its own line breaks is refused rather than displayed however it
            # lands.
            ("Widget Co\nby someone else", "single line"),
        ],
        ids=["no name at all", "a blank name", "a name spanning lines"],
    )
    def test_a_name_that_is_not_one_is_refused(self, value, problem):
        with pytest.raises(ListingDefinitionError, match=problem):
            normalize_publisher(value)

    def test_a_name_is_kept_as_written(self):
        assert normalize_publisher("  Widget Co  ") == "Widget Co"

    def test_an_overlong_name_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="publisher"):
            normalize_publisher("W" * 500)


class TestReservedNamespace:
    """``core.*`` names listings shipped in this repository."""

    def test_a_built_in_may_use_it(self):
        assert reserved_prefix_problem("core.project-health", source="builtin") is None

    @pytest.mark.parametrize("source", sorted(LISTING_SOURCES - {"builtin"}))
    def test_no_other_source_may_claim_it(self, source):
        problem = reserved_prefix_problem("core.impostor", source=source)
        assert problem is not None
        assert "reserved" in problem

    def test_other_namespaces_are_open_to_everyone(self):
        for source in sorted(LISTING_SOURCES):
            assert reserved_prefix_problem("widgetco.thing", source=source) is None

    def test_the_prefix_is_matched_at_the_boundary(self):
        # 'coreutils.x' is somebody else's publisher, not the reserved one.
        assert reserved_prefix_problem("coreutils.x", source="registry") is None


class TestPublishedByUs:
    """Built-ins, and the registry's listings under this project's prefix."""

    @pytest.mark.parametrize(
        ("source", "public_id", "expected"),
        [
            ("builtin", "core.project-health", True),
            ("registry", "beyonders-studio.github", True),
            ("registry", "acme.github", False),
            ("registry", "beyonders-studioco.github", False),
            ("operator", "beyonders-studio.github", False),
            ("local", "beyonders-studio.github", False),
        ],
    )
    def test_who_publishes_it(self, source, public_id, expected):
        assert published_by_us(source, public_id) is expected


class TestPluginKinds:
    def test_service_is_publishable(self):
        assert "service" in PLUGIN_KINDS

    def test_service_is_installable_into_a_guild(self):
        """A service plug-in has somewhere to land now: the registration supplies
        the address and the powers, and the install is the pinned definition
        plus whatever the guild configures against it."""
        assert "service" in GUILD_INSTALLABLE_PLUGIN_KINDS

    def test_installable_kinds_are_declared_kinds(self):
        """The two sets answer different questions — what a listing may declare
        versus what this build can mount — so a kind added to the vocabulary
        ahead of its machinery is refused rather than half-mounted."""
        assert GUILD_INSTALLABLE_PLUGIN_KINDS <= PLUGIN_KINDS

    def test_an_unknown_kind_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown plug-in kind"):
            normalize_listing_definition("plugin", {"plugin_kind": "daemon"})


class TestServiceIdentity:
    def test_a_service_names_itself(self):
        with pytest.raises(ListingDefinitionError, match="service.public_id"):
            normalize_listing_definition(
                "plugin", {"plugin_kind": "service", "service": {}, "features": []}
            )

    def test_the_service_id_is_publisher_scoped(self):
        with pytest.raises(ListingDefinitionError, match="publisher"):
            _normalize(service={"public_id": "noslug"})

    def test_a_protocol_this_build_does_not_speak_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="protocol"):
            _normalize(service={"public_id": "tests.widget-co", "protocol": 99})

    def test_the_protocol_defaults_to_the_one_this_build_speaks(self):
        definition = normalize_listing_definition(
            "plugin",
            {
                "plugin_kind": "service",
                "service": {"public_id": "tests.widget-co"},
                "features": [],
            },
        )
        assert definition["service"]["protocol"] == 1


class TestFeaturesMatchBlocks:
    """A declaration and a manifest body cannot disagree, in either direction."""

    @pytest.mark.parametrize(
        ("feature", "problem"),
        [("widgets", "is declared but"), ("telemetry", "unknown feature")],
        ids=["a feature with no block behind it", "a feature this build has not got"],
    )
    def test_a_declared_feature_the_manifest_cannot_back_is_refused(
        self, feature, problem
    ):
        with pytest.raises(ListingDefinitionError, match=problem):
            _normalize(features=[feature])

    def test_shipping_a_block_without_declaring_it_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="is not declared"):
            _normalize(
                endpoints=[
                    {"id": "plugin.tests.widget-co.thing-happened", "direction": "emit"}
                ],
            )

    def test_an_empty_block_is_not_a_block(self):
        """Empty means absent, the same way for every block.

        A block that is present but empty describes nothing. Storing it would be
        a second shape meaning "none" — and one the feature cross-check could
        read differently from the way it was stored, letting a manifest carry a
        block its own ``features`` never declared.
        """
        definition = _normalize(endpoints=[])
        assert "endpoints" not in definition

        with pytest.raises(ListingDefinitionError, match="is declared but"):
            _normalize(features=["endpoints"], endpoints=[])

    def test_a_plugin_may_offer_no_local_features(self):
        definition = _normalize()
        assert definition["features"] == []
        assert "widgets" not in definition

    def test_features_are_stored_in_a_stable_order(self):
        definition = _normalize(
            features=["endpoints", "pages", "endpoints"],
            endpoints=[
                {"id": "plugin.tests.widget-co.thing-happened", "direction": "emit"}
            ],
            pages=[{"id": "main", "path": "/page", "name": _label()}],
        )
        assert definition["features"] == ["endpoints", "pages"]

    @pytest.mark.parametrize("feature", sorted(service_plugins.FEATURES))
    def test_every_feature_names_a_block(self, feature):
        # The cross-check is only as complete as this map, so a feature added
        # without one would silently stop being checked.
        assert feature in service_plugins.FEATURE_BLOCKS


class TestConnections:
    def test_a_static_connection_needs_something_to_supply(self):
        with pytest.raises(ListingDefinitionError, match="at least one field"):
            _normalize(
                connections=[
                    {"id": "shop", "scope": "static", "label": _label(), "fields": []}
                ]
            )

    def test_an_unknown_scope_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown scope"):
            _normalize(
                connections=[{"id": "shop", "scope": "global", "label": _label()}]
            )

    def test_an_interactive_connection_declares_a_flow(self):
        with pytest.raises(ListingDefinitionError, match="declares a flow"):
            _normalize(
                connections=[
                    {"id": "account", "scope": "interactive", "label": _label()}
                ]
            )

    def test_the_retired_connect_path_is_no_way_in(self):
        """The plug-in no longer runs a flow of its own: a connection naming only
        where the plug-in's page was has no flow, and is refused as one."""
        with pytest.raises(ListingDefinitionError, match="declares a flow"):
            _normalize(
                connections=[
                    {
                        "id": "account",
                        "scope": "interactive",
                        "label": _label(),
                        "connect_path": "/connect",
                    }
                ]
            )

    def test_a_member_flow_is_kept_as_declared(self):
        [connection] = _normalize(
            vendor=VENDOR,
            connections=[
                {
                    "id": "account",
                    "scope": "interactive",
                    "label": _label(),
                    "fields": [_managed("login")],
                    "flow": {**FLOW, "revoke": "hook", "scopes": ["read"]},
                }
            ],
        )["connections"]
        assert connection["flow"] == {
            **FLOW,
            "revoke": "hook",
            "scopes": ["read"],
            "pkce": True,
            "authorize_params": {},
        }
        assert "connect_path" not in connection

    def test_a_guild_credential_may_come_from_a_vendor_flow(self):
        """An admin runs the vendor's install once, for the whole guild.

        The alternative this replaces is an admin retyping an organization's
        name into a text box and hoping it names the same organization somebody
        installed at the vendor. Nothing about that is per-member, so the scope
        stays ``static``; the ``flow`` is how the value arrives.
        """
        [connection] = _normalize(
            vendor=VENDOR,
            connections=[
                {
                    "id": "workspace",
                    "scope": "static",
                    "label": _label(),
                    "flow": {
                        **FLOW,
                        "install_url": (
                            "https://vendor.test/apps/{vendor.app_slug}/install"
                        ),
                    },
                    "fields": [_managed()],
                }
            ],
        )["connections"]
        assert connection["flow"]["install_url"].endswith("/{vendor.app_slug}/install")
        assert connection["fields"][0]["managed"] is True

    def test_a_flow_holds_only_managed_values(self):
        """Its values come from the plug-in's after_connect hook; a typed field
        would be one nobody fills in."""
        with pytest.raises(ListingDefinitionError, match="only managed values"):
            _normalize(
                vendor=VENDOR,
                connections=[
                    {
                        "id": "shop",
                        "scope": "static",
                        "label": _label(),
                        "flow": FLOW,
                        "fields": [
                            {"key": "token", "type": "secret", "label": _label()}
                        ],
                    }
                ],
            )

    def test_managed_values_need_the_hook_that_returns_them(self):
        with pytest.raises(ListingDefinitionError, match="after_connect"):
            _normalize(
                vendor=VENDOR,
                connections=[
                    {
                        "id": "account",
                        "scope": "interactive",
                        "label": _label(),
                        "flow": {**FLOW, "after_connect": False},
                        "fields": [_managed("login")],
                    }
                ],
            )

    def test_a_value_after_the_host_is_filled_in(self):
        """A value in the query of an address with no path is not in its host."""
        [connection] = _normalize(
            vendor=VENDOR,
            connections=[
                {
                    "id": "account",
                    "scope": "interactive",
                    "label": _label(),
                    "flow": {**FLOW, "authorize_url": "https://vendor.test?as={login}"},
                    "fields": [_managed("login")],
                }
            ],
        )["connections"]
        assert connection["flow"]["authorize_url"] == "https://vendor.test?as={login}"

    @pytest.mark.parametrize(
        ("change", "problem"),
        [
            ({"authorize_url": "http://vendor.test/oauth"}, "https address"),
            ({"client_id": "{vendor.nope}"}, "vendor block does not declare"),
            (
                {"token_url": "https://vendor.test/{tenant}/token"},
                "not a field of this connection",
            ),
            ({"token_url": "https://{login}.vendor.test/token"}, "into its host"),
            (
                {"authorize_url": "https://{vendor.app_slug}.vendor.test/oauth"},
                "into its host",
            ),
            ({"revoke": "rfc7009"}, "revoke_url"),
            ({"revoke": "github_grant"}, "revoke_url"),
            ({"revoke": "telegram"}, "unknown revoke"),
            ({"type": "saml"}, "unknown type"),
        ],
        ids=[
            "plain http",
            "an undeclared vendor value",
            "an undeclared field",
            "a field filled into the host",
            "a vendor value filled into the host",
            "rfc7009 with nowhere to post",
            "github_grant with nowhere to send",
            "an unknown revocation",
            "an unknown flow",
        ],
    )
    def test_a_flow_that_cannot_run_is_refused(self, change, problem):
        with pytest.raises(ListingDefinitionError, match=problem):
            _normalize(
                vendor=VENDOR,
                connections=[
                    {
                        "id": "account",
                        "scope": "interactive",
                        "label": _label(),
                        "flow": {**FLOW, **change},
                        "fields": [_managed("login")],
                    }
                ],
            )

    def test_an_install_page_is_a_guild_connection_s(self):
        with pytest.raises(ListingDefinitionError, match="install page"):
            _normalize(
                vendor=VENDOR,
                connections=[
                    {
                        "id": "account",
                        "scope": "interactive",
                        "label": _label(),
                        "flow": {**FLOW, "install_url": "https://vendor.test/i"},
                        "fields": [_managed("login")],
                    }
                ],
            )

    def test_a_minted_token_belongs_to_a_guild_connection(self):
        token = {
            "type": "jwt_bearer",
            "exchange_url": "https://vendor.test/{owner}/token",
            "iss": "{vendor.client_id}",
            "key": "{vendor.client_secret}",
        }
        [connection] = _normalize(
            vendor=VENDOR,
            connections=[
                {
                    "id": "workspace",
                    "scope": "static",
                    "label": _label(),
                    "flow": FLOW,
                    "fields": [_managed()],
                    "token": token,
                }
            ],
        )["connections"]
        assert connection["token"] == {**token, "alg": "RS256", "lifetime": 540}

        with pytest.raises(ListingDefinitionError, match="static connection"):
            _normalize(
                vendor=VENDOR,
                connections=[
                    {
                        "id": "account",
                        "scope": "interactive",
                        "label": _label(),
                        "flow": FLOW,
                        "fields": [_managed()],
                        "token": token,
                    }
                ],
            )

    @pytest.mark.parametrize(
        ("body", "problem"),
        [
            ({"permissions": {"issues": "write"}, "repositories": ["{owner}"]}, None),
            ('{"permissions": connection.owner = "acme" ? {"members": "read"}}', None),
            ({"repositories": ["{repo}"]}, "not a field of this connection"),
            ({"app": "{vendor.nope}"}, "vendor block does not declare"),
            ('{"permissions": {"issues": "write"}', "does not parse"),
            (["{owner}"], "must be an object"),
        ],
        ids=[
            "an object",
            "an expression",
            "an undeclared field",
            "an undeclared vendor value",
            "an expression that does not parse",
            "a list",
        ],
    )
    def test_a_token_s_exchange_body_is_an_object_or_an_expression(self, body, problem):
        token = {
            "type": "jwt_bearer",
            "exchange_url": "https://vendor.test/{owner}/token",
            "exchange_body": body,
            "iss": "{vendor.client_id}",
            "key": "{vendor.client_secret}",
        }
        connections = [
            {
                "id": "workspace",
                "scope": "static",
                "label": _label(),
                "flow": FLOW,
                "fields": [_managed()],
                "token": token,
            }
        ]
        if problem is not None:
            with pytest.raises(ListingDefinitionError, match=problem):
                _normalize(vendor=VENDOR, connections=connections)
            return
        [connection] = _normalize(vendor=VENDOR, connections=connections)["connections"]
        assert connection["token"]["exchange_body"] == body

    @pytest.mark.parametrize(
        ("verify", "route", "problem"),
        [
            ({"secret": "{vendor.nope}"}, {}, "verify.secret"),
            ({"secret": "x{vendor.client_secret}"}, {}, "verify.secret"),
            ({}, {"connection": "account"}, "not a static connection"),
            ({}, {"field": "login"}, "not a field of the connection"),
            ({"header": "X-Sig nature"}, {}, "not allowed"),
        ],
        ids=[
            "an undeclared vendor value",
            "more than one vendor value",
            "a member's connection",
            "an undeclared field",
            "a header name with a space",
        ],
    )
    def test_webhooks_route_by_a_static_field_under_a_vendor_secret(
        self, verify, route, problem
    ):
        webhooks = {
            "verify": {
                "scheme": "hmac_sha256",
                "header": "X-Hub-Signature-256",
                "prefix": "sha256=",
                "encoding": "hex",
                "secret": "{vendor.client_secret}",
            },
            "dedup": "X-GitHub-Delivery",
            "route": {
                "path": "installation.id",
                "connection": "workspace",
                "field": "owner",
            },
        }
        connections = [
            {
                "id": "workspace",
                "scope": "static",
                "label": _label(),
                "flow": FLOW,
                "fields": [_managed()],
            },
            {
                "id": "account",
                "scope": "interactive",
                "label": _label(),
                "flow": FLOW,
                "fields": [_managed("login")],
            },
        ]
        kept = _normalize(vendor=VENDOR, connections=connections, webhooks=webhooks)
        assert kept["webhooks"] == webhooks

        webhooks["verify"].update(verify)
        webhooks["route"].update(route)
        with pytest.raises(ListingDefinitionError, match=problem):
            _normalize(vendor=VENDOR, connections=connections, webhooks=webhooks)

    @staticmethod
    def _shop() -> tuple[list[dict], dict]:
        """A shop an admin types in, which the plug-in checks, signing its
        webhooks with a secret of its own."""
        connections = [
            {
                "id": "shop",
                "scope": "static",
                "label": _label(),
                "fields": [
                    {"key": "url", "type": "url", "label": _label(), "required": True},
                    {"key": "key", "type": "secret", "label": _label()},
                    _managed("store_id"),
                    {**_managed("hook_secret"), "type": "secret"},
                ],
                "after_connect": True,
            },
            {
                "id": "workspace",
                "scope": "static",
                "label": _label(),
                "flow": FLOW,
                "fields": [_managed()],
            },
        ]
        webhooks = {
            "verify": {
                "scheme": "hmac_sha256",
                "header": "X-Shop-Signature",
                "encoding": "base64",
                "secret": "{hook_secret}",
            },
            "dedup": "X-Shop-Delivery",
            "route": {
                "header": "x-shop-store",
                "connection": "shop",
                "field": "store_id",
            },
        }
        return connections, webhooks

    def test_a_typed_connection_the_plugin_checks_signs_its_own_webhooks(self):
        connections, webhooks = self._shop()
        kept = _normalize(vendor=VENDOR, connections=connections, webhooks=webhooks)
        assert kept["connections"][0]["after_connect"] is True
        assert "after_connect" not in kept["connections"][1]
        assert kept["webhooks"]["verify"]["secret"] == "{hook_secret}"

    @pytest.mark.parametrize(
        ("change", "problem"),
        [
            (lambda c, w: w["verify"].update(secret="{key}"), "verify.secret"),
            (lambda c, w: w["verify"].update(secret="{store_id}"), "verify.secret"),
            (lambda c, w: w["verify"].update(secret="{owner}"), "verify.secret"),
            (lambda c, w: c[0].pop("after_connect"), "which it does not call"),
            (lambda c, w: c[1].update(after_connect=True), "a flow names its own"),
            (lambda c, w: c[0].update(after_connect="yes"), "true or false"),
        ],
        ids=[
            "a typed secret",
            "a managed value that is not a secret",
            "another connection's field",
            "managed fields nothing fills",
            "beside a flow",
            "not a boolean",
        ],
    )
    def test_a_connection_secret_comes_from_its_after_connect(self, change, problem):
        connections, webhooks = self._shop()
        change(connections, webhooks)
        with pytest.raises(ListingDefinitionError, match=problem):
            _normalize(vendor=VENDOR, connections=connections, webhooks=webhooks)

    @pytest.mark.parametrize("key", ["access_token", "removed_at", "account_label"])
    def test_a_field_may_not_take_a_reserved_key(self, key: str):
        with pytest.raises(ListingDefinitionError, match="is reserved for"):
            _normalize(
                vendor=VENDOR,
                connections=[
                    {
                        "id": "account",
                        "scope": "interactive",
                        "label": _label(),
                        "flow": FLOW,
                        "fields": [_managed(key)],
                    }
                ],
            )

    def test_a_vendor_block_declares_its_fields(self):
        definition = _normalize(vendor=VENDOR)
        assert definition["vendor"] == {
            "fields": [
                {**field, "required": field.get("required") is True}
                for field in VENDOR["fields"]
            ],
            "label": VENDOR["label"],
        }
        with pytest.raises(ListingDefinitionError, match="vendor field"):
            _normalize(
                vendor={
                    "fields": [{"key": "n", "type": "int", "label": _label()}],
                }
            )

    @pytest.mark.parametrize(
        ("field", "problem"),
        [
            (
                {"key": "token", "type": "certificate", "label": _label()},
                "unknown field type",
            ),
            (
                {"key": "region", "type": "select", "label": _label()},
                "at least one option",
            ),
        ],
        ids=["a type this build has not got", "a menu with nothing on it"],
    )
    def test_a_field_nobody_could_fill_in_is_refused(self, field, problem):
        with pytest.raises(ListingDefinitionError, match=problem):
            _normalize(
                connections=[
                    {
                        "id": "shop",
                        "scope": "static",
                        "label": _label(),
                        "fields": [field],
                    }
                ]
            )

    def test_two_connections_cannot_share_an_id(self):
        connection = {
            "id": "shop",
            "scope": "static",
            "label": _label(),
            "fields": [{"key": "token", "type": "secret", "label": _label()}],
        }
        with pytest.raises(ListingDefinitionError, match="share the id"):
            _normalize(connections=[connection, dict(connection)])

    def test_a_connection_is_stored_canonically(self):
        definition = _normalize(
            connections=[
                {
                    "id": "shop",
                    "scope": "static",
                    "label": _label("Storefront"),
                    "access_hint": {"api": "Storefront API", "scopes": ["read_items"]},
                    "fields": [
                        {
                            "key": "token",
                            "type": "secret",
                            "required": True,
                            "managed": True,
                            "label": _label("Token"),
                        }
                    ],
                    "after_connect": True,
                    "unexpected": "dropped",
                }
            ]
        )
        assert definition["connections"] == [
            {
                "id": "shop",
                "scope": "static",
                "label": {"en": "Storefront"},
                "fields": [
                    {
                        "key": "token",
                        "type": "secret",
                        "required": True,
                        "label": {"en": "Token"},
                        "managed": True,
                    }
                ],
                "after_connect": True,
                "access_hint": {"api": "Storefront API", "scopes": ["read_items"]},
            }
        ]


#: The id the fixtures below read, spelled once. Namespaced under the fixture
#: plug-in's own service id, which is what every endpoint id has to be.
READ_ID = "plugin.tests.widget-co.orders"


def _with_source(**endpoint_overrides) -> dict:
    """A service plug-in with one connection and one read endpoint that needs it."""
    endpoint = {
        "id": READ_ID,
        "direction": "read",
        "requires": {"all_of": ["shop"]},
    }
    endpoint.update(endpoint_overrides)
    return _normalize(
        features=["endpoints"],
        connections=[
            {
                "id": "shop",
                "scope": "static",
                "label": _label(),
                "fields": [{"key": "token", "type": "secret", "label": _label()}],
            }
        ],
        endpoints=[endpoint],
    )


class TestSchedules:
    def test_intervals_from_five_minutes_to_a_day_are_kept(self):
        schedules = [
            {"id": "fast", "every": "5m"},
            {"id": "daily", "every": "24h"},
            {"id": "minutes", "every": "1440m"},
        ]
        assert _normalize(schedules=schedules)["schedules"] == schedules

    @pytest.mark.parametrize(
        ("every", "problem"),
        [
            ("4m", "at least 5m"),
            ("25h", "at most 24h"),
            ("15", "whole number"),
            ("1.5h", "whole number"),
            ("١٥m", "whole number"),
        ],
    )
    def test_an_interval_out_of_bounds_or_shape_is_refused(self, every, problem):
        with pytest.raises(ListingDefinitionError, match=problem):
            _normalize(schedules=[{"id": "sync", "every": every}])

    def test_two_schedules_may_not_share_an_id(self):
        with pytest.raises(ListingDefinitionError, match="share the id"):
            _normalize(
                schedules=[{"id": "sync", "every": "5m"}, {"id": "sync", "every": "1h"}]
            )


class TestRequires:
    def test_an_item_may_only_require_a_connection_that_exists(self):
        with pytest.raises(ListingDefinitionError, match="unknown connection"):
            _with_source(requires={"all_of": ["nope"]})

    def test_one_operator_at_a_time(self):
        with pytest.raises(ListingDefinitionError, match="exactly one"):
            _with_source(requires={"all_of": ["shop"], "any_of": ["shop"]})

    def test_an_empty_expression_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="names no connection"):
            _with_source(requires={"any_of": []})

    def test_omitting_it_means_always_available(self):
        definition = _with_source(requires=None)
        assert "requires" not in definition["endpoints"][0]

    def test_a_repeated_term_is_stored_once(self):
        definition = _with_source(requires={"any_of": ["shop", "shop"]})
        assert definition["endpoints"][0]["requires"] == {"any_of": ["shop"]}


class TestEndpoints:
    def test_an_id_is_namespaced_under_the_plugin(self):
        # Two plug-ins offering `create-issue` would be two different things under
        # one name, and a caller resolving the wrong one would do the wrong
        # thing successfully.
        for value in (
            "orders",
            "plugin.someone.else.orders",
            "plugin.tests.widget-co.",
        ):
            with pytest.raises(ListingDefinitionError, match="must start with"):
                _with_source(id=value)

    def test_a_direction_is_required_and_closed(self):
        # Direction decides who may call it, whether an answer may be cached,
        # and whether a widget may bind it — so an endpoint without one is not a
        # partial declaration, it is an unanswerable question.
        with pytest.raises(ListingDefinitionError, match="direction"):
            _with_source(direction=None)
        with pytest.raises(ListingDefinitionError, match="direction"):
            _with_source(direction="sideways")

    def test_the_retired_audience_term_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="visibility"):
            _with_source(visibility="member")

    def test_a_read_endpoint_stores_no_audience(self):
        endpoint = _with_source()["endpoints"][0]
        assert "visibility" not in endpoint
        assert endpoint["admin_only"] is False

    def test_a_write_endpoint_may_be_admin_only(self):
        endpoint = _with_source(direction="write", admin_only=True)["endpoints"][0]
        assert endpoint["admin_only"] is True

    def test_a_cache_window_is_clamped_rather_than_refused(self):
        definition = _with_source(cache_ttl_seconds=10_000_000)
        ttl = definition["endpoints"][0]["cache_ttl_seconds"]
        assert ttl == service_plugins.MAX_CACHE_TTL_SECONDS

    def test_only_a_read_is_cached(self):
        # A write answers once, so a window means nothing on one.
        with pytest.raises(ListingDefinitionError, match="only a read"):
            _with_source(direction="write", cache_ttl_seconds=60)

    def test_an_emission_carries_nothing_a_caller_would_send(self):
        # Nobody calls it, so there is nothing to send, nothing to cache and
        # nobody to gate. Carrying any of it would describe a call that never
        # happens.
        with pytest.raises(ListingDefinitionError, match="has no requires"):
            _with_source(direction="emit")

    def test_an_actor_list_is_drawn_from_the_closed_set(self):
        with pytest.raises(ListingDefinitionError, match="actors"):
            _with_source(actors=["nobody"])
        with pytest.raises(ListingDefinitionError, match="no actor"):
            _with_source(actors=[])
        assert _with_source(actors=["member", "member"])["endpoints"][0]["actors"] == [
            "member"
        ]

    def test_a_parameter_cannot_be_a_secret(self):
        # A credential is supplied once and held in custody; it is never
        # restated as a query parameter.
        assert "secret" not in service_plugins.PARAM_TYPES
        with pytest.raises(ListingDefinitionError, match="unknown field type"):
            _with_source(params=[{"key": "token", "type": "secret", "label": _label()}])


def _with_widget(**widget_overrides) -> dict:
    widget = {
        "id": "summary",
        "meta": {"name": {"en": "Sales summary"}},
        "module_source": "export const render = () => ({});",
    }
    widget.update(widget_overrides)
    return _normalize(features=["widgets"], widgets=[widget])


class TestWidgets:
    def test_a_widget_names_itself(self):
        with pytest.raises(ListingDefinitionError, match="meta must name"):
            _with_widget(meta={"description": {"en": "no name"}})

    def test_a_widget_ships_a_module(self):
        with pytest.raises(ListingDefinitionError, match="module_source is required"):
            _with_widget(module_source="")

    def test_a_module_larger_than_the_cap_is_refused(self):
        oversized = "x" * (service_plugins.MAX_MODULE_SOURCE_BYTES + 1)
        with pytest.raises(ListingDefinitionError, match="larger than"):
            _with_widget(module_source=oversized)

    def test_a_module_is_stored_exactly_as_published(self):
        """Byte-for-byte: this build measures the module and stores it. What it
        contains is the browser sandbox's business, not this validator's."""
        source = "const render = (d) => ({ kind: 'metric', value: d.length });\n"
        definition = _with_widget(module_source=source)
        assert definition["widgets"][0]["module_source"] == source

    def test_a_widget_may_only_bind_an_endpoint_the_plugin_declares(self):
        with pytest.raises(
            ListingDefinitionError, match="not a declared read endpoint"
        ):
            _with_widget(endpoints=[READ_ID])

    def test_a_widget_may_only_bind_one_that_answers(self):
        # A write and an emission are both real endpoints and neither fills a
        # tile: one changes something and returns, the other is posted
        # somewhere else entirely.
        for direction in ("write", "emit"):
            with pytest.raises(
                ListingDefinitionError, match="not a declared read endpoint"
            ):
                _normalize(
                    features=["endpoints", "widgets"],
                    endpoints=[{"id": READ_ID, "direction": direction}],
                    widgets=[
                        {
                            "id": "summary",
                            "meta": {"name": {"en": "Sales summary"}},
                            "module_source": "export const render = () => ({});",
                            "endpoints": [READ_ID],
                        }
                    ],
                )

    def test_sample_rows_are_kept_only_for_declared_endpoints(self):
        definition = _normalize(
            features=["endpoints", "widgets"],
            endpoints=[{"id": READ_ID, "direction": "read"}],
            widgets=[
                {
                    "id": "summary",
                    "meta": {"name": {"en": "Sales summary"}},
                    "module_source": "export const render = () => ({});",
                    "endpoints": [READ_ID],
                    "sample_data": {
                        READ_ID: {"n": [1]},
                        "elsewhere": {"n": [2]},
                    },
                }
            ],
        )
        assert definition["widgets"][0]["sample_data"] == {READ_ID: {"n": [1]}}

    def test_a_sample_is_what_the_endpoint_would_answer(self):
        """An endpoint answers with its declared returns, so a sample is written
        in them too — the preview reads it the way the proxy reads a live one."""
        with pytest.raises(ListingDefinitionError, match="sample_data for"):
            _normalize(
                features=["endpoints", "widgets"],
                endpoints=[{"id": READ_ID, "direction": "read"}],
                widgets=[
                    {
                        "id": "summary",
                        "meta": {"name": {"en": "Sales summary"}},
                        "module_source": "export const render = () => ({});",
                        "endpoints": [READ_ID],
                        "sample_data": {READ_ID: [{"n": 1}]},
                    }
                ],
            )

    def test_sample_rows_are_size_capped(self):
        with pytest.raises(ListingDefinitionError, match="sample_data"):
            _normalize(
                features=["endpoints", "widgets"],
                endpoints=[{"id": READ_ID, "direction": "read"}],
                widgets=[
                    {
                        "id": "summary",
                        "meta": {"name": {"en": "Sales summary"}},
                        "module_source": "export const render = () => ({});",
                        "endpoints": [READ_ID],
                        "sample_data": {
                            READ_ID: {
                                "blob": "x" * service_plugins.MAX_SAMPLE_DATA_BYTES
                            }
                        },
                    }
                ],
            )

    def test_two_widgets_cannot_share_an_id(self):
        widget = {
            "id": "summary",
            "meta": {"name": {"en": "Sales summary"}},
            "module_source": "export const render = () => ({});",
        }
        with pytest.raises(ListingDefinitionError, match="share the id"):
            _normalize(features=["widgets"], widgets=[widget, dict(widget)])


class TestWidgetTypeNamespacing:
    def test_a_plugin_widget_carries_its_listing(self):
        assert plugin_widget_type("K7M2QX8N4TVB9C", "summary") == (
            "plugin:K7M2QX8N4TVB9C:summary"
        )

    def test_it_cannot_collide_with_a_built_in_type(self):
        from app.services.tenant.dashboard_definition import WIDGET_TYPES

        assert plugin_widget_type("K7M2QX8N4TVB9C", "stat") not in WIDGET_TYPES

    def test_the_separator_is_outside_the_id_alphabet(self):
        # Which is what keeps the three parts separable: no widget id can
        # contain the character that joins them.
        assert ":" not in IDENTIFIER_CHARS

    def test_a_widget_id_is_checked_before_it_is_composed(self):
        with pytest.raises(ListingDefinitionError, match="widget id"):
            plugin_widget_type("K7M2QX8N4TVB9C", "sum:mary")


class TestPages:
    def _page(self, **overrides) -> dict:
        page = {
            "id": "orders",
            "path": "/page/orders",
            "admin_only": True,
            "name": _label("Orders"),
        }
        page.update(overrides)
        return _normalize(features=["pages"], pages=[page])

    def test_a_page_names_itself_for_the_sidebar(self):
        with pytest.raises(ListingDefinitionError, match="label"):
            self._page(name=None)

    def test_a_page_declares_a_path_not_an_address(self):
        with pytest.raises(ListingDefinitionError, match="path"):
            self._page(path="https://widget.test/page/orders")

    def test_a_page_is_stored_canonically(self):
        definition = self._page()
        assert definition["pages"] == [
            {
                "id": "orders",
                "path": "/page/orders",
                "scopes": ["community"],
                "admin_only": True,
                "name": {"en": "Orders"},
            }
        ]


class TestWhatASurfaceMayAskItsFrameFor:
    """``capabilities`` is the whole of what a frame is granted.

    A manifest names browser features from a closed vocabulary, and a surface
    that names none is stored with no such key — which is what every definition
    pinned before this existed says, and what their frames now get.
    """

    def _page(self, **overrides) -> dict:
        page = {"id": "board", "path": "/page", "name": _label("Board")}
        page.update(overrides)
        return _normalize(features=["pages"], pages=[page])["pages"][0]

    def test_a_surface_asking_for_nothing_stores_nothing(self):
        assert "capabilities" not in self._page()

    def test_a_surface_may_ask_for_what_it_needs(self):
        assert self._page(capabilities=["clipboard-write"])["capabilities"] == [
            "clipboard-write"
        ]

    def test_capabilities_are_stored_canonically(self):
        """Sorted and de-duplicated, so re-publishing the same manifest produces
        the same document."""
        asked = ["fullscreen", "clipboard-write", "fullscreen"]
        assert self._page(capabilities=asked)["capabilities"] == [
            "clipboard-write",
            "fullscreen",
        ]

    def test_a_capability_outside_the_vocabulary_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="not a capability"):
            self._page(capabilities=["midi"])

    @pytest.mark.parametrize(
        "entry", [{"camera": True}, ["camera"], 7, None, True], ids=repr
    )
    def test_an_entry_that_is_not_a_name_is_refused(self, entry):
        """A publisher gets the same validation error for any entry that is not
        one of the names. Set membership is defined only for a hashable value,
        so an entry is typed before it is looked up rather than after."""
        with pytest.raises(ListingDefinitionError, match="not a capability"):
            self._page(capabilities=[entry])

    def test_payment_is_not_namable(self):
        """The platform takes payment on its own screens, so a plug-in's page
        has no reading of this to request."""
        assert "payment" not in PAGE_CAPABILITIES
        with pytest.raises(ListingDefinitionError, match="not a capability"):
            self._page(capabilities=["payment"])


class TestWhereASurfaceRenders:
    """``scopes`` is not a choice between the two — it is a list.

    A surface may ask for the guild-wide entry, an entry in each initiative, or
    both; both is the interesting case, because it is one page reached from two
    places rather than two surfaces to keep in step.
    """

    def _page(self, **overrides) -> dict:
        page = {"id": "board", "path": "/page", "name": _label("Board")}
        page.update(overrides)
        return _normalize(features=["pages"], pages=[page])["pages"][0]

    def test_saying_nothing_keeps_the_placement_pages_already_had(self):
        assert self._page()["scopes"] == ["community"]

    def test_a_surface_may_render_in_both(self):
        assert self._page(scopes=["initiative", "community"])["scopes"] == [
            "community",
            "initiative",
        ]

    def test_a_surface_may_render_only_inside_initiatives(self):
        assert self._page(scopes=["initiative"])["scopes"] == ["initiative"]

    def test_an_unknown_scope_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="unknown scope"):
            self._page(scopes=["project"])

    def test_nowhere_to_render_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="nowhere to render"):
            self._page(scopes=[])

    def test_a_repeated_scope_is_stored_once(self):
        assert self._page(scopes=["community", "community"])["scopes"] == ["community"]


class TestAdminOnlySurfaces:
    """``admin_only`` is the one audience a manifest may still name.

    Who else opens a surface is the community's to choose, per initiative and
    role, so the manifest says only whether a surface is for admins alone.
    """

    def _page(self, **overrides) -> dict:
        page = {
            "id": "board",
            "path": "/page",
            "name": _label("Board"),
            "scopes": ["initiative"],
        }
        page.update(overrides)
        return _normalize(features=["pages"], pages=[page])["pages"][0]

    def test_saying_nothing_is_not_admin_only(self):
        assert self._page()["admin_only"] is False

    @pytest.mark.parametrize(
        "scopes", [["community"], ["initiative"], ["community", "initiative"]]
    )
    def test_any_surface_may_be_admin_only(self, scopes):
        assert self._page(scopes=scopes, admin_only=True)["admin_only"] is True

    @pytest.mark.parametrize("value", ["true", 1, None, []])
    def test_anything_but_a_boolean_is_refused(self, value):
        if value is None:
            # Absent and null read the same: the default.
            assert self._page(admin_only=value)["admin_only"] is False
            return
        with pytest.raises(ListingDefinitionError, match="admin_only"):
            self._page(admin_only=value)

    def test_the_retired_audience_term_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="visibility"):
            self._page(visibility="initiative_manager")


class TestEmissions:
    def _emit(self, **overrides) -> dict:
        endpoint = {"id": "plugin.tests.widget-co.order-created", "direction": "emit"}
        endpoint.update(overrides)
        return _normalize(features=["endpoints"], endpoints=[endpoint])

    def test_an_id_is_namespaced_under_the_plugin(self):
        for value in ("order_created", "plugin.someone.else.order_created"):
            with pytest.raises(ListingDefinitionError, match="must start with"):
                self._emit(id=value)

    def test_the_namespace_alone_is_not_an_id(self):
        with pytest.raises(ListingDefinitionError, match="must start with"):
            self._emit(id="plugin.tests.widget-co.")

    def test_a_declared_one_is_kept(self):
        definition = self._emit()
        assert definition["endpoints"] == [
            {"id": "plugin.tests.widget-co.order-created", "direction": "emit"}
        ]

    def test_two_of_the_same_id_are_refused(self):
        # One id, two answers, and which one a caller reaches would depend on
        # iteration order.
        with pytest.raises(ListingDefinitionError, match="share the id"):
            _normalize(
                features=["endpoints"],
                endpoints=[
                    {"id": "plugin.tests.widget-co.order-created", "direction": "emit"},
                    {"id": "plugin.tests.widget-co.order-created", "direction": "read"},
                ],
            )


#: The write an action runs, spelled once.
WRITE_ID = "plugin.tests.widget-co.create-link"


def _nested(depth: int) -> dict:
    """A field node inside sections, ``depth`` nodes deep."""
    node: dict = {"type": "field", "props": {"field": "demo.link"}}
    for _ in range(depth - 1):
        node = {"type": "section", "children": [node]}
    return node


#: A field's state facet, with one key.
FACET = {"name": _label("Status"), "values": {"open": {"label": _label("Open")}}}


def _items(change=None) -> dict:
    """A plug-in with a field, an action and a part on tasks, and the write the
    action runs. ``change`` edits the manifest before it is published."""
    body = _service(
        features=["endpoints", "fields", "parts", "actions"],
        endpoints=[
            {"id": WRITE_ID, "direction": "write"},
            {"id": READ_ID, "direction": "read"},
        ],
        fields=[
            {"key": "demo.link", "name": _label("Demo"), "kind": "link", "on": ["task"]}
        ],
        actions=[
            {
                "id": "new-link",
                "name": _label("New link"),
                "endpoint": WRITE_ID,
                "on": ["task"],
            }
        ],
        parts=[
            {
                "id": "demo",
                "name": _label("Demo"),
                "on": ["task"],
                "tree": {
                    "type": "section",
                    "children": [
                        {"type": "field", "props": {"field": "demo.link"}},
                        {"type": "button", "props": {"action": "new-link"}},
                    ],
                },
            }
        ],
    )
    if change is not None:
        change(body)
    return normalize_listing_definition("plugin", body)


class TestFieldsPartsAndActions:
    """What a plug-in adds to items, re-checked as the SDK's validator checks
    it: each declared once, every part a tree Initiative can draw on every kind
    it is offered on, and every action a write."""

    def test_they_are_stored_canonically(self):
        definition = _items(
            lambda b: b["fields"][0].update(
                on=["task", "post"],
                list=True,
                states={
                    "status": {
                        **FACET,
                        "values": {
                            "open": {"label": _label("Open"), "tone": "positive"},
                            "shut": {"label": _label("Shut"), "colour": "red"},
                        },
                    }
                },
            )
        )
        assert definition["fields"] == [
            {
                "key": "demo.link",
                "name": {"en": "Demo"},
                "kind": "link",
                "on": ["post", "task"],
                "list": True,
                "states": {
                    "status": {
                        "name": {"en": "Status"},
                        "values": {
                            "open": {"label": {"en": "Open"}, "tone": "positive"},
                            "shut": {"label": {"en": "Shut"}},
                        },
                    }
                },
            }
        ]
        # Stored only when it is a list.
        assert (
            "list"
            not in _items(lambda b: b["fields"][0].update(list=False))["fields"][0]
        )
        assert definition["actions"] == [
            {
                "id": "new-link",
                "name": {"en": "New link"},
                "endpoint": WRITE_ID,
                "on": ["task"],
                "menu": False,
            }
        ]
        assert definition["parts"] == [
            {
                "id": "demo",
                "name": {"en": "Demo"},
                "on": ["task"],
                "tree": {
                    "type": "section",
                    "children": [
                        {"type": "field", "props": {"field": "demo.link"}},
                        {"type": "button", "props": {"action": "new-link"}},
                    ],
                },
            }
        ]

    def test_an_action_asks_the_reader_for_what_its_endpoint_requires(self):
        """A parameter the endpoint requires is sent once the action asks the
        reader for it."""

        def asking(body: dict) -> None:
            body["endpoints"][0]["params"] = [
                {"key": "x", "type": "string", "label": _label(), "required": True},
                {"key": "y", "type": "int", "label": _label()},
            ]
            body["actions"][0]["params"] = ["y", "x"]

        assert _items(asking)["actions"][0]["params"] == ["y", "x"]

    def test_a_tree_at_its_bounds_is_kept(self):
        widest = {
            "type": "section",
            "children": [
                {"type": "value", "props": {"field": "demo.link"}}
                for _ in range(service_plugins.MAX_PART_NODES - 1)
            ],
        }
        for tree in (widest, _nested(service_plugins.MAX_PART_DEPTH)):
            items = _items(lambda b, tree=tree: b["parts"][0].update(tree=tree))
            assert items["parts"][0]["tree"] == tree

    @pytest.mark.parametrize(
        ("change", "problem"),
        [
            (lambda b: b["fields"].append(b["fields"][0]), "two fields share the key"),
            (lambda b: b["parts"].append(b["parts"][0]), "two parts share the id"),
            (
                lambda b: b["actions"].append(b["actions"][0]),
                "two actions share the id",
            ),
            (lambda b: b["fields"][0].update(key="Demo"), "lowercase letter"),
            (lambda b: b["fields"][0].update(key="1demo"), "lowercase letter"),
            (lambda b: b["fields"][0].update(kind="colour"), "kind must be one of"),
            (lambda b: b["fields"][0].update(on=["wiki_page"]), "not an item kind"),
            (lambda b: b["fields"][0].update(on=[]), "names no item kind"),
            (lambda b: b["fields"][0].update(list="yes"), "true or false"),
            (
                lambda b: b["fields"][0].update(
                    states={
                        f"f{index}": FACET
                        for index in range(service_plugins.MAX_FACETS + 1)
                    }
                ),
                f"more than {service_plugins.MAX_FACETS} facets",
            ),
            (
                lambda b: b["fields"][0].update(
                    states={
                        "status": {
                            **FACET,
                            "values": {
                                f"k{index}": {"label": _label()}
                                for index in range(service_plugins.MAX_FACET_VALUES + 1)
                            },
                        }
                    }
                ),
                f"more than {service_plugins.MAX_FACET_VALUES} keys",
            ),
            (
                lambda b: b["fields"][0].update(
                    states={"status": {**FACET, "values": {"open": {}}}}
                ),
                "must carry a label",
            ),
            (
                lambda b: b["fields"][0].update(
                    states={
                        "status": {
                            **FACET,
                            "values": {"open": {"label": _label(), "tone": "loud"}},
                        }
                    }
                ),
                "tone must be one of",
            ),
            (lambda b: b["actions"][0].update(on=["task", "task"]), "twice"),
            (lambda b: b["actions"][0].update(endpoint=READ_ID), "a read endpoint"),
            (
                lambda b: b["endpoints"][0].update(
                    params=[
                        {
                            "key": "x",
                            "type": "string",
                            "label": _label(),
                            "required": True,
                        }
                    ]
                ),
                "requires 'x', which the action does not ask the reader for",
            ),
            (
                lambda b: b["actions"][0].update(
                    endpoint="plugin.tests.widget-co.missing"
                ),
                "does not declare",
            ),
            (lambda b: b["actions"][0].update(menu="yes"), "true or false"),
            (
                lambda b: b["actions"][0].update(params=["colour"]),
                "'colour' is not a parameter of",
            ),
            (
                lambda b: b.update(
                    settings=[
                        {
                            "key": "prefix",
                            "type": "string",
                            "label": _label(),
                            "assigned": "community_name",
                        }
                    ]
                ),
                "only a unique setting's value is assigned",
            ),
            (
                lambda b: b.update(
                    help={"en": "x" * (service_plugins.MAX_HELP_LENGTH + 1)}
                ),
                "help in 'en' is longer than",
            ),
            (
                lambda b: b["parts"][0].update(tree={"type": "image"}),
                "type must be one of",
            ),
            (
                lambda b: b["parts"][0]["tree"].update(style="bold"),
                "not a term of the contract",
            ),
            (
                lambda b: b["parts"][0]["tree"].update(props={"colour": "red"}),
                "not a prop of a section",
            ),
            (
                lambda b: b["parts"][0].update(
                    tree={"type": "stack", "props": {"direction": "diagonal"}}
                ),
                "direction must be one of",
            ),
            (
                lambda b: b["parts"][0].update(
                    tree={"type": "text", "props": {"text": _label(), "tone": "loud"}}
                ),
                "tone must be one of",
            ),
            (
                lambda b: b["parts"][0].update(
                    tree={"type": "value", "props": {"field": "demo.other"}}
                ),
                "not one of this manifest's fields",
            ),
            (
                lambda b: b["parts"][0].update(
                    tree={"type": "button", "props": {"action": "other"}}
                ),
                "not one of this manifest's actions",
            ),
            (
                lambda b: b["parts"][0].update(on=["post", "task"]),
                "'demo.link' is not offered on post",
            ),
            (
                lambda b: (
                    b["fields"][0].update(on=["post", "task"]),
                    b["parts"][0].update(on=["post", "task"]),
                ),
                "'new-link' is not offered on post",
            ),
            (
                lambda b: b["parts"][0].update(
                    tree=_nested(service_plugins.MAX_PART_DEPTH + 1)
                ),
                "nested deeper than",
            ),
            (
                lambda b: b["parts"][0]["tree"].update(
                    children=[
                        {"type": "value", "props": {"field": "demo.link"}}
                        for _ in range(service_plugins.MAX_PART_NODES)
                    ]
                ),
                f"more than {service_plugins.MAX_PART_NODES} nodes",
            ),
            (
                lambda b: b.update(
                    fields=[
                        {
                            "key": f"k{index}",
                            "name": _label(),
                            "kind": "text",
                            "on": ["task"],
                        }
                        for index in range(service_plugins.MAX_FIELDS + 1)
                    ]
                ),
                "holds more than",
            ),
            (
                lambda b: b.update(features=["endpoints", "fields", "actions"]),
                "parts is present",
            ),
        ],
        ids=[
            "field-twice",
            "part-twice",
            "action-twice",
            "key-not-lowercase",
            "key-not-letter-first",
            "unknown-field-kind",
            "unknown-item-kind",
            "offered-nowhere",
            "list-not-a-boolean",
            "too-many-facets",
            "too-many-state-keys",
            "state-key-without-a-label",
            "unknown-state-tone",
            "item-kind-twice",
            "action-runs-a-read",
            "action-runs-a-write-needing-params",
            "action-runs-nothing-declared",
            "menu-not-a-boolean",
            "action-asks-for-what-its-endpoint-does-not-take",
            "assigned-setting-not-unique",
            "help-too-long",
            "unknown-component",
            "unknown-node-term",
            "unknown-prop",
            "unknown-direction",
            "unknown-tone",
            "node-names-no-field",
            "node-names-no-action",
            "field-not-where-the-part-is",
            "action-not-where-the-part-is",
            "too-deep",
            "too-many-nodes",
            "too-many-fields",
            "block-without-its-feature",
        ],
    )
    def test_what_the_sdk_refuses_is_refused_here(self, change, problem):
        with pytest.raises(ListingDefinitionError, match=problem):
            _items(change)


class TestCanonicalShape:
    def test_unknown_keys_are_dropped(self):
        definition = _normalize(
            default_name="Widget Co",
            surprise="dropped",
            base_url="https://widget.test",
        )
        assert set(definition) == {
            "plugin_kind",
            "service",
            "features",
            "default_name",
        }

    def test_a_definition_holds_no_address_of_the_plugin(self):
        """The governing rule, asserted on a manifest that tries: a plug-in says
        which route, and the deployment's registration says where. The one kind
        of address it may hold is its vendor's, in a flow Initiative runs."""
        definition = _normalize(
            features=["endpoints", "pages"],
            service={
                "public_id": "tests.widget-co",
                "protocol": 1,
                "default_url": "http://widget.test:8100",
            },
            connections=[
                {
                    "id": "shop",
                    "scope": "interactive",
                    "label": _label(),
                    "flow": {**FLOW, "after_connect": False},
                }
            ],
            vendor=VENDOR,
            endpoints=[{"id": READ_ID, "direction": "read"}],
            pages=[
                {
                    "id": "orders",
                    "path": "/page/orders",
                    "name": _label(),
                    "url": "https://widget.test/page/orders",
                }
            ],
        )
        rendered = repr(definition)
        assert "http://" not in rendered
        assert "widget.test" not in rendered
        assert "default_url" not in definition["service"]

    def test_the_whole_document_is_size_capped(self):
        # Each widget is under the per-module cap; together they are not.
        module = "x" * (service_plugins.MAX_MODULE_SOURCE_BYTES - 1)
        widgets = [
            {
                "id": f"w{index}",
                "meta": {"name": {"en": f"Widget {index}"}},
                "module_source": module,
            }
            for index in range(service_plugins.MAX_WIDGETS)
        ]
        with pytest.raises(ListingDefinitionError, match="service plug-in definition"):
            _normalize(features=["widgets"], widgets=widgets)

    def test_a_block_longer_than_its_cap_is_refused_not_truncated(self):
        with pytest.raises(ListingDefinitionError, match="more than"):
            _normalize(
                features=["pages"],
                pages=[
                    {"id": f"e{index}", "path": f"/page/{index}", "name": _label()}
                    for index in range(service_plugins.MAX_PAGES + 1)
                ],
            )


class TestWhatAnEndpointSaysItIs:
    """The half a consumer reads before it ever makes a call.

    A widget binds a column and an automation offers a value for a later step,
    and both have to be arrangeable — and refusable — before the endpoint has
    run once. None of it means anything to THIS build, which is the point:
    these are bounded and stored, never interpreted.
    """

    def test_a_label_and_description_are_kept(self):
        cleaned = _with_source(
            label=_label("Open issues"), description=_label("Everything still open")
        )
        endpoint = cleaned["endpoints"][0]
        assert endpoint["label"] == _label("Open issues")
        assert endpoint["description"] == _label("Everything still open")

    def test_an_emission_may_be_labelled_too(self):
        """The one endpoint chosen from a list without ever being called, so it
        needs a name more than the others do — and the branch that strips
        everything else from an emission must let it through."""
        cleaned = _normalize(
            features=["endpoints"],
            endpoints=[
                {
                    "id": "plugin.tests.widget-co.order-created",
                    "direction": "emit",
                    "label": _label("An order is placed"),
                    "returns": [{"key": "order_id", "type": "int"}],
                    "group": "orders",
                }
            ],
        )
        endpoint = cleaned["endpoints"][0]
        assert endpoint["label"] == _label("An order is placed")
        assert endpoint["returns"] == [{"key": "order_id", "type": "int"}]
        assert endpoint["group"] == "orders"

    def test_an_emission_still_has_no_caller_side(self):
        with pytest.raises(ListingDefinitionError, match="no params"):
            _normalize(
                features=["endpoints"],
                endpoints=[
                    {
                        "id": "plugin.tests.widget-co.order-created",
                        "direction": "emit",
                        "label": _label("An order is placed"),
                        "params": [{"key": "x", "type": "string", "label": _label()}],
                    }
                ],
            )

    def test_saying_nothing_stores_nothing(self):
        """An absent label is absent, not an empty one — the same rule every
        other optional block here follows."""
        endpoint = _with_source()["endpoints"][0]
        for key in ("label", "description", "returns", "group", "needs_subject"):
            assert key not in endpoint


class TestReturns:
    def test_a_return_carries_a_key_a_type_and_optionally_a_label(self):
        cleaned = _with_source(
            returns=[
                {"key": "count", "type": "int", "label": _label("How many")},
                {"key": "url", "type": "url"},
            ]
        )
        assert cleaned["endpoints"][0]["returns"] == [
            {"key": "count", "type": "int", "label": _label("How many")},
            {"key": "url", "type": "url"},
        ]

    def test_several_values_are_flagged_rather_than_typed_apart(self):
        cleaned = _with_source(
            returns=[{"key": "labels", "type": "string", "list": True}]
        )
        assert cleaned["endpoints"][0]["returns"][0]["list"] is True

    def test_select_is_not_a_return_type(self):
        """A select is a CONTROL, and the value behind one is a string."""
        with pytest.raises(ListingDefinitionError, match="unknown type"):
            _with_source(returns=[{"key": "k", "type": "select"}])

    def test_a_credential_is_not_a_return_type_either(self):
        with pytest.raises(ListingDefinitionError, match="unknown type"):
            _with_source(returns=[{"key": "k", "type": "secret"}])

    def test_two_returns_may_not_share_a_key(self):
        with pytest.raises(ListingDefinitionError, match="share the key"):
            _with_source(
                returns=[{"key": "k", "type": "int"}, {"key": "k", "type": "string"}]
            )

    def test_a_return_needs_a_readable_key(self):
        with pytest.raises(ListingDefinitionError):
            _with_source(returns=[{"key": "Not An Id", "type": "int"}])


class TestWhatAParameterTakes:
    """A manifest describes the API, not the control a consumer draws for it.

    ``picker`` named one of an automation editor's own controls inside a third
    party's manifest, so a plug-in could only ask for something that editor had
    already thought of — and a consumer that writes its own step needs no term
    here at all. What survives is what a caller cannot infer: whether to send
    one value or an array.
    """

    def test_a_param_may_take_several_values(self):
        cleaned = _with_source(
            params=[{"key": "ids", "type": "int", "label": _label(), "list": True}]
        )
        assert cleaned["endpoints"][0]["params"][0]["list"] is True

    def test_one_value_is_the_default(self):
        cleaned = _with_source(params=[{"key": "id", "type": "int", "label": _label()}])
        assert "list" not in cleaned["endpoints"][0]["params"][0]

    def test_a_connection_field_takes_one_credential(self):
        """An admin types a credential once; there is no list of them."""
        cleaned = _normalize(
            features=["endpoints"],
            connections=[
                {
                    "id": "shop",
                    "scope": "static",
                    "label": _label(),
                    "fields": [
                        {
                            "key": "token",
                            "type": "secret",
                            "label": _label(),
                            "list": True,
                        }
                    ],
                }
            ],
            endpoints=[{"id": READ_ID, "direction": "read"}],
        )
        assert "list" not in cleaned["connections"][0]["fields"][0]


LOOKUP_ID = "plugin.tests.widget-co.boards"


def _with_option_source(source: dict, *, siblings: list | None = None) -> dict:
    """A read whose parameter draws its values from a second read."""
    return _normalize(
        features=["endpoints"],
        endpoints=[
            {
                "id": LOOKUP_ID,
                "direction": "read",
                "returns": [
                    {"key": "ids", "type": "string", "list": True},
                    {"key": "names", "type": "string", "list": True},
                    {"key": "total", "type": "int"},
                ],
                "params": [{"key": "owner", "type": "string", "label": _label()}],
            },
            {
                "id": READ_ID,
                "direction": "read",
                "params": (siblings or [])
                + [
                    {
                        "key": "board",
                        "type": "string",
                        "label": _label(),
                        "options_from": source,
                    }
                ],
            },
        ],
    )


class TestWhereAParametersValuesComeFrom:
    """Values a manifest cannot list because only the plug-in can enumerate them.

    A repository, a channel, a board: the set differs per install and changes
    after it, so a parameter names the read that answers instead of carrying the
    answers. Every part of that reference is checked here, where every endpoint
    is known — a source that resolves to nothing fails silently at the far end,
    in a form that draws an empty menu.
    """

    def test_a_source_survives_a_publish_whole(self):
        cleaned = _with_option_source(
            {
                "endpoint": LOOKUP_ID,
                "key": "ids",
                "label_key": "names",
                "needs": {"owner": "org"},
            },
            siblings=[{"key": "org", "type": "string", "label": _label()}],
        )
        board = cleaned["endpoints"][1]["params"][1]
        assert board["options_from"] == {
            "endpoint": LOOKUP_ID,
            "key": "ids",
            "label_key": "names",
            "needs": {"owner": "org"},
        }

    def test_it_may_name_a_source_it_sends_nothing_to(self):
        cleaned = _with_option_source({"endpoint": LOOKUP_ID, "key": "ids"})
        assert "needs" not in cleaned["endpoints"][1]["params"][0]["options_from"]

    def test_an_endpoint_from_another_plugin_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="not declared here"):
            _with_option_source({"endpoint": "plugin.other.co.boards", "key": "ids"})

    def test_a_write_cannot_fill_in_a_form(self):
        with pytest.raises(ListingDefinitionError, match="does not read"):
            _normalize(
                features=["endpoints"],
                endpoints=[
                    {"id": LOOKUP_ID, "direction": "write"},
                    {
                        "id": READ_ID,
                        "direction": "read",
                        "params": [
                            {
                                "key": "board",
                                "type": "string",
                                "label": _label(),
                                "options_from": {"endpoint": LOOKUP_ID, "key": "ids"},
                            }
                        ],
                    },
                ],
            )

    @pytest.mark.parametrize(
        ("key", "problem"),
        [("nope", "is not returned by"), ("total", "is a single value")],
        ids=["a key the source does not return", "a key that is one value"],
    )
    def test_a_menu_must_name_a_list_the_source_returns(self, key, problem):
        with pytest.raises(ListingDefinitionError, match=problem):
            _with_option_source({"endpoint": LOOKUP_ID, "key": key})

    def test_it_can_only_send_a_parameter_the_source_takes(self):
        with pytest.raises(ListingDefinitionError, match="does not take"):
            _with_option_source(
                {"endpoint": LOOKUP_ID, "key": "ids", "needs": {"nope": "org"}},
                siblings=[{"key": "org", "type": "string", "label": _label()}],
            )

    def test_it_cannot_ask_for_the_answer_being_filled_in(self):
        with pytest.raises(ListingDefinitionError, match="being filled in"):
            _with_option_source(
                {"endpoint": LOOKUP_ID, "key": "ids", "needs": {"owner": "board"}}
            )

    def test_a_sibling_this_endpoint_does_not_declare_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="does not declare"):
            _with_option_source(
                {"endpoint": LOOKUP_ID, "key": "ids", "needs": {"owner": "org"}}
            )


class TestListingAudience:
    """Who a listing installs to, and what follows from it."""

    def test_every_audience_a_kind_names_is_one_of_the_two(self):
        # Which kinds have an audience at all is asserted in
        # ``app/core/registry_coverage_test.py``, beside every other registry
        # that has to span its vocabulary.
        assert set(KIND_AUDIENCE.values()) <= LISTING_AUDIENCES

    def test_the_two_shelves_do_not_overlap(self):
        guild = kinds_for_audience("guild")
        user = kinds_for_audience("user")
        assert not guild & user
        assert guild | user == LISTING_KINDS

    def test_a_profile_pack_and_a_home_layout_install_to_a_person(self):
        assert kinds_for_audience("user") == {"profile_pack", "home_layout"}

    def test_an_unknown_audience_is_named_rather_than_empty(self):
        with pytest.raises(ValueError):
            kinds_for_audience("initiative")


class TestAPacksOwnArt:
    DIGEST = "b" * 64

    def _pack(self, **decoration) -> dict:
        return {
            "schema_version": 1,
            "kind": "profile_pack",
            "decorations": [
                {"id": "acme.star", "slot": "banner", "name": "Star", **decoration}
            ],
        }

    def test_a_decoration_may_name_its_picture_in_the_marketplace(self):
        from app.services.marketplace.media import media_path

        stored = normalize_listing_definition(
            "profile_pack", self._pack(image=media_path(self.DIGEST))
        )
        assert stored["decorations"][0]["image"] == media_path(self.DIGEST)

    def test_a_picture_from_anywhere_else_is_refused(self):
        with pytest.raises(ListingDefinitionError, match="image"):
            normalize_listing_definition(
                "profile_pack", self._pack(image="https://example.invalid/star.png")
            )

    def test_a_pack_without_art_keeps_the_shape_it_was_published_in(self):
        stored = normalize_listing_definition("profile_pack", self._pack())
        assert "image" not in stored["decorations"][0]
