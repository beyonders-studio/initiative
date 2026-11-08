"""Dashboards a plug-in ships with itself.

A publisher who declares widgets otherwise leaves every guild to arrange them.
The point of bundling is that the operator adds one file and the arrangements
come with it — so what these check is mostly about *identity and lifecycle*: the
derived listing is an ordinary one, it is the publisher's own uid rather than
anything invented here, and it lives and dies with the plug-in that supplied it.

The one case worth reading first is the last: a bundled dashboard is offered
only where its plug-in is installed, and that has to be decided at install and not
only in the browse response, because a uid seen in one guild is otherwise just
as installable in the next.
"""

import pytest
from sqlmodel import select

from app.models.platform.marketplace import MarketplaceListing
from app.services.marketplace import catalog as service
from app.services.marketplace.catalog import CatalogError
from app.services.marketplace.installs import (
    ListingInstallError,
    resolve_listing_install,
)
from app.testing import create_guild, create_guild_plugin, create_user
from app.testing.schema_harness import route_session_to_guild

PLUGIN_UID = "TYG4VVZKAWRMBZ"
DASH_UID = "J9H7S9T7GP7FAG"
OTHER_DASH_UID = "P3R9WT5HZ2NM6D"


#: The read a tile draws, spelled once. Namespaced under the plug-in's own service
#: id, which is what every endpoint id has to be.
OPEN_ITEMS = "plugin.tests.tracker.open-items"


def _dashboard(uid=DASH_UID, public_id="tests.tracker-overview", **overrides):
    entry = {
        "uid": uid,
        "public_id": public_id,
        "name": "Tracker overview",
        "description": "At a glance.",
        "layout": {"columns": 12},
        "widgets": [
            {
                "type": "open-items",
                "title": "Open",
                "grid": {"x": 0, "y": 0, "w": 4, "h": 3},
                "binding": {"endpoint_id": OPEN_ITEMS},
            }
        ],
    }
    entry.update(overrides)
    return entry


def _plugin_manifest(dashboards=None, version="1.0.0"):
    definition = {
        "plugin_kind": "service",
        "service": {"public_id": "tests.tracker", "protocol": 1},
        "features": ["endpoints", "widgets"],
        "endpoints": [{"id": OPEN_ITEMS, "direction": "read"}],
        "widgets": [
            {
                "id": "open-items",
                "meta": {"name": {"en": "Open items"}},
                "module_source": "export default () => ({});",
                "endpoints": [OPEN_ITEMS],
            }
        ],
    }
    if dashboards is not None:
        definition["features"] = [*definition["features"], "dashboards"]
        definition["dashboards"] = dashboards
    return {
        "uid": PLUGIN_UID,
        "public_id": "tests.tracker",
        "kind": "plugin",
        "name": "Tracker",
        "publisher": "Tests",
        "description": "Track the things.",
        "avatar_url": "/marketplace/tracker.svg",
        "version": version,
        "definition": definition,
    }


async def _by_uid(session, uid):
    return (
        await session.exec(
            select(MarketplaceListing).where(MarketplaceListing.uid == uid)
        )
    ).first()


