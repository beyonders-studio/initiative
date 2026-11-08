"""An install reaching the audit log.

A plug-in is a standing arrangement between a community and somebody outside it,
so the four moments worth writing down are the ones that change what that
arrangement is: it arrives, its settings move, its configuration moves, its
version moves, and it goes.

What a record is allowed to carry is the other half of these. An install is
named by its listing and its version; a configuration change is named by the
fields that moved and never by what was typed into them.
"""

import json

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import CommunityRole
from app.testing import (
    create_guild_plugin,
    create_marketplace_listing,
    create_plugin_service_registration,
    emitted,
    marketplace_uid,
)

CALENDAR_PLUGIN_UID = marketplace_uid("auditcalendar")
UPGRADE_PLUGIN_UID = marketplace_uid("auditupgrade")

SECRET = "shpat_auditsupersecret"

ADMIN_CONNECTION = {
    "id": "admin",
    "scope": "static",
    "label": {"en": "Admin API"},
    "fields": [
        {"key": "shop_domain", "type": "string", "label": {"en": "Shop"}},
        {"key": "admin_token", "type": "secret", "label": {"en": "Token"}},
    ],
}

SERVICE_DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": "tests.auditshop", "protocol": 1},
    "features": [],
    "connections": [ADMIN_CONNECTION],
}


def _tool_definition(**overrides) -> dict:
    return {
        "plugin_kind": "tool_instance",
        "tool": "calendar",
        "default_name": "Community calendar",
        **overrides,
    }


@pytest.fixture
async def calendar_plugin(session: AsyncSession):
    return await create_marketplace_listing(
        session,
        uid=CALENDAR_PLUGIN_UID,
        public_id="tests.auditcalendar",
        kind="plugin",
        name="Community calendar",
        definition=_tool_definition(),
    )


