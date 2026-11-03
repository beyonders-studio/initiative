"""Connections Initiative runs, against a fake vendor and a fake plug-in.

The whole trip is exercised through the routes a browser and a plug-in use: a
member starts the flow, the vendor answers the callback with a code, Initiative
exchanges it (with PKCE), asks the plug-in's ``after_connect`` hook, and stores the
result; a plug-in asks for a token by reference and gets a fresh one, refreshed
once however many ask at once and without holding the row anyone else writes;
and ending a connection ends the grant at the vendor.
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import cryptography.fernet
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from httpx import AsyncClient
from sqlalchemy import delete, text, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_PLUGIN_CONFIG, decrypt_field, encrypt_field
from app.core.messages import (
    AccessGrantMessages,
    GuildPluginMessages,
    PluginChannelMessages,
    PluginDataMessages,
)
from app.core.plugin_access_token import seal_install_token
from app.core.security import SESSION_COOKIE_NAME
from app.db import cohorts, post_commit
from app.db.request_context import SystemGuild
from app.db.session import set_rls_context
from app.models.platform.access_grant import (
    AccessGrant,
    AccessGrantPurpose,
    AccessLevel,
    SettingsLevel,
)
from app.models.platform.community_timer import CommunityTimer
from app.models.platform.guild import CommunityRole, CommunityStatus, GuildMembership
from app.models.platform.plugin_install import PluginInstall
from app.models.platform.plugin_service_registration import RegistrationKind
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_secret import GuildPluginSecret
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.plugin_event_outbox import PluginEventOutbox
from app.models.tenant.plugin_hook_delivery import PluginHookDelivery
from app.models.tenant.metadata import MetadataType
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.plugin_schedule_run import PluginScheduleRun
from app.services.marketplace import declarative as declarative_service
from app.services.marketplace import expressions, plugin_installs
from app.services.marketplace.registration_lookup import (
    invalidate_registrations,
    load_registrations,
)
from app.services.tenant import (
    plugin_connection_flows,
    plugin_connections,
    plugin_hooks,
    plugin_revocation,
    plugin_schedules,
)
from app.services.tenant import metadata as metadata_service
from app.services.tenant.plugin_connections import load_connection_secrets
from app.testing import (
    create_access_grant,
    create_guild_plugin,
    create_initiative,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_plugin_user_connection,
    create_project,
    create_property_definition,
    create_property_value,
    create_resource_grant,
    create_task,
    route_session_to_guild,
    sealed_vendor_values,
)
from app.testing.fake_vendor import FakeVendor, declarative_github
from app.testing.plugin_clients import kept_plugin_values

PUBLIC_ID = "tests.gh"
LISTING_UID = "TESTAPP0000009"
TOKEN_ROUTE = "/api/v1/plugin-platform/installation/connections/{ref}/token"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_KEY_PEM = _KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
PLATFORM_KEY_PEM = (
    ed25519.Ed25519PrivateKey.generate()
    .private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    .decode()
)
PUBLIC_KEY_PEM = (
    _KEY.public_key()
    .public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    .decode()
)

VENDOR_VALUES = {
    "client_id": "client-123",
    "client_secret": "client-secret-456",
    "app_slug": "initiative-test",
    "app_id": "4242",
    "private_key": PRIVATE_KEY_PEM,
    "webhook_secret": "webhook-secret-789",
}


def _field(key: str) -> dict:
    return {"key": key, "type": "string", "label": {"en": key}, "managed": True}


FLOW = {
    "type": "oauth2",
    "authorize_url": "https://github.test/login/oauth/authorize",
    "token_url": "https://github.test/login/oauth/access_token",
    "client_id": "{vendor.client_id}",
    "client_secret": "{vendor.client_secret}",
    "scopes": ["read:user"],
    "pkce": True,
    "after_connect": True,
}

ACCOUNT = {
    "id": "account",
    "scope": "interactive",
    "label": {"en": "Your account"},
    "fields": [_field("login")],
    "flow": {
        **FLOW,
        "revoke": "rfc7009",
        "revoke_url": "https://github.test/revoke",
    },
}

HOOKED = {
    "id": "hooked",
    "scope": "interactive",
    "label": {"en": "Hooked"},
    "fields": [_field("login")],
    "flow": {**FLOW, "revoke": "hook"},
}

WORKSPACE = {
    "id": "workspace",
    "scope": "static",
    "label": {"en": "Organization"},
    "fields": [_field("owner"), _field("installation_id")],
    "flow": {
        **FLOW,
        "install_url": "https://github.test/apps/{vendor.app_slug}/installations/new",
    },
    "token": {
        "type": "jwt_bearer",
        "exchange_url": (
            "https://github.test/app/installations/{installation_id}/access_tokens"
        ),
        "iss": "{vendor.app_id}",
        "key": "{vendor.private_key}",
        "alg": "RS256",
        "lifetime": 540,
    },
}


def _minting(exchange_body: dict | str) -> dict:
    """:data:`DEFINITION` with the workspace's token minted with
    ``exchange_body``."""
    workspace = {
        **WORKSPACE,
        "fields": [*WORKSPACE["fields"], _field("owner_type")],
        "token": {**WORKSPACE["token"], "exchange_body": exchange_body},
    }
    return {**DEFINITION, "connections": [ACCOUNT, HOOKED, workspace]}


#: A community connection whose tokens Initiative holds and refreshes.
ORG = {
    "id": "org",
    "scope": "static",
    "label": {"en": "Organization account"},
    "fields": [],
    "flow": FLOW,
}

DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": PUBLIC_ID, "protocol": 1},
    "features": [],
    "vendor": {
        "fields": [
            {"key": key, "type": "string", "label": {"en": key}}
            for key in VENDOR_VALUES
        ]
    },
    "connections": [ACCOUNT, HOOKED, WORKSPACE],
    "webhooks": {
        "verify": {
            "scheme": "hmac_sha256",
            "header": "X-Hub-Signature-256",
            "prefix": "sha256=",
            "encoding": "hex",
            "secret": "{vendor.webhook_secret}",
        },
        "dedup": "X-GitHub-Delivery",
        "route": {
            "path": "installation.id",
            "connection": "workspace",
            "field": "installation_id",
        },
    },
    "schedules": [{"id": "check-installation", "every": "15m"}],
}


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """Initiative signs its hook calls with the plug-in platform's own key, an
    Ed25519 key of its own (the RSA key above is the vendor's GitHub App key)."""
    monkeypatch.setattr(
        settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", PLATFORM_KEY_PEM
    )
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_KEY_ID", "plugin-platform-1")


@pytest.fixture
def vendor(monkeypatch) -> FakeVendor:
    fake = FakeVendor()
    fake.install(monkeypatch)
    plugin_connection_flows.clear_token_cache()
    monkeypatch.setattr(plugin_revocation, "retry_delays", (0.0, 0.0))
    return fake


@pytest.fixture
async def registration(session: AsyncSession):
    return await create_plugin_service_registration(
        session,
        public_id=PUBLIC_ID,
        listing_uid=LISTING_UID,
        base_url="https://app.example.test",
        vendor_values=sealed_vendor_values(VENDOR_VALUES),
    )


async def _install(
    session: AsyncSession, actor, definition: dict = DEFINITION, **overrides
) -> GuildPlugin:
    return await create_guild_plugin(
        session,
        actor.guild,
        actor.user,
        definition=definition,
        listing_uid=LISTING_UID,
        **overrides,
    )


async def _member_row(
    session: AsyncSession, guild_id: int, plugin_id: int, connection_id: str = "account"
) -> GuildPluginUserConnection | None:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return (
        await session.exec(
            select(GuildPluginUserConnection).where(
                GuildPluginUserConnection.plugin_id == plugin_id,
                GuildPluginUserConnection.connection_id == connection_id,
            )
        )
    ).first()


async def _indexed(
    session: AsyncSession, guild_id: int, plugin_id: int
) -> PluginInstall | None:
    """The install's row in the install index, once the index sweep has
    visited the community."""
    await route_session_to_guild(session, guild_id)
    await plugin_installs.reindex_community(session, guild_id)
    session.expunge_all()
    return await session.get(PluginInstall, (guild_id, plugin_id))


async def _reload(session: AsyncSession, guild_id: int, plugin_id: int) -> GuildPlugin:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
    ).one()


