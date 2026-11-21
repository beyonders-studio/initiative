"""What the catalog will and will not accept.

The load-bearing cases are the identity ones. A uid is the code someone shares
or types, so it has to mean the same listing everywhere — which only holds if a
later publisher cannot take one that is already held. And a listing's definition
has to survive the tool's own validator, because installing copies it into a
guild's schema and the canvas that renders it knows nothing about where it came
from.
"""

import copy
import json
import subprocess
from pathlib import Path

import pytest
from sqlmodel import select

from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.services.marketplace import catalog as service
from app.services.marketplace.catalog import CatalogError
from app.services.marketplace.definitions import (
    normalize_listing_definition,
    normalize_listing_example,
)
from app.testing import counters_tool_manifest, create_marketplace_listing
from app.testing.fake_vendor import declarative_plugin


def _widget(widget_type="stat", binding=None) -> dict:
    return {
        "id": "w1",
        "type": widget_type,
        "binding": binding
        or {"source": "query", "sql": "SELECT count(*) AS n FROM tasks"},
    }


DASHBOARD = {"widgets": [_widget()]}
CALENDAR = {
    "plugin_kind": "tool_instance",
    "tool": "calendar",
    "default_name": "Community calendar",
}


def _manifest(**overrides):
    manifest = {
        "uid": "ABCDEFGH123456",
        "public_id": "tests.example",
        "kind": "dashboard",
        "name": "Example",
        "publisher": "Tests",
        "description": "An example listing.",
        "avatar_url": "/marketplace/example.svg",
        "version": "1.0.0",
        "definition": DASHBOARD,
    }
    manifest.update(overrides)
    return copy.deepcopy(manifest)


async def _version_count(session, listing_id: int) -> int:
    return len(
        (
            await session.exec(
                select(MarketplaceListingVersion).where(
                    MarketplaceListingVersion.listing_id == listing_id
                )
            )
        ).all()
    )


@pytest.mark.parametrize(
    ("overrides", "source", "match"),
    [
        # I, L, O and U are excluded so a code can be transcribed by hand.
        *(
            ({"uid": uid}, "builtin", "uid")
            for uid in (
                "TOOSHORT",
                "WAYTOOLONGFORAUID",
                "ABCDEFGHIJ1234",
                "ABCDEFGH12345l",
            )
        ),
        ({"public_id": "noslug"}, "builtin", "publisher"),
        # Who publishes it is part of what a listing is.
        ({"publisher": None}, "builtin", "publisher is required"),
        ({"publisher": "   "}, "builtin", "publisher"),
        # `core.*` says "shipped in this repository", so only a built-in holds one.
        ({"public_id": "core.impostor"}, "operator", "reserved"),
        ({"public_id": "core.impostor"}, "registry", "reserved"),
        # Catalog content goes through the tool's own validator.
        (
            {"definition": {"widgets": [_widget("iframe")]}},
            "builtin",
            "invalid dashboard definition",
        ),
        (
            {
                "definition": {
                    "widgets": [_widget(binding={"source": "https://x.test"})]
                }
            },
            "builtin",
            "invalid dashboard definition",
        ),
        (
            {
                "kind": "plugin",
                "definition": {"plugin_kind": "tool_instance", "tool": "dashboard"},
            },
            "builtin",
            "cannot be mounted",
        ),
        # Artwork must be a same-origin path; which check refuses it varies.
        *(
            ({"avatar_url": avatar_url}, "builtin", "avatar_url")
            for avatar_url in (
                "https://elsewhere.test/logo.png",
                "http://elsewhere.test/logo.png",
                "//elsewhere.test/logo.png",
                "marketplace/relative.svg",
                "/\\elsewhere.test/logo.png",
                "/\telsewhere.test/logo.png",
                "/marketplace/../logo.png",
                "/marketplace//logo.png",
            )
        ),
        (
            {"images": ["/marketplace/ok.png", "https://elsewhere.test/x.png"]},
            "builtin",
            "images",
        ),
        (
            {
                "min_plugin_api": "4.1",
                "definition": {**DASHBOARD, "min_plugin_api": "4.2"},
            },
            "builtin",
            "differs from its manifest",
        ),
        *(
            ({"min_plugin_api": value}, "builtin", "MAJOR.MINOR")
            for value in ("4", "4.1.0", "latest", 4)
        ),
    ],
)
async def test_a_manifest_it_cannot_take_is_refused(session, overrides, source, match):
    with pytest.raises(CatalogError, match=match):
        await service.upsert_listing(session, _manifest(**overrides), source=source)


