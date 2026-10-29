"""What the registry client will and will not take.

Every test builds a real TUF repository in memory with keys generated for it
(``app.testing.tuf_repository``), trusts its root, and serves it through a
fetcher that records every URL it was asked for. Nothing reaches a network.

Grouped by what they defend:

* what a verified repository becomes: publishers, listings, registrations;
* whose rows a refresh may not touch: other sources' listings, an operator's
  publisher, another listing's registration, the deployment facts on a
  registry row;
* what a refusal leaves behind: an expired or unverifiable repository keeps
  the last verified catalog, and a file that fails verification costs its own
  listing only;
* withdrawal, the switch, the root, and the offline bundle.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import PluginServiceMessages
from app.core.messages import MarketplaceRegistryMessages as Codes
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.marketplace_registry import (
    MarketplaceRegistryStatus,
    MarketplaceTufMetadata,
)
from app.models.platform.publisher import Publisher
from app.services.marketplace import registrations as registrations_service
from app.services.marketplace import tuf_registry
from app.services.marketplace.catalog import upsert_listing
from app.services.platform import rules
from app.testing import (
    create_plugin_service_registration,
    create_publisher,
    sample_plugin_jwks,
)
from app.testing.tuf_repository import (
    BASE_URL,
    TufRepository,
    container_registration,
    dashboard_definition,
)


PLUGIN_UID = "ACME0000000001"
BOARD_UID = "ACME0000000002"
OTHER_UID = "ACME0000000003"


@pytest.fixture
def repo() -> TufRepository:
    repository = TufRepository()
    repository.add_publisher("acme", name="Acme Corp", verified=True)
    return repository


def _write_root(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


@pytest.fixture
def trusted(monkeypatch, tmp_path, repo) -> Path:
    """The repository's root is the one this build ships."""
    root = _write_root(tmp_path / "root.json", repo.root_bytes())
    monkeypatch.setattr(tuf_registry, "BUILTIN_ROOT_PATH", root)
    monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_ROOT", None)
    monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_URL", BASE_URL)
    return root


async def _refresh(session: AsyncSession, repo: TufRepository, **kwargs):
    fetcher = repo.fetcher()
    result = await tuf_registry.refresh_registry(session, fetcher=fetcher, **kwargs)
    return result, fetcher


async def _listing(session: AsyncSession, uid: str) -> MarketplaceListing | None:
    session.expire_all()
    return (
        await session.exec(
            select(MarketplaceListing).where(MarketplaceListing.uid == uid)
        )
    ).first()


async def _registration(
    session: AsyncSession, public_id: str
) -> PluginServiceRegistration | None:
    session.expire_all()
    return (
        await session.exec(
            select(PluginServiceRegistration).where(
                PluginServiceRegistration.public_id == public_id
            )
        )
    ).first()


async def _publisher(session: AsyncSession, prefix: str) -> Publisher | None:
    session.expire_all()
    return (
        await session.exec(select(Publisher).where(Publisher.prefix == prefix))
    ).first()


async def _status(session: AsyncSession) -> MarketplaceRegistryStatus | None:
    session.expire_all()
    return await session.get(MarketplaceRegistryStatus, 1)


async def _live(session: AsyncSession, registration_id: int) -> bool:
    views = await registrations_service.registration_views(session, registration_id)
    return views[0].live


# ---------------------------------------------------------------------------
# What a verified repository becomes
# ---------------------------------------------------------------------------


