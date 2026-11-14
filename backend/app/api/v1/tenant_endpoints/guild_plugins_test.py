"""Installing a plug-in, and what that gives the guild.

Two things carry the weight.

A plug-in mounts an *existing* tool at guild scope — installing the guild calendar
creates an ordinary `calendars` row with no initiative, not a parallel thing. So
the tests assert on the calendar: that it exists, that it belongs to no
initiative, and that a plain member of the guild — who is in no initiative at
all — can actually read it. That last one is the whole point of guild scope, and
it is the assertion that would fail if any layer still assumed a row must name
an initiative.

The other is who may do this. Installing mounts a guild-wide surface, so it is a
guild-admin action; reading the list is not, because the sidebar has to know
what is there.
"""

import pytest
from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildMessages, GuildPluginMessages, MarketplaceMessages
from app.models.platform.guild import CommunityRole
from app.models.tenant.calendar import Calendar
from app.testing import (
    create_marketplace_listing,
    create_plugin_service_registration,
    marketplace_uid,
    route_session_to_guild,
)

CALENDAR_PLUGIN_UID = marketplace_uid("guildcalendar")


def _plugin_definition(tool: str = "calendar") -> dict:
    return {
        "plugin_kind": "tool_instance",
        "tool": tool,
        "default_name": "Community calendar",
    }


@pytest.fixture
async def calendar_plugin(session):
    return await create_marketplace_listing(
        session,
        uid=CALENDAR_PLUGIN_UID,
        public_id="core.guild-calendar",
        kind="plugin",
        name="Community calendar",
        definition=_plugin_definition(),
    )


async def _read_calendar(
    session: AsyncSession,
    guild_id: int,
    calendar_id: int,
    *,
    include_deleted: bool = False,
):
    """Read the calendar the install created, directly.

    Two things a request would do for us: the test session is not routed by
    itself (guild content lives in that guild's schema), and soft-deleted rows
    are filtered out of ordinary queries — so asserting that uninstalling
    *trashed* rather than deleted has to opt back in.
    """
    await route_session_to_guild(session, guild_id)
    statement = select(Calendar).where(Calendar.id == calendar_id)
    if include_deleted:
        statement = statement.execution_options(include_deleted=True)
    return (await session.exec(statement)).first()


