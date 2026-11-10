"""Plug-ins the deployment places into every guild.

The behaviour is one sentence — a registration marked ``mandatory`` is installed
everywhere — and the tests are about the edges around it, because those are what
make it usable in production:

* **A new guild gets it as it is created**, through the real creation path, so
  nobody has to remember to run anything.
* **An existing guild gets it at boot**, which is the only way a flag set today
  reaches guilds created last year.
* **Twice is once.** The sweep is idempotent; a guild that already has the plug-in
  is left exactly as it was, configuration and all.
* **Nothing here fails a guild creation.** A plug-in whose listing has not arrived
  is a gap the next boot closes, not a reason a guild cannot exist.
* **The kill switch outranks the flag**, and clearing the flag deletes nothing.
"""

from datetime import UTC
from typing import Any, ClassVar

import pytest
from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.request_context import SystemGuild
from app.models.platform.guild import CommunityRole
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.plugin_placement import PluginPlacement
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.platform.intake_setup import set_operations_guild
from app.services.tenant import mandatory_plugins
from app.services.tenant.mandatory_plugins import backfill_mandatory_plugins
from app.testing import (
    create_guild,
    create_guild_membership,
    create_guild_plugin,
    create_initiative,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_user,
    get_auth_headers,
    marketplace_uid,
    route_session_to_guild,
)

PROVIDED_ID = "platform.provided"
PROVIDED_UID = marketplace_uid("provided")

PROVIDED_DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": PROVIDED_ID, "protocol": 1},
    "features": [],
    "default_name": "Provided plug-in",
}


@pytest.fixture
async def provided_listing(session: AsyncSession):
    return await create_marketplace_listing(
        session,
        uid=PROVIDED_UID,
        public_id=PROVIDED_ID,
        kind="plugin",
        name="Provided plug-in",
        definition=PROVIDED_DEFINITION,
    )


@pytest.fixture
async def mandatory_registration(session: AsyncSession, provided_listing):
    return await create_plugin_service_registration(
        session,
        public_id=PROVIDED_ID,
        base_url="https://provided.example.test",
        listing_uid=PROVIDED_UID,
        mandatory=True,
    )


async def _installed_plugins(session: AsyncSession, guild_id: int) -> list[GuildPlugin]:
    await route_session_to_guild(session, guild_id)
    return list(
        (
            await session.exec(
                select(GuildPlugin).execution_options(populate_existing=True)
            )
        ).all()
    )


class TestAtGuildCreation:
    async def test_a_new_guild_gets_the_plugin(
        self, client: AsyncClient, session: AsyncSession, mandatory_registration
    ):
        """Through the real creation path: nobody installs it, and nobody was
        offered a choice."""
        user = await create_user(session, email="founder@example.com")
        response = await client.post(
            "/api/v1/communities/",
            headers=get_auth_headers(user),
            json={"name": "Fresh guild"},
        )
        assert response.status_code == 201, response.text
        guild_id = response.json()["id"]

        plugins = await _installed_plugins(session, guild_id)
        assert [plugin.listing_uid for plugin in plugins] == [PROVIDED_UID]
        assert plugins[0].name == "Provided plug-in"
        assert plugins[0].plugin_kind == "service"

    async def test_a_registration_switched_off_installs_nowhere(
        self, client: AsyncClient, session: AsyncSession, mandatory_registration
    ):
        mandatory_registration.enabled = False
        session.add(mandatory_registration)
        await session.commit()
        invalidate_registrations()

        user = await create_user(session, email="founder2@example.com")
        response = await client.post(
            "/api/v1/communities/",
            headers=get_auth_headers(user),
            json={"name": "Quiet guild"},
        )
        assert response.status_code == 201, response.text

        assert await _installed_plugins(session, response.json()["id"]) == []

    async def test_a_missing_listing_does_not_fail_the_creation(
        self, client: AsyncClient, session: AsyncSession
    ):
        """The install is a local row; a plug-in whose listing this deployment does
        not hold yet is a gap the next boot closes."""
        await create_plugin_service_registration(
            session,
            public_id="platform.absent",
            base_url="https://absent.example.test",
            listing_uid=marketplace_uid("absent"),
            mandatory=True,
        )
        user = await create_user(session, email="founder3@example.com")

        response = await client.post(
            "/api/v1/communities/",
            headers=get_auth_headers(user),
            json={"name": "Still created"},
        )
        assert response.status_code == 201, response.text
        assert await _installed_plugins(session, response.json()["id"]) == []

    async def test_nothing_mandatory_means_nothing_installed(
        self, client: AsyncClient, session: AsyncSession, provided_listing
    ):
        """A deployment that registered nothing compulsory sees no trace of any
        of this."""
        await create_plugin_service_registration(
            session,
            public_id=PROVIDED_ID,
            base_url="https://provided.example.test",
            listing_uid=PROVIDED_UID,
            mandatory=False,
        )
        user = await create_user(session, email="founder4@example.com")

        response = await client.post(
            "/api/v1/communities/",
            headers=get_auth_headers(user),
            json={"name": "Ordinary guild"},
        )
        assert response.status_code == 201, response.text
        assert await _installed_plugins(session, response.json()["id"]) == []


