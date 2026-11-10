"""One installed plug-in calling another through Initiative.

The caller holds ``plugins:<target>`` and calls
``POST /plugin-platform/plugins/{public_id}/endpoints/{endpoint_id}`` on its own
installation or member token. Initiative checks the call and makes it with a
context token naming the caller, the actor and, for a member, the target's own
reference for them.

The seam these tests stub is ``plugin_data._read_body``, where the call leaves for
the plug-in called; everything above it runs for real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import jwt
import pytest
from httpx2 import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.messages import PluginDataMessages, PluginHubMessages
from app.core.plugin_access_token import seal_install_token
from app.models.platform.guild import CommunityRole, GuildMembership
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.guild_plugin_user_connection import GuildPluginUserConnection
from app.models.tenant.initiative import InitiativeRule
from app.models.tenant.plugin_member_consent import PluginMemberConsent
from app.models.tenant.plugin_placement import PluginPlacement
from app.services.marketplace import plugin_data as plugin_data_service
from app.services.marketplace.context_jwt_test import _PRIVATE_PEM
from app.services.marketplace.plugin_refs import ensure_plugin_ref
from app.services.tenant.initiatives import get_member_role
from app.services.tenant.plugin_connection_flows import TokenSet, seal_tokens
from app.testing import (
    create_guild_plugin,
    create_plugin_service_registration,
    create_plugin_user_connection,
    emitted,
    route_session_to_guild,
)
from app.testing.fake_vendor import API_HOST, FakeVendor, declarative_plugin
from app.testing.plugin_clients import CLIENT, InstalledPlugin, install_plugin

TARGET = "tests.github"
TARGET_UID = "TESTGTHB000001"
TARGET_BASE = "http://127.0.0.1:9200"
PLUGINS_SCOPE = f"plugins:{TARGET}"
PURPOSE = "node-1"

#: A read either actor may call, the community's and a member's connection
#: either satisfying it.
ISSUES = f"plugin.{TARGET}.issues"
#: A write only a member may call.
COMMENT = f"plugin.{TARGET}.comment"
#: A write the community may call.
OPEN_ISSUE = f"plugin.{TARGET}.open_issue"
#: A read that is not part of the public surface.
PRIVATE = f"plugin.{TARGET}.private"
#: Long after any test ends, as a stored token's expiry.
_LATER = 4102444800


def _url(endpoint_id: str, public_id: str = TARGET) -> str:
    return f"/api/v1/plugin-platform/plugins/{public_id}/endpoints/{endpoint_id}"


def _target_definition() -> dict[str, Any]:
    return {
        "plugin_kind": "service",
        "service": {"public_id": TARGET, "protocol": 1},
        "features": ["endpoints"],
        "connections": [
            {
                "id": "workspace",
                "scope": "static",
                "label": {"en": "Workspace"},
                "fields": [
                    {
                        "key": "org",
                        "type": "string",
                        "label": {"en": "Org"},
                        "required": True,
                    }
                ],
            },
            {
                "id": "account",
                "scope": "interactive",
                "label": {"en": "Account"},
                "fields": [{"key": "login", "type": "string", "label": {"en": "L"}}],
            },
        ],
        "endpoints": [
            {
                "id": ISSUES,
                "direction": "read",
                "public": True,
                "actors": ["installation", "member"],
                "requires": {"any_of": ["workspace", "account"]},
                "params": [{"key": "repo", "type": "string", "label": {"en": "R"}}],
                "cache_ttl_seconds": 60,
            },
            {
                "id": COMMENT,
                "direction": "write",
                "public": True,
                "actors": ["member"],
                "params": [{"key": "body", "type": "string", "label": {"en": "B"}}],
            },
            {
                "id": OPEN_ISSUE,
                "direction": "write",
                "public": True,
                "actors": ["installation"],
            },
            {
                "id": PRIVATE,
                "direction": "read",
                "actors": ["installation"],
            },
        ],
    }


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setattr(
        settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PRIVATE_PEM
    )
    monkeypatch.setattr(settings, "PLUGIN_PLATFORM_SIGNING_KEY_ID", "plugin-platform-1")


@pytest.fixture(autouse=True)
def _clean_cache():
    plugin_data_service.clear_plugin_data_cache()
    plugin_data_service._inflight.clear()
    yield
    plugin_data_service.clear_plugin_data_cache()
    plugin_data_service._inflight.clear()


@pytest.fixture
def upstream(monkeypatch):
    """Stand in for the plug-in called, recording every request it receives."""

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[httpx2.Request] = []

        def claims(self, index: int = -1) -> dict[str, Any]:
            header = self.calls[index].headers["Authorization"]
            return jwt.decode(
                header.removeprefix("Bearer "),
                options={"verify_signature": False},
                algorithms=["EdDSA"],
            )

    recorder = Recorder()

    async def _fake_read_body(request, *, transport=None):
        recorder.calls.append(request)
        return {"endpoint": "x", "actor": "installation", "result": {"number": 7}}

    monkeypatch.setattr(plugin_data_service, "_read_body", _fake_read_body)
    return recorder


async def _hub(
    session: AsyncSession,
    acting_user,
    role_session,
    *,
    granted: tuple[str, ...] = (PLUGINS_SCOPE,),
    place_target: bool = True,
    install_target: bool = True,
    declarative: bool = False,
    definition: dict[str, Any] | None = None,
) -> tuple[InstalledPlugin, GuildPlugin | None]:
    """A caller asking for ``plugins:tests.github``, and the target installed in
    the same community, placed where the caller is unless told otherwise, where
    its members' role uses it. A ``declarative`` target is called by Initiative
    itself, on the community's stored token."""
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=list(granted),
        requested=[PLUGINS_SCOPE, "files:read"],
    )
    if declarative:
        await create_plugin_service_registration(
            session,
            public_id=TARGET,
            listing_uid=TARGET_UID,
            base_url=None,
            allowed_origins=[],
            jwks={},
            kind="declarative",
        )
    else:
        await create_plugin_service_registration(
            session, public_id=TARGET, listing_uid=TARGET_UID, base_url=TARGET_BASE
        )
    if not install_target:
        return installed, None
    config, secrets = seal_tokens(
        TokenSet(access_token="gho_community", expires_at=_LATER),
        config={"owner": "acme"},
        secrets={},
    )
    target = await create_guild_plugin(
        session,
        installed.guild,
        installed.seat.user,
        definition=definition
        or (declarative_plugin(TARGET) if declarative else _target_definition()),
        listing_uid=TARGET_UID,
        name="GitHub",
        **(
            {"config": {"workspace": config}, "secrets": {"workspace": secrets}}
            if declarative
            else {
                "config": {"workspace": {"org": "acme"}},
                "connection_refs": {"workspace": "gcr_workspace"},
            }
        ),
    )
    if place_target:
        await route_session_to_guild(session, installed.guild.id)
        session.add(
            PluginPlacement(install_id=target.id, initiative_id=installed.placed.id)
        )
        await _hold(session, installed, target, "use")
    return installed, target


