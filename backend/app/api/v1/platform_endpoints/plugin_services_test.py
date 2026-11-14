"""Endpoint tests for the plug-in service registry and its publishers.

Only the owner tier reaches this surface. It writes a registration's
deployment facts; its plug-in facts come from the plug-in's listing. A registration is
shown whole, since none of it is secret.
"""

import copy
import ipaddress
import json
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from httpx2 import AsyncClient
from jwt.algorithms import OKPAlgorithm
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.messages import AuthMessages, PluginServiceMessages
from app.models.platform.plugin_install import PluginInstall
from app.models.platform.plugin_service_registration import (
    LISTING_STATED_FIELDS,
    PluginServiceRegistration,
)
from app.models.platform.user import UserRole
from app.services import safe_http
from app.services.marketplace import plugin_installs, plugin_keys, vendor_setup
from app.services.marketplace.vendor_values import load_vendor_values
from app.services.webhook_target_url import ValidatedTarget
from app.testing import emitted
from app.testing.factories import (
    create_guild,
    create_guild_plugin,
    create_marketplace_listing,
    create_plugin_service_registration,
    create_user,
    get_auth_headers,
)
from app.testing.fake_vendor import declarative_github

BASE = "/api/v1/plugin-services/"
PUBLISHERS = "/api/v1/plugin-publishers/"
PLUGIN_URL = "http://127.0.0.1:9100"
LISTING_UID = "K7M2QX8N4TVB9C"
NEW = {"public_id": "acme.widgets", "base_url": PLUGIN_URL}


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setattr(
        settings,
        "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM",
        "-----BEGIN PRIVATE KEY-----",
    )


async def _owner_headers(session: AsyncSession) -> dict[str, str]:
    owner = await create_user(session, role=UserRole.owner)
    return get_auth_headers(owner)


async def _seed(session: AsyncSession, **overrides) -> PluginServiceRegistration:
    return await create_plugin_service_registration(
        session,
        public_id=overrides.pop("public_id", "acme.widgets"),
        base_url=overrides.pop("base_url", PLUGIN_URL),
        allowed_origins=overrides.pop("allowed_origins", [PLUGIN_URL]),
        listing_uid=overrides.pop("listing_uid", LISTING_UID),
        **overrides,
    )


async def _listed(client: AsyncClient, headers: dict[str, str], row_id: int) -> dict:
    """One registration as the operator's list shows it."""
    response = await client.get(BASE, headers=headers)
    assert response.status_code == 200, response.text
    (entry,) = [entry for entry in response.json() if entry["id"] == row_id]
    return entry


# --- capability gating -------------------------------------------------------


@pytest.mark.parametrize(
    "role", [UserRole.member, UserRole.support, UserRole.moderator, UserRole.operator]
)
async def test_non_owner_tiers_are_refused(
    client: AsyncClient, session: AsyncSession, role: UserRole
):
    """``plugins.manage`` is owner-only: wiring a plug-in service is deployment
    configuration, so no lower tier reaches any verb."""
    user = await create_user(session, role=role)
    headers = get_auth_headers(user)
    row = await _seed(session)

    assert (await client.get(BASE, headers=headers)).status_code == 403
    create = await client.post(BASE, headers=headers, json=NEW)
    assert create.status_code == 403
    assert create.json()["detail"] == AuthMessages.INSUFFICIENT_PRIVILEGES
    assert (
        await client.patch(f"{BASE}{row.id}", headers=headers, json={"enabled": False})
    ).status_code == 403
    assert (await client.delete(f"{BASE}{row.id}", headers=headers)).status_code == 403
    assert (
        await client.get(f"{BASE}{row.id}/connect", headers=headers)
    ).status_code == 403
    assert (
        await client.post(
            f"{BASE}{row.id}/connect",
            headers=headers,
            json={"keys": [{"kid": "k", "fingerprint": "x"}]},
        )
    ).status_code == 403
    assert (
        await client.post(f"{BASE}{row.id}/vendor-setup", headers=headers, json={})
    ).status_code == 403
    assert (
        await client.post(
            f"{BASE}{row.id}/vendor-setup/complete",
            headers=headers,
            json={"code": "c", "state": "s"},
        )
    ).status_code == 403

    assert (await client.get(PUBLISHERS, headers=headers)).status_code == 403
    assert (
        await client.post(
            PUBLISHERS, headers=headers, json={"prefix": "x", "display_name": "X"}
        )
    ).status_code == 403
    assert (
        await client.patch(
            f"{PUBLISHERS}{row.publisher_id}", headers=headers, json={"enabled": False}
        )
    ).status_code == 403


