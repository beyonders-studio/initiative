"""An installed plug-in asking to act as a member, the member answering, and the
member token that follows.

A plug-in asks on its installation token (``POST /plugin-platform/consent-requests``)
for one purpose; the member is notified and answers on their consent screen
(``/c/{community_id}/plugins/{plugin_id}/consents/{consent_id}``); the plug-in then presents
a JWT-bearer assertion at the token endpoint and is issued a member token only
while that answer stands. The token's reach is the install standing's member branch
(``app/db/member_standing_test.py``); here the probe route reads through it.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends
from httpx2 import AsyncClient
from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.actor_route import ActorRoute
from app.api.deps import ActorContext, ActorSessionDep, plugin_scope
from app.core.messages import AuthMessages, GuildPluginMessages, PluginMessages
from app.core.plugin_access_token import (
    InstallAccessToken,
    seal_install_token,
    unseal_access_token,
)
from app.db.guild_standing import InstallContext
from app.main import app
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.file import File
from app.models.tenant.initiative import InitiativeMember
from app.services.marketplace import plugin_oauth
from app.services.marketplace.plugin_refs import (
    ensure_plugin_guild_ref,
    ensure_plugin_ref,
)
from app.testing import create_file, drain_notices, route_session_to_guild
from app.testing.plugin_clients import (
    CLIENT,
    InstalledPlugin,
    install_plugin,
    mint_client_assertion,
)

CONSENT_URL = "/api/v1/plugin-platform/consent-requests"
TOKEN_URL = "/api/v1/plugin-platform/oauth/token"
JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"

_PROBE_PATH = "/api/v1/c/{community_id}/member-token-probe/files"
_read_files = plugin_scope("files:read")
_probe = APIRouter(route_class=ActorRoute)


@_probe.get(_PROBE_PATH)
async def _probe_files(
    actor: Annotated[ActorContext, Depends(_read_files)],
    session: ActorSessionDep,
) -> dict[str, Any]:
    names = sorted((await session.exec(select(File.name))).all())
    member = actor.member_user_id if isinstance(actor, InstallContext) else None
    return {"member": member, "files": names}


@pytest.fixture(autouse=True)
def _mounted():
    routes = list(_probe.routes)
    app.router.routes[0:0] = routes
    try:
        yield
    finally:
        for route in routes:
            app.router.routes.remove(route)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _installation_token(installed: InstalledPlugin, **overrides) -> str:
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=installed.plugin.id,
        client_id=CLIENT,
        scopes=frozenset(overrides.pop("scopes", ["files:read"])),
        initiative_id=overrides.pop("initiative_id", None),
        **overrides,
    )
    return token


async def _member(acting_user, installed: InstalledPlugin):
    return await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )


async def _ref(installed: InstalledPlugin, user_id: int) -> str:
    return await ensure_plugin_ref(
        guild_id=installed.guild.id,
        public_id=installed.public_id,
        user_id=user_id,
    )


async def _foreign_ref(guild_id: int, user_id: int) -> str:
    """What another plug-in calls ``user_id`` in the community, written as its
    own install would have it."""
    from app.db.session import SystemSessionLocal
    from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
    from app.services.platform.identity_refs import ensure_ref

    async with SystemSessionLocal() as session:
        ref = await ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=IdentityPurpose.plugin,
            sector_guild_id=guild_id,
            sector_plugin="someone.else",
        )
        await session.commit()
    return ref


async def _ask(client: AsyncClient, installed: InstalledPlugin, **body):
    token = body.pop("token", None) or _installation_token(installed)
    body.setdefault("label", "Comment on the linked issue as you")
    body.setdefault("access", "read_write")
    return await client.post(CONSENT_URL, json=body, headers=_bearer(token))


async def _grant_token(
    client: AsyncClient,
    installed: InstalledPlugin,
    member_ref: str,
    *,
    purpose: str | None = "node-1",
    **form,
):
    extra: dict[str, Any] = {
        "installation": await ensure_plugin_guild_ref(
            guild_id=installed.guild.id, public_id=installed.public_id
        )
    }
    if purpose is not None:
        extra["purpose"] = purpose
    assertion = mint_client_assertion(
        audience=plugin_oauth.token_endpoint_url(), subject=member_ref, extra=extra
    )
    return await client.post(
        TOKEN_URL,
        data={"grant_type": JWT_BEARER, "assertion": assertion, **form},
    )


async def _answer(client, member, installed, consent_id: int, access: str):
    return await client.put(
        member.g(f"/plugins/{installed.plugin.id}/consents/{consent_id}"),
        headers=member.headers,
        json={"access": access},
    )


async def _consent_id(client, member, installed) -> int:
    listed = await client.get(
        member.g(f"/plugins/{installed.plugin.id}"), headers=member.headers
    )
    assert listed.status_code == 200, listed.text
    (row,) = listed.json()["consents"]
    return row["id"]


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------


async def test_a_request_notifies_the_member_once_and_repeats_as_it_stands(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    first = await _ask(client, installed, member=member_ref, purpose="node-1")
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["member"] == member_ref
    assert body["purpose"] == "node-1"
    assert body["status"] == "pending"
    assert body["requested_access"] == "read_write"
    assert body["granted_access"] is None

    again = await _ask(
        client, installed, member=member_ref, purpose="node-1", access="read"
    )
    assert again.status_code == 200, again.text
    assert again.json()["requested_access"] == "read_write"
    assert again.json()["requested_at"] == body["requested_at"]

    await drain_notices()
    notices = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == member.user.id,
                Notification.type == NotificationType.plugin_consent_requested,
            )
        )
    ).all()
    assert len(notices) == 1
    assert notices[0].guild_id == installed.guild.id
    assert notices[0].data["plugin_id"] == installed.plugin.id
    assert notices[0].data["target_path"] == f"/?plugin={installed.plugin.id}"

    # Another purpose is another request.
    other = await _ask(client, installed, member=member_ref, purpose="node-2")
    assert other.status_code == 201, other.text


async def test_a_request_names_a_member_by_this_install_s_reference(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    # A name another plug-in holds, which only its own install could mint.
    elsewhere = await _foreign_ref(installed.guild.id, member.user.id)

    response = await _ask(client, installed, member=elsewhere)

    assert response.status_code == 422
    assert response.json()["detail"] == PluginMessages.REFERENCE_UNKNOWN


async def test_a_request_is_bound_only_where_the_install_and_token_reach(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    unplaced = await _ask(
        client, installed, member=member_ref, initiative_id=installed.unplaced.id
    )
    assert unplaced.status_code == 422
    assert unplaced.json()["detail"] == PluginMessages.CONSENT_INITIATIVE_NOT_PLACED

    narrowed = _installation_token(installed, initiative_id=installed.placed.id)
    beyond = await _ask(client, installed, member=member_ref, token=narrowed)
    assert beyond.status_code == 403
    assert beyond.json()["detail"] == PluginMessages.CONSENT_OUTSIDE_TOKEN

    within = await _ask(
        client,
        installed,
        member=member_ref,
        token=narrowed,
        initiative_id=installed.placed.id,
    )
    assert within.status_code == 201, within.text


async def test_a_request_bound_to_an_initiative_names_a_member_of_it(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=installed.guild)
    outsider_ref = await _ref(installed, outsider.user.id)

    bound = await _ask(
        client, installed, member=outsider_ref, initiative_id=installed.placed.id
    )
    assert bound.status_code == 422, bound.text
    assert bound.json()["detail"] == PluginMessages.CONSENT_MEMBER_NOT_IN_INITIATIVE

    # App-wide, the same member can still be asked.
    plugin_wide = await _ask(client, installed, member=outsider_ref)
    assert plugin_wide.status_code == 201, plugin_wide.text


async def test_a_member_token_cannot_ask(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    token = _installation_token(installed, user_id=member.user.id, purpose="node-1")

    response = await _ask(client, installed, member=member_ref, token=token)

    assert response.status_code == 401
    assert response.json()["detail"] == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS


# ---------------------------------------------------------------------------
# The member's answer
# ---------------------------------------------------------------------------


async def test_the_member_answers_and_nobody_else_sees_it(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    other = await _member(acting_user, installed)
    await _ask(
        client,
        installed,
        member=await _ref(installed, member.user.id),
        purpose="node-1",
        access="read",
    )
    consent_id = await _consent_id(client, member, installed)

    theirs = await client.get(
        other.g(f"/plugins/{installed.plugin.id}"), headers=other.headers
    )
    assert theirs.json()["consents"] == []
    not_theirs = await _answer(client, other, installed, consent_id, "read")
    assert not_theirs.status_code == 404
    assert not_theirs.json()["detail"] == GuildPluginMessages.CONSENT_NOT_FOUND

    more = await _answer(client, member, installed, consent_id, "read_write")
    assert more.status_code == 400
    assert more.json()["detail"] == GuildPluginMessages.CONSENT_EXCEEDS_REQUEST

    granted = await _answer(client, member, installed, consent_id, "read")
    assert granted.status_code == 200, granted.text
    assert granted.json()["status"] == "granted"
    assert granted.json()["granted_access"] == "read"

    detail = await client.get(
        member.g(f"/plugins/{installed.plugin.id}"), headers=member.headers
    )
    assert [c["status"] for c in detail.json()["consents"]] == ["granted"]

    withdrawn = await client.delete(
        member.g(f"/plugins/{installed.plugin.id}/consents/{consent_id}"),
        headers=member.headers,
    )
    assert withdrawn.status_code == 204
    listed = await client.get(
        member.g(f"/plugins/{installed.plugin.id}"), headers=member.headers
    )
    assert listed.json()["consents"][0]["status"] == "revoked"


async def test_an_api_key_cannot_answer(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    from app.services.platform import api_keys as api_keys_service

    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    await _ask(client, installed, member=await _ref(installed, member.user.id))
    consent_id = await _consent_id(client, member, installed)
    secret, _row = await api_keys_service.create_api_key(
        session, user=member.user, name="script"
    )
    await session.commit()

    response = await client.put(
        member.g(f"/plugins/{installed.plugin.id}/consents/{consent_id}"),
        headers={"Authorization": f"Bearer {secret}"},
        json={"access": "read"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"


async def test_the_seat_revokes_every_answer_at_once(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await _ask(client, installed, member=member_ref, purpose="node-1", access="read")
    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read")
    assert (await _grant_token(client, installed, member_ref)).status_code == 200

    stopped = await client.post(
        installed.seat.g(f"/plugins/{installed.plugin.id}/consents/revoke-all"),
        headers=installed.seat.headers,
    )
    assert stopped.status_code == 204, stopped.text

    response = await _grant_token(client, installed, member_ref)
    assert response.status_code == 400
    assert response.json()["error"] == "consent_required"


# ---------------------------------------------------------------------------
# The member token
# ---------------------------------------------------------------------------


async def test_a_member_token_waits_for_the_answer(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await create_file(session, installed.placed, member.user, name="Theirs")

    never_asked = await _grant_token(client, installed, member_ref)
    assert never_asked.status_code == 400
    assert never_asked.json()["error"] == "consent_required"

    await _ask(client, installed, member=member_ref, purpose="node-1")
    unanswered = await _grant_token(client, installed, member_ref)
    assert unanswered.json()["error"] == "consent_required"

    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read")

    # Another purpose, and app-wide, are still unanswered.
    other = await _grant_token(client, installed, member_ref, purpose="node-2")
    assert other.json()["error"] == "consent_required"
    plugin_wide = await _grant_token(client, installed, member_ref, purpose=None)
    assert plugin_wide.json()["error"] == "consent_required"

    issued = await _grant_token(client, installed, member_ref)
    assert issued.status_code == 200, issued.text
    # Read was allowed, so the write scope is issued as read.
    assert issued.json()["scope"] == "files:read"
    token = unseal_access_token(issued.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert (token.user_id, token.purpose) == (member.user.id, "node-1")

    read = await client.get(
        _PROBE_PATH.format(community_id=installed.guild.id),
        headers=_bearer(issued.json()["access_token"]),
    )
    assert read.status_code == 200, read.text
    assert read.json() == {"member": member.user.id, "files": ["Theirs"]}


async def test_a_member_token_is_issued_within_the_ceiling(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """Narrowing the registration's ceiling narrows the member's next token as
    it does the installation's."""
    from app.models.platform.plugin_service_registration import (
        PluginServiceRegistration,
    )
    from app.services.marketplace import registration_lookup
    from app.testing.plugin_clients import CLIENT

    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:write", "comments:read"],
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await _ask(client, installed, member=member_ref, purpose="node-1")
    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read_write")

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

    issued = await _grant_token(client, installed, member_ref)
    assert issued.status_code == 200, issued.text
    assert issued.json()["scope"] == "comments:read"


