"""What the catalog will and will not accept.

The load-bearing cases are the identity ones. A uid is the code someone shares
or types, so it has to mean the same listing everywhere — which only holds if a
later publisher cannot take one that is already held. And a listing's definition
has to survive the tool's own validator, because installing copies it into a
guild's schema and the canvas that renders it knows nothing about where it came
from.
"""

import json
import subprocess
from pathlib import Path

import pytest
from sqlmodel import select

from app.models.platform.marketplace import MarketplaceListing
from app.services.marketplace import catalog as service
from app.services.marketplace.catalog import CatalogError
from app.services.marketplace.definitions import (
    normalize_listing_definition,
    normalize_listing_example,
)
from app.testing import create_marketplace_listing
from app.testing.fake_vendor import declarative_plugin


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

    @pytest.mark.parametrize(
        "uid",
        [
            "TOOSHORT",
            "WAYTOOLONGFORAUID",
            # I, L, O and U are excluded so a code can be transcribed by hand.
            "ABCDEFGHIJ1234",
            "ABCDEFGH12345l",
        ],
    )
    async def test_a_malformed_uid_is_refused(self, session, uid):
        with pytest.raises(CatalogError, match="uid"):
            await service.upsert_listing(session, _manifest(uid=uid), source="builtin")

    async def test_a_public_id_must_name_its_publisher(self, session):
        with pytest.raises(CatalogError, match="publisher"):
            await service.upsert_listing(
                session, _manifest(public_id="noslug"), source="builtin"
            )


class TestAttribution:
    """Who publishes it is part of what a listing *is*, so it is settled here
    rather than left to whatever surface happens to display the listing."""

    async def test_a_listing_without_a_publisher_is_not_published(self, session):
        manifest = _manifest()
        del manifest["publisher"]
        with pytest.raises(CatalogError, match="publisher is required"):
            await service.upsert_listing(session, manifest, source="builtin")

    async def test_the_publisher_lands_on_the_row(self, session):
        listing = await service.upsert_listing(
            session, _manifest(publisher="Widget Co"), source="builtin"
        )
        assert listing.publisher == "Widget Co"

    async def test_a_blank_publisher_is_not_a_publisher(self, session):
        with pytest.raises(CatalogError, match="publisher"):
            await service.upsert_listing(
                session, _manifest(publisher="   "), source="builtin"
            )


class TestReservedNamespace:
    """``core.*`` says "shipped in this repository", so only a built-in holds one.

    A name can be typed by anyone; the namespace cannot, which is what keeps an
    unverified listing from reading as a first-party one.
    """

    @pytest.mark.parametrize("source", ["operator", "registry"])
    async def test_no_other_source_may_claim_it(self, session, source):
        with pytest.raises(CatalogError, match="reserved"):
            await service.upsert_listing(
                session, _manifest(public_id="core.impostor"), source=source
            )

    async def test_a_built_in_publishes_under_it(self, session):
        listing = await service.upsert_listing(
            session, _manifest(public_id="core.example"), source="builtin"
        )
        assert listing.public_id == "core.example"

    async def test_other_namespaces_stay_open(self, session):
        listing = await service.upsert_listing(
            session, _manifest(public_id="widgetco.thing"), source="registry"
        )
        assert listing.source == "registry"


