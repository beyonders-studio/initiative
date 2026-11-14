"""Sign in with Initiative: the authorize page's reads, the code it sends a
person back with, and the token endpoint's two grants for it.

A plug-in that names ``sign_in`` in its manifest sends somebody to Initiative;
they choose where to open it, and come back with a code the plug-in spends,
with its registered key, for an ID token carrying the handoff's claims for that
place. Every renewal asks again.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import PluginSignInMessages
from app.models.platform.guild import CommunityRole
from app.services.auth import sessions as auth_sessions
from app.services.marketplace import plugin_oauth, plugin_sign_in
from app.services.marketplace.plugin_refs import ensure_plugin_ref
from app.testing import create_marketplace_listing, marketplace_uid
from app.testing.factories import signed_in_headers
from app.testing.plugin_clients import (
    CLIENT,
    install_plugin,
    mint_client_assertion,
)

TOKEN_URL = "/api/v1/plugin-platform/oauth/token"
CLIENT_URL = "/api/v1/plugin-platform/oauth/authorize/client"
PLACES_URL = "/api/v1/plugin-platform/oauth/authorize/places"
AUTHORIZE_URL = "/api/v1/plugin-platform/oauth/authorize"
LISTING = marketplace_uid("hoard")
ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
#: The registration's address (``create_plugin_service_registration``) with the
#: manifest's ``return_path``.
REDIRECT = "https://app.example.test/signed-in"

SIGNS_IN = {
    "features": ["pages"],
    "pages": [
        {
            "id": "inventory",
            "path": "/inventory",
            "name": {"en": "Inventory"},
            "scopes": ["community", "initiative"],
        }
    ],
    "sign_in": {"page": "inventory", "return_path": "/signed-in"},
}

_SIGNING_KEY_PEM = (
    ed25519.Ed25519PrivateKey.generate()
    .private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    .decode("ascii")
)


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setattr(
        settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _SIGNING_KEY_PEM
    )
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_KEY_ID", "test-key")


async def _offered(session: AsyncSession, acting_user, role_session):
    """The plug-in installed, registered and listed with a ``sign_in``."""
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=[],
        listing_uid=LISTING,
        declares=SIGNS_IN,
    )
    await create_marketplace_listing(
        session,
        uid=LISTING,
        public_id=CLIENT,
        kind="plugin",
        name="Hoard",
        definition={
            "plugin_kind": "service",
            "service": {"public_id": CLIENT, "protocol": 1},
            "default_name": "Hoard",
            **SIGNS_IN,
        },
    )
    return installed


def _request(**overrides) -> dict[str, str]:
    """An authorize request as the SDK sends one, and its PKCE verifier under
    ``_verifier``."""
    verifier = secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return {
        "response_type": "code",
        "client_id": CLIENT,
        "redirect_uri": REDIRECT,
        "scope": "openid",
        "state": "state-1",
        "nonce": "nonce-1",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "_verifier": verifier,
        **overrides,
    }


def _query(request: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in request.items() if not k.startswith("_")}


async def _spend(client: AsyncClient, **form):
    return await client.post(
        TOKEN_URL,
        data={
            "client_assertion_type": ASSERTION_TYPE,
            "client_assertion": mint_client_assertion(
                audience=plugin_oauth.token_endpoint_url()
            ),
            **form,
        },
    )


async def _code(client: AsyncClient, headers, request, **place) -> dict[str, str]:
    response = await client.post(
        AUTHORIZE_URL, json={**_query(request), **place}, headers=headers
    )
    assert response.status_code == 200, response.text
    redirect = urlsplit(response.json()["redirect_to"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == REDIRECT
    return {k: v[0] for k, v in parse_qs(redirect.query).items()}


def _claims(id_token: str) -> dict:
    return jwt.decode(
        id_token,
        options={"verify_signature": False},
        audience=CLIENT,
    )


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


async def test_the_page_names_the_plugin_asking(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await _offered(session, acting_user, role_session)

    response = await client.get(CLIENT_URL, params=_query(_request()))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Hoard"
    assert body["listing_public_id"] == CLIENT
    assert body["refusal_redirect"] is None
    cancel = parse_qs(urlsplit(body["cancel_redirect"]).query)
    assert cancel == {
        "error": ["access_denied"],
        "state": ["state-1"],
        "iss": [plugin_sign_in.issuer()],
    }


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"client_id": "tests.nobody"}, PluginSignInMessages.UNKNOWN_CLIENT),
        (
            {"redirect_uri": "https://elsewhere.example.test/signed-in"},
            PluginSignInMessages.REDIRECT_MISMATCH,
        ),
        (
            {"redirect_uri": f"{REDIRECT}?next=x"},
            PluginSignInMessages.REDIRECT_MISMATCH,
        ),
    ],
)
async def test_a_request_that_cannot_name_where_to_answer_is_answered_here(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    overrides,
    code,
):
    """Checked before anything else, and never sent anywhere."""
    await _offered(session, acting_user, role_session)

    response = await client.get(CLIENT_URL, params=_query(_request(**overrides)))

    assert response.status_code == 400
    assert response.json()["detail"] == code


@pytest.mark.parametrize(
    "overrides",
    [
        {"code_challenge_method": "plain"},
        {"code_challenge": ""},
        {"nonce": ""},
        {"scope": "profile"},
    ],
)
async def test_a_malformed_request_is_sent_back_to_the_plugin(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, overrides
):
    """Its client and address check out, so the plug-in hears about it."""
    await _offered(session, acting_user, role_session)

    response = await client.get(CLIENT_URL, params=_query(_request(**overrides)))

    assert response.status_code == 200, response.text
    refusal = urlsplit(response.json()["refusal_redirect"])
    assert parse_qs(refusal.query)["state"] == ["state-1"]
    assert parse_qs(refusal.query)["error"][0] in {"invalid_request", "invalid_scope"}


async def test_a_plugin_that_names_no_sign_in_is_not_offered_one(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(
        session, acting_user, role_session, granted=[], listing_uid=LISTING
    )
    await create_marketplace_listing(
        session,
        uid=LISTING,
        public_id=CLIENT,
        kind="plugin",
        definition={
            "plugin_kind": "service",
            "service": {"public_id": CLIENT, "protocol": 1},
            "default_name": "Hoard",
        },
    )

    response = await client.get(CLIENT_URL, params=_query(_request()))

    assert response.json()["detail"] == PluginSignInMessages.NOT_OFFERED


# ---------------------------------------------------------------------------
# Places and the code
# ---------------------------------------------------------------------------


async def test_the_places_are_where_the_page_would_open_inside_initiative(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """The community admin opens it at community level and in the initiative
    it is placed in; not in the one it is not."""
    installed = await _offered(session, acting_user, role_session)

    response = await client.get(
        PLACES_URL, params=_query(_request()), headers=installed.seat.headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["installed_community_ids"] == [installed.guild.id]
    assert [(p["community_id"], p["initiative_id"]) for p in body["places"]] == [
        (installed.guild.id, None),
        (installed.guild.id, installed.placed.id),
    ]
    assert body["places"][1]["initiative_name"] == installed.placed.name


async def test_a_member_the_placement_does_not_admit_has_nowhere_to_open_it(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _offered(session, acting_user, role_session)
    member = await acting_user(guild_role=CommunityRole.member, guild=installed.guild)
    headers = await signed_in_headers(session, member.user)

    places = await client.get(PLACES_URL, params=_query(_request()), headers=headers)
    assert places.json() == {
        "places": [],
        "installed_community_ids": [installed.guild.id],
    }

    refused = await client.post(
        AUTHORIZE_URL,
        json={**_query(_request()), "community_id": installed.guild.id},
        headers=headers,
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == PluginSignInMessages.PLACE_UNAVAILABLE


async def test_the_code_buys_an_id_token_carrying_the_handoffs_claims(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _offered(session, acting_user, role_session)
    headers = await signed_in_headers(session, installed.seat.user)
    request = _request()

    returned = await _code(
        client,
        headers,
        request,
        community_id=installed.guild.id,
        initiative_id=installed.placed.id,
    )
    assert returned["state"] == "state-1"
    assert returned["iss"] == plugin_sign_in.issuer()

    response = await _spend(
        client,
        grant_type="authorization_code",
        code=returned["code"],
        redirect_uri=REDIRECT,
        code_verifier=request["_verifier"],
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["refresh_token"].startswith("irt_")
    assert jwt.get_unverified_header(body["id_token"])["typ"] == "JWT"
    claims = _claims(body["id_token"])
    assert claims["iss"] == plugin_sign_in.issuer() != "initiative"
    assert claims["nonce"] == "nonce-1"
    assert claims["sub"] == await ensure_plugin_ref(
        guild_id=installed.guild.id, public_id=CLIENT, user_id=installed.seat.user.id
    )
    assert claims["surface_id"] == "inventory"
    assert claims["plugin_install_id"] == installed.plugin.id
    assert claims["initiative_id"] == installed.placed.id
    assert claims["community_admin"] is True
    assert "email" not in claims and "name" not in claims

    # Spent once.
    again = await _spend(
        client,
        grant_type="authorization_code",
        code=returned["code"],
        redirect_uri=REDIRECT,
        code_verifier=request["_verifier"],
    )
    assert again.json()["error"] == "invalid_grant"


@pytest.mark.parametrize("wrong", ["verifier", "redirect_uri"])
async def test_a_code_spent_without_its_request_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, wrong
):
    installed = await _offered(session, acting_user, role_session)
    headers = await signed_in_headers(session, installed.seat.user)
    request = _request()
    returned = await _code(client, headers, request, community_id=installed.guild.id)

    response = await _spend(
        client,
        grant_type="authorization_code",
        code=returned["code"],
        redirect_uri=f"{REDIRECT}/other" if wrong == "redirect_uri" else REDIRECT,
        code_verifier=secrets.token_urlsafe(32)
        if wrong == "verifier"
        else request["_verifier"],
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# Renewal
# ---------------------------------------------------------------------------


async def test_a_renewal_asks_again_and_ends_with_the_initiative_sign_in(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _offered(session, acting_user, role_session)
    headers = await signed_in_headers(session, installed.seat.user)
    request = _request()
    returned = await _code(client, headers, request, community_id=installed.guild.id)
    first = (
        await _spend(
            client,
            grant_type="authorization_code",
            code=returned["code"],
            redirect_uri=REDIRECT,
            code_verifier=request["_verifier"],
        )
    ).json()

    renewed = await _spend(
        client, grant_type="refresh_token", refresh_token=first["refresh_token"]
    )
    assert renewed.status_code == 200, renewed.text
    claims = _claims(renewed.json()["id_token"])
    assert "nonce" not in claims
    assert claims["sub"] == _claims(first["id_token"])["sub"]

    # Signing out of Initiative ends the plug-in's session at its next renewal.
    await auth_sessions.revoke_all_for_user(session, user_id=installed.seat.user.id)
    await session.commit()
    ended = await _spend(
        client, grant_type="refresh_token", refresh_token=first["refresh_token"]
    )
    assert ended.status_code == 400
    assert ended.json()["error"] == "invalid_grant"


async def test_a_refresh_token_is_spent_only_by_its_own_plugin(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await _offered(session, acting_user, role_session)
    headers = await signed_in_headers(session, installed.seat.user)
    request = _request()
    returned = await _code(client, headers, request, community_id=installed.guild.id)
    first = (
        await _spend(
            client,
            grant_type="authorization_code",
            code=returned["code"],
            redirect_uri=REDIRECT,
            code_verifier=request["_verifier"],
        )
    ).json()

    response = await client.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": first["refresh_token"]},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


async def test_the_provider_publishes_where_to_find_it(client: AsyncClient):
    response = await client.get("/.well-known/openid-configuration")

    assert response.status_code == 200
    body = response.json()
    assert body["issuer"] == plugin_sign_in.issuer()
    assert (
        body["authorization_endpoint"] == f"{plugin_sign_in.issuer()}/oauth/authorize"
    )
    assert body["token_endpoint"] == plugin_oauth.token_endpoint_url()
    assert body["id_token_signing_alg_values_supported"] == ["EdDSA"]
    assert body["code_challenge_methods_supported"] == ["S256"]
