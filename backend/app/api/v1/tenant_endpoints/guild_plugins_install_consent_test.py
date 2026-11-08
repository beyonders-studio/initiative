"""The install dialog is the seat's consent.

``POST /plugins`` carries what the seat answered: the scopes it grants, where the
plug-in appears, and which built-in roles open it there. All of it lands with the
install in one transaction, under the same checks the separate scope and
placement routes apply, and anything refused leaves no install behind.
"""

import pytest
from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildMessages, GuildPluginMessages, MarketplaceMessages
from app.models.platform.guild import CommunityRole
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.tenant.initiatives import get_role_by_name
from app.testing import (
    create_initiative,
    create_marketplace_listing,
    create_plugin_service_registration,
    marketplace_uid,
    route_session_to_guild,
)

SERVICE_ID = "tests.consentco"
SERVICE_UID = marketplace_uid("consentco")
CEILING = ["comments:read", "projects:read", "tags:read"]


def _definition(*, inside: bool = True) -> dict:
    """A service plug-in asking for three scopes, one of them above the ceiling,
    with a surface inside initiatives when ``inside``."""
    pages = [
        {
            "id": "board",
            "path": "/page/board",
            "scopes": ["initiative"] if inside else ["guild"],
            "admin_only": False,
            "name": {"en": "Board"},
        }
    ]
    return {
        "plugin_kind": "service",
        "service": {
            "public_id": SERVICE_ID,
            "protocol": 1,
            "scopes": ["comments:read", "projects:read", "projects:write"],
        },
        "features": ["pages"],
        "pages": pages,
        "default_name": "ConsentCo",
    }


@pytest.fixture
async def listing(session: AsyncSession):
    await create_plugin_service_registration(
        session,
        public_id=SERVICE_ID,
        base_url="https://consentco.example.test",
        listing_uid=SERVICE_UID,
        scope_ceiling=CEILING,
    )
    return await create_marketplace_listing(
        session,
        uid=SERVICE_UID,
        public_id=SERVICE_ID,
        kind="plugin",
        name="ConsentCo",
        definition=_definition(),
    )


async def _install(client: AsyncClient, actor, **body):
    return await client.post(
        actor.g("/plugins/"),
        headers=actor.headers,
        json={"listing_uid": SERVICE_UID, **body},
    )


async def _role_id(session: AsyncSession, guild_id: int, initiative_id: int, name: str):
    await route_session_to_guild(session, guild_id)
    role = await get_role_by_name(session, initiative_id=initiative_id, role_name=name)
    assert role is not None
    return role.id


async def _installs(session: AsyncSession, guild_id: int) -> list[GuildPlugin]:
    session.expunge_all()
    await route_session_to_guild(session, guild_id)
    return list((await session.exec(select(GuildPlugin))).all())


class TestConsentAtInstall:
    async def test_scopes_placements_and_roles_land_with_the_install(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
        second = await create_initiative(session, a.guild, a.user, name="Second")

        response = await _install(
            client,
            a,
            granted_scopes=["projects:read", "comments:read"],
            placements="all",
            role_kinds=["moderator", "project_manager"],
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["granted_scopes"] == ["comments:read", "projects:read"]
        expected = []
        for initiative_id in sorted([a.initiative.id, second.id]):
            roles = sorted(
                [
                    await _role_id(session, a.guild.id, initiative_id, "moderator"),
                    await _role_id(
                        session, a.guild.id, initiative_id, "project_manager"
                    ),
                ]
            )
            expected.append({"initiative_id": initiative_id, "role_ids": roles})
        assert body["placements"] == expected

    async def test_picked_initiatives_start_with_their_moderators(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)
        await create_initiative(session, a.guild, a.user, name="Left out")

        response = await _install(client, a, placements=[a.initiative.id])

        assert response.status_code == 201, response.text
        moderator = await _role_id(session, a.guild.id, a.initiative.id, "moderator")
        assert response.json()["placements"] == [
            {"initiative_id": a.initiative.id, "role_ids": [moderator]}
        ]
        assert response.json()["granted_scopes"] == []

    async def test_an_install_with_no_answers_is_what_it_was(
        self, client: AsyncClient, acting_user, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)

        response = await _install(client, a)

        assert response.status_code == 201, response.text
        assert response.json()["granted_scopes"] == []
        assert response.json()["placements"] == []

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            (
                {"granted_scopes": ["tags:read"]},
                GuildPluginMessages.SCOPE_NOT_REQUESTED,
            ),
            (
                {"granted_scopes": ["projects:write"]},
                GuildPluginMessages.SCOPE_ABOVE_CEILING,
            ),
            ({"placements": [987654]}, GuildPluginMessages.PLACEMENT_INVALID),
            (
                {"placements": "all", "role_kinds": ["owner"]},
                GuildPluginMessages.PLACEMENT_ROLE_INVALID,
            ),
        ],
    )
    async def test_a_refused_answer_installs_nothing(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        listing,
        body,
        code,
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin, initiative=True)

        response = await _install(client, a, **body)

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == code
        assert await _installs(session, a.guild.id) == []

    async def test_only_the_seat_installs(
        self, client: AsyncClient, acting_user, listing
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)

        response = await _install(client, a, granted_scopes=["projects:read"])

        assert response.status_code == 403
        assert response.json()["detail"] == GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED


