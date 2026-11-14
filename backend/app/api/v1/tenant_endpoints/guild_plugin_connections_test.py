"""Configuring a plug-in, connecting to it, and every way that access ends.

Four things carry the weight here.

**A credential goes in and does not come back.** Every read of an install
reports which fields hold a value and never the value, for the member who typed
it and the guild admin who governs the install alike. The tests read the whole
payload and assert the plaintext is nowhere in it, rather than checking the one
field somebody remembered to hide.

**A personal connection is the member's, and the seat's to govern.** One member
must not see another's row; the seat that decides what the community hands
outward sees every one. That is a database policy rather than an endpoint
branch, so the tests exercise it through real roles: the ``client`` fixture
executes as ``app_user`` under the guild role it routes into.

**Installation never waits on a person.** A plug-in whose credentials are supplied
per member installs with none present and reports itself as needing no
configuration — connecting is something members do afterwards, if they want
what it unlocks.

**Access ends when the relationship does.** Leaving, being removed, being
revoked or blocked, closing an account, uninstalling and deleting the guild each
delete the stored values, and each queues the revocation that tells the plug-in to
let go at the vendor. The teardown tests assert on the rows *and* on the
recorded revocations, because deleting our copy is only half of it.
"""

import asyncio
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_PLUGIN_CONFIG, encrypt_field
from app.core.messages import GuildMessages, GuildPluginMessages, MarketplaceMessages
from app.models.platform.guild import CommunityRole
from app.models.platform.plugin_install import PluginInstallClaim
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.services.marketplace import plugin_installs
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant import plugin_revocation
from app.services.tenant.plugin_connection_flows import callback_url
from app.services.tenant.plugin_connections import load_connection_secrets
from app.testing import (
    create_guild,
    create_guild_membership,
    create_guild_plugin,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_plugin_user_connection,
    marketplace_uid,
    route_session_to_guild,
    sealed_vendor_values,
)


def _field(key: str, field_type: str, **extra) -> dict:
    return {"key": key, "type": field_type, "label": {"en": key}, **extra}


ADMIN_CONNECTION = {
    "id": "admin",
    "scope": "static",
    "label": {"en": "Admin API"},
    "access_hint": {"api": "Admin", "scopes": ["read_orders"]},
    "fields": [
        _field("shop_domain", "string", required=True),
        _field("admin_token", "secret", required=True),
    ],
}

#: The vendor's own client, as a flow names it.
VENDOR_FLOW = {
    "type": "oauth2",
    "authorize_url": "https://github.test/login/oauth/authorize",
    "token_url": "https://github.test/login/oauth/access_token",
    "client_id": "{vendor.client_id}",
    "client_secret": "{vendor.client_secret}",
    "scopes": [],
    "pkce": True,
    "after_connect": True,
}

GITHUB_CONNECTION = {
    "id": "github",
    "scope": "interactive",
    "label": {"en": "GitHub"},
    "fields": [_field("login", "string", managed=True)],
    "flow": {**VENDOR_FLOW, "revoke": "hook"},
}

#: A guild-wide credential obtained rather than typed.
#:
#: The case this exists for is the one no text box can express: a vendor whose
#: organization-wide install is a page of its own, where somebody who owns the
#: account chooses what the plug-in may see. What comes back is an installation, and
#: the plug-in's after_connect hook says what it is — so every field is ``managed``.
WORKSPACE_CONNECTION = {
    "id": "workspace",
    "scope": "static",
    "label": {"en": "Organization"},
    "fields": [_field("owner", "string", managed=True)],
    "flow": {
        **VENDOR_FLOW,
        "install_url": "https://github.test/apps/{vendor.app_slug}/installations/new",
    },
}

#: What the manifest asks the operator for.
VENDOR_BLOCK = {
    "fields": [
        {"key": key, "type": "string", "label": {"en": key}}
        for key in ("client_id", "client_secret", "app_slug")
    ]
}

#: What the operator supplied for the vendor client.
VENDOR_VALUES = {
    "client_id": "client-123",
    "client_secret": "client-secret-456",
    "app_slug": "initiative-test",
}

SERVICE_DEFINITION = {
    "plugin_kind": "service",
    "vendor": VENDOR_BLOCK,
    "service": {"public_id": "tests.shop", "protocol": 1},
    "features": [],
    "connections": [ADMIN_CONNECTION, GITHUB_CONNECTION],
}

#: The same plug-in, where the guild-wide half is obtained rather than typed.
#:
#: Kept apart from ``SERVICE_DEFINITION`` on purpose: an unsatisfied static
#: connection is an install that needs configuring, and every test about
#: something else would start asserting around one.
WORKSPACE_DEFINITION = {
    "plugin_kind": "service",
    "vendor": VENDOR_BLOCK,
    "service": {"public_id": "tests.shop", "protocol": 1},
    "features": [],
    "connections": [WORKSPACE_CONNECTION, GITHUB_CONNECTION],
}

MEMBER_ONLY_DEFINITION = {
    "plugin_kind": "service",
    "vendor": VENDOR_BLOCK,
    "service": {"public_id": "tests.gh", "protocol": 1},
    "features": [],
    "connections": [GITHUB_CONNECTION],
}

SECRET = "shpat_supersecret"
VALID_ADMIN_VALUES = {"shop_domain": "example.test", "admin_token": SECRET}


async def _install(session: AsyncSession, actor, definition=SERVICE_DEFINITION):
    return await create_guild_plugin(
        session, actor.guild, actor.user, definition=definition
    )


async def _rows(session: AsyncSession, guild_id: int) -> list:
    """The connection rows as stored, read past RLS via the setup session."""
    await route_session_to_guild(session, guild_id)
    return list((await session.exec(select(GuildPluginUserConnection))).all())


