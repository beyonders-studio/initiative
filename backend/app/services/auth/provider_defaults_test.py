"""What a deployment answers once, and what a community does to that answer.

The rule under test is the one the design settles on: **the unit of override
is the connection.** A community's own row replaces the deployment's outright —
nothing merges — and a community that has said nothing inherits.
"""

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import auth_context
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.schemas.platform.settings import PlatformProviderDefaultUpdate
from app.services.auth import guild_provider_connections as connections
from app.services.auth import provider_defaults
from app.testing.factories import (
    create_auth_provider,
    create_guild,
    create_guild_membership,
    create_guild_provider_connection,
    create_user,
    get_auth_headers,
)


async def _answered(session: AsyncSession, provider, **fields):
    return await provider_defaults.set_default(
        session, provider.id, PlatformProviderDefaultUpdate(**fields)
    )


async def test_a_community_that_has_not_said_inherits(
    session: AsyncSession,
):
    provider = await create_auth_provider(session, slug="entra", display_name="Entra")
    guild = await create_guild(session)
    await _answered(session, provider, claim="tid", claim_values=["acme-tenant"])

    listed = await connections.list_connections(session, guild_id=guild.id)
    assert [(row.provider_id, row.inherited, row.id) for row in listed] == [
        (provider.id, True, None)
    ]
    assert listed[0].claim == "tid"
    assert listed[0].claim_values == ["acme-tenant"]
    # And its sign-in page offers the button.
    offered = await connections.connected_providers(session, guild_id=guild.id)
    assert [row.id for row in offered] == [provider.id]


async def test_its_own_connection_replaces_the_answer_outright(
    session: AsyncSession,
):
    """Not a merge. The community's narrowing is the only one that applies."""
    provider = await create_auth_provider(session, slug="entra")
    guild = await create_guild(session)
    await _answered(session, provider, claim="tid", claim_values=["acme-tenant"])
    await create_guild_provider_connection(
        session,
        guild=guild,
        provider=provider,
        claim="groups",
        claim_values=["eng-platform"],
    )

    listed = await connections.list_connections(session, guild_id=guild.id)
    assert len(listed) == 1
    assert listed[0].inherited is False
    assert listed[0].claim == "groups"
    assert listed[0].claim_values == ["eng-platform"]


async def test_connecting_with_the_button_off_declines_the_answer(
    session: AsyncSession,
):
    """How a community says no. Its own row shadows the default whatever it
    says, so an unenabled one withdraws the inherited button."""
    provider = await create_auth_provider(session, slug="entra")
    guild = await create_guild(session)
    await _answered(session, provider, claim="tid", claim_values=["acme-tenant"])
    await create_guild_provider_connection(
        session, guild=guild, provider=provider, enabled=False
    )

    offered = await connections.connected_providers(session, guild_id=guild.id)
    assert offered == []


async def test_a_withdrawn_answer_reaches_only_those_who_inherited_it(
    session: AsyncSession,
):
    provider = await create_auth_provider(session, slug="entra")
    inheritor = await create_guild(session)
    speaker = await create_guild(session)
    await create_guild_provider_connection(
        session, guild=speaker, provider=provider, claim="hd", claim_values=["ours.com"]
    )
    await _answered(session, provider, claim="tid", claim_values=["acme-tenant"])

    await provider_defaults.clear_default(session, provider.id)

    assert await connections.list_connections(session, guild_id=inheritor.id) == []
    kept = await connections.list_connections(session, guild_id=speaker.id)
    assert [row.claim for row in kept] == ["hd"]


async def test_an_answer_switched_off_is_inherited_by_nobody(
    session: AsyncSession,
):
    provider = await create_auth_provider(session, slug="entra")
    guild = await create_guild(session)
    await _answered(session, provider, claim="tid", claim_values=["t"], enabled=False)

    assert await connections.connected_providers(session, guild_id=guild.id) == []


async def test_only_the_operator_answers(client: AsyncClient, session: AsyncSession):
    provider = await create_auth_provider(session, slug="entra")
    admin = await create_user(session)
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=CommunityRole.superadmin
    )
    path = f"/api/v1/settings/auth/providers/{provider.id}/default"

    refused = await client.put(
        path, headers=get_auth_headers(admin), json={"claim": None}
    )
    assert refused.status_code == 403, refused.text

    owner = await create_user(session, role=UserRole.owner)
    accepted = await client.put(
        path,
        headers=get_auth_headers(owner),
        json={"claim": "tid", "claim_values": ["acme-tenant"]},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["claim_values"] == ["acme-tenant"]


async def test_an_answer_is_both_halves_or_neither(
    client: AsyncClient, session: AsyncSession
):
    provider = await create_auth_provider(session, slug="entra")
    owner = await create_user(session, role=UserRole.owner)

    refused = await client.put(
        f"/api/v1/settings/auth/providers/{provider.id}/default",
        headers=get_auth_headers(owner),
        json={"claim": "tid"},
    )
    assert refused.status_code == 422, refused.text


async def test_the_gate_reads_the_answer_for_a_community_that_has_none(
    session: AsyncSession,
):
    """The SQL gate, not just the listing. An inherited narrowing decides who
    a community counts as its own, exactly as its own would."""
    provider = await create_auth_provider(session, slug="entra")
    guild = await create_guild(session)
    await _answered(session, provider, claim="tid", claim_values=["acme-tenant"])

    async def admits(tenant: str) -> bool:
        auth_context.record(
            satisfied_providers=frozenset({provider.id}),
            satisfied_claims={str(provider.id): {"tid": [tenant]}},
        )
        try:
            return await connections.admits_this_session(session, guild_id=guild.id)
        finally:
            auth_context.reset()

    assert await admits("acme-tenant") is True
    assert await admits("someone-else") is False


async def test_its_own_narrowing_is_what_the_gate_asks(session: AsyncSession):
    """The shadowing rule, at the gate. A community that narrowed the provider
    itself is asked its own question, not the deployment's."""
    provider = await create_auth_provider(session, slug="entra")
    guild = await create_guild(session)
    await _answered(session, provider, claim="tid", claim_values=["acme-tenant"])
    await create_guild_provider_connection(
        session,
        guild=guild,
        provider=provider,
        claim="tid",
        claim_values=["a-different-tenant"],
    )

    async def admits(tenant: str) -> bool:
        auth_context.record(
            satisfied_providers=frozenset({provider.id}),
            satisfied_claims={str(provider.id): {"tid": [tenant]}},
        )
        try:
            return await connections.admits_this_session(session, guild_id=guild.id)
        finally:
            auth_context.reset()

    assert await admits("a-different-tenant") is True
    # The deployment's answer no longer applies here.
    assert await admits("acme-tenant") is False
