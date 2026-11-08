"""The plug-in platform's token endpoint and the listing a plug-in token reaches.

A plug-in authenticates with a JWT it signs (RFC 7523 §2.2) against the key set
its registration publishes, and is issued a plug-in token or an installation
token. Every refusal is the OAuth error body RFC 6749 §5.2 defines.
"""

from __future__ import annotations

import time

import pytest
from httpx2 import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.plugin_access_token import (
    ACCESS_TOKEN_PREFIX,
    InstallAccessToken,
    PluginAccessToken,
    unseal_access_token,
)
from app.models.platform.plugin_service_registration import (
    PluginServiceRegistration,
    RegistrationKind,
)
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import plugin_installs, plugin_oauth
from app.services.marketplace.plugin_refs import ensure_plugin_guild_ref
from app.services.marketplace.registration_lookup import invalidate_registrations
from app.services.tenant import plugin_updates
from app.testing import route_session_to_guild
from app.testing.audit import emitted
from app.testing.plugin_clients import (
    CLIENT,
    InstalledPlugin,
    install_plugin,
    mint_client_assertion,
)

TOKEN_URL = "/api/v1/plugin-platform/oauth/token"
INSTALLATIONS_URL = "/api/v1/plugin-platform/installations"
ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


def _assertion(**overrides) -> str:
    overrides.setdefault("audience", plugin_oauth.token_endpoint_url())
    return mint_client_assertion(**overrides)


async def _ask(client: AsyncClient, *, assertion: str | None = None, **form):
    body = {
        "grant_type": "client_credentials",
        "client_assertion_type": ASSERTION_TYPE,
        "client_assertion": assertion if assertion is not None else _assertion(),
        **form,
    }
    return await client.post(TOKEN_URL, data=body)


def _error(response) -> str:
    return response.json()["error"]


async def _limit_to_operations(session: AsyncSession) -> None:
    """Limit the client's registration to the operations community, which no
    test community is."""
    await session.exec(
        text(
            "UPDATE public.plugin_service_registrations SET operations_only = true "
            "WHERE public_id = :c"
        ).bindparams(c=CLIENT)
    )
    await session.commit()
    invalidate_registrations()


async def _installation(installed: InstalledPlugin) -> str:
    return await ensure_plugin_guild_ref(
        guild_id=installed.guild.id, public_id=installed.public_id
    )


# ---------------------------------------------------------------------------
# Plug-in tokens
# ---------------------------------------------------------------------------