class TestPublishing:
    async def test_publishing_the_plugin_publishes_its_dashboards(self, session):
        """One file for the operator. That is the whole point of the block."""
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        dashboard = await _by_uid(session, DASH_UID)
        assert dashboard is not None
        assert dashboard.kind == "dashboard"
        assert dashboard.bundled_with_uid == PLUGIN_UID
        # Inherited, because it *is* the plug-in's publish.
        assert dashboard.publisher == "Tests"
        assert dashboard.source == "operator"

    async def test_the_derived_row_is_an_ordinary_listing(self, session):
        """Nothing downstream should be able to tell it was derived: a guild
        installs it with the same call it installs any other dashboard with."""
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        dashboard = await _by_uid(session, DASH_UID)
        version = await service.get_listing_version(
            session, dashboard.latest_version_id
        )
        # Stored as the dashboard's envelope, around the canvas it installs.
        assert version.definition["type"] == "initiative-dashboard"
        definition = version.definition["definition"]

        assert definition["kind"] == "dashboard"
        assert definition["schema_version"] == 1
        assert definition["layout"] == {"columns": 12}
        widget = definition["widgets"][0]
        # Resolved to the namespaced form here, from the plug-in's own uid — a
        # publisher writes a bare widget id and never a uid, so the two cannot
        # disagree.
        assert widget["type"] == f"plugin:{PLUGIN_UID}:open-items"
        assert widget["binding"] == {
            "source": "plugin",
            "plugin_uid": PLUGIN_UID,
            "endpoint_id": OPEN_ITEMS,
        }

    async def test_a_bundled_tile_may_fix_several_values_for_one_parameter(
        self, session
    ):
        """The same shape a guild's own binding may hold.

        An endpoint declaring a parameter takes several is entitled to have
        several fixed by the dashboard its plug-in ships, or the arrangement a
        publisher bundles could express less than one somebody assembles by
        hand — for no reason a reader of either could see.
        """
        entry = _dashboard()
        entry["widgets"][0]["binding"] = {
            "endpoint_id": OPEN_ITEMS,
            "params": {"labels": ["bug", "regression"], "state": "open"},
        }
        await service.upsert_listing(
            session, _plugin_manifest([entry]), source="operator"
        )
        await session.commit()

        dashboard = await _by_uid(session, DASH_UID)
        version = await service.get_listing_version(
            session, dashboard.latest_version_id
        )
        assert version.definition["definition"]["widgets"][0]["binding"]["params"] == {
            "labels": ["bug", "regression"],
            "state": "open",
        }

    async def test_a_bundled_tile_cannot_fix_a_value_of_no_declarable_shape(
        self, session
    ):
        entry = _dashboard()
        entry["widgets"][0]["binding"] = {
            "endpoint_id": OPEN_ITEMS,
            "params": {"labels": [{"nested": "object"}]},
        }
        with pytest.raises(CatalogError):
            await service.upsert_listing(
                session, _plugin_manifest([entry]), source="operator"
            )

    async def test_it_carries_no_artwork_of_its_own(self, session):
        """A dashboard previews by rendering its widgets against their sample
        data, which cannot go stale against the plug-in the way a picture would."""
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        dashboard = await _by_uid(session, DASH_UID)
        assert dashboard.avatar_url == service.DEFAULT_AVATAR_URL
        assert dashboard.images == []

    async def test_a_plugin_with_no_dashboards_publishes_one_row(self, session):
        await service.upsert_listing(session, _plugin_manifest(), source="operator")
        await session.commit()

        assert await _by_uid(session, DASH_UID) is None
        assert await _by_uid(session, PLUGIN_UID) is not None

    async def test_two_dashboards_sharing_a_uid_are_refused(self, session):
        with pytest.raises(CatalogError):
            await service.upsert_listing(
                session,
                _plugin_manifest(
                    [_dashboard(), _dashboard(public_id="tests.tracker-second")]
                ),
                source="operator",
            )

    async def test_a_uid_another_listing_holds_is_refused(self, session):
        """The catalog's own rule, and it has to hold for a derived row too —
        a uid names one listing everywhere or it names nothing."""
        await service.upsert_listing(
            session,
            {
                **_plugin_manifest(),
                "uid": DASH_UID,
                "public_id": "tests.something-else",
                "kind": "dashboard",
                "definition": {"widgets": []},
            },
            source="operator",
        )
        await session.commit()

        with pytest.raises(CatalogError):
            await service.upsert_listing(
                session, _plugin_manifest([_dashboard()]), source="operator"
            )


