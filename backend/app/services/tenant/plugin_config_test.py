"""Holding what a guild typed into a plug-in's connection form.

The load-bearing property is custody: a secret goes in, is stored encrypted, and
the only thing that ever comes back out through a read is *whether* it is there.
So the tests assert on both halves — that the value round-trips for the one
caller entitled to it, and that the presence map carries no trace of it.

The rest is validation against the *pinned* definition. Types are checked
exactly rather than coerced, because a form that turns ``true`` into ``1`` for
an int field has silently accepted something the plug-in never declared it would
receive.
"""

import pytest

from app.core.encryption import SALT_PLUGIN_CONFIG, decrypt_field
from app.core.messages import GuildPluginMessages
from app.services.tenant.plugin_config import (
    MAX_SECRET_VALUE_LENGTH,
    PluginConfigError,
    apply_connection_values,
    connection_id_for_ref,
    decrypt_connection_secrets,
    guild_connection_ref,
    has_value_map,
    is_satisfied,
    needs_configuration,
    prune_to_definition,
    runs_vendor_flow,
)


def _field(key: str, field_type: str, **extra) -> dict:
    return {"key": key, "type": field_type, "label": {"en": key}, **extra}


ADMIN_CONNECTION = {
    "id": "admin",
    "scope": "static",
    "label": {"en": "Admin API"},
    "fields": [
        _field("shop_domain", "string", required=True),
        _field("admin_token", "secret", required=True),
        _field("base_url", "url"),
        _field("page_size", "int"),
        _field("sandbox", "bool"),
        _field("region", "select", options=["eu", "us"]),
    ],
}

MEMBER_CONNECTION = {
    "id": "github",
    "scope": "interactive",
    "label": {"en": "GitHub"},
    "flow": {
        "type": "oauth2",
        "authorize_url": "https://github.test/login/oauth/authorize",
        "token_url": "https://github.test/login/oauth/access_token",
        "client_id": "{vendor.client_id}",
        "after_connect": True,
    },
    "fields": [_field("login", "string", managed=True)],
}

#: A guild-wide credential obtained rather than typed.
#:
#: The vendor authorizes an organization through a page of its own, so an admin
#: is sent there and the plug-in writes down what came back. Same scope as
#: ``ADMIN_CONNECTION`` — one credential for everybody — and a different way of
#: arriving at one.
WORKSPACE_CONNECTION = {
    "id": "workspace",
    "scope": "static",
    "label": {"en": "Organization"},
    "flow": {
        "type": "oauth2",
        "authorize_url": "https://github.test/login/oauth/authorize",
        "token_url": "https://github.test/login/oauth/access_token",
        "client_id": "{vendor.client_id}",
        "install_url": "https://github.test/apps/x/installations/new",
        "after_connect": True,
    },
    "fields": [_field("owner", "string", required=True, managed=True)],
}

DEFINITION = {
    "plugin_kind": "service",
    "connections": [ADMIN_CONNECTION, MEMBER_CONNECTION],
}


class _Install:
    """Just enough of a ``GuildPlugin`` row for the handle helpers."""

    def __init__(self, refs=None):
        self.connection_refs = refs if refs is not None else {}


def _apply(submitted: dict, *, current=None, secrets=None, **kwargs):
    return apply_connection_values(
        ADMIN_CONNECTION,
        submitted,
        current=current or {},
        current_secrets=secrets or {},
        **kwargs,
    )


VALID = {"shop_domain": "example.test", "admin_token": "shpat_abc"}


class TestSecretCustody:
    def test_a_secret_round_trips_for_the_one_caller_entitled_to_it(self):
        """Fernet carries a random IV, so the same value stored twice is not the
        same bytes, which is why a stored secret cannot be compared for
        equality from outside."""
        _config, secrets = _apply(VALID)
        assert "shpat_abc" not in secrets["admin_token"]
        assert decrypt_field(secrets["admin_token"], SALT_PLUGIN_CONFIG) == "shpat_abc"
        assert decrypt_connection_secrets(secrets) == {"admin_token": "shpat_abc"}
        assert _apply(VALID)[1]["admin_token"] != secrets["admin_token"]

    def test_clearing_a_secret_removes_the_ciphertext(self):
        config, secrets = _apply(VALID)
        config, secrets = _apply({"admin_token": None}, current=config, secrets=secrets)
        assert secrets == {}
        assert has_value_map(ADMIN_CONNECTION, config, secrets)["admin_token"] is False