class TestIdentity:
    async def test_a_uid_cannot_be_taken_from_its_holder(self, session):
        """A shared code resolves to one product, so a uid already in use is
        refused rather than merged into."""
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="refusing to reassign"):
            await service.upsert_listing(
                session,
                _manifest(public_id="another.publisher"),
                source="builtin",
            )

    @pytest.mark.parametrize("held_by", ["builtin", "local", "operator"])
    async def test_a_registry_never_replaces_another_sources_listing(
        self, session, held_by
    ):
        """The registry adds listings beside this deployment's own. The same
        uid arriving from it is refused, whoever published it first."""
        await service.upsert_listing(session, _manifest(), source=held_by)
        with pytest.raises(service.CatalogSourceConflict):
            await service.upsert_listing(
                session, _manifest(name="From the registry"), source="registry"
            )
        listing = await service.get_listing_by_uid(session, _manifest()["uid"])
        assert listing is not None
        assert listing.source == held_by
        assert listing.name == "Example"

    async def test_a_public_id_cannot_be_republished_under_a_new_uid(self, session):
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="already published"):
            await service.upsert_listing(
                session, _manifest(uid="ZZZZZZZZ999999"), source="registry"
            )

    async def test_a_built_in_lands_with_its_publisher_namespace_and_artwork(
        self, session
    ):
        listing = await service.upsert_listing(
            session,
            _manifest(
                public_id="core.example",
                publisher="Widget Co",
                images=["/marketplace/shot-1.png"],
            ),
            source="builtin",
        )
        assert listing.public_id == "core.example"
        assert listing.publisher == "Widget Co"
        assert listing.images == ["/marketplace/shot-1.png"]


class TestDefinitions:
    async def test_a_published_definition_is_stored_normalized(self, session):
        listing = await service.upsert_listing(session, _manifest(), source="builtin")
        version = await service.get_listing_version(session, listing.latest_version_id)
        assert version is not None
        # Canonical shape, not whatever the manifest happened to carry: the
        # dashboard's envelope, around a normalized canvas.
        assert version.definition["type"] == "initiative-dashboard"
        assert version.definition["definition"]["kind"] == "dashboard"
        assert version.definition["definition"]["layout"] == {"columns": 12}

    async def test_a_plugin_listing_is_stored_canonically_with_the_plugin_mark(
        self, session
    ):
        """Artwork is optional: a listing that ships none is published with
        Initiative's own same-origin mark rather than refused over a picture."""
        manifest = _manifest(
            kind="plugin", definition={**CALENDAR, "unexpected": "dropped"}
        )
        manifest.pop("avatar_url")

        listing = await service.upsert_listing(session, manifest, source="builtin")

        assert listing.avatar_url == service.DEFAULT_AVATAR_URL
        assert listing.avatar_url.startswith("/")
        version = await service.get_listing_version(session, listing.latest_version_id)
        assert version.definition == CALENDAR

    async def test_a_service_plugin_reaches_the_catalog_as_data(self, session):
        """The widest thing a publisher can send, through the ordinary path:
        what lands is the canonical document, with the keys this build has no
        use for gone — including anything that looks like an address, since
        where a plug-in lives is the deployment's statement, not the listing's."""
        listing = await service.upsert_listing(
            session,
            _manifest(
                kind="plugin",
                definition={
                    "plugin_kind": "service",
                    "service": {
                        "public_id": "tests.widget-co",
                        "default_url": "https://widget.test",
                    },
                    "features": ["pages"],
                    "pages": [
                        {"id": "main", "path": "/embed/main", "name": {"en": "Main"}}
                    ],
                },
            ),
            source="builtin",
        )
        version = await service.get_listing_version(session, listing.latest_version_id)
        assert version.definition["plugin_kind"] == "service"
        assert version.definition["service"] == {
            "public_id": "tests.widget-co",
            "protocol": 1,
        }
        assert version.definition["pages"][0]["path"] == "/embed/main"


def _declarative(definition=None):
    return _manifest(
        kind="plugin",
        public_id="tests.issues",
        definition=definition or declarative_plugin("tests.issues"),
    )


