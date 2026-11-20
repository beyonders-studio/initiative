"""Connections, message requests, and what survives losing a leg of can_ask.

The three worth keeping are the ones the design turns on: a connection is
permission to ask rather than a channel; leaving a shared community revokes an
open channel unless the pair connected first; and removing a connection re-tests
the grant rather than deleting it, so two co-members keep talking.
"""

import pytest
from sqlalchemy import text

from app.db import post_commit
from app.models.platform.contact_grant import (
    ContactGrant,
    ContactGrantKind,
    ContactGrantState,
    canonical_pair,
)
from app.models.platform.guild import GuildMembership
from app.models.platform.user_dm_settings import DmPolicy
from app.services.platform import contact_grants as contact_grants_service
from app.testing import create_guild, create_guild_membership, create_user


async def _policy(session, user, policy: DmPolicy) -> None:
    await session.exec(
        text(
            "UPDATE public.user_dm_settings SET dm_policy = CAST(:p AS user_dm_policy) "
            "WHERE user_id = :u"
        ).bindparams(p=policy.value, u=user.id)
    )
    await session.flush()


async def _as(session, user) -> None:
    """Act as this account, the way a routed request does.

    The entry points read the caller from ``app.current_user_id`` rather than
    taking one, so a service test has to say who is asking.
    """
    await session.exec(
        text("SELECT set_config('app.current_user_id', :v, true)").bindparams(
            v=str(user.id)
        )
    )


async def _grant(session, a, b, kind):
    low, high = canonical_pair(a.id, b.id)
    return await session.get(ContactGrant, (low, high, kind))


async def _drop_membership(session, *, guild_id: int, user_id: int) -> None:
    """Leave the community, and run the sweep the guild path runs.

    The real ``remove_user_from_guild`` also tears down initiative membership
    inside the guild schema, which wants a routed session; what is under test
    here is the rule, so this drops the row and calls the same sweep.
    ``test_the_guild_path_runs_the_sweep`` covers the wiring.
    """
    row = await session.get(GuildMembership, (guild_id, user_id))
    if row is not None:
        await session.delete(row)
    # Committed before the sweep: it runs on its own session, so it must be
    # looking at the state the change left behind.
    await session.commit()
    await contact_grants_service.revoke_stale_message_grants(session, user_id=user_id)


async def _connect(session, a, b):
    """Both halves of a real connection, through the service."""
    await _as(session, a)
    await contact_grants_service.request(
        session, actor_id=a.id, target_id=b.id, kind=ContactGrantKind.connection
    )
    await _as(session, b)
    return await contact_grants_service.accept(
        session, actor_id=b.id, other_id=a.id, kind=ContactGrantKind.connection
    )


# ------------------------------------------------------- what a connection is ---


async def test_a_connection_is_permission_to_ask_not_a_channel(session):
    """The model, on its own: a connection row alone leaves the pair closed."""
    a = await create_user(session)
    b = await create_user(session)
    await _policy(session, a, DmPolicy.private)
    await _policy(session, b, DmPolicy.private)

    low, high = canonical_pair(a.id, b.id)
    session.add(
        ContactGrant(
            user_id_low=low,
            user_id_high=high,
            kind=ContactGrantKind.connection,
            state=ContactGrantState.accepted,
            requested_by=a.id,
        )
    )
    await session.flush()

    await _as(session, a)
    assert await contact_grants_service._may_message(session, b.id)
    assert await _grant(session, a, b, ContactGrantKind.message) is None


async def test_a_crossing_request_becomes_an_accept(session):
    a = await create_user(session)
    b = await create_user(session)

    await _as(session, a)
    await contact_grants_service.request(
        session, actor_id=a.id, target_id=b.id, kind=ContactGrantKind.connection
    )
    await _as(session, b)
    grant = await contact_grants_service.request(
        session, actor_id=b.id, target_id=a.id, kind=ContactGrantKind.connection
    )
    assert grant.state is ContactGrantState.accepted


async def test_an_unconfirmed_age_cannot_connect(session):
    a = await create_user(session, age_confirmed_at=None)
    b = await create_user(session)
    await _as(session, a)
    with pytest.raises(contact_grants_service.ContactGrantError):
        await contact_grants_service.request(
            session, actor_id=a.id, target_id=b.id, kind=ContactGrantKind.connection
        )


# ------------------------------------------------------------- losing a leg ---


async def test_leaving_the_community_revokes_an_open_channel(session):
    guild = await create_guild(session)
    a = await create_user(session)
    b = await create_user(session)
    for user in (a, b):
        await create_guild_membership(session, user=user, guild=guild)
        await _policy(session, user, DmPolicy.community)
    await session.commit()

    await _as(session, a)
    await contact_grants_service.request(
        session, actor_id=a.id, target_id=b.id, kind=ContactGrantKind.message
    )
    await _as(session, b)
    await contact_grants_service.accept(
        session, actor_id=b.id, other_id=a.id, kind=ContactGrantKind.message
    )
    assert await _grant(session, a, b, ContactGrantKind.message) is not None

    await _drop_membership(session, guild_id=guild.id, user_id=b.id)

    assert not await _grant_exists_fresh(a, b, ContactGrantKind.message)