class TestDefinitions:
    async def test_a_listing_cannot_publish_a_widget_we_cannot_render(self, session):
        """Catalog content goes through the tool's own validator, so there is no
        laxer path into a guild's schema by way of the marketplace."""
        with pytest.raises(CatalogError, match="invalid dashboard definition"):
            await service.upsert_listing(
                session,
                _manifest(
                    definition={
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "iframe",
                                "binding": {
                                    "source": "query",
                                    "sql": "SELECT count(*) AS n FROM tasks",
                                },
                            }
                        ]
                    }
                ),
                source="builtin",
            )

    async def test_a_listing_cannot_publish_a_source_we_cannot_fetch(self, session):
        with pytest.raises(CatalogError, match="invalid dashboard definition"):
            await service.upsert_listing(
                session,
                _manifest(
                    definition={
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "stat",
                                "binding": {"source": "https://example.test/x"},
                            }
                        ]
                    }
                ),
                source="builtin",
            )

    async def test_a_published_definition_is_stored_normalized(self, session):
        listing = await service.upsert_listing(session, _manifest(), source="builtin")
        version = await service.get_listing_version(session, listing.latest_version_id)
        assert version is not None
        # Canonical shape, not whatever the manifest happened to carry: the
        # dashboard's envelope, around a normalized canvas.
        assert version.definition["type"] == "initiative-dashboard"
        assert version.definition["definition"]["kind"] == "dashboard"
        assert version.definition["definition"]["layout"] == {"columns": 12}

    async def test_a_plugin_listing_must_name_a_mountable_tool(self, session):
        """A plug-in definition is narrow on purpose: a kind, and which of this
        build's tools it mounts. It cannot name one we do not mount at guild
        scope."""
        with pytest.raises(CatalogError, match="cannot be mounted"):
            await service.upsert_listing(
                session,
                _manifest(
                    kind="plugin",
                    definition={"plugin_kind": "tool_instance", "tool": "dashboard"},
                ),
                source="builtin",
            )

    async def test_a_listing_without_artwork_gets_the_plugin_mark(self, session):
        """Artwork is optional. A listing that ships none is published with
        Initiative's own mark rather than refused over a picture — and the
        default is same-origin like everything else the catalog stores."""
        manifest = _manifest(
            kind="plugin",
            definition={
                "plugin_kind": "tool_instance",
                "tool": "calendar",
                "default_name": "Community calendar",
            },
        )
        manifest.pop("avatar_url", None)

        listing = await service.upsert_listing(session, manifest, source="builtin")

        assert listing.avatar_url == service.DEFAULT_AVATAR_URL
        assert listing.avatar_url.startswith("/")

    async def test_supplied_artwork_still_has_to_be_same_origin(self, session):
        """The default is not a way in for a remote URL."""
        manifest = _manifest(
            kind="plugin",
            definition={
                "plugin_kind": "tool_instance",
                "tool": "calendar",
                "default_name": "Community calendar",
            },
        )
        manifest["avatar_url"] = "https://cdn.example.test/icon.svg"

        with pytest.raises(CatalogError, match="same-origin"):
            await service.upsert_listing(session, manifest, source="builtin")

    async def test_a_valid_plugin_listing_is_stored_canonically(self, session):
        listing = await service.upsert_listing(
            session,
            _manifest(
                kind="plugin",
                definition={
                    "plugin_kind": "tool_instance",
                    "tool": "calendar",
                    "default_name": "Community calendar",
                    "unexpected": "dropped",
                },
            ),
            source="builtin",
        )
        version = await service.get_listing_version(session, listing.latest_version_id)
        assert version.definition == {
            "plugin_kind": "tool_instance",
            "tool": "calendar",
            "default_name": "Community calendar",
        }

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


class TestArtwork:
    """Artwork must be a same-origin path; anything else is refused."""

    @pytest.mark.parametrize(
        "avatar_url",
        [
            "https://elsewhere.test/logo.png",
            "http://elsewhere.test/logo.png",
            "//elsewhere.test/logo.png",
            "marketplace/relative.svg",
            # Outside the allow-list.
            "/\\elsewhere.test/logo.png",
            "/\telsewhere.test/logo.png",
            "/marketplace/../logo.png",
            "/marketplace//logo.png",
        ],
    )
    async def test_offsite_avatar_is_refused(self, session, avatar_url):
        # Which of the three checks refuses it varies by case; that it names
        # the field is the contract.
        with pytest.raises(CatalogError, match="avatar_url"):
            await service.upsert_listing(
                session, _manifest(avatar_url=avatar_url), source="builtin"
            )

    async def test_offsite_screenshot_is_refused(self, session):
        with pytest.raises(CatalogError, match="images"):
            await service.upsert_listing(
                session,
                _manifest(
                    images=["/marketplace/ok.png", "https://elsewhere.test/x.png"]
                ),
                source="builtin",
            )

    async def test_local_artwork_is_accepted(self, session):
        listing = await service.upsert_listing(
            session,
            _manifest(images=["/marketplace/shot-1.png"]),
            source="builtin",
        )
        assert listing.images == ["/marketplace/shot-1.png"]


