"""The dependency a route names to admit an installed plug-in.

A probe route is mounted for these tests that names ``files:read`` with
:func:`plugin_scope` and reads files through :data:`ActorSessionDep`. No real
route opts in yet, so the probe is what exercises the marker end to end: an
installation token is verified, routed through the install seam and held to
the route's scope; a person passes through the ordinary seam unchanged; and a
route that names no scope refuses the token before anything is read.
"""

from __future__ import annotations

import time
from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends
from sqlalchemy import event
from sqlmodel import select
from starlette.requests import Request

from app.api.actor_route import ActorRoute
from app.api.deps import (
    PLUGIN_SCOPE_ATTRIBUTE,
    ActorContext,
    ActorSessionDep,
    plugin_scope,
    route_plugin_scope,
)
from app.core.identity_boundary import boundary_scope
from app.core.messages import AuthMessages, PluginMessages
from app.core.plugin_access_token import seal_install_token, seal_plugin_token
from app.db.guild_standing import GuildContext, InstallContext
from app.main import app
from app.models.platform.guild import CommunityRole
from app.models.tenant.file import File
from app.testing import create_file
from app.testing.plugin_clients import CLIENT, install_plugin, share_with_members

_PROBE_PATH = "/api/v1/c/{community_id}/plugin-scope-probe/files"
_read_files = plugin_scope("files:read")

_probe = APIRouter(route_class=ActorRoute)


@_probe.get(_PROBE_PATH)
async def _probe_files(
    actor: Annotated[ActorContext, Depends(_read_files)],
    session: ActorSessionDep,
) -> dict[str, Any]:
    names = sorted((await session.exec(select(File.name))).all())
    return {
        "actor": "install" if isinstance(actor, InstallContext) else "person",
        "files": names,
    }


@pytest.fixture(autouse=True)
def _mounted():
    """Put the probe ahead of the SPA's catch-all, and take it away after."""
    routes = list(_probe.routes)
    app.router.routes[0:0] = routes
    try:
        yield
    finally:
        for route in routes:
            app.router.routes.remove(route)


def _url(guild_id: int) -> str:
    return _PROBE_PATH.format(community_id=guild_id)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _install_token(installed, scopes, **overrides) -> str:
    token, _exp = seal_install_token(
        guild_id=overrides.pop("guild_id", installed.guild.id),
        install_id=installed.plugin.id,
        client_id=CLIENT,
        scopes=frozenset(scopes),
        initiative_id=None,
        **overrides,
    )
    return token


async def _with_shared_file(session, installed):
    file = await create_file(
        session, installed.placed, installed.seat.user, name="Shared"
    )
    await share_with_members(session, file, installed.placed.id)
    await create_file(session, installed.placed, installed.seat.user, name="Private")


# ---------------------------------------------------------------------------
# The marker
# ---------------------------------------------------------------------------


def test_the_dependency_carries_its_scope():
    assert getattr(_read_files, PLUGIN_SCOPE_ATTRIBUTE) == "files:read"
    (route,) = _probe.routes
    assert route_plugin_scope(route) == "files:read"


def test_an_unknown_scope_fails_where_the_route_is_written():
    with pytest.raises(ValueError):
        plugin_scope("files:admin")


# ---------------------------------------------------------------------------
# An installed plug-in
# ---------------------------------------------------------------------------


async def test_an_installation_token_reads_through_the_routed_session(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    await _with_shared_file(session, installed)

    response = await client.get(
        _url(installed.guild.id),
        headers=_bearer(_install_token(installed, ["files:read"])),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"actor": "install", "files": ["Shared"]}


async def test_the_guild_comes_from_the_token_not_the_path(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    await _with_shared_file(session, installed)

    response = await client.get(
        _url(installed.guild.id + 100_000),
        headers=_bearer(_install_token(installed, ["files:read"])),
    )

    assert response.status_code == 200, response.text
    assert response.json()["files"] == ["Shared"]


async def test_write_covers_read(client, session, acting_user, role_session):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:write"]
    )
    await _with_shared_file(session, installed)

    response = await client.get(
        _url(installed.guild.id),
        headers=_bearer(_install_token(installed, ["files:write"])),
    )

    assert response.status_code == 200, response.text


async def test_a_token_without_the_scope_is_forbidden(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session,
        acting_user,
        role_session,
        granted=["files:read", "comments:read"],
    )

    response = await client.get(
        _url(installed.guild.id),
        headers=_bearer(_install_token(installed, ["comments:read"])),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == PluginMessages.SCOPE_REQUIRED


@pytest.mark.parametrize("shape", ["tampered", "expired", "plugin-token", "not-live"])
async def test_a_token_that_is_not_a_live_install_is_unauthorized(
    client, session, acting_user, role_session, shape
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    if shape == "tampered":
        good = _install_token(installed, ["files:read"])
        flipped = "A" if good[-5] != "A" else "B"
        token = good[:-5] + flipped + good[-4:]
    elif shape == "expired":
        token = _install_token(installed, ["files:read"], now=time.time() - 700)
    elif shape == "plugin-token":
        token, _exp = seal_plugin_token(client_id=CLIENT)
    else:
        # Sealed correctly, for a community the install is not in.
        token = _install_token(
            installed, ["files:read"], guild_id=installed.guild.id + 100_000
        )

    response = await client.get(_url(installed.guild.id), headers=_bearer(token))

    assert response.status_code == 401
    assert response.json()["detail"] == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS


# ---------------------------------------------------------------------------
# A person
# ---------------------------------------------------------------------------


async def test_a_person_passes_through_unchanged(client, session, acting_user):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    await create_file(session, a.initiative, a.user, name="Mine")

    response = await client.get(_url(a.guild.id), headers=a.headers)

    assert response.status_code == 200, response.text
    assert response.json() == {"actor": "person", "files": ["Mine"]}


async def test_a_person_route_refuses_an_installation_token(
    client, session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )

    response = await client.get(
        "/api/v1/me",
        headers=_bearer(_install_token(installed, ["files:read"])),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


async def test_an_install_request_spends_two_statements_before_its_handler(
    session, acting_user, role_session
):
    installed = await install_plugin(
        session, acting_user, role_session, granted=["files:read"]
    )
    token = _install_token(installed, ["files:read"])
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": _url(installed.guild.id),
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "client": ("198.51.100.7", 40404),
        }
    )

    s = await role_session("app_user")
    await s.connection()
    statements: list[str] = []

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    engine = s.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        # The slot ActorRoute opens for every request it serves.
        with boundary_scope():
            # ``person`` is what ``get_actor_user`` answers for an access token.
            context = await _read_files(request, s, installed.guild.id, person=None)
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert isinstance(context, InstallContext)
    assert not isinstance(context, GuildContext)
    assert len(statements) == 2, statements
    assert request.state.plugin_install == (
        CLIENT,
        installed.guild.id,
        installed.plugin.id,
    )
    await s.rollback()