def _relabelled_declarative():
    changed = declarative_plugin("tests.issues")
    changed["vendor"]["fields"][0]["label"]["en"] = "Application id"
    return _declarative(changed)


class TestVersions:
    @pytest.mark.parametrize(
        ("manifest", "source"),
        [(_manifest(), "builtin"), (_declarative(), "registry")],
        ids=["dashboard", "declarative"],
    )
    async def test_republishing_a_version_unchanged_is_a_no_op(
        self, session, manifest, source
    ):
        """Boot re-seeds the shipped listings on every start, so publishing the
        same manifest twice has to be harmless. A declarative plug-in is named
        by its listing, so its stored version is compared under that name."""
        await service.upsert_listing(session, copy.deepcopy(manifest), source=source)
        listing = await service.upsert_listing(session, manifest, source=source)
        assert await _version_count(session, listing.id) == 1

    @pytest.mark.parametrize(
        ("first", "changed", "source"),
        [
            (
                _manifest(),
                _manifest(definition={"widgets": [_widget("table")]}),
                "builtin",
            ),
            # Changing a floor would change who can run that exact version.
            (_manifest(), _manifest(min_app_version="999.0.0"), "builtin"),
            (_manifest(), _manifest(min_plugin_api="4.0"), "builtin"),
            (_declarative(), _relabelled_declarative(), "registry"),
        ],
        ids=["definition", "min_app_version", "min_plugin_api", "declarative"],
    )
    async def test_a_published_version_cannot_be_rewritten(
        self, session, first, changed, source
    ):
        """The definition under a version is frozen once published.

        An instance pins its version, and the upgrade path has nothing to offer
        one already on it — so a changed body under an unchanged version could
        never reach whoever installed it. It would also mean `uid` + version
        named different content on different deployments, which is exactly what
        a shared code must not do.
        """
        await service.upsert_listing(session, first, source=source)
        with pytest.raises(CatalogError, match="already published with different"):
            await service.upsert_listing(session, changed, source=source)

    async def test_a_version_saved_before_a_format_default_is_the_same_version(
        self, session
    ):
        """A field the definition format gains takes its default on reading,
        so a version saved before it is not "different content"."""
        listing = await service.upsert_listing(session, _manifest(), source="builtin")
        stored = await service.get_listing_version(session, listing.latest_version_id)
        assert stored is not None
        definition = dict(stored.definition)
        assert definition.pop("properties") == []
        stored.definition = definition
        session.add(stored)
        await session.flush()

        await service.upsert_listing(session, _manifest(), source="builtin")

        assert await _version_count(session, listing.id) == 1

    async def test_listing_metadata_stays_editable_without_a_new_version(self, session):
        """A publisher fixing a typo in their blurb should not need a release —
        the name, description and artwork belong to the listing, not the
        version."""
        await service.upsert_listing(session, _manifest(), source="builtin")
        listing = await service.upsert_listing(
            session,
            _manifest(name="Renamed", description="Reworded."),
            source="builtin",
        )
        assert (listing.name, listing.description) == ("Renamed", "Reworded.")
        assert await _version_count(session, listing.id) == 1

    async def test_a_new_version_becomes_the_latest(self, session):
        await service.upsert_listing(session, _manifest(), source="builtin")
        listing = await service.upsert_listing(
            session, _manifest(version="1.1.0"), source="builtin"
        )
        latest = await service.get_listing_version(session, listing.latest_version_id)
        assert latest is not None and latest.version == "1.1.0"
        assert await _version_count(session, listing.id) == 2

    @pytest.mark.parametrize(
        ("min_app_version", "installable"), [("999.0.0", False), ("0.1.0", True)]
    )
    async def test_only_a_version_this_build_can_run_is_installable(
        self, session, min_app_version, installable
    ):
        listing = await create_marketplace_listing(
            session,
            uid="PRESENT0000001",
            public_id="tests.present",
            min_app_version=min_app_version,
        )
        version = await service.resolve_installable_version(session, listing)
        if installable:
            assert version is not None and version.version == "1.0.0"
        else:
            assert version is None

    async def test_a_prerelease_floor_reads_as_its_release(self):
        # Only ever answers "is this deployment new enough", so 1.2.3-rc1 and
        # 1.2.3 are the same floor.
        assert service.version_is_compatible("0.0.1-rc1") is True
        assert service.version_is_compatible(None) is True