class TestTheListingSaysWhatTheDialogAsks:
    async def test_requested_grantable_and_surfaces(
        self, client: AsyncClient, acting_user, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)

        response = await client.get(
            a.g(f"/marketplace/listings/by-uid/{SERVICE_UID}"), headers=a.headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["requested_scopes"] == [
            "projects:read",
            "projects:write",
            "comments:read",
        ]
        assert body["grantable_scopes"] == ["projects:read", "comments:read"]
        assert body["has_initiative_surfaces"] is True

    async def test_a_declarative_plugin_asks_at_the_top_of_its_manifest(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """A declarative plug-in has no service block: it asks for its read
        scopes at the top of its manifest, and the registration its listing
        applied holds the ceiling the install is granted within."""
        uid = marketplace_uid("declaredco")
        await create_plugin_service_registration(
            session,
            public_id="tests.declaredco",
            listing_uid=uid,
            base_url=None,
            allowed_origins=[],
            jwks={},
            kind="declarative",
            scope_ceiling=["projects:read"],
        )
        await create_marketplace_listing(
            session,
            uid=uid,
            public_id="tests.declaredco",
            kind="plugin",
            name="DeclaredCo",
            definition={
                "plugin_kind": "service",
                "features": [],
                "hosts": ["api.declared.test"],
                "scopes": ["comments:read", "projects:read"],
            },
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)

        detail = await client.get(
            a.g(f"/marketplace/listings/by-uid/{uid}"), headers=a.headers
        )
        installed = await _install(
            client, a, listing_uid=uid, granted_scopes=["projects:read"]
        )

        assert detail.status_code == 200, detail.text
        assert detail.json()["requested_scopes"] == ["projects:read", "comments:read"]
        assert detail.json()["grantable_scopes"] == ["projects:read"]
        assert installed.status_code == 201, installed.text
        assert installed.json()["granted_scopes"] == ["projects:read"]

    @pytest.mark.parametrize(
        "block",
        [
            {
                "features": ["fields"],
                "fields": [
                    {
                        "key": "estimate",
                        "name": {"en": "Estimate"},
                        "kind": "text",
                        "on": ["task"],
                    }
                ],
            },
            {
                "features": ["parts"],
                "parts": [
                    {
                        "id": "summary",
                        "name": {"en": "Summary"},
                        "on": ["task"],
                        "tree": {"type": "stack"},
                    }
                ],
            },
            {
                "features": ["actions"],
                "actions": [
                    {
                        "id": "ping",
                        "name": {"en": "Ping"},
                        "on": ["task"],
                        "write": '{"set": {"pinged": now}}',
                    }
                ],
            },
        ],
        ids=["field", "part", "action"],
    )
    async def test_what_a_plugin_adds_to_items_is_placed_like_a_page(
        self, client: AsyncClient, acting_user, session: AsyncSession, block
    ):
        """A plug-in's fields, sections and actions are drawn on an item to the
        roles its placement names, as a page is opened, so a plug-in with any
        of them and no page has somewhere to be placed and is asked about
        roles."""
        uid = marketplace_uid("fieldco")
        await create_plugin_service_registration(
            session,
            public_id="tests.fieldco",
            listing_uid=uid,
            base_url=None,
            allowed_origins=[],
            jwks={},
            kind="declarative",
            scope_ceiling=["projects:read"],
        )
        await create_marketplace_listing(
            session,
            uid=uid,
            public_id="tests.fieldco",
            kind="plugin",
            name="FieldCo",
            definition={
                "plugin_kind": "service",
                "hosts": ["api.field.test"],
                "scopes": ["projects:read"],
                **block,
            },
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)

        detail = await client.get(
            a.g(f"/marketplace/listings/by-uid/{uid}"), headers=a.headers
        )

        assert detail.status_code == 200, detail.text
        assert detail.json()["has_initiative_surfaces"] is True


class TestAPluginAskingToUseAnother:
    """``plugins:<public_id>`` is asked when that plug-in is installed, not before."""

    async def test_the_seat_is_asked_when_the_plugin_it_uses_arrives(
        self, client: AsyncClient, session: AsyncSession, acting_user
    ):
        target_uid = marketplace_uid("gitco")
        caller_uid = marketplace_uid("callerco")
        await create_plugin_service_registration(
            session,
            public_id="tests.gitco",
            base_url="https://gitco.example.test",
            listing_uid=target_uid,
        )
        await create_marketplace_listing(
            session,
            uid=target_uid,
            public_id="tests.gitco",
            kind="plugin",
            name="GitCo",
            definition={
                "plugin_kind": "service",
                "service": {"public_id": "tests.gitco", "protocol": 1},
                "features": [],
            },
        )
        await create_plugin_service_registration(
            session,
            public_id="tests.callerco",
            base_url="https://callerco.example.test",
            listing_uid=caller_uid,
            scope_ceiling=["plugins:tests.gitco", "tags:read"],
        )
        await create_marketplace_listing(
            session,
            uid=caller_uid,
            public_id="tests.callerco",
            kind="plugin",
            name="CallerCo",
            definition={
                "plugin_kind": "service",
                "service": {
                    "public_id": "tests.callerco",
                    "protocol": 1,
                    "scopes": [
                        "plugins:tests.gitco",
                        "plugins:tests.nameless",
                        "tags:read",
                    ],
                },
                "features": [],
            },
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)

        # Neither plug-in it uses is here, so neither is asked about.
        detail = await client.get(
            a.g(f"/marketplace/listings/by-uid/{caller_uid}"), headers=a.headers
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["requested_scopes"] == ["tags:read"]
        assert detail.json()["grantable_scopes"] == ["tags:read"]
        refused = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": caller_uid, "granted_scopes": ["plugins:tests.gitco"]},
        )
        assert refused.status_code == 422
        assert (
            refused.json()["detail"] == GuildPluginMessages.SCOPE_TARGET_NOT_INSTALLED
        )
        installed = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": caller_uid, "granted_scopes": ["tags:read"]},
        )
        assert installed.status_code == 201, installed.text
        caller_id = installed.json()["id"]

        # Installing GitCo asks whether CallerCo may use it.
        target = await client.get(
            a.g(f"/marketplace/listings/by-uid/{target_uid}"), headers=a.headers
        )
        assert target.json()["callers"] == [{"id": caller_id, "name": "CallerCo"}]
        target_install = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": target_uid, "callers": [caller_id]},
        )
        assert target_install.status_code == 201, target_install.text
        read = await client.get(a.g(f"/plugins/{caller_id}"), headers=a.headers)
        assert read.json()["granted_scopes"] == ["plugins:tests.gitco", "tags:read"]
        assert read.json()["requested_scopes"] == ["tags:read", "plugins:tests.gitco"]
        assert read.json()["plugin_names"]["tests.gitco"] == "GitCo"

        # Removing GitCo takes it back, so installing it again asks again.
        removed = await client.delete(
            a.g(f"/plugins/{target_install.json()['id']}"), headers=a.headers
        )
        assert removed.status_code == 204, removed.text
        read = await client.get(a.g(f"/plugins/{caller_id}"), headers=a.headers)
        assert read.json()["granted_scopes"] == ["tags:read"]
        assert read.json()["requested_scopes"] == ["tags:read"]