class TestBackfill:
    async def test_a_guild_that_predates_the_flag_gets_it(
        self, session: AsyncSession, mandatory_registration
    ):
        """The only way a decision made today reaches a guild made last year."""
        creator = await create_user(session, email="old@example.com")
        guild = await create_guild(session, creator=creator, name="Existing guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )

        result = await backfill_mandatory_plugins()
        assert result.installed == 1
        assert result.failed == 0

        plugins = await _installed_plugins(session, guild.id)
        assert [plugin.listing_uid for plugin in plugins] == [PROVIDED_UID]
        # Recorded against a guild admin: a plug-in they did not choose is still
        # one they are responsible for.
        assert plugins[0].created_by == creator.id

    async def test_a_guild_still_erasing_it_waits_for_the_erase(
        self, session: AsyncSession, mandatory_registration
    ):
        """The preprod case: an admin removed the plug-in and asked it to erase
        its data, and the sweep comes round before the plug-in has answered. An
        install now would be handed the names the erase is about to drop, so
        the guild is skipped and gets it on a pass after the erase is done."""
        from datetime import datetime

        from sqlalchemy import update

        from app.db.request_context import Unattributed
        from app.db.session import set_rls_context
        from app.models.platform.plugin_community_hook import PluginCommunityHook
        from app.services.marketplace import community_hooks

        creator = await create_user(session, email="erasing@example.com")
        guild = await create_guild(session, creator=creator, name="Erasing guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )
        guild_id = guild.id
        await community_hooks.deliver_community_hook(
            guild_id=guild_id, public_id=PROVIDED_ID, hook="erase"
        )

        result = await backfill_mandatory_plugins()
        assert (result.installed, result.failed) == (0, 0)
        assert await _installed_plugins(session, guild_id) == []

        await set_rls_context(session, Unattributed())
        await session.exec(
            update(PluginCommunityHook)
            .where(PluginCommunityHook.guild_id == guild_id)
            .values(done_at=datetime.now(UTC), outcome="delivered")
        )
        await session.commit()

        result = await backfill_mandatory_plugins()
        assert result.installed == 1
        plugins = await _installed_plugins(session, guild_id)
        assert [plugin.listing_uid for plugin in plugins] == [PROVIDED_UID]

    async def test_several_guilds_each_get_their_own(
        self, session: AsyncSession, mandatory_registration
    ):
        """The sweep walks guild schemas with one session, and ids restart at 1
        in each of them — so the second guild must not be answered with the
        first guild's install still sitting in the identity map."""
        guilds = []
        for index in range(3):
            creator = await create_user(session, email=f"many{index}@example.com")
            guild = await create_guild(session, creator=creator, name=f"Guild {index}")
            await create_guild_membership(
                session, user=creator, guild=guild, role=CommunityRole.admin
            )
            guilds.append(guild)

        result = await backfill_mandatory_plugins()

        assert (result.installed, result.failed) == (3, 0)
        for guild in guilds:
            plugins = await _installed_plugins(session, guild.id)
            assert [plugin.listing_uid for plugin in plugins] == [PROVIDED_UID], (
                f"guild {guild.id} did not get its own install"
            )

    async def test_an_operations_only_plugin_goes_to_the_operations_community(
        self, session: AsyncSession, mandatory_registration
    ):
        mandatory_registration.operations_only = True
        session.add(mandatory_registration)
        await session.commit()
        guilds = []
        for index in range(2):
            creator = await create_user(session, email=f"ops{index}@example.com")
            guild = await create_guild(session, creator=creator, name=f"Ops {index}")
            await create_guild_membership(
                session, user=creator, guild=guild, role=CommunityRole.admin
            )
            guilds.append(guild)
        operations, other = guilds
        await set_operations_guild(session, operations.id)

        result = await backfill_mandatory_plugins()

        assert (result.installed, result.failed) == (1, 0)
        plugins = await _installed_plugins(session, operations.id)
        assert [plugin.listing_uid for plugin in plugins] == [PROVIDED_UID]
        assert await _installed_plugins(session, other.id) == []

    async def test_running_it_twice_installs_once(
        self, session: AsyncSession, mandatory_registration
    ):
        """And the second run visits nothing: the install index says every
        community is settled."""
        creator = await create_user(session, email="twice@example.com")
        guild = await create_guild(session, creator=creator, name="Twice guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )

        await backfill_mandatory_plugins()
        second = await backfill_mandatory_plugins()

        assert second.guilds == 0
        assert len(await _installed_plugins(session, guild.id)) == 1

    async def test_a_guild_whose_install_rolled_back_is_visited_again(
        self, session: AsyncSession, mandatory_registration, monkeypatch
    ):
        creator = await create_user(session, email="rolled-back@example.com")
        guild = await create_guild(session, creator=creator, name="Rolled back")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )
        install = mandatory_plugins.install_mandatory_plugins

        async def fails(session, **kwargs):
            await install(session, **kwargs)
            raise RuntimeError("down")

        monkeypatch.setattr(mandatory_plugins, "install_mandatory_plugins", fails)
        await backfill_mandatory_plugins()
        monkeypatch.setattr(mandatory_plugins, "install_mandatory_plugins", install)
        retried = await backfill_mandatory_plugins()

        assert retried.installed == 1
        assert len(await _installed_plugins(session, guild.id)) == 1

    async def test_with_nothing_mandatory_it_touches_no_guild(
        self, session: AsyncSession, provided_listing
    ):
        creator = await create_user(session, email="none@example.com")
        guild = await create_guild(session, creator=creator, name="Untouched")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )

        result = await backfill_mandatory_plugins()
        # Not even a pass over the guilds: with nothing marked, there is nothing
        # this could be for.
        assert (result.guilds, result.installed, result.failed) == (0, 0, 0)
        assert await _installed_plugins(session, guild.id) == []

    async def test_clearing_the_flag_leaves_the_install_alone(
        self, session: AsyncSession, mandatory_registration
    ):
        """The destructive path is deleting the registration, not clearing a
        flag: a plug-in that stops being compulsory keeps its install."""
        creator = await create_user(session, email="cleared@example.com")
        guild = await create_guild(session, creator=creator, name="Cleared guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )
        await backfill_mandatory_plugins()

        mandatory_registration.mandatory = False
        session.add(mandatory_registration)
        await session.commit()
        invalidate_registrations()
        await backfill_mandatory_plugins()

        assert len(await _installed_plugins(session, guild.id)) == 1


class TestPlacement:
    async def test_it_is_placed_in_every_initiative_there_is(
        self, session: AsyncSession, mandatory_registration
    ):
        """In every initiative there is when it lands, with the moderator role.
        One created afterwards is the seat's to place."""
        creator = await create_user(session, email="placed@example.com")
        guild = await create_guild(session, creator=creator, name="Placed guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )
        before = await create_initiative(session, guild, creator, name="Before")

        await backfill_mandatory_plugins()
        [plugin] = await _installed_plugins(session, guild.id)

        await create_initiative(session, guild, creator, name="After")

        await route_session_to_guild(session, guild.id)
        rows = (
            await session.exec(
                select(PluginPlacement).where(PluginPlacement.install_id == plugin.id)
            )
        ).all()
        assert {row.initiative_id for row in rows} == {before.id}

    async def test_an_install_already_there_is_left_as_the_seat_set_it(
        self, session: AsyncSession, mandatory_registration
    ):
        """Marked mandatory after it landed: the initiatives keep the seat's
        placement."""
        creator = await create_user(session, email="late@example.com")
        guild = await create_guild(session, creator=creator, name="Late guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )
        await create_initiative(session, guild, creator, name="Existing")
        await create_guild_plugin(
            session,
            guild,
            creator,
            definition=PROVIDED_DEFINITION,
            listing_uid=PROVIDED_UID,
        )

        await backfill_mandatory_plugins()

        [plugin] = await _installed_plugins(session, guild.id)
        await route_session_to_guild(session, guild.id)
        assert (
            await session.exec(
                select(PluginPlacement).where(PluginPlacement.install_id == plugin.id)
            )
        ).all() == []


class TestScopes:
    async def test_it_is_granted_what_it_asks_for_within_the_ceiling(
        self, session: AsyncSession
    ):
        """The operator's registration is the consent a seat would otherwise
        give, so a mandatory install lands holding the manifest's scopes that
        the registration's ceiling allows — and nothing beyond it."""
        public_id = "platform.scoped"
        uid = marketplace_uid("scoped")
        await create_marketplace_listing(
            session,
            uid=uid,
            public_id=public_id,
            kind="plugin",
            name="Scoped plug-in",
            definition={
                "plugin_kind": "service",
                "service": {
                    "public_id": public_id,
                    "protocol": 1,
                    "scopes": ["comments:read", "projects:read", "projects:write"],
                },
                "features": [],
                "default_name": "Scoped plug-in",
            },
        )
        await create_plugin_service_registration(
            session,
            public_id=public_id,
            base_url="https://scoped.example.test",
            listing_uid=uid,
            mandatory=True,
            scope_ceiling=["projects:read", "projects:write", "tags:read"],
        )
        creator = await create_user(session, email="scoped@example.com")
        guild = await create_guild(session, creator=creator, name="Scoped guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )

        await backfill_mandatory_plugins()

        [plugin] = await _installed_plugins(session, guild.id)
        assert plugin.granted_scopes == ["projects:read", "projects:write"]

    async def test_a_manifest_asking_for_nothing_is_granted_nothing(
        self, session: AsyncSession, mandatory_registration
    ):
        creator = await create_user(session, email="unscoped@example.com")
        guild = await create_guild(session, creator=creator, name="Unscoped guild")
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )

        await backfill_mandatory_plugins()

        [plugin] = await _installed_plugins(session, guild.id)
        assert plugin.granted_scopes == []


class TestScopesOnAnInstallAlreadyThere:
    """The sweep leaves an existing mandatory install's grant as the seat set
    it, empty or not."""

    PUBLIC_ID = "platform.scoped-later"
    UID = marketplace_uid("scopedlater")
    DEFINITION: ClassVar[dict[str, Any]] = {
        "plugin_kind": "service",
        "service": {
            "public_id": "platform.scoped-later",
            "protocol": 1,
            "scopes": ["comments:read", "projects:read"],
        },
        "features": [],
        "default_name": "Scoped later",
    }

    async def _guild_with_install(
        self, session: AsyncSession, email: str, *, granted: list[str] | None = None
    ):
        await create_marketplace_listing(
            session,
            uid=self.UID,
            public_id=self.PUBLIC_ID,
            kind="plugin",
            name="Scoped later",
            definition=self.DEFINITION,
        )
        await create_plugin_service_registration(
            session,
            public_id=self.PUBLIC_ID,
            base_url="https://scoped-later.example.test",
            listing_uid=self.UID,
            mandatory=True,
            scope_ceiling=["comments:read", "projects:read"],
        )
        creator = await create_user(session, email=email)
        guild = await create_guild(session, creator=creator, name=email)
        await create_guild_membership(
            session, user=creator, guild=guild, role=CommunityRole.admin
        )
        plugin = await create_guild_plugin(
            session,
            guild,
            creator,
            definition=self.DEFINITION,
            listing_uid=self.UID,
        )
        if granted:
            # Written on the system engine, which the grant guard admits, as a
            # stand-in for the seat having granted it.
            from app.db import cohorts
            from app.db import session as db_session

            async with cohorts.system_session(guild.id) as system:
                await db_session.set_rls_context(system, SystemGuild(guild.id))
                row = (
                    await system.exec(
                        select(GuildPlugin).where(GuildPlugin.id == plugin.id)
                    )
                ).one()
                row.granted_scopes = granted
                system.add(row)
                await system.commit()
        return guild

    async def test_an_empty_grant_stays_empty(self, session: AsyncSession):
        guild = await self._guild_with_install(session, "empty-grant@example.com")

        await backfill_mandatory_plugins()

        [plugin] = await _installed_plugins(session, guild.id)
        assert plugin.granted_scopes == []

    async def test_a_grant_the_seat_set_is_left_alone(self, session: AsyncSession):
        guild = await self._guild_with_install(
            session, "seat-grant@example.com", granted=["comments:read"]
        )

        await backfill_mandatory_plugins()

        [plugin] = await _installed_plugins(session, guild.id)
        assert plugin.granted_scopes == ["comments:read"]
