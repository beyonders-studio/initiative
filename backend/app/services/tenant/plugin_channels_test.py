"""The pure decision behind a plug-in's installation calls.

Everything else in this module reaches a database, and the endpoint tests hold
that. What is worth pinning separately is the predicate that decides whether an
install belongs to the calling plug-in — it is the whole of the isolation between
one plug-in's credentials and another's.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.tenant.plugin_channels import owns_install, set_connection_state

SHOP_UID = "TESTAPP0000001"


def _registration(public_id: str = "tests.shop", listing_uid: str | None = SHOP_UID):
    return SimpleNamespace(public_id=public_id, listing_uid=listing_uid)


def _plugin(
    *,
    listing_uid: str = SHOP_UID,
    service_id: str = "tests.shop",
    plugin_kind: str = "service",
):
    return SimpleNamespace(
        id=1,
        guild_id=2,
        listing_uid=listing_uid,
        listing_version="1.0.0",
        name="Shop",
        enabled=True,
        plugin_kind=plugin_kind,
        definition={
            "plugin_kind": plugin_kind,
            "service": {"public_id": service_id},
            "connections": [],
        },
        config={},
        secret_fields={},
        config_state="unverified",
        config_state_detail=None,
        updated_at=datetime.now(UTC),
    )


class TestOwnsInstall:
    def test_a_matching_uid_and_service_id_is_ours(self):
        assert owns_install(_plugin(), _registration()) is True

    def test_another_listings_install_is_not_ours(self):
        theirs = _plugin(listing_uid="TESTAPP0000002")

        assert owns_install(theirs, _registration()) is False

    def test_an_install_pinning_another_service_is_not_ours(self):
        """The second condition, on its own. A registration re-pointed at a
        listing still cannot reach installs whose pinned definition names a
        different plug-in."""
        assert owns_install(_plugin(service_id="tests.other"), _registration()) is False

    def test_a_registration_naming_no_listing_owns_nothing(self):
        assert owns_install(_plugin(), _registration(listing_uid=None)) is False

    def test_a_non_service_install_is_never_ours(self):
        """An embed or a tool instance has no service behind it, so no
        registration speaks for it however its uid lines up."""
        assert owns_install(_plugin(plugin_kind="embed"), _registration()) is False

    def test_a_declarative_install_is_its_listings(self):
        """A definition with no service block is a declarative plug-in, named by
        its listing: the listing is the one statement there is."""
        plugin = _plugin()
        plugin.definition = {"plugin_kind": "service", "hosts": ["api.test"]}
        theirs = _plugin(listing_uid="TESTAPP0000002")
        theirs.definition = plugin.definition

        assert owns_install(plugin, _registration()) is True
        assert owns_install(theirs, _registration()) is False


def test_a_connections_recovery_clears_only_its_own_verdict():
    """``foo`` working again says nothing about ``foo_bar``, whose name it
    begins."""
    plugin = SimpleNamespace(
        config={}, config_state="unverified", config_state_detail=None, updated_at=None
    )

    assert set_connection_state(plugin, "foo_bar", "removed")
    assert not set_connection_state(plugin, "foo", "ok")
    assert (plugin.config_state, plugin.config_state_detail) == (
        "invalid",
        "foo_bar_removed",
    )

    assert set_connection_state(plugin, "foo_bar", "ok")
    assert (plugin.config_state, plugin.config_state_detail) == ("ok", None)
