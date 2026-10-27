"""Identity at the boundary, end to end.

A probe router is mounted for these tests on ``ActorRoute``, with routes that
name ``files:read`` and ``files:write`` and whose schemas type their
person and community fields :data:`PersonId` and :data:`GuildId`. No real route
opts in yet, so the probe is what exercises the translation: an installed plug-in
names people by its own references and reads them back the same way; a person
sends and receives row ids, unchanged; and the round trips stay where the
design puts them.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Iterator, Optional

import pytest
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlmodel import select

from app.api.actor_route import ActorRoute
from app.api.deps import ActorContext, ActorSessionDep, plugin_scope, route_plugin_scope
from app.core.plugin_access_token import seal_install_token
from app.core.identity_boundary import GuildId, PersonId
from app.core.messages import PluginMessages
from app.db.guild_standing import InstallContext
from app.main import app
from app.models.platform.guild import CommunityRole
from app.models.platform.identity_ref import (
    REF_GRACE_PERIOD,
    IdentityEntity,
    IdentityPurpose,
    IdentityRef,
)
from app.models.tenant.plugin_placement import PluginPlacement
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import plugin_refs
from app.testing import (
    create_plugin_service_registration,
    create_guild_plugin,
    route_as,
    route_session_to_guild,
)
from app.testing.plugin_clients import CLIENT, client_jwks, install_plugin

pytestmark = pytest.mark.always

_BASE = "/api/v1/c/{community_id}/actor-route-probe"
_read = plugin_scope("files:read")
_write = plugin_scope("files:write")


class _Person(BaseModel):
    id: PersonId
    name: str


class _People(BaseModel):
    guild_id: GuildId
    creator: PersonId
    people: list[_Person]
    reviewer: Optional[PersonId] = None


class _Naming(BaseModel):
    guild_id: GuildId
    assignees: list[PersonId]


#: What the tests hand the probe, and what the probe saw.
_state: dict[str, Any] = {}

_probe = APIRouter(route_class=ActorRoute)


@_probe.get(_BASE + "/people", response_model=_People)
async def _list_people(
    actor: Annotated[ActorContext, Depends(_read)], session: ActorSessionDep
) -> _People:
    _state["before_handler"] = len(_state.get("statements", []))
    creator, *others = _state["people"]
    return _People(
        guild_id=actor.guild_id,
        creator=creator,
        people=[_Person(id=user_id, name=f"person {user_id}") for user_id in others],
    )


@_probe.post(_BASE + "/assign", response_model=_Naming)
async def _assign(
    body: _Naming,
    actor: Annotated[ActorContext, Depends(_write)],
    session: ActorSessionDep,
    reviewer: Optional[PersonId] = None,
) -> _Naming:
    _state["before_handler"] = len(_state.get("statements", []))
    _state["received"] = {
        "guild_id": body.guild_id,
        "assignees": list(body.assignees),
        "reviewer": reviewer,
        "actor": "install" if isinstance(actor, InstallContext) else "person",
    }
    return body


@_probe.get(_BASE + "/raw")
async def _raw(actor: Annotated[ActorContext, Depends(_read)]) -> JSONResponse:
    return JSONResponse({"creator": _state["people"][0]})


@pytest.fixture(autouse=True)
def _mounted():
    """Put the probe ahead of the SPA's catch-all, and take it away after."""
    routes = list(_probe.routes)
    app.router.routes[0:0] = routes
    _state.clear()
    try:
        yield
    finally:
        for route in routes:
            app.router.routes.remove(route)
        _state.clear()


@contextmanager
def _counting() -> Iterator[list[str]]:
    """Every statement any engine runs meanwhile, in order."""
    statements: list[str] = []
    _state["statements"] = statements

    def count(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", count)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", count)


def _url(guild_id: int, path: str) -> str:
    return _BASE.format(community_id=guild_id) + path


def _bearer(guild_id: int, install_id: int, scopes, client_id: str = CLIENT):
    token, _exp = seal_install_token(
        guild_id=guild_id,
        install_id=install_id,
        client_id=client_id,
        scopes=frozenset(scopes),
        initiative_id=None,
    )
    return {"Authorization": f"Bearer {token}"}


async def _setup(session, acting_user, role_session, scopes=("files:write",)):
    installed = await install_plugin(
        session, acting_user, role_session, granted=list(scopes)
    )
    others = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=installed.guild,
            initiative=installed.placed,
            initiative_role="member",
        )
        for _ in range(3)
    ]
    people = [installed.seat.user.id, *(o.user.id for o in others)]
    _state["people"] = people
    return installed, people