@pytest.fixture(autouse=True)
async def wired_plugin_services(session: AsyncSession):
    """The deployment has both test plug-ins wired up.

    Starting a member's vendor flow sends them to the plug-in's own URL, which
    comes from a registration — so a guild whose plug-in service is not registered
    here has nowhere to send anyone. Every test in this file assumes the
    ordinary case: the operator wired the plug-in up, and it is switched on.
    """
    return [
        await create_plugin_service_registration(
            session,
            public_id=public_id,
            base_url=f"https://{slug}.example.test",
            vendor_values=sealed_vendor_values(VENDOR_VALUES),
        )
        for public_id, slug in (("tests.shop", "shop"), ("tests.gh", "github"))
    ]


async def _connected(
    session: AsyncSession, actor, plugin, connection_id: str = "github"
) -> GuildPluginUserConnection:
    """A member connection as a completed flow leaves it."""
    return await create_plugin_user_connection(
        session,
        plugin,
        actor.user,
        connection_id=connection_id,
        config={"login": "someone"},
        secrets={"access_token": encrypt_field("gho_member", SALT_PLUGIN_CONFIG)},
    )


@pytest.fixture
def recorded_revocations(monkeypatch):
    """Capture what each teardown asked the plug-ins to revoke.

    The transport itself belongs to the plug-in protocol; what this phase owes is
    that an intent is raised for every credential it deletes, addressed by the
    handle the plug-in knows it by. Recorded as the commit hands them over.
    """
    captured: list = []

    def _capture(intents):
        captured.extend(intents)
        return asyncio.sleep(0)

    monkeypatch.setattr(plugin_revocation, "dispatch_revocations", _capture)
    return captured


# ---------------------------------------------------------------------------
# Installing a service plug-in
# ---------------------------------------------------------------------------