class TestValidation:
    def test_a_managed_field_is_written_by_a_flow_and_not_a_form(self):
        with pytest.raises(PluginConfigError) as exc:
            apply_connection_values(
                MEMBER_CONNECTION,
                {"login": "alice"},
                current={},
                current_secrets={},
            )
        assert exc.value.code == GuildPluginMessages.CONFIG_MANAGED_FIELD

        config, _ = apply_connection_values(
            MEMBER_CONNECTION,
            {"login": "alice"},
            current={},
            current_secrets={},
            allow_managed=True,
        )
        assert config["login"] == "alice"

    def test_a_flows_token_keys_are_not_fields(self):
        """The reserved keys a flow keeps its tokens under are no field of the
        connection, and nothing writes them through a form."""
        with pytest.raises(PluginConfigError) as exc:
            apply_connection_values(
                MEMBER_CONNECTION,
                {"access_token": "gho_x"},
                current={},
                current_secrets={},
                allow_managed=True,
            )
        assert exc.value.code == GuildPluginMessages.CONFIG_UNKNOWN_FIELD

    @pytest.mark.parametrize(
        "submitted",
        [
            {"page_size": True},  # a bool is not a whole number
            {"page_size": "10"},  # nor is a string that looks like one
            {"sandbox": "true"},
            {"sandbox": 1},
            {"region": "apac"},
            {"base_url": "ftp://example.test"},
            {"base_url": "example.test"},
            {"shop_domain": "   "},
            {"shop_domain": 5},
        ],
    )
    def test_a_value_that_is_not_what_the_field_declared_is_refused(self, submitted):
        with pytest.raises(PluginConfigError) as exc:
            _apply({**VALID, **submitted})
        assert exc.value.code == GuildPluginMessages.CONFIG_INVALID_VALUE

    def test_an_over_long_secret_is_refused_rather_than_cut(self):
        with pytest.raises(PluginConfigError) as exc:
            _apply({**VALID, "admin_token": "x" * (MAX_SECRET_VALUE_LENGTH + 1)})
        assert exc.value.code == GuildPluginMessages.CONFIG_VALUE_TOO_LONG

    def test_a_private_key_sized_secret_fits(self):
        """PEM private keys are legitimate credentials for several vendors, so
        the secret cap is not the plain-field cap."""
        pem = "-" * 3_000
        _, secrets = _apply({**VALID, "admin_token": pem})
        assert decrypt_field(secrets["admin_token"], SALT_PLUGIN_CONFIG) == pem

    def test_values_are_trimmed(self):
        config, _ = _apply({**VALID, "shop_domain": "  example.test  "})
        assert config["shop_domain"] == "example.test"

    def test_a_field_left_out_is_untouched(self):
        """A form that renders part of a connection must not wipe the rest."""
        config, secrets = _apply(VALID)
        config, secrets = _apply(
            {"base_url": "https://example.test"}, current=config, secrets=secrets
        )
        assert config["shop_domain"] == "example.test"
        assert "admin_token" in secrets


class TestSatisfaction:
    def test_a_connection_with_no_required_fields_is_satisfied_by_any_value(self):
        connection = {
            "id": "x",
            "scope": "interactive",
            "fields": [_field("token", "secret")],
        }
        assert is_satisfied(connection, {}, {}) is False
        assert is_satisfied(connection, {}, {"token": "ct"}) is True

    def test_clearing_configuration_makes_it_needed_again(self):
        """No capability outlives its credential — the same read on the next
        fetch, rather than a cached yes."""
        config, secrets = _apply(VALID)
        config, secrets = _apply({"admin_token": None}, current=config, secrets=secrets)
        assert (
            needs_configuration(DEFINITION, {"admin": config}, {"admin": secrets})
            is True
        )


