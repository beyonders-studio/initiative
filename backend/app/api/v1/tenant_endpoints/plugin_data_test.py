"""External data reaching a widget, and everything that has to be true first.

Five things carry the weight here.

**The gates run before anything else.** A member of the guild who is not in the
dashboard's initiative gets nothing — not a filtered answer, not an empty one.
That is the hard isolation boundary, and it is enforced by loading the dashboard
through the ordinary resource path rather than by a check in the proxy.

**A dashboard is not a skeleton key.** Holding one dashboard lets you fetch the
sources *it displays*. Naming a different source of the same plug-in is refused, so
the surface a viewer can reach is the surface they can see.

**Both kill switches are real.** The guild's install and the operator's
registration each stop the call on their own: the install is re-read per
request, and an operator's write drops the registration snapshot — neither is
something a cached body can outlive.

**The cache key contains every credential the response depended on.** Two members
who connected different vendor accounts must never see each other's rows. That is
the assertion the whole cache exists to survive, so it is tested end to end
through two real sessions rather than by inspecting a key.

**A plug-in that misbehaves costs one tile.** Unreachable, slow, oversized, or
answering in a shape we will not pass on — all of it comes back as a named code
with a 4xx/502, never a server fault.

The seam these tests stub is `_read_answer`: the single point where the decision
ends and the network begins. Everything above it — gates, kill switches,
parameters, credentials, the cache, the in-flight cap, the minted token — runs
for real.
"""

from datetime import datetime, timezone
from urllib.parse import quote

import json
import httpx
import jwt
import pytest
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.encryption import SALT_PLUGIN_CONFIG, encrypt_field
from app.core.messages import PluginDataMessages, GuildPluginMessages
from app.models.platform.plugin_service_registration import PluginServiceRegistration
from app.models.platform.guild import CommunityRole, CommunityStatus, Guild
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.initiative import InitiativeMember
from app.models.tenant.metadata import MetadataDefinition, MetadataType, MetadataValue
from app.models.tenant.task import Task
from app.models.tenant.plugin_placement import PluginPlacement
from app.services.marketplace.plugin_refs import (
    ensure_plugin_guild_ref,
    ensure_plugin_ref,
)
from app.services.marketplace import plugin_data as plugin_data_service
from app.services.marketplace.context_jwt_test import _PRIVATE_PEM
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant import plugin_connection_flows
from app.services.tenant.plugin_connection_flows import TokenSet, seal_tokens
from app.services.tenant.dashboard_definition import normalize_dashboard_definition
from app.testing.fake_vendor import API_HOST, FakeVendor, declarative_plugin
from app.models.platform.access_grant import AccessGrantPurpose, SettingsLevel
from app.models.platform.user import UserRole
from app.testing import (
    create_plugin_user_connection,
    create_access_grant,
    create_initiative,
    create_project,
    create_property_definition,
    create_property_value,
    create_resource_grant,
    create_task,
    create_user,
    get_auth_headers,
    create_plugin_service_registration,
    create_dashboard,
    create_guild_plugin,
    route_session_to_guild,
)


PLUGIN_UID = "SHPAPP00000001"
PUBLIC_ID = "acme.shop"

#: What the fixture plug-in declares. Namespaced under its own service id, which is
#: what every endpoint id has to be.
ORDERS_SUMMARY = f"plugin.{PUBLIC_ID}.orders-summary"
REVENUE = f"plugin.{PUBLIC_ID}.revenue"
#: Pinned before ``admin_only`` existed, under the earlier contract's term.
LEGACY_REPORT = f"plugin.{PUBLIC_ID}.legacy-report"
MY_PRS = f"plugin.{PUBLIC_ID}.my-prs"
REFUND = f"plugin.{PUBLIC_ID}.refund"
#: The two reads that exist to fill a menu rather than a tile. Which shops
#: there are is a fact about one install, so it cannot be written into a
#: manifest — the manifest names these instead.
LIST_SHOPS = f"plugin.{PUBLIC_ID}.list-shops"
LIST_AISLES = f"plugin.{PUBLIC_ID}.list-aisles"
BASE_URL = "http://127.0.0.1:9100"

#: A widget module with the characters a plain-text sanitizer would mangle.
MODULE_SOURCE = (
    "export const render = (d) => (d.rows.length < 5 && d.rows[0] ? {} : {});"
)


def _field(key: str, field_type: str, **extra) -> dict:
    return {"key": key, "type": field_type, "label": {"en": key}, **extra}


ADMIN_CONNECTION = {
    "id": "admin",
    "scope": "static",
    "label": {"en": "Admin API"},
    "fields": [_field("admin_token", "secret", required=True)],
}

GITHUB_CONNECTION = {
    "id": "github",
    "scope": "interactive",
    "label": {"en": "GitHub"},
    "flow": {
        "type": "oauth2",
        "authorize_url": "https://github.test/login/oauth/authorize",
        "token_url": "https://github.test/login/oauth/access_token",
        "client_id": "{vendor.client_id}",
        "after_connect": True,
    },
    "fields": [_field("login", "string", managed=True)],
}


def _definition() -> dict:
    """A service plug-in offering several sources: one for guild admins (and one
    pinned as such under the earlier contract), one that runs on the caller's
    own vendor account, and ordinary ones."""
    return {
        "plugin_kind": "service",
        "service": {"public_id": PUBLIC_ID, "protocol": 1},
        "features": ["endpoints", "widgets"],
        "connections": [ADMIN_CONNECTION, GITHUB_CONNECTION],
        "endpoints": [
            {
                "id": ORDERS_SUMMARY,
                "direction": "read",
                "cache_ttl_seconds": 60,
                "params": [
                    _field("range", "select", options=["7d", "30d"]),
                    _field("limit", "int"),
                    # A menu the plug-in fills, and a second that cannot be filled
                    # until the first has been: an aisle belongs to a shop.
                    _field(
                        "shop",
                        "string",
                        options_from={"endpoint": LIST_SHOPS, "key": "names"},
                    ),
                    _field(
                        "aisle",
                        "string",
                        options_from={
                            "endpoint": LIST_AISLES,
                            "key": "codes",
                            "label_key": "names",
                            "needs": {"shop": "shop"},
                        },
                    ),
                    # Sourced from the admin-only read, so a member asking for
                    # its values is a case rather than a hypothetical.
                    _field(
                        "tier",
                        "string",
                        options_from={"endpoint": REVENUE, "key": "tiers"},
                    ),
                    # Several values rather than one, which is a fact about the
                    # value and the only thing that says so.
                    _field(
                        "tags",
                        "string",
                        list=True,
                        options_from={"endpoint": LIST_SHOPS, "key": "names"},
                    ),
                    # Several of a type that is not a string, so the per-entry
                    # check is about the declared type rather than about text.
                    _field("floors", "int", list=True),
                ],
                "returns": [
                    {"key": "days", "type": "string", "list": True},
                    {"key": "totals", "type": "int", "list": True},
                    {"key": "total", "type": "int"},
                ],
            },
            {
                "id": REVENUE,
                "direction": "read",
                "admin_only": True,
                "cache_ttl_seconds": 0,
                "returns": [{"key": "tiers", "type": "string", "list": True}],
            },
            {
                "id": LEGACY_REPORT,
                "direction": "read",
                "visibility": "guild_admin",
                "cache_ttl_seconds": 0,
            },
            {
                "id": LIST_SHOPS,
                "direction": "read",
                "cache_ttl_seconds": 300,
                "returns": [{"key": "names", "type": "string", "list": True}],
            },
            {
                "id": LIST_AISLES,
                "direction": "read",
                "cache_ttl_seconds": 300,
                "params": [_field("shop", "string")],
                "returns": [
                    {"key": "codes", "type": "string", "list": True},
                    {"key": "names", "type": "string", "list": True},
                ],
            },
            {
                "id": MY_PRS,
                "direction": "read",
                "cache_ttl_seconds": 60,
                "requires": {"all_of": ["github"]},
            },
            # A write, so a case can prove a tile cannot reach one. Its
            # parameter's menu is filled from a read, as an action's form is.
            {
                "id": REFUND,
                "direction": "write",
                "actors": ["member"],
                "params": [
                    _field(
                        "shop",
                        "string",
                        options_from={"endpoint": LIST_SHOPS, "key": "names"},
                    )
                ],
            },
        ],
        "widgets": [
            {
                "id": "summary",
                "meta": {"name": {"en": "Summary"}},
                # Carries ``<`` and ``&`` deliberately: a widget module is
                # JavaScript, and a plain-text sanitizer on the way out would
                # rewrite these into something that no longer parses.
                "module_source": MODULE_SOURCE,
                "endpoints": [ORDERS_SUMMARY],
                # What the endpoint would answer with, in its own declared
                # returns — the catalog reads it the way the proxy reads a live
                # answer.
                "sample_data": {
                    ORDERS_SUMMARY: {"days": ["mon"], "totals": [4], "total": 4}
                },
            }
        ],
    }