class TestInstallKind:
    async def test_a_service_listing_installs_with_its_connections(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Installing through the endpoint is what makes this whole file
        reachable in production: the row pins the listing's definition, and the
        form a guild fills in is read straight off it."""
        uid = marketplace_uid("servicelisting")
        await create_marketplace_listing(
            session,
            uid=uid,
            public_id="tests.service",
            kind="plugin",
            definition=SERVICE_DEFINITION,
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)
        response = await client.post(
            a.g("/plugins/"), headers=a.headers, json={"listing_uid": uid}
        )
        assert response.status_code == 201, response.text
        plugin_id = response.json()["id"]

        detail = (
            await client.get(a.g(f"/plugins/{plugin_id}"), headers=a.headers)
        ).json()
        assert [c["id"] for c in detail["connections"]] == ["admin", "github"]


class TestInstallIsNotGatedOnAConnection:
    async def test_a_plugin_with_only_member_connections_needs_no_configuration(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Nobody has to connect for the install to be valid."""
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a, MEMBER_ONLY_DEFINITION)

        response = await client.get(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["needs_config"] is False
        assert body["config_state"] == "unverified"
        assert [c["id"] for c in body["connections"]] == ["github"]
        assert body["connections"][0]["satisfied"] is False

    async def test_a_guild_credential_is_reported_as_outstanding(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        body = (
            await client.get(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
        ).json()
        assert body["needs_config"] is True


# ---------------------------------------------------------------------------
# Guild-scoped configuration
# ---------------------------------------------------------------------------


class TestConfig:
    async def test_a_secret_is_stored_and_echoed_only_as_presence(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)

        response = await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        assert response.status_code == 200, response.text
        body = response.json()

        admin = next(c for c in body["connections"] if c["id"] == "admin")
        assert admin["has_value"] == {"shop_domain": True, "admin_token": True}
        assert admin["satisfied"] is True
        assert body["needs_config"] is False
        # The whole payload, not just the field somebody remembered to hide.
        assert SECRET not in response.text

    async def test_a_guild_value_is_read_back_by_the_seat_alone(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """The seat reads back what it set, to edit it; an administrator below
        the seat and a member are told only that it is there."""
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, seat)
        response = await client.put(
            seat.g(f"/plugins/{plugin.id}/config"),
            headers=seat.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        assert response.status_code == 200, response.text
        admin = await acting_user(guild_role=CommunityRole.admin, guild=seat.guild)
        member = await acting_user(guild_role=CommunityRole.member, guild=seat.guild)

        for viewer, values in (
            (seat, {"shop_domain": "example.test"}),
            (admin, {}),
            (member, {}),
        ):
            body = (
                await client.get(
                    viewer.g(f"/plugins/{plugin.id}"), headers=viewer.headers
                )
            ).json()
            block = next(c for c in body["connections"] if c["id"] == "admin")
            assert block["values"] == values
            assert block["has_value"] == {"shop_domain": True, "admin_token": True}

    async def test_the_secret_is_not_in_the_list_payload_either(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        listed = await client.get(a.g("/plugins/"), headers=a.headers)
        assert SECRET not in listed.text

    async def test_configuring_is_a_guild_admin_action(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.put(
            member.g(f"/plugins/{plugin.id}/config"),
            headers=member.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED

    async def test_values_are_validated_against_the_pinned_schema(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)

        response = await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"admin": {**VALID_ADMIN_VALUES, "nope": "x"}}},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == GuildPluginMessages.CONFIG_UNKNOWN_FIELD

    async def test_an_unknown_connection_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        response = await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"stripe": {"key": "x"}}},
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"] == GuildPluginMessages.CONFIG_UNKNOWN_CONNECTION
        )

    async def test_a_per_member_connection_is_not_set_through_the_form(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """It is that member's to make, and the plug-in writes the result."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        response = await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"github": {"access_token": "gho_x"}}},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == GuildPluginMessages.CONNECTION_NOT_STATIC

    async def test_a_required_field_left_empty_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        response = await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"admin": {"shop_domain": "example.test"}}},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == GuildPluginMessages.CONFIG_REQUIRED_FIELD

    async def test_writing_configuration_resets_the_plugins_verdict(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Whatever the plug-in said about the old values is not an answer about
        the new ones."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await create_guild_plugin(
            session,
            a.guild,
            a.user,
            definition=SERVICE_DEFINITION,
            config_state="ok",
        )

        body = (
            await client.put(
                a.g(f"/plugins/{plugin.id}/config"),
                headers=a.headers,
                json={"values": {"admin": VALID_ADMIN_VALUES}},
            )
        ).json()
        assert body["config_state"] == "unverified"

    async def test_clearing_a_guild_credential_revokes_it(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )

        response = await client.delete(
            a.g(f"/plugins/{plugin.id}/connections/admin"), headers=a.headers
        )
        assert response.status_code == 204
        assert [i.connection_id for i in recorded_revocations] == ["admin"]

        body = (
            await client.get(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
        ).json()
        assert body["needs_config"] is True


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

#: A unique setting Initiative assigns from the community's name.
PREFIX_SETTING = {
    "key": "task_prefix",
    "type": "string",
    "label": {"en": "Task prefix"},
    "unique": True,
    "assigned": "community_name",
}

SETTINGS_DEFINITION = {
    **MEMBER_ONLY_DEFINITION,
    "settings": [
        PREFIX_SETTING,
        {"key": "team", "type": "string", "label": {"en": "Team"}},
    ],
}

SETTINGS_UID = marketplace_uid("prefixed")


async def _seat(acting_user, session: AsyncSession, name: str):
    """The seat of a community called ``name``."""
    return await acting_user(
        guild_role=CommunityRole.superadmin,
        guild=await create_guild(session, name=name),
    )


def _setting(body: dict, key: str) -> tuple:
    """A setting's value and earlier values, as the detail reports them."""
    setting = next(one for one in body["settings"] if one["key"] == key)
    return setting["value"], setting["aliases"]


async def _claims(session: AsyncSession) -> set[tuple]:
    """Every claimed value, read past RLS by the setup session."""
    rows = (await session.exec(select(PluginInstallClaim))).all()
    return {(row.guild_id, row.install_id, row.value) for row in rows}


@pytest.fixture
def drawn(monkeypatch):
    """Random letters and digits, drawn the same every time: ``zqzq…``."""
    monkeypatch.setattr(
        plugin_installs, "_random", lambda alphabet, length: ("zq" * 8)[:length]
    )


class TestSettings:
    @pytest.mark.parametrize(
        ("name", "assigned"),
        [
            ("Acme Studio", "acmestudio"),
            ("3M Café Society International", "mcafesocietyinte"),
            ("42", "zqzq"),
        ],
    )
    async def test_installing_assigns_a_value_from_the_communitys_name(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        drawn,
        name,
        assigned,
    ):
        """Its letters and digits, without accents, in lowercase, from its
        first letter, cut to 16; random letters for a name that gives fewer
        than two. The value is claimed for the install."""
        await create_marketplace_listing(
            session,
            uid=SETTINGS_UID,
            public_id="tests.gh",
            kind="plugin",
            definition=SETTINGS_DEFINITION,
        )
        seat = await _seat(acting_user, session, name)

        response = await client.post(
            seat.g("/plugins/"),
            headers=seat.headers,
            json={"listing_uid": SETTINGS_UID},
        )
        assert response.status_code == 201, response.text
        plugin_id = response.json()["id"]

        body = (
            await client.get(seat.g(f"/plugins/{plugin_id}"), headers=seat.headers)
        ).json()
        assert body["settings"] == [
            {
                "key": "task_prefix",
                "label": {"en": "Task prefix"},
                "description": {},
                "unique": True,
                "value": assigned,
                "aliases": [],
            },
            {
                "key": "team",
                "label": {"en": "Team"},
                "description": {},
                "unique": False,
                "value": None,
                "aliases": [],
            },
        ]
        assert await _claims(session) == {(seat.guild.id, plugin_id, assigned)}

    async def test_a_value_another_community_holds_gets_a_random_suffix(
        self, acting_user, session: AsyncSession, drawn
    ):
        """Never the next number."""
        first = await _seat(acting_user, session, "Acme")
        second = await _seat(acting_user, session, "ACME!")

        held = await create_guild_plugin(
            session, first.guild, first.user, definition=SETTINGS_DEFINITION
        )
        suffixed = await create_guild_plugin(
            session, second.guild, second.user, definition=SETTINGS_DEFINITION
        )

        assert suffixed.settings == {"task_prefix": "acmezq"}
        assert await _claims(session) == {
            (first.guild.id, held.id, "acme"),
            (second.guild.id, suffixed.id, "acmezq"),
        }

    async def test_an_update_that_declares_an_assigned_setting_assigns_it(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        await create_marketplace_listing(
            session,
            uid=SETTINGS_UID,
            public_id="tests.gh",
            kind="plugin",
            version="1.0.0",
            definition=MEMBER_ONLY_DEFINITION,
        )
        seat = await _seat(acting_user, session, "Acme")
        installed = await client.post(
            seat.g("/plugins/"),
            headers=seat.headers,
            json={"listing_uid": SETTINGS_UID},
        )
        plugin_id = installed.json()["id"]
        await create_marketplace_listing(
            session,
            uid=SETTINGS_UID,
            public_id="tests.gh",
            kind="plugin",
            version="1.1.0",
            definition=SETTINGS_DEFINITION,
        )

        response = await client.post(
            seat.g(f"/plugins/{plugin_id}/upgrade"), headers=seat.headers
        )

        assert response.status_code == 200, response.text
        assert _setting(response.json(), "task_prefix") == ("acme", [])

    async def test_a_rename_keeps_the_value_it_replaces_as_an_earlier_one(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """It stays the community's, and renaming back to it makes it current
        again. A unique value is kept in lowercase."""
        seat = await _seat(acting_user, session, "Acme")
        plugin = await create_guild_plugin(
            session, seat.guild, seat.user, definition=SETTINGS_DEFINITION
        )
        url = seat.g(f"/plugins/{plugin.id}/settings/task_prefix")

        renamed = await client.put(url, headers=seat.headers, json={"value": "AcmeCo"})
        assert renamed.status_code == 200, renamed.text
        assert _setting(renamed.json(), "task_prefix") == ("acmeco", ["acme"])

        back = await client.put(url, headers=seat.headers, json={"value": "acme"})
        assert back.status_code == 200, back.text
        assert _setting(back.json(), "task_prefix") == ("acme", ["acmeco"])
        assert await _claims(session) == {
            (seat.guild.id, plugin.id, "acme"),
            (seat.guild.id, plugin.id, "acmeco"),
        }

    async def test_a_setting_that_is_not_unique_holds_a_line_and_clears(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        seat = await _seat(acting_user, session, "Acme")
        plugin = await create_guild_plugin(
            session, seat.guild, seat.user, definition=SETTINGS_DEFINITION
        )
        url = seat.g(f"/plugins/{plugin.id}/settings/team")

        typed = await client.put(url, headers=seat.headers, json={"value": " Web "})
        assert _setting(typed.json(), "team") == ("Web", [])
        cleared = await client.put(url, headers=seat.headers, json={"value": None})
        assert _setting(cleared.json(), "team") == (None, [])

    @pytest.mark.parametrize(
        ("key", "value", "status", "code"),
        [
            ("task_prefix", "acmenew", 409, GuildPluginMessages.SETTING_UNAVAILABLE),
            ("task_prefix", "ACME", 409, GuildPluginMessages.SETTING_UNAVAILABLE),
            ("task_prefix", "acme-1", 400, GuildPluginMessages.SETTING_INVALID),
            ("task_prefix", None, 400, GuildPluginMessages.SETTING_INVALID),
            ("nope", "x", 404, GuildPluginMessages.SETTING_NOT_FOUND),
        ],
    )
    async def test_a_value_it_cannot_take_is_refused(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        key,
        value,
        status,
        code,
    ):
        """One another community holds, now or as an earlier value, whatever
        its case, is refused with one code that says nothing more; a unique
        value not of its form, or none, with another. The install keeps its
        own."""
        other = await _seat(acting_user, session, "Acme")
        held = await create_guild_plugin(
            session, other.guild, other.user, definition=SETTINGS_DEFINITION
        )
        moved = await client.put(
            other.g(f"/plugins/{held.id}/settings/task_prefix"),
            headers=other.headers,
            json={"value": "acmenew"},
        )
        assert moved.status_code == 200, moved.text
        seat = await _seat(acting_user, session, "Beta")
        plugin = await create_guild_plugin(
            session, seat.guild, seat.user, definition=SETTINGS_DEFINITION
        )

        response = await client.put(
            seat.g(f"/plugins/{plugin.id}/settings/{key}"),
            headers=seat.headers,
            json={"value": value},
        )

        assert response.status_code == status
        assert response.json()["detail"] == code
        body = (
            await client.get(seat.g(f"/plugins/{plugin.id}"), headers=seat.headers)
        ).json()
        assert _setting(body, "task_prefix") == ("beta", [])

    async def test_an_update_that_makes_a_setting_unique_claims_what_it_holds(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """The first community to update keeps its value and claims it; one
        whose value another community claimed first is given a value of its
        own."""
        await create_marketplace_listing(
            session,
            uid=SETTINGS_UID,
            public_id="tests.gh",
            kind="plugin",
            version="1.0.0",
            definition={
                **MEMBER_ONLY_DEFINITION,
                "settings": [
                    {"key": "task_prefix", "type": "string", "label": {"en": "P"}}
                ],
            },
        )
        installs = []
        for name in ("Acme", "Beta"):
            seat = await _seat(acting_user, session, name)
            installed = await client.post(
                seat.g("/plugins/"),
                headers=seat.headers,
                json={"listing_uid": SETTINGS_UID},
            )
            plugin_id = installed.json()["id"]
            typed = await client.put(
                seat.g(f"/plugins/{plugin_id}/settings/task_prefix"),
                headers=seat.headers,
                json={"value": "acme"},
            )
            assert typed.status_code == 200, typed.text
            installs.append((seat, plugin_id))
        assert await _claims(session) == set()
        await create_marketplace_listing(
            session,
            uid=SETTINGS_UID,
            public_id="tests.gh",
            kind="plugin",
            version="1.1.0",
            definition=SETTINGS_DEFINITION,
        )

        upgraded = [
            await client.post(
                seat.g(f"/plugins/{plugin_id}/upgrade"), headers=seat.headers
            )
            for seat, plugin_id in installs
        ]

        assert [_setting(one.json(), "task_prefix") for one in upgraded] == [
            ("acme", []),
            ("beta", []),
        ]
        (first, first_id), (second, second_id) = installs
        assert await _claims(session) == {
            (first.guild.id, first_id, "acme"),
            (second.guild.id, second_id, "beta"),
        }

    async def test_a_setting_unique_once_before_keeps_its_value(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """A value the install claimed when the setting was unique is its own
        when an update makes the setting unique again."""
        plain = {
            **MEMBER_ONLY_DEFINITION,
            "settings": [
                {"key": "task_prefix", "type": "string", "label": {"en": "P"}}
            ],
        }
        for version, definition in (
            ("1.0.0", SETTINGS_DEFINITION),
            ("1.1.0", plain),
            ("1.2.0", SETTINGS_DEFINITION),
        ):
            await create_marketplace_listing(
                session,
                uid=SETTINGS_UID,
                public_id="tests.gh",
                kind="plugin",
                version=version,
                definition=definition,
            )
            if version == "1.0.0":
                seat = await _seat(acting_user, session, "Acme")
                installed = await client.post(
                    seat.g("/plugins/"),
                    headers=seat.headers,
                    json={"listing_uid": SETTINGS_UID},
                )
                plugin_id = installed.json()["id"]
                continue
            upgraded = await client.post(
                seat.g(f"/plugins/{plugin_id}/upgrade"), headers=seat.headers
            )
            assert upgraded.status_code == 200, upgraded.text

        assert _setting(upgraded.json(), "task_prefix") == ("acme", [])
        assert await _claims(session) == {(seat.guild.id, plugin_id, "acme")}

    async def test_removing_the_plugin_gives_its_values_back(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Every value it held, the earlier ones too, goes with it, and another
        community may take one."""
        first = await _seat(acting_user, session, "Acme")
        plugin = await create_guild_plugin(
            session, first.guild, first.user, definition=SETTINGS_DEFINITION
        )
        renamed = await client.put(
            first.g(f"/plugins/{plugin.id}/settings/task_prefix"),
            headers=first.headers,
            json={"value": "acmeco"},
        )
        assert renamed.status_code == 200, renamed.text

        removed = await client.delete(
            first.g(f"/plugins/{plugin.id}"), headers=first.headers
        )
        assert removed.status_code == 204, removed.text
        assert await _claims(session) == set()

        second = await _seat(acting_user, session, "Acme")
        again = await create_guild_plugin(
            session, second.guild, second.user, definition=SETTINGS_DEFINITION
        )
        assert again.settings == {"task_prefix": "acme"}


# ---------------------------------------------------------------------------
# A member's own connection
# ---------------------------------------------------------------------------


class TestConnect:
    async def test_any_member_may_connect_their_own_account(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """The vendor is going to authorize *them*: what the credential reaches
        is what they already reach, so this is not an admin's decision.

        Initiative runs the flow, so the address is the vendor's authorization
        endpoint with this deployment's client and callback, and nothing is
        stored until the vendor sends the member back."""
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.post(
            member.g(f"/plugins/{plugin.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "pending"
        assert "connection_ref" not in body

        connect = urlparse(body["connect_url"])
        assert f"{connect.scheme}://{connect.netloc}{connect.path}" == (
            "https://github.test/login/oauth/authorize"
        )
        query = parse_qs(connect.query)
        assert query["client_id"] == ["client-123"]
        assert query["redirect_uri"] == [callback_url()]
        assert query["response_type"] == ["code"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["state"][0]
        # The client's secret is the deployment's, and never in an address.
        assert "client-secret-456" not in body["connect_url"]
        assert await _rows(session, a.guild.id) == []

    async def test_a_typed_connection_is_not_connected_to(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """No ``flow``, so there is no vendor to send anybody to.

        The scope is not what decides this — a guild-wide connection may run a
        flow of its own. Declaring one is.
        """
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        response = await client.post(
            a.g(f"/plugins/{plugin.id}/connections/admin/connect"), headers=a.headers
        )
        assert response.status_code == 409
        assert (
            response.json()["detail"] == GuildPluginMessages.CONNECTION_NOT_INTERACTIVE
        )

    async def test_an_admin_starts_the_guild_s_own_vendor_flow(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """One credential for everybody, obtained rather than typed: the seat is
        sent to the vendor's install page first."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a, definition=WORKSPACE_DEFINITION)

        response = await client.post(
            a.g(f"/plugins/{plugin.id}/connections/workspace/connect"),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "pending"

        connect = urlparse(body["connect_url"])
        assert f"{connect.scheme}://{connect.netloc}{connect.path}" == (
            "https://github.test/apps/initiative-test/installations/new"
        )
        assert parse_qs(connect.query)["state"][0]

        # Nothing is stored while the flow is in progress.
        await route_session_to_guild(session, a.guild.id)
        await session.refresh(plugin)
        assert plugin.connection_refs == {}
        assert await _rows(session, a.guild.id) == []

    async def test_a_member_may_not_start_the_guild_s_flow(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """The install it produces is the guild's boundary, which is the seat's
        to decide, exactly as typing the same connection would be."""
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a, definition=WORKSPACE_DEFINITION)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.post(
            member.g(f"/plugins/{plugin.id}/connections/workspace/connect"),
            headers=member.headers,
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED

    async def test_a_flow_needs_the_vendor_values(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """The flow names the operator's client values; without them there is
        no address to send anybody to."""
        await create_plugin_service_registration(
            session,
            public_id="tests.bare",
            base_url="https://bare.example.test",
        )
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(
            session,
            a,
            {**MEMBER_ONLY_DEFINITION, "service": {"public_id": "tests.bare"}},
        )

        response = await client.post(
            a.g(f"/plugins/{plugin.id}/connections/github/connect"), headers=a.headers
        )
        assert response.status_code == 409
        assert (
            response.json()["detail"]
            == GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED
        )

    async def test_an_unknown_connection_is_a_404(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        response = await client.post(
            a.g(f"/plugins/{plugin.id}/connections/nope/connect"), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == GuildPluginMessages.CONNECTION_NOT_FOUND

    async def test_a_disabled_plugin_accepts_no_new_connections(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        await client.patch(
            a.g(f"/plugins/{plugin.id}"), headers=a.headers, json={"enabled": False}
        )
        response = await client.post(
            a.g(f"/plugins/{plugin.id}/connections/github/connect"),
            headers=a.headers,
        )
        assert response.status_code == 409
        assert response.json()["detail"] == GuildPluginMessages.DISABLED

    async def test_a_member_disconnects_their_own(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        await _connected(session, member, plugin)

        response = await client.delete(
            member.g(f"/plugins/{plugin.id}/connections/github"), headers=member.headers
        )
        assert response.status_code == 204
        assert await _rows(session, a.guild.id) == []
        assert [i.reason for i in recorded_revocations] == ["disconnected"]


# ---------------------------------------------------------------------------
# Own row, or guild admin — and nothing in between
# ---------------------------------------------------------------------------


class TestConnectionVisibility:
    async def test_a_second_member_does_not_see_the_firsts_connection(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """One member's vendor account is not another member's business. The
        gate is the table's own-row policy, so there is no endpoint branch that
        could be forgotten."""
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        first = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        second = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        await _connected(session, first, plugin)

        body = (
            await client.get(second.g(f"/plugins/{plugin.id}"), headers=second.headers)
        ).json()
        github = next(c for c in body["connections"] if c["id"] == "github")
        assert github["status"] is None
        assert github["satisfied"] is False
        assert github["blocked"] is False

    async def test_the_connecting_member_sees_their_own(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        await _connected(session, member, plugin)

        body = (
            await client.get(member.g(f"/plugins/{plugin.id}"), headers=member.headers)
        ).json()
        github = next(c for c in body["connections"] if c["id"] == "github")
        assert github["status"] == "connected"
        assert github["values"] == {"login": "someone"}
        assert "gho_member" not in str(body)

    async def test_a_member_may_not_read_the_members_view(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.get(
            member.g(f"/plugins/{plugin.id}/members"), headers=member.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildMessages.COMMUNITY_SUPERADMIN_REQUIRED

    async def test_a_guild_admin_sees_every_members_connection(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Admins have full authority over their guild, and knowing who reaches
        an outside system through it is part of that."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        first = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        second = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        for actor in (first, second):
            await _connected(session, actor, plugin)

        body = (
            await client.get(a.g(f"/plugins/{plugin.id}/members"), headers=a.headers)
        ).json()
        assert sorted(item["user_id"] for item in body["items"]) == sorted(
            [first.user.id, second.user.id]
        )
        github = next(s for s in body["summary"] if s["connection_id"] == "github")
        assert github["connected_count"] == 2
        assert github["blocked_count"] == 0
        # Three members in the guild: the admin plus the two who connected.
        assert github["member_count"] == 3

        # A page holds some of the members; the counts still cover everyone.
        paged = (
            await client.get(
                a.g(f"/plugins/{plugin.id}/members"),
                params={"page_size": 1, "page": 2},
                headers=a.headers,
            )
        ).json()
        assert paged["total_count"] == 2
        assert [item["user_id"] for item in paged["items"]] == [
            max(first.user.id, second.user.id)
        ]
        github = next(s for s in paged["summary"] if s["connection_id"] == "github")
        assert github["connected_count"] == 2

    async def test_the_members_view_carries_no_values_and_no_handles(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Revoking beats reading: no admin workflow needs the bytes, and the
        handle is between the platform and the plug-in."""
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        started = await _connected(session, member, plugin)
        ref = started.connection_ref

        response = await client.get(
            a.g(f"/plugins/{plugin.id}/members"), headers=a.headers
        )
        assert ref not in response.text
        assert "config_secrets" not in response.text

    async def test_another_guilds_admin_sees_nothing(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        await _connected(session, a, plugin)
        stranger = await acting_user(guild_role=CommunityRole.admin)

        response = await client.get(
            stranger.g(f"/plugins/{plugin.id}"), headers=stranger.headers
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Admin governance
# ---------------------------------------------------------------------------


class TestGovernance:
    async def test_an_admin_revokes_one_members_connection(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        await _connected(session, member, plugin)

        response = await client.delete(
            a.g(f"/plugins/{plugin.id}/members/{member.user.id}/connections/github"),
            headers=a.headers,
        )
        assert response.status_code == 204
        assert await _rows(session, a.guild.id) == []
        assert [i.reason for i in recorded_revocations] == ["admin_revoked"]

    async def test_a_revoked_member_may_connect_again(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        await _connected(session, member, plugin)
        await client.delete(
            a.g(f"/plugins/{plugin.id}/members/{member.user.id}/connections/github"),
            headers=a.headers,
        )

        again = await client.post(
            member.g(f"/plugins/{plugin.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert again.status_code == 200

    async def test_blocking_revokes_and_refuses_the_next_attempt(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        await _connected(session, member, plugin)

        blocked = await client.post(
            a.g(
                f"/plugins/{plugin.id}/members/{member.user.id}/connections/github/block"
            ),
            headers=a.headers,
        )
        assert blocked.status_code == 204
        assert [i.reason for i in recorded_revocations] == ["blocked"]

        retry = await client.post(
            member.g(f"/plugins/{plugin.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert retry.status_code == 403
        assert retry.json()["detail"] == GuildPluginMessages.CONNECTION_BLOCKED

    async def test_a_block_leaves_a_tombstone_holding_no_values(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        await _connected(session, member, plugin)
        await client.post(
            a.g(
                f"/plugins/{plugin.id}/members/{member.user.id}/connections/github/block"
            ),
            headers=a.headers,
        )

        rows = await _rows(session, a.guild.id)
        assert len(rows) == 1
        assert rows[0].blocked_at is not None
        assert rows[0].blocked_by_id == a.user.id
        assert rows[0].secret_fields == {}
        assert await load_connection_secrets(session, rows[0]) == {}
        assert rows[0].status == "blocked"

    async def test_a_members_values_are_theirs_alone(
        self, acting_user, session: AsyncSession, reading_as
    ):
        """The member reads what their connection holds. The seat sees that
        they connected, and a plain admin and another member see nothing."""
        from sqlmodel import select

        from app.models.tenant.guild_plugin_user_connection import (
            GuildPluginUserConnection,
        )
        from app.models.tenant.plugin_connection_secret import PluginConnectionSecret

        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, seat)
        member, other = [
            await acting_user(guild_role=CommunityRole.member, guild=seat.guild)
            for _ in range(2)
        ]
        admin = await acting_user(guild_role=CommunityRole.admin, guild=seat.guild)
        await _connected(session, member, plugin)

        for reader, values, rows in (
            (member, 1, 1),
            (seat, 0, 1),
            (admin, 0, 0),
            (other, 0, 0),
        ):
            asking = await reading_as(reader.user.id, seat.guild.id)
            held = (await asking.exec(select(PluginConnectionSecret))).all()
            seen = (await asking.exec(select(GuildPluginUserConnection))).all()
            assert (len(held), len(seen)) == (values, rows), reader

    async def test_a_member_can_be_blocked_before_ever_connecting(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.post(
            a.g(
                f"/plugins/{plugin.id}/members/{member.user.id}/connections/github/block"
            ),
            headers=a.headers,
        )
        assert response.status_code == 204
        retry = await client.post(
            member.g(f"/plugins/{plugin.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert retry.status_code == 403

    async def test_lifting_a_block_lets_them_connect_again(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        await client.post(
            a.g(
                f"/plugins/{plugin.id}/members/{member.user.id}/connections/github/block"
            ),
            headers=a.headers,
        )

        lifted = await client.delete(
            a.g(
                f"/plugins/{plugin.id}/members/{member.user.id}/connections/github/block"
            ),
            headers=a.headers,
        )
        assert lifted.status_code == 204
        retry = await client.post(
            member.g(f"/plugins/{plugin.id}/connections/github/connect"),
            headers=member.headers,
        )
        assert retry.status_code == 200

    async def test_revoke_all_ends_everyones_without_touching_the_install(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        """For a suspected compromise: reacting fast should not cost the guild
        its configuration."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )
        members = [
            await acting_user(guild_role=CommunityRole.member, guild=a.guild)
            for _ in range(2)
        ]
        for member in members:
            await _connected(session, member, plugin)

        response = await client.post(
            a.g(f"/plugins/{plugin.id}/revoke-all"), headers=a.headers
        )
        assert response.status_code == 204
        assert await _rows(session, a.guild.id) == []
        assert len(recorded_revocations) == 2

        # The install and its guild credential are still standing.
        body = (
            await client.get(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
        ).json()
        assert body["needs_config"] is False

    async def test_governance_is_admin_only(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        other = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        base = f"/plugins/{plugin.id}/members/{other.user.id}/connections/github"
        assert (
            await client.delete(member.g(base), headers=member.headers)
        ).status_code == 403
        assert (
            await client.post(member.g(f"{base}/block"), headers=member.headers)
        ).status_code == 403
        assert (
            await client.post(
                member.g(f"/plugins/{plugin.id}/revoke-all"), headers=member.headers
            )
        ).status_code == 403


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


UPGRADE_UID = marketplace_uid("upgradeable")


def _tool_definition() -> dict:
    return {"plugin_kind": "tool_instance", "tool": "calendar", "default_name": "Cal"}


class TestUpgrade:
    async def test_upgrading_re_pins_to_the_current_version(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        await create_marketplace_listing(
            session,
            uid=UPGRADE_UID,
            public_id="tests.upgradeable",
            kind="plugin",
            version="1.0.0",
            definition=_tool_definition(),
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)
        installed = await client.post(
            a.g("/plugins/"), headers=a.headers, json={"listing_uid": UPGRADE_UID}
        )
        plugin_id = installed.json()["id"]
        assert installed.json()["listing_version"] == "1.0.0"

        await create_marketplace_listing(
            session,
            uid=UPGRADE_UID,
            public_id="tests.upgradeable",
            kind="plugin",
            version="1.1.0",
            definition={**_tool_definition(), "default_name": "Cal v2"},
        )

        # What the settings page draws its Update button from.
        offered = await client.get(a.g(f"/plugins/{plugin_id}"), headers=a.headers)
        assert offered.json()["update_version"] == "1.1.0"

        response = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["listing_version"] == "1.1.0"
        # And the button goes away rather than offering the version just taken.
        assert response.json()["update_version"] is None

    async def test_a_switched_off_service_still_upgrades_its_installs(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        wired_plugin_services,
    ):
        """Whether this deployment runs the service decides whether a guild may
        *take* the plug-in. The install this guild already has stays theirs, and
        keeps following the versions its publisher ships, so switching the
        service back on finds it current rather than a version behind."""
        uid = marketplace_uid("offbutinstalled")
        await create_marketplace_listing(
            session,
            uid=uid,
            public_id="tests.offbutinstalled",
            kind="plugin",
            version="1.0.0",
            definition=SERVICE_DEFINITION,
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)
        installed = await client.post(
            a.g("/plugins/"), headers=a.headers, json={"listing_uid": uid}
        )
        plugin_id = installed.json()["id"]

        shop, _ = wired_plugin_services
        shop.enabled = False
        session.add(shop)
        await session.commit()
        invalidate_registrations()

        await create_marketplace_listing(
            session,
            uid=uid,
            public_id="tests.offbutinstalled",
            kind="plugin",
            version="1.1.0",
            definition=SERVICE_DEFINITION,
        )

        detail = await client.get(a.g(f"/plugins/{plugin_id}"), headers=a.headers)
        assert detail.json()["update_version"] == "1.1.0"
        assert detail.json()["available"] is False

        response = await client.post(
            a.g(f"/plugins/{plugin_id}/upgrade"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["listing_version"] == "1.1.0"

    async def test_upgrading_to_the_pinned_version_is_refused(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        await create_marketplace_listing(
            session,
            uid=marketplace_uid("alreadylatest"),
            public_id="tests.alreadylatest",
            kind="plugin",
            definition=_tool_definition(),
        )
        a = await acting_user(guild_role=CommunityRole.superadmin)
        installed = await client.post(
            a.g("/plugins/"),
            headers=a.headers,
            json={"listing_uid": marketplace_uid("alreadylatest")},
        )
        response = await client.post(
            a.g(f"/plugins/{installed.json()['id']}/upgrade"), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == MarketplaceMessages.ALREADY_LATEST_VERSION

    async def test_upgrading_is_admin_only(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        plugin = await _install(session, a)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        response = await client.post(
            member.g(f"/plugins/{plugin.id}/upgrade"), headers=member.headers
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Teardown: access ends when the relationship does
# ---------------------------------------------------------------------------


async def _connected_member(client, acting_user, session, admin):
    plugin = await _install(session, admin)
    member = await acting_user(guild_role=CommunityRole.member, guild=admin.guild)
    await _connected(session, member, plugin)
    return plugin, member


class TestUninstallKillsAccess:
    async def test_uninstalling_deletes_every_members_connection(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        """An uninstalled plug-in still receiving a guild's data is the thing this
        prevents — so the values go, and the plug-in is told."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin, _member = await _connected_member(client, acting_user, session, a)
        await client.put(
            a.g(f"/plugins/{plugin.id}/config"),
            headers=a.headers,
            json={"values": {"admin": VALID_ADMIN_VALUES}},
        )

        response = await client.delete(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
        assert response.status_code == 204
        assert await _rows(session, a.guild.id) == []
        reasons = {i.reason for i in recorded_revocations}
        assert reasons == {"uninstalled"}
        # Both halves: the member's handle, and the guild-scoped credential.
        assert any(i.connection_ref for i in recorded_revocations)
        assert any(i.connection_ref is None for i in recorded_revocations)

    async def test_uninstalling_takes_blocked_tombstones_too(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """A block on a plug-in that is no longer installed constrains nothing."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin, member = await _connected_member(client, acting_user, session, a)
        await client.post(
            a.g(
                f"/plugins/{plugin.id}/members/{member.user.id}/connections/github/block"
            ),
            headers=a.headers,
        )

        await client.delete(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
        assert await _rows(session, a.guild.id) == []


class TestRelationshipCascades:
    async def test_leaving_a_guild_ends_the_connections_made_in_it(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        _, member = await _connected_member(client, acting_user, session, a)

        response = await client.delete(
            f"/api/v1/communities/{a.guild.id}/leave", headers=member.headers
        )
        assert response.status_code == 204, response.text
        assert await _rows(session, a.guild.id) == []
        assert [i.reason for i in recorded_revocations] == ["left_guild"]

    async def test_being_removed_from_a_guild_ends_them_too(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        a = await acting_user(guild_role=CommunityRole.admin)
        _, member = await _connected_member(client, acting_user, session, a)

        response = await client.delete(
            a.g(f"/users/{member.user.id}"), headers=a.headers
        )
        assert response.status_code == 204, response.text
        assert await _rows(session, a.guild.id) == []
        assert [i.reason for i in recorded_revocations] == ["removed_from_guild"]
        # A plain admin never reads the member's values; the platform hands
        # the vendor the token all the same.
        assert set(recorded_revocations[0].sealed_tokens) == {"access_token"}

    async def test_leaving_does_not_touch_another_guild(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Their access elsewhere is a relationship that has not ended."""
        a = await acting_user(guild_role=CommunityRole.admin)
        b = await acting_user(guild_role=CommunityRole.admin)
        _, member = await _connected_member(client, acting_user, session, a)
        plugin_b = await _install(session, b)
        await _connected(session, b, plugin_b)

        await client.delete(
            f"/api/v1/communities/{a.guild.id}/leave", headers=member.headers
        )
        assert await _rows(session, a.guild.id) == []
        assert len(await _rows(session, b.guild.id)) == 1

    async def test_a_block_survives_the_member_leaving(
        self, client: AsyncClient, acting_user, session: AsyncSession
    ):
        """Somebody removed and later re-invited must not come back with the
        block quietly lifted."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin, member = await _connected_member(client, acting_user, session, a)
        await client.post(
            a.g(
                f"/plugins/{plugin.id}/members/{member.user.id}/connections/github/block"
            ),
            headers=a.headers,
        )

        await client.delete(
            f"/api/v1/communities/{a.guild.id}/leave", headers=member.headers
        )
        rows = await _rows(session, a.guild.id)
        assert len(rows) == 1
        assert rows[0].blocked_at is not None

    async def test_deleting_a_guild_revokes_before_the_schema_goes(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        """The DROP would take the rows silently, leaving vendor grants
        outliving the guild that authorized them."""
        # Deleting a community belongs to the seat.
        a = await acting_user(guild_role=CommunityRole.superadmin)
        await _connected_member(client, acting_user, session, a)

        response = await client.request(
            "DELETE",
            f"/api/v1/communities/{a.guild.id}",
            headers=a.headers,
            json={
                "password": "testpassword123",
                "confirmation_text": f"DELETE COMMUNITY {a.guild.name.upper()}",
            },
        )
        assert response.status_code == 204, response.text
        assert [i.reason for i in recorded_revocations] == ["guild_deleted"]


class TestAccountDeletionSweep:
    async def test_closing_an_account_ends_connections_in_every_guild(
        self,
        client: AsyncClient,
        acting_user,
        session: AsyncSession,
        recorded_revocations,
    ):
        """One sweep across all their memberships, not a per-guild chore."""
        admin_a = await acting_user(guild_role=CommunityRole.admin)
        admin_b = await acting_user(guild_role=CommunityRole.admin)
        _, member = await _connected_member(client, acting_user, session, admin_a)

        # The same person, in a second guild, connected there too.
        plugin_b = await _install(session, admin_b)
        await create_guild_membership(session, user=member.user, guild=admin_b.guild)
        await _connected(
            session, SimpleNamespace(guild=admin_b.guild, user=member.user), plugin_b
        )

        response = await client.post(
            "/api/v1/me/delete-account",
            headers=member.headers,
            json={
                "password": "testpassword123",
                "action": "soft_delete",
                "confirmation_text": "DELETE MY ACCOUNT",
            },
        )
        assert response.status_code == 200, response.text

        # Both guilds, in one sweep.
        assert await _rows(session, admin_a.guild.id) == []
        assert await _rows(session, admin_b.guild.id) == []
        assert [i.reason for i in recorded_revocations] == [
            "account_closed",
            "account_closed",
        ]