async def _second_install(session, role_session, installed, scopes):
    """Another plug-in installed in the same community and placed beside the
    first."""
    client_id, listing = "tests.token-client-two", "TOKENCLIENT002"
    second = await create_guild_plugin(
        session,
        installed.guild,
        installed.seat.user,
        definition={
            "plugin_kind": "service",
            "service": {"public_id": client_id, "protocol": 1, "scopes": list(scopes)},
        },
        listing_uid=listing,
    )
    await create_plugin_service_registration(
        session, public_id=client_id, listing_uid=listing, jwks=client_jwks()
    )
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        PluginPlacement(install_id=second.id, initiative_id=installed.placed.id)
    )
    await session.commit()
    s = await role_session("app_user")
    await route_as(s, user_id=installed.seat.user.id, guild_id=installed.guild.id)
    row = (await s.exec(select(GuildPlugin).where(GuildPlugin.id == second.id))).one()
    row.granted_scopes = list(scopes)
    s.add(row)
    await s.commit()
    return second, client_id


async def _ref_row(session, ref: str) -> IdentityRef:
    return (await session.exec(select(IdentityRef).where(IdentityRef.ref == ref))).one()


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_every_route_that_names_a_scope_is_an_actor_route():
    """An installed plug-in's request is translated by the route class, so a route
    that admits one is served by it."""
    offenders = [
        f"{sorted(getattr(route, 'methods', ()))} {getattr(route, 'path', route)}"
        for route in app.routes
        if route_plugin_scope(route) is not None and not isinstance(route, ActorRoute)
    ]
    assert offenders == []


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