class TestItCannotTakeOverSomebodyElsesListing:
    """Both identities matching is what an *update* looks like, so this is the
    one path where a publish reaches an existing row rather than being refused
    by the uniqueness rules. Ownership has to be checked on its own."""

    async def _standalone(
        self, session, uid=DASH_UID, public_id="tests.tracker-overview"
    ):
        # Deliberately a *different* version from the plug-in's. Publishing at the
        # same one would collide on version immutability and refuse for a reason
        # that has nothing to do with ownership — which is how this case hid.
        await service.upsert_listing(
            session,
            {
                **_plugin_manifest(version="0.9.0"),
                "uid": uid,
                "public_id": public_id,
                "kind": "dashboard",
                "name": "Somebody else's board",
                "definition": {"widgets": []},
            },
            source="operator",
        )
        await session.commit()

    async def test_it_cannot_adopt_a_standalone_dashboard(self, session):
        await self._standalone(session)

        with pytest.raises(CatalogError):
            await service.upsert_listing(
                session, _plugin_manifest([_dashboard()]), source="operator"
            )

    async def test_the_standalone_listing_is_left_alone(self, session):
        await self._standalone(session)

        with pytest.raises(CatalogError):
            await service.upsert_listing(
                session, _plugin_manifest([_dashboard()]), source="operator"
            )
        await session.rollback()

        untouched = await _by_uid(session, DASH_UID)
        assert untouched.name == "Somebody else's board"
        assert untouched.bundled_with_uid is None

    async def test_it_cannot_adopt_another_plugin_s_dashboard(self, session):
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        # A different version too, so version immutability cannot be what
        # refuses it — ownership has to be.
        other = _plugin_manifest([_dashboard()], version="2.0.0")
        other["uid"] = "P3R9WT5HZ2NM6D"
        other["public_id"] = "tests.other-plugin"
        other["definition"]["service"]["public_id"] = "tests.other-plugin"

        with pytest.raises(CatalogError):
            await service.upsert_listing(session, other, source="operator")

    async def test_a_standalone_publish_cannot_adopt_a_bundled_one(self, session):
        """The mirror. An operator dropping a file with a uid a plug-in already
        bundles must not edit that row, or take it out of the plug-in's lifecycle."""
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        with pytest.raises(CatalogError):
            await service.upsert_listing(
                session,
                {
                    **_plugin_manifest(version="3.0.0"),
                    "uid": DASH_UID,
                    "public_id": "tests.tracker-overview",
                    "kind": "dashboard",
                    "name": "Mine now",
                    "definition": {"widgets": []},
                },
                source="operator",
            )

    async def test_republishing_the_same_plugin_is_not_a_takeover(self, session):
        """The case all of this has to stay out of the way of."""
        await service.upsert_listing(
            session,
            _plugin_manifest([_dashboard()], version="1.0.0"),
            source="operator",
        )
        await session.commit()
        await service.upsert_listing(
            session,
            _plugin_manifest([_dashboard()], version="2.0.0"),
            source="operator",
        )
        await session.commit()

        assert (await _by_uid(session, DASH_UID)).bundled_with_uid == PLUGIN_UID


class TestLifecycle:
    async def test_they_version_with_the_plugin(self, session):
        await service.upsert_listing(
            session,
            _plugin_manifest([_dashboard()], version="1.0.0"),
            source="operator",
        )
        await session.commit()
        await service.upsert_listing(
            session,
            _plugin_manifest([_dashboard()], version="2.0.0"),
            source="operator",
        )
        await session.commit()

        dashboard = await _by_uid(session, DASH_UID)
        version = await service.get_listing_version(
            session, dashboard.latest_version_id
        )
        assert version.version == "2.0.0"

    async def test_dropping_one_from_the_manifest_withdraws_it(self, session):
        """Withdrawn, not deleted: a guild that installed it keeps what it has."""
        await service.upsert_listing(
            session,
            _plugin_manifest(
                [_dashboard(), _dashboard(OTHER_DASH_UID, "tests.second")]
            ),
            source="operator",
        )
        await session.commit()

        await service.upsert_listing(
            session,
            _plugin_manifest([_dashboard()], version="2.0.0"),
            source="operator",
        )
        await session.commit()

        assert (await _by_uid(session, DASH_UID)).available is True
        dropped = await _by_uid(session, OTHER_DASH_UID)
        assert dropped is not None and dropped.available is False

    async def test_withdrawing_the_plugin_withdraws_them(self, session):
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        assert await service.withdraw_listing(session, PLUGIN_UID) is True
        await session.commit()

        assert (await _by_uid(session, DASH_UID)).available is False

    async def test_withdrawing_a_standalone_dashboard_touches_nothing_else(
        self, session
    ):
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        assert await service.withdraw_listing(session, DASH_UID) is True
        await session.commit()

        assert (await _by_uid(session, PLUGIN_UID)).available is True