class TestApplying:
    async def test_publishers_listings_and_registrations_land(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker", name="Tracker")
        repo.add_listing("acme", BOARD_UID, slug="board", kind="dashboard")
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        assert result.upserted == 2
        assert result.skipped == []

        publisher = await _publisher(session, "acme")
        assert publisher is not None
        assert publisher.source == "registry"
        assert publisher.display_name == "Acme Corp"
        assert publisher.verified is True
        publisher_id = publisher.id

        plugin = await _listing(session, PLUGIN_UID)
        assert plugin is not None
        assert plugin.source == "registry"
        assert plugin.public_id == "acme.tracker"
        assert plugin.publisher == "Acme Corp"
        assert plugin.publisher_id == publisher_id
        assert plugin.publisher_verified is True
        assert plugin.avatar_url.startswith("/api/v1/marketplace/media/")
        assert len(plugin.images) == 1
        board = await _listing(session, BOARD_UID)
        assert board is not None and board.kind == "dashboard"

        registration = await _registration(session, "acme.tracker")
        assert registration is not None
        assert registration.source == "registry"
        assert registration.listing_uid == PLUGIN_UID
        assert registration.publisher_id == publisher_id
        assert registration.image_digest == "ghcr.io/acme/tracker@sha256:" + "0" * 64
        assert (registration.base_url, registration.jwks) == (None, None)
        assert registration.scope_ceiling == ["projects:read", "projects:write"]

        status = await _status(session)
        assert status is not None
        assert status.last_error is None
        assert status.listing_count == 2
        assert status.root_version == 1

    async def test_versions_land_oldest_first_with_the_last_as_latest(
        self, session, repo, trusted
    ):
        repo.add_listing(
            "acme",
            BOARD_UID,
            slug="board",
            kind="dashboard",
            versions=("1.0.0", "1.1.0"),
        )
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        listing = await _listing(session, BOARD_UID)
        assert listing is not None
        latest = await session.get(MarketplaceListingVersion, listing.latest_version_id)
        assert latest is not None and latest.version == "1.1.0"

    async def test_a_container_is_not_live_until_the_operator_places_it(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        await _refresh(session, repo)
        registration = await _registration(session, "acme.tracker")
        assert registration is not None and registration.id is not None
        assert await _live(session, registration.id) is False

        await registrations_service.update_registration(
            session, registration.id, base_url="https://tracker.internal.test"
        )
        assert await _live(session, registration.id) is False

        await registrations_service.update_registration(
            session, registration.id, jwks=sample_plugin_jwks()
        )
        assert await _live(session, registration.id) is True

    async def test_a_hosted_plugin_is_refused(self, session, repo, trusted):
        hosted = container_registration(kind="hosted", base_url=BASE_URL)
        del hosted["image"]
        repo.add_listing("acme", PLUGIN_UID, slug="tracker", registration=hosted)
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert [item.code for item in result.skipped] == [Codes.LISTING_REJECTED]
        assert await _listing(session, PLUGIN_UID) is None
        assert await _registration(session, "acme.tracker") is None

    async def test_the_ceiling_keeps_only_scopes_this_build_defines(
        self, session, repo, trusted
    ):
        repo.add_listing(
            "acme",
            PLUGIN_UID,
            slug="tracker",
            registration=container_registration(
                scope_ceiling=["projects:read", "starships:write"]
            ),
        )
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        registration = await _registration(session, "acme.tracker")
        assert registration is not None
        assert registration.scope_ceiling == ["projects:read"]

    async def test_a_kind_this_build_does_not_carry_is_passed_over(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", OTHER_UID, slug="pack", kind="art_pack")
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        assert result.skipped == []
        assert await _listing(session, OTHER_UID) is None

    async def test_an_unchanged_repository_is_not_read_again(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        await _refresh(session, repo)

        result, fetcher = await _refresh(session, repo)

        assert result.ok and result.unchanged
        assert not any("listing.json" in url for url in fetcher.requested)

    async def test_the_verified_metadata_is_kept_and_a_root_rotation_followed(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        await _refresh(session, repo)

        repo.rotate_timestamp_key()
        repo.publish()
        result, _ = await _refresh(session, repo)

        assert result.ok, result
        assert result.root_version == 2
        rows = (await session.exec(select(MarketplaceTufMetadata))).all()
        roles = {(row.role, row.version) for row in rows}
        assert ("root", 2) in roles
        assert {row.role for row in rows} >= {
            "root",
            "timestamp",
            "snapshot",
            "targets",
        }


# ---------------------------------------------------------------------------
# Whose rows a refresh leaves alone
# ---------------------------------------------------------------------------


class TestOtherSources:
    async def test_a_listing_another_source_published_is_not_taken_over(
        self, session, repo, trusted
    ):
        await upsert_listing(
            session,
            {
                "uid": BOARD_UID,
                "public_id": "acme.board",
                "kind": "dashboard",
                "name": "Our own board",
                "publisher": "This deployment",
                "description": "Uploaded here.",
                "version": "1.0.0",
                "definition": dashboard_definition(),
            },
            source="local",
        )
        await session.commit()
        repo.add_listing("acme", BOARD_UID, slug="board", kind="dashboard")
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert [item.code for item in result.skipped] == [Codes.SOURCE_CONFLICT]
        listing = await _listing(session, BOARD_UID)
        assert listing is not None
        assert listing.source == "local"
        assert listing.name == "Our own board"

    async def test_an_operators_publisher_wins(self, session, repo, trusted):
        await create_publisher(session, prefix="acme", display_name="Ours")
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert [item.code for item in result.skipped] == [Codes.PUBLISHER_CONFLICT]
        publisher = await _publisher(session, "acme")
        assert publisher is not None and publisher.display_name == "Ours"
        assert await _listing(session, PLUGIN_UID) is None

    async def test_the_seeded_publisher_is_kept_up_to_date_but_not_switched_on(
        self, session, repo, trusted
    ):
        await create_publisher(
            session,
            prefix="beyonders-studio",
            display_name="Seeded",
            enabled=False,
            source="seed",
        )
        repo.add_publisher("beyonders-studio", name="BeyondersStudio")
        repo.add_listing("beyonders-studio", "MRXT0000000001", slug="github")
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        publisher = await _publisher(session, "beyonders-studio")
        assert publisher is not None
        assert publisher.display_name == "BeyondersStudio"
        assert publisher.enabled is False

    async def test_a_registration_another_listing_holds_is_not_taken(
        self, session, repo, trusted
    ):
        await create_publisher(session, prefix="acme", source="registry")
        await create_plugin_service_registration(
            session, public_id="acme.tracker", listing_uid=OTHER_UID
        )
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert [item.code for item in result.skipped] == [Codes.SOURCE_CONFLICT]
        registration = await _registration(session, "acme.tracker")
        assert registration is not None
        assert (registration.source, registration.listing_uid) == (
            "operator",
            OTHER_UID,
        )

    async def test_the_registry_fills_in_a_registration_set_up_before_it(
        self, session, repo, trusted
    ):
        await create_publisher(session, prefix="acme", source="registry")
        set_up = await create_plugin_service_registration(
            session, public_id="acme.tracker", mandatory=True
        )
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.skipped == []
        registration = await _registration(session, "acme.tracker")
        assert registration is not None and registration.id == set_up.id
        assert (registration.source, registration.listing_uid) == (
            "registry",
            PLUGIN_UID,
        )
        assert registration.scope_ceiling == ["projects:read", "projects:write"]
        assert (registration.base_url, registration.mandatory) == (
            set_up.base_url,
            True,
        )
        assert await _live(session, registration.id) is True

    async def test_the_operators_deployment_facts_survive_a_refresh(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        await _refresh(session, repo)
        registration = await _registration(session, "acme.tracker")
        assert registration is not None and registration.id is not None

        with pytest.raises(HTTPException) as refused:
            await registrations_service.delete_registration(session, registration.id)
        assert refused.value.status_code == 409
        assert refused.value.detail == PluginServiceMessages.REGISTRY_MANAGED

        await registrations_service.update_registration(
            session,
            registration.id,
            base_url="https://tracker.internal.test",
            jwks=sample_plugin_jwks(),
            mandatory=True,
            enabled=False,
        )
        repo.publish()
        await _refresh(session, repo, force=True)
        registration = await _registration(session, "acme.tracker")
        assert registration is not None
        assert (registration.enabled, registration.mandatory) == (False, True)
        assert registration.base_url == "https://tracker.internal.test"
        assert registration.jwks == sample_plugin_jwks()

    async def test_an_entry_places_the_container_and_the_registry_keeps_the_rest(
        self, session, repo, trusted, monkeypatch, tmp_path
    ):
        """The entry gives what this deployment knows (where the container
        runs, the key its pod signs with, whether every community gets it);
        the registry keeps the rest, and later refreshes keep applying."""
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        await _refresh(session, repo)
        config = tmp_path / "plugins.json"
        config.write_text(
            json.dumps(
                [
                    {
                        "public_id": "acme.tracker",
                        "base_url": "http://tracker.internal.test:8080",
                        "allowed_origins": ["https://initiative.example.test"],
                        "jwks": sample_plugin_jwks(),
                        "mandatory": True,
                    }
                ]
            )
        )
        monkeypatch.setattr(settings, "PLUGIN_SERVICES_CONFIG", str(config))

        reconciled = await registrations_service.reconcile_from_config(session)
        assert (reconciled.updated, reconciled.skipped) == (1, 0)
        registration = await _registration(session, "acme.tracker")
        assert registration is not None and registration.id is not None
        assert registration.source == "registry"
        assert registration.image_digest is not None
        assert registration.base_url == "http://tracker.internal.test:8080"
        assert registration.allowed_origins == ["https://initiative.example.test"]
        assert registration.mandatory is True
        assert await _live(session, registration.id) is True

        repo.publish()
        result, _ = await _refresh(session, repo, force=True)
        assert result.skipped == []
        registration = await _registration(session, "acme.tracker")
        assert registration is not None
        assert registration.jwks == sample_plugin_jwks()
        assert registration.scope_ceiling == ["projects:read", "projects:write"]

    async def test_an_entry_waits_for_the_registry_to_bring_its_plugin(
        self, session, repo, trusted, monkeypatch, tmp_path
    ):
        config = tmp_path / "plugins.json"
        config.write_text(
            json.dumps(
                [
                    {
                        "public_id": "acme.tracker",
                        "base_url": "http://tracker.internal.test:8080",
                        "jwks": sample_plugin_jwks(),
                    }
                ]
            )
        )
        monkeypatch.setattr(settings, "PLUGIN_SERVICES_CONFIG", str(config))
        reconciled = await registrations_service.reconcile_from_config(session)
        assert (reconciled.updated, reconciled.waiting) == (0, 1)
        assert await _registration(session, "acme.tracker") is None

        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        result, _ = await _refresh(session, repo)

        assert result.skipped == []
        registration = await _registration(session, "acme.tracker")
        assert registration is not None and registration.id is not None
        assert registration.source == "registry"
        assert registration.base_url == "http://tracker.internal.test:8080"
        assert registration.jwks == sample_plugin_jwks()
        assert await _live(session, registration.id) is True


# ---------------------------------------------------------------------------
# Refusals keep the last verified state
# ---------------------------------------------------------------------------


class TestRefusals:
    async def test_an_expired_timestamp_is_refused_and_the_catalog_kept(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker", name="Tracker")
        repo.publish()
        await _refresh(session, repo)
        first_success = (await _status(session)).last_success_at

        repo.add_listing("acme", PLUGIN_UID, slug="tracker", name="Renamed")
        repo.publish(timestamp_expires=datetime.now(timezone.utc) - timedelta(hours=1))
        result, _ = await _refresh(session, repo)

        assert result.code == Codes.EXPIRED
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.name == "Tracker"
        status = await _status(session)
        assert status is not None
        assert status.last_error == Codes.EXPIRED
        assert status.last_success_at == first_success

    async def test_tampered_metadata_is_refused(self, session, repo, trusted):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        path = "metadata/1.acme.json"
        repo.files[path] = repo.files[path].replace(b"listing.json", b"listing.jsoN", 1)

        result, _ = await _refresh(session, repo)

        # The publisher's role no longer verifies; nothing of it lands.
        assert [(item.name, item.code) for item in result.skipped] == [
            ("acme", Codes.METADATA_REJECTED)
        ]
        assert await _listing(session, PLUGIN_UID) is None

    async def test_a_tampered_top_level_role_refuses_the_whole_repository(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        path = "metadata/1.targets.json"
        repo.files[path] = repo.files[path].replace(b'"acme"', b'"acmf"', 1)

        result, _ = await _refresh(session, repo)

        assert result.code == Codes.METADATA_REJECTED
        assert await _listing(session, PLUGIN_UID) is None

    async def test_a_tampered_target_costs_its_listing_and_nothing_else(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker", name="Tracker")
        repo.add_listing("acme", BOARD_UID, slug="board", kind="dashboard")
        repo.publish()
        await _refresh(session, repo)

        repo.add_listing("acme", PLUGIN_UID, slug="tracker", name="Renamed")
        repo.publish()
        served = repo.served_path(f"publishers/acme/{PLUGIN_UID}/listing.json", "acme")
        repo.files[served] = repo.files[served].replace(b"Renamed", b"Changed")
        result, _ = await _refresh(session, repo)

        assert [item.code for item in result.skipped] == [Codes.TARGET_REJECTED]
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None
        assert listing.name == "Tracker"
        assert listing.available is True
        board = await _listing(session, BOARD_UID)
        assert board is not None and board.available is True

    async def test_a_publisher_whose_role_expired_is_unknown_not_withdrawn(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        await _refresh(session, repo)

        repo.publish(publisher_expires=datetime.now(timezone.utc) - timedelta(days=1))
        result, _ = await _refresh(session, repo)

        assert [(item.name, item.code) for item in result.skipped] == [
            ("acme", Codes.EXPIRED)
        ]
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.available is True


# ---------------------------------------------------------------------------
# Withdrawal
# ---------------------------------------------------------------------------


class TestWithdrawal:
    async def test_a_listing_that_leaves_is_withdrawn_and_kept(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.add_listing("acme", BOARD_UID, slug="board", kind="dashboard")
        repo.publish()
        await _refresh(session, repo)

        repo.remove_listing("acme", PLUGIN_UID)
        repo.publish()
        result, _ = await _refresh(session, repo)

        assert result.ok, result
        assert result.withdrawn == 1
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.available is False
        registration = await _registration(session, "acme.tracker")
        assert registration is not None and registration.enabled is False
        board = await _listing(session, BOARD_UID)
        assert board is not None and board.available is True


# ---------------------------------------------------------------------------
# The switch and the root
# ---------------------------------------------------------------------------


class TestConfiguration:
    async def test_switched_off_nothing_is_fetched(self, session, repo, trusted):
        await rules.put(session, "marketplace_registry_enabled", False)
        await session.commit()
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()

        result, fetcher = await _refresh(session, repo)

        assert result.ran is False
        assert result.code == Codes.DISABLED
        assert fetcher.requested == []
        assert await _listing(session, PLUGIN_UID) is None

    async def test_a_placeholder_root_is_not_configured(
        self, session, repo, trusted, monkeypatch, tmp_path
    ):
        placeholder = _write_root(
            tmp_path / "placeholder.json", b'{"placeholder": "no root yet"}'
        )
        monkeypatch.setattr(tuf_registry, "BUILTIN_ROOT_PATH", placeholder)
        repo.publish()

        result, fetcher = await _refresh(session, repo)

        assert tuf_registry.registry_available() is False
        assert result.code == Codes.NOT_CONFIGURED
        assert fetcher.requested == []

    async def test_a_replaced_root_is_not_the_builtin_one(
        self, session, repo, trusted, monkeypatch, tmp_path
    ):
        other = TufRepository()
        monkeypatch.setattr(
            tuf_registry,
            "BUILTIN_ROOT_PATH",
            _write_root(tmp_path / "shipped.json", other.root_bytes()),
        )
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_ROOT", str(trusted))
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        assert tuf_registry.configured_root_is_builtin() is False

    async def test_a_repository_signed_under_another_root_is_refused(
        self, session, trusted, monkeypatch
    ):
        stranger = TufRepository()
        stranger.add_publisher("acme")
        stranger.add_listing("acme", PLUGIN_UID, slug="tracker")
        stranger.publish()

        result, _ = await _refresh(session, stranger)

        assert result.code == Codes.METADATA_REJECTED
        assert await _listing(session, PLUGIN_UID) is None

    def test_the_shipped_root_is_the_registrys_first_root(self):
        """The image carries a real root, so a fresh deployment follows the
        registry out of the box."""
        anchor = tuf_registry.load_trust_anchor()
        assert anchor is not None
        assert anchor.builtin is True
        assert anchor.version == 1


# ---------------------------------------------------------------------------
# Fetching over the network
# ---------------------------------------------------------------------------


class TestFetching:
    @pytest.mark.parametrize(
        ("token", "url", "authorization"),
        [
            ("t0ken", f"{BASE_URL}metadata/timestamp.json", "Bearer t0ken"),
            ("t0ken", "https://other.example/metadata/timestamp.json", None),
            ("t0ken", "https://registry.test:8443/public/metadata/x.json", None),
            (None, f"{BASE_URL}metadata/timestamp.json", None),
        ],
        ids=["registry origin", "another host", "another port", "unset"],
    )
    async def test_the_token_goes_only_to_the_registry_origin(
        self, monkeypatch, token, url, authorization
    ):
        sent: dict[str, str] = {}

        async def request(method, target, *, headers, **kwargs):
            sent.update(headers)
            return httpx.Response(200, content=b"{}")

        monkeypatch.setattr(tuf_registry, "request_public_target", request)
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_URL", BASE_URL)
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_TOKEN", token)

        assert await tuf_registry._get(url) == b"{}"
        assert sent.get("Authorization") == authorization


# ---------------------------------------------------------------------------
# The offline bundle
# ---------------------------------------------------------------------------


class TestBundle:
    async def test_a_bundle_applies_like_a_fetch(self, session, repo, trusted):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()

        result = await tuf_registry.apply_bundle(session, repo.bundle())

        assert result.ok, result
        assert result.upserted == 1
        assert await _listing(session, PLUGIN_UID) is not None
        status = await _status(session)
        assert status is not None and status.source == tuf_registry.BUNDLE_SOURCE

    async def test_a_bundle_applies_with_the_switch_off(self, session, repo, trusted):
        await rules.put(session, "marketplace_registry_enabled", False)
        await session.commit()
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()

        result = await tuf_registry.apply_bundle(session, repo.bundle())

        assert result.ok, result

    async def test_a_tampered_bundle_is_refused(self, session, repo, trusted):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        path = "metadata/1.targets.json"
        repo.files[path] = repo.files[path].replace(b'"acme"', b'"acmf"', 1)

        result = await tuf_registry.apply_bundle(session, repo.bundle())

        assert result.code == Codes.METADATA_REJECTED
        assert await _listing(session, PLUGIN_UID) is None

    async def test_something_that_is_not_a_bundle_is_refused(self, session, trusted):
        with pytest.raises(tuf_registry.RegistryError) as refused:
            await tuf_registry.apply_bundle(session, b"not a tar archive")
        assert refused.value.code == Codes.BUNDLE_INVALID

    def test_a_member_outside_the_repository_is_refused(self):
        import io
        import tarfile

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo(name="../metadata/timestamp.json")
            info.size = 2
            tar.addfile(info, io.BytesIO(b"{}"))
        with pytest.raises(tuf_registry.RegistryError) as refused:
            tuf_registry.read_bundle(buffer.getvalue())
        assert refused.value.code == Codes.BUNDLE_INVALID


# ---------------------------------------------------------------------------
# A package's terms
# ---------------------------------------------------------------------------


def _terms(uid: str = PLUGIN_UID, **overrides):
    return {
        "listing_uid": uid,
        "access": "entitled",
        "mandatory": False,
        "meters": [],
        **overrides,
    }


MANDATORY_TERMS = {"access": "open", "mandatory": True, "meters": ["runs"]}


class TestPackageTerms:
    async def test_terms_land_on_the_listing_under_the_shipped_root(
        self, session, repo, trusted
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.add_listing("acme", OTHER_UID, slug="other")
        repo.set_terms(PLUGIN_UID, _terms())
        repo.set_terms(OTHER_UID, _terms(OTHER_UID, **MANDATORY_TERMS))
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        paid = await _listing(session, PLUGIN_UID)
        assert paid is not None
        assert (paid.access, paid.mandatory, paid.meters) == ("entitled", False, [])
        metered = await _listing(session, OTHER_UID)
        assert metered is not None
        assert (metered.access, metered.mandatory, metered.meters) == (
            "open",
            True,
            ["runs"],
        )

    async def test_terms_are_not_honoured_under_another_root(
        self, session, repo, trusted, monkeypatch, tmp_path
    ):
        other = TufRepository()
        monkeypatch.setattr(
            tuf_registry,
            "BUILTIN_ROOT_PATH",
            _write_root(tmp_path / "shipped.json", other.root_bytes()),
        )
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_ROOT", str(trusted))
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.set_terms(PLUGIN_UID, _terms(**MANDATORY_TERMS))
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None
        assert (listing.access, listing.mandatory, listing.meters) == (None, False, [])

    async def test_terms_a_root_change_leaves_are_dropped(
        self, session, repo, trusted, monkeypatch, tmp_path
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.set_terms(PLUGIN_UID, _terms())
        repo.publish()
        await _refresh(session, repo)
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.access == "entitled"

        other = TufRepository()
        monkeypatch.setattr(
            tuf_registry,
            "BUILTIN_ROOT_PATH",
            _write_root(tmp_path / "shipped.json", other.root_bytes()),
        )
        monkeypatch.setattr(settings, "MARKETPLACE_REGISTRY_ROOT", str(trusted))
        result, _ = await _refresh(session, repo)

        assert result.ok, result
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.access is None

    async def test_a_delegation_with_no_role_file_means_no_terms(
        self, session, repo, trusted
    ):
        """The public index delegates the role and publishes no file for it."""
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.add_package(publish_role=False)
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        assert result.skipped == []
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.access is None

    @pytest.mark.parametrize(
        "bad",
        [
            {"access": "entitled", "mandatory": True},
            {"access": "entitled", "meters": ["runs"]},
            {"access": "open", "mandatory": False},
            {"access": "open", "mandatory": False, "meters": ["runs"]},
            {"access": "paid"},
            {"mandatory": "yes"},
            {"meters": ["Runs"]},
            {"meters": ["runs", "runs"], "access": "open", "mandatory": True},
            {"listing_uid": OTHER_UID},
            {"price": 5},
        ],
    )
    async def test_terms_outside_the_two_shapes_are_refused(
        self, session, repo, trusted, bad
    ):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.set_terms(PLUGIN_UID, _terms(**bad))
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert [entry.code for entry in result.skipped] == [Codes.TERMS_INVALID]
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.access is None

    async def test_refused_terms_keep_the_ones_held(self, session, repo, trusted):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.set_terms(PLUGIN_UID, _terms())
        repo.publish()
        await _refresh(session, repo)

        repo.set_terms(PLUGIN_UID, _terms(mandatory=True))
        repo.publish()
        result, _ = await _refresh(session, repo)

        assert [entry.code for entry in result.skipped] == [Codes.TERMS_INVALID]
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.access == "entitled"

    async def test_a_package_role_that_does_not_verify_keeps_every_term(
        self, session, repo, trusted
    ):
        from securesystemslib.signer import CryptoSigner

        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.set_terms(PLUGIN_UID, _terms())
        repo.publish()
        await _refresh(session, repo)

        repo.package_signed_by = CryptoSigner.generate_ed25519()
        repo.remove_terms(PLUGIN_UID)
        repo.publish()
        result, _ = await _refresh(session, repo)

        assert [entry.name for entry in result.skipped] == ["package"]
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.access == "entitled"

    async def test_terms_a_package_drops_are_dropped(self, session, repo, trusted):
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.set_terms(PLUGIN_UID, _terms())
        repo.publish()
        await _refresh(session, repo)

        repo.remove_terms(PLUGIN_UID)
        repo.publish()
        result, _ = await _refresh(session, repo)

        assert result.ok, result
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.access is None

    async def test_a_publisher_cannot_sign_terms(self, session, repo, trusted):
        """Terms are read from the package role alone: a publisher's own role
        listing an ``entitlements/`` path gives nothing."""
        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.content["acme"][f"entitlements/{PLUGIN_UID}.json"] = json.dumps(
            _terms(**MANDATORY_TERMS)
        ).encode()
        repo.add_package()
        repo.publish()

        result, _ = await _refresh(session, repo)

        assert result.ok, result
        listing = await _listing(session, PLUGIN_UID)
        assert listing is not None and listing.access is None

    async def test_the_package_makes_a_listing_mandatory_whatever_the_registration_says(
        self, session, repo, trusted
    ):
        from app.services.marketplace import registration_lookup

        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.set_terms(PLUGIN_UID, _terms(**MANDATORY_TERMS))
        repo.publish()
        await _refresh(session, repo)
        registration = await _registration(session, "acme.tracker")
        assert registration is not None
        # The operator clears the flag on the registration.
        registration.mandatory = False
        session.add(registration)
        await session.commit()

        snapshots = await registration_lookup.load_registrations(force=True)

        assert snapshots["acme.tracker"].mandatory is True

    async def test_a_listing_without_terms_follows_the_registration(
        self, session, repo, trusted
    ):
        from app.services.marketplace import registration_lookup

        repo.add_listing("acme", PLUGIN_UID, slug="tracker")
        repo.publish()
        await _refresh(session, repo)

        snapshots = await registration_lookup.load_registrations(force=True)

        assert snapshots["acme.tracker"].mandatory is False
