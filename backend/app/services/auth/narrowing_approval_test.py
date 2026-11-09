"""Agreeing a community's claim values: what waits for it, and what does not."""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import Guild
from app.models.platform.guild_provider_connection import GuildProviderConnection
from app.schemas.platform.settings import (
    CommunityProviderConnectionCreate,
    CommunityProviderConnectionUpdate,
)
from app.services.auth import guild_provider_connections as connections
from app.services.auth import narrowing_approval
from app.testing import (
    NARROWED_CLAIM,
    NARROWED_VALUE,
    create_auth_provider,
    create_guild,
    create_guild_provider_connection,
    create_user,
)


async def _connection(session: AsyncSession, **overrides) -> GuildProviderConnection:
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp")
    return await create_guild_provider_connection(
        session, guild=guild, provider=provider, **overrides
    )


async def test_a_new_connection_is_not_agreed_yet(session: AsyncSession):
    """The community wrote the values; nobody outside it has said anything.

    Through the service rather than the factory, which makes one that works.
    """
    guild = await create_guild(session)
    provider = await create_auth_provider(session, slug="corp")
    actor = await create_user(session)

    await connections.create_connection(
        session,
        CommunityProviderConnectionCreate(
            provider_id=provider.id,
            claim=NARROWED_CLAIM,
            claim_values=[NARROWED_VALUE],
        ),
        guild_id=guild.id,
        actor_user_id=actor.id,
    )

    row = (
        await session.exec(
            select(GuildProviderConnection).where(
                GuildProviderConnection.guild_id == guild.id
            )
        )
    ).one()
    assert row.narrowing_approved_at is None


async def test_agreeing_records_who_said_so(session: AsyncSession):
    staff = await create_user(session)
    row = await _connection(session, narrowing_approved_at=None)

    agreed = await narrowing_approval.agree(
        session, row.id, agreed=True, actor_user_id=staff.id
    )

    assert agreed.narrowing_approved_at is not None
    assert agreed.narrowing_approved_by == staff.id


async def test_withdrawing_leaves_the_values_alone(session: AsyncSession):
    """What stops is joining people on arrival, not the connection."""
    staff = await create_user(session)
    row = await _connection(session, auto_join=True)
    await narrowing_approval.agree(session, row.id, agreed=True, actor_user_id=staff.id)

    withdrawn = await narrowing_approval.agree(
        session, row.id, agreed=False, actor_user_id=staff.id
    )

    assert withdrawn.narrowing_approved_at is None
    assert withdrawn.claim == NARROWED_CLAIM
    assert withdrawn.claim_values == [NARROWED_VALUE]
    assert withdrawn.auto_join is True
    assert withdrawn.enabled is True


async def test_writing_different_values_asks_again(session: AsyncSession):
    """An agreement is about the values that were agreed."""
    staff = await create_user(session)
    row = await _connection(session)
    await narrowing_approval.agree(session, row.id, agreed=True, actor_user_id=staff.id)

    await connections.update_connection(
        session,
        row.id,
        CommunityProviderConnectionUpdate(claim_values=["somewhere-else.example"]),
        guild_id=row.guild_id,
        actor_user_id=staff.id,
    )

    after = (
        await session.exec(
            select(GuildProviderConnection).where(GuildProviderConnection.id == row.id)
        )
    ).one()
    assert after.narrowing_approved_at is None
    assert after.narrowing_approved_by is None


async def test_writing_the_same_values_keeps_the_agreement(session: AsyncSession):
    """Saving the page without touching the values is not a new question."""
    staff = await create_user(session)
    row = await _connection(session)
    await narrowing_approval.agree(session, row.id, agreed=True, actor_user_id=staff.id)

    await connections.update_connection(
        session,
        row.id,
        CommunityProviderConnectionUpdate(auto_join=True),
        guild_id=row.guild_id,
        actor_user_id=staff.id,
    )

    after = (
        await session.exec(
            select(GuildProviderConnection).where(GuildProviderConnection.id == row.id)
        )
    ).one()
    assert after.narrowing_approved_at is not None
    assert after.auto_join is True


async def test_nobody_joins_on_arrival_until_the_values_are_agreed(
    session: AsyncSession,
):
    """Admitting people the community already has does not wait; placing
    somebody in it does."""
    from app.services.auth.guild_provider_connections import join_on_arrival

    arriving = await create_user(session)
    row = await _connection(session, auto_join=True, narrowing_approved_at=None)
    claims = {NARROWED_CLAIM: NARROWED_VALUE}

    # The connection counts this arrival as its own; only the agreement is
    # missing, so nothing happens.
    assert row.admits(claims) is True
    joined = await join_on_arrival(
        session, provider_id=row.provider_id, user_id=arriving.id, claims=claims
    )
    assert joined == []

    staff = await create_user(session)
    await narrowing_approval.agree(session, row.id, agreed=True, actor_user_id=staff.id)

    joined = await join_on_arrival(
        session, provider_id=row.provider_id, user_id=arriving.id, claims=claims
    )
    assert joined == [row.guild_id]

    # A community they are already in is not a new arrival.
    joined = await join_on_arrival(
        session, provider_id=row.provider_id, user_id=arriving.id, claims=claims
    )
    assert joined == []


async def test_a_community_that_refuses_an_arrival_leaves_the_sign_in_alone(
    session: AsyncSession,
):
    """A listed community keeps out an account whose age answer is under its
    minimum; joining on arrival skips it rather than failing the sign-in."""
    from datetime import UTC, datetime

    from app.services.auth.guild_provider_connections import join_on_arrival
    from app.services.platform import rules

    await rules.put(session, "community_directory_enabled", True)
    await rules.put(session, "community_age_gate_enabled", True)
    row = await _connection(session, auto_join=True)
    guild = await session.get(Guild, row.guild_id)
    assert guild is not None
    guild.is_community = True
    guild.categories = ["other"]
    guild.has_adult_content = False
    session.add(guild)
    arriving = await create_user(session, age_confirmed_at=None)
    arriving.age_below_minimum_at = datetime.now(UTC)
    session.add(arriving)
    await session.commit()

    joined = await join_on_arrival(
        session,
        provider_id=row.provider_id,
        user_id=arriving.id,
        claims={NARROWED_CLAIM: NARROWED_VALUE},
    )
    assert joined == []