async def _hold(
    session: AsyncSession, installed, target, permission: str, *, enabled=True
) -> None:
    """The placed initiative's member role's answer for one of the target's
    permissions."""
    await route_session_to_guild(session, installed.guild.id)
    role = await get_member_role(session, initiative_id=installed.placed.id)
    assert role is not None
    rule = (
        await session.exec(
            select(InitiativeRule).where(
                InitiativeRule.initiative_role_id == role.id,
                InitiativeRule.install_id == target.id,
                InitiativeRule.key == permission,
            )
        )
    ).first() or InitiativeRule(
        initiative_id=installed.placed.id,
        initiative_role_id=role.id,
        install_id=target.id,
        key=permission,
        enabled=enabled,
    )
    rule.enabled = enabled
    session.add(rule)
    await session.commit()


def _installation_headers(
    installed: InstalledPlugin,
    scopes: tuple[str, ...] = (PLUGINS_SCOPE,),
    initiative_id: int | None = None,
) -> dict[str, str]:
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=installed.plugin.id,
        client_id=CLIENT,
        scopes=frozenset(scopes),
        initiative_id=initiative_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def _member(
    session: AsyncSession,
    acting_user,
    installed: InstalledPlugin,
    *,
    access: str = "read_write",
):
    """A member of the placed initiative who let the caller act as them."""
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        PluginMemberConsent(
            install_id=installed.plugin.id,
            user_id=member.user.id,
            purpose=PURPOSE,
            label="Comment as you",
            requested_access="read_write",
            granted_access=access,
            granted_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return member


def _member_headers(installed: InstalledPlugin, member) -> dict[str, str]:
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=installed.plugin.id,
        client_id=CLIENT,
        scopes=frozenset({PLUGINS_SCOPE}),
        initiative_id=None,
        user_id=member.user.id,
        purpose=PURPOSE,
    )
    return {"Authorization": f"Bearer {token}"}