def _wider(*, surfaces: bool = False) -> dict:
    """Version 1.1.0: asks for ``tags:read`` too, and a second surface inside
    initiatives when ``surfaces``."""
    definition = _definition()
    definition["service"]["scopes"] = [
        "comments:read",
        "projects:read",
        "projects:write",
        "tags:read",
    ]
    if surfaces:
        definition["pages"] = [
            *definition["pages"],
            {
                "id": "planner",
                "path": "/page/planner",
                "scopes": ["initiative"],
                "admin_only": False,
                "name": {"en": "Planner"},
            },
        ]
    return definition


class TestUpgradeConsent:
    async def _installed_then_widened(
        self, client: AsyncClient, session: AsyncSession, actor, **wider
    ) -> int:
        response = await _install(client, actor, granted_scopes=["projects:read"])
        assert response.status_code == 201, response.text
        await create_marketplace_listing(
            session,
            uid=SERVICE_UID,
            public_id=SERVICE_ID,
            kind="plugin",
            name="ConsentCo",
            version="1.1.0",
            definition=_wider(**wider),
        )
        return response.json()["id"]

    async def test_the_detail_says_what_the_version_asks_for_or_why_it_cannot_run(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await self._installed_then_widened(
            client, session, a, surfaces=True
        )

        read = (
            await client.get(a.g(f"/plugins/{plugin_id}"), headers=a.headers)
        ).json()

        assert read["update_version"] == "1.1.0"
        assert read["pending_update"] == {
            "version": "1.1.0",
            "added_scopes": ["tags:read"],
            "added_surfaces": [{"id": "planner", "name": {"en": "Planner"}}],
            "declined": False,
        }
        assert read["update_refused"] is None

        await create_marketplace_listing(
            session,
            uid=SERVICE_UID,
            public_id=SERVICE_ID,
            kind="plugin",
            name="ConsentCo",
            version="1.2.0",
            definition=_wider(surfaces=True),
            min_plugin_api="99.0",
        )
        read = (
            await client.get(a.g(f"/plugins/{plugin_id}"), headers=a.headers)
        ).json()

        assert (read["update_version"], read["pending_update"]) == (None, None)
        assert read["update_refused"] == {
            "version": "1.2.0",
            "reason": MarketplaceMessages.LISTING_PLUGIN_API_INCOMPATIBLE,
        }

    async def test_without_consent_it_answers_with_what_it_asks(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade"), headers=a.headers
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"] == {
            "code": GuildPluginMessages.UPGRADE_NEEDS_CONSENT,
            "version": "1.1.0",
            "added_scopes": ["tags:read"],
            "added_surfaces": [],
            "declined": False,
        }
        (plugin,) = await _installs(session, a.guild.id)
        assert plugin.listing_version == "1.0.0"

    async def test_consent_applies_the_version_and_grants(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade"),
            headers=a.headers,
            json={"version": "1.1.0", "add_scopes": ["tags:read"]},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["listing_version"] == "1.1.0"
        assert body["granted_scopes"] == ["projects:read", "tags:read"]
        assert body["pending_update"] is None

    async def test_consent_to_another_version_applies_nothing(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade"),
            headers=a.headers,
            json={"version": "1.0.5", "add_scopes": []},
        )

        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == (
            GuildPluginMessages.UPGRADE_VERSION_MOVED
        )

    async def test_consent_is_held_to_the_ceiling(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade"),
            headers=a.headers,
            json={"version": "1.1.0", "add_scopes": ["projects:write"]},
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == GuildPluginMessages.SCOPE_ABOVE_CEILING

    async def test_declining_keeps_the_version_and_sticks(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await self._installed_then_widened(client, session, a)

        response = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade/decline"),
            headers=a.headers,
            json={"version": "1.1.0"},
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["listing_version"] == "1.0.0"
        assert body["pending_update"]["declined"] is True
        (plugin,) = await _installs(session, a.guild.id)
        assert plugin.declined_version == "1.1.0"

        moved = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade/decline"),
            headers=a.headers,
            json={"version": "1.0.9"},
        )
        assert moved.status_code == 409
        assert moved.json()["detail"] == GuildPluginMessages.UPGRADE_VERSION_MOVED

    async def test_only_the_seat_declines(
        self, client: AsyncClient, acting_user, session: AsyncSession, listing
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin_id = await self._installed_then_widened(client, session, a)
        admin = await acting_user(guild_role=CommunityRole.admin, guild=a.guild)

        response = await client.post(
            admin.g(f"/plugins/{plugin_id}/upgrade/decline"),
            headers=admin.headers,
            json={"version": "1.1.0"},
        )

        assert response.status_code == 403
