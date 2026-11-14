"""Installing a dashboard from the catalog, and taking a later version.

Two properties carry the weight here.

The first is that installing is a *server-side copy*. A client names a listing;
the body comes from the catalog row, so what lands in a guild's schema is the
definition that listing published.

The second is that nothing is ever pushed. A new version sits in the catalog
until someone with write access on that one dashboard asks for it, and applying
it re-pins that instance alone — other installs of the same listing, in this
guild or any other, keep the version they chose.
"""

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import MarketplaceMessages
from app.models.platform.guild import CommunityRole
from app.services.marketplace.plugin_api import PLUGIN_API_VERSION
from app.testing import create_marketplace_listing, marketplace_uid, route_as

INSTALL_UID = marketplace_uid("sprinthealth")
WITHDRAWN_UID = marketplace_uid("withdrawn")
TOO_NEW_UID = marketplace_uid("toonew")
OTHER_API_UID = marketplace_uid("otherapi")


def _definition(
    widget_type: str = "stat", sql: str = "SELECT count(*) AS tasks FROM tasks"
) -> dict:
    """A canvas of one widget, bound the only way a binding is bound.

    The statement is checked when a definition is stored, so it has to be one
    the query surface will run — a listing that ships an unreadable one is not
    installable, which is a different test from any of these."""
    return {
        "widgets": [
            {
                "id": "w1",
                "type": widget_type,
                "binding": {"source": "query", "sql": sql},
            }
        ]
    }


async def _enable(session: AsyncSession, initiative) -> None:
    initiative.dashboards_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


@pytest.fixture
async def listing(session):
    return await create_marketplace_listing(
        session,
        uid=INSTALL_UID,
        public_id="tests.install",
        name="Sprint health",
        definition=_definition(),
    )