class TestWhoIsOfferedOne:
    async def test_it_is_not_offered_to_a_caller_with_no_guild(self, session):
        """The platform-addressed browse has no guild to decide for, so it
        offers nothing bundled rather than offering it to everybody."""
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        listings, _ = await service.list_listings(session, kind="dashboard")
        assert DASH_UID not in {listing.uid for listing in listings}

    async def test_it_is_offered_where_the_plugin_is_installed(self, session):
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()

        listings, _ = await service.list_listings(
            session, kind="dashboard", bundled_with=[PLUGIN_UID]
        )
        assert DASH_UID in {listing.uid for listing in listings}

    async def test_a_standalone_dashboard_is_offered_either_way(self, session):
        await service.upsert_listing(
            session,
            {
                **_plugin_manifest(),
                "uid": OTHER_DASH_UID,
                "public_id": "tests.shared-board",
                "kind": "dashboard",
                "definition": {"widgets": []},
            },
            source="operator",
        )
        await session.commit()

        for bundled_with in (None, [PLUGIN_UID]):
            listings, _ = await service.list_listings(
                session, kind="dashboard", bundled_with=bundled_with
            )
            assert OTHER_DASH_UID in {listing.uid for listing in listings}


class TestWhoMayInstallOne:
    async def test_a_guild_with_the_plugin_may_install_it(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await create_guild_plugin(
            session,
            guild,
            user,
            definition={
                "plugin_kind": "service",
                "service": {"public_id": "tests.tracker"},
            },
            listing_uid=PLUGIN_UID,
        )
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()
        await route_session_to_guild(session, guild.id)

        listing, version = await resolve_listing_install(
            session, DASH_UID, kind="dashboard"
        )
        assert listing.uid == DASH_UID
        canvas = version.definition["definition"]
        assert canvas["widgets"][0]["binding"]["plugin_uid"] == PLUGIN_UID

    async def test_a_guild_without_the_plugin_may_not(self, session):
        """The case the browse filter cannot cover on its own. A uid read in a
        guild that has the plug-in is otherwise just as installable here."""
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()
        await route_session_to_guild(session, guild.id)

        with pytest.raises(ListingInstallError) as caught:
            await resolve_listing_install(session, DASH_UID, kind="dashboard")
        assert caught.value.code == "MARKETPLACE_LISTING_NEEDS_PLUGIN"
        assert caught.value.status_code == 409

    async def test_a_guild_that_switched_the_plugin_off_may_not(self, session):
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        plugin = await create_guild_plugin(
            session,
            guild,
            user,
            definition={
                "plugin_kind": "service",
                "service": {"public_id": "tests.tracker"},
            },
            listing_uid=PLUGIN_UID,
        )
        plugin.enabled = False
        session.add(plugin)
        await service.upsert_listing(
            session, _plugin_manifest([_dashboard()]), source="operator"
        )
        await session.commit()
        await route_session_to_guild(session, guild.id)

        with pytest.raises(ListingInstallError) as caught:
            await resolve_listing_install(session, DASH_UID, kind="dashboard")
        assert caught.value.code == "MARKETPLACE_LISTING_NEEDS_PLUGIN"

    async def test_a_standalone_dashboard_needs_no_plugin(self, session):
        """The other route, unchanged: somebody publishes a dashboard to share
        and any guild installs it."""
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await service.upsert_listing(
            session,
            {
                **_plugin_manifest(),
                "uid": OTHER_DASH_UID,
                "public_id": "tests.shared-board",
                "kind": "dashboard",
                "definition": {"widgets": []},
            },
            source="operator",
        )
        await session.commit()
        await route_session_to_guild(session, guild.id)

        listing, _ = await resolve_listing_install(
            session, OTHER_DASH_UID, kind="dashboard"
        )
        assert listing.bundled_with_uid is None