async def _install(client: AsyncClient, actor) -> dict:
    response = await client.post(
        actor.g("/plugins/"),
        headers=actor.headers,
        json={"listing_uid": CALENDAR_PLUGIN_UID},
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestInstalling:
    async def test_an_install_records_its_listing_and_how_it_arrived(
        self, client: AsyncClient, acting_user, calendar_plugin, capfd
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        capfd.readouterr()
        plugin = await _install(client, a)

        (row,) = emitted(capfd, AuditEventType.PLUGIN_INSTALLED)
        assert row["actor_user_id"] == a.user.id
        assert row["target_user_id"] is None
        assert row["guild_id"] == a.guild.id
        assert row["target"] == {"type": "plugin", "id": plugin["id"]}
        assert row["detail"] == {
            "listing_uid": CALENDAR_PLUGIN_UID,
            "version": "1.0.0",
            "via": "install",
            "granted_scopes": [],
        }

    async def test_a_refused_install_records_nothing(
        self, client: AsyncClient, acting_user, calendar_plugin, capfd
    ):
        """The seat is the gate, and a request that never got past it did not
        install anything to write down."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        capfd.readouterr()

        response = await client.post(
            member.g("/plugins/"),
            headers=member.headers,
            json={"listing_uid": CALENDAR_PLUGIN_UID},
        )
        assert response.status_code == 403

        assert emitted(capfd, AuditEventType.PLUGIN_INSTALLED) == []


class TestManaging:
    async def test_a_rename_records_which_fields_moved(
        self, client: AsyncClient, acting_user, calendar_plugin, capfd
    ):
        """A name is a string, so the record says it moved and stops there;
        a flag is copied, because its type rules out anything else."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        capfd.readouterr()

        response = await client.patch(
            a.g(f"/plugins/{plugin['id']}"),
            headers=a.headers,
            json={"name": "Club nights", "auto_update": False},
        )
        assert response.status_code == 200, response.text

        (row,) = emitted(capfd, AuditEventType.PLUGIN_UPDATED)
        assert row["actor_user_id"] == a.user.id
        assert row["guild_id"] == a.guild.id
        assert row["target"] == {"type": "plugin", "id": plugin["id"]}
        detail = row["detail"]
        assert detail["area"] == "settings"
        assert detail["changed"] == ["auto_update", "name"]
        assert detail["values"] == {"auto_update": {"from": True, "to": False}}
        assert "Club nights" not in json.dumps(row)

    async def test_a_patch_that_moves_nothing_records_nothing(
        self, client: AsyncClient, acting_user, calendar_plugin, capfd
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        capfd.readouterr()

        response = await client.patch(
            a.g(f"/plugins/{plugin['id']}"),
            headers=a.headers,
            json={"name": plugin["name"], "auto_update": plugin["auto_update"]},
        )
        assert response.status_code == 200, response.text

        assert emitted(capfd, AuditEventType.PLUGIN_UPDATED) == []

    async def test_an_upgrade_records_the_two_versions(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        await create_marketplace_listing(
            session,
            uid=UPGRADE_PLUGIN_UID,
            public_id="tests.auditupgrade",
            kind="plugin",
            version="1.0.0",
            definition=_tool_definition(),
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)
        installed = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": UPGRADE_PLUGIN_UID},
        )
        assert installed.status_code == 201, installed.text
        plugin_id = installed.json()["id"]

        await create_marketplace_listing(
            session,
            uid=UPGRADE_PLUGIN_UID,
            public_id="tests.auditupgrade",
            kind="plugin",
            version="1.1.0",
            definition=_tool_definition(default_name="Community calendar v2"),
        )
        capfd.readouterr()
        upgraded = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade"), headers=a.headers
        )
        assert upgraded.status_code == 200, upgraded.text

        (row,) = emitted(capfd, AuditEventType.PLUGIN_UPDATED)
        assert row["actor_user_id"] == a.user.id
        assert row["target"] == {"type": "plugin", "id": plugin_id}
        assert row["detail"] == {
            "area": "version",
            "from": "1.0.0",
            "to": "1.1.0",
        }


class TestConfiguring:
    @pytest.fixture(autouse=True)
    async def wired(self, session: AsyncSession):
        return await create_plugin_service_registration(
            session,
            public_id="tests.auditshop",
            base_url="https://auditshop.example.test",
        )

    async def test_config_records_the_field_names_and_none_of_the_values(
        self, client: AsyncClient, session: AsyncSession, acting_user, capfd
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await create_guild_plugin(
            session, a.guild, a.user, definition=SERVICE_DEFINITION
        )
        capfd.readouterr()

        response = await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={
                "values": {
                    "admin": {"shop_domain": "example.test", "admin_token": SECRET}
                }
            },
        )
        assert response.status_code == 200, response.text

        (row,) = emitted(capfd, AuditEventType.PLUGIN_UPDATED)
        assert row["actor_user_id"] == a.user.id
        assert row["guild_id"] == a.guild.id
        assert row["target"] == {"type": "plugin", "id": plugin.id}
        detail = row["detail"]
        assert detail["area"] == "config"
        assert sorted(detail["changed"]) == ["admin.admin_token", "admin.shop_domain"]
        assert detail["connection_ids"] == ["admin"]
        # The whole envelope, not just the key somebody remembered to leave out.
        assert SECRET not in json.dumps(row)
        assert "example.test" not in json.dumps(row)


class TestUninstalling:
    @pytest.mark.parametrize("erase", [False, True])
    async def test_removal_records_what_went_with_it(
        self, client: AsyncClient, acting_user, calendar_plugin, capfd, erase
    ):
        """Including whether the community asked for the plug-in's data to be
        erased with it."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(client, a)
        capfd.readouterr()

        response = await client.delete(
            a.g(f"/plugins/{plugin['id']}"),
            headers=a.headers,
            params={"erase": "true"} if erase else {},
        )
        assert response.status_code == 204, response.text

        (row,) = emitted(capfd, AuditEventType.PLUGIN_UNINSTALLED)
        assert row["actor_user_id"] == a.user.id
        assert row["guild_id"] == a.guild.id
        assert row["target"] == {"type": "plugin", "id": plugin["id"]}
        assert row["detail"] == {
            "listing_uid": CALENDAR_PLUGIN_UID,
            "connections": 0,
            "consents": 0,
            "erase": erase,
        }
