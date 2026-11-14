"""Publishing by dropping a file in a directory.

The promise this path makes is specific: **a self-hoster publishes a listing
without touching this repository**. So the cases that matter are the ones an
operator actually meets — a good file lands, a bad one costs only itself, a
deleted one takes its listing out of the catalog — plus the two boundaries the
directory does not get to cross. It publishes under its own namespace, not the
one that means "shipped with the build", and it cannot take over a listing
another source already published.

Boot and the operator's on-demand rescan run the same function, so everything
here exercises the boot path too.
"""

import json
from pathlib import Path

import pytest
from sqlmodel import select

from app.core.config import settings
from app.models.platform.marketplace import MarketplaceListing
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.services.marketplace import operator_catalog as service
from app.services.marketplace.catalog import upsert_listing

#: 14 characters from the catalog's alphabet, written out rather than generated
#: so a failing uid assertion reads plainly.
OPERATOR_UID = "0PRT0R00000001"
BUILTIN_UID = "BB11TT00000001"
REGISTRY_UID = "REG15TRY000001"
PLUGIN_UID = "APP00000000001"
BUNDLED_DASH_UID = "DASHB0ARD00001"


def _manifest(**overrides) -> dict:
    manifest = {
        "uid": OPERATOR_UID,
        "public_id": "acme.standup",
        "kind": "dashboard",
        "name": "Standup board",
        "publisher": "Acme",
        "description": "What everyone is on today.",
        "avatar_url": "/marketplace/acme-standup.svg",
        "version": "1.0.0",
        "definition": {
            "widgets": [
                {
                    "id": "w1",
                    "type": "stat",
                    "binding": {
                        "source": "query",
                        "sql": "SELECT count(*) AS n FROM tasks",
                    },
                }
            ]
        },
    }
    manifest.update(overrides)
    return manifest


#: The read the bundled tile draws, namespaced under the plug-in's own service id.
OPEN_ITEMS = "plugin.acme.tracker.open-items"