async def test_a_consent_bound_to_an_initiative_issues_only_narrowed_tokens(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await _ask(
        client,
        installed,
        member=member_ref,
        purpose="node-1",
        initiative_id=installed.placed.id,
    )
    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read_write")

    unnarrowed = await _grant_token(client, installed, member_ref)
    assert unnarrowed.status_code == 400
    assert unnarrowed.json()["error"] == "invalid_target"

    narrowed = await _grant_token(
        client,
        installed,
        member_ref,
        resource=f"urn:initiative:initiative:{installed.placed.id}",
    )
    assert narrowed.status_code == 200, narrowed.text
    token = unseal_access_token(narrowed.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.initiative_id == installed.placed.id


async def test_leaving_the_initiative_or_revoking_stops_the_member_token(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await create_file(session, installed.placed, member.user, name="Theirs")
    await _ask(
        client,
        installed,
        member=member_ref,
        purpose="node-1",
        initiative_id=installed.placed.id,
    )
    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read")
    resource = f"urn:initiative:initiative:{installed.placed.id}"
    issued = await _grant_token(client, installed, member_ref, resource=resource)
    token = issued.json()["access_token"]
    url = _PROBE_PATH.format(community_id=installed.guild.id)

    assert (await client.get(url, headers=_bearer(token))).json()["files"] == ["Theirs"]

    await route_session_to_guild(session, installed.guild.id)
    await session.exec(
        delete(InitiativeMember).where(
            InitiativeMember.initiative_id == installed.placed.id,  # type: ignore[arg-type]
            InitiativeMember.user_id == member.user.id,  # type: ignore[arg-type]
        )
    )
    await session.commit()

    after_leaving = await client.get(url, headers=_bearer(token))
    assert after_leaving.status_code == 200
    assert after_leaving.json()["files"] == []
    regrant = await _grant_token(client, installed, member_ref, resource=resource)
    assert regrant.json()["error"] == "consent_required"

    await client.delete(
        member.g(f"/plugins/{installed.plugin.id}/consents/{consent_id}"),
        headers=member.headers,
    )
    after_revoking = await client.get(url, headers=_bearer(token))
    assert after_revoking.status_code == 401


async def test_the_member_grant_is_its_own_client_authentication(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    beside = await _grant_token(
        client,
        installed,
        member_ref,
        client_assertion_type=plugin_oauth.ASSERTION_TYPE,
        client_assertion=mint_client_assertion(
            audience=plugin_oauth.token_endpoint_url()
        ),
    )
    assert beside.status_code == 400
    assert beside.json()["error"] == "invalid_request"

    unknown = await _grant_token(client, installed, "plugin_unknown_member")
    assert unknown.status_code == 400
    assert unknown.json()["error"] == "invalid_grant"

    no_installation = await client.post(
        TOKEN_URL,
        data={
            "grant_type": JWT_BEARER,
            "assertion": mint_client_assertion(
                audience=plugin_oauth.token_endpoint_url(), subject=member_ref
            ),
        },
    )
    assert no_installation.status_code == 400
    assert no_installation.json()["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# How often a plug-in may ask
# ---------------------------------------------------------------------------


@pytest.fixture
def limits_on(client, monkeypatch):
    """The limiter on, with no global default in the way. Takes ``client``,
    whose setup switches the limiter off."""
    from app.core.rate_limit import limiter

    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(limiter, "_default_limits", [])
    limiter.reset()
    yield
    limiter.reset()


async def test_new_requests_of_one_member_are_limited_and_repeats_are_not(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, limits_on
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    for n in range(5):
        made = await _ask(client, installed, member=member_ref, purpose=f"node-{n}")
        assert made.status_code == 201, made.text

    sixth = await _ask(client, installed, member=member_ref, purpose="node-5")
    assert sixth.status_code == 429
    assert sixth.json()["detail"] == PluginMessages.CONSENT_RATE_LIMITED

    repeat = await _ask(client, installed, member=member_ref, purpose="node-0")
    assert repeat.status_code == 200, repeat.text

    # Another member has an allowance of their own.
    other = await _member(acting_user, installed)
    fresh = await _ask(
        client,
        installed,
        member=await _ref(installed, other.user.id),
        purpose="node-5",
    )
    assert fresh.status_code == 201, fresh.text

    await drain_notices()
    notices = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == member.user.id,
                Notification.type == NotificationType.plugin_consent_requested,
            )
        )
    ).all()
    assert len(notices) == 5


async def test_an_install_is_limited_however_it_asks(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    limits_on,
    monkeypatch,
):
    from limits import parse

    from app.api.v1.platform_endpoints import plugin_consent_requests

    monkeypatch.setattr(
        plugin_consent_requests, "CONSENT_REQUESTS_PER_INSTALL", parse("3/minute")
    )
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    for _ in range(3):
        asked = await _ask(client, installed, member=member_ref, purpose="node-1")
        assert asked.status_code in (200, 201), asked.text

    refused = await _ask(client, installed, member=member_ref, purpose="node-1")
    assert refused.status_code == 429
    assert refused.json()["detail"] == PluginMessages.CONSENT_RATE_LIMITED


async def _reinstall(session: AsyncSession, installed: InstalledPlugin):
    """The same plug-in removed and installed again: a new install row, placed
    where the old one was, with the same grant."""
    from dataclasses import replace

    from app.models.tenant.guild_plugin import GuildPlugin
    from app.models.tenant.plugin_placement import PluginPlacement
    from app.testing import create_guild_plugin

    await route_session_to_guild(session, installed.guild.id)
    old = await session.get(GuildPlugin, installed.plugin.id)
    assert old is not None
    definition, listing, granted = (
        dict(old.definition),
        old.listing_uid,
        list(old.granted_scopes),
    )
    await session.delete(old)
    await session.commit()
    plugin = await create_guild_plugin(
        session,
        installed.guild,
        installed.seat.user,
        definition=definition,
        listing_uid=listing,
        granted_scopes=granted,
    )
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        PluginPlacement(install_id=plugin.id, initiative_id=installed.placed.id)
    )
    await session.commit()
    return replace(installed, plugin=plugin)


async def test_a_member_is_the_same_reference_after_a_reinstall(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    """The reference is the plug-in's in the community, not the install's: it
    names the same member to the new install, whose token endpoint issues on
    it once the member has answered the new install's request."""
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    community = await ensure_plugin_guild_ref(
        guild_id=installed.guild.id, public_id=installed.public_id
    )

    again = await _reinstall(session, installed)
    assert again.plugin.id != installed.plugin.id
    assert await _ref(again, member.user.id) == member_ref
    assert (
        await ensure_plugin_guild_ref(
            guild_id=again.guild.id, public_id=again.public_id
        )
        == community
    )

    asked = await _ask(
        client,
        again,
        member=member_ref,
        purpose="node-1",
        token=_installation_token(again),
    )
    assert asked.status_code == 201, asked.text
    await _answer(
        client, member, again, await _consent_id(client, member, again), "read"
    )

    issued = await _grant_token(client, again, member_ref)
    assert issued.status_code == 200, issued.text
    token = unseal_access_token(issued.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert (token.install_id, token.user_id) == (again.plugin.id, member.user.id)


async def test_no_member_token_while_the_plugin_is_not_installed(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    # The community's name stands, and is what the assertion names it by.
    await ensure_plugin_guild_ref(
        guild_id=installed.guild.id, public_id=installed.public_id
    )
    await route_session_to_guild(session, installed.guild.id)
    from app.models.tenant.guild_plugin import GuildPlugin

    await session.delete(await session.get(GuildPlugin, installed.plugin.id))
    await session.commit()

    refused = await _grant_token(client, installed, member_ref)
    assert refused.status_code == 400
    assert refused.json()["error"] == "invalid_grant"