async def test_anonymous_is_refused(client: AsyncClient):
    assert (await client.get(BASE)).status_code == 401


# --- what a registration is ---------------------------------------------------


async def test_owner_creates_a_registration_as_stated(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)

    response = await client.post(BASE, headers=headers, json=NEW)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["public_id"] == "acme.widgets"
    # Its plug-in facts wait for its listing.
    assert (body["listing_uid"], body["scope_ceiling"]) == (None, [])
    assert body["publisher_prefix"] == "acme"
    assert body["publisher_enabled"] is True
    # No key set yet, so it is not live.
    assert body["live"] is False
    for gone in ("status", "has_secret", "manifest_hash", "last_verified_at"):
        assert gone not in body


async def test_owner_lists_registrations_with_their_publisher(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    await _seed(session, mandatory=True)

    response = await client.get(BASE, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    entry = body[0]
    assert entry["public_id"] == "acme.widgets"
    assert "grants" not in entry
    assert entry["mandatory"] is True
    assert entry["publisher_prefix"] == "acme"
    assert entry["live"] is True
    assert entry["jwks"]["keys"]


@pytest.mark.parametrize("stated", LISTING_STATED_FIELDS)
async def test_a_request_takes_deployment_facts_only(
    client: AsyncClient, session: AsyncSession, stated: str
):
    headers = await _owner_headers(session)
    row = await _seed(session, scope_ceiling=["projects:read"])

    created = await client.post(BASE, headers=headers, json={**NEW, stated: None})
    edited = await client.patch(
        f"{BASE}{row.id}", headers=headers, json={stated: ["projects:write"]}
    )

    for response in (created, edited):
        assert response.status_code == 422, response.text
        assert PluginServiceMessages.STATED_BY_LISTING in response.text
    await session.refresh(row)
    assert (row.listing_uid, row.scope_ceiling) == (LISTING_UID, ["projects:read"])


async def test_the_key_set_address_round_trips(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session, base_url="https://plugin.example.com", jwks={})

    set_it = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"jwks_uri": "https://plugin.example.com/jwks.json", "jwks": {}},
    )
    assert set_it.status_code == 200, set_it.text
    assert set_it.json()["jwks_uri"] == "https://plugin.example.com/jwks.json"
    assert set_it.json()["jwks"] is None
    assert set_it.json()["live"] is True

    elsewhere = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"jwks_uri": "https://keys.example.net/jwks.json"},
    )
    assert elsewhere.status_code == 400
    assert elsewhere.json()["detail"] == PluginServiceMessages.INVALID_JWKS_URI


#: The plug-in's signing key, and the one it moves to: Ed25519, the one kind a
#: plug-in may sign with.
_PLUGIN_KEY = ed25519.Ed25519PrivateKey.generate()
_MOVED_KEY = ed25519.Ed25519PrivateKey.generate()


def _key_set(key: ed25519.Ed25519PrivateKey, kid: str) -> dict:
    """A key set publishing ``key`` under ``kid``."""
    entry = json.loads(OKPAlgorithm.to_jwk(key.public_key()))
    entry["kid"] = kid
    return {"keys": [entry]}