class TestToolVersions:
    """A community keeps a tool plug-in's tables across its versions, so a
    version only adds to them: within a major nothing a field holds goes, and
    no version takes an item table away."""

    @staticmethod
    def _tool(version: str, change=None) -> dict:
        definition = counters_tool_manifest()
        if change is not None:
            change(definition["tool"])
        return _manifest(
            kind="plugin",
            public_id="tests.counters",
            version=version,
            definition=definition,
        )

    @staticmethod
    def _counter(tool: dict) -> dict:
        return tool["items"][0]

    async def test_a_minor_adds_and_a_major_drops(self, session):
        def unit(tool):
            self._counter(tool)["fields"].append(
                {"key": "unit", "name": {"en": "Unit"}, "kind": "text"}
            )

        def no_unit(tool):
            pass

        await service.upsert_listing(session, self._tool("1.0.0"), source="builtin")
        await service.upsert_listing(
            session, self._tool("1.1.0", unit), source="builtin"
        )
        with pytest.raises(CatalogError, match="counter.unit"):
            await service.upsert_listing(
                session, self._tool("1.2.0", no_unit), source="builtin"
            )
        await service.upsert_listing(
            session, self._tool("2.0.0", no_unit), source="builtin"
        )

    @pytest.mark.parametrize(
        "change",
        [
            lambda tool: tool["fields"][0].update(kind="number"),
            lambda tool: tool["items"][0]["fields"][6]["options"].pop(),
        ],
        ids=["retyped", "fewer options"],
    )
    async def test_a_minor_never_changes_what_a_field_holds(self, session, change):
        await service.upsert_listing(session, self._tool("1.0.0"), source="builtin")
        with pytest.raises(CatalogError, match="within a major"):
            await service.upsert_listing(
                session, self._tool("1.1.0", change), source="builtin"
            )

    async def test_a_tool_plugin_stays_one(self, session):
        await service.upsert_listing(session, self._tool("1.0.0"), source="builtin")
        service_plugin = _manifest(
            kind="plugin",
            public_id="tests.counters",
            version="2.0.0",
            definition=declarative_plugin("tests.counters"),
        )
        with pytest.raises(CatalogError, match="all declare a tool"):
            await service.upsert_listing(session, service_plugin, source="builtin")

    async def test_no_version_takes_an_item_table_away(self, session):
        def bare(tool):
            del tool["items"]
            del tool["actions"]

        await service.upsert_listing(session, self._tool("1.0.0"), source="builtin")
        with pytest.raises(CatalogError, match="item table"):
            await service.upsert_listing(
                session, self._tool("2.0.0", bare), source="builtin"
            )


@pytest.mark.parametrize(
    ("listing_floor", "manifest_floor", "stored", "runs"),
    [
        ("4.1", None, "4.1", None),
        (None, "4.0", "4.0", None),
        ("4.1", "4.1", "4.1", None),
        (None, None, None, True),
        ("99.0", None, "99.0", False),
    ],
)
async def test_a_versions_plugin_api_floor_is_stored_and_decides_where_it_runs(
    session, listing_floor, manifest_floor, stored, runs
):
    """``min_plugin_api``: the oldest plug-in API contract a version needs, as
    its listing says beside ``min_app_version`` or its manifest does."""
    manifest = _manifest(min_plugin_api=listing_floor)
    if manifest_floor is not None:
        manifest["definition"] = {**DASHBOARD, "min_plugin_api": manifest_floor}
    listing = await service.upsert_listing(session, manifest, source="builtin")
    version = await service.get_listing_version(session, listing.latest_version_id)
    assert version is not None and version.min_plugin_api == stored
    if runs is not None:
        assert service.version_runs_here(version) is runs


