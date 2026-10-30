"""What a community can say about who signs in, and what it cannot.

The shape under test: **the operator holds providers, a community connects to
one.** So nothing here takes an issuer, a client id or a secret, a community
sees only the providers it is allowed to, and the narrowing it sets is what
decides whether somebody arriving is one of theirs.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AuthProviderMessages, GuildMessages
from app.models.platform.guild import CommunityRole
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_guild_provider_connection,
    create_user,
    get_auth_headers,
)
from app.core.login_methods import LoginMethod
from app.core.rules import SURFACE_CUSTOM_ROLES, SetBy, SignInRequirement
from app.services.platform import rules


async def _seat(session: AsyncSession, *, auth_options: list[str] | None = None):
    """A community with somebody in the seat that decides who may enter."""
    admin = await create_user(session)
    kwargs = {} if auth_options is None else {"auth_options": auth_options}
    guild = await create_guild(session, creator=admin, **kwargs)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.superadmin
    )
    return admin, guild


def _base(guild_id: int) -> str:
    return f"/api/v1/communities/{guild_id}/auth/connections"


async def test_the_seat_connects_narrows_and_disconnects(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(session, slug="google", display_name="Google")
    headers = get_auth_headers(admin)

    created = await client.post(
        _base(guild.id),
        headers=headers,
        json={"provider_id": provider.id, "claim": "hd", "claim_values": ["morels.me"]},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["provider_display_name"] == "Google"
    assert body["claim"] == "hd"
    assert body["claim_values"] == ["morels.me"]
    # Nothing about the provider's internals comes back on a community's
    # surface, because a community holds none of it.
    assert "issuer" not in body
    assert "client_id" not in body

    listed = await client.get(_base(guild.id), headers=headers)
    assert [row["provider_slug"] for row in listed.json()] == ["google"]

    narrowed = await client.patch(
        f"{_base(guild.id)}/{body['id']}",
        headers=headers,
        json={"claim_values": ["morels.me", "morels.dev"]},
    )
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["claim_values"] == ["morels.me", "morels.dev"]

    gone = await client.delete(f"{_base(guild.id)}/{body['id']}", headers=headers)
    assert gone.status_code == 204, gone.text
    assert await client.get(_base(guild.id), headers=headers) is not None
    assert (await client.get(_base(guild.id), headers=headers)).json() == []


async def test_a_community_sees_every_way_in_the_deployment_offers(
    client: AsyncClient, session: AsyncSession
):
    """The picker is every way in the deployment offers. They are all public
    sign-in buttons; what a community decides is which arrivals are its own."""
    admin, guild = await _seat(session)
    google = await create_auth_provider(session, slug="google", display_name="Google")
    theirs = await create_auth_provider(
        session, slug="acme-okta", display_name="Acme Okta"
    )
    await create_guild_provider_connection(session, guild=guild, provider=theirs)

    response = await client.get(
        f"{_base(guild.id)}/available", headers=get_auth_headers(admin)
    )

    assert response.status_code == 200, response.text
    names = {row["display_name"] for row in response.json()}
    assert {"Google", "Acme Okta"} <= names
    assert google.id in {row["id"] for row in response.json()}


async def test_the_picker_says_nothing_a_sign_in_page_does_not(
    client: AsyncClient, session: AsyncSession
):
    """A community picks by name. No issuer, no client, no secret."""
    admin, guild = await _seat(session)
    await create_auth_provider(session, slug="google", display_name="Google")

    response = await client.get(
        f"{_base(guild.id)}/available", headers=get_auth_headers(admin)
    )

    assert response.status_code == 200, response.text
    row = next(r for r in response.json() if r["display_name"] == "Google")
    assert set(row) == {"id", "display_name", "icon", "login_ready"}


async def test_an_enabled_connection_says_who_counts(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(session, slug="google")
    headers = get_auth_headers(admin)

    # A narrowing is both halves or neither; half of one narrows nothing.
    half = await client.post(
        _base(guild.id),
        headers=headers,
        json={"provider_id": provider.id, "claim": "hd", "claim_values": []},
    )
    assert half.status_code == 422, half.text
    assert half.json()["detail"] == AuthProviderMessages.CONNECTION_HALF_NARROWED

    # And neither half is refused too, while the connection is on:
    # communities here are separate tenants, so a provider vouching for
    # somebody is not the same as them belonging to this one.
    neither = await client.post(
        _base(guild.id), headers=headers, json={"provider_id": provider.id}
    )
    assert neither.status_code == 422, neither.text
    assert neither.json()["detail"] == AuthProviderMessages.CONNECTION_NEEDS_NARROWING

    # Off, it may name nobody: that is how a community declines the
    # deployment's answer for a provider, and it admits nobody by being off.
    declined = await client.post(
        _base(guild.id),
        headers=headers,
        json={"provider_id": provider.id, "enabled": False},
    )
    assert declined.status_code == 201, declined.text
    assert declined.json()["claim"] is None


async def test_a_community_connects_to_a_provider_once(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(session, slug="google")
    await create_guild_provider_connection(session, guild=guild, provider=provider)

    again = await client.post(
        _base(guild.id),
        headers=get_auth_headers(admin),
        json={
            "provider_id": provider.id,
            "claim": "hd",
            "claim_values": ["example.com"],
        },
    )

    # Two narrowings of one provider would be two answers to one question.
    assert again.status_code == 409, again.text
    assert again.json()["detail"] == AuthProviderMessages.CONNECTION_EXISTS


async def test_an_ordinary_admin_reads_but_does_not_connect(
    client: AsyncClient, session: AsyncSession
):
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.admin
    )
    provider = await create_auth_provider(session, slug="google")
    headers = get_auth_headers(admin)

    assert (await client.get(_base(guild.id), headers=headers)).status_code == 200
    refused = await client.post(
        _base(guild.id),
        headers=headers,
        json={
            "provider_id": provider.id,
            "claim": "hd",
            "claim_values": ["example.com"],
        },
    )
    assert refused.status_code == 403, refused.text


async def test_the_surface_404s_when_the_option_is_not_granted(
    client: AsyncClient, session: AsyncSession
):
    """Without the operator's grant the whole surface 404s — and the
    connections a community already has are left intact, so its members keep
    signing in through them."""
    admin, guild = await _seat(session, auth_options=[])
    provider = await create_auth_provider(session, slug="google")
    connection = await create_guild_provider_connection(
        session, guild=guild, provider=provider
    )
    headers = get_auth_headers(admin)

    assert (await client.get(_base(guild.id), headers=headers)).status_code == 404
    assert (
        await client.get(f"{_base(guild.id)}/available", headers=headers)
    ).status_code == 404
    assert (
        await client.delete(f"{_base(guild.id)}/{connection.id}", headers=headers)
    ).status_code == 404


async def test_one_communitys_connection_is_not_anothers_to_change(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    _, other_guild = await _seat(session)
    provider = await create_auth_provider(session, slug="google")
    theirs = await create_guild_provider_connection(
        session, guild=other_guild, provider=provider
    )

    response = await client.patch(
        f"{_base(guild.id)}/{theirs.id}",
        headers=get_auth_headers(admin),
        json={"enabled": False},
    )

    # Somebody else's is indistinguishable from one that is not there.
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == AuthProviderMessages.CONNECTION_NOT_FOUND


# ── What a requirement keeps ───────────────────────────────────────────────


@pytest.mark.parametrize("half", ["", "guest_"], ids=["members", "guests"])
async def test_a_required_provider_cannot_be_disconnected(
    client: AsyncClient, session: AsyncSession, half: str
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(session, slug="corp")
    connection = await create_guild_provider_connection(
        session, guild=guild, provider=provider
    )
    await rules.put(
        session,
        f"{half}auth_policy",
        SignInRequirement("required", provider.id),
        guild_id=guild.id,
    )
    await session.commit()

    response = await client.delete(
        f"{_base(guild.id)}/{connection.id}", headers=get_auth_headers(admin)
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == AuthProviderMessages.IN_USE


async def test_a_required_provider_cannot_be_disabled(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(session, slug="corp")
    connection = await create_guild_provider_connection(
        session, guild=guild, provider=provider
    )
    await rules.put(
        session,
        "auth_policy",
        SignInRequirement("required", provider.id),
        guild_id=guild.id,
    )
    await session.commit()

    response = await client.patch(
        f"{_base(guild.id)}/{connection.id}",
        headers=get_auth_headers(admin),
        json={"enabled": False},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == AuthProviderMessages.IN_USE


async def test_the_last_connection_for_an_sso_requirement_cannot_be_removed(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    provider = await create_auth_provider(session, slug="corp")
    connection = await create_guild_provider_connection(
        session, guild=guild, provider=provider
    )
    await rules.put(
        session,
        "auth_policy",
        SignInRequirement("required", None, frozenset({LoginMethod.sso})),
        guild_id=guild.id,
    )
    await session.commit()

    response = await client.delete(
        f"{_base(guild.id)}/{connection.id}", headers=get_auth_headers(admin)
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == AuthProviderMessages.IN_USE


async def test_an_sso_requirement_allows_one_of_multiple_connections_to_be_removed(
    client: AsyncClient, session: AsyncSession
):
    admin, guild = await _seat(session)
    first = await create_auth_provider(session, slug="first")
    second = await create_auth_provider(session, slug="second")
    connection = await create_guild_provider_connection(
        session, guild=guild, provider=first
    )
    await create_guild_provider_connection(session, guild=guild, provider=second)
    await rules.put(
        session,
        "auth_policy",
        SignInRequirement("required", None, frozenset({LoginMethod.sso})),
        guild_id=guild.id,
    )
    await session.commit()

    response = await client.delete(
        f"{_base(guild.id)}/{connection.id}", headers=get_auth_headers(admin)
    )

    assert response.status_code == 204, response.text


async def test_the_seat_orders_the_groups_that_give_custom_roles(
    client: AsyncClient, session: AsyncSession
):
    """Rules naming which custom role a group gives: added after the others,
    put in a new order, and closed with the rest of the community's custom
    roles."""
    admin, guild = await _seat(session)
    provider = await create_auth_provider(session, slug="corp")
    await create_guild_provider_connection(session, guild=guild, provider=provider)
    await session.commit()
    headers = get_auth_headers(admin)
    roles = f"/api/v1/c/{guild.id}/custom-roles/"
    doors = (
        await client.post(
            roles,
            headers=headers,
            json={"name": "Doors", "base_rung": "member", "surfaces": ["invites"]},
        )
    ).json()["id"]
    url = f"/api/v1/communities/{guild.id}/auth/role-rules"

    ids = []
    for group in ("staff", "crew"):
        made = await client.post(
            url,
            headers=headers,
            json={"provider_id": provider.id, "claim_value": group, "role_id": doors},
        )
        assert made.status_code == 201, made.text
        ids.append(made.json()["id"])
    # A sign-in matches a group whatever its capitals, so a rule does too.
    again = await client.post(
        url,
        headers=headers,
        json={"provider_id": provider.id, "claim_value": "Staff", "role_id": doors},
    )
    assert again.status_code == 409

    ordered = await client.put(
        f"{url}/order", headers=headers, json={"rule_ids": list(reversed(ids))}
    )
    assert ordered.status_code == 200, ordered.text
    assert [r["claim_value"] for r in ordered.json()] == ["crew", "staff"]

    await rules.put(
        session,
        SURFACE_CUSTOM_ROLES,
        False,
        guild_id=guild.id,
        set_by=SetBy.deployment,
    )
    await session.commit()
    closed = await client.delete(f"{url}/{ids[0]}", headers=headers)
    assert closed.status_code == 403
    assert closed.json()["detail"] == GuildMessages.COMMUNITY_SURFACE_CLOSED