async def _connect(session: AsyncSession, installed, target, member) -> None:
    """The member's own account on the target."""
    config, secrets = seal_tokens(
        TokenSet(access_token="gho_member", expires_at=_LATER),
        config={"login": "alice"},
        secrets={},
    )
    await create_plugin_user_connection(
        session,
        target,
        member.user,
        connection_id="account",
        connection_ref="cr_member_account",
        config=config,
        secrets=secrets,
    )


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


async def test_a_caller_without_the_scope_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(ISSUES),
        json={"params": {}},
        headers=_installation_headers(installed, scopes=("files:read",)),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == PluginHubMessages.INSUFFICIENT_SCOPE
    assert upstream.calls == []


async def test_a_scope_the_seat_took_back_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    """The token still carries it; the grant no longer does."""
    installed, _target = await _hub(
        session, acting_user, role_session, granted=("files:read",)
    )

    response = await client.post(
        _url(ISSUES), json={}, headers=_installation_headers(installed)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == PluginHubMessages.INSUFFICIENT_SCOPE
    assert upstream.calls == []


async def test_a_target_not_installed_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(
        session, acting_user, role_session, install_target=False
    )

    response = await client.post(
        _url(ISSUES), json={}, headers=_installation_headers(installed)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == PluginHubMessages.TARGET_NOT_INSTALLED


async def test_an_endpoint_that_is_not_public_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(PRIVATE), json={}, headers=_installation_headers(installed)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == PluginHubMessages.ENDPOINT_NOT_PUBLIC
    assert upstream.calls == []


async def test_a_member_only_endpoint_refuses_an_installation_token(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(COMMENT),
        json={"params": {"body": "Done"}},
        headers=_installation_headers(installed),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == PluginHubMessages.ACTOR_NOT_SUPPORTED
    assert upstream.calls == []


async def test_a_target_not_placed_in_the_narrowed_initiative_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(
        session, acting_user, role_session, place_target=False
    )

    response = await client.post(
        _url(OPEN_ISSUE),
        json={},
        headers=_installation_headers(installed, initiative_id=installed.placed.id),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == PluginHubMessages.TARGET_NOT_PLACED
    assert upstream.calls == []


async def test_a_target_placed_in_the_narrowed_initiative_is_called(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(OPEN_ISSUE),
        json={},
        headers=_installation_headers(installed, initiative_id=installed.placed.id),
    )

    assert response.status_code == 200, response.text
    assert upstream.claims()["initiative_id"] == installed.placed.id


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


async def test_an_installation_call_names_the_caller_and_passes_the_answer_back(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, target = await _hub(session, acting_user, role_session)
    assert target is not None

    response = await client.post(
        _url(ISSUES),
        json={"params": {"repo": "acme/web"}},
        headers=_installation_headers(installed),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "endpoint": "x",
        "actor": "installation",
        "result": {"number": 7},
    }
    (request,) = upstream.calls
    assert str(request.url) == f"{TARGET_BASE}/v1/endpoints"
    claims = upstream.claims()
    assert claims["aud"] == f"initiative-plugin:{TARGET}"
    assert claims["plugin_install_id"] == target.id
    assert claims["endpoint_id"] == ISSUES
    assert claims["act"] == {"sub": CLIENT}
    assert claims["actor"] == "installation"
    assert "member" not in claims
    assert "initiative_id" not in claims
    # The community's handle only.
    assert claims["connection_refs"] == {"workspace": "gcr_workspace"}


async def test_a_member_call_carries_the_targets_reference_never_the_callers(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, target = await _hub(session, acting_user, role_session)
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)

    response = await client.post(
        _url(COMMENT),
        json={"params": {"body": "Done"}},
        headers=_member_headers(installed, member),
    )

    assert response.status_code == 200, response.text
    claims = upstream.claims()
    target_ref = await ensure_plugin_ref(
        guild_id=installed.guild.id,
        public_id=target.definition["service"]["public_id"],
        user_id=member.user.id,
    )
    caller_ref = await ensure_plugin_ref(
        guild_id=installed.guild.id,
        public_id=installed.public_id,
        user_id=member.user.id,
    )
    assert claims["actor"] == "member"
    assert claims["member"] == target_ref
    assert target_ref != caller_ref
    assert caller_ref not in upstream.calls[0].headers["Authorization"]
    assert caller_ref.encode() not in upstream.calls[0].content


async def test_a_member_call_hands_on_only_the_members_connections(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, target = await _hub(session, acting_user, role_session)
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)

    response = await client.post(
        _url(ISSUES), json={}, headers=_member_headers(installed, member)
    )

    assert response.status_code == 200, response.text
    assert upstream.claims()["connection_refs"] == {"account": "cr_member_account"}


async def test_a_member_call_is_held_to_the_members_permission_in_the_target(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    """As opening the target would be: the member's role where the target is
    placed holds the permission the endpoint names, or ``use``. A call made as
    the community answers to what the community granted alone."""
    definition = _target_definition()
    definition["permissions"] = [
        {"id": "triage", "level": "initiative", "name": {"en": "Triage"}}
    ]
    definition["endpoints"][0]["permission"] = "triage"
    installed, target = await _hub(
        session, acting_user, role_session, definition=definition
    )
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)

    async def call(endpoint_id: str, headers) -> int:
        response = await client.post(
            _url(endpoint_id), json={"params": {}}, headers=headers
        )
        if response.status_code == 403:
            assert response.json()["detail"] == PluginDataMessages.PERMISSION_REQUIRED
        return response.status_code

    assert await call(ISSUES, _member_headers(installed, member)) == 403
    assert await call(ISSUES, _installation_headers(installed)) == 200
    await _hold(session, installed, target, "triage")
    assert await call(ISSUES, _member_headers(installed, member)) == 200
    await _hold(session, installed, target, "use", enabled=False)
    assert await call(COMMENT, _member_headers(installed, member)) == 403


async def test_a_read_only_consent_does_not_write_as_the_member(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)
    member = await _member(session, acting_user, installed, access="read")

    response = await client.post(
        _url(COMMENT),
        json={"params": {"body": "Done"}},
        headers=_member_headers(installed, member),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == PluginHubMessages.INSUFFICIENT_SCOPE
    assert upstream.calls == []


async def test_a_parameter_the_endpoint_does_not_declare_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(ISSUES),
        json={"params": {"nope": "x"}},
        headers=_installation_headers(installed),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == PluginDataMessages.INVALID_PARAMS


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


async def test_a_write_is_not_cached(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)
    headers = _installation_headers(installed)

    for _ in range(2):
        response = await client.post(_url(OPEN_ISSUE), json={}, headers=headers)
        assert response.status_code == 200, response.text

    assert len(upstream.calls) == 2


async def test_a_read_is_cached_per_actor(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, target = await _hub(session, acting_user, role_session)
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)
    body = {"params": {"repo": "acme/web"}}

    for _ in range(2):
        response = await client.post(
            _url(ISSUES), json=body, headers=_installation_headers(installed)
        )
        assert response.status_code == 200, response.text
    assert len(upstream.calls) == 1

    response = await client.post(
        _url(ISSUES), json=body, headers=_member_headers(installed, member)
    )
    assert response.status_code == 200, response.text
    assert len(upstream.calls) == 2


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def test_every_call_is_written_to_the_audit_stream_without_its_params(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    upstream,
    capfd,
):
    installed, _target = await _hub(session, acting_user, role_session)
    capfd.readouterr()

    await client.post(
        _url(ISSUES),
        json={"params": {"repo": "secret-repo-name"}},
        headers=_installation_headers(installed),
    )
    await client.post(_url(PRIVATE), json={}, headers=_installation_headers(installed))

    answered, refused = emitted(capfd, AuditEventType.PLUGIN_HUB_CALL)
    assert answered["guild_id"] == installed.guild.id
    assert answered["detail"] == {
        "caller": CLIENT,
        "target": TARGET,
        "endpoint": ISSUES,
        "actor": "installation",
        "outcome": "ok",
        "direction": "read",
    }
    assert refused["detail"]["outcome"] == PluginHubMessages.ENDPOINT_NOT_PUBLIC
    assert "secret-repo-name" not in str(answered)


@pytest.mark.parametrize("ended", ["consent", "guest_time"])
async def test_a_member_token_for_a_member_who_left_is_refused(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    upstream,
    ended,
):
    """The install seam still stands the token up first: a withdrawn consent,
    or a guest's time running out, leaves the member token nothing to act
    with."""
    installed, _target = await _hub(session, acting_user, role_session)
    member = await _member(session, acting_user, installed)
    now = datetime.now(UTC)
    if ended == "consent":
        await route_session_to_guild(session, installed.guild.id)
        consent = (
            await session.exec(
                select(PluginMemberConsent).where(
                    PluginMemberConsent.user_id == member.user.id
                )
            )
        ).one()
        consent.revoked_at = now
        session.add(consent)
    else:
        membership = (
            await session.exec(
                select(GuildMembership).where(
                    GuildMembership.guild_id == installed.guild.id,
                    GuildMembership.user_id == member.user.id,
                )
            )
        ).one()
        membership.guest_until = now - timedelta(minutes=1)
        session.add(membership)
    await session.commit()

    response = await client.post(
        _url(ISSUES), json={}, headers=_member_headers(installed, member)
    )

    assert response.status_code == 401
    assert upstream.calls == []


# ---------------------------------------------------------------------------
# A declarative target
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint,answer,status,body",
    [
        (
            "issues",
            {"body": [{"title": "Broken build"}]},
            200,
            {
                "endpoint": f"plugin.{TARGET}.issues",
                "actor": "installation",
                "result": {"titles": ["Broken build"], "total": 1},
            },
        ),
        ("issues", {"status": 404}, 200, None),
        ("label", {"status": 422, "body": {"message": "locked"}}, 422, "locked"),
        ("label", {"status": 403}, 403, "not-authorized"),
        ("label", {"status": 429}, 502, PluginDataMessages.SERVICE_UNAVAILABLE),
    ],
    ids=["read", "read-refused", "write-rule", "write-default", "throttled"],
)
async def test_a_declarative_target_is_called_by_initiative(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    monkeypatch,
    endpoint,
    answer,
    status,
    body,
):
    """The hub's checks are the same; the call is Initiative's own, on the
    community's credential. A read answers its unavailable code; a write is
    refused with it; a throttle is the plug-in being unavailable, which a caller
    retries."""
    vendor = FakeVendor()
    vendor.install(monkeypatch)
    vendor.api_answers = [answer]
    installed, _target = await _hub(
        session, acting_user, role_session, declarative=True
    )

    response = await client.post(
        _url(f"plugin.{TARGET}.{endpoint}"),
        json={
            "params": {
                "repo": "acme/web",
                **({"number": 7} if endpoint == "label" else {}),
            }
        },
        headers=_installation_headers(installed),
    )

    assert response.status_code == status, response.text
    if status != 200:
        assert response.json()["detail"] == body
    elif body is None:
        assert response.json()["result"] == {"unavailable": "not-found"}
    else:
        assert response.json() == body
    assert vendor.api_requests[0]["headers"]["authorization"] == "Bearer gho_community"


def _with_member_account(requires: dict[str, Any] | None) -> dict[str, Any]:
    """:func:`declarative_plugin` with a member's own account beside the
    community's workspace: its read open to members, on the workspace, under
    ``requires``; and a member's comment on their account."""
    definition = declarative_plugin(TARGET)
    (workspace,) = definition["connections"]
    workspace["fields"] = [{"key": "owner", "type": "string", "label": {"en": "O"}}]
    definition["connections"].append(
        {**workspace, "id": "account", "scope": "interactive", "fields": []}
    )
    issues, label = definition["endpoints"]
    issues["actors"] = ["installation", "member"]
    if requires is not None:
        issues["requires"] = requires
    definition["endpoints"].append(
        {
            **label,
            "id": COMMENT,
            "actors": ["member"],
            "requires": {"all_of": ["workspace", "account"]},
            "request": {
                "method": "POST",
                "url": (
                    f'"https://{API_HOST}/repos/" & connections.workspace.owner'
                    ' & "/" & params.repo & "/issues/" & params.number & "/comments"'
                ),
                "body": '{"seen": connections}',
                "connection": "account",
            },
        }
    )
    return definition


@pytest.mark.parametrize(
    "requires,status",
    [({"all_of": ["workspace"]}, 200), ({"any_of": ["workspace"]}, 200), (None, 409)],
    ids=["all-of", "any-of", "not-named"],
)
async def test_a_member_call_reads_on_the_community_connection_its_requires_names(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    monkeypatch,
    requires,
    status,
):
    vendor = FakeVendor()
    vendor.install(monkeypatch)
    vendor.api_answers = [{"body": [{"title": "Broken build"}]}]
    installed, _target = await _hub(
        session,
        acting_user,
        role_session,
        declarative=True,
        definition=_with_member_account(requires),
    )
    member = await _member(session, acting_user, installed)

    response = await client.post(
        _url(ISSUES),
        json={"params": {"repo": "acme/web"}},
        headers=_member_headers(installed, member),
    )

    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["result"] == {"titles": ["Broken build"], "total": 1}
        assert vendor.api_requests[0]["headers"]["authorization"] == (
            "Bearer gho_community"
        )
    else:
        assert response.json()["detail"] == PluginDataMessages.NEEDS_CONFIGURATION
        assert vendor.api_requests == []


async def test_a_member_write_reads_the_community_connection_without_its_secrets(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    monkeypatch,
):
    vendor = FakeVendor()
    vendor.install(monkeypatch)
    vendor.api_answers = [{"body": {"number": 7}}]
    installed, target = await _hub(
        session,
        acting_user,
        role_session,
        declarative=True,
        definition=_with_member_account(None),
    )
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)

    response = await client.post(
        _url(COMMENT),
        json={"params": {"repo": "web", "number": 7}},
        headers=_member_headers(installed, member),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actor"] == "member"
    sent = vendor.api_requests[0]
    assert sent["url"] == f"https://{API_HOST}/repos/acme/web/issues/7/comments"
    assert sent["headers"]["authorization"] == "Bearer gho_member"
    assert sent["body"] == {
        "seen": {"workspace": {"owner": "acme"}, "account": {"login": "alice"}}
    }


@pytest.mark.parametrize(
    "caller,status,token",
    [
        ("installation", 200, "gho_community"),
        ("member", 200, "gho_member"),
        ("unconnected", 409, None),
    ],
    ids=["installation", "member", "member-not-connected"],
)
async def test_a_write_naming_a_connection_per_actor_runs_on_the_callers(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    monkeypatch,
    caller,
    status,
    token,
):
    """A write made as the installation carries the community's credential
    and one made as a member the member's own, which ``requires`` need not
    name: a member who has not connected it is told to, and the vendor is
    not called."""
    definition = _with_member_account(None)
    label = definition["endpoints"][1]
    label.update(actors=["member", "installation"], requires={"all_of": ["workspace"]})
    label["request"]["connection"] = {"member": "account", "installation": "workspace"}
    vendor = FakeVendor()
    vendor.install(monkeypatch)
    vendor.api_answers = [{"body": {"number": 7}}]
    installed, target = await _hub(
        session, acting_user, role_session, declarative=True, definition=definition
    )
    assert target is not None
    headers = _installation_headers(installed)
    if caller != "installation":
        member = await _member(session, acting_user, installed)
        if caller == "member":
            await _connect(session, installed, target, member)
        headers = _member_headers(installed, member)

    response = await client.post(
        _url(f"plugin.{TARGET}.label"),
        json={"params": {"repo": "web", "number": 7}},
        headers=headers,
    )

    assert response.status_code == status, response.text
    if token is None:
        assert response.json()["detail"] == PluginDataMessages.CONNECTION_REQUIRED
        assert vendor.api_requests == []
    else:
        assert response.json()["actor"] == caller
        assert vendor.api_requests[0]["headers"]["authorization"] == f"Bearer {token}"


async def test_a_cached_read_follows_the_members_connection_fields(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    monkeypatch,
):
    """The same parameters on the same connection are answered from the
    cache until the connection's fields change."""
    definition = _with_member_account({"all_of": ["workspace", "account"]})
    definition["endpoints"][0]["request"]["url"] = (
        f'"https://{API_HOST}/repos/" & connections.account.login & "/issues"'
    )
    vendor = FakeVendor()
    vendor.install(monkeypatch)
    vendor.api_answers = [
        {"body": [{"title": "Alice's"}]},
        {"body": [{"title": "Bob's"}]},
    ]
    installed, target = await _hub(
        session, acting_user, role_session, declarative=True, definition=definition
    )
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)

    async def titles() -> list[str]:
        response = await client.post(
            _url(ISSUES),
            json={"params": {"repo": "web"}},
            headers=_member_headers(installed, member),
        )
        assert response.status_code == 200, response.text
        return response.json()["result"]["titles"]

    assert await titles() == ["Alice's"]
    assert await titles() == ["Alice's"]
    assert len(vendor.api_requests) == 1

    await route_session_to_guild(session, installed.guild.id)
    row = (
        await session.exec(
            select(GuildPluginUserConnection).where(
                GuildPluginUserConnection.connection_ref == "cr_member_account"
            )
        )
    ).one()
    row.config = {**row.config, "login": "bob"}
    session.add(row)
    await session.commit()

    assert await titles() == ["Bob's"]
    assert [request["url"] for request in vendor.api_requests] == [
        f"https://{API_HOST}/repos/alice/issues",
        f"https://{API_HOST}/repos/bob/issues",
    ]