async def test_connect_pins_the_key_set_the_operator_confirmed(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, capfd
):
    owner = await acting_user()
    row = await _seed(session, jwks={})
    served = [_key_set(_PLUGIN_KEY, kid="acme.widgets-1")]
    fetched: list[str] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        fetched.append(str(request.url))
        return httpx2.Response(200, json=served[0])

    real_request = plugin_keys.request_public_target

    async def through_the_plugin(*args, **kwargs):
        return await real_request(
            *args, **{**kwargs, "transport": httpx2.MockTransport(answer)}
        )

    monkeypatch.setattr(plugin_keys, "request_public_target", through_the_plugin)

    shown = await client.get(f"{BASE}{row.id}/connect", headers=owner.headers)
    assert shown.status_code == 200, shown.text
    (confirmed,) = shown.json()
    assert confirmed["kid"] == "acme.widgets-1"
    assert fetched == [f"{PLUGIN_URL}/.well-known/jwks.json"]
    assert (await _listed(client, owner.headers, row.id))["jwks"] is None

    capfd.readouterr()
    pinned = await client.post(
        f"{BASE}{row.id}/connect",
        headers=owner.headers,
        json={"keys": [confirmed]},
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["jwks"] == served[0]
    assert pinned.json()["live"] is True
    (record,) = emitted(capfd, AuditEventType.PLUGIN_SERVICE_UPDATED)
    assert record["actor_user_id"] == owner.user.id
    assert record["detail"]["changed"] == ["jwks"]

    # The plug-in's set moves: nothing follows it until the operator connects again.
    served[0] = _key_set(_MOVED_KEY, kid="acme.widgets-1")
    stale = await client.post(
        f"{BASE}{row.id}/connect",
        headers=owner.headers,
        json={"keys": [confirmed]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == PluginServiceMessages.KEYS_CHANGED
    listed = await _listed(client, owner.headers, row.id)
    assert listed["jwks"] == _key_set(_PLUGIN_KEY, kid="acme.widgets-1")


# --- operator-conferred fields ------------------------------------------------


async def test_patch_sets_the_operator_only_fields(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"mandatory": True, "operations_only": True, "enabled": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mandatory"] is True
    assert body["operations_only"] is True
    assert body["enabled"] is False


async def test_sharing_is_turned_off_once_each_installation_has_one_community(
    client: AsyncClient, session: AsyncSession
):
    """Two communities hold installation 42. While sharing is off the second
    is indexed without it; turning sharing on gives it the route, turning it
    off is refused while both hold it, and goes through once one does."""
    headers = await _owner_headers(session)
    row = await _seed(session)
    user = await create_user(session)
    installs = []
    for _ in range(2):
        guild = await create_guild(session, creator=user)
        plugin = await create_guild_plugin(
            session,
            guild,
            user,
            definition=declarative_github(row.public_id),
            listing_uid=LISTING_UID,
            config={"workspace": {"owner": "acme", "installation_id": "42"}},
        )
        installs.append((guild.id, plugin))
    (first, _), (second, second_plugin) = installs

    async def indexed() -> dict[int, tuple]:
        session.expunge_all()
        rows = await session.exec(
            select(PluginInstall).where(PluginInstall.listing_uid == LISTING_UID)
        )
        return {item.guild_id: (item.hook_route, item.exclusive) for item in rows}

    async def share(on: bool) -> httpx2.Response:
        return await client.patch(
            f"{BASE}{row.id}", headers=headers, json={"shared_routes": on}
        )

    assert await indexed() == {first: ("42", True), second: (None, True)}

    shared = await share(True)
    assert shared.status_code == 200, shared.text
    assert shared.json()["shared_routes"] is True
    await plugin_installs.record(second, second_plugin)
    assert await indexed() == {first: ("42", False), second: ("42", False)}

    refused = await share(False)
    assert refused.status_code == 409
    assert refused.json()["detail"] == PluginServiceMessages.SHARED_ROUTES_IN_USE
    assert (await _listed(client, headers, row.id))["shared_routes"] is True
    assert await indexed() == {first: ("42", False), second: ("42", False)}

    await plugin_installs.forget(second, second_plugin.id)
    unshared = await share(False)
    assert unshared.status_code == 200, unshared.text
    assert unshared.json()["shared_routes"] is False
    assert await indexed() == {first: ("42", True)}


async def test_the_browser_address_round_trips_and_clears(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)

    set_it = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"page_origin": "https://plugin.example.com"},
    )
    assert set_it.status_code == 200, set_it.text
    assert set_it.json()["page_origin"] == "https://plugin.example.com"

    cleared = await client.patch(
        f"{BASE}{row.id}", headers=headers, json={"page_origin": ""}
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["page_origin"] is None


@pytest.mark.parametrize(
    ("case", "body", "detail"),
    [
        (
            "a malformed base url",
            {**NEW, "base_url": "ftp://plugin.example.com"},
            PluginServiceMessages.INVALID_BASE_URL,
        ),
        # Its own code, so an operator is told which of the two addresses the
        # registry would not take.
        (
            "a malformed page origin",
            {**NEW, "page_origin": "ftp://plugin.example.com"},
            PluginServiceMessages.INVALID_PAGE_ORIGIN,
        ),
        (
            "an origin carrying a path",
            {**NEW, "allowed_origins": ["https://plugin.example.com/embed"]},
            PluginServiceMessages.INVALID_ORIGIN,
        ),
    ],
    ids=lambda v: v if isinstance(v, str) and " " in v else "",
)
async def test_create_refuses_a_registration_it_cannot_store(
    client: AsyncClient, session: AsyncSession, case: str, body: dict, detail: str
):
    """Each rejection names the field the operator has to fix."""
    headers = await _owner_headers(session)

    response = await client.post(BASE, headers=headers, json=body)

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == detail


# --- fail-closed without the platform keypair ---------------------------------


async def test_create_fails_closed_without_a_signing_key(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The plug-in platform keypair is required and has no fallback, so the request
    is refused with a code an operator can act on."""
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
    headers = await _owner_headers(session)

    response = await client.post(BASE, headers=headers, json=NEW)

    assert response.status_code == 503
    assert response.json()["detail"] == PluginServiceMessages.SIGNING_NOT_CONFIGURED


# --- delete -------------------------------------------------------------------


async def test_owner_deletes_a_registration(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)
    row = await _seed(session)

    assert (await client.delete(f"{BASE}{row.id}", headers=headers)).status_code == 204
    assert (await client.get(BASE, headers=headers)).json() == []


async def test_missing_registration_is_a_404(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)

    response = await client.patch(
        f"{BASE}999999", headers=headers, json={"enabled": False}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == PluginServiceMessages.NOT_FOUND


# --- publishers ---------------------------------------------------------------


async def test_owner_adds_and_lists_a_publisher(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)

    created = await client.post(
        PUBLISHERS,
        headers=headers,
        json={"prefix": "Private-Plugins", "display_name": "Our own plug-ins"},
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["prefix"] == "private-plugins"
    assert body["display_name"] == "Our own plug-ins"
    assert body["verified"] is False
    assert body["enabled"] is True

    listed = await client.get(PUBLISHERS, headers=headers)
    assert "private-plugins" in {entry["prefix"] for entry in listed.json()}

    again = await client.post(
        PUBLISHERS,
        headers=headers,
        json={"prefix": "private-plugins", "display_name": "Twice"},
    )
    assert again.status_code == 409
    assert again.json()["detail"] == PluginServiceMessages.DUPLICATE_PUBLISHER


@pytest.mark.parametrize("prefix", ["", "has.dot", "has space", "x" * 121])
async def test_a_prefix_is_one_segment_of_a_plugin_id(
    client: AsyncClient, session: AsyncSession, prefix: str
):
    headers = await _owner_headers(session)

    response = await client.post(
        PUBLISHERS, headers=headers, json={"prefix": prefix, "display_name": "X"}
    )

    assert response.status_code in (400, 422), response.text


async def test_switching_a_publisher_off_takes_its_plugins_out_of_service(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    row = await _seed(session)
    assert (await _listed(client, headers, row.id))["live"]

    off = await client.patch(
        f"{PUBLISHERS}{row.publisher_id}",
        headers=headers,
        json={"enabled": False, "display_name": "Acme, paused"},
    )

    assert off.status_code == 200, off.text
    assert off.json()["enabled"] is False
    assert off.json()["display_name"] == "Acme, paused"
    read = await _listed(client, headers, row.id)
    assert read["enabled"] is True
    assert read["publisher_enabled"] is False
    assert read["live"] is False


async def test_a_missing_publisher_is_a_404(client: AsyncClient, session: AsyncSession):
    headers = await _owner_headers(session)

    response = await client.patch(
        f"{PUBLISHERS}999999", headers=headers, json={"enabled": False}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == PluginServiceMessages.PUBLISHER_NOT_FOUND


# --- vendor values -------------------------------------------------------------


VENDOR_DEFINITION = {
    "plugin_kind": "service",
    "service": {"public_id": "acme.widgets", "protocol": 1},
    "features": [],
    "vendor": {
        "label": {"en": "Widget client"},
        "fields": [
            {
                "key": "client_id",
                "type": "string",
                "required": True,
                "label": {"en": "Client id"},
            },
            {
                "key": "client_secret",
                "type": "secret",
                "required": True,
                "label": {"en": "Client secret"},
            },
        ],
    },
}


async def _vendor_listing(session: AsyncSession) -> None:
    await create_marketplace_listing(
        session,
        uid=LISTING_UID,
        public_id="acme.widgets",
        kind="plugin",
        definition=VENDOR_DEFINITION,
    )


async def test_the_form_shows_the_fields_the_listing_asks_for(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    body = await _listed(client, headers, row.id)

    assert [field["key"] for field in body["vendor_fields"]] == [
        "client_id",
        "client_secret",
    ]
    assert body["vendor_fields"][1]["type"] == "secret"
    assert body["vendor_set"] == []
    assert body["connection_callback_url"] == (
        f"{settings.APP_URL.rstrip('/')}/api/v1/plugin-connections/callback"
    )
    assert body["connection_setup_url"] == (
        f"{settings.APP_URL.rstrip('/')}/api/v1/plugin-connections/setup"
    )
    assert body["webhook_url"] == (
        f"{settings.APP_URL.rstrip('/')}/api/v1/plugin-hooks/acme.widgets"
    )


async def test_a_secret_is_written_and_shown_only_as_set(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"client_id": "widget-app", "client_secret": "s3cr3t"}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vendor_values"] == {"client_id": "widget-app"}
    assert body["vendor_set"] == ["client_id", "client_secret"]
    assert body["vendor_ready"] is True
    assert body["live"] is True
    assert "s3cr3t" not in response.text

    # Left out, a secret is kept; sent empty, it is cleared.
    kept = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"client_id": "widget-app-2"}},
    )
    assert kept.json()["vendor_set"] == ["client_id", "client_secret"]
    cleared = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"client_secret": ""}},
    )
    assert cleared.json()["vendor_set"] == ["client_id"]


async def test_a_registration_is_not_live_until_its_required_values_are_set(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    body = (
        await client.patch(
            f"{BASE}{row.id}",
            headers=headers,
            json={"vendor_values": {"client_id": "widget-app"}},
        )
    ).json()

    assert body["vendor_ready"] is False
    assert body["live"] is False


async def test_a_value_the_listing_does_not_ask_for_is_refused(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    response = await client.patch(
        f"{BASE}{row.id}",
        headers=headers,
        json={"vendor_values": {"webhook_secret": "x"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == PluginServiceMessages.UNKNOWN_VENDOR_FIELD


# --- the compose snippet ------------------------------------------------------


async def test_the_form_shows_the_compose_service_filled_in(
    client: AsyncClient, session: AsyncSession
):
    headers = await _owner_headers(session)
    image = "ghcr.io/acme/widgets@sha256:" + "0" * 64
    row = await _seed(
        session,
        image_digest=image,
        compose={
            "service": "widgets:\n  image: ${IMAGE}\n"
            "  environment:\n    INITIATIVE_URL: ${INITIATIVE_URL}\n",
            "base_url": "http://widgets:8080",
        },
    )

    body = await _listed(client, headers, row.id)

    assert body["compose_service"] == (
        f"widgets:\n  image: {image}\n"
        f"  environment:\n    INITIATIVE_URL: {settings.APP_URL.rstrip('/')}\n"
    )
    assert body["compose_base_url"] == "http://widgets:8080"


# --- the vendor's own setup ------------------------------------------------------


GITHUB_APP = {
    "name": "Widgets",
    "url": "https://widgets.example.com",
    "default_permissions": {"issues": "write"},
    "default_events": ["issues"],
}
GITHUB_DEFINITION: dict[str, Any] = {
    **VENDOR_DEFINITION,
    "vendor": {
        "fields": [
            {"key": key, "type": kind, "required": True, "label": {"en": key}}
            for key, kind in (
                ("app_id", "string"),
                ("client_id", "string"),
                ("client_secret", "secret"),
                ("private_key", "secret"),
                ("webhook_secret", "secret"),
            )
        ],
        "setup": {
            "kind": "github_app_manifest",
            "app": GITHUB_APP,
            "values": {
                "app_id": "id",
                "client_id": "client_id",
                "client_secret": "client_secret",
                "private_key": "pem",
                "webhook_secret": "webhook_secret",
            },
        },
    },
}
CONVERSION = {
    "id": 4242,
    "slug": "widgets",
    "client_id": "Iv1.widgets",
    "client_secret": "client-secret",
    "pem": "-----BEGIN RSA PRIVATE KEY-----\nkey\n-----END RSA PRIVATE KEY-----\n",
    "webhook_secret": "hook-secret",
}


def _github(
    monkeypatch, *, status: int = 201, answer: dict = CONVERSION
) -> list[httpx2.Request]:
    """GitHub answering a manifest conversion; the requests it was sent."""
    sent: list[httpx2.Request] = []

    async def resolve(url: str, *, allow_private: bool = False) -> ValidatedTarget:
        return ValidatedTarget(
            hostname=httpx2.URL(url).host,
            addresses=(ipaddress.ip_address("140.82.112.6"),),
        )

    def handle(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(status, json=answer if status < 400 else {})

    monkeypatch.setattr(safe_http, "resolve_validated_target_async", resolve)
    monkeypatch.setattr(vendor_setup, "http_transport", httpx2.MockTransport(handle))
    return sent


async def _github_registration(session: AsyncSession) -> PluginServiceRegistration:
    await create_marketplace_listing(
        session,
        uid=LISTING_UID,
        public_id="acme.widgets",
        kind="plugin",
        definition=GITHUB_DEFINITION,
    )
    return await _seed(session)


async def _start(client: AsyncClient, headers, row_id: int, **body) -> dict:
    response = await client.post(
        f"{BASE}{row_id}/vendor-setup", headers=headers, json=body
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_github_setup_carries_initiatives_own_addresses(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user()
    row = await _github_registration(session)

    assert (await _listed(client, a.headers, row.id))["vendor_setup"] == (
        "github_app_manifest"
    )
    started = await _start(client, a.headers, row.id)

    app_url = settings.APP_URL.rstrip("/")
    assert started["action"] == "https://github.com/settings/apps/new"
    assert started["state"]
    assert json.loads(started["manifest"]) == {
        **GITHUB_APP,
        "public": False,
        "redirect_url": (
            f"{app_url}/settings/platform/integrations/vendor-setup/{row.id}"
        ),
        "callback_urls": [f"{app_url}/api/v1/plugin-connections/callback"],
        "setup_url": f"{app_url}/api/v1/plugin-connections/setup",
        "hook_attributes": {
            "url": f"{app_url}/api/v1/plugin-hooks/acme.widgets",
            "active": True,
        },
    }
    owned = await _start(client, a.headers, row.id, organization="acme-org")
    assert owned["action"] == (
        "https://github.com/organizations/acme-org/settings/apps/new"
    )
    refused = await client.post(
        f"{BASE}{row.id}/vendor-setup",
        headers=a.headers,
        json={"organization": "acme/org"},
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == (
        PluginServiceMessages.VENDOR_SETUP_INVALID_ORGANIZATION
    )


async def test_a_plugin_with_no_setup_offers_none(
    client: AsyncClient, session: AsyncSession
):
    await _vendor_listing(session)
    headers = await _owner_headers(session)
    row = await _seed(session)

    assert (await _listed(client, headers, row.id))["vendor_setup"] is None
    response = await client.post(
        f"{BASE}{row.id}/vendor-setup", headers=headers, json={}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == PluginServiceMessages.VENDOR_SETUP_UNAVAILABLE


async def test_completing_the_github_setup_writes_the_vendor_values(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, capfd
):
    sent = _github(monkeypatch)
    a = await acting_user()
    row = await _github_registration(session)
    started = await _start(client, a.headers, row.id)
    capfd.readouterr()

    response = await client.post(
        f"{BASE}{row.id}/vendor-setup/complete",
        headers=a.headers,
        json={"code": "abc123", "state": started["state"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["vendor_values"] == {"app_id": "4242", "client_id": "Iv1.widgets"}
    assert body["vendor_set"] == [
        "app_id",
        "client_id",
        "client_secret",
        "private_key",
        "webhook_secret",
    ]
    assert body["vendor_ready"] is True
    assert "client-secret" not in response.text
    (request,) = sent
    assert request.method == "POST"
    assert (request.headers["host"], request.url.path) == (
        "api.github.com",
        "/plugin-manifests/abc123/conversions",
    )
    assert await load_vendor_values("acme.widgets") == {
        "app_id": "4242",
        "client_id": "Iv1.widgets",
        "client_secret": "client-secret",
        "private_key": CONVERSION["pem"].strip(),
        "webhook_secret": "hook-secret",
    }
    (record,) = emitted(capfd, AuditEventType.PLUGIN_SERVICE_UPDATED)
    assert record["actor_user_id"] == a.user.id
    assert record["detail"]["vendor_values"] == [
        "app_id",
        "client_id",
        "client_secret",
        "private_key",
        "webhook_secret",
    ]

    again = await client.post(
        f"{BASE}{row.id}/vendor-setup/complete",
        headers=a.headers,
        json={"code": "abc123", "state": started["state"]},
    )
    assert again.status_code == 400
    assert again.json()["detail"] == PluginServiceMessages.VENDOR_SETUP_EXPIRED
    assert len(sent) == 1


async def _complete(client: AsyncClient, headers, row_id: int, state: str):
    return await client.post(
        f"{BASE}{row_id}/vendor-setup/complete",
        headers=headers,
        json={"code": "abc123", "state": state},
    )


@pytest.mark.parametrize("whose", ["another_owner", "another_plugin"])
async def test_a_setup_is_finished_only_by_who_started_it_for_that_plugin(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch, whose
):
    sent = _github(monkeypatch)
    a = await acting_user()
    row = await _github_registration(session)
    other = await _seed(session, public_id="acme.other", listing_uid=None)
    started = await _start(client, a.headers, row.id)
    headers = (await acting_user()).headers if whose == "another_owner" else a.headers
    target = other.id if whose == "another_plugin" else row.id

    response = await _complete(client, headers, target, started["state"])

    assert response.status_code == 400
    assert response.json()["detail"] == PluginServiceMessages.VENDOR_SETUP_EXPIRED
    assert sent == []
    # Left for the completion it belongs to.
    finished = await _complete(client, a.headers, row.id, started["state"])
    assert finished.status_code == 200, finished.text
    assert len(sent) == 1


async def test_an_expired_setup_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    sent = _github(monkeypatch)
    monkeypatch.setattr(vendor_setup, "STATE_TTL", timedelta(seconds=-1))
    a = await acting_user()
    row = await _github_registration(session)
    started = await _start(client, a.headers, row.id)

    response = await _complete(client, a.headers, row.id, started["state"])

    assert response.status_code == 400
    assert response.json()["detail"] == PluginServiceMessages.VENDOR_SETUP_EXPIRED
    assert sent == []


async def test_a_conversion_missing_a_value_writes_none_of_them(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    answer = {**CONVERSION, "webhook_secret": None}
    _github(monkeypatch, answer=answer)
    a = await acting_user()
    row = await _github_registration(session)
    await client.patch(
        f"{BASE}{row.id}",
        headers=a.headers,
        json={"vendor_values": {"client_id": "earlier-app"}},
    )
    started = await _start(client, a.headers, row.id)

    response = await _complete(client, a.headers, row.id, started["state"])

    assert response.status_code == 502
    assert response.json()["detail"] == PluginServiceMessages.VENDOR_SETUP_FAILED
    assert await load_vendor_values("acme.widgets") == {"client_id": "earlier-app"}


async def _republish(session: AsyncSession, **setup_values: str) -> None:
    """A newer version of the listing, whose setup writes ``setup_values``
    and whose vendor block declares only the fields it names."""
    definition = copy.deepcopy(GITHUB_DEFINITION)
    vendor = definition["vendor"]
    vendor["fields"] = [f for f in vendor["fields"] if f["key"] in setup_values]
    vendor["setup"]["values"] = setup_values
    await create_marketplace_listing(
        session,
        uid=LISTING_UID,
        public_id="acme.widgets",
        kind="plugin",
        version="1.1.0",
        definition=definition,
    )


async def test_a_setup_writes_by_the_mapping_it_started_with(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    _github(monkeypatch)
    a = await acting_user()
    row = await _github_registration(session)
    started = await _start(client, a.headers, row.id)
    stored = GITHUB_DEFINITION["vendor"]["setup"]["values"]
    await _republish(session, **{**stored, "app_id": "slug"})

    response = await _complete(client, a.headers, row.id, started["state"])

    assert response.status_code == 200, response.text
    assert response.json()["vendor_values"]["app_id"] == "4242"


async def test_a_setup_naming_a_field_the_listing_dropped_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    sent = _github(monkeypatch)
    a = await acting_user()
    row = await _github_registration(session)
    started = await _start(client, a.headers, row.id)
    await _republish(session, app_id="id", client_id="client_id")

    response = await _complete(client, a.headers, row.id, started["state"])

    assert response.status_code == 400
    assert response.json()["detail"] == PluginServiceMessages.VENDOR_SETUP_EXPIRED
    assert sent == []
    assert await load_vendor_values("acme.widgets") == {}


async def test_a_conversion_github_refuses_writes_nothing(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
):
    _github(monkeypatch, status=404)
    a = await acting_user()
    row = await _github_registration(session)
    started = await _start(client, a.headers, row.id)

    response = await client.post(
        f"{BASE}{row.id}/vendor-setup/complete",
        headers=a.headers,
        json={"code": "abc123", "state": started["state"]},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == PluginServiceMessages.VENDOR_SETUP_FAILED
    assert await load_vendor_values("acme.widgets") == {}