async def test_a_connection_carries_the_channel_through_leaving(session):
    guild = await create_guild(session)
    a = await create_user(session)
    b = await create_user(session)
    for user in (a, b):
        await create_guild_membership(session, user=user, guild=guild)
        await _policy(session, user, DmPolicy.community)
    await session.commit()

    await _connect(session, a, b)
    assert await _grant(session, a, b, ContactGrantKind.message) is not None

    await _drop_membership(session, guild_id=guild.id, user_id=b.id)

    assert await _grant_exists_fresh(a, b, ContactGrantKind.message)


async def test_removing_a_connection_re_tests_rather_than_deletes(session):
    """A ``private`` pair lose the channel, because the connection was the only
    leg. Co-members on ``community`` keep it (``dm_test``)."""
    c = await create_user(session)
    d = await create_user(session)
    await _policy(session, c, DmPolicy.private)
    await _policy(session, d, DmPolicy.private)
    await session.commit()
    await _connect(session, c, d)

    await _as(session, c)
    await contact_grants_service.remove(
        session, actor_id=c.id, other_id=d.id, kind=ContactGrantKind.connection
    )
    assert not await _grant_exists_fresh(c, d, ContactGrantKind.message)


async def test_going_private_revokes_a_community_channel(session):
    guild = await create_guild(session)
    a = await create_user(session)
    b = await create_user(session)
    for user in (a, b):
        await create_guild_membership(session, user=user, guild=guild)
        await _policy(session, user, DmPolicy.community)
    await session.commit()

    await _as(session, a)
    await contact_grants_service.request(
        session, actor_id=a.id, target_id=b.id, kind=ContactGrantKind.message
    )
    await _as(session, b)
    await contact_grants_service.accept(
        session, actor_id=b.id, other_id=a.id, kind=ContactGrantKind.message
    )

    await _policy(session, a, DmPolicy.private)
    await session.commit()
    dropped = await contact_grants_service.revoke_stale_message_grants(
        session, user_id=a.id
    )

    assert dropped == 1
    assert not await _grant_exists_fresh(a, b, ContactGrantKind.message)


async def _open_channel_between_co_members(session):
    """Two co-members on ``community`` with an accepted message grant."""
    guild = await create_guild(session)
    a = await create_user(session)
    b = await create_user(session)
    for user in (a, b):
        await create_guild_membership(session, user=user, guild=guild)
        await _policy(session, user, DmPolicy.community)
    await session.commit()

    await _as(session, a)
    await contact_grants_service.request(
        session, actor_id=a.id, target_id=b.id, kind=ContactGrantKind.message
    )
    await _as(session, b)
    await contact_grants_service.accept(
        session, actor_id=b.id, other_id=a.id, kind=ContactGrantKind.message
    )
    return guild, a, b


async def _grant_exists_fresh(a, b, kind) -> bool:
    """Ask a connection of its own.

    The sweep commits on a session of its own, so the answer is read on one too
    rather than through the test session's identity map.
    """
    from app.db.session import SystemSessionLocal

    low, high = canonical_pair(a.id, b.id)
    async with SystemSessionLocal() as system_session:
        return (await system_session.get(ContactGrant, (low, high, kind))) is not None


async def test_the_sweep_waits_for_the_commit(session):
    """The ordering the queue exists for.

    A sweep that ran against the uncommitted delete would still see the
    membership, find the pair allowed, and keep a channel whose only leg has
    just gone — the failure this replaces a source-text check with.
    """
    guild, a, b = await _open_channel_between_co_members(session)

    membership = await session.get(GuildMembership, (guild.id, b.id))
    await session.delete(membership)
    contact_grants_service.queue_stale_grant_sweep(session, b.id)

    # Still there: the delete has not landed, so nothing has been re-tested.
    assert await _grant_exists_fresh(a, b, ContactGrantKind.message)

    await session.commit()
    await post_commit.settle(session)

    assert not await _grant_exists_fresh(a, b, ContactGrantKind.message)


async def test_a_rollback_discards_its_own_sweeps(session, monkeypatch):
    """A change that did not happen revokes nothing.

    A rolled-back savepoint drops the sweep queued inside it and keeps the
    transaction's other one; a rolled-back transaction drops them all.
    """
    swept: list[int] = []

    async def _sweep(_session, *, user_id: int) -> int:
        swept.append(user_id)
        return 0

    monkeypatch.setattr(contact_grants_service, "revoke_stale_message_grants", _sweep)

    contact_grants_service.queue_stale_grant_sweep(session, 7)
    savepoint = await session.begin_nested()
    contact_grants_service.queue_stale_grant_sweep(session, 8)
    await savepoint.rollback()
    await session.commit()
    await post_commit.settle(session)
    assert swept == [7]

    contact_grants_service.queue_stale_grant_sweep(session, 9)
    await session.rollback()
    await session.commit()
    await post_commit.settle(session)
    assert swept == [7]