class TestVersions:
    async def test_republishing_a_version_unchanged_is_a_no_op(self, session):
        """Boot re-seeds the shipped listings on every start, so publishing the
        same manifest twice has to be harmless."""
        await service.upsert_listing(session, _manifest(), source="builtin")
        listing = await service.upsert_listing(session, _manifest(), source="builtin")
        assert len(await service.listing_versions(session, listing.id)) == 1

    async def test_republishing_a_declarative_plugin_unchanged_is_a_no_op(
        self, session
    ):
        """A declarative plug-in is named by its listing, so its stored version
        is compared under that name too. Without it every registry refresh read
        the version as rewritten and skipped the listing."""
        manifest = _manifest(
            kind="plugin",
            public_id="tests.issues",
            definition=declarative_plugin("tests.issues"),
        )
        await service.upsert_listing(session, manifest, source="registry")
        listing = await service.upsert_listing(session, manifest, source="registry")
        assert len(await service.listing_versions(session, listing.id)) == 1

    async def test_a_declarative_plugins_version_cannot_be_rewritten(self, session):
        definition = declarative_plugin("tests.issues")
        await service.upsert_listing(
            session,
            _manifest(kind="plugin", public_id="tests.issues", definition=definition),
            source="registry",
        )
        changed = json.loads(json.dumps(definition))
        changed["vendor"]["fields"][0]["label"]["en"] = "Application id"
        with pytest.raises(CatalogError, match="already published with different"):
            await service.upsert_listing(
                session,
                _manifest(kind="plugin", public_id="tests.issues", definition=changed),
                source="registry",
            )

    async def test_a_published_version_cannot_be_rewritten(self, session):
        """The definition under a version is frozen once published.

        An instance pins its version, and the upgrade path has nothing to offer
        one already on it — so a changed body under an unchanged version could
        never reach whoever installed it. It would also mean `uid` + version
        named different content on different deployments, which is exactly what
        a shared code must not do.
        """
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="already published with different"):
            await service.upsert_listing(
                session,
                _manifest(
                    definition={
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "table",
                                "binding": {
                                    "source": "query",
                                    "sql": "SELECT count(*) AS n FROM tasks",
                                },
                            }
                        ]
                    }
                ),
                source="builtin",
            )

    async def test_a_published_version_cannot_move_its_plugin_floor(self, session):
        # Changing min_app_version would change who can install that exact
        # version, after the fact.
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="already published with different"):
            await service.upsert_listing(
                session, _manifest(min_app_version="999.0.0"), source="builtin"
            )

    async def test_a_version_saved_before_a_format_default_is_the_same_version(
        self, session
    ):
        """A field the definition format gains takes its default on reading,
        so a version saved before it is not "different content"."""
        listing = await service.upsert_listing(session, _manifest(), source="builtin")
        [stored] = await service.listing_versions(session, listing.id)
        definition = dict(stored.definition)
        assert definition.pop("properties") == []
        stored.definition = definition
        session.add(stored)
        await session.flush()

        await service.upsert_listing(session, _manifest(), source="builtin")

        assert len(await service.listing_versions(session, listing.id)) == 1

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
        assert len(await service.listing_versions(session, listing.id)) == 1

    async def test_a_new_version_becomes_the_latest(self, session):
        await service.upsert_listing(session, _manifest(), source="builtin")
        listing = await service.upsert_listing(
            session, _manifest(version="1.1.0"), source="builtin"
        )
        latest = await service.get_listing_version(session, listing.latest_version_id)
        assert latest is not None and latest.version == "1.1.0"
        assert len(await service.listing_versions(session, listing.id)) == 2

    async def test_a_version_needing_a_newer_plugin_is_not_installable(self, session):
        listing = await create_marketplace_listing(
            session,
            uid="FTRE0000000001",
            public_id="tests.future",
            min_app_version="999.0.0",
        )
        assert await service.resolve_installable_version(session, listing) is None

    async def test_a_version_this_build_can_run_resolves(self, session):
        listing = await create_marketplace_listing(
            session,
            uid="PRESENT0000001",
            public_id="tests.present",
            min_app_version="0.1.0",
        )
        version = await service.resolve_installable_version(session, listing)
        assert version is not None and version.version == "1.0.0"

    async def test_a_prerelease_floor_reads_as_its_release(self):
        # Only ever answers "is this deployment new enough", so 1.2.3-rc1 and
        # 1.2.3 are the same floor.
        assert service.version_is_compatible("0.0.1-rc1") is True
        assert service.version_is_compatible(None) is True