async def _start(
    client: AsyncClient, actor, plugin: GuildPlugin, connection: str
) -> dict:
    response = await client.post(
        actor.g(f"/plugins/{plugin.id}/connections/{connection}/connect"),
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    url = urlparse(response.json()["connect_url"])
    return {key: values[0] for key, values in parse_qs(url.query).items()} | {
        "_url": url
    }


def _cookie(actor) -> dict[str, str]:
    """The session cookie the actor's browser carries."""
    token = actor.headers["Authorization"].removeprefix("Bearer ")
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"}


async def _callback(client: AsyncClient, actor, **params) -> dict:
    """The vendor's return, in a browser where ``actor`` is signed in (or no
    one is, when ``actor`` is ``None``)."""
    response = await client.get(
        "/api/v1/plugin-connections/callback",
        params=params,
        headers=_cookie(actor) if actor is not None else {},
    )
    assert response.status_code == 303, response.text
    return _landing(response.headers["location"])


def _landing(location: str) -> dict:
    parsed = urlparse(location)
    return {key: values[0] for key, values in parse_qs(parsed.query).items()} | {
        "_path": parsed.path
    }


async def _connect_installation(
    client: AsyncClient,
    actor,
    plugin: GuildPlugin,
    vendor: FakeVendor,
    installation: int = 42,
) -> dict:
    """The install page, then one authorization, returning ``installation``."""
    start = await _start(client, actor, plugin, "workspace")
    setup = await client.get(
        "/api/v1/plugin-connections/setup",
        headers=_cookie(actor),
        params={
            "state": start["state"],
            "installation_id": str(installation),
            "setup_action": "install",
        },
    )
    assert setup.status_code == 303, setup.text
    query = {
        key: values[0]
        for key, values in parse_qs(urlparse(setup.headers["location"]).query).items()
    }
    code = vendor.authorize(query["code_challenge"])
    return await _callback(client, actor, state=query["state"], code=code)


def _install_headers(guild, plugin) -> dict[str, str]:
    token, _ = seal_install_token(
        guild_id=guild.id,
        install_id=plugin.id,
        client_id=PUBLIC_ID,
        scopes=frozenset(),
        initiative_id=None,
        user_id=None,
        purpose=None,
    )
    return {"Authorization": f"Bearer {token}"}


async def _connected_row(
    session: AsyncSession,
    actor,
    plugin: GuildPlugin,
    *,
    expires_in: int,
    connection_id: str = "account",
    ref: str = "cr_account_one",
) -> GuildPluginUserConnection:
    """A member connection as a completed flow leaves it."""
    return await create_plugin_user_connection(
        session,
        plugin,
        actor.user,
        connection_id=connection_id,
        connection_ref=ref,
        config={"login": "alice", "expires_at": int(time.time()) + expires_in},
        secrets={
            "access_token": encrypt_field("gho_stored", SALT_PLUGIN_CONFIG),
            "refresh_token": encrypt_field("ghr_stored", SALT_PLUGIN_CONFIG),
        },
        account_label="@alice",
    )


def _during_refresh(monkeypatch, vendor: FakeVendor, write) -> None:
    """Run ``write`` while the vendor is answering a refresh."""

    async def handle(request: httpx.Request) -> httpx.Response:
        if b"grant_type=refresh_token" in request.content:
            await write()
        return vendor.handle(request)

    monkeypatch.setattr(
        plugin_connection_flows, "http_transport", httpx.MockTransport(handle)
    )


async def _write_during_refresh(guild_id: int, *statements) -> None:
    """Another request's writes, refused rather than left waiting on a lock
    the refresh holds."""
    async with cohorts.system_session(guild_id) as own:
        await set_rls_context(own, SystemGuild(guild_id))
        await own.exec(text("SET LOCAL lock_timeout = '2s'"))
        for statement in statements:
            await own.exec(statement)
        await own.commit()


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------


class TestMemberFlow:
    async def test_authorize_callback_and_exchange(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """The whole trip: the member is sent to the vendor, comes back with a
        code, and Initiative exchanges it, asks the plug-in who connected, and
        keeps the tokens."""
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)

        start = await _start(client, a, plugin, "account")
        assert start["client_id"] == "client-123"
        assert start["scope"] == "read:user"
        assert start["redirect_uri"] == plugin_connection_flows.callback_url()

        code = vendor.authorize(start["code_challenge"])
        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["_path"] == "/plugins/connected"
        assert landing["outcome"] == "connected"
        assert landing["plugin"] == PUBLIC_ID
        assert landing["connection"] == "account"

        exchange = vendor.token_requests[0]
        assert exchange["grant_type"] == "authorization_code"
        assert exchange["redirect_uri"] == plugin_connection_flows.callback_url()
        assert exchange["code_verifier"]

        name, body, authorization = vendor.hooks[0]
        assert name == "after_connect"
        assert body["connection"] == "account"
        assert body["actor"] == "member"
        assert body["access_token"].startswith("gho_access_")
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            options={"verify_signature": False},
        )
        assert claims["scope"] == "lifecycle"
        assert claims["hook"] == "after_connect"
        assert claims["plugin_install_id"] == plugin.id

        row = await _member_row(session, a.guild.id, plugin.id)
        assert row is not None
        assert row.status == "connected"
        assert row.account_label == "@alice"
        assert row.config["login"] == "alice"
        assert isinstance(row.config["expires_at"], int)
        assert row.connection_ref
        # Sealed, never stored as it came, beside the row; the row says only
        # which keys hold one.
        sealed = await load_connection_secrets(session, row)
        assert sealed["access_token"] != body["access_token"]
        assert (
            decrypt_field(sealed["access_token"], SALT_PLUGIN_CONFIG)
            == body["access_token"]
        )
        assert "access_token" in row.secret_fields

    async def test_reconnecting_keeps_the_handle(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)

        refs = []
        for _ in range(2):
            start = await _start(client, a, plugin, "account")
            code = vendor.authorize(start["code_challenge"])
            await _callback(client, a, state=start["state"], code=code)
            row = await _member_row(session, a.guild.id, plugin.id)
            assert row is not None
            refs.append(row.connection_ref)
        assert refs[0] == refs[1]

    async def test_pkce_is_verified(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """The code is bound to the challenge the authorization request sent; a
        verifier that does not answer it is refused by the vendor, and nothing
        is stored."""
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")
        assert start["code_challenge_method"] == "S256"

        code = vendor.authorize("a-challenge-this-flow-never-sent")
        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["outcome"] == "refused"
        assert await _member_row(session, a.guild.id, plugin.id) is None

    async def test_a_tampered_state_is_refused(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")
        code = vendor.authorize(start["code_challenge"])
        state = start["state"]
        tampered = state[:-6] + ("A" if state[-6] != "A" else "B") + state[-5:]

        landing = await _callback(client, a, state=tampered, code=code)

        assert landing["outcome"] == "expired"
        assert vendor.token_requests == []
        assert await _member_row(session, a.guild.id, plugin.id) is None

    async def test_an_expired_state_is_refused(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        registration,
        monkeypatch,
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")
        code = vendor.authorize(start["code_challenge"])

        later = time.time() + 11 * 60
        monkeypatch.setattr(cryptography.fernet.time, "time", lambda: later)
        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["outcome"] == "expired"
        assert vendor.token_requests == []

    async def test_the_vendor_saying_no_reads_as_refused(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")

        landing = await _callback(
            client, a, state=start["state"], error="access_denied"
        )

        assert landing["outcome"] == "refused"

    async def test_the_plugin_may_refuse_the_account(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        vendor.after_connect_answer = {"refuse": True}
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")
        code = vendor.authorize(start["code_challenge"])

        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["outcome"] == "refused"
        assert await _member_row(session, a.guild.id, plugin.id) is None

    async def test_a_hook_that_fails_is_not_recorded(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        vendor.hook_status = 500
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")
        code = vendor.authorize(start["code_challenge"])

        landing = await _callback(client, a, state=start["state"], code=code)

        assert landing["outcome"] == "not_recorded"
        assert await _member_row(session, a.guild.id, plugin.id) is None

    async def test_another_signed_in_person_cannot_finish_it(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """A flow is finished only by the person who started it; anyone else
        is told to finish it where that person is signed in, and the code is
        never exchanged."""
        a = await acting_user(guild_role=CommunityRole.member)
        other = await acting_user(guild_role=CommunityRole.member, guild=a.guild)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")
        code = vendor.authorize(start["code_challenge"])

        landing = await _callback(client, other, state=start["state"], code=code)

        assert landing["outcome"] == "sign_in_required"
        assert vendor.token_requests == []
        assert vendor.hooks == []
        assert await _member_row(session, a.guild.id, plugin.id) is None

    async def test_no_session_cannot_finish_it(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")
        code = vendor.authorize(start["code_challenge"])

        landing = await _callback(client, None, state=start["state"], code=code)
        # A request that presents a bearer header is read by that header, so
        # the session cookie beside it does not sign anyone in here.
        beside_bearer = await client.get(
            "/api/v1/plugin-connections/callback",
            params={"state": start["state"], "code": code},
            headers=_cookie(a) | a.headers,
        )

        assert landing["outcome"] == "sign_in_required"
        assert beside_bearer.status_code == 303
        assert (
            _landing(beside_bearer.headers["location"])["outcome"] == "sign_in_required"
        )
        assert vendor.token_requests == []
        assert await _member_row(session, a.guild.id, plugin.id) is None


class TestInstallationStyleFlow:
    async def test_install_page_setup_then_one_authorization(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """The seat installs on the vendor's page, the vendor returns the
        installation's id to the setup address, and one authorization trip lets
        the plug-in check who installed it. The managed values land on the
        community's connection and the person's token is not kept."""
        vendor.after_connect_answer = {
            "values": {"owner": "acme", "installation_id": "42"},
            "account_label": "acme",
        }
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)

        start = await _start(client, a, plugin, "workspace")
        assert start["_url"].path == "/apps/initiative-test/installations/new"

        setup = await client.get(
            "/api/v1/plugin-connections/setup",
            headers=_cookie(a),
            params={
                "state": start["state"],
                "installation_id": "42",
                "setup_action": "install",
            },
        )
        assert setup.status_code == 303, setup.text
        authorize = urlparse(setup.headers["location"])
        assert authorize.netloc == "github.test"
        assert authorize.path == "/login/oauth/authorize"
        query = {k: v[0] for k, v in parse_qs(authorize.query).items()}
        # A fresh state for the second leg.
        assert query["state"] != start["state"]

        code = vendor.authorize(query["code_challenge"])
        landing = await _callback(client, a, state=query["state"], code=code)
        assert landing["outcome"] == "connected"

        name, body, _ = vendor.hooks[0]
        assert name == "after_connect"
        assert body["actor"] == "installation"
        assert body["params"] == {"installation_id": "42"}

        stored = await _reload(session, a.guild.id, plugin.id)
        assert stored.config["workspace"] == {"owner": "acme", "installation_id": "42"}
        assert "workspace" not in (stored.secret_fields or {})
        assert stored.connection_refs.get("workspace")
        assert await _member_row(session, a.guild.id, plugin.id, "workspace") is None
        # The vendor's webhooks for installation 42 now route here.
        assert (await _indexed(session, a.guild.id, plugin.id)).hook_route == "42"

    async def test_losing_the_seat_mid_flow_refuses_it(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """A community connection is finished only while its starter still
        holds the seat."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "workspace")

        membership = (
            await session.exec(
                select(GuildMembership).where(
                    GuildMembership.guild_id == a.guild.id,
                    GuildMembership.user_id == a.user.id,
                )
            )
        ).one()
        membership.role = CommunityRole.member
        session.add(membership)
        await session.commit()

        setup = await client.get(
            "/api/v1/plugin-connections/setup",
            headers=_cookie(a),
            params={"state": start["state"], "installation_id": "42"},
        )

        assert _landing(setup.headers["location"])["outcome"] == "refused"
        assert vendor.token_requests == []
        stored = await _reload(session, a.guild.id, plugin.id)
        assert "workspace" not in (stored.config or {})

    async def _lent_seat(self, session, acting_user, a, *, content: str):
        """A support account the community's seat is lent to, beside a
        ``content`` grant."""
        support = await acting_user("support")
        await create_access_grant(
            session, user=support.user, guild=a.guild, access_level=content
        )
        await create_access_grant(
            session,
            user=support.user,
            guild=a.guild,
            purpose=AccessGrantPurpose.settings.value,
            access_level=SettingsLevel.superadmin.value,
        )
        return replace(support, guild=a.guild)

    async def test_a_lent_seat_beside_a_read_grant_cannot_start_it(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        support = await self._lent_seat(session, acting_user, a, content="read")

        response = await client.post(
            support.g(f"/plugins/{plugin.id}/connections/workspace/connect"),
            headers=support.headers,
        )

        assert response.status_code == 403, response.text
        assert response.json()["detail"] == AccessGrantMessages.WRITE_GRANT_REQUIRED

    async def test_a_lent_seat_whose_write_grant_lapses_mid_flow_is_refused(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """The flow is finished only while its starter may still change what
        the seat holds."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        support = await self._lent_seat(session, acting_user, a, content="read_write")
        start = await _start(client, support, plugin, "workspace")

        await session.exec(
            update(AccessGrant)
            .where(
                AccessGrant.user_id == support.user.id,
                AccessGrant.purpose == AccessGrantPurpose.content.value,
            )
            .values(access_level=AccessLevel.read.value)
        )
        await session.commit()

        setup = await client.get(
            "/api/v1/plugin-connections/setup",
            headers=_cookie(support),
            params={"state": start["state"], "installation_id": "42"},
        )

        assert _landing(setup.headers["location"])["outcome"] == "refused"
        assert vendor.token_requests == []

    async def test_an_install_awaiting_approval_says_so(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "workspace")

        setup = await client.get(
            "/api/v1/plugin-connections/setup",
            headers=_cookie(a),
            params={"state": start["state"], "setup_action": "request"},
        )

        assert setup.status_code == 303
        assert _landing(setup.headers["location"])["outcome"] == "awaiting_approval"
        assert vendor.token_requests == []

    async def test_an_authorize_state_is_not_a_setup_state(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        start = await _start(client, a, plugin, "account")

        setup = await client.get(
            "/api/v1/plugin-connections/setup",
            headers=_cookie(a),
            params={"state": start["state"], "installation_id": "42"},
        )

        assert _landing(setup.headers["location"])["outcome"] == "expired"


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


class TestTokens:
    async def test_a_members_token_by_reference(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        row = await _connected_row(session, a, plugin, expires_in=3600)

        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(a.guild, plugin),
        )

        assert response.status_code == 200, response.text
        assert response.json()["access_token"] == "gho_stored"
        assert response.json()["expires_at"] == row.config["expires_at"]
        assert vendor.refreshes == 0

    async def test_concurrent_reads_refresh_once(
        self, acting_user, session, vendor, registration
    ):
        """A token about to expire is refreshed by one reader at a time: the
        second waits and finds the first's fresh token.

        Two sessions of their own, as two requests in two workers would have;
        the test client shares one session per role, so it cannot overlap
        two requests."""
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        row = await _connected_row(session, a, plugin, expires_in=30)

        async def read_token():
            async with cohorts.system_session(a.guild.id) as own:
                await set_rls_context(own, SystemGuild(a.guild.id))
                install = (
                    await own.exec(
                        select(GuildPlugin).where(GuildPlugin.id == plugin.id)
                    )
                ).one()
                return await plugin_connection_flows.member_token(
                    own,
                    plugin=install,
                    public_id=PUBLIC_ID,
                    connection_ref=row.connection_ref,
                    guild_id=a.guild.id,
                )

        first, second = await asyncio.gather(read_token(), read_token())

        assert first is not None and second is not None
        assert vendor.refreshes == 1
        assert first.access_token == second.access_token
        assert first.access_token.startswith("gho_access_")
        refreshed = await _member_row(session, a.guild.id, plugin.id)
        assert refreshed is not None
        sealed = await load_connection_secrets(session, refreshed)
        assert (
            decrypt_field(sealed["refresh_token"], SALT_PLUGIN_CONFIG) != "ghr_stored"
        )

    async def test_a_member_blocked_during_a_refresh_gets_no_token(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        registration,
        monkeypatch,
    ):
        """The vendor is asked without holding the member's row, and what it
        answered is dropped when the row changed meanwhile."""
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        row = await _connected_row(session, a, plugin, expires_in=30)

        async def block():
            await _write_during_refresh(
                a.guild.id,
                update(GuildPluginUserConnection)
                .where(GuildPluginUserConnection.id == row.id)
                .values(blocked_at=datetime.now(timezone.utc)),
            )

        _during_refresh(monkeypatch, vendor, block)
        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(a.guild, plugin),
        )

        assert response.status_code == 403
        assert response.json()["detail"] == PluginChannelMessages.CONNECTION_BLOCKED
        assert vendor.refreshes == 1
        blocked = await _member_row(session, a.guild.id, plugin.id)
        assert blocked is not None
        sealed = await load_connection_secrets(session, blocked)
        assert (
            decrypt_field(sealed["refresh_token"], SALT_PLUGIN_CONFIG) == "ghr_stored"
        )

    async def test_a_community_connection_cleared_during_a_refresh_stays_cleared(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        registration,
        monkeypatch,
    ):
        """The install's row is locked only to store the refreshed token, so a
        disconnect lands while the vendor is being asked, and wins."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await create_guild_plugin(
            session,
            a.guild,
            a.user,
            definition={**DEFINITION, "connections": [*DEFINITION["connections"], ORG]},
            listing_uid=LISTING_UID,
            config={"org": {"expires_at": int(time.time()) + 30}},
            connection_refs={"org": "gcr_org"},
            secrets={
                "org": {
                    "access_token": encrypt_field("gho_stored", SALT_PLUGIN_CONFIG),
                    "refresh_token": encrypt_field("ghr_stored", SALT_PLUGIN_CONFIG),
                }
            },
        )

        async def disconnect():
            await _write_during_refresh(
                a.guild.id,
                update(GuildPlugin)
                .where(GuildPlugin.id == plugin.id)
                .values(config={}),
                delete(GuildPluginSecret).where(
                    GuildPluginSecret.install_id == plugin.id
                ),
            )

        _during_refresh(monkeypatch, vendor, disconnect)
        response = await client.post(
            TOKEN_ROUTE.format(ref="gcr_org"), headers=_install_headers(a.guild, plugin)
        )

        assert response.status_code == 409
        assert response.json()["detail"] == PluginChannelMessages.CONNECTION_NO_TOKEN
        assert vendor.refreshes == 1
        cleared = await _reload(session, a.guild.id, plugin.id)
        assert cleared.config == {}

    async def test_a_refused_refresh_expires_the_connection(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        vendor.refuse_refresh = True
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        row = await _connected_row(session, a, plugin, expires_in=30)

        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(a.guild, plugin),
        )

        assert response.status_code == 409
        assert response.json()["detail"] == PluginChannelMessages.CONNECTION_EXPIRED
        expired = await _member_row(session, a.guild.id, plugin.id)
        assert expired is not None and expired.status == "expired"

        # The member sees it, and is offered to connect again.
        detail = (
            await client.get(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
        ).json()
        account = next(c for c in detail["connections"] if c["id"] == "account")
        assert account["status"] == "expired"
        assert account["runs_flow"] is True

    async def test_a_minted_token_is_cached(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """A ``jwt_bearer`` connection's token is minted with the vendor key and
        reused until shortly before it expires."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(
            session,
            a,
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
            connection_refs={"workspace": "gcr_workspace"},
        )
        headers = _install_headers(a.guild, plugin)

        first = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"), headers=headers
        )
        second = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"), headers=headers
        )

        assert first.status_code == 200, first.text
        assert first.json()["access_token"].startswith("ghs_installation_")
        assert second.json() == first.json()
        [(authorization, body)] = vendor.exchanges
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            PUBLIC_KEY_PEM,
            algorithms=["RS256"],
        )
        assert claims["iss"] == "4242"
        assert claims["exp"] - claims["iat"] == 540
        assert body is None

    async def test_a_cleared_connections_minted_tokens_are_forgotten(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """What was minted for a connection goes with its values."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(
            session,
            a,
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
            connection_refs={"workspace": "gcr_workspace"},
        )
        minted = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"),
            headers=_install_headers(a.guild, plugin),
        )
        assert minted.status_code == 200, minted.text
        assert len(plugin_connection_flows._minted) == 1

        cleared = await client.delete(
            a.g(f"/plugins/{plugin.id}/connections/workspace"), headers=a.headers
        )

        assert cleared.status_code == 204, cleared.text
        assert plugin_connection_flows._minted == {}

    async def test_a_clear_while_the_vendor_is_asked_keeps_nothing(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        registration,
        monkeypatch,
    ):
        """A mint waiting for the vendor when the connection is cleared keeps
        the token it is then given out of the cache."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(
            session,
            a,
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
            connection_refs={"workspace": "gcr_workspace"},
        )
        parse_expiry = plugin_connection_flows._parse_expiry

        def clearing_first(body, *, now):
            plugin_connection_flows.forget_minted(a.guild.id, plugin.id, "workspace")
            return parse_expiry(body, now=now)

        monkeypatch.setattr(plugin_connection_flows, "_parse_expiry", clearing_first)

        minted = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"),
            headers=_install_headers(a.guild, plugin),
        )

        assert minted.status_code == 200, minted.text
        assert plugin_connection_flows._minted == {}

    async def test_a_minted_token_asks_for_what_its_body_names(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """An ``exchange_body`` object is posted with the JWT, each name in its
        strings filled from the vendor values and the connection's fields; a
        name with no value sends nothing."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(
            session,
            a,
            _minting(
                {
                    "permissions": {"issues": "write"},
                    "repositories": ["{owner}"],
                    "app": "{vendor.app_slug}",
                    "limit": 5,
                }
            ),
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
            connection_refs={"workspace": "gcr_workspace"},
        )
        headers = _install_headers(a.guild, plugin)

        response = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"), headers=headers
        )

        assert response.status_code == 200, response.text
        assert [body for _, body in vendor.exchanges] == [
            {
                "permissions": {"issues": "write"},
                "repositories": ["acme"],
                "app": "initiative-test",
                "limit": 5,
            }
        ]

        plugin = await _reload(session, a.guild.id, plugin.id)
        plugin.config = {"workspace": {"installation_id": "42"}}
        session.add(plugin)
        await session.commit()
        unnamed = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"), headers=headers
        )

        assert unnamed.status_code == 409
        assert (
            unnamed.json()["detail"]
            == GuildPluginMessages.CONNECTION_VENDOR_NOT_CONFIGURED
        )
        assert len(vendor.exchanges) == 1

    async def test_a_minted_token_asks_for_what_its_expression_answers(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """An ``exchange_body`` expression answers the body from the
        connection's fields, and a token is minted again when they change. A
        token past reuse is dropped when another is minted."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(
            session,
            a,
            _minting(
                '{"permissions": $merge([{"issues": "write"},'
                ' connection.owner_type = "Organization" ? {"members": "read"} : {}])}'
            ),
            config={
                "workspace": {
                    "owner": "acme",
                    "installation_id": "42",
                    "owner_type": "Organization",
                }
            },
            connection_refs={"workspace": "gcr_workspace"},
        )
        headers = _install_headers(a.guild, plugin)

        first = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"), headers=headers
        )
        [held] = plugin_connection_flows._minted.values()
        held.reuse_until = 0.0
        plugin = await _reload(session, a.guild.id, plugin.id)
        plugin.config = {
            "workspace": {"owner": "ada", "installation_id": "42", "owner_type": "User"}
        }
        session.add(plugin)
        await session.commit()
        second = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"), headers=headers
        )

        assert first.status_code == second.status_code == 200, second.text
        assert second.json() != first.json()
        assert [body for _, body in vendor.exchanges] == [
            {"permissions": {"issues": "write", "members": "read"}},
            {"permissions": {"issues": "write"}},
        ]
        assert [one.token for one in plugin_connection_flows._minted.values()] == [
            second.json()["access_token"]
        ]

    async def test_an_expression_answering_no_object_mints_nothing(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(
            session,
            a,
            _minting("connection.owner"),
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
            connection_refs={"workspace": "gcr_workspace"},
        )

        response = await client.post(
            TOKEN_ROUTE.format(ref="gcr_workspace"),
            headers=_install_headers(a.guild, plugin),
        )

        assert response.status_code == 502
        assert response.json()["detail"] == PluginChannelMessages.TOKEN_UNAVAILABLE
        assert vendor.exchanges == []

    async def test_a_ref_of_another_install_is_not_found(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        row = await _connected_row(session, a, plugin, expires_in=3600)
        b = await acting_user(guild_role=CommunityRole.member)
        other = await _install(session, b)

        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(b.guild, other),
        )

        assert response.status_code == 404
        assert response.json()["detail"] == PluginChannelMessages.CONNECTION_NOT_FOUND

    async def test_a_blocked_member_gets_no_token(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        row = await _connected_row(session, a, plugin, expires_in=3600)
        await route_session_to_guild(session, a.guild.id)
        row.status = "blocked"
        row.blocked_at = row.updated_at
        session.add(row)
        await session.commit()

        response = await client.post(
            TOKEN_ROUTE.format(ref=row.connection_ref),
            headers=_install_headers(a.guild, plugin),
        )

        assert response.status_code == 403
        assert response.json()["detail"] == PluginChannelMessages.CONNECTION_BLOCKED

    async def test_the_config_dump_holds_no_flow_secrets(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(
            session,
            a,
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
            connection_refs={"workspace": "gcr_workspace"},
        )
        await _connected_row(session, a, plugin, expires_in=3600)

        response = await client.get(
            "/api/v1/plugin-platform/installation/config",
            headers=_install_headers(a.guild, plugin),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["member_connections"][0]["values"] == {"login": "alice"}
        assert body["connections"]["workspace"] == {
            "owner": "acme",
            "installation_id": "42",
        }
        assert body["connection_refs"] == {"workspace": "gcr_workspace"}
        assert "gho_stored" not in response.text
        assert "ghr_stored" not in response.text
        assert "expires_at" not in response.text

    async def test_the_write_back_route_is_gone(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)

        response = await client.put(
            "/api/v1/plugin-platform/installation/connections/cr_x",
            headers=_install_headers(a.guild, plugin),
            json={"values": {"login": "mallory"}},
        )

        assert response.status_code in (404, 405)


# ---------------------------------------------------------------------------
# Ending a grant
# ---------------------------------------------------------------------------


class TestRevocation:
    async def test_uninstall_calls_the_revoke_url(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """Once, after the commit that ended the connection; a rolled-back
        disconnect sends nothing."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        await _connected_row(session, a, plugin, expires_in=3600)

        async with cohorts.system_session(a.guild.id) as own:
            await set_rls_context(own, SystemGuild(a.guild.id))
            await plugin_connections.disconnect(
                own, plugin=plugin, connection_id="account", user_id=a.user.id
            )
            await own.rollback()
        await post_commit.settle_all()
        assert vendor.revocations == []

        response = await client.delete(a.g(f"/plugins/{plugin.id}"), headers=a.headers)

        assert response.status_code == 204, response.text
        assert vendor.revocations == [
            {
                "token": "ghr_stored",
                "token_type_hint": "refresh_token",
                "client_id": "client-123",
                "client_secret": "client-secret-456",
            }
        ]

    async def test_a_failing_revocation_is_tried_three_times(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        vendor.revoke_status = 503
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        await _connected_row(session, a, plugin, expires_in=3600)

        response = await client.delete(
            a.g(f"/plugins/{plugin.id}/connections/account"), headers=a.headers
        )
        await post_commit.settle_all()

        assert response.status_code == 204
        assert len(vendor.revocations) == plugin_revocation.REVOKE_ATTEMPTS

    @staticmethod
    def _grant_intent(**overrides) -> plugin_revocation.RevocationIntent:
        """A member connection whose grant GitHub ends by its access token."""
        return plugin_revocation.RevocationIntent(
            **{
                "guild_id": 1,
                "plugin_id": 1,
                "listing_uid": LISTING_UID,
                "connection_id": "account",
                "public_id": PUBLIC_ID,
                "flow": {
                    **FLOW,
                    "revoke": "github_grant",
                    "revoke_url": (
                        "https://github.test/applications/{vendor.client_id}/grant"
                    ),
                },
                "sealed_tokens": {
                    "access_token": encrypt_field("gho_stored", SALT_PLUGIN_CONFIG),
                    "refresh_token": encrypt_field("ghr_stored", SALT_PLUGIN_CONFIG),
                },
                "expires_at": int(time.time()) + 3600,
                **overrides,
            }
        )

    @staticmethod
    def _deletion(access_token: str) -> tuple:
        basic = base64.b64encode(b"client-123:client-secret-456").decode()
        return (
            "DELETE",
            "/applications/client-123/grant",
            f"Basic {basic}",
            {"access_token": access_token},
        )

    @pytest.mark.parametrize(
        ("status", "tries"), [(204, 1), (503, plugin_revocation.REVOKE_ATTEMPTS)]
    )
    async def test_a_github_grant_is_deleted_with_the_client_credentials(
        self, vendor, registration, status, tries
    ):
        vendor.grant_status = status

        await plugin_revocation._deliver(self._grant_intent())

        assert vendor.grant_deletions == [self._deletion("gho_stored")] * tries
        assert vendor.refreshes == 0

    async def test_a_declarative_plugins_grant_is_deleted_under_its_listings_name(
        self, session, vendor, registration
    ):
        """It names no service: the registration its listing applied says
        which vendor client ends the grant."""
        registration.kind = RegistrationKind.DECLARATIVE
        session.add(registration)
        await session.commit()
        invalidate_registrations()
        granted = self._grant_intent()
        intent = plugin_revocation._intent_for(
            guild_id=1,
            plugin_id=1,
            listing_uid=LISTING_UID,
            definition={
                "plugin_kind": "service",
                "hosts": ["api.github.test"],
                "connections": [
                    {"id": "account", "scope": "interactive", "flow": granted.flow}
                ],
            },
            connection_id="account",
            config={"expires_at": granted.expires_at},
            secrets=granted.sealed_tokens,
            reason="disconnected",
        )
        assert intent.public_id is None

        await plugin_revocation._deliver(intent)

        assert vendor.grant_deletions == [self._deletion("gho_stored")]

    async def test_a_lapsed_github_token_is_refreshed_before_the_deletion(
        self, vendor, registration
    ):
        await plugin_revocation._deliver(
            self._grant_intent(expires_at=int(time.time()) - 60)
        )

        assert vendor.refreshes == 1
        assert vendor.token_requests[-1]["refresh_token"] == "ghr_stored"
        assert vendor.grant_deletions == [self._deletion("gho_access_1")]

    async def test_a_token_github_no_longer_accepts_is_refreshed_once(
        self, vendor, registration
    ):
        vendor.lapsed_tokens = {"gho_stored"}

        await plugin_revocation._deliver(self._grant_intent())

        assert vendor.refreshes == 1
        assert vendor.grant_deletions == [
            self._deletion("gho_stored"),
            self._deletion("gho_access_1"),
        ]

    async def test_a_lapsed_github_token_with_no_refresh_token_is_dropped(
        self, vendor, registration
    ):
        await plugin_revocation._deliver(
            self._grant_intent(
                expires_at=int(time.time()) - 60,
                sealed_tokens={
                    "access_token": encrypt_field("gho_stored", SALT_PLUGIN_CONFIG)
                },
            )
        )

        assert vendor.refreshes == 0
        assert vendor.grant_deletions == []

    async def test_a_github_grant_with_no_access_token_sends_nothing(
        self, vendor, registration
    ):
        await plugin_revocation._deliver(self._grant_intent(sealed_tokens={}))

        assert vendor.grant_deletions == []

    async def test_a_github_grant_with_no_client_secret_sends_nothing(
        self, session: AsyncSession, vendor
    ):
        await create_plugin_service_registration(
            session,
            public_id=PUBLIC_ID,
            listing_uid=LISTING_UID,
            base_url="https://app.example.test",
            vendor_values=sealed_vendor_values(
                {k: v for k, v in VENDOR_VALUES.items() if k != "client_secret"}
            ),
        )

        await plugin_revocation._deliver(self._grant_intent())

        assert vendor.grant_deletions == []

    async def test_revocations_are_sent_together(self, monkeypatch):
        """Each delivery waits for the other, so both finish only when they run
        at once."""
        both = asyncio.Barrier(2)
        delivered = []

        async def deliver(intent):
            await asyncio.wait_for(both.wait(), timeout=1)
            delivered.append(intent.connection_id)

        monkeypatch.setattr(plugin_revocation, "_deliver", deliver)
        intents = [
            plugin_revocation.RevocationIntent(
                guild_id=1, plugin_id=1, listing_uid="l", connection_id=connection_id
            )
            for connection_id in ("a", "b")
        ]

        await plugin_revocation.dispatch_revocations(intents)

        assert sorted(delivered) == ["a", "b"]

    async def test_a_hook_revocation_hands_the_plugin_the_tokens(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        a = await acting_user(guild_role=CommunityRole.member)
        plugin = await _install(session, a)
        await _connected_row(
            session, a, plugin, expires_in=3600, connection_id="hooked", ref="cr_hooked"
        )

        response = await client.delete(
            a.g(f"/plugins/{plugin.id}/connections/hooked"), headers=a.headers
        )
        await post_commit.settle_all()
        assert response.status_code == 204
        from app.services import sweep_timers

        # Written to the plug-in's hook queue with the delete, and sent by it.
        assert [hook for hook in vendor.hooks if hook[0] == "revoke"] == []
        await sweep_timers.process_due_timers(outward=True)

        name, body, authorization = next(h for h in vendor.hooks if h[0] == "revoke")
        assert body == {
            "connection": "hooked",
            "access_token": "gho_stored",
            "refresh_token": "ghr_stored",
        }
        claims = jwt.decode(
            authorization.removeprefix("Bearer "),
            options={"verify_signature": False},
        )
        assert claims["hook"] == "revoke"

    async def test_an_uninstall_asks_the_plugin_to_revoke_before_it_erases(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """An uninstall's revocations to the plug-in ride its hook queue, in the
        uninstall's transaction and ahead of ``uninstalled`` and ``erase``. The
        tokens wait sealed and are opened only to be sent, and a finished
        revocation keeps none."""
        from app.db.request_context import Unattributed
        from app.models.platform.plugin_community_hook import PluginCommunityHook
        from app.services import sweep_timers
        from app.services.marketplace import plugin_refs

        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        await _connected_row(
            session, a, plugin, expires_in=3600, connection_id="hooked", ref="cr_hooked"
        )
        await plugin_refs.ensure_plugin_guild_ref(
            guild_id=a.guild.id, public_id=PUBLIC_ID
        )

        response = await client.delete(
            a.g(f"/plugins/{plugin.id}"), headers=a.headers, params={"erase": "true"}
        )
        assert response.status_code == 204, response.text
        await post_commit.settle_all()
        assert [hook for hook in vendor.hooks if hook[0] == "revoke"] == []

        async def rows():
            await set_rls_context(session, Unattributed())
            found = (
                await session.exec(
                    select(PluginCommunityHook)
                    .where(PluginCommunityHook.guild_id == a.guild.id)
                    .order_by(PluginCommunityHook.id)
                    .execution_options(populate_existing=True)
                )
            ).all()
            await session.commit()
            return found

        queued = await rows()
        assert [row.hook for row in queued] == ["revoke", "uninstalled", "erase"]
        assert "gho_stored" not in str(queued[0].body)
        assert set(queued[0].body["sealed_tokens"]) == {"access_token", "refresh_token"}

        await sweep_timers.process_due_timers(outward=True)

        sent = [name for name, _body, _auth in vendor.hooks]
        assert sent == ["revoke", "uninstalled", "erase"]
        name, body, _authorization = next(h for h in vendor.hooks if h[0] == "revoke")
        assert body == {
            "connection": "hooked",
            "access_token": "gho_stored",
            "refresh_token": "ghr_stored",
        }
        revoke = (await rows())[0]
        assert revoke.done_at is not None and revoke.body == {}

    async def test_a_hook_after_the_install_has_gone_names_nobody(
        self, acting_user, session, vendor, registration
    ):
        """Once the plug-in's install is gone, a hook finds no name for the
        community and mints none, so a revocation still queued behind an erase
        is settled without bringing one back."""
        from app.db.request_context import Unattributed
        from app.models.platform.identity_ref import IdentityRef

        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a)
        guild_id, install_id = a.guild.id, plugin.id
        await route_session_to_guild(session, guild_id)
        await session.delete(await session.get(GuildPlugin, install_id))
        await session.commit()

        with pytest.raises(plugin_connection_flows.HookNameRefused):
            await plugin_connection_flows.call_hook(
                "revoke",
                public_id=PUBLIC_ID,
                base_url="https://app.example.test",
                guild_id=guild_id,
                install_id=install_id,
                body={"connection": "hooked"},
            )
        await set_rls_context(session, Unattributed())
        minted = (
            await session.exec(
                select(IdentityRef).where(
                    IdentityRef.sector_guild_id == guild_id,
                    IdentityRef.sector_plugin == PUBLIC_ID,
                )
            )
        ).all()
        assert minted == []


# ---------------------------------------------------------------------------
# The vendor values a registration needs
# ---------------------------------------------------------------------------


class TestVendorLiveness:
    async def test_a_registration_missing_a_required_value_is_not_live(
        self, session: AsyncSession
    ):
        await create_plugin_service_registration(
            session,
            public_id="tests.needs",
            base_url="https://needs.example.test",
            vendor_required=["client_id", "client_secret"],
            vendor_values=sealed_vendor_values({"client_id": "x"}),
        )
        snapshot = (await load_registrations(force=True))["tests.needs"]
        assert snapshot.live is False

    async def test_every_required_value_set_is_live(self, session: AsyncSession):
        await create_plugin_service_registration(
            session,
            public_id="tests.ready",
            base_url="https://ready.example.test",
            vendor_required=["client_id"],
            vendor_values=sealed_vendor_values({"client_id": "x"}),
        )
        snapshot = (await load_registrations(force=True))["tests.ready"]
        assert snapshot.live is True


# ---------------------------------------------------------------------------
# The vendor's webhooks
# ---------------------------------------------------------------------------

HOOK_ROUTE = f"/api/v1/plugin-hooks/{PUBLIC_ID}"


def _connected(installation_id: str) -> dict:
    """The community connection as a completed install-style flow leaves it."""
    return {"workspace": {"owner": "acme", "installation_id": installation_id}}


@pytest.fixture
async def listing(session: AsyncSession, registration):
    """The listing whose manifest declares the webhooks."""
    return await create_marketplace_listing(
        session,
        uid=LISTING_UID,
        public_id=PUBLIC_ID,
        kind="plugin",
        definition=DEFINITION,
    )


async def _deliveries(session: AsyncSession, guild_id: int) -> list[PluginHookDelivery]:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    return list((await session.exec(select(PluginHookDelivery))).all())


async def _delivered(session: AsyncSession, guild_id: int) -> None:
    """The delivery sweep's visit to the community, as a minute pass makes it."""
    async with cohorts.system_session(guild_id) as worker:
        await set_rls_context(worker, SystemGuild(guild_id))
        await plugin_hooks.run_due(worker, guild_id)


async def _deliveries_due(session: AsyncSession, guild_id: int) -> None:
    """Bring every waiting delivery in the community due again."""
    await route_session_to_guild(session, guild_id)
    await session.exec(
        update(PluginHookDelivery).values(
            taken_until=datetime.now(timezone.utc) - timedelta(seconds=1)
        )
    )
    await session.commit()


class TestVendorWebhooks:
    def test_the_limit_is_kept_per_plugin_and_sending_address(self):
        from starlette.requests import Request

        from app.api.v1.platform_endpoints.plugin_hooks import _per_plugin_and_sender
        from app.core import audit_context

        def _key(address: str) -> str:
            _, token = audit_context.begin(request_id="x", source_ip=address)
            try:
                return _per_plugin_and_sender(
                    Request(
                        {
                            "type": "http",
                            "headers": [],
                            "path_params": {"public_id": PUBLIC_ID},
                        }
                    )
                )
            finally:
                audit_context.end(token)

        assert _key("203.0.113.7") != _key("198.51.100.9")
        assert _key("203.0.113.7") == _key("203.0.113.7")

    async def test_a_delivery_reaches_each_community_that_connected_it_once(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        registration,
        listing,
    ):
        """One community connected installation 42 and a third connected 7.
        The second's connect of 42 is refused, storing nothing, until the
        registration shares routes, and then goes through. A delivery for 42
        is queued in each of the two, and each one's visit forwards it on a
        lifecycle token naming that install; a redelivery forwards nothing."""
        seats = [
            await acting_user(guild_role=CommunityRole.superadmin) for _ in range(3)
        ]
        plugins = [
            await _install(session, seats[0], config=_connected("42")),
            await _install(session, seats[1]),
            await _install(session, seats[2], config=_connected("7")),
        ]
        vendor.after_connect_answer = {
            "values": {"owner": "acme", "installation_id": "42"}
        }
        guild_id, install_id = seats[1].guild.id, plugins[1].id

        refused = await _connect_installation(client, seats[1], plugins[1], vendor)
        assert refused["outcome"] == "taken"
        stored = await _reload(session, guild_id, install_id)
        assert not stored.config and not stored.connection_refs
        assert (await _indexed(session, guild_id, install_id)).hook_route is None

        registration.shared_routes = True
        session.add(registration)
        await session.commit()
        connected = await _connect_installation(client, seats[1], plugins[1], vendor)
        assert connected["outcome"] == "connected"
        indexed = await _indexed(session, guild_id, install_id)
        assert (indexed.hook_route, indexed.exclusive) == ("42", False)

        body, headers = vendor.webhook({"action": "opened", "installation": {"id": 42}})

        response = await client.post(HOOK_ROUTE, content=body, headers=headers)
        assert response.status_code == 202, response.text
        assert [name for name, _, _ in vendor.hooks if name == "webhook"] == []
        for seat in seats[:2]:
            await _delivered(session, seat.guild.id)

        forwarded = [
            (call, token) for name, call, token in vendor.hooks if name == "webhook"
        ]
        claims = [
            jwt.decode(
                token.removeprefix("Bearer "), options={"verify_signature": False}
            )
            for _, token in forwarded
        ]
        assert sorted(claim["plugin_install_id"] for claim in claims) == [
            plugins[0].id,
            plugins[1].id,
        ]
        assert {claim["hook"] for claim in claims} == {"webhook"}
        assert claims[0]["community_ref"] != claims[1]["community_ref"]
        call = forwarded[0][0]
        assert call["connection"] == "workspace"
        assert call["body"] == body.decode()
        assert call["headers"]["x-github-event"] == "issues"
        assert call["headers"]["x-github-delivery"] == "delivery-1"
        assert "x-hub-signature-256" not in call["headers"]

        again = await client.post(HOOK_ROUTE, content=body, headers=headers)
        assert again.status_code == 202
        for seat in seats[:2]:
            await _delivered(session, seat.guild.id)
        assert len([name for name, _, _ in vendor.hooks if name == "webhook"]) == 2
        assert await _deliveries(session, seats[2].guild.id) == []

    @pytest.mark.parametrize("problem", ["bad_signature", "unroutable"])
    async def test_nothing_is_forwarded_or_stored_for_a_delivery_it_cannot_route(
        self, client: AsyncClient, acting_user, session, vendor, listing, problem
    ):
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _install(session, seat, config=_connected("42"))
        installation = 999 if problem == "unroutable" else 42
        body, headers = vendor.webhook({"installation": {"id": installation}})
        if problem == "bad_signature":
            headers["X-Hub-Signature-256"] = "sha256=" + "0" * 64

        response = await client.post(HOOK_ROUTE, content=body, headers=headers)

        assert response.status_code == (401 if problem == "bad_signature" else 202)
        assert [name for name, _, _ in vendor.hooks] == []
        assert await _deliveries(session, seat.guild.id) == []

    async def test_a_forward_that_fails_is_tried_again(
        self, client: AsyncClient, acting_user, session, vendor, listing
    ):
        """A delivery the plug-in did not accept waits in the community, and
        the next visit forwards it again."""
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook({"installation": {"id": 42}})
        queued = await client.post(HOOK_ROUTE, content=body, headers=headers)
        assert queued.status_code == 202, queued.text

        vendor.hook_status = 500
        await _delivered(session, seat.guild.id)
        [waiting] = await _deliveries(session, seat.guild.id)
        assert waiting.body is not None and waiting.attempts == 1
        assert waiting.taken_until > datetime.now(timezone.utc)

        vendor.hook_status = 200
        await _deliveries_due(session, seat.guild.id)
        await _delivered(session, seat.guild.id)

        assert len([name for name, _, _ in vendor.hooks if name == "webhook"]) == 2
        [recorded] = await _deliveries(session, seat.guild.id)
        assert (recorded.delivery_id, recorded.body) == ("delivery-1", None)

    async def test_a_delivery_is_described_by_the_version_each_install_pinned(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """The listing has moved on and calls its connection something else;
        the install's delivery still names the connection its version does."""
        moved = {
            **DEFINITION,
            "connections": [ACCOUNT, HOOKED, {**WORKSPACE, "id": "installation"}],
            "webhooks": {
                **DEFINITION["webhooks"],
                "route": {
                    **DEFINITION["webhooks"]["route"],
                    "connection": "installation",
                },
            },
        }
        await create_marketplace_listing(
            session,
            uid=LISTING_UID,
            public_id=PUBLIC_ID,
            kind="plugin",
            definition=moved,
        )
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook({"installation": {"id": 42}})

        response = await client.post(HOOK_ROUTE, content=body, headers=headers)

        assert response.status_code == 202, response.text
        await _delivered(session, seat.guild.id)
        [(name, call, _)] = vendor.hooks
        assert (name, call["connection"]) == ("webhook", "workspace")

    async def test_disconnecting_and_uninstalling_remove_the_route(
        self, client: AsyncClient, acting_user, session, vendor, registration
    ):
        """And uninstalling removes the install's schedules."""
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, a, config=_connected("42"))
        assert (await _indexed(session, a.guild.id, plugin.id)).hook_route == "42"
        assert set(await _runs(session, a.guild.id)) == {"check-installation"}

        response = await client.delete(
            a.g(f"/plugins/{plugin.id}/connections/workspace"), headers=a.headers
        )
        assert response.status_code == 204, response.text
        assert (await _indexed(session, a.guild.id, plugin.id)).hook_route is None

        response = await client.delete(a.g(f"/plugins/{plugin.id}"), headers=a.headers)
        assert response.status_code == 204, response.text
        assert await _indexed(session, a.guild.id, plugin.id) is None
        assert await _runs(session, a.guild.id) == {}


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


async def _runs(session: AsyncSession, guild_id: int) -> dict[str, PluginScheduleRun]:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    runs = (await session.exec(select(PluginScheduleRun))).all()
    return {run.schedule_id: run for run in runs}


async def _due(
    session: AsyncSession, guild_id: int, schedule_id: str | None = None
) -> None:
    """Bring every schedule in the community due, or only the one named."""
    now = datetime.now(timezone.utc)
    await route_session_to_guild(session, guild_id)
    due = update(PluginScheduleRun).values(next_due_at=now - timedelta(seconds=1))
    if schedule_id is not None:
        await session.exec(
            update(PluginScheduleRun).values(next_due_at=now + timedelta(hours=1))
        )
        due = due.where(PluginScheduleRun.schedule_id == schedule_id)
    await session.exec(due)
    await session.commit()


async def _run_due(worker: AsyncSession, guild_id: int) -> None:
    """One minute pass's visit to the community, on a system session."""
    await set_rls_context(worker, SystemGuild(guild_id))
    await plugin_schedules.run_due(worker, guild_id)


def _schedule_calls(vendor: FakeVendor) -> list[tuple[dict, dict]]:
    """Each schedule hook call, with its token's claims."""
    return [
        (
            call,
            jwt.decode(
                token.removeprefix("Bearer "), options={"verify_signature": False}
            ),
        )
        for name, call, token in vendor.hooks
        if name == "schedule"
    ]


class TestSchedules:
    async def test_two_workers_run_a_due_schedule_once(
        self, acting_user, session, role_session, vendor, registration
    ):
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _install(session, seat)
        await _due(session, seat.guild.id)

        workers = [await role_session() for _ in range(2)]
        await asyncio.gather(*(_run_due(w, seat.guild.id) for w in workers))

        [(call, claims)] = _schedule_calls(vendor)
        assert call == {"schedule": "check-installation", "since": None}
        assert (claims["scope"], claims["hook"]) == ("lifecycle", "schedule")
        assert claims["plugin_install_id"] == plugin.id

    async def test_since_is_the_last_success(
        self, acting_user, session, role_session, vendor, registration
    ):
        """A success is next due one interval later, plus up to a tenth of it,
        and a failure after it leaves ``since`` where the success put it."""
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        guild_id = seat.guild.id
        await _install(session, seat)
        worker = await role_session()

        started = datetime.now(timezone.utc)
        await _due(session, guild_id)
        await _run_due(worker, guild_id)
        run = (await _runs(session, guild_id))["check-installation"]
        assert run.last_success_at >= started
        wait = run.next_due_at - run.last_success_at
        assert timedelta(minutes=15) <= wait <= timedelta(minutes=17)

        for status in (500, 200):
            vendor.hook_status = status
            await _due(session, guild_id)
            await _run_due(worker, guild_id)

        since = run.last_success_at.isoformat()
        calls = [call["since"] for call, _ in _schedule_calls(vendor)]
        assert calls == [None, since, since]

    async def test_a_switched_off_install_is_not_called(
        self, acting_user, session, role_session, vendor, registration
    ):
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _install(session, seat, enabled=False)
        await _due(session, seat.guild.id)

        await _run_due(await role_session(), seat.guild.id)

        assert _schedule_calls(vendor) == []
        run = (await _runs(session, seat.guild.id))["check-installation"]
        assert (run.failures, run.claimed_until) == (0, None)

    async def test_a_failing_schedule_backs_off_to_ten_intervals(
        self, acting_user, session, role_session, vendor, registration
    ):
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        guild_id = seat.guild.id
        await _install(session, seat)
        worker = await role_session()
        vendor.hook_status = 500

        waits = []
        for _ in range(4):
            await _due(session, guild_id)
            before = datetime.now(timezone.utc)
            await _run_due(worker, guild_id)
            run = (await _runs(session, guild_id))["check-installation"]
            minutes = round((run.next_due_at - before).total_seconds() / 60)
            waits.append((run.failures, minutes))

        assert waits == [(1, 30), (2, 60), (3, 120), (4, 150)]


# ---------------------------------------------------------------------------
# A declarative plug-in: Initiative runs its connection and maps its deliveries
# ---------------------------------------------------------------------------

DECLARATIVE_ID = "tests.ghd"
DECLARATIVE_UID = "TESTAPP0000010"
DECLARATIVE = declarative_github(DECLARATIVE_ID)
ISSUE_OPENED = f"plugin.{DECLARATIVE_ID}.issue-opened"
DECLARATIVE_HOOKS = f"/api/v1/plugin-hooks/{DECLARATIVE_ID}"


@pytest.fixture
async def declarative(session: AsyncSession):
    return await create_plugin_service_registration(
        session,
        public_id=DECLARATIVE_ID,
        listing_uid=DECLARATIVE_UID,
        base_url=None,
        allowed_origins=[],
        jwks={},
        kind="declarative",
        vendor_values=sealed_vendor_values(VENDOR_VALUES),
        scope_ceiling=["projects:read"],
    )


async def _declarative_listing(session: AsyncSession, definition: dict = DECLARATIVE):
    return await create_marketplace_listing(
        session,
        uid=DECLARATIVE_UID,
        public_id=DECLARATIVE_ID,
        kind="plugin",
        definition=definition,
    )


async def _declarative_install(
    session: AsyncSession, actor, **overrides
) -> GuildPlugin:
    return await create_guild_plugin(
        session,
        actor.guild,
        actor.user,
        listing_uid=DECLARATIVE_UID,
        **{"definition": DECLARATIVE, **overrides},
    )


def _installations(*owners: tuple[int, str]) -> dict:
    """One page of the person's installations, as GitHub lists them."""
    return {
        "body": {
            "installations": [
                {"id": number, "account": {"login": login}} for number, login in owners
            ]
        }
    }


async def _events(session: AsyncSession, guild_id: int) -> list[tuple]:
    await route_session_to_guild(session, guild_id)
    session.expunge_all()
    rows = (await session.exec(select(PluginEventOutbox))).all()
    return [(row.event_type, row.initiative_id, row.payload) for row in rows]


def _issue(**issue) -> dict:
    return {
        "action": "opened",
        "installation": {"id": 42},
        "repository": {"full_name": "acme/web"},
        "issue": {"number": 12, "title": "Broken build", **issue},
    }


class TestDeclarativePlugins:
    async def test_after_connect_finds_the_installation_among_the_persons(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """Initiative lists the person's installations, every page, with the
        token it just obtained, and keeps the one the install page returned."""
        vendor.api_answers = [
            _installations((7, "other"), (8, "else")),
            _installations((42, "acme")),
        ]
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _declarative_install(session, a)

        landing = await _connect_installation(client, a, plugin, vendor)

        assert landing["outcome"] == "connected"
        assert vendor.hooks == []
        assert [request["url"] for request in vendor.api_requests] == [
            "https://api.github.test/user/installations?page=1&per_page=2",
            "https://api.github.test/user/installations?page=2&per_page=2",
        ]
        assert vendor.api_requests[0]["headers"]["authorization"].startswith(
            "Bearer gho_access_"
        )
        stored = await _reload(session, a.guild.id, plugin.id)
        assert stored.config["workspace"] == {"owner": "acme", "installation_id": "42"}
        assert (await _indexed(session, a.guild.id, plugin.id)).hook_route == "42"

    async def test_after_connect_refuses_an_installation_not_the_persons(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        vendor.api_answers = [_installations((7, "other"))]
        a = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _declarative_install(session, a)

        landing = await _connect_installation(client, a, plugin, vendor)

        assert landing["outcome"] == "refused"
        stored = await _reload(session, a.guild.id, plugin.id)
        assert "workspace" not in (stored.config or {})
        assert (await _indexed(session, a.guild.id, plugin.id)).hook_route is None

    async def test_an_opened_issue_is_emitted_once(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """The delivery becomes the plug-in's event, through the outbox a
        container's emission is kept in, and is never forwarded to a hook. A
        redelivery emits nothing."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook(_issue())

        for _ in range(2):
            response = await client.post(
                DECLARATIVE_HOOKS, content=body, headers=headers
            )
            assert response.status_code == 202, response.text
        await _delivered(session, seat.guild.id)

        assert await _events(session, seat.guild.id) == [
            (
                ISSUE_OPENED,
                None,
                {"repository": "acme/web", "number": 12, "title": "Broken build"},
            )
        ]
        assert vendor.hooks == []
        [recorded] = await _deliveries(session, seat.guild.id)
        assert recorded.delivery_id == "delivery-1"

    async def test_a_copy_of_a_waiting_delivery_is_queued_once(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """A redelivery of a waiting delivery's id changes nothing: one row,
        mapped once, remembered for 24 hours."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook(_issue())
        for _ in range(2):
            response = await client.post(
                DECLARATIVE_HOOKS, content=body, headers=headers
            )
            assert response.status_code == 202, response.text
        [queued] = await _deliveries(session, seat.guild.id)
        assert queued.body is not None

        await _delivered(session, seat.guild.id)

        assert len(await _events(session, seat.guild.id)) == 1
        [recorded] = await _deliveries(session, seat.guild.id)
        assert recorded.body is None
        assert recorded.expires_at > datetime.now(timezone.utc) + timedelta(hours=23)

    async def test_a_delivery_whose_changes_failed_is_tried_again(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        declarative,
        monkeypatch,
    ):
        """Its work waits, and the next visit makes it."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        apply_changes = metadata_service.apply_changes
        failed = False

        async def failing_once(*args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise RuntimeError("the database went away")
            return await apply_changes(*args, **kwargs)

        monkeypatch.setattr(metadata_service, "apply_changes", failing_once)
        body, headers = vendor.webhook(_issue())
        queued = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)
        assert queued.status_code == 202, queued.text
        await _delivered(session, seat.guild.id)
        [waiting] = await _deliveries(session, seat.guild.id)
        assert waiting.body is not None and waiting.attempts == 1
        assert await _events(session, seat.guild.id) == []

        await _deliveries_due(session, seat.guild.id)
        await _delivered(session, seat.guild.id)

        assert len(await _events(session, seat.guild.id)) == 1
        [recorded] = await _deliveries(session, seat.guild.id)
        assert (recorded.delivery_id, recorded.body) == ("delivery-1", None)

    async def test_a_holding_target_reaches_every_item(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        declarative,
        monkeypatch,
    ):
        """A change aimed at the items holding a value is made on all of them;
        the lookup route's page is not its bound."""
        writing = declarative_github(DECLARATIVE_ID)
        writing.update(scopes=["projects:read"])
        writing["webhooks"]["events"][0]["write"] = (
            '[{"target": {"holding": {"key": "github.repo",'
            ' "value": payload.repository.full_name}},'
            ' "set": {"github.state": "open"}}]'
        )
        await _declarative_listing(session, writing)
        seat = await acting_user(
            guild_role=CommunityRole.superadmin, initiative=True, project=True
        )
        await create_resource_grant(session, seat.project, all_initiative_members=True)
        tasks = [await create_task(session, seat.project) for _ in range(2)]
        plugin = await _declarative_install(
            session,
            seat,
            definition=writing,
            config=_connected("42"),
            granted_scopes=["projects:read"],
        )
        await route_session_to_guild(session, seat.guild.id)
        session.add(
            PluginPlacement(install_id=plugin.id, initiative_id=seat.initiative.id)
        )
        await session.commit()
        repo = await create_property_definition(
            session, None, plugin=plugin, key="github.repo", type=MetadataType.json
        )
        for task in tasks:
            await create_property_value(session, task, repo, value_json="acme/web")
        monkeypatch.setattr(metadata_service, "FIND_LIMIT", 1)
        body, headers = vendor.webhook(_issue())

        response = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)

        assert response.status_code == 202, response.text
        await _delivered(session, seat.guild.id)
        await route_session_to_guild(session, seat.guild.id)
        states = [
            entity_id
            for _, entity_id, key, _ in await kept_plugin_values(session)
            if key == "github.state"
        ]
        assert sorted(states) == sorted(task.id for task in tasks)

    async def test_an_installs_writes_arm_the_index_sweep(
        self, client: AsyncClient, acting_user, session, declarative
    ):
        """Each write to an install arms the index sweep in its community; its
        visit writes the install's row from the install as it stands. An
        uninstall drops the row at once."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)

        installed = await client.post(
            seat.g("/plugins/"),
            headers=seat.headers,
            json={"listing_uid": DECLARATIVE_UID},
        )

        assert installed.status_code == 201, installed.text
        plugin_id = installed.json()["id"]
        armed = await session.exec(
            select(CommunityTimer).where(
                CommunityTimer.community_id == seat.guild.id,
                CommunityTimer.kind == plugin_installs.INDEX_SWEEP,
            )
        )
        assert armed.first() is not None
        assert await _indexed(session, seat.guild.id, plugin_id) is not None

        removed = await client.delete(
            seat.g(f"/plugins/{plugin_id}"), headers=seat.headers
        )

        assert removed.status_code == 204, removed.text
        session.expunge_all()
        assert await session.get(PluginInstall, (seat.guild.id, plugin_id)) is None

    async def test_a_read_only_communitys_delivery_waits_for_it(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """It is queued, and worked through once the community takes writes
        again."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        seat.guild.status = CommunityStatus.read_only.value
        session.add(seat.guild)
        await session.commit()
        body, headers = vendor.webhook(_issue())

        queued = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)

        assert queued.status_code == 202, queued.text
        [waiting] = await _deliveries(session, seat.guild.id)
        assert waiting.body is not None

    async def test_a_delivery_for_a_replaced_connection_is_dropped(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """One waiting for installation 42 when the community connects 43
        instead maps nothing, and its id stays remembered."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _declarative_install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook(_issue())
        queued = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)
        assert queued.status_code == 202, queued.text
        vendor.api_answers = [_installations((43, "acme"))]
        landing = await _connect_installation(client, seat, plugin, vendor, 43)
        assert landing["outcome"] == "connected"

        await _delivered(session, seat.guild.id)

        assert await _events(session, seat.guild.id) == []
        [dropped] = await _deliveries(session, seat.guild.id)
        assert (dropped.delivery_id, dropped.body) == ("delivery-1", None)

    async def test_a_delivery_waits_as_long_as_it_must(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """One that has waited past the day a finished id is remembered is
        neither forgotten nor passed over; its day starts when it is done."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook(_issue())
        queued = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)
        assert queued.status_code == 202, queued.text
        await route_session_to_guild(session, seat.guild.id)
        long_ago = datetime.now(timezone.utc) - timedelta(days=2)
        await session.exec(update(PluginHookDelivery).values(expires_at=long_ago))
        await session.commit()
        async with cohorts.system_session(seat.guild.id) as worker:
            await set_rls_context(worker, SystemGuild(seat.guild.id))
            await plugin_hooks.expire_deliveries(
                worker, SimpleNamespace(now=datetime.now(timezone.utc))
            )
            await worker.commit()
        [waiting] = await _deliveries(session, seat.guild.id)
        assert waiting.body is not None

        await _delivered(session, seat.guild.id)

        assert len(await _events(session, seat.guild.id)) == 1
        [done] = await _deliveries(session, seat.guild.id)
        assert done.body is None
        assert done.expires_at > datetime.now(timezone.utc) + timedelta(hours=23)

    async def test_an_install_switched_on_is_delivered_to_at_once(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """The index may still say the install is off until its sweep comes;
        the install row says it is on, and that is what queues the delivery."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _declarative_install(session, seat, config=_connected("42"))
        session.expunge_all()
        indexed = await session.get(PluginInstall, (seat.guild.id, plugin.id))
        indexed.enabled = False
        session.add(indexed)
        await session.commit()
        body, headers = vendor.webhook(_issue())

        queued = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)

        assert queued.status_code == 202, queued.text
        [waiting] = await _deliveries(session, seat.guild.id)
        assert waiting.body is not None

    async def test_a_delivery_keeps_values_as_the_install(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """The matched row's ``write`` keeps values, as the install, on a task
        it reads, on every task holding a value it names, a list's element by
        its ref, and on the install itself, beside the event the row emits. A
        task in an initiative the install is not placed in is passed over. A
        value is shown where the plug-in declares its key as a field, and an
        upserted element merges into the one with its ref. The write reads the
        install's settings, and a unique setting's earlier values."""
        writing = declarative_github(DECLARATIVE_ID)
        writing.update(
            scopes=["projects:read"],
            features=["endpoints", "fields"],
            fields=[
                {
                    "key": "github.issue",
                    "name": {"en": "Issue"},
                    "kind": "number",
                    "on": ["task"],
                },
                {
                    "key": "github.pulls",
                    "name": {"en": "Pull requests"},
                    "kind": "link",
                    "list": True,
                    "on": ["task"],
                },
            ],
        )
        writing["webhooks"]["events"][0]["write"] = (
            '[{"target": {"kind": "task", "id": payload.task},'
            ' "set": {"github.issue": payload.issue.number}},'
            ' {"target": {"kind": "task", "id": payload.hidden},'
            ' "set": {"github.issue": payload.issue.number}},'
            ' {"target": {"holding": {"key": "github.repo",'
            ' "value": payload.repository.full_name}},'
            ' "set": {"github.state": "open"}},'
            ' {"target": {"holding": {"key": "github.pulls", "value": "812"}},'
            ' "upsert": {"github.pulls": [{"ref": "812",'
            ' "state": {"status": "merged"}}]}},'
            ' {"target": {"install": true},'
            ' "set": {"github.delivery": headers."x-github-delivery",'
            ' "github.prefixes": $append(settings.task_prefix, aliases.task_prefix)}}]'
        )
        await _declarative_listing(session, writing)
        seat = await acting_user(
            guild_role=CommunityRole.superadmin, initiative=True, project=True
        )
        await create_resource_grant(session, seat.project, all_initiative_members=True)
        task = await create_task(session, seat.project)
        linked = await create_task(session, seat.project)
        elsewhere = await create_initiative(session, seat.guild, seat.user, name="B")
        hidden = await create_task(
            session, await create_project(session, elsewhere, seat.user)
        )
        plugin = await _declarative_install(
            session,
            seat,
            definition=writing,
            config=_connected("42"),
            granted_scopes=["projects:read"],
            settings={"task_prefix": "acme"},
            setting_aliases={"task_prefix": ["acmeold"]},
        )
        pull = {"ref": "812", "url": "https://github.test/acme/web/pull/812"}
        await route_session_to_guild(session, seat.guild.id)
        session.add(
            PluginPlacement(install_id=plugin.id, initiative_id=seat.initiative.id)
        )
        await session.commit()
        await create_property_value(
            session,
            linked,
            await create_property_definition(
                session, None, plugin=plugin, key="github.repo", type=MetadataType.json
            ),
            value_json="acme/web",
        )
        await create_property_value(
            session,
            linked,
            await create_property_definition(
                session,
                None,
                plugin=plugin,
                key="github.pulls",
                type=MetadataType.link,
                list=True,
                shown_on=["task"],
            ),
            ref="812",
            value_json={"url": pull["url"]},
            value_text=pull["url"],
            state={"status": "open", "review": "approved"},
        )
        body, headers = vendor.webhook(
            {**_issue(), "task": task.id, "hidden": hidden.id}
        )

        response = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)

        assert response.status_code == 202, response.text
        await _delivered(session, seat.guild.id)
        assert [event for event, _, _ in await _events(session, seat.guild.id)] == [
            ISSUE_OPENED
        ]
        await route_session_to_guild(session, seat.guild.id)
        kept = await kept_plugin_values(session)
        assert kept == {
            ("task", task.id, "github.issue", ""): (12, True),
            ("task", linked.id, "github.repo", ""): ("acme/web", False),
            ("task", linked.id, "github.state", ""): ("open", False),
            ("task", linked.id, "github.pulls", "812"): (
                {**pull, "state": {"status": "merged", "review": "approved"}},
                True,
            ),
            ("plugin", plugin.id, "github.delivery", ""): ("delivery-1", False),
            ("plugin", plugin.id, "github.prefixes", ""): (["acme", "acmeold"], False),
        }

    async def test_a_pull_request_is_not_an_opened_issue(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook(_issue(pull_request={"url": "https://x"}))

        response = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)

        assert response.status_code == 202, response.text
        await _delivered(session, seat.guild.id)
        assert await _events(session, seat.guild.id) == []
        assert vendor.hooks == []

    async def test_an_installation_event_sets_the_connections_state(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        declarative,
        monkeypatch,
    ):
        """A removed installation holds no route, so nothing after it reaches
        the community. The index is written from the install as it stands once
        the state commits, so a reconnect landing in between keeps its route,
        and a status about an installation the community has since reconnected
        away from changes nothing."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _declarative_install(session, seat, config=_connected("42"))

        async def deliver(serial: int, action: str, installation: int = 42) -> tuple:
            body, headers = vendor.webhook(
                {"action": action, "installation": {"id": installation}},
                delivery=f"delivery-{serial}",
            )
            headers["X-GitHub-Event"] = "installation"
            response = await client.post(
                DECLARATIVE_HOOKS, content=body, headers=headers
            )
            assert response.status_code == 202, response.text
            await _delivered(session, seat.guild.id)
            stored = await _reload(session, seat.guild.id, plugin.id)
            indexed = await _indexed(session, seat.guild.id, plugin.id)
            return (stored.config_state, stored.config_state_detail, indexed.hook_route)

        def reconnecting(installation: int, then):
            """``then``, once the community has connected ``installation``."""

            async def run(*args, **kwargs):
                vendor.api_answers = [_installations((installation, "acme"))]
                landing = await _connect_installation(
                    client, seat, plugin, vendor, installation
                )
                assert landing["outcome"] == "connected"
                return await then(*args, **kwargs)

            return run

        reindex = plugin_installs.reindex_community
        mapping = declarative_service.map_delivery
        removed = ("invalid", "workspace_removed", None)
        assert await deliver(0, "suspend") == ("invalid", "workspace_suspended", "42")
        assert await deliver(1, "unsuspend") == ("ok", None, "42")
        # Reconnected between the state's commit and the index sweep's visit.
        monkeypatch.setattr(
            plugin_installs, "reindex_community", reconnecting(42, reindex)
        )
        assert await deliver(2, "deleted") == ("unverified", None, "42")
        monkeypatch.setattr(plugin_installs, "reindex_community", reindex)
        # Reconnected to installation 43 between routing and the status.
        monkeypatch.setattr(
            declarative_service, "map_delivery", reconnecting(43, mapping)
        )
        assert await deliver(3, "deleted") == ("unverified", None, "43")
        monkeypatch.setattr(declarative_service, "map_delivery", mapping)
        assert await deliver(4, "deleted", 43) == removed
        assert await deliver(5, "unsuspend", 43) == removed
        assert await _events(session, seat.guild.id) == []

    async def test_the_pinned_mapping_is_used_when_the_listing_moved_on(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        moved = declarative_github(DECLARATIVE_ID)
        moved["webhooks"]["events"][0]["map"] = (
            '{"repository": "moved/on", "number": payload.issue.number}'
        )
        await _declarative_listing(session, moved)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook(_issue())

        response = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)

        assert response.status_code == 202, response.text
        await _delivered(session, seat.guild.id)
        [(_, _, payload)] = await _events(session, seat.guild.id)
        assert payload["repository"] == "acme/web"

    async def test_a_mapping_that_may_answer_later_is_asked_again(
        self,
        client: AsyncClient,
        acting_user,
        session,
        vendor,
        declarative,
        monkeypatch,
    ):
        """No evaluator answered: the delivery waits, and maps on the next
        visit."""
        await _declarative_listing(session)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        holds = expressions.holds
        busy = [True]

        async def once_busy(*args, **kwargs):
            if busy.pop() if busy else False:
                raise expressions.ExpressionError("no evaluator", transient=True)
            return await holds(*args, **kwargs)

        monkeypatch.setattr(expressions, "holds", once_busy)
        body, headers = vendor.webhook(_issue())

        queued = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)
        assert queued.status_code == 202, queued.text
        await _delivered(session, seat.guild.id)
        [waiting] = await _deliveries(session, seat.guild.id)
        assert waiting.body is not None and waiting.attempts == 1
        assert await _events(session, seat.guild.id) == []

        await _deliveries_due(session, seat.guild.id)
        await _delivered(session, seat.guild.id)

        assert [event for event, _, _ in await _events(session, seat.guild.id)] == [
            ISSUE_OPENED
        ]

    async def test_a_mapping_that_cannot_answer_is_logged_and_the_state_kept(
        self, client: AsyncClient, acting_user, session, vendor, declarative, caplog
    ):
        """The event's payload does not fit its returns, and its write answers
        one change where a list belongs, neither of which a redelivery changes:
        the delivery is recorded, each failure logged, nothing written, and the
        status row it also matched still sets the state."""
        broken = declarative_github(DECLARATIVE_ID)
        broken["webhooks"]["events"][0].update(
            when="$exists(payload.action)",
            map='{"number": "twelve"}',
            write='{"target": {"install": true}, "set": {"seen": true}}',
        )
        await _declarative_listing(session, broken)
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _declarative_install(
            session, seat, definition=broken, config=_connected("42")
        )
        body, headers = vendor.webhook(
            {"action": "deleted", "installation": {"id": 42}}
        )
        headers["X-GitHub-Event"] = "installation"

        for _ in range(2):
            response = await client.post(
                DECLARATIVE_HOOKS, content=body, headers=headers
            )
            assert response.status_code == 202, response.text
        await _delivered(session, seat.guild.id)

        assert await _events(session, seat.guild.id) == []
        assert await kept_plugin_values(session) == {}
        stored = await _reload(session, seat.guild.id, plugin.id)
        assert stored.config_state_detail == "workspace_removed"
        [recorded] = await _deliveries(session, seat.guild.id)
        assert (recorded.delivery_id, recorded.body) == ("delivery-1", None)
        for failed in (
            "could not map delivery",
            "could not make the changes of delivery",
        ):
            logged = [
                record.getMessage()
                for record in caplog.records
                if f"{failed} delivery-1" in record.getMessage()
            ]
            assert len(logged) == 1 and DECLARATIVE_ID in logged[0]
        assert PluginChannelMessages.INVALID_PAYLOAD in logged[0]

    async def test_an_install_pinned_to_an_older_route_is_still_reached(
        self, client: AsyncClient, acting_user, session, vendor, declarative
    ):
        """The listing now routes by a header; an install still pinned to the
        version that read the body is found by it, and its own mapping runs."""
        await _declarative_listing(session)
        moved = declarative_github(DECLARATIVE_ID)
        moved["webhooks"]["route"] = {
            "header": "X-Installation-Target",
            "connection": "workspace",
            "field": "installation_id",
        }
        await create_marketplace_listing(
            session,
            uid=DECLARATIVE_UID,
            public_id=DECLARATIVE_ID,
            kind="plugin",
            version="2.0.0",
            definition=moved,
        )
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(session, seat, config=_connected("42"))
        body, headers = vendor.webhook(_issue())

        response = await client.post(DECLARATIVE_HOOKS, content=body, headers=headers)

        assert response.status_code == 202, response.text
        await _delivered(session, seat.guild.id)
        assert [event for event, _, _ in await _events(session, seat.guild.id)] == [
            ISSUE_OPENED
        ]

    async def test_a_check_of_a_connection_made_again_meanwhile_reports_nothing(
        self, acting_user, session, role_session, vendor, declarative, monkeypatch
    ):
        """The check read the installation the connection replaced, so what it
        found is not written to the new one, whose route stays."""
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        guild_id = seat.guild.id
        plugin = await _declarative_install(session, seat, config=_connected("42"))
        worker = await role_session()
        vendor.api_answers = [{"status": 404}]
        await _due(session, guild_id, "workspace")
        await _run_due(worker, guild_id)

        async def answer(request: httpx.Request) -> httpx.Response:
            if request.headers.get("host") == vendor.api_host:
                await route_session_to_guild(session, guild_id)
                await session.exec(
                    update(GuildPlugin)
                    .where(GuildPlugin.id == plugin.id)  # type: ignore[arg-type]
                    .values(config=_connected("99"))
                )
                await session.exec(
                    update(PluginInstall)
                    .where(
                        PluginInstall.guild_id == guild_id,  # type: ignore[arg-type]
                        PluginInstall.install_id == plugin.id,  # type: ignore[arg-type]
                    )
                    .values(hook_route="99")
                )
                await session.commit()
            return vendor.handle(request)

        monkeypatch.setattr(
            plugin_connection_flows, "http_transport", httpx.MockTransport(answer)
        )
        vendor.api_answers = [{"status": 404}]
        await _due(session, guild_id, "workspace")
        await _run_due(worker, guild_id)

        stored = await _reload(session, guild_id, plugin.id)
        indexed = await _indexed(session, guild_id, plugin.id)
        assert (
            stored.config_state,
            stored.config["workspace"]["installation_id"],
            "removed_at" in stored.config["workspace"],
            indexed.hook_route,
        ) == ("unverified", "99", False, "99")

    async def test_health_reports_a_failure_read_twice_and_recovery_at_once(
        self, acting_user, session, role_session, vendor, declarative
    ):
        """The check runs with the installation's own token. One answer that
        the installation is gone is not reported; two in a row are, and the
        first answer that it works again is. The removed connection holds no
        route until then: each report of it removed writes the index again,
        and another connection's report leaves it without one."""
        mirror = {**DECLARATIVE["connections"][0], "id": "mirror"}
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _declarative_install(
            session,
            seat,
            definition={
                **DECLARATIVE,
                "connections": [*DECLARATIVE["connections"], mirror],
            },
            config={
                **_connected("42"),
                "mirror": {"owner": "acme", "installation_id": "7"},
            },
        )
        assert set(await _runs(session, seat.guild.id)) == {"workspace", "mirror"}
        worker = await role_session()

        async def check(connection: str, answer: dict) -> tuple:
            vendor.api_answers = [answer]
            await _due(session, seat.guild.id, connection)
            await _run_due(worker, seat.guild.id)
            stored = await _reload(session, seat.guild.id, plugin.id)
            indexed = await _indexed(session, seat.guild.id, plugin.id)
            return (stored.config_state, stored.config_state_detail, indexed.hook_route)

        removed = ("invalid", "workspace_removed", None)
        assert await check("workspace", {"status": 404}) == ("unverified", None, "42")
        assert await check("workspace", {"status": 404}) == removed
        await session.exec(
            update(PluginInstall)
            .where(
                PluginInstall.guild_id == seat.guild.id,
                PluginInstall.install_id == plugin.id,
            )
            .values(hook_route="42")
        )
        await session.commit()
        assert await check("workspace", {"status": 404}) == removed
        assert await check("mirror", {"status": 403}) == removed
        suspended = ("invalid", "mirror_suspended")
        assert await check("mirror", {"status": 403}) == (*suspended, None)
        assert await check("workspace", {"body": {}}) == (*suspended, "42")
        assert {request["url"] for request in vendor.api_requests} == {
            "https://api.github.test/installation/repositories"
        }
        assert vendor.api_requests[0]["headers"]["authorization"].startswith(
            "Bearer ghs_installation_"
        )
        assert vendor.hooks == []


# ---------------------------------------------------------------------------
# A declarative plug-in's schedules: Initiative makes the read and its changes
# ---------------------------------------------------------------------------

#: Counts a repository's issues onto the tasks holding the repository, with
#: when it last succeeded.
SYNC = {
    "id": "sync",
    "every": "30m",
    "endpoint": f"plugin.{DECLARATIVE_ID}.issues",
    "params": '{"repo": connection.owner & "/web", "since": since}',
    "write": (
        '[{"target": {"holding": {"key": "github.repo", "value": "acme/web"}},'
        ' "set": {"github.issues": result.total, "github.since": since}}]'
    ),
}


def _syncing(**schedule: str) -> dict:
    """:data:`DECLARATIVE` with no health check, its issues read taking
    ``since`` as a query parameter, and :data:`SYNC` with ``schedule`` over
    it."""
    plugin = declarative_github(DECLARATIVE_ID)
    del plugin["connections"][0]["health"]
    issues = plugin["endpoints"][0]
    issues["params"].append(
        {"key": "since", "type": "string", "label": {"en": "Since"}}
    )
    issues["request"]["query"] = {"since": "params.since"}
    plugin.update(scopes=["projects:read"], schedules=[{**SYNC, **schedule}])
    return plugin


class TestDeclarativeSchedules:
    async def test_a_schedule_is_a_row_beside_the_health_checks(
        self, acting_user, session, declarative
    ):
        """It goes when the pinned version no longer declares it."""
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        plugin = await _declarative_install(
            session, seat, definition={**DECLARATIVE, "schedules": [SYNC]}
        )
        assert set(await _runs(session, seat.guild.id)) == {"workspace", "sync"}

        await plugin_schedules.reconcile(seat.guild.id, plugin.id, DECLARATIVE)

        assert set(await _runs(session, seat.guild.id)) == {"workspace"}

    async def test_a_due_schedule_keeps_what_its_read_answers(
        self, acting_user, session, role_session, vendor, declarative
    ):
        """The read is made with the installation's token and the params the
        schedule answers from the connection and ``since``, when it last
        succeeded. Its write keeps values, as the install, on the task holding
        the repository."""
        seat = await acting_user(
            guild_role=CommunityRole.superadmin, initiative=True, project=True
        )
        await create_resource_grant(session, seat.project, all_initiative_members=True)
        task = await create_task(session, seat.project)
        plugin = await _declarative_install(
            session,
            seat,
            definition=_syncing(),
            config=_connected("42"),
            granted_scopes=["projects:read"],
        )
        await route_session_to_guild(session, seat.guild.id)
        session.add(
            PluginPlacement(install_id=plugin.id, initiative_id=seat.initiative.id)
        )
        await session.commit()
        await create_property_value(
            session,
            task,
            await create_property_definition(
                session, None, plugin=plugin, key="github.repo", type=MetadataType.json
            ),
            value_json="acme/web",
        )
        worker = await role_session()

        successes = []
        for issues in ([{"title": "Broken build"}], [{"title": "A"}, {"title": "B"}]):
            vendor.api_answers = [{"body": issues}]
            await _due(session, seat.guild.id)
            await _run_due(worker, seat.guild.id)
            run = (await _runs(session, seat.guild.id))["sync"]
            assert (run.failures, run.claimed_until) == (0, None)
            successes.append(run.last_success_at)

        first, second = successes
        assert first < second
        read = "https://api.github.test/repos/acme/web/issues"
        assert [request["url"] for request in vendor.api_requests] == [
            read,
            f"{read}?{urlencode({'since': first.isoformat()})}",
        ]
        assert vendor.api_requests[0]["headers"]["authorization"].startswith(
            "Bearer ghs_installation_"
        )
        await route_session_to_guild(session, seat.guild.id)
        kept = {
            (entity_type, entity_id, key): value
            for (entity_type, entity_id, key, _), (value, _) in (
                await kept_plugin_values(session)
            ).items()
        }
        assert kept == {
            ("task", task.id, "github.repo"): "acme/web",
            ("task", task.id, "github.issues"): 2,
            ("task", task.id, "github.since"): first.isoformat(),
        }

    @pytest.mark.parametrize(
        ("exchange", "answer", "schedule", "code"),
        [
            (
                403,
                {"body": [{"title": "A"}]},
                {},
                PluginDataMessages.NEEDS_CONFIGURATION,
            ),
            (201, {"status": 502}, {}, PluginDataMessages.SERVICE_UNAVAILABLE),
            (201, {"status": 404}, {}, "not-found"),
            (
                201,
                {"body": [{"title": "A"}]},
                {"params": '"acme/web"'},
                "mapping-failed",
            ),
            (
                201,
                {"body": [{"title": "A"}]},
                {"write": '{"target": {"install": true}, "set": {"seen": true}}'},
                PluginChannelMessages.INVALID_PAYLOAD,
            ),
        ],
    )
    async def test_a_failing_schedule_is_logged_and_backs_off(
        self,
        acting_user,
        session,
        role_session,
        vendor,
        declarative,
        caplog,
        exchange,
        answer,
        schedule,
        code,
    ):
        """A stored connection whose token the vendor refuses, a read that
        fails or answers unavailable, a ``params`` that is not an object and
        changes that are not a list each fail the run: it is logged, nothing is
        kept, ``since`` stays unset, and the schedule waits
        ``every × 2^failures``."""
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        guild_id = seat.guild.id
        await _declarative_install(
            session, seat, definition=_syncing(**schedule), config=_connected("42")
        )
        worker = await role_session()
        vendor.exchange_status = exchange

        waits = []
        for _ in range(2):
            vendor.api_answers = [answer]
            await _due(session, guild_id)
            before = datetime.now(timezone.utc)
            await _run_due(worker, guild_id)
            run = (await _runs(session, guild_id))["sync"]
            minutes = round((run.next_due_at - before).total_seconds() / 60)
            waits.append((run.failures, minutes))

        assert waits == [(1, 60), (2, 120)]
        assert run.last_success_at is None
        assert await kept_plugin_values(session) == {}
        failure = (
            f"plug-in schedules: {DECLARATIVE_ID} did not run sync "
            f"for guild {guild_id} ({code})"
        )
        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == plugin_schedules.__name__
        ] == [failure, failure]

    async def test_a_schedule_whose_connection_is_not_made_is_skipped(
        self, acting_user, session, role_session, vendor, declarative, caplog
    ):
        """Nothing is sent or logged, its failures and ``since`` stay as they
        were, and it is next due one interval later."""
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        guild_id = seat.guild.id
        await _declarative_install(session, seat, definition=_syncing())
        since = datetime(2026, 10, 1, tzinfo=timezone.utc)
        await route_session_to_guild(session, guild_id)
        await session.exec(update(PluginScheduleRun).values(last_success_at=since))
        await session.commit()
        await _due(session, guild_id)
        before = datetime.now(timezone.utc)

        await _run_due(await role_session(), guild_id)

        run = (await _runs(session, guild_id))["sync"]
        assert (run.failures, run.last_success_at) == (0, since)
        wait = run.next_due_at - before
        assert timedelta(minutes=30) <= wait <= timedelta(minutes=34)
        assert (vendor.exchanges, vendor.api_requests) == ([], [])
        assert [r for r in caplog.records if r.name == plugin_schedules.__name__] == []

    @pytest.mark.parametrize(
        ("settings", "urls"),
        [
            ({"org": "acme"}, ["https://api.github.test/orgs/acme/issues"]),
            (None, []),
        ],
        ids=["held", "not stored yet"],
    )
    async def test_a_read_sees_each_connection_its_requires_names(
        self, acting_user, session, role_session, vendor, declarative, settings, urls
    ):
        """As ``connections.<id>``, as when the installation calls it. One the
        community has not stored yet is waited for, as the read's own is."""
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        definition = _syncing()
        definition["connections"].append(
            {
                "id": "settings",
                "scope": "static",
                "label": {"en": "Settings"},
                "fields": [
                    {
                        "key": "org",
                        "type": "string",
                        "required": True,
                        "label": {"en": "Organization"},
                    }
                ],
            }
        )
        issues = definition["endpoints"][0]
        issues["requires"] = {"all_of": ["workspace", "settings"]}
        issues["request"]["url"] = (
            '"https://api.github.test/orgs/" & connections.settings.org & "/issues"'
        )
        config = _connected("42") | ({} if settings is None else {"settings": settings})
        await _declarative_install(session, seat, definition=definition, config=config)
        vendor.api_answers = [{"body": []}]
        await _due(session, seat.guild.id)

        await _run_due(await role_session(), seat.guild.id)

        assert [request["url"] for request in vendor.api_requests] == urls
        assert (await _runs(session, seat.guild.id))["sync"].failures == 0

    async def test_a_switched_off_install_runs_no_schedule(
        self, acting_user, session, role_session, vendor, declarative
    ):
        seat = await acting_user(guild_role=CommunityRole.superadmin)
        await _declarative_install(
            session, seat, definition=_syncing(), config=_connected("42"), enabled=False
        )
        await _due(session, seat.guild.id)

        await _run_due(await role_session(), seat.guild.id)

        assert (vendor.exchanges, vendor.api_requests) == ([], [])
        run = (await _runs(session, seat.guild.id))["sync"]
        assert (run.failures, run.claimed_until) == (0, None)