class TestInstall:
    async def test_installing_pins_the_listing_and_its_version(
        self, client: AsyncClient, acting_user, session, listing
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        response = await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "Sprint health",
                "initiative_id": a.initiative.id,
                "listing_uid": INSTALL_UID,
            },
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["listing_uid"] == INSTALL_UID
        assert body["listing_version"] == "1.0.0"
        assert body["definition"]["widgets"][0]["type"] == "stat"
        assert body["can"]["delete"] is True

    async def test_the_body_comes_from_the_catalog_not_the_request(
        self, client: AsyncClient, acting_user, session, listing
    ):
        """Naming a listing and *also* sending a definition installs the
        listing's. Provenance records what the server resolved, not what the
        request contained."""
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        response = await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "Sprint health",
                "initiative_id": a.initiative.id,
                "listing_uid": INSTALL_UID,
                "definition": _definition(widget_type="table"),
            },
        )

        assert response.status_code == 201, response.text
        assert response.json()["definition"]["widgets"][0]["type"] == "stat"

    async def test_an_unknown_listing_is_a_404(
        self, client: AsyncClient, acting_user, session
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        response = await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "Nope",
                "initiative_id": a.initiative.id,
                "listing_uid": marketplace_uid("nothere"),
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_a_withdrawn_listing_cannot_be_installed(
        self, client: AsyncClient, acting_user, session
    ):
        await create_marketplace_listing(
            session, uid=WITHDRAWN_UID, public_id="tests.gone2", available=False
        )
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        response = await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "Gone",
                "initiative_id": a.initiative.id,
                "listing_uid": WITHDRAWN_UID,
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"] == MarketplaceMessages.LISTING_UNAVAILABLE

    async def test_a_listing_needing_a_newer_app_is_refused(
        self, client: AsyncClient, acting_user, session
    ):
        await create_marketplace_listing(
            session,
            uid=TOO_NEW_UID,
            public_id="tests.toonew2",
            min_app_version="999.0.0",
        )
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        response = await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "Too new",
                "initiative_id": a.initiative.id,
                "listing_uid": TOO_NEW_UID,
            },
        )
        # Refused rather than quietly installing an older version: the guild
        # would get something other than the listing page showed them.
        assert response.status_code == 409
        assert (
            response.json()["detail"]
            == MarketplaceMessages.LISTING_VERSION_INCOMPATIBLE
        )

    async def test_a_listing_needing_a_plugin_api_not_served_here_is_refused(
        self, client: AsyncClient, acting_user, session
    ):
        """A version built against a plug-in API contract this deployment
        does not serve (another major, or a newer minor) is refused, with
        words of its own."""
        await create_marketplace_listing(
            session,
            uid=OTHER_API_UID,
            public_id="tests.otherapi",
            min_plugin_api="99.0",
        )
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        response = await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "Other API",
                "initiative_id": a.initiative.id,
                "listing_uid": OTHER_API_UID,
            },
        )
        assert response.status_code == 409
        assert (
            response.json()["detail"]
            == MarketplaceMessages.LISTING_PLUGIN_API_INCOMPATIBLE
        )

    async def test_a_listing_needing_the_plugin_api_served_here_installs(
        self, client: AsyncClient, acting_user, session
    ):
        major, minor, *_ = PLUGIN_API_VERSION.split(".")
        await create_marketplace_listing(
            session,
            uid=OTHER_API_UID,
            public_id="tests.otherapi",
            min_plugin_api=f"{major}.{minor}",
        )
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        response = await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "This API",
                "initiative_id": a.initiative.id,
                "listing_uid": OTHER_API_UID,
            },
        )
        assert response.status_code == 201, response.text

    async def test_installing_still_needs_the_create_permission(
        self, client: AsyncClient, acting_user, session, listing
    ):
        """Installing is subject to the tool's own create gate, like any other
        way of adding a dashboard."""
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        response = await client.post(
            b.g("/dashboards/"),
            headers=b.headers,
            json={
                "name": "Sneaky",
                "initiative_id": a.initiative.id,
                "listing_uid": INSTALL_UID,
            },
        )
        assert response.status_code == 403

    async def test_installing_counts_once_and_records_no_guild(
        self, client: AsyncClient, acting_user, session, listing
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        for name in ("First", "Second"):
            response = await client.post(
                a.g("/dashboards/"),
                headers=a.headers,
                json={
                    "name": name,
                    "initiative_id": a.initiative.id,
                    "listing_uid": INSTALL_UID,
                },
            )
            assert response.status_code == 201, response.text

        await session.refresh(listing)
        assert listing.installs_count == 2
        # A number, not a record of who: there is no column that could say.
        assert not hasattr(listing, "guild_id")


class TestUpgrade:
    async def _install(self, client, actor, uid: str = INSTALL_UID) -> dict:
        response = await client.post(
            actor.g("/dashboards/"),
            headers=actor.headers,
            json={
                "name": "Installed",
                "initiative_id": actor.initiative.id,
                "listing_uid": uid,
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def test_a_new_version_is_not_pushed(
        self, client: AsyncClient, acting_user, session, listing
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        installed = await self._install(client, a)

        await create_marketplace_listing(
            session,
            uid=INSTALL_UID,
            public_id="tests.install",
            version="2.0.0",
            definition=_definition(widget_type="table"),
        )

        # Untouched until someone here asks for it.
        response = await client.get(
            a.g(f"/dashboards/{installed['id']}"), headers=a.headers
        )
        body = response.json()
        assert body["listing_version"] == "1.0.0"
        assert body["definition"]["widgets"][0]["type"] == "stat"

    async def test_upgrading_re_pins_this_instance_only(
        self, client: AsyncClient, acting_user, session, listing
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        first = await self._install(client, a)
        second = await self._install(client, a)

        await create_marketplace_listing(
            session,
            uid=INSTALL_UID,
            public_id="tests.install",
            version="2.0.0",
            definition=_definition(widget_type="table"),
        )

        response = await client.post(
            a.g(f"/dashboards/{first['id']}/upgrade"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["listing_version"] == "2.0.0"
        assert response.json()["definition"]["widgets"][0]["type"] == "table"

        # The other install of the same listing is untouched — which is what
        # makes "install the new one alongside the old" a real strategy.
        other = await client.get(a.g(f"/dashboards/{second['id']}"), headers=a.headers)
        assert other.json()["listing_version"] == "1.0.0"

    async def test_upgrading_needs_write_access_on_that_dashboard(
        self, client: AsyncClient, acting_user, session, listing
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        installed = await self._install(client, a)
        await create_marketplace_listing(
            session,
            uid=INSTALL_UID,
            public_id="tests.install",
            version="2.0.0",
            definition=_definition(widget_type="table"),
        )

        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        response = await client.post(
            b.g(f"/dashboards/{installed['id']}/upgrade"), headers=b.headers
        )
        # The default grant is read; re-pinning is authoring.
        assert response.status_code == 403

    async def test_upgrading_an_authored_dashboard_is_refused(
        self, client: AsyncClient, acting_user, session
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        created = await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "Mine",
                "initiative_id": a.initiative.id,
                "definition": _definition(),
            },
        )
        response = await client.post(
            a.g(f"/dashboards/{created.json()['id']}/upgrade"), headers=a.headers
        )
        assert response.status_code == 409
        assert (
            response.json()["detail"] == MarketplaceMessages.NOT_INSTALLED_FROM_LISTING
        )

    async def test_upgrading_when_already_current_is_refused(
        self, client: AsyncClient, acting_user, session, listing
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        installed = await self._install(client, a)

        response = await client.post(
            a.g(f"/dashboards/{installed['id']}/upgrade"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == MarketplaceMessages.ALREADY_LATEST_VERSION

    async def test_config_for_a_dropped_widget_does_not_survive(
        self, client: AsyncClient, acting_user, session, listing
    ):
        """An upgrade re-runs the same normalization an edit does, so instance
        config can never outlive the widget it configured."""
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        installed = await self._install(client, a)

        await client.patch(
            a.g(f"/dashboards/{installed['id']}"),
            headers=a.headers,
            json={"config": {"widgets": {"w1": {"counter_id": 7}}}},
        )

        # v2 renames the widget, so w1's config has nothing left to configure.
        await create_marketplace_listing(
            session,
            uid=INSTALL_UID,
            public_id="tests.install",
            version="2.0.0",
            definition={
                "widgets": [
                    {
                        "id": "w9",
                        "type": "stat",
                        "binding": {
                            "source": "query",
                            "sql": "SELECT count(*) AS n FROM tasks",
                        },
                    }
                ]
            },
        )
        response = await client.post(
            a.g(f"/dashboards/{installed['id']}/upgrade"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["config"]["widgets"] == {}


class TestInstalledListings:
    async def test_counts_every_install_regardless_of_list_paging(
        self, client: AsyncClient, acting_user, session, listing
    ):
        """The dashboard list is paginated; this answer is not. A browse surface
        deriving 'already installed' from a page would mark some installs and
        miss others."""
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        for name in ("One", "Two", "Three"):
            response = await client.post(
                a.g("/dashboards/"),
                headers=a.headers,
                json={
                    "name": name,
                    "initiative_id": a.initiative.id,
                    "listing_uid": INSTALL_UID,
                },
            )
            assert response.status_code == 201, response.text

        response = await client.get(
            a.g("/dashboards/installed-listings"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["counts"] == {INSTALL_UID: 3}

    async def test_a_dashboard_authored_here_is_not_counted(
        self, client: AsyncClient, acting_user, session
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        await client.post(
            a.g("/dashboards/"),
            headers=a.headers,
            json={
                "name": "Mine",
                "initiative_id": a.initiative.id,
                "definition": _definition(),
            },
        )
        response = await client.get(
            a.g("/dashboards/installed-listings"), headers=a.headers
        )
        assert response.json()["counts"] == {}

    async def test_the_literal_path_is_not_read_as_a_dashboard_id(
        self, client: AsyncClient, acting_user, session
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)
        response = await client.get(
            a.g("/dashboards/installed-listings"), headers=a.headers
        )
        assert response.status_code == 200
        assert "counts" in response.json()


class TestCatalogIsolation:
    async def test_a_routed_session_can_read_the_catalog_but_not_write_it(
        self, role_session, acting_user, session, listing
    ):
        """The install path reads the catalog under whatever role the request
        already has, and that role's access to the catalog is read-only.

        Exercised through the real login role rather than the superuser-backed
        `session` fixture, which would not show the difference.
        """
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        await _enable(session, a.initiative)

        routed = await role_session("app_user")
        await route_as(routed, user_id=a.user.id, guild_id=a.guild.id)

        found = (
            await routed.exec(
                text(
                    "SELECT public_id FROM public.marketplace_listings WHERE uid = :u"
                ),
                params={"u": INSTALL_UID},
            )
        ).all()
        assert [row[0] for row in found] == ["tests.install"]

        with pytest.raises(DBAPIError):
            await routed.exec(
                text(
                    "UPDATE public.marketplace_listings "
                    "SET description = 'rewritten' WHERE uid = :u"
                ),
                params={"u": INSTALL_UID},
            )
        await routed.rollback()

        with pytest.raises(DBAPIError):
            await routed.exec(
                text(
                    "INSERT INTO public.marketplace_listings "
                    "(uid, public_id, kind, source, name, publisher, description, "
                    " avatar_url, images, installs_count, available, created_at, "
                    " updated_at) "
                    "VALUES ('FAKE0000000001', 'tests.unwritable', 'dashboard', "
                    "'registry', 'Unwritable', 'Tests', 'x', '/x.svg', '[]', 0, "
                    "true, now(), now())"
                )
            )
        await routed.rollback()