async def test_an_install_reads_people_and_its_community_by_reference(
    client, session, acting_user, role_session
):
    installed, people = await _setup(session, acting_user, role_session)

    response = await client.get(
        _url(installed.guild.id, "/people"),
        headers={
            **_bearer(installed.guild.id, installed.plugin.id, ["files:read"]),
            # Uncompressed, so the length is the rewritten body's own.
            "Accept-Encoding": "identity",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    named = [body["creator"], *(p["id"] for p in body["people"])]
    assert all(isinstance(ref, str) and ref.startswith("uplu_") for ref in named)
    assert isinstance(body["guild_id"], str) and body["guild_id"].startswith("gplu_")
    assert int(response.headers["content-length"]) == len(response.content)

    for ref, user_id in zip(named, people):
        row = await _ref_row(session, ref)
        assert (row.entity_type, row.entity_id) == (IdentityEntity.user, user_id)
        assert (row.purpose, row.sector_guild_id, row.sector_plugin) == (
            IdentityPurpose.plugin,
            installed.guild.id,
            installed.public_id,
        )
    # The community's reference is the one the install is known to hold.
    assert body["guild_id"] == await plugin_refs.ensure_plugin_guild_ref(
        guild_id=installed.guild.id, public_id=installed.public_id
    )


async def test_the_same_person_is_called_the_same_thing_every_time(
    client, session, acting_user, role_session
):
    installed, _people = await _setup(session, acting_user, role_session)
    headers = _bearer(installed.guild.id, installed.plugin.id, ["files:read"])

    first = await client.get(_url(installed.guild.id, "/people"), headers=headers)
    plugin_refs.forget_cached_install_refs()
    second = await client.get(_url(installed.guild.id, "/people"), headers=headers)

    assert first.json() == second.json()


async def test_a_second_install_sees_different_references(
    client, session, acting_user, role_session
):
    installed, _people = await _setup(session, acting_user, role_session)
    other, other_client = await _second_install(
        session, role_session, installed, ["files:read"]
    )

    mine = await client.get(
        _url(installed.guild.id, "/people"),
        headers=_bearer(installed.guild.id, installed.plugin.id, ["files:read"]),
    )
    theirs = await client.get(
        _url(installed.guild.id, "/people"),
        headers=_bearer(
            installed.guild.id, other.id, ["files:read"], client_id=other_client
        ),
    )

    assert mine.status_code == theirs.status_code == 200, theirs.text
    a, b = mine.json(), theirs.json()
    assert a["creator"] != b["creator"]
    assert a["guild_id"] != b["guild_id"]
    assert {p["id"] for p in a["people"]}.isdisjoint(p["id"] for p in b["people"])


async def test_a_person_reads_row_ids_unchanged(client, session, acting_user):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    _state["people"] = [a.user.id]

    response = await client.get(_url(a.guild.id, "/people"), headers=a.headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "guild_id": a.guild.id,
        "creator": a.user.id,
        "people": [],
        "reviewer": None,
    }


async def test_an_install_is_refused_a_json_response_the_route_built(
    client, session, acting_user, role_session
):
    installed, _people = await _setup(session, acting_user, role_session)

    with pytest.raises(RuntimeError):
        await client.get(
            _url(installed.guild.id, "/raw"),
            headers=_bearer(installed.guild.id, installed.plugin.id, ["files:read"]),
        )


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


async def _refs_for(client, installed) -> dict[str, Any]:
    response = await client.get(
        _url(installed.guild.id, "/people"),
        headers=_bearer(installed.guild.id, installed.plugin.id, ["files:read"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_an_install_names_people_by_reference(
    client, session, acting_user, role_session
):
    installed, people = await _setup(session, acting_user, role_session)
    known = await _refs_for(client, installed)
    refs = [p["id"] for p in known["people"]]

    response = await client.post(
        _url(installed.guild.id, "/assign"),
        params={"reviewer": known["creator"]},
        json={"guild_id": known["guild_id"], "assignees": refs},
        headers=_bearer(installed.guild.id, installed.plugin.id, ["files:write"]),
    )

    assert response.status_code == 200, response.text
    assert _state["received"] == {
        "guild_id": installed.guild.id,
        "assignees": people[1:],
        "reviewer": people[0],
        "actor": "install",
    }
    # And reads back what it sent.
    assert response.json() == {"guild_id": known["guild_id"], "assignees": refs}


async def test_a_person_names_people_by_row_id(client, session, acting_user):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.post(
        _url(a.guild.id, "/assign"),
        params={"reviewer": a.user.id},
        json={"guild_id": a.guild.id, "assignees": [a.user.id]},
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    assert _state["received"]["assignees"] == [a.user.id]
    assert response.json() == {"guild_id": a.guild.id, "assignees": [a.user.id]}


async def test_what_the_install_does_not_hold_is_unprocessable(
    client, session, acting_user, role_session
):
    installed, people = await _setup(session, acting_user, role_session)
    other, _client = await _second_install(
        session, role_session, installed, ["files:read"]
    )
    known = await _refs_for(client, installed)
    foreign = await plugin_refs.ensure_plugin_ref(
        guild_id=installed.guild.id,
        public_id=other.definition["service"]["public_id"],
        user_id=people[1],
    )
    headers = _bearer(installed.guild.id, installed.plugin.id, ["files:write"])

    for assignees, guild in (
        ([foreign], known["guild_id"]),
        ([people[1]], known["guild_id"]),
        (["uplu_" + "x" * 32], known["guild_id"]),
        ([known["creator"]], known["creator"]),
        ([known["guild_id"]], known["guild_id"]),
    ):
        response = await client.post(
            _url(installed.guild.id, "/assign"),
            json={"guild_id": guild, "assignees": assignees},
            headers=headers,
        )
        assert response.status_code == 422, (assignees, guild, response.text)
        assert PluginMessages.REFERENCE_UNKNOWN in {
            error["msg"] for error in response.json()["detail"]
        }
    assert "received" not in _state


async def test_a_replaced_reference_resolves_for_its_grace_window(
    client, session, acting_user, role_session
):
    installed, people = await _setup(session, acting_user, role_session)
    known = await _refs_for(client, installed)
    replaced = known["people"][0]["id"]
    headers = _bearer(installed.guild.id, installed.plugin.id, ["files:write"])

    async def retire(ago: timedelta) -> int:
        await session.exec(
            text(
                "UPDATE public.identity_refs SET retired_at = :at WHERE ref = :ref"
            ).bindparams(at=datetime.now(timezone.utc) - ago, ref=replaced)
        )
        await session.commit()
        response = await client.post(
            _url(installed.guild.id, "/assign"),
            json={"guild_id": known["guild_id"], "assignees": [replaced]},
            headers=headers,
        )
        return response.status_code

    assert await retire(timedelta(days=1)) == 200
    assert _state["received"]["assignees"] == [people[1]]
    assert await retire(REF_GRACE_PERIOD + timedelta(days=1)) == 422


# ---------------------------------------------------------------------------
# Round trips
# ---------------------------------------------------------------------------


async def test_naming_three_people_costs_no_statement_of_its_own(
    client, session, acting_user, role_session
):
    installed, _people = await _setup(session, acting_user, role_session)
    known = await _refs_for(client, installed)
    headers = _bearer(installed.guild.id, installed.plugin.id, ["files:write"])

    with _counting() as statements:
        response = await client.post(
            _url(installed.guild.id, "/assign"),
            json={
                "guild_id": known["guild_id"],
                "assignees": [p["id"] for p in known["people"]],
            },
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert _state["before_handler"] == 2, statements
    # The references it named are in the cache the response reads.
    assert len(statements) == 2, statements


async def test_a_response_mints_once_on_a_cold_cache_and_not_on_a_warm_one(
    client, session, acting_user, role_session
):
    installed, _people = await _setup(session, acting_user, role_session)
    headers = _bearer(installed.guild.id, installed.plugin.id, ["files:read"])

    with _counting() as cold:
        first = await client.get(_url(installed.guild.id, "/people"), headers=headers)
    assert first.status_code == 200, first.text
    assert _state["before_handler"] == 2, cold
    assert len(cold) == 3, cold

    with _counting() as warm:
        second = await client.get(_url(installed.guild.id, "/people"), headers=headers)
    assert second.json() == first.json()
    assert _state["before_handler"] == 2, warm
    assert len(warm) == 2, warm

    # Held in the database, not only in this process: a cold cache reads what
    # the first request minted, in the same one statement.
    plugin_refs.forget_cached_install_refs()
    with _counting() as reread:
        third = await client.get(_url(installed.guild.id, "/people"), headers=headers)
    assert third.json() == first.json()
    assert len(reread) == 3, reread