class TestSearch:
    async def test_search_matches_name_description_and_publisher(self, session):
        await create_marketplace_listing(
            session,
            uid="SEARCH00000001",
            public_id="tests.alpha",
            name="Burndown",
            publisher="Acme",
            description="Tracks velocity.",
        )
        await create_marketplace_listing(
            session,
            uid="SEARCH00000002",
            public_id="tests.beta",
            name="Roadmap",
            publisher="Initiative",
            description="Quarterly plan.",
        )
        for needle, expected in [
            ("burn", "tests.alpha"),
            ("velocity", "tests.alpha"),
            ("acme", "tests.alpha"),
            ("roadmap", "tests.beta"),
        ]:
            found, _ = await service.list_listings(session, query=needle)
            assert [listing.public_id for listing in found] == [expected], needle

    async def test_a_withdrawn_listing_is_not_browsable(self, session):
        await create_marketplace_listing(
            session, uid="GNE00000000001", public_id="tests.gone", available=False
        )
        found, _total = await service.list_listings(session)
        assert "tests.gone" not in [listing.public_id for listing in found]
        # But it is still there, so an install that pinned it keeps its
        # provenance rather than pointing at nothing.
        assert await service.get_listing(session, "tests.gone") is not None
        found, _ = await service.list_listings(session, include_unavailable=True)
        assert "tests.gone" in [listing.public_id for listing in found]

    async def test_kind_filters(self, session):
        await create_marketplace_listing(
            session, uid="KND00000000001", public_id="tests.kind"
        )
        found, _ = await service.list_listings(session, kind="dashboard")
        assert "tests.kind" in [listing.public_id for listing in found]
        found, _ = await service.list_listings(session, kind="plugin")
        assert found == []


class TestInstallsCount:
    async def test_the_counter_increments_in_the_database(self, session, role_session):
        """Two installs that overlap must both count.

        Staged rather than raced, so it is deterministic: one connection has
        already loaded the row when a second install lands and commits. An
        increment computed in Python would write that connection's stale value
        back and lose the other install; one computed in SQL cannot.
        """
        listing = await create_marketplace_listing(
            session, uid="CNCRRENT000001", public_id="tests.concurrent"
        )

        first = await role_session("app_admin")
        second = await role_session("app_admin")
        # `first` reads the row at 0 and holds it.
        loaded = (
            await first.exec(
                select(MarketplaceListing).where(MarketplaceListing.id == listing.id)
            )
        ).one()
        assert loaded.installs_count == 0

        # A second install lands and commits in the meantime.
        await service.bump_installs_count(second, listing.id)
        await second.commit()

        # Then the first one does. It must not write back the 0 it is holding.
        await service.bump_installs_count(first, listing.id)
        await first.commit()

        await session.refresh(listing)
        assert listing.installs_count == 2
        # There is no column that could say *who* — the catalog must not be able
        # to answer that.
        assert not hasattr(listing, "guild_id")

    async def test_bumping_an_unknown_listing_is_a_no_op(self, session):
        # Best-effort by design: the bump happens after an install has already
        # committed, so it must never raise.
        await service.bump_installs_count(session, 999_999)


def _body(manifest: dict) -> tuple:
    definition = normalize_listing_definition(
        manifest["kind"], manifest.get("definition"), public_id=manifest["public_id"]
    )
    example = normalize_listing_example(
        manifest["kind"], manifest.get("example"), definition
    )
    return (
        definition,
        example,
        manifest.get("release_notes"),
        manifest.get("min_app_version"),
        manifest.get("min_plugin_api")
        or (manifest.get("definition") or {}).get("min_plugin_api"),
    )


def test_a_shipped_version_keeps_its_content():
    """A built-in listing whose content changed since the last release carries a
    new version: an install keeps the content it first saw under a version, so
    the change would never reach it."""
    catalog = Path(__file__).resolve().parents[2] / "marketplace_catalog"
    git = ["git", "-C", str(catalog)]
    try:
        tags = subprocess.run(
            [*git, "tag", "--merged", "HEAD", "--list", "v*", "--sort=-v:refname"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    except OSError, subprocess.CalledProcessError:
        pytest.skip("no git history here")
    if not tags:
        pytest.skip("no release tag in this checkout's history")
    prefix = subprocess.run(
        [*git, "rev-parse", "--show-prefix"], capture_output=True, text=True, check=True
    ).stdout.strip()

    changed = []
    for path in sorted(catalog.glob("*.json")):
        shipped = subprocess.run(
            [*git, "show", f"{tags[0]}:{prefix}{path.name}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if shipped.returncode != 0:
            continue  # not in that release
        then, now = json.loads(shipped.stdout), json.loads(path.read_text())
        if then["version"] == now["version"] and _body(then) != _body(now):
            changed.append(f"{path.name} {now['version']}")
    assert changed == [], f"changed since {tags[0]} without a new version: {changed}"