class TestPruningToANewDefinition:
    """What an upgrade keeps.

    A value cannot outlive the field it was typed into, and that has to reach
    fields rather than stopping at connections — a version that keeps a
    connection but drops one of its fields would otherwise leave the value
    stored, and a non-secret one would keep appearing in the install's detail.
    """

    def test_a_dropped_field_takes_its_value(self):
        narrowed = {
            "plugin_kind": "service",
            "connections": [
                {**ADMIN_CONNECTION, "fields": [_field("shop_domain", "string")]}
            ],
        }
        config, secrets, dropped = prune_to_definition(
            narrowed,
            {"admin": {"shop_domain": "example.test", "page_size": 50}},
            {"admin": {"admin_token": "ciphertext"}},
        )
        assert config == {"admin": {"shop_domain": "example.test"}}
        assert secrets == {}
        assert dropped == set()

    def test_a_dropped_connection_is_reported_for_revocation(self):
        config, _secrets, dropped = prune_to_definition(
            {"plugin_kind": "service", "connections": [ADMIN_CONNECTION]},
            {"admin": {"shop_domain": "example.test"}, "gone": {"key": "value"}},
            {},
        )
        assert config == {"admin": {"shop_domain": "example.test"}}
        assert dropped == {"gone"}

    def test_a_connection_that_keeps_everything_is_untouched(self):
        stored = {"admin": {"shop_domain": "example.test", "page_size": 50}}
        config, _, dropped = prune_to_definition(DEFINITION, stored, {})
        assert config == stored
        assert dropped == set()


class TestAFlowsTokens:
    def test_an_upgrade_keeps_a_flows_tokens(self):
        """The reserved keys are no declared field, and pruning to a new
        version's fields must not take a flow's tokens with it."""
        definition = {"connections": [MEMBER_CONNECTION, WORKSPACE_CONNECTION]}
        config, secrets, dropped = prune_to_definition(
            definition,
            {"workspace": {"owner": "acme", "expires_at": 1, "stray": "x"}},
            {"workspace": {"access_token": "sealed", "refresh_token": "sealed"}},
        )
        assert config == {"workspace": {"owner": "acme", "expires_at": 1}}
        assert secrets == {
            "workspace": {"access_token": "sealed", "refresh_token": "sealed"}
        }
        assert dropped == set()

    def test_a_flow_with_no_fields_is_satisfied_by_its_token(self):
        bare = {**MEMBER_CONNECTION, "fields": []}
        assert is_satisfied(bare, {}, {}) is False
        assert is_satisfied(bare, {}, {"access_token": "sealed"}) is True


class TestWhichConnectionsRunAFlow:
    def test_a_flow_is_a_declared_flow_and_not_a_scope(self):
        """Two independent questions, and they used to look like one.

        The scope says whose credential comes back. The ``flow`` says
        whether a vendor is involved in getting it. A guild-wide connection may
        have one, and an admin running an organization-wide install is the case
        it exists for.
        """
        assert runs_vendor_flow(MEMBER_CONNECTION) is True
        assert runs_vendor_flow(WORKSPACE_CONNECTION) is True
        assert runs_vendor_flow(ADMIN_CONNECTION) is False
        assert runs_vendor_flow(None) is False


class TestTheHandleAGuildFlowIsJoinedBy:
    def test_a_handle_is_minted_once_per_connection_and_kept(self):
        """Reconnecting writes over one connection rather than making a second,
        and the JSONB column is reassigned rather than changed in place, since
        SQLAlchemy tracks it by identity."""
        held = {}
        install = _Install(held)
        first = guild_connection_ref(install, "workspace")
        other = guild_connection_ref(install, "billing")

        assert first and first != other
        assert install.connection_refs == {"workspace": first, "billing": other}
        assert guild_connection_ref(install, "workspace") == first
        assert held == {}

    def test_a_handle_resolves_only_to_the_connection_it_names(self):
        """``None`` is also the ordinary answer for a member's handle, which
        lives on a row of its own and not here."""
        install = _Install()
        ref = guild_connection_ref(install, "workspace")

        assert connection_id_for_ref(install, ref) == "workspace"
        assert connection_id_for_ref(install, "gcr_invented") is None
        assert connection_id_for_ref(install, "") is None
        assert connection_id_for_ref(_Install(), ref) is None


class TestAFlowFilledConnectionIsStillConfiguration:
    def test_an_install_needs_configuring_until_the_flow_has_run(self):
        """Nobody types anything, and it is still unfinished until it is done.

        Satisfaction is presence, wherever the values came from — so the
        settings page says an admin still has something to do, and what they
        have to do is press Connect.
        """
        definition = {"plugin_kind": "service", "connections": [WORKSPACE_CONNECTION]}

        assert needs_configuration(definition, {}, {}) is True
        assert (
            needs_configuration(definition, {"workspace": {"owner": "acme"}}, {})
            is False
        )