def _plugin_manifest(dashboards=None, **overrides) -> dict:
    """A plug-in manifest, optionally carrying the dashboards it bundles."""
    definition: dict = {
        "plugin_kind": "service",
        "service": {"public_id": "acme.tracker", "protocol": 1},
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
    manifest = {
        "uid": PLUGIN_UID,
        "public_id": "acme.tracker",
        "kind": "plugin",
        "name": "Tracker",
        "publisher": "Acme",
        "description": "Track the things.",
        "avatar_url": "/marketplace/acme-tracker.svg",
        "version": "1.0.0",
        "definition": definition,
    }
    manifest.update(overrides)
    return manifest


def _bundled_dashboard(uid=BUNDLED_DASH_UID, public_id="acme.tracker-overview") -> dict:
    return {
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


def _write(directory: Path, filename: str, body) -> Path:
    path = directory / filename
    path.write_text(
        body if isinstance(body, str) else json.dumps(body), encoding="utf-8"
    )
    return path


@pytest.fixture
def catalog_dir(tmp_path: Path, monkeypatch) -> Path:
    directory = tmp_path / "marketplace"
    directory.mkdir()
    monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", str(directory))
    return directory


async def _listings(session) -> dict[str, MarketplaceListing]:
    rows = (await session.exec(select(MarketplaceListing))).all()
    return {row.public_id: row for row in rows}


class TestUnconfigured:
    async def test_no_directory_withdraws_what_a_directory_once_published(
        self, session, monkeypatch
    ):
        """Unset reads as empty. The directory is the only source of operator
        listings, so one left from a directory that is no longer set — the
        Automations listing earlier releases copied into every deployment — is
        withdrawn rather than offered forever."""
        monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", None)
        await upsert_listing(session, _manifest(), source="operator")
        await session.commit()

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.configured is False
        assert (result.published, result.withdrawn, result.skipped) == (0, 1, 0)
        assert (await _listings(session))["acme.standup"].available is False

    async def test_no_directory_and_no_operator_listings_is_a_no_op(
        self, session, monkeypatch
    ):
        monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", None)

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.configured is False
        assert (result.published, result.withdrawn, result.skipped) == (0, 0, 0)
        assert await _listings(session) == {}

    async def test_no_directory_leaves_other_sources_alone(self, session, monkeypatch):
        """Only what the directory published is the directory's to withdraw;
        a built-in or a registry listing is out of its scope either way."""
        monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", None)
        await upsert_listing(
            session,
            _manifest(uid=BUILTIN_UID, public_id="core.shipped"),
            source="builtin",
        )
        await upsert_listing(
            session,
            _manifest(uid=REGISTRY_UID, public_id="acme.registered"),
            source="registry",
        )
        await session.commit()

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.withdrawn == 0
        listings = await _listings(session)
        assert listings["core.shipped"].available is True
        assert listings["acme.registered"].available is True

    async def test_a_blank_setting_reads_as_unset(self, session, monkeypatch):
        monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", "   ")
        assert service.operator_catalog_dir() is None
        assert (await service.scan_operator_catalog(session)).configured is False

    async def test_a_configured_directory_that_is_not_there_says_so(
        self, session, tmp_path, monkeypatch
    ):
        """A volume that did not mount looks exactly like an empty catalog
        otherwise, so the scan reports it instead of publishing silence."""
        monkeypatch.setattr(
            settings, "MARKETPLACE_EXTRA_CATALOG_DIR", str(tmp_path / "absent")
        )
        result = await service.scan_operator_catalog(session)

        assert result.configured is True
        assert result.directory_missing is True
        assert result.published == 0


class TestPublishing:
    async def test_a_manifest_in_the_directory_is_in_the_marketplace(
        self, session, catalog_dir
    ):
        """The whole promise, in one test: a file appears, a listing appears,
        and nothing in this repository changed."""
        _write(catalog_dir, "standup.json", _manifest())

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.published == 1
        listing = (await _listings(session))["acme.standup"]
        assert listing.source == "operator"
        assert listing.available is True
        # Attribution is required on every ingestion path and shown beside the
        # provenance, so the catalog carries the publisher the file claimed.
        assert listing.publisher == "Acme"

    async def test_a_rescan_is_idempotent(self, session, catalog_dir):
        _write(catalog_dir, "standup.json", _manifest())

        first = await service.scan_operator_catalog(session)
        await session.commit()
        second = await service.scan_operator_catalog(session)
        await session.commit()

        assert (first.published, second.published) == (1, 1)
        assert second.withdrawn == 0
        assert len(await _listings(session)) == 1

    async def test_editing_a_file_republishes_it(self, session, catalog_dir):
        """Listing-level copy is editable in place; the version body is not,
        which is the catalog's own rule and stays the catalog's own rule."""
        _write(catalog_dir, "standup.json", _manifest())
        await service.scan_operator_catalog(session)
        await session.commit()

        _write(catalog_dir, "standup.json", _manifest(name="Daily standup"))
        await service.scan_operator_catalog(session)
        await session.commit()

        assert (await _listings(session))["acme.standup"].name == "Daily standup"

    async def test_a_plugins_registration_block_gives_its_registration_the_plugin_facts(
        self, session, catalog_dir
    ):
        """The same block a registry listing carries: the operator's file is
        the trust, and its ceiling is their approval."""
        block = {"kind": "container", "scope_ceiling": ["projects:read"]}
        _write(catalog_dir, "tracker.json", _plugin_manifest(registration=block))

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.problems == ()
        row = (
            await session.exec(
                select(PluginServiceRegistration).where(
                    PluginServiceRegistration.public_id == "acme.tracker"
                )
            )
        ).one()
        assert (row.listing_uid, row.scope_ceiling, row.source) == (
            PLUGIN_UID,
            ["projects:read"],
            "operator",
        )


class TestBadFiles:
    async def test_a_broken_file_does_not_stop_its_neighbours(
        self, session, catalog_dir
    ):
        """One malformed manifest is the case that must never cost a boot. The
        good file beside it publishes and the bad one is named."""
        _write(catalog_dir, "aaa-broken.json", "{ not json at all")
        _write(catalog_dir, "zzz-good.json", _manifest())

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.published == 1
        assert result.skipped == 1
        assert [problem.file for problem in result.problems] == ["aaa-broken.json"]
        assert "acme.standup" in await _listings(session)

    async def test_a_manifest_that_fails_validation_is_named_not_raised(
        self, session, catalog_dir
    ):
        """Attribution is required, so a manifest without an author is refused
        — by the catalog's own validator, reported here rather than thrown."""
        manifest = _manifest()
        del manifest["publisher"]
        _write(catalog_dir, "anonymous.json", manifest)

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.published == 0
        assert result.skipped == 1
        assert "publisher" in result.problems[0].reason
        assert await _listings(session) == {}

    async def test_a_file_that_is_not_an_object_is_skipped(self, session, catalog_dir):
        _write(catalog_dir, "list.json", [{"uid": OPERATOR_UID}])

        result = await service.scan_operator_catalog(session)

        assert result.published == 0
        assert result.problems[0].reason == "is not a JSON object"

    async def test_an_oversized_file_is_skipped(
        self, session, catalog_dir, monkeypatch
    ):
        monkeypatch.setattr(service, "MAX_MANIFEST_BYTES", 32)
        _write(catalog_dir, "huge.json", _manifest())

        result = await service.scan_operator_catalog(session)

        assert result.published == 0
        assert "larger than" in result.problems[0].reason

    async def test_files_that_are_not_json_are_ignored_entirely(
        self, session, catalog_dir
    ):
        """A directory people keep files in also holds notes and artwork; only
        `*.json` is read, and the rest is not a problem to report."""
        (catalog_dir / "README.md").write_text("notes", encoding="utf-8")
        (catalog_dir / "logo.svg").write_text("<svg/>", encoding="utf-8")
        _write(catalog_dir, "standup.json", _manifest())

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert (result.published, result.skipped) == (1, 0)


class TestNamespaceAndCollisions:
    async def test_the_core_namespace_belongs_to_the_build(self, session, catalog_dir):
        """`core.*` says "shipped with this build". A directory the operator
        controls publishes under its own prefix, so the id can never imply a
        provenance the listing does not have."""
        _write(catalog_dir, "impostor.json", _manifest(public_id="core.standup"))

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.published == 0
        assert "reserved" in result.problems[0].reason
        assert await _listings(session) == {}

    async def test_a_uid_held_by_a_builtin_is_refused(self, session, catalog_dir):
        """Refused loudly rather than overwritten: a built-in and an operator
        file naming the same listing is a collision to fix, not an update."""
        await upsert_listing(
            session,
            _manifest(uid=BUILTIN_UID, public_id="core.shipped"),
            source="builtin",
        )
        await session.commit()

        _write(
            catalog_dir,
            "clash.json",
            _manifest(uid=BUILTIN_UID, public_id="acme.clash"),
        )
        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.published == 0
        assert "builtin catalog" in result.problems[0].reason
        listing = (await _listings(session))["core.shipped"]
        # The built-in is untouched — still its own, still offered.
        assert listing.source == "builtin"
        assert listing.available is True

    async def test_a_public_id_held_by_another_source_is_refused(
        self, session, catalog_dir
    ):
        await upsert_listing(
            session,
            _manifest(uid=REGISTRY_UID, public_id="acme.standup"),
            source="registry",
        )
        await session.commit()

        _write(catalog_dir, "clash.json", _manifest())
        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.published == 0
        assert "registry catalog" in result.problems[0].reason
        assert (await _listings(session))["acme.standup"].source == "registry"


class TestWithdrawal:
    async def test_removing_the_file_retires_the_listing(self, session, catalog_dir):
        """Deleting a manifest is how an operator unpublishes. Withdrawn, not
        deleted: a guild that installed it keeps its instance."""
        path = _write(catalog_dir, "standup.json", _manifest())
        await service.scan_operator_catalog(session)
        await session.commit()
        assert (await _listings(session))["acme.standup"].available is True

        path.unlink()
        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.withdrawn == 1
        listing = (await _listings(session))["acme.standup"]
        assert listing.available is False
        assert listing.public_id == "acme.standup"

    async def test_putting_the_file_back_publishes_it_again(self, session, catalog_dir):
        path = _write(catalog_dir, "standup.json", _manifest())
        await service.scan_operator_catalog(session)
        await session.commit()
        path.unlink()
        await service.scan_operator_catalog(session)
        await session.commit()

        _write(catalog_dir, "standup.json", _manifest())
        await service.scan_operator_catalog(session)
        await session.commit()

        assert (await _listings(session))["acme.standup"].available is True

    async def test_a_file_with_a_mistake_in_it_is_not_a_removal(
        self, session, catalog_dir
    ):
        """An operator mid-edit has not unpublished anything. The file still
        claims its uid, so the listing stays as it was while they fix it."""
        _write(catalog_dir, "standup.json", _manifest())
        await service.scan_operator_catalog(session)
        await session.commit()

        broken = _manifest()
        del broken["publisher"]
        _write(catalog_dir, "standup.json", broken)
        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.withdrawn == 0
        assert result.skipped == 1
        assert (await _listings(session))["acme.standup"].available is True

    async def test_listings_from_other_sources_are_never_withdrawn(
        self, session, catalog_dir
    ):
        """The directory speaks for what the operator publishes and nothing
        else — a built-in is not absent from it, it is out of its scope."""
        await upsert_listing(
            session,
            _manifest(uid=BUILTIN_UID, public_id="core.shipped"),
            source="builtin",
        )
        await session.commit()

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.withdrawn == 0
        assert (await _listings(session))["core.shipped"].available is True


class TestBundledDashboards:
    """The seam between the two: a dashboard a manifest bundles is published by
    the same scan that would otherwise be asked to account for it."""

    async def test_a_bundled_dashboard_survives_the_scan_that_publishes_it(
        self, session, catalog_dir
    ):
        """Its uid is only ever written inside its plug-in's file, so the scan has
        to read the file to know the directory claims it."""
        _write(catalog_dir, "tracker.json", _plugin_manifest([_bundled_dashboard()]))

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert (result.published, result.withdrawn, result.skipped) == (1, 0, 0)
        listings = await _listings(session)
        assert listings["acme.tracker"].available is True
        dashboard = listings["acme.tracker-overview"]
        assert dashboard.available is True
        assert dashboard.bundled_with_uid == PLUGIN_UID

    async def test_a_rescan_leaves_the_bundled_dashboard_alone(
        self, session, catalog_dir
    ):
        _write(catalog_dir, "tracker.json", _plugin_manifest([_bundled_dashboard()]))
        await service.scan_operator_catalog(session)
        await session.commit()

        result = await service.scan_operator_catalog(session)
        await session.commit()

        assert result.withdrawn == 0
        assert (await _listings(session))["acme.tracker-overview"].available is True

    async def test_dropping_the_entry_still_withdraws_the_dashboard(
        self, session, catalog_dir
    ):
        """The plug-in no longer ships that arrangement, so it stops being offered
        — while the plug-in itself carries on."""
        _write(catalog_dir, "tracker.json", _plugin_manifest([_bundled_dashboard()]))
        await service.scan_operator_catalog(session)
        await session.commit()

        _write(catalog_dir, "tracker.json", _plugin_manifest([]))
        await service.scan_operator_catalog(session)
        await session.commit()

        listings = await _listings(session)
        assert listings["acme.tracker-overview"].available is False
        assert listings["acme.tracker"].available is True

    async def test_deleting_the_file_withdraws_both(self, session, catalog_dir):
        """Claiming the dashboard's uid is not exempting it: with the file gone,
        nothing claims either row."""
        path = _write(
            catalog_dir, "tracker.json", _plugin_manifest([_bundled_dashboard()])
        )
        await service.scan_operator_catalog(session)
        await session.commit()

        path.unlink()
        await service.scan_operator_catalog(session)
        await session.commit()

        listings = await _listings(session)
        assert listings["acme.tracker"].available is False
        assert listings["acme.tracker-overview"].available is False


class TestOneAtATime:
    async def test_a_second_scan_is_refused_while_one_runs(self, session, catalog_dir):
        """Two scans over one directory would interleave their upserts and
        their withdrawals, so the second is refused rather than queued."""
        async with service._scan_lock:
            with pytest.raises(service.OperatorCatalogScanRunning):
                await service.scan_operator_catalog(session)

    async def test_the_lock_is_released_when_a_scan_fails(
        self, session, catalog_dir, monkeypatch
    ):
        """A scan that dies still leaves the next one able to run."""

        def explode(root):
            raise RuntimeError("disk went away")

        monkeypatch.setattr(service, "_read_directory", explode)
        with pytest.raises(RuntimeError):
            await service.scan_operator_catalog(session)

        assert service._scan_lock.locked() is False
