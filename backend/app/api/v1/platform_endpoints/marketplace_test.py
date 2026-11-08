"""The routes that maintain the catalog.

Reading the marketplace is guild-addressed and covered by
``tenant_endpoints/marketplace_test.py``: what a guild is offered depends on
which plug-ins it has installed.

What is left here is the operator's rescan of their own catalog directory —
deployment configuration rather than content, so it sits at the top of the
ladder with everything else that decides what this deployment is.
"""

import json

import pytest

from app.core.config import settings
from app.core.messages import MarketplaceMessages
from app.models.platform.guild import CommunityRole
from app.testing.tuf_repository import service_plugin_definition

RESCAN_URL = "/api/v1/marketplace/operator-catalog/rescan"


def _manifest(**overrides) -> dict:
    manifest = {
        "uid": "0PRT0R00000001",
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


@pytest.fixture
def catalog_dir(tmp_path, monkeypatch):
    directory = tmp_path / "marketplace"
    directory.mkdir()
    monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", str(directory))
    return directory


class TestOperatorRescan:
    """Picking up a file that was dropped in, without a restart.

    The same scan the boot runs, so what an operator sees here is what a
    restart would have given them.
    """

    async def test_a_dropped_file_appears_without_a_restart(
        self, client, acting_user, catalog_dir
    ):
        (catalog_dir / "standup.json").write_text(
            json.dumps(_manifest()), encoding="utf-8"
        )
        # An operator who is also in a guild, so the listing can be read back
        # from the marketplace the way anyone would meet it.
        actor = await acting_user("owner", guild_role=CommunityRole.admin)

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 200
        assert response.json()["published"] == 1
        assert response.json()["problems"] == []

        page = await client.get(
            actor.g("/marketplace/listings/acme.standup"), headers=actor.headers
        )
        assert page.status_code == 200
        # Provenance travels with the listing: the marketplace shows this as
        # the operator's own addition, never as something shipped from here.
        assert page.json()["source"] == "operator"

    async def test_a_rescan_is_idempotent(self, client, acting_user, catalog_dir):
        (catalog_dir / "standup.json").write_text(
            json.dumps(_manifest()), encoding="utf-8"
        )
        actor = await acting_user("owner")

        first = await client.post(RESCAN_URL, headers=actor.headers)
        second = await client.post(RESCAN_URL, headers=actor.headers)

        assert first.json() == second.json()
        assert second.json()["withdrawn"] == 0

    async def test_a_skipped_file_is_reported_by_name(
        self, client, acting_user, catalog_dir
    ):
        """The operator who just edited the file is the one reading this, so
        the answer names the file rather than sending them to the server log."""
        (catalog_dir / "broken.json").write_text("{ not json", encoding="utf-8")
        actor = await acting_user("owner")

        response = await client.post(RESCAN_URL, headers=actor.headers)

        body = response.json()
        assert body["skipped"] == 1
        assert body["problems"][0]["file"] == "broken.json"
        assert body["problems"][0]["reason"]

    async def test_no_directory_configured_is_a_400(
        self, client, acting_user, monkeypatch
    ):
        monkeypatch.setattr(settings, "MARKETPLACE_EXTRA_CATALOG_DIR", None)
        actor = await acting_user("owner")

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == MarketplaceMessages.OPERATOR_CATALOG_NOT_CONFIGURED
        )

    async def test_a_directory_that_did_not_mount_is_a_400(
        self, client, acting_user, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            settings, "MARKETPLACE_EXTRA_CATALOG_DIR", str(tmp_path / "absent")
        )
        actor = await acting_user("owner")

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == MarketplaceMessages.OPERATOR_CATALOG_DIR_MISSING
        )

    @pytest.mark.parametrize("tier", ["member", "support", "moderator", "operator"])
    async def test_only_the_config_capability_may_rescan(
        self, client, acting_user, catalog_dir, tier
    ):
        """Publishing a listing decides what this deployment offers everyone
        on it, so it sits with app-wide configuration rather than with the
        tiers that read or moderate."""
        actor = await acting_user(tier)

        response = await client.post(RESCAN_URL, headers=actor.headers)

        assert response.status_code == 403

    async def test_a_rescan_needs_a_session(self, client, catalog_dir):
        assert (await client.post(RESCAN_URL)).status_code == 401