async def test_a_plugin_token_names_only_the_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(session, acting_user, role_session, granted=["files:read"])

    response = await _ask(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 600
    assert body["scope"] == ""
    assert body["access_token"].startswith(ACCESS_TOKEN_PREFIX)
    assert response.headers["cache-control"] == "no-store"
    token = unseal_access_token(body["access_token"])
    assert token == PluginAccessToken(client_id=CLIENT, exp=token.exp)


async def test_an_assertion_presented_twice_is_refused_and_written_down(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, capfd
):
    await install_plugin(session, acting_user, role_session, granted=["files:read"])
    assertion = _assertion()
    assert (await _ask(client, assertion=assertion)).status_code == 200

    emitted(capfd)
    again = await _ask(client, assertion=assertion)
    assert again.status_code == 401
    (line,) = emitted(capfd, AuditEventType.SECURITY_REPLAY_REJECTED)
    assert line["detail"] == {"channel": "plugin_assertion", "install": CLIENT}


async def test_a_key_the_plugin_never_registered_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Only the registered Ed25519 key authenticates: an RSA key, even under the
    plug-in's own kid, is refused, as is any non-EdDSA algorithm."""
    await install_plugin(session, acting_user, role_session, granted=["files:read"])

    response = await _ask(client, assertion=_assertion(key="foreign-rsa"))

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


# ---------------------------------------------------------------------------
# Installation tokens
# ---------------------------------------------------------------------------


async def test_an_installation_token_carries_every_granted_scope(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:write", "comments:read"],
    )

    response = await _ask(client, installation=await _installation(installed))

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "comments:read files:write"
    token = unseal_access_token(response.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.guild_id == installed.guild.id
    assert token.install_id == installed.plugin.id
    assert token.client_id == CLIENT
    assert token.scopes == frozenset({"files:write", "comments:read"})
    assert token.initiative_id is None


async def test_an_installation_token_can_be_down_scoped(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:write", "comments:read"],
    )

    response = await _ask(
        client, installation=await _installation(installed), scope="comments:read"
    )

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "comments:read"
    token = unseal_access_token(response.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.scopes == frozenset({"comments:read"})


async def test_a_written_resource_may_be_asked_for_at_read(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )

    response = await _ask(
        client, installation=await _installation(installed), scope="files:read"
    )

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "files:read"


async def test_a_scope_to_use_another_plugin_is_issued_and_asked_for_by_name(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:read", "plugins:tests.github"],
        requested=["files:read", "plugins:tests.github"],
    )
    installation = await _installation(installed)

    everything = await _ask(client, installation=installation)
    assert everything.status_code == 200, everything.text
    assert everything.json()["scope"] == "files:read plugins:tests.github"

    narrowed = await _ask(
        client, installation=installation, scope="plugins:tests.github"
    )
    assert narrowed.status_code == 200, narrowed.text
    token = unseal_access_token(narrowed.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.scopes == frozenset({"plugins:tests.github"})

    other = await _ask(client, installation=installation, scope="plugins:tests.other")
    assert other.status_code == 400
    assert _error(other) == "invalid_scope"


@pytest.mark.parametrize("scope", ["projects:read", "files:write", "not-a-scope"])
async def test_a_scope_beyond_the_grant_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, scope
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )

    response = await _ask(
        client, installation=await _installation(installed), scope=scope
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_scope"


async def _upgrade_dropping(session: AsyncSession, installed: InstalledPlugin, keep):
    """Move the install to a version whose manifest requests only ``keep``,
    through the same re-pin the Update button and the sweep use."""
    await route_session_to_guild(session, installed.guild.id)
    row = (
        await session.exec(
            select(GuildPlugin).where(GuildPlugin.id == installed.plugin.id)
        )
    ).one()
    definition = {
        **row.definition,
        "service": {**row.definition["service"], "scopes": list(keep)},
    }
    await plugin_updates.apply_version(
        session,
        row,
        plugin_updates.PendingUpdate(version="1.1.0", definition=definition),
        guild_id=installed.guild.id,
    )
    await session.commit()


async def test_a_scope_the_pinned_version_dropped_is_not_issued(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """The seat's grant is left as it was; the next token carries only what
    the pinned version still requests."""
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:write", "comments:read"],
    )
    installation = await _installation(installed)
    before = await _ask(client, installation=installation)
    assert before.json()["scope"] == "comments:read files:write"

    await _upgrade_dropping(session, installed, ["comments:read"])

    after = await _ask(client, installation=installation)
    assert after.status_code == 200, after.text
    assert after.json()["scope"] == "comments:read"
    refused = await _ask(client, installation=installation, scope="files:write")
    assert refused.status_code == 400
    assert _error(refused) == "invalid_scope"

    (row,) = (await session.exec(select(GuildPlugin))).all()
    assert sorted(row.granted_scopes) == ["comments:read", "files:write"]


async def test_a_scope_the_ceiling_no_longer_allows_is_not_issued(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Narrowing the registration's ceiling narrows the next token, whatever
    the seat granted before."""
    from app.models.platform.plugin_service_registration import (
        PluginServiceRegistration,
    )
    from app.services.marketplace import registration_lookup

    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:write", "comments:read"],
    )
    installation = await _installation(installed)

    registration = (
        await session.exec(
            select(PluginServiceRegistration).where(
                PluginServiceRegistration.public_id == CLIENT
            )
        )
    ).one()
    registration.scope_ceiling = ["comments:read"]
    session.add(registration)
    await session.commit()
    registration_lookup.invalidate_registrations()

    after = await _ask(client, installation=installation)
    assert after.status_code == 200, after.text
    assert after.json()["scope"] == "comments:read"


async def test_a_placed_initiative_narrows_the_token(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )

    response = await _ask(
        client,
        installation=await _installation(installed),
        resource=f"urn:initiative:initiative:{installed.placed.id}",
    )

    assert response.status_code == 200, response.text
    token = unseal_access_token(response.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.initiative_id == installed.placed.id


@pytest.mark.parametrize("which", ["unplaced", "malformed"])
async def test_an_initiative_it_is_not_placed_in_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, which
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    resource = (
        f"urn:initiative:initiative:{installed.unplaced.id}"
        if which == "unplaced"
        else "urn:initiative:project:1"
    )

    response = await _ask(
        client, installation=await _installation(installed), resource=resource
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_target"


# ---------------------------------------------------------------------------
# Standings: asked for by level, never carried by default
# ---------------------------------------------------------------------------

_STANDINGS = ["initiatives:moderate", "community:admin"]


async def test_a_granted_standing_is_not_on_a_token_that_did_not_ask(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read", *_STANDINGS]
    )

    response = await _ask(client, installation=await _installation(installed))

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "files:read"


async def test_a_moderator_level_carries_its_scope_into_the_initiative(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read", *_STANDINGS]
    )

    response = await _ask(
        client,
        installation=await _installation(installed),
        resource=f"urn:initiative:initiative:{installed.placed.id}",
        level="moderator",
    )

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "files:read initiatives:moderate"
    token = unseal_access_token(response.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.scopes == frozenset({"files:read", "initiatives:moderate"})
    assert token.initiative_id == installed.placed.id


async def test_a_guild_admin_level_carries_its_scope(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read", *_STANDINGS]
    )

    response = await _ask(
        client,
        installation=await _installation(installed),
        scope="files:read",
        level="community_admin",
    )

    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "community:admin files:read"


@pytest.mark.parametrize(
    ("level", "narrowed"), [("moderator", True), ("community_admin", False)]
)
async def test_a_level_the_community_did_not_grant_is_refused(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    level,
    narrowed,
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    form = {"level": level}
    if narrowed:
        form["resource"] = f"urn:initiative:initiative:{installed.placed.id}"

    response = await _ask(client, installation=await _installation(installed), **form)

    assert response.status_code == 400
    assert _error(response) == "invalid_scope"


async def test_a_level_the_ceiling_does_not_allow_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    from app.models.platform.plugin_service_registration import (
        PluginServiceRegistration,
    )
    from app.services.marketplace import registration_lookup

    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read", *_STANDINGS]
    )
    registration = (
        await session.exec(
            select(PluginServiceRegistration).where(
                PluginServiceRegistration.public_id == CLIENT
            )
        )
    ).one()
    registration.scope_ceiling = ["files:read"]
    session.add(registration)
    await session.commit()
    registration_lookup.invalidate_registrations()

    response = await _ask(
        client, installation=await _installation(installed), level="community_admin"
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_scope"


async def test_a_moderator_level_names_its_initiative(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """A moderator moderates one initiative, which the token names."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read", *_STANDINGS]
    )

    response = await _ask(
        client, installation=await _installation(installed), level="moderator"
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_target"


async def test_a_guild_admin_level_may_be_narrowed(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Narrowed, it administers within that one initiative."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read", *_STANDINGS]
    )

    response = await _ask(
        client,
        installation=await _installation(installed),
        resource=f"urn:initiative:initiative:{installed.placed.id}",
        level="community_admin",
    )

    assert response.status_code == 200, response.text
    token = unseal_access_token(response.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.scopes == frozenset({"files:read", "community:admin"})
    assert token.initiative_id == installed.placed.id


@pytest.mark.parametrize("standing", _STANDINGS)
async def test_a_standing_is_not_asked_for_by_scope(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, standing
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read", *_STANDINGS]
    )

    response = await _ask(
        client,
        installation=await _installation(installed),
        scope=f"files:read {standing}",
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_scope"


async def test_an_unknown_level_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read", *_STANDINGS]
    )

    response = await _ask(
        client, installation=await _installation(installed), level="owner"
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_request"


async def test_a_plugin_token_takes_no_level(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(session, acting_user, role_session, granted=_STANDINGS)

    response = await _ask(client, level="community_admin")

    assert response.status_code == 400
    assert _error(response) == "invalid_request"


async def test_a_member_token_takes_no_level(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """It acts for the member, whose own standing it already is."""
    await install_plugin(session, acting_user, role_session, granted=_STANDINGS)

    response = await client.post(
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": "unread",
            "level": "moderator",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_request",
        "error_description": "a member token takes no level",
    }


async def test_an_unknown_installation_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(session, acting_user, role_session, granted=["files:read"])

    response = await _ask(client, installation="not-a-reference")

    assert response.status_code == 400
    assert _error(response) == "invalid_grant"


async def test_another_clients_installation_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(session, acting_user, role_session, granted=["files:read"])
    other = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:read"],
        client_id="tests.other-client",
        listing_uid="OTHERCLIENT001",
    )

    response = await _ask(client, installation=await _installation(other))

    assert response.status_code == 400
    assert _error(response) == "invalid_grant"


async def test_an_operations_only_plugin_gets_no_token_elsewhere(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    await _limit_to_operations(session)

    response = await _ask(client, installation=await _installation(installed))

    assert response.status_code == 400
    assert _error(response) == "invalid_grant"


async def test_the_member_grant_takes_no_client_assertion(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Its assertion authenticates the client (RFC 7523 §3); the member grant
    itself is in ``plugin_member_tokens_test``."""
    await install_plugin(session, acting_user, role_session, granted=["files:read"])

    response = await _ask(
        client, grant_type="urn:ietf:params:oauth:grant-type:jwt-bearer"
    )

    assert response.status_code == 400
    assert _error(response) == "invalid_request"


async def test_an_unknown_grant_type_is_unsupported(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(session, acting_user, role_session, granted=["files:read"])

    response = await _ask(client, grant_type="password")

    assert response.status_code == 400
    assert _error(response) == "unsupported_grant_type"


# ---------------------------------------------------------------------------
# Client authentication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"audience": "https://elsewhere.example/token"}, id="bad-aud"),
        pytest.param({"kid": "no-such-kid"}, id="unknown-kid"),
        # Signed RS256 with a key the plug-in never registered, under its own
        # kid: the key the kid names decides the algorithm, never the header.
        pytest.param({"key": "foreign-rsa"}, id="foreign-key-under-the-kid"),
        pytest.param({"lifetime": 301}, id="lives-too-long"),
        pytest.param({"issued_ago": 120, "lifetime": 60}, id="expired"),
        pytest.param({"issued_ago": -300, "lifetime": 60}, id="issued-in-future"),
        pytest.param({"client_id": "tests.nobody"}, id="unknown-iss"),
        pytest.param({"subject": "tests.someone-else"}, id="sub-is-not-iss"),
    ],
)
async def test_a_bad_assertion_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, overrides
):
    await install_plugin(session, acting_user, role_session, granted=["files:read"])
    overrides = dict(overrides)
    issued_ago = overrides.pop("issued_ago", None)
    if issued_ago is not None:
        overrides["issued_at"] = time.time() - issued_ago

    response = await _ask(client, assertion=_assertion(**overrides))

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


async def test_an_assertion_is_used_once(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(session, acting_user, role_session, granted=["files:read"])
    assertion = _assertion()

    first = await _ask(client, assertion=assertion)
    second = await _ask(client, assertion=assertion)

    assert first.status_code == 200, first.text
    assert second.status_code == 401
    assert _error(second) == "invalid_client"


async def test_a_disabled_registration_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(
        session, acting_user, role_session, granted=["files:read"], enabled=False
    )

    response = await _ask(client)

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


async def test_a_declarative_registration_is_never_a_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """A declarative plug-in runs no code, so keys left on its registration
    authenticate nothing."""
    await install_plugin(session, acting_user, role_session, granted=["files:read"])
    registration = (
        await session.exec(
            select(PluginServiceRegistration).where(
                PluginServiceRegistration.public_id == CLIENT
            )
        )
    ).one()
    registration.kind = RegistrationKind.DECLARATIVE
    session.add(registration)
    await session.commit()
    invalidate_registrations()
    assert registration.jwks

    response = await _ask(client)

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


async def test_no_assertion_is_an_invalid_client(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    await install_plugin(session, acting_user, role_session, granted=["files:read"])

    response = await client.post(TOKEN_URL, data={"grant_type": "client_credentials"})

    assert response.status_code == 401
    assert _error(response) == "invalid_client"


async def test_a_json_body_is_an_invalid_request(client: AsyncClient):
    response = await client.post(TOKEN_URL, json={"grant_type": "client_credentials"})

    assert response.status_code == 400
    assert _error(response) == "invalid_request"


# ---------------------------------------------------------------------------
# The plug-in's installs
# ---------------------------------------------------------------------------


async def test_a_plugin_token_lists_the_installs_a_page_at_a_time(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Read from the install index, with the next page named in a ``Link``
    header until the last."""
    first = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    second = await install_plugin(
        session, acting_user, role_session, granted=[], register=False
    )
    plugin_token = (await _ask(client)).json()["access_token"]
    headers = {"Authorization": f"Bearer {plugin_token}"}

    page = await client.get(INSTALLATIONS_URL, params={"limit": 1}, headers=headers)

    assert page.status_code == 200, page.text
    assert page.json() == [{"installation": await _installation(first), "active": True}]
    link = page.headers["link"]
    assert link.startswith("<?") and link.endswith('>; rel="next"')
    last = await client.get(f"{INSTALLATIONS_URL}{link[1:-13]}", headers=headers)
    assert last.json() == [
        {"installation": await _installation(second), "active": True}
    ]
    assert "link" not in last.headers


@pytest.mark.parametrize(
    "paused_by", ["install_off", "guild_on_hold", "guild_deleted", "operations_only"]
)
async def test_a_paused_install_is_listed_as_inactive(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    paused_by: str,
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    plugin_token = (await _ask(client)).json()["access_token"]
    installation = await _installation(installed)
    if paused_by == "install_off":
        switched = await client.patch(
            installed.seat.g(f"/plugins/{installed.plugin.id}"),
            json={"enabled": False},
            headers=installed.seat.headers,
        )
        assert switched.status_code == 200, switched.text
    elif paused_by == "operations_only":
        await _limit_to_operations(session)
    else:
        status = "on_hold" if paused_by == "guild_on_hold" else "deleted"
        await session.exec(
            text("UPDATE public.guilds SET status = :s WHERE id = :id").bindparams(
                s=status, id=installed.guild.id
            )
        )
    await session.commit()
    # The index follows the install on the index sweep's next visit.
    await route_session_to_guild(session, installed.guild.id)
    await plugin_installs.reindex_community(session, installed.guild.id)

    response = await client.get(
        INSTALLATIONS_URL, headers={"Authorization": f"Bearer {plugin_token}"}
    )

    assert response.status_code == 200, response.text
    [listed] = response.json()
    assert listed["installation"] == installation
    assert listed["active"] is False


async def test_an_installation_token_does_not_list_installs(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    installation_token = (
        await _ask(client, installation=await _installation(installed))
    ).json()["access_token"]

    response = await client.get(
        INSTALLATIONS_URL, headers={"Authorization": f"Bearer {installation_token}"}
    )

    assert response.status_code == 401