async def _install(client: AsyncClient, actor, **body) -> dict:
    response = await client.post(
        actor.g("/plugins/"),
        headers=actor.headers,
        json={"listing_uid": CALENDAR_PLUGIN_UID, **body},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _artifact_id(plugin: dict, artifact_type: str = "calendar") -> int:
    """The id of what the install produced.

    An install may produce several things, so what it produced is a list rather
    than a well-known key on ``config``; a caller says which type it wants.
    """
    matching = [a["id"] for a in plugin["artifacts"] if a["type"] == artifact_type]
    assert matching, f"no {artifact_type} artifact on {plugin['artifacts']}"
    return matching[0]


class TestInstall:
    async def test_installing_mounts_a_guild_level_calendar(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)

        assert plugin["plugin_kind"] == "tool_instance"
        assert plugin["tool"] == "calendar"
        assert plugin["listing_version"] == "1.0.0"
        assert plugin["enabled"] is True

        calendar = await _read_calendar(session, a.guild.id, _artifact_id(plugin))
        assert calendar is not None
        # Belongs to the guild, not to any initiative — which is what a plug-in is.
        assert calendar.initiative_id is None

    async def test_the_list_carries_the_listing_artwork(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        """The sidebar draws an install from its listing's picture, so the LIST
        payload has to carry it — a field added only to the detail read would
        leave every sidebar entry blank."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        await _install(client, a)

        response = await client.get(a.g("/plugins/"), headers=a.headers)
        assert response.status_code == 200, response.text
        (item,) = response.json()["items"]
        assert item["avatar_url"] == "/marketplace/test.svg"

    async def test_the_detail_names_the_listing_behind_the_install(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        """The plug-in's page says who made it and offers a report, so the
        detail read carries the listing's source, publisher and id."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)

        response = await client.get(a.g(f"/plugins/{plugin['id']}"), headers=a.headers)
        assert response.status_code == 200, response.text
        assert response.json()["listing"] == {
            "id": calendar_plugin.id,
            "source": "builtin",
            "publisher": "Tests",
            "first_party": True,
        }

    async def test_the_name_can_be_chosen_at_install(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a, name="Club nights")
        assert plugin["name"] == "Club nights"
        calendar = await _read_calendar(session, a.guild.id, _artifact_id(plugin))
        assert calendar.name == "Club nights"

    async def test_only_a_guild_admin_may_install(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        response = await client.post(
            member.g("/plugins/"),
            headers=member.headers,
            json={"listing_uid": CALENDAR_PLUGIN_UID},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED

    async def test_a_listing_that_is_not_a_plugin_is_a_404(
        self, client: AsyncClient, acting_user, session
    ):
        # A dashboard listing installs through the dashboards endpoint; asking
        # the plug-ins endpoint for one is asking for something that isn't there.
        await create_marketplace_listing(
            session, uid=marketplace_uid("dashnotapp"), public_id="tests.dash"
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)
        response = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": marketplace_uid("dashnotapp")},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND

    async def test_installing_twice_is_refused(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        await _install(client, a)
        again = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": CALENDAR_PLUGIN_UID},
        )
        assert again.status_code == 409
        assert again.json()["detail"] == GuildPluginMessages.ALREADY_INSTALLED

    async def test_each_guild_installs_its_own(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_plugin
    ):
        """One install per listing is per *guild* — the catalog is shared, the
        installs are not.

        Not asserted on the ids: each guild has its own schema, so both
        calendars are legitimately id 1. What matters is that each guild has a
        calendar of its own, in its own schema.
        """
        a = await acting_user(guild_role=CommunityRole.superadmin)
        b = await acting_user(guild_role=CommunityRole.superadmin)
        first = await _install(client, a)
        second = await _install(client, b)

        for actor, plugin in ((a, first), (b, second)):
            calendar = await _read_calendar(
                session, actor.guild.id, _artifact_id(plugin)
            )
            assert calendar is not None


class TestVisibility:
    async def test_a_member_in_no_initiative_can_read_the_calendar(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        """The point of guild scope: a member who belongs to no initiative still
        reaches the guild's own calendar, because it belongs to no initiative
        either."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.get(
            member.g(f"/calendars/{_artifact_id(plugin)}"),
            headers=member.headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["initiative_id"] is None

    async def test_a_member_can_list_the_plugins(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        # The sidebar has to know what is installed; that is not privileged.
        a = await acting_user(guild_role=CommunityRole.superadmin)
        await _install(client, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.get(member.g("/plugins/"), headers=member.headers)
        assert response.status_code == 200
        assert [item["tool"] for item in response.json()["items"]] == ["calendar"]

    async def test_another_guild_sees_nothing(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        await _install(client, a)
        stranger = await acting_user(guild_role=CommunityRole.superadmin)

        response = await client.get(stranger.g("/plugins/"), headers=stranger.headers)
        assert response.json()["items"] == []


class TestManage:
    async def test_renaming_and_disabling(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)

        response = await client.patch(
            a.g(f"/plugins/{plugin['id']}"),
            headers=a.headers,
            json={"name": "Renamed", "enabled": False},
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Renamed"
        assert response.json()["enabled"] is False

    async def test_an_install_tracks_its_listing_by_default(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        """Nobody opts in. An install takes what its publisher ships until a
        guild admin says it should not."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        assert plugin["auto_update"] is True

    async def test_an_admin_can_switch_to_manual_updates(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)

        response = await client.patch(
            a.g(f"/plugins/{plugin['id']}"),
            headers=a.headers,
            json={"auto_update": False},
        )
        assert response.status_code == 200, response.text
        assert response.json()["auto_update"] is False

        # And it is what the next reader sees, not just what the write echoed.
        (listed,) = (await client.get(a.g("/plugins/"), headers=a.headers)).json()[
            "items"
        ]
        assert listed["auto_update"] is False

    async def test_the_cadence_is_a_guild_admin_s_to_set(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.patch(
            member.g(f"/plugins/{plugin['id']}"),
            headers=member.headers,
            json={"auto_update": False},
        )
        assert response.status_code == 403

    async def test_the_detail_read_offers_nothing_when_there_is_nothing_to_take(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        """``update_version`` is what draws the Update button, so an install on
        the newest version has to come back without one."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)

        response = await client.get(a.g(f"/plugins/{plugin['id']}"), headers=a.headers)
        assert response.status_code == 200, response.text
        assert response.json()["update_version"] is None

    async def test_disabling_leaves_the_content_alone(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        await client.patch(
            a.g(f"/plugins/{plugin['id']}"), headers=a.headers, json={"enabled": False}
        )
        # Turning a plug-in off hides it; it does not throw anything away.
        response = await client.get(
            a.g(f"/calendars/{_artifact_id(plugin)}"), headers=a.headers
        )
        assert response.status_code == 200

    @pytest.mark.parametrize("role", [CommunityRole.admin, CommunityRole.member])
    async def test_only_the_seat_may_manage(
        self, client: AsyncClient, acting_user, calendar_plugin, role: CommunityRole
    ):
        """What the community hands a plug-in is the seat's, so running the
        community is not enough on its own."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        other = await acting_user(guild_role=role, guild=a.guild)

        patched = await client.patch(
            other.g(f"/plugins/{plugin['id']}"),
            headers=other.headers,
            json={"name": "no"},
        )
        assert patched.status_code == 403
        removed = await client.delete(
            other.g(f"/plugins/{plugin['id']}"), headers=other.headers
        )
        assert removed.status_code == 403


class TestUninstall:
    async def test_removing_a_plugin_trashes_what_it_made(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_plugin
    ):
        """Trashed, not deleted: whatever the guild put in that calendar should
        survive an admin removing the plug-in."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        calendar_id = _artifact_id(plugin)

        response = await client.delete(
            a.g(f"/plugins/{plugin['id']}"), headers=a.headers
        )
        assert response.status_code == 204

        assert (await client.get(a.g("/plugins/"), headers=a.headers)).json()[
            "items"
        ] == []
        calendar = await _read_calendar(
            session, a.guild.id, calendar_id, include_deleted=True
        )
        assert calendar is not None
        assert calendar.deleted_at is not None
        # And gone from the ordinary view, like anything else in the trash.
        assert await _read_calendar(session, a.guild.id, calendar_id) is None

    async def test_removal_trashes_a_calendar_added_after_the_install(
        self, client: AsyncClient, acting_user, session: AsyncSession, calendar_plugin
    ):
        """A plug-in is answerable for everything made inside it, not only for what
        it created on the way in. Removal reads that list under the same lock a
        create takes, so a calendar added later goes to the trash with the rest
        rather than staying live with nothing that reaches it."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        mounted_id = _artifact_id(plugin)

        added = await client.post(
            a.g("/calendars/"), headers=a.headers, json={"name": "Holidays"}
        )
        assert added.status_code == 201, added.text
        added_id = added.json()["id"]

        response = await client.delete(
            a.g(f"/plugins/{plugin['id']}"), headers=a.headers
        )
        assert response.status_code == 204

        for calendar_id in (mounted_id, added_id):
            trashed = await _read_calendar(
                session, a.guild.id, calendar_id, include_deleted=True
            )
            assert trashed is not None and trashed.deleted_at is not None, calendar_id
            assert await _read_calendar(session, a.guild.id, calendar_id) is None

    async def test_the_listing_can_be_installed_again_afterwards(
        self, client: AsyncClient, acting_user, calendar_plugin
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        await client.delete(a.g(f"/plugins/{plugin['id']}"), headers=a.headers)
        # The one-install rule is about what is currently mounted, not a
        # permanent claim on the listing.
        again = await _install(client, a)
        assert _artifact_id(again) != _artifact_id(plugin)


class TestKindsThisBuildCanMount:
    """Every kind the catalog may hold is one a guild can install.

    A ``service`` plug-in is the one whose install produces nothing locally: it
    brings connections rather than content, and what it offers is served by the
    container the operator registered. So the assertion that matters is that
    installing one records the row and creates no artifact — quietly mounting
    something would be the bug.

    Which is also why one can only be installed where its service is
    registered: with no registration there is no container, and the install
    would be a row standing for nothing.
    """

    SERVICE_UID = marketplace_uid("servicekind")

    @pytest.fixture
    async def service_listing(self, session: AsyncSession):
        return await create_marketplace_listing(
            session,
            uid=self.SERVICE_UID,
            public_id="tests.service-kind",
            kind="plugin",
            name="A service plug-in",
            definition={
                "plugin_kind": "service",
                "service": {"public_id": "tests.service-kind"},
                "features": [],
            },
        )

    async def test_a_service_plugin_installs_and_creates_no_artifact(
        self, client: AsyncClient, acting_user, session: AsyncSession, service_listing
    ):
        # Wired up: the operator has said this deployment runs the plug-in. Whether
        # its container is up yet is not asked.
        await create_plugin_service_registration(
            session, public_id="tests.service-kind"
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)

        response = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": self.SERVICE_UID},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["plugin_kind"] == "service"
        assert body["artifacts"] == []
        assert body["available"] is True
        assert body["mandatory"] is False

    async def test_a_service_nobody_registered_is_not_installable(
        self, client: AsyncClient, acting_user, service_listing
    ):
        """The same answer the marketplace gives by leaving it out.

        The catalog is published to every deployment; running the service is
        what makes one carry the plug-in. Until an operator has wired it up, the
        uid names nothing this deployment installs.
        """
        a = await acting_user(guild_role=CommunityRole.superadmin)

        response = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": self.SERVICE_UID},
        )

        assert response.status_code == 404, response.text
        assert response.json()["detail"] == MarketplaceMessages.LISTING_NOT_FOUND
