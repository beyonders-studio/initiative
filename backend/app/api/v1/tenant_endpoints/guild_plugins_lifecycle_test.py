"""Installing, uninstalling and erasing, as the community sees it and as its
plug-in is told.

An install and an uninstall each tell the plug-in (``installed``,
``uninstalled``), and neither touches what the plug-in calls the community and
its members: a reinstall finds the same names. Erasing is asked for with the
uninstall, by the community's admins alone and never of a plug-in the
deployment provides; it tells the plug-in ``erase``, after ``uninstalled``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx2 import AsyncClient
from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildPluginMessages
from app.db import post_commit
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.platform.plugin_community_hook import PluginCommunityHook
from app.models.platform.user import UserRole
from app.services.marketplace import plugin_refs
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.testing import (
    create_access_grant,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_user,
    get_auth_headers,
    marketplace_uid,
)

SERVICE_ID = "tests.lifeco"
SERVICE_UID = marketplace_uid("lifeco")

_DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": SERVICE_ID, "protocol": 1, "scopes": ["files:read"]},
    "features": [],
    "default_name": "LifeCo",
}


@pytest.fixture
async def registration(session: AsyncSession):
    row = await create_plugin_service_registration(
        session,
        public_id=SERVICE_ID,
        base_url="https://lifeco.example.test",
        listing_uid=SERVICE_UID,
        scope_ceiling=["files:read"],
    )
    await create_marketplace_listing(
        session,
        uid=SERVICE_UID,
        public_id=SERVICE_ID,
        kind="plugin",
        name="LifeCo",
        definition=_DEFINITION,
    )
    invalidate_registrations()
    return row


async def _install(client: AsyncClient, actor) -> int:
    response = await client.post(
        actor.g("/plugins/"), headers=actor.headers, json={"listing_uid": SERVICE_UID}
    )
    assert response.status_code == 201, response.text
    await post_commit.settle_all()
    return response.json()["id"]


async def _uninstall(client: AsyncClient, actor, plugin_id: int, **params):
    response = await client.delete(
        actor.g(f"/plugins/{plugin_id}"), headers=actor.headers, params=params
    )
    await post_commit.settle_all()
    return response


async def _told(session: AsyncSession, guild_id: int) -> list[tuple[str, int | None]]:
    """The hooks written for the plug-in, oldest first, with the install each
    names."""
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    rows = (
        await session.exec(
            select(PluginCommunityHook)
            .where(
                PluginCommunityHook.guild_id == guild_id,
                PluginCommunityHook.public_id == SERVICE_ID,
            )
            .order_by(PluginCommunityHook.id)
        )
    ).all()
    await session.commit()
    return [(row.hook, row.install_id) for row in rows]


class TestTheNamesStay:
    async def test_an_uninstall_keeps_them_and_a_reinstall_finds_them(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        first = await _install(client, a)
        community = await plugin_refs.ensure_plugin_guild_ref(
            guild_id=a.guild.id, public_id=SERVICE_ID
        )
        member = await plugin_refs.ensure_plugin_ref(
            guild_id=a.guild.id, public_id=SERVICE_ID, user_id=a.user.id
        )

        removed = await _uninstall(client, a, first)
        assert removed.status_code == 204, removed.text
        assert (
            await plugin_refs.existing_plugin_guild_ref(
                guild_id=a.guild.id, public_id=SERVICE_ID
            )
            == community
        )

        second = await _install(client, a)
        assert second != first
        assert (
            await plugin_refs.ensure_plugin_guild_ref(
                guild_id=a.guild.id, public_id=SERVICE_ID
            )
            == community
        )
        assert (
            await plugin_refs.ensure_plugin_ref(
                guild_id=a.guild.id, public_id=SERVICE_ID, user_id=a.user.id
            )
            == member
        )
        assert await _told(session, a.guild.id) == [
            ("installed", first),
            ("uninstalled", first),
            ("installed", second),
        ]


class TestErasing:
    async def test_an_admin_erases_with_the_uninstall(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await _install(client, a)
        community = await plugin_refs.ensure_plugin_guild_ref(
            guild_id=a.guild.id, public_id=SERVICE_ID
        )

        removed = await _uninstall(client, a, plugin_id, erase="true")
        assert removed.status_code == 204, removed.text
        assert await _told(session, a.guild.id) == [
            ("installed", plugin_id),
            ("uninstalled", plugin_id),
            ("erase", plugin_id),
        ]
        # Kept until the plug-in answers the erase.
        assert (
            await plugin_refs.existing_plugin_guild_ref(
                guild_id=a.guild.id, public_id=SERVICE_ID
            )
            == community
        )

    @pytest.mark.parametrize("settled", ["delivered", "gave_up"])
    async def test_it_cannot_come_back_until_the_erase_is_done(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        registration,
        settled,
    ):
        """An install while the erase is unfinished would be handed the names
        it is about to drop. Answered or given up on, the erase is done."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await _install(client, a)
        await _uninstall(client, a, plugin_id, erase="true")

        refused = await client.post(
            a.g("/plugins/"), headers=a.headers, json={"listing_uid": SERVICE_UID}
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["detail"] == GuildPluginMessages.ERASE_PENDING

        await set_rls_context(session, Unattributed())
        await session.exec(
            update(PluginCommunityHook)
            .where(
                PluginCommunityHook.guild_id == a.guild.id,
                PluginCommunityHook.hook == "erase",
            )
            .values(done_at=datetime.now(UTC), outcome=settled)
        )
        await session.commit()
        assert await _install(client, a)

    async def test_the_removal_and_its_hooks_land_together(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """Removing the install and writing ``uninstalled`` and ``erase`` are one
        transaction: rolled back, the install stays and nothing is told."""
        from app.models.tenant.guild_plugin import GuildPlugin
        from app.services.tenant import guild_plugins as guild_plugins_service

        a = await acting_user(guild_role=CommunityRole.superadmin)
        guild_id, user_id = a.guild.id, a.user.id
        plugin_id = await _install(client, a)

        await set_rls_context(session, SystemGuild(guild_id))
        plugin = await session.get(GuildPlugin, plugin_id)
        await guild_plugins_service.uninstall_plugin(
            session, plugin, actor_user_id=user_id, erase=True
        )
        await session.rollback()

        assert await _told(session, guild_id) == [("installed", plugin_id)]
        await set_rls_context(session, SystemGuild(guild_id))
        assert await session.get(GuildPlugin, plugin_id) is not None

    async def test_a_plugin_the_deployment_provides_is_never_erased(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await _install(client, a)
        registration.mandatory = True
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        refused = await _uninstall(client, a, plugin_id, erase="true")
        assert refused.status_code == 409
        assert refused.json()["detail"] == GuildPluginMessages.MANDATORY
        assert await _told(session, a.guild.id) == [("installed", plugin_id)]

    async def test_a_lent_seat_removes_but_does_not_erase(
        self, client: AsyncClient, acting_user, session: AsyncSession, registration
    ):
        """The seat lent to an operator may take a plug-in out; asking it to
        delete the community's data with it is the community's own admins'."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await _install(client, a)
        operator = await create_user(session, role=UserRole.operator)
        await create_access_grant(
            session, user=operator, guild=a.guild, access_level="read_write"
        )
        await create_access_grant(
            session,
            user=operator,
            guild=a.guild,
            access_level="superadmin",
            purpose="settings",
        )
        headers = get_auth_headers(operator)

        refused = await client.delete(
            a.g(f"/plugins/{plugin_id}"), headers=headers, params={"erase": "true"}
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"] == GuildPluginMessages.ERASE_ADMIN_ONLY

        removed = await client.delete(a.g(f"/plugins/{plugin_id}"), headers=headers)
        assert removed.status_code == 204, removed.text
        await post_commit.settle_all()
        assert await _told(session, a.guild.id) == [
            ("installed", plugin_id),
            ("uninstalled", plugin_id),
        ]