def _dashboard_definition(*endpoint_ids: str, sql: str | None = None) -> dict:
    return normalize_dashboard_definition(
        {
            "widgets": [
                {
                    "id": f"w{index + 1}",
                    "type": f"plugin:{PLUGIN_UID}:summary",
                    "binding": {
                        "source": "plugin",
                        "plugin_uid": PLUGIN_UID,
                        "endpoint_id": endpoint_id,
                        **({"sql": sql} if sql else {}),
                    },
                }
                for index, endpoint_id in enumerate(endpoint_ids)
            ]
        }
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    """The plug-in platform needs its own keypair; these tests are about the proxy
    rather than the fail-closed path, so give it a real one."""
    monkeypatch.setattr(
        settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PRIVATE_PEM
    )
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_KEY_ID", "plugin-platform-1")


@pytest.fixture(autouse=True)
def _clean_cache():
    """Per test, both directions: an entry left behind would let one test's
    answer satisfy another's request."""
    plugin_data_service.clear_plugin_data_cache()
    plugin_data_service._inflight.clear()
    yield
    plugin_data_service.clear_plugin_data_cache()
    plugin_data_service._inflight.clear()


@pytest.fixture
def upstream(monkeypatch):
    """Stand in for the plug-in service, recording every call it receives.

    Returns a recorder whose ``calls`` holds the outgoing `httpx.Request`s — so a
    test can assert on the minted token and the URL — and whose ``rows`` and
    ``values`` are what the plug-in answers with next.
    """

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[httpx.Request] = []
            self.rows: list = [{"id": 1}]
            self.values: dict = {}
            self.error: Exception | None = None

        @property
        def count(self) -> int:
            return len(self.calls)

    recorder = Recorder()

    async def _fake_read_answer(request, *, endpoint, transport=None):
        recorder.calls.append(request)
        if recorder.error is not None:
            raise recorder.error
        return list(recorder.rows), dict(recorder.values)

    monkeypatch.setattr(plugin_data_service, "_read_answer", _fake_read_answer)
    return recorder


async def _register(
    session: AsyncSession, *, enabled: bool = True
) -> PluginServiceRegistration:
    return await create_plugin_service_registration(
        session,
        public_id=PUBLIC_ID,
        listing_uid=PLUGIN_UID,
        base_url=BASE_URL,
        allowed_origins=[BASE_URL],
        enabled=enabled,
    )


async def _install(session: AsyncSession, actor, **overrides):
    return await create_guild_plugin(
        session,
        actor.guild,
        actor.user,
        definition=_definition(),
        listing_uid=PLUGIN_UID,
        name="Shop",
        **overrides,
    )


async def _workspace(
    session: AsyncSession, acting_user, *sources: str, sql: str | None = None
):
    """A guild admin with a dashboards-enabled initiative, an installed plug-in, a
    live registration, and a dashboard binding the given sources."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    a.initiative.dashboards_enabled = True
    session.add(a.initiative)
    await session.commit()

    await _register(session)
    plugin = await _install(session, a)
    dashboard = await create_dashboard(
        session,
        a.initiative,
        a.user,
        definition=_dashboard_definition(*(sources or (ORDERS_SUMMARY,)), sql=sql),
    )
    return a, plugin, dashboard


def _url(actor, plugin, endpoint_id: str, dashboard, **params) -> str:
    query = f"dashboard_id={dashboard.id}"
    for key, value in params.items():
        query = f"{query}&{key}={value}"
    return actor.g(f"/plugins/{plugin.id}/endpoints/{endpoint_id}?{query}")


# ---------------------------------------------------------------------------
# The gates run first
# ---------------------------------------------------------------------------


class TestGates:
    async def test_a_member_reads_a_source_their_dashboard_displays(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows"] == [{"id": 1}]
        assert body["cached"] is False
        assert datetime.fromisoformat(body["fetched_at"]).tzinfo is not None

    async def test_both_halves_of_an_answer_reach_the_viewer(
        self, client, acting_user, session, upstream
    ):
        """An endpoint's ``list`` returns become rows and its single ones stay
        whole, and the route carries both."""
        a, plugin, dashboard = await _workspace(session, acting_user)
        upstream.rows = [{"days": "mon", "totals": 4}]
        upstream.values = {"total": 4}

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows"] == [{"days": "mon", "totals": 4}]
        assert body["values"] == {"total": 4}

    async def test_a_guild_member_outside_the_initiative_reaches_nothing(
        self, client, acting_user, session, upstream
    ):
        """The hard isolation boundary. The plug-in is installed guild-wide and this
        person is a member of the guild — but the dashboard belongs to an
        initiative they are not in, so RLS hides the row and the read is a 404
        before the plug-in is ever contacted."""
        a, plugin, dashboard = await _workspace(session, acting_user)
        outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.get(
            _url(outsider, plugin, ORDERS_SUMMARY, dashboard), headers=outsider.headers
        )
        assert response.status_code == 404
        assert upstream.count == 0

    async def test_a_dashboard_is_not_a_key_to_every_source(
        self, client, acting_user, session, upstream
    ):
        """The dashboard names which sources it displays; anything else is not
        reachable through it, even though the same plug-in offers it."""
        a, plugin, dashboard = await _workspace(session, acting_user, ORDERS_SUMMARY)

        response = await client.get(
            _url(a, plugin, REVENUE, dashboard), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == PluginDataMessages.ENDPOINT_NOT_FOUND
        assert upstream.count == 0

    async def test_a_source_the_plugin_does_not_declare_is_refused(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user, "made_up")

        response = await client.get(
            _url(a, plugin, "made_up", dashboard), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == PluginDataMessages.ENDPOINT_NOT_FOUND
        assert upstream.count == 0


class TestAdminOnly:
    @pytest.mark.parametrize("source", [REVENUE, LEGACY_REPORT])
    async def test_an_admin_only_source_is_open_to_an_admin(
        self, client, acting_user, session, upstream, source
    ):
        a, plugin, dashboard = await _workspace(session, acting_user, source)

        response = await client.get(
            _url(a, plugin, source, dashboard), headers=a.headers
        )
        assert response.status_code == 200, response.text

    @pytest.mark.parametrize("source", [REVENUE, LEGACY_REPORT])
    async def test_an_admin_only_source_is_refused_to_a_member(
        self, client, acting_user, session, upstream, source
    ):
        """Checked against the caller's real guild role, on the pinned
        definition — including one pinned under the earlier contract's
        ``visibility: "guild_admin"`` — not against anything the request
        supplied."""
        a, plugin, dashboard = await _workspace(session, acting_user, source)
        member = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        response = await client.get(
            _url(member, plugin, source, dashboard), headers=member.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == PluginDataMessages.ADMIN_ONLY
        assert upstream.count == 0


class TestKillSwitches:
    async def test_a_disabled_install_stops_the_call(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)
        await route_session_to_guild(session, a.guild.id)
        plugin.enabled = False
        session.add(plugin)
        await session.commit()

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == PluginDataMessages.PLUGIN_DISABLED
        assert upstream.count == 0

    async def test_the_operators_kill_switch_stops_the_call(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)
        registration = (await session.exec(select(PluginServiceRegistration))).first()
        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == PluginDataMessages.SERVICE_DISABLED
        assert upstream.count == 0

    async def test_a_kill_is_not_outlived_by_a_cached_body(
        self, client, acting_user, session, upstream
    ):
        """The operator's switch is read before the response cache, so an
        entry cached a moment earlier is not served after it flips."""
        a, plugin, dashboard = await _workspace(session, acting_user)
        first = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert first.status_code == 200

        registration = (await session.exec(select(PluginServiceRegistration))).first()
        registration.enabled = False
        session.add(registration)
        await session.commit()
        invalidate_registrations()

        second = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert second.status_code == 409

    async def test_an_unregistered_plugin_is_named_rather_than_guessed_at(
        self, client, acting_user, session, upstream
    ):
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        a.initiative.dashboards_enabled = True
        session.add(a.initiative)
        await session.commit()
        plugin = await _install(session, a)
        dashboard = await create_dashboard(
            session,
            a.initiative,
            a.user,
            definition=_dashboard_definition(ORDERS_SUMMARY),
        )

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == PluginDataMessages.SERVICE_NOT_REGISTERED


class TestParams:
    async def test_declared_parameters_reach_the_plugin(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params='{"range":"30d"}'),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        # In the body now, not the query string: one path serves every endpoint,
        # so which one is being called travels with the parameters.
        body = json.loads(upstream.calls[0].content)
        assert body["endpoint"] == ORDERS_SUMMARY
        assert body["params"]["range"] == "30d"

    @pytest.mark.parametrize(
        "params",
        [
            '{"nope":"1"}',  # not declared
            '{"range":"90d"}',  # outside the declared options
            '{"limit":"ten"}',  # wrong type for an int
            '{"limit":true}',  # a bool is not an int
            "not json",
            "[1,2]",  # not an object
        ],
    )
    async def test_anything_the_source_did_not_declare_is_refused(
        self, client, acting_user, session, upstream, params
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params=params),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == PluginDataMessages.INVALID_PARAMS
        assert upstream.count == 0


class TestContextToken:
    async def test_the_call_carries_a_guild_pinned_token_with_no_user(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)
        await client.get(_url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers)

        header = upstream.calls[0].headers["Authorization"]
        assert header.startswith("Bearer ")
        claims = jwt.decode(
            header.removeprefix("Bearer "),
            options={"verify_signature": False},
            algorithms=["EdDSA"],
        )
        # Named the way this install knows the guild, and by nothing else.
        assert claims["community_ref"] == await ensure_plugin_guild_ref(
            guild_id=a.guild.id, public_id=plugin.definition["service"]["public_id"]
        )
        assert "guild_id" not in claims
        assert claims["community_status"] == "active"
        assert claims["plugin_install_id"] == plugin.id
        assert claims["scope"] == "endpoint"
        assert claims["endpoint_id"] == ORDERS_SUMMARY
        assert claims["aud"] == f"initiative-plugin:{PUBLIC_ID}"
        assert claims["exp"] - claims["iat"] == 60
        assert "sub" not in claims
        # A guild-scoped source needs no per-member credential, so the token
        # carries no user-derived claim at all.
        assert "connection_refs" not in claims


# ---------------------------------------------------------------------------
# Credentials, and the cache key that follows them
# ---------------------------------------------------------------------------


async def _connect(session: AsyncSession, *, plugin, user, ref: str) -> None:
    """Give one member a completed per-member connection."""
    await create_plugin_user_connection(
        session,
        plugin,
        user,
        connection_ref=ref,
        secrets={"access_token": encrypt_field("tok", SALT_PLUGIN_CONFIG)},
    )


class TestConnections:
    async def test_a_member_who_has_not_connected_is_told_to(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user, MY_PRS)

        response = await client.get(
            _url(a, plugin, MY_PRS, dashboard), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == PluginDataMessages.CONNECTION_REQUIRED
        assert upstream.count == 0

    async def test_a_blocked_member_is_refused_by_name(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user, MY_PRS)
        await route_session_to_guild(session, a.guild.id)
        session.add(
            GuildPluginUserConnection(
                plugin_id=plugin.id,
                connection_id="github",
                user_id=a.user.id,
                connection_ref="cr_blocked",
                status="blocked",
                blocked_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

        response = await client.get(
            _url(a, plugin, MY_PRS, dashboard), headers=a.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == GuildPluginMessages.CONNECTION_BLOCKED
        assert upstream.count == 0

    async def test_the_token_carries_the_opaque_handle_not_the_person(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user, MY_PRS)
        await _connect(session, plugin=plugin, user=a.user, ref="cr_alice")

        response = await client.get(
            _url(a, plugin, MY_PRS, dashboard), headers=a.headers
        )
        assert response.status_code == 200, response.text

        claims = jwt.decode(
            upstream.calls[0].headers["Authorization"].removeprefix("Bearer "),
            options={"verify_signature": False},
            algorithms=["EdDSA"],
        )
        assert claims["connection_refs"] == {"github": "cr_alice"}
        assert str(a.user.id) not in str(claims.get("connection_refs"))
        assert "sub" not in claims

    async def test_an_unconfigured_guild_credential_is_named(
        self, client, acting_user, session, upstream
    ):
        """A source needing the guild's own credential says so rather than
        calling a plug-in that would fail."""
        definition = _definition()
        definition["endpoints"][0]["requires"] = {"all_of": ["admin"]}

        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        a.initiative.dashboards_enabled = True
        session.add(a.initiative)
        await session.commit()
        await _register(session)
        plugin = await create_guild_plugin(
            session, a.guild, a.user, definition=definition, listing_uid=PLUGIN_UID
        )
        dashboard = await create_dashboard(
            session,
            a.initiative,
            a.user,
            definition=_dashboard_definition(ORDERS_SUMMARY),
        )

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 409
        assert response.json()["detail"] == PluginDataMessages.NEEDS_CONFIGURATION
        assert upstream.count == 0


class TestCache:
    async def test_repeat_reads_of_guild_data_cost_one_upstream_call(
        self, client, acting_user, session, upstream
    ):
        """Twenty viewers of a dashboard are one call to the plug-in, which is what
        keeps a single-replica community container comfortable."""
        a, plugin, dashboard = await _workspace(session, acting_user)
        member = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )

        first = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        second = await client.get(
            _url(member, plugin, ORDERS_SUMMARY, dashboard), headers=member.headers
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["rows"] == first.json()["rows"]
        assert second.json()["cached"] is True
        assert upstream.count == 1

    async def test_different_parameters_are_different_entries(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)

        await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params='{"range":"7d"}'),
            headers=a.headers,
        )
        await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params='{"range":"30d"}'),
            headers=a.headers,
        )
        assert upstream.count == 2

    async def test_two_members_with_different_connections_never_share_an_entry(
        self, client, acting_user, session, upstream
    ):
        """The assertion the cache exists to survive.

        Both members read the same source of the same install on the same
        dashboard. Their vendor accounts differ, so their rows differ, and a
        shared entry would show one person the other's data.
        """
        a, plugin, dashboard = await _workspace(session, acting_user, MY_PRS)
        b = await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        await _connect(session, plugin=plugin, user=a.user, ref="cr_alice")
        await _connect(session, plugin=plugin, user=b.user, ref="cr_bob")

        upstream.rows = [{"pr": "alice"}]
        alice = await client.get(_url(a, plugin, MY_PRS, dashboard), headers=a.headers)
        upstream.rows = [{"pr": "bob"}]
        bob = await client.get(_url(b, plugin, MY_PRS, dashboard), headers=b.headers)

        assert alice.status_code == 200, alice.text
        assert bob.status_code == 200, bob.text
        assert alice.json()["rows"] == [{"pr": "alice"}]
        assert bob.json()["rows"] == [{"pr": "bob"}]
        # Two calls, because two credentials.
        assert upstream.count == 2
        assert bob.json()["cached"] is False

    async def test_one_members_repeated_reads_still_collapse(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user, MY_PRS)
        await _connect(session, plugin=plugin, user=a.user, ref="cr_alice")

        await client.get(_url(a, plugin, MY_PRS, dashboard), headers=a.headers)
        again = await client.get(_url(a, plugin, MY_PRS, dashboard), headers=a.headers)

        assert again.json()["cached"] is True
        assert upstream.count == 1

    async def test_a_rotated_credential_retires_the_answers_it_produced(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)
        await client.get(_url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers)
        assert upstream.count == 1

        await route_session_to_guild(session, a.guild.id)
        plugin.config = {"admin": {"shop_domain": "rotated.example"}}
        session.add(plugin)
        await session.commit()

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.json()["cached"] is False
        assert upstream.count == 2

    async def test_a_source_asking_for_no_cache_is_not_cached(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user, REVENUE)

        await client.get(_url(a, plugin, REVENUE, dashboard), headers=a.headers)
        await client.get(_url(a, plugin, REVENUE, dashboard), headers=a.headers)
        assert upstream.count == 2


class TestFailureIsOneTile:
    async def test_an_unreachable_plugin_is_a_named_code_not_a_server_fault(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)
        upstream.error = plugin_data_service.PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE, 502, "down"
        )

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 502
        assert response.json()["detail"] == PluginDataMessages.SERVICE_UNAVAILABLE

    async def test_a_failed_call_is_not_cached(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)
        upstream.error = plugin_data_service.PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE, 502, "down"
        )
        await client.get(_url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers)

        upstream.error = None
        upstream.rows = [{"id": 2}]
        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 200
        assert response.json()["rows"] == [{"id": 2}]

    async def test_one_slow_plugin_cannot_exhaust_the_worker(
        self, client, acting_user, session, upstream, monkeypatch
    ):
        """The in-flight cap is refused rather than queued: waiting behind a
        stalled plug-in is the same outage with a longer fuse."""
        a, plugin, dashboard = await _workspace(session, acting_user)
        monkeypatch.setitem(
            plugin_data_service._inflight,
            PUBLIC_ID,
            plugin_data_service.MAX_INFLIGHT_PER_PLUGIN,
        )

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 503
        assert response.json()["detail"] == PluginDataMessages.BUSY
        assert upstream.count == 0


class TestWidgetCatalog:
    async def test_it_serves_the_pinned_module_and_samples(
        self, client, acting_user, session
    ):
        a, plugin, _ = await _workspace(session, acting_user)

        response = await client.get(a.g("/plugins/widget-catalog"), headers=a.headers)
        assert response.status_code == 200, response.text

        entry = response.json()["items"][0]
        assert entry["plugin_uid"] == PLUGIN_UID
        assert entry["plugin_id"] == plugin.id

        widget = entry["widgets"][0]
        assert widget["type"] == f"plugin:{PLUGIN_UID}:summary"
        # Byte-for-byte: the module is JavaScript, and anything that rewrote a
        # ``<`` or an ``&`` on the way out would ship a module that cannot parse.
        assert widget["module_source"] == MODULE_SOURCE
        # Projected through the endpoint's returns, so what a preview draws is
        # what a bound tile draws.
        assert widget["sample_data"] == {
            ORDERS_SUMMARY: {
                "rows": [{"days": "mon", "totals": 4}],
                "values": {"total": 4},
            }
        }

        sources = {source["id"]: source for source in entry["endpoints"]}
        assert sources[REVENUE]["admin_only"] is True
        assert sources[LEGACY_REPORT]["admin_only"] is True
        assert sources[ORDERS_SUMMARY]["admin_only"] is False
        assert "visibility" not in sources[LEGACY_REPORT]
        assert sources[ORDERS_SUMMARY]["cache_ttl_seconds"] == 60

    async def test_a_disabled_install_offers_no_widgets(
        self, client, acting_user, session
    ):
        a, plugin, _ = await _workspace(session, acting_user)
        await route_session_to_guild(session, a.guild.id)
        plugin.enabled = False
        session.add(plugin)
        await session.commit()

        response = await client.get(a.g("/plugins/widget-catalog"), headers=a.headers)
        assert response.status_code == 200
        assert response.json()["items"] == []


# ---------------------------------------------------------------------------
# Filling a menu
# ---------------------------------------------------------------------------


def _options_url(actor, plugin, endpoint_id: str, param: str, **query) -> str:
    parts = [f"param={param}"]
    for key, value in query.items():
        parts.append(f"{key}={value}")
    return actor.g(
        f"/plugins/{plugin.id}/endpoints/{endpoint_id}/options?{'&'.join(parts)}"
    )


class TestParamOptions:
    """The read that turns a declared ``options_from`` into a menu.

    It is the one here with no dashboard on it, and the reason is the whole
    point of it: a form is filled in *before* a widget is placed, so there is no
    dashboard row whose gates could decide it. What stands in for that is that
    the caller never names what gets called — the source is read out of the
    plug-in's own declaration — and that the source's own visibility is enforced on
    the caller's own credentials.
    """

    async def test_a_member_gets_the_values_the_plugin_answers_with(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [{"names": "north"}, {"names": "south"}]

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "shop"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["unavailable"] is None
        assert [option["value"] for option in body["options"]] == ["north", "south"]
        # The source the manifest named, never one the caller did.
        assert json.loads(upstream.calls[0].content)["endpoint"] == LIST_SHOPS

    async def test_no_dashboard_is_named_or_needed(
        self, client, acting_user, session, upstream
    ):
        """The case the route exists for: a widget nobody has placed yet."""
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [{"names": "north"}]

        url = _options_url(a, plugin, ORDERS_SUMMARY, "shop")
        assert "dashboard" not in url
        assert (await client.get(url, headers=a.headers)).status_code == 200

    async def test_an_opaque_value_carries_what_a_person_reads(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [{"codes": "A1", "names": "Baking"}]

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "aisle", params='{"shop":"north"}'),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["options"] == [{"value": "A1", "label": "Baking"}]

    async def test_a_sibling_the_form_has_not_answered_calls_nothing(
        self, client, acting_user, session, upstream
    ):
        """An aisle belongs to a shop, and no shop has been chosen.

        Not an error, and not an empty menu either: the parameter stays typeable
        and the caller asks again once the sibling has a value. Asking the
        source anyway would offer every shop's aisles, which is not a menu
        anybody can use.
        """
        a, plugin, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "aisle"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"options": [], "unavailable": "needs-sibling"}
        assert upstream.count == 0

    async def test_a_sibling_answered_is_what_the_source_is_told(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [{"codes": "A1"}]

        await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "aisle", params='{"shop":"north"}'),
            headers=a.headers,
        )
        assert json.loads(upstream.calls[0].content)["params"] == {"shop": "north"}

    async def test_only_what_the_source_asked_for_is_forwarded(
        self, client, acting_user, session, upstream
    ):
        """The form holds more answers than the source needs, and the source is
        told exactly the ones its ``needs`` names."""
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [{"codes": "A1"}]

        await client.get(
            _options_url(
                a,
                plugin,
                ORDERS_SUMMARY,
                "aisle",
                params='{"shop":"north","range":"30d","limit":5}',
            ),
            headers=a.headers,
        )
        assert json.loads(upstream.calls[0].content)["params"] == {"shop": "north"}

    async def test_a_parameter_naming_no_source_says_so(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "limit"), headers=a.headers
        )
        assert response.status_code == 200
        assert response.json() == {"options": [], "unavailable": "no-source"}
        assert upstream.count == 0

    async def test_a_parameter_the_endpoint_does_not_declare_is_a_404(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "nonesuch"), headers=a.headers
        )
        assert response.status_code == 404
        assert response.json()["detail"] == PluginDataMessages.PARAM_NOT_FOUND

    async def test_a_source_that_will_not_answer_leaves_the_field_typeable(
        self, client, acting_user, session, upstream
    ):
        """A vendor outage must not become a value nobody can enter.

        The alternative — a disabled control — makes a configuration that would
        have worked unreachable for as long as the plug-in is down.
        """
        a, plugin, _ = await _workspace(session, acting_user)
        # The same seam every other failure case uses: `_read_answer` is where
        # the network is, and it is what turns an unreachable host into this.
        upstream.error = plugin_data_service.PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE, 502, "down"
        )

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "shop"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"options": [], "unavailable": "unresolved"}

    async def test_a_member_is_told_nothing_by_an_admin_only_source(
        self, client, acting_user, session, upstream
    ):
        """The source's own ``admin_only`` decides, exactly as it does for a
        tile. A member asking for the values of a parameter sourced from an
        admin-only read gets the same answer as one whose plug-in is down."""
        a, plugin, _ = await _workspace(session, acting_user)
        member = await acting_user(guild=a.guild, guild_role=CommunityRole.member)

        response = await client.get(
            _options_url(member, plugin, ORDERS_SUMMARY, "tier"), headers=member.headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"options": [], "unavailable": "unresolved"}
        assert upstream.count == 0

    async def test_a_member_fills_in_no_form_for_an_admin_only_endpoint(
        self, client, acting_user, session, upstream
    ):
        """Refused before the parameter is looked for: the form belongs to an
        endpoint this caller may not read."""
        a, plugin, _ = await _workspace(session, acting_user)
        member = await acting_user(guild=a.guild, guild_role=CommunityRole.member)

        response = await client.get(
            _options_url(member, plugin, REVENUE, "anything"), headers=member.headers
        )
        assert response.status_code == 403
        assert response.json()["detail"] == PluginDataMessages.ADMIN_ONLY
        assert upstream.count == 0

    async def test_a_guild_admin_reads_that_same_source(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [{"tiers": "gold"}]

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "tier"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert [o["value"] for o in response.json()["options"]] == ["gold"]

    async def test_a_repeated_value_is_offered_once_in_the_order_given(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [
            {"names": "south"},
            {"names": "north"},
            {"names": "south"},
            {"names": None},
        ]

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "shop"), headers=a.headers
        )
        assert [o["value"] for o in response.json()["options"]] == ["south", "north"]

    async def test_a_disabled_install_fills_no_menu(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)
        await route_session_to_guild(session, a.guild.id)
        plugin.enabled = False
        session.add(plugin)
        await session.commit()

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "shop"), headers=a.headers
        )
        assert response.status_code == 200
        assert response.json()["unavailable"] == "unresolved"

    async def test_a_writes_parameter_is_filled_from_its_read(
        self, client, acting_user, session, upstream
    ):
        """An action's form asks for a write's parameters, and their menus are
        filled the way a read's are: from the read the parameter names, which
        is the only thing called. Filling in a form is no way to make a
        plug-in act."""
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [{"names": "north"}]

        response = await client.get(
            _options_url(a, plugin, REFUND, "shop"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert [option["value"] for option in response.json()["options"]] == ["north"]
        assert [json.loads(call.content)["endpoint"] for call in upstream.calls] == [
            LIST_SHOPS
        ]


class TestListParams:
    """A parameter declaring several values.

    ``list`` exists so a plug-in does not have to declare a string and document a
    comma — a convention nothing on this side could validate or complete. That
    only holds if an array is what actually travels, so these pin the shape
    rather than the convention.
    """

    async def test_several_values_reach_the_plugin_as_several(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(
                a, plugin, ORDERS_SUMMARY, dashboard, params='{"tags":["red","blue"]}'
            ),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        assert json.loads(upstream.calls[0].content)["params"] == {
            "tags": ["red", "blue"]
        }

    async def test_one_value_for_a_list_parameter_is_still_an_array(
        self, client, acting_user, session, upstream
    ):
        """Cardinality is the declaration's, not the caller's. A single value
        sent bare would be a second encoding of the same thing."""
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params='{"tags":"red"}'),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == PluginDataMessages.INVALID_PARAMS

    @pytest.mark.parametrize(
        "params",
        [
            '{"shop":["north"]}',
            # "None of them" is a parameter that is absent. An array with
            # nothing in it is a request nobody meant to make.
            '{"tags":[]}',
            '{"tags":["red",7]}',
        ],
        ids=[
            "an array for a single parameter",
            "an empty array",
            "an entry of the wrong type",
        ],
    )
    async def test_a_value_the_declaration_does_not_describe_never_reaches_the_plugin(
        self, client, acting_user, session, upstream, params
    ):
        """Cardinality and type are both read off the declaration, and a value
        that answers neither is refused here rather than forwarded."""
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params=params),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert upstream.count == 0

    async def test_more_values_than_a_request_may_carry_are_refused(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)
        many = json.dumps(
            {
                "tags": [
                    str(index)
                    for index in range(plugin_data_service.MAX_PARAM_VALUES + 1)
                ]
            }
        )

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params=many), headers=a.headers
        )
        assert response.status_code == 400
        assert upstream.count == 0

    async def test_a_list_parameter_fills_its_menu_the_same_way(
        self, client, acting_user, session, upstream
    ):
        """Where the values come from does not change with how many are wanted:
        one source answers both."""
        a, plugin, _ = await _workspace(session, acting_user)
        upstream.rows = [{"names": "north"}, {"names": "south"}]

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "tags"), headers=a.headers
        )
        assert response.status_code == 200, response.text
        assert [o["value"] for o in response.json()["options"]] == ["north", "south"]

    async def test_a_sibling_answered_with_nothing_is_unanswered(
        self, client, acting_user, session, upstream
    ):
        a, plugin, _ = await _workspace(session, acting_user)

        response = await client.get(
            _options_url(a, plugin, ORDERS_SUMMARY, "aisle", params='{"shop":""}'),
            headers=a.headers,
        )
        assert response.json()["unavailable"] == "needs-sibling"
        assert upstream.count == 0

    async def test_several_integers_are_accepted_as_integers(
        self, client, acting_user, session, upstream
    ):
        """`list` says how many, never what kind.

        Each entry is held to the parameter's own declared type, so a caller
        that sent the strings a form's controls read would be refused here —
        which is exactly the failure a configured widget would hit on its first
        draw rather than on save.
        """
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params='{"floors":[1,2]}'),
            headers=a.headers,
        )
        assert response.status_code == 200, response.text
        # Rendered for the wire the same way a single int is, which is what
        # keeps one encoding for one type.
        assert json.loads(upstream.calls[0].content)["params"] == {"floors": ["1", "2"]}

    async def test_a_string_where_an_integer_was_declared_is_refused(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params='{"floors":["1"]}'),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == PluginDataMessages.INVALID_PARAMS
        assert upstream.count == 0

    async def test_a_bool_is_not_an_integer_inside_a_list_either(
        self, client, acting_user, session, upstream
    ):
        a, plugin, dashboard = await _workspace(session, acting_user)

        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, params='{"floors":[true]}'),
            headers=a.headers,
        )
        assert response.status_code == 400
        assert upstream.count == 0


class TestAStatementOverTheRows:
    """A built-in widget pointed at a plug-in.

    The plug-in's own rows are read by its own module, by the names its manifest
    declared. A statement is what lets a chart or a table be pointed at them
    instead — evaluated here, over the answer the proxy already fetched, so
    twenty viewers are still one upstream call.
    """

    async def test_the_widget_gets_what_its_statement_made_of_the_rows(
        self, client, session, acting_user, upstream
    ):
        upstream.rows = [
            {"days": "mon", "totals": 3},
            {"days": "mon", "totals": 4},
            {"days": "tue", "totals": 5},
        ]
        a, plugin, dashboard = await _workspace(
            session,
            acting_user,
            ORDERS_SUMMARY,
            sql="SELECT days AS day, sum(totals) AS total FROM rows GROUP BY days",
        )
        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, widget_id="w1"),
            headers=a.headers,
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["table"]["columns"] == [
            {"name": "day", "type": "text", "grain": None, "date_only": False},
            {"name": "total", "type": "number", "grain": None, "date_only": False},
        ]
        assert body["table"]["rows"] == [["mon", 7.0], ["tue", 5.0]]

    async def test_two_outputs_of_one_name_both_survive(
        self, client, session, acting_user, upstream
    ):
        """Positional, for the reason every read of this surface is: a mapping
        would keep one of the two."""
        upstream.rows = [{"days": "mon", "totals": 3}]
        a, plugin, dashboard = await _workspace(
            session,
            acting_user,
            ORDERS_SUMMARY,
            sql="SELECT days, totals AS days FROM rows",
        )
        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, widget_id="w1"),
            headers=a.headers,
        )
        assert response.status_code == 200, response.json()
        assert response.json()["table"]["rows"] == [["mon", 3]]

    async def test_a_binding_with_no_statement_is_untouched(
        self, client, session, acting_user, upstream
    ):
        """The plug-in's own widget still reads its own rows, by its own names."""
        a, plugin, dashboard = await _workspace(session, acting_user)
        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["table"] is None
        assert body["rows"] == [{"id": 1}]

    async def test_the_statement_that_runs_is_the_stored_one(
        self, client, session, acting_user, upstream
    ):
        """Naming a widget that is not on this dashboard changes nothing —
        there is nowhere for a request to put a statement of its own."""
        a, plugin, dashboard = await _workspace(
            session,
            acting_user,
            ORDERS_SUMMARY,
            sql="SELECT days AS day FROM rows",
        )
        response = await client.get(
            _url(a, plugin, ORDERS_SUMMARY, dashboard, widget_id="nope"),
            headers=a.headers,
        )
        assert response.status_code == 200
        # Untransformed, because no widget of that id binds this endpoint.
        assert response.json()["table"] is None


# ---------------------------------------------------------------------------
# A declarative plug-in: Initiative calls the vendor itself
# ---------------------------------------------------------------------------


class TestDeclarative:
    """No container and no context token: the endpoint is the manifest's
    request, sent to the vendor with the community's credential, and its map.
    What reaches the tile is read exactly as a container's answer is."""

    ISSUES = "plugin.acme.issues.issues"

    async def _workspace(self, session, acting_user, monkeypatch):
        vendor = FakeVendor()
        vendor.install(monkeypatch)
        a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
        a.initiative.dashboards_enabled = True
        session.add(a.initiative)
        await session.commit()
        await create_plugin_service_registration(
            session,
            public_id="acme.issues",
            listing_uid=PLUGIN_UID,
            base_url=None,
            allowed_origins=[],
            jwks={},
            kind="declarative",
        )
        config, secrets = seal_tokens(
            TokenSet(access_token="gho_community"), config={}, secrets={}
        )
        plugin = await create_guild_plugin(
            session,
            a.guild,
            a.user,
            definition=declarative_plugin("acme.issues"),
            listing_uid=PLUGIN_UID,
            name="Issues",
            config={"workspace": config},
            secrets={"workspace": secrets},
        )
        dashboard = await create_dashboard(
            session,
            a.initiative,
            a.user,
            definition=_dashboard_definition(self.ISSUES),
        )
        url = _url(
            a, plugin, self.ISSUES, dashboard, params=quote('{"repo": "acme/web"}')
        )
        return a, vendor, url

    async def test_the_vendor_answers_through_the_plugins_own_mapping(
        self, client, acting_user, session, monkeypatch
    ):
        a, vendor, url = await self._workspace(session, acting_user, monkeypatch)
        vendor.api_answers = [{"body": [{"title": "Broken build"}, {"title": "Typo"}]}]

        first = await client.get(url, headers=a.headers)
        again = await client.get(url, headers=a.headers)

        assert first.status_code == 200, first.text
        assert first.json()["rows"] == [{"titles": "Broken build"}, {"titles": "Typo"}]
        assert first.json()["values"] == {"total": 2}
        assert again.json()["cached"] is True
        (request,) = vendor.api_requests
        assert request["url"] == "https://api.github.test/repos/acme/web/issues"
        assert request["headers"]["authorization"] == "Bearer gho_community"

    async def test_a_vendor_refusal_is_the_endpoints_unavailable_code(
        self, client, acting_user, session, monkeypatch
    ):
        a, vendor, url = await self._workspace(session, acting_user, monkeypatch)
        vendor.api_answers = [{"status": 404}]

        response = await client.get(url, headers=a.headers)

        assert response.status_code == 200, response.text
        assert response.json()["rows"] == []
        assert response.json()["values"] == {"unavailable": "not-found"}

    async def test_a_passing_failure_is_the_plugin_being_unavailable(
        self, client, acting_user, session, monkeypatch
    ):
        a, vendor, url = await self._workspace(session, acting_user, monkeypatch)
        vendor.api_answers = [{"status": 503}]

        response = await client.get(url, headers=a.headers)

        assert response.status_code == 502
        assert response.json()["detail"] == PluginDataMessages.SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Where the community stands with a plug-in
# ---------------------------------------------------------------------------


class TestSummary:
    """The read a manifest names as its ``community_summary``, for the Usage
    settings tab. The caller names the install; the endpoint is the pinned
    definition's to say."""

    async def _summarised(self, session, acting_user, *, summary=REVENUE):
        a = await acting_user(guild_role=CommunityRole.admin)
        await _register(session)
        definition = _definition()
        if summary is not None:
            definition["community_summary"] = summary
        plugin = await create_guild_plugin(
            session,
            a.guild,
            a.user,
            definition=definition,
            listing_uid=PLUGIN_UID,
            name="Shop",
        )
        return a, plugin

    async def test_an_admin_reads_the_endpoint_the_definition_names(
        self, client, acting_user, session, upstream
    ):
        a, plugin = await self._summarised(session, acting_user)
        upstream.rows = []
        upstream.values = {"tiers": None}

        response = await client.get(
            a.g(f"/plugins/{plugin.id}/summary"), headers=a.headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["values"] == {"tiers": None}
        (request,) = upstream.calls
        assert json.loads(request.content)["endpoint"] == REVENUE

    async def test_a_member_reads_no_summary(
        self, client, acting_user, session, upstream
    ):
        a, plugin = await self._summarised(session, acting_user)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.get(
            member.g(f"/plugins/{plugin.id}/summary"), headers=member.headers
        )

        assert response.status_code == 403
        assert upstream.count == 0

    async def test_an_install_naming_no_summary_has_nothing_to_draw(
        self, client, acting_user, session, upstream
    ):
        a, plugin = await self._summarised(session, acting_user, summary=None)

        response = await client.get(
            a.g(f"/plugins/{plugin.id}/summary"), headers=a.headers
        )

        assert response.status_code == 404
        assert upstream.count == 0

    async def test_a_plugin_that_does_not_answer_is_named_unavailable(
        self, client, acting_user, session, upstream
    ):
        a, plugin = await self._summarised(session, acting_user)
        upstream.error = plugin_data_service.PluginDataError(
            PluginDataMessages.SERVICE_UNAVAILABLE, 502, "down"
        )

        response = await client.get(
            a.g(f"/plugins/{plugin.id}/summary"), headers=a.headers
        )

        assert response.status_code == 502
        assert response.json()["detail"] == PluginDataMessages.SERVICE_UNAVAILABLE

    async def test_the_list_names_each_install_with_a_summary_and_what_it_returns(
        self, client, acting_user, session, upstream
    ):
        a, plugin = await self._summarised(session, acting_user)
        # A second install that names none is not listed.
        await create_guild_plugin(
            session,
            a.guild,
            a.user,
            definition=_definition(),
            listing_uid="SHPAPP00000002",
            name="Other",
        )

        response = await client.get(a.g("/plugins/summaries"), headers=a.headers)

        assert response.status_code == 200, response.text
        (item,) = response.json()["items"]
        assert item["plugin_id"] == plugin.id
        assert item["name"] == "Shop"
        assert [value["key"] for value in item["returns"]] == ["tiers"]
        assert upstream.count == 0

    async def test_a_settings_grantee_lists_and_reads_summaries(
        self, client, acting_user, session, upstream
    ):
        """Support lent the seat opens the Usage tab without a content grant, so
        neither read may sit behind the content-gated install list."""
        a, plugin = await self._summarised(session, acting_user)
        support = await create_user(session, role=UserRole.support)
        await create_access_grant(
            session,
            user=support,
            guild=a.guild,
            access_level=SettingsLevel.admin.value,
            purpose=AccessGrantPurpose.settings.value,
        )
        headers = get_auth_headers(support)

        listed = await client.get(
            f"/api/v1/c/{a.guild.id}/plugins/summaries", headers=headers
        )
        read = await client.get(
            f"/api/v1/c/{a.guild.id}/plugins/{plugin.id}/summary", headers=headers
        )

        assert listed.status_code == 200, listed.text
        assert [item["plugin_id"] for item in listed.json()["items"]] == [plugin.id]
        assert read.status_code == 200, read.text

    async def test_a_member_lists_no_summaries(
        self, client, acting_user, session, upstream
    ):
        a, _ = await self._summarised(session, acting_user)
        member = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

        response = await client.get(
            member.g("/plugins/summaries"), headers=member.headers
        )

        assert response.status_code == 403

    async def test_an_operator_lists_and_reads_summaries_without_joining(
        self, client, acting_user, session, upstream
    ):
        """The operator's sheet for the community shows what its Usage tab
        does, with no membership or grant."""
        a, plugin = await self._summarised(session, acting_user)
        upstream.values = {"tiers": 3}
        headers = get_auth_headers(await create_user(session, role=UserRole.operator))
        base = f"/api/v1/settings/communities/{a.guild.id}/plugin-summaries"

        listed = await client.get(base, headers=headers)
        read = await client.get(f"{base}/{plugin.id}", headers=headers)

        assert listed.status_code == 200, listed.text
        assert [item["plugin_id"] for item in listed.json()["items"]] == [plugin.id]
        assert read.status_code == 200, read.text
        assert read.json()["values"] == {"tiers": 3}

    async def test_support_reads_no_operator_summaries(
        self, client, acting_user, session, upstream
    ):
        a, _ = await self._summarised(session, acting_user)
        headers = get_auth_headers(await create_user(session, role=UserRole.support))

        response = await client.get(
            f"/api/v1/settings/communities/{a.guild.id}/plugin-summaries",
            headers=headers,
        )

        assert response.status_code == 403


async def test_a_viewer_too_young_for_the_plugin_reads_no_tile(
    client, acting_user, session, upstream
):
    """What a tile shows is the plug-in's, so a viewer under its minimum age —
    or with no date of birth on file — reads none of it."""
    a, plugin, dashboard = await _workspace(session, acting_user)
    plugin.definition = {**plugin.definition, "minimum_age": {"default": 16}}
    session.add(plugin)
    await session.commit()

    response = await client.get(
        _url(a, plugin, ORDERS_SUMMARY, dashboard), headers=a.headers
    )

    assert response.status_code == 403
    assert response.json()["detail"] == GuildPluginMessages.AGE_RESTRICTED
    assert upstream.count == 0


# ---------------------------------------------------------------------------
# Actions on items
# ---------------------------------------------------------------------------

LINK_ISSUE = f"plugin.{PUBLIC_ID}.link-issue"


def _action_definition() -> dict:
    """One field and two actions on tasks, each running a write, the second
    for the community's admins alone."""
    return {
        "plugin_kind": "service",
        "service": {"public_id": PUBLIC_ID, "protocol": 1, "scopes": ["projects:read"]},
        "endpoints": [{"id": LINK_ISSUE, "direction": "write"}],
        "fields": [
            {"key": "issue", "name": {"en": "Issue"}, "kind": "number", "on": ["task"]}
        ],
        "actions": [
            {
                "id": "link",
                "name": {"en": "Link"},
                "endpoint": LINK_ISSUE,
                "on": ["task"],
                "menu": False,
            },
            {
                "id": "relink",
                "name": {"en": "Link again"},
                "endpoint": LINK_ISSUE,
                "on": ["task"],
                "menu": False,
                "admin_only": True,
            },
        ],
    }


FIND_ISSUE = f"plugin.{PUBLIC_ID}.find-issue"


def _declarative_action_definition() -> dict:
    """:func:`declarative_plugin` keeping an issue on tasks: ``link`` searches
    for the task's title on the community's connection and keeps the number
    found; ``tally`` adds one to it; ``unlink``, for a reader who has
    connected their own account, drops it with no call, keeping what it was;
    ``relink`` is the community's admins' alone; ``label`` makes the label
    write as the reader, on the account its request names for the member,
    once they have connected it, and as the installation, on the community's,
    before; ``garble`` answers a targeted change where a change belongs;
    ``assign`` asks the reader which issue to label and keeps its number;
    ``drop``, offered on each of the ``links`` list's elements, removes the
    one it was run from."""
    definition = declarative_plugin(PUBLIC_ID)
    (workspace,) = definition["connections"]
    definition["connections"].append(
        {**workspace, "id": "github", "scope": "interactive", "fields": []}
    )
    _, label = definition["endpoints"]
    label.update(actors=["member", "installation"], requires={"all_of": ["workspace"]})
    label["request"]["connection"] = {"member": "github", "installation": "workspace"}
    definition["endpoints"].append(
        {
            "id": FIND_ISSUE,
            "direction": "read",
            "actors": ["installation"],
            "returns": [{"key": "number", "type": "int"}],
            "request": {
                "method": "GET",
                "url": f'"https://{API_HOST}/search/issues"',
                "query": {"q": "item.title"},
                "connection": "workspace",
            },
            "map": '{"number": response.body.items[0].number}',
        }
    )
    definition.update(
        scopes=["projects:read"],
        fields=[
            {"key": "issue", "name": {"en": "Issue"}, "kind": "number", "on": ["task"]},
            {
                "key": "links",
                "name": {"en": "Links"},
                "kind": "link",
                "list": True,
                "on": ["task"],
                "actions": ["drop"],
            },
        ],
        actions=[
            {"id": action_id, "name": {"en": action_id}, "on": ["task"], **terms}
            for action_id, terms in (
                (
                    "assign",
                    {
                        "endpoint": f"plugin.{PUBLIC_ID}.label",
                        "params": ["repo", "number"],
                        "write": '{"set": {"issue": params.number,'
                        ' "repo": params.repo}}',
                    },
                ),
                ("drop", {"write": '{"remove": {"links": [element]}}'}),
                (
                    "link",
                    {
                        "endpoint": FIND_ISSUE,
                        "write": '{"set": {"issue": result.number, "task": item.id}}',
                    },
                ),
                (
                    "tally",
                    {
                        "endpoint": FIND_ISSUE,
                        "write": '{"set": {"issue": $sum([held.issue, 1])}}',
                    },
                ),
                (
                    "unlink",
                    {
                        "write": '{"set": {"issue": null, "was": held.issue}}',
                        "requires": {"all_of": ["github"]},
                    },
                ),
                ("relink", {"write": '{"set": {"issue": 1}}', "admin_only": True}),
                ("label", {"endpoint": f"plugin.{PUBLIC_ID}.label"}),
                (
                    "garble",
                    {
                        "write": '{"target": {"kind": "task", "id": item.id},'
                        ' "set": {"issue": 1}}'
                    },
                ),
            )
        ],
    )
    return definition


@pytest.fixture
def plugin_write(monkeypatch):
    """Stand in for the plug-in's write: record each request, run ``then``,
    and answer as the plug-in kit does."""

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[httpx.Request] = []
            self.then = None

    recorder = Recorder()

    async def _fake_send(request, *, transport=None):
        recorder.calls.append(request)
        if recorder.then is not None:
            await recorder.then()
        return {"endpoint": LINK_ISSUE, "result": {}}

    monkeypatch.setattr(plugin_data_service, "_send", _fake_send)
    return recorder


async def _action_board(
    session: AsyncSession, acting_user, declarative: dict | None = None
):
    """An install placed in one initiative for its members, and tasks called
    "Broken build" each side reads differently: ``shared`` both read,
    ``hidden`` only the install, ``mine`` only the member, ``elsewhere`` in an
    initiative the install is not placed in. The install is
    :func:`_action_definition`'s container, or the ``declarative`` definition
    with the community's workspace connected."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    await create_plugin_service_registration(
        session,
        public_id=PUBLIC_ID,
        listing_uid=PLUGIN_UID,
        scope_ceiling=["projects:read"],
        **(
            {"base_url": None, "allowed_origins": [], "jwks": {}, "kind": "declarative"}
            if declarative
            else {"base_url": BASE_URL, "allowed_origins": [BASE_URL]}
        ),
    )
    config, secrets = seal_tokens(
        TokenSet(access_token="gho_community"), config={}, secrets={}
    )
    plugin = await create_guild_plugin(
        session,
        admin.guild,
        admin.user,
        definition=declarative or _action_definition(),
        listing_uid=PLUGIN_UID,
        granted_scopes=["projects:read"],
        **(
            {"config": {"workspace": config}, "secrets": {"workspace": secrets}}
            if declarative
            else {}
        ),
    )
    await route_session_to_guild(session, admin.guild.id)
    role_id = (
        await session.exec(
            select(InitiativeMember.role_id).where(
                InitiativeMember.initiative_id == admin.initiative.id,
                InitiativeMember.user_id == member.user.id,
            )
        )
    ).one()
    session.add(
        PluginPlacement(
            install_id=plugin.id, initiative_id=admin.initiative.id, role_ids=[role_id]
        )
    )
    await session.commit()

    async def task_in(initiative, owner, *, members=False, install=False):
        made = await create_project(session, initiative, owner)
        if members:
            await create_resource_grant(session, made, all_initiative_members=True)
        if install:
            await create_resource_grant(session, made, plugin_install_id=plugin.id)
        return (await create_task(session, made, title="Broken build")).id

    other = await create_initiative(session, admin.guild, admin.user, name="B")
    tasks = {
        "shared": await task_in(admin.initiative, admin.user, members=True),
        "hidden": await task_in(admin.initiative, admin.user, install=True),
        "mine": await task_in(admin.initiative, member.user),
        "elsewhere": await task_in(other, admin.user, members=True),
    }
    return admin, member, plugin, tasks


async def _kept(session: AsyncSession) -> dict:
    """The plug-ins' values, by key, each as its column keeps it."""
    rows = await session.exec(
        select(MetadataDefinition.key, MetadataValue)
        .join(MetadataValue, MetadataValue.property_id == MetadataDefinition.id)
        .where(MetadataDefinition.install_id.is_not(None))
    )
    return {
        key: next(
            held
            for held in (row.value_number, row.value_json, row.value_text)
            if held is not None
        )
        for key, row in rows
    }


def _run(actor, plugin, action: str = "link") -> str:
    return actor.g(f"/plugins/{plugin.id}/actions/{action}")


class TestActions:
    async def test_the_plugin_is_called_for_the_viewer_and_answers_fresh_values(
        self, client, acting_user, session, plugin_write
    ):
        _admin, member, plugin, tasks = await _action_board(session, acting_user)

        async def the_plugin_writes() -> None:
            await route_session_to_guild(session, member.guild.id)
            task = await session.get(Task, tasks["shared"])
            for key, kind, listed, shown, value in (
                ("issue", MetadataType.number, False, ["task"], {"value_number": 7}),
                ("etag", MetadataType.json, False, [], {"value_json": 7}),
                (
                    "pulls",
                    MetadataType.json,
                    True,
                    ["task"],
                    {"ref": "812", "value_json": {}},
                ),
            ):
                definition = await create_property_definition(
                    session,
                    None,
                    plugin=plugin,
                    key=key,
                    type=kind,
                    list=listed,
                    shown_on=shown,
                )
                await create_property_value(session, task, definition, **value)

        plugin_write.then = the_plugin_writes
        response = await client.post(
            _run(member, plugin),
            headers=member.headers,
            json={"entity_type": "task", "entity_id": tasks["shared"]},
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"values": {"issue": 7, "pulls": [{"ref": "812"}]}}
        (call,) = plugin_write.calls
        assert json.loads(call.content)["endpoint"] == LINK_ISSUE
        claims = jwt.decode(
            call.headers["Authorization"].removeprefix("Bearer "),
            options={"verify_signature": False},
            algorithms=["EdDSA"],
        )
        assert claims["endpoint_id"] == LINK_ISSUE
        assert claims["subject"] == {"type": "task", "id": tasks["shared"]}
        assert claims["viewer"] == await ensure_plugin_ref(
            guild_id=member.guild.id,
            public_id=plugin.definition["service"]["public_id"],
            user_id=member.user.id,
        )
        assert "act" not in claims and "member" not in claims

    async def test_an_unmet_connection_or_a_frozen_community_runs_nothing(
        self, client, acting_user, session, plugin_write
    ):
        admin, member, plugin, tasks = await _action_board(session, acting_user)
        token = {"key": "token", "type": "secret", "required": True}
        plugin.definition = {
            **plugin.definition,
            "connections": [{"id": "admin", "scope": "static", "fields": [token]}],
            "actions": [
                {**plugin.definition["actions"][0], "requires": {"all_of": ["admin"]}}
            ],
        }
        session.add(plugin)
        await session.commit()
        body = {"entity_type": "task", "entity_id": tasks["shared"]}

        unmet = await client.post(
            _run(member, plugin), headers=member.headers, json=body
        )
        guild = await session.get(Guild, admin.guild.id)
        assert guild is not None
        guild.status = CommunityStatus.read_only.value
        session.add(guild)
        await session.commit()
        frozen = await client.post(
            _run(member, plugin), headers=member.headers, json=body
        )

        assert unmet.status_code == 409, unmet.text
        assert unmet.json()["detail"] == PluginDataMessages.NEEDS_CONFIGURATION
        assert frozen.status_code == 403, frozen.text
        assert frozen.json()["detail"] == PluginDataMessages.ACTION_NOT_OFFERED
        assert plugin_write.calls == []

    @pytest.mark.parametrize(
        ("who", "task", "body", "status_code", "detail"),
        [
            ("member", "shared", {"action": "unlink"}, 404, "ACTION_NOT_FOUND"),
            (
                "member",
                "shared",
                {"entity_type": "queue_item"},
                404,
                "ACTION_NOT_FOUND",
            ),
            ("member", "hidden", {}, 404, None),
            ("admin", "elsewhere", {}, 403, "ACTION_NOT_OFFERED"),
            ("manager", "shared", {}, 403, "ACTION_NOT_OFFERED"),
            ("member", "shared", {"action": "relink"}, 403, "ACTION_NOT_OFFERED"),
            ("member", "mine", {}, 403, "ACTION_NOT_OFFERED"),
        ],
        ids=[
            "an undeclared action",
            "an item kind the action is not on",
            "an item the viewer cannot read",
            "an initiative the install is not placed in",
            "a role the placement does not allow",
            "an action for the community's admins alone",
            "an item the install cannot read",
        ],
    )
    async def test_the_connection_is_made_only_where_it_may_be(
        self,
        client,
        acting_user,
        session,
        plugin_write,
        who,
        task,
        body,
        status_code,
        detail,
    ):
        admin, member, plugin, tasks = await _action_board(session, acting_user)
        actors = {"admin": admin, "member": member}
        actors["manager"] = await acting_user(
            guild_role=CommunityRole.member,
            guild=admin.guild,
            initiative=admin.initiative,
            initiative_role="project_manager",
        )
        actor = actors[who]

        response = await client.post(
            _run(actor, plugin, body.get("action", "link")),
            headers=actor.headers,
            json={
                "entity_type": body.get("entity_type", "task"),
                "entity_id": tasks[task],
            },
        )

        assert response.status_code == status_code, response.text
        if detail is not None:
            assert response.json()["detail"] == getattr(PluginDataMessages, detail)
        assert plugin_write.calls == []

    async def test_a_declarative_action_keeps_what_the_vendor_answers(
        self, client, acting_user, session, monkeypatch
    ):
        """Initiative makes the call on the credential the endpoint's actors
        say, its request reading the item: the community's for a read the
        installation makes, and for a write made as the reader, their own
        once they have connected it, and the community's, as the
        installation, before. What the write makes of the answer is kept as
        the install. An action naming no endpoint calls nothing and reads
        what the install holds on the item."""
        vendor = FakeVendor()
        vendor.install(monkeypatch)
        vendor.api_answers = [
            {"body": {"items": [{"number": 12}]}},
            {"body": {"number": 12}},
            {"body": {"number": 12}},
        ]
        _admin, member, plugin, tasks = await _action_board(
            session, acting_user, _declarative_action_definition()
        )
        body = {"entity_type": "task", "entity_id": tasks["shared"]}

        linked = await client.post(
            _run(member, plugin), headers=member.headers, json=body
        )
        unconnected = await client.post(
            _run(member, plugin, "label"), headers=member.headers, json=body
        )
        await _connect(session, plugin=plugin, user=member.user, ref="cr_member")
        labelled = await client.post(
            _run(member, plugin, "label"), headers=member.headers, json=body
        )
        unlinked = await client.post(
            _run(member, plugin, "unlink"), headers=member.headers, json=body
        )

        assert linked.status_code == 200, linked.text
        assert linked.json() == {"values": {"issue": 12}}
        assert unconnected.status_code == 200, unconnected.text
        assert labelled.status_code == 200, labelled.text
        assert unlinked.status_code == 200, unlinked.text
        assert unlinked.json() == {"values": {}}
        found, by_community, labelling = vendor.api_requests
        assert found["url"] == f"https://{API_HOST}/search/issues?q=Broken+build"
        assert found["headers"]["authorization"] == "Bearer gho_community"
        assert by_community["headers"]["authorization"] == "Bearer gho_community"
        assert labelling["method"] == "PUT"
        assert labelling["headers"]["authorization"] == "Bearer tok"
        await route_session_to_guild(session, member.guild.id)
        kept = await _kept(session)
        assert kept == {"task": tasks["shared"], "was": 12}

    @pytest.mark.parametrize(
        ("unplace", "status_code", "kept"),
        [(False, 200, {"issue": 6}), (True, 502, {})],
        ids=[
            "another run changed the value meanwhile",
            "the install was taken out of the initiative meanwhile",
        ],
    )
    async def test_a_declarative_action_changes_the_values_once_answered(
        self, client, acting_user, session, monkeypatch, unplace, status_code, kept
    ):
        """``held`` is what the install holds on the item once the vendor has
        answered, so a change made while it worked is built on; an item the
        install no longer reads by then fails the action, which keeps
        nothing."""
        vendor = FakeVendor()
        vendor.install(monkeypatch)
        vendor.api_answers = [{"body": {"items": [{"number": 12}]}}]
        _admin, member, plugin, tasks = await _action_board(
            session, acting_user, _declarative_action_definition()
        )

        async def answer(request: httpx.Request) -> httpx.Response:
            await route_session_to_guild(session, member.guild.id)
            if unplace:
                await session.exec(
                    delete(PluginPlacement).where(
                        PluginPlacement.install_id == plugin.id
                    )
                )
            else:
                await create_property_value(
                    session,
                    await session.get(Task, tasks["shared"]),
                    await create_property_definition(
                        session,
                        None,
                        plugin=plugin,
                        key="issue",
                        type=MetadataType.number,
                        shown_on=["task"],
                    ),
                    value_number=5,
                )
            await session.commit()
            return vendor.handle(request)

        monkeypatch.setattr(
            plugin_connection_flows, "http_transport", httpx.MockTransport(answer)
        )
        response = await client.post(
            _run(member, plugin, "tally"),
            headers=member.headers,
            json={"entity_type": "task", "entity_id": tasks["shared"]},
        )

        assert response.status_code == status_code, response.text
        await route_session_to_guild(session, member.guild.id)
        assert await _kept(session) == kept

    @pytest.mark.parametrize(
        ("who", "task", "action", "status_code", "detail"),
        [
            ("member", "shared", "relink", 403, "ACTION_NOT_OFFERED"),
            ("admin", "elsewhere", "link", 403, "ACTION_NOT_OFFERED"),
            ("member", "shared", "unlink", 409, "CONNECTION_REQUIRED"),
            ("member", "shared", "garble", 502, "SERVICE_UNAVAILABLE"),
        ],
        ids=[
            "an action for the community's admins alone",
            "an initiative the install is not placed in",
            "an action needing the reader's own account, which they never connected",
            "a write answering what is not a change",
        ],
    )
    async def test_a_declarative_action_changes_nothing_where_it_may_not_run(
        self,
        client,
        acting_user,
        session,
        monkeypatch,
        who,
        task,
        action,
        status_code,
        detail,
    ):
        """The vendor is not called and the install keeps nothing."""
        vendor = FakeVendor()
        vendor.install(monkeypatch)
        admin, member, plugin, tasks = await _action_board(
            session, acting_user, _declarative_action_definition()
        )
        actor = {"admin": admin, "member": member}[who]

        response = await client.post(
            _run(actor, plugin, action),
            headers=actor.headers,
            json={"entity_type": "task", "entity_id": tasks[task]},
        )

        assert response.status_code == status_code, response.text
        assert response.json()["detail"] == getattr(PluginDataMessages, detail)
        assert vendor.api_requests == []
        await route_session_to_guild(session, admin.guild.id)
        assert await _kept(session) == {}

    async def test_a_declarative_action_is_sent_what_the_reader_answered(
        self, client, acting_user, session, monkeypatch
    ):
        """The endpoint's call is made with the reader's answers to the
        parameters the action asks for, and its ``write`` reads them in their
        declared types."""
        vendor = FakeVendor()
        vendor.install(monkeypatch)
        vendor.api_answers = [{"body": {"number": 7}}]
        _admin, member, plugin, tasks = await _action_board(
            session, acting_user, _declarative_action_definition()
        )

        response = await client.post(
            _run(member, plugin, "assign"),
            headers=member.headers,
            json={
                "entity_type": "task",
                "entity_id": tasks["shared"],
                "params": {"repo": "acme/widgets", "number": 7},
            },
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"values": {"issue": 7}}
        (labelled,) = vendor.api_requests
        assert labelled["url"] == (
            f"https://{API_HOST}/repos/acme/widgets/issues/7/labels"
        )
        await route_session_to_guild(session, member.guild.id)
        assert await _kept(session) == {"issue": 7, "repo": "acme/widgets"}

    async def test_a_declarative_action_run_from_an_element_reads_it(
        self, client, acting_user, session, monkeypatch
    ):
        """An action a list field offers on its elements reads the ``ref`` of
        the one it was run from, and the values answered are the list's rest."""
        vendor = FakeVendor()
        vendor.install(monkeypatch)
        _admin, member, plugin, tasks = await _action_board(
            session, acting_user, _declarative_action_definition()
        )
        await route_session_to_guild(session, member.guild.id)
        links = await create_property_definition(
            session,
            None,
            plugin=plugin,
            key="links",
            type=MetadataType.link,
            list=True,
            shown_on=["task"],
        )
        for ref in ("a", "b"):
            await create_property_value(
                session,
                await session.get(Task, tasks["shared"]),
                links,
                ref=ref,
                value_json={"url": f"https://x.example/{ref}"},
                value_text=f"https://x.example/{ref}",
            )

        response = await client.post(
            _run(member, plugin, "drop"),
            headers=member.headers,
            json={"entity_type": "task", "entity_id": tasks["shared"], "element": "a"},
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "values": {"links": [{"ref": "b", "url": "https://x.example/b"}]}
        }
        assert vendor.api_requests == []

    @pytest.mark.parametrize(
        ("action", "given"),
        [
            ("assign", {"params": {"repo": "acme/widgets", "colour": "red"}}),
            ("assign", {"params": {"repo": "acme/widgets", "number": "seven"}}),
            ("link", {"params": {"repo": "acme/widgets"}}),
            ("link", {"element": "a"}),
            ("drop", {"element": ""}),
        ],
        ids=[
            "an answer the action did not ask for",
            "an answer not of the parameter's type",
            "answers for an action that asks nothing",
            "an element for an action no list offers",
            "an element that is not a ref",
        ],
    )
    async def test_what_an_action_is_given_is_held_to_what_it_asks(
        self, client, acting_user, session, monkeypatch, action, given
    ):
        """Refused before anything is called or kept."""
        vendor = FakeVendor()
        vendor.install(monkeypatch)
        _admin, member, plugin, tasks = await _action_board(
            session, acting_user, _declarative_action_definition()
        )

        response = await client.post(
            _run(member, plugin, action),
            headers=member.headers,
            json={"entity_type": "task", "entity_id": tasks["shared"], **given},
        )

        assert response.status_code == 400, response.text
        assert response.json()["detail"] == PluginDataMessages.INVALID_PARAMS
        assert vendor.api_requests == []
        await route_session_to_guild(session, member.guild.id)
        assert await _kept(session) == {}