UPLOAD_URL = "/api/v1/marketplace/local/upload"


def _counter_manifest(**overrides) -> dict:
    return {
        "uid": "VPR0AD00000001",
        "public_id": "ours.party-tally",
        "kind": "counter_group",
        "name": "Party tally",
        "publisher": "Our deployment",
        "description": "Keep score.",
        "version": "1.0.0",
        "definition": {
            "type": "initiative-counter-group",
            "name": "Tally",
            "counters": [{"name": "Hit points", "count": 0}],
        },
        **overrides,
    }


def _plugin_manifest(**overrides) -> dict:
    return _counter_manifest(
        uid="VPR0ADAPP00001",
        public_id="ours.tracker",
        kind="plugin",
        name="Tracker",
        definition=service_plugin_definition("ours.tracker"),
        **overrides,
    )


class TestUploadingAListingFile:
    async def test_the_owner_publishes_a_file_as_a_local_listing(
        self, client, acting_user
    ):
        owner = await acting_user("owner", guild_role=CommunityRole.member)

        response = await client.post(
            UPLOAD_URL, json={"manifest": _counter_manifest()}, headers=owner.headers
        )

        assert response.status_code == 201, response.text
        assert response.json()["version"] == "1.0.0"
        shelf = await client.get(
            owner.g("/marketplace/listings"),
            params={"kind": "counter_group"},
            headers=owner.headers,
        )
        [card] = [
            item for item in shelf.json()["items"] if item["uid"] == "VPR0AD00000001"
        ]
        assert card["source"] == "local"

    async def test_a_file_it_will_not_take_says_why(self, client, acting_user):
        owner = await acting_user("owner")

        response = await client.post(
            UPLOAD_URL,
            json={"manifest": _counter_manifest(definition={"type": "nope"})},
            headers=owner.headers,
        )

        assert response.status_code == 422
        assert response.json()["detail"] == MarketplaceMessages.LISTING_UPLOAD_INVALID
        assert "initiative-counter-group" in response.json()["problem"]

    async def test_a_uid_another_catalogue_publishes_is_not_taken_over(
        self, client, acting_user, session
    ):
        from app.testing import create_marketplace_listing

        await create_marketplace_listing(
            session, uid="VPR0AD00000001", public_id="core.shipped"
        )
        owner = await acting_user("owner")

        response = await client.post(
            UPLOAD_URL, json={"manifest": _counter_manifest()}, headers=owner.headers
        )

        assert response.status_code == 422
        assert "builtin" in response.json()["problem"]

    async def test_a_private_plugins_listing_brings_its_registration(
        self, client, acting_user
    ):
        """Adding a private plug-in is uploading its listing, then giving it
        deployment facts under Plug-in services."""
        owner = await acting_user("owner")
        manifest = _plugin_manifest(
            registration={"kind": "container", "scope_ceiling": ["projects:read"]}
        )

        response = await client.post(
            UPLOAD_URL, json={"manifest": manifest}, headers=owner.headers
        )

        assert response.status_code == 201, response.text
        services = await client.get("/api/v1/plugin-services/", headers=owner.headers)
        [registration] = services.json()
        assert registration["public_id"] == "ours.tracker"
        assert registration["listing_uid"] == manifest["uid"]
        assert registration["scope_ceiling"] == ["projects:read"]
        assert registration["live"] is False

    @pytest.mark.parametrize("tier", ["operator", "member"])
    async def test_uploading_is_the_owners(self, client, acting_user, tier):
        actor = await acting_user(tier)

        response = await client.post(
            UPLOAD_URL, json={"manifest": _counter_manifest()}, headers=actor.headers
        )

        assert response.status_code == 403

    async def test_a_rescan_leaves_local_listings_alone(
        self, client, acting_user, catalog_dir
    ):
        owner = await acting_user("owner")
        await client.post(
            UPLOAD_URL, json={"manifest": _counter_manifest()}, headers=owner.headers
        )

        scan = await client.post(RESCAN_URL, headers=owner.headers)

        assert scan.status_code == 200, scan.text
        assert scan.json()["withdrawn"] == 0