class TestPluginApiFloor:
    """``min_plugin_api``: the oldest plug-in API contract a version needs, as
    its listing says beside ``min_app_version`` or its manifest does."""

    async def _stored(self, session, manifest):
        listing = await service.upsert_listing(session, manifest, source="builtin")
        return await service.get_listing_version(session, listing.latest_version_id)

    async def test_a_listing_s_floor_is_stored_with_its_version(self, session):
        version = await self._stored(session, _manifest(min_plugin_api="4.1"))
        assert version is not None and version.min_plugin_api == "4.1"

    async def test_a_manifest_s_floor_is_stored_too(self, session):
        manifest = _manifest()
        manifest["definition"] = {**manifest["definition"], "min_plugin_api": "4.0"}
        version = await self._stored(session, manifest)
        assert version is not None and version.min_plugin_api == "4.0"

    async def test_a_listing_and_manifest_that_agree_are_taken(self, session):
        manifest = _manifest(min_plugin_api="4.1")
        manifest["definition"] = {**manifest["definition"], "min_plugin_api": "4.1"}
        version = await self._stored(session, manifest)
        assert version is not None and version.min_plugin_api == "4.1"

    async def test_a_listing_and_manifest_that_disagree_are_refused(self, session):
        manifest = _manifest(min_plugin_api="4.1")
        manifest["definition"] = {**manifest["definition"], "min_plugin_api": "4.2"}
        with pytest.raises(CatalogError, match="differs from its manifest"):
            await service.upsert_listing(session, manifest, source="builtin")

    @pytest.mark.parametrize("value", ["4", "4.1.0", "latest", 4])
    async def test_a_floor_that_is_not_major_minor_is_refused(self, session, value):
        with pytest.raises(CatalogError, match="MAJOR.MINOR"):
            await service.upsert_listing(
                session, _manifest(min_plugin_api=value), source="builtin"
            )

    async def test_a_listing_without_one_runs_on_any_contract(self, session):
        version = await self._stored(session, _manifest())
        assert version is not None and version.min_plugin_api is None
        assert service.version_runs_here(version) is True

    async def test_a_published_version_cannot_move_its_floor(self, session):
        await service.upsert_listing(session, _manifest(), source="builtin")
        with pytest.raises(CatalogError, match="already published with different"):
            await service.upsert_listing(
                session, _manifest(min_plugin_api="4.0"), source="builtin"
            )

    async def test_a_version_needing_another_contract_does_not_run_here(self, session):
        version = await self._stored(session, _manifest(min_plugin_api="99.0"))
        assert version is not None
        assert service.version_runs_here(version) is False


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
    async def test_the_counter_records_a_number_and_nothing_else(self, session):
        listing = await create_marketplace_listing(
            session, uid="CNT00000000001", public_id="tests.count"
        )
        assert listing.installs_count == 0
        await service.bump_installs_count(session, listing.id)
        await session.commit()
        await session.refresh(listing)
        assert listing.installs_count == 1

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
    except (OSError, subprocess.CalledProcessError):
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
