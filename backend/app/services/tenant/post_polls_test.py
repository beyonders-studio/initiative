"""The poll row is the lock its ballots and its edits queue on.

Editing the question, casting a ballot and retracting one each decide what to
write by reading what has already been answered, so each holds the poll's row
for the whole of its transaction and one poll's writes proceed in turn.

These cases hold the two properties that rests on: the lock is really taken — a
second transaction waits for it, and a free row does not — and whether the poll
still takes votes is decided by the database's clock in the statement that takes
the row, rather than from whatever the caller had loaded.
"""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.post_poll import PostPoll
from app.services.tenant import post_polls as post_polls_service
from app.testing import (
    create_guild,
    create_initiative,
    create_post,
    create_post_poll,
    create_user,
)
from app.testing.schema_harness import route_session_to_guild

#: Long enough that a lock genuinely held is still held when the second
#: transaction gives up, short enough that the case is not a pause.
_LOCK_TIMEOUT = "400ms"


async def _poll(session: AsyncSession) -> tuple[int | None, PostPoll]:
    creator = await create_user(session)
    guild = await create_guild(session, creator=creator)
    initiative = await create_initiative(session, guild=guild, creator=creator)
    post = await create_post(session, initiative, creator)
    poll = await create_post_poll(session, post)
    return guild.id, poll


async def test_the_lock_is_really_taken(session: AsyncSession, engine):
    """A second transaction cannot have the row while the first holds it.

    Asserted by waiting for it with a timeout rather than by reading the SQL:
    what matters is that the database queues the two, not that a particular
    clause was written.
    """
    guild_id, poll = await _poll(session)
    await session.commit()

    await post_polls_service.lock_poll(session, poll, guild_id=guild_id)

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as other:
        await route_session_to_guild(other, guild_id)
        await other.exec(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
        with pytest.raises(Exception) as blocked:
            await post_polls_service.lock_poll(other, poll, guild_id=guild_id)
        assert "lock" in str(blocked.value).lower()
        await other.rollback()

    await session.rollback()


async def test_a_free_row_is_not_a_wait(session: AsyncSession, engine):
    """The other half of the case above: with nobody holding it, the same call
    on the same row returns at once. Without this, a lock that was never taken
    and a lock that is always taken would look the same."""
    guild_id, poll = await _poll(session)
    await session.commit()

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as other:
        await route_session_to_guild(other, guild_id)
        await other.exec(text(f"SET LOCAL lock_timeout = '{_LOCK_TIMEOUT}'"))
        await asyncio.wait_for(
            post_polls_service.lock_poll(other, poll, guild_id=guild_id), timeout=5
        )
        await other.rollback()


async def test_the_deadline_is_the_databases_clock(session: AsyncSession):
    """``lock_open_poll`` answers "does this still take votes?" once it holds
    the poll's turnstile, so the close time is read at the moment the ballot's
    transaction acquires it rather than whenever the row was loaded."""
    guild_id, poll = await _poll(session)
    await session.commit()

    assert (
        await post_polls_service.lock_open_poll(session, poll, guild_id=guild_id)
        is True
    )

    # Move the deadline into the past without touching the loaded object: the
    # gate must read the row, not the copy in memory.
    await session.exec(
        text(
            "UPDATE post_polls SET closes_at = now() - interval '1 minute' WHERE id = :i"
        ).bindparams(i=poll.id)
    )
    assert poll.is_closed() is False  # the in-memory copy still says open
    assert (
        await post_polls_service.lock_open_poll(session, poll, guild_id=guild_id)
        is False
    )

    await session.rollback()


async def test_a_poll_with_no_deadline_always_takes_votes(session: AsyncSession):
    guild_id, poll = await _poll(session)
    await session.commit()

    assert poll.closes_at is None
    assert (
        await post_polls_service.lock_open_poll(session, poll, guild_id=guild_id)
        is True
    )

    await session.rollback()


async def test_the_deadline_is_the_wall_clock_not_the_transactions_start(
    session: AsyncSession,
):
    """A ballot is measured by the deadline in force as it is about to be
    written, not by when its request arrived.

    Postgres fixes ``now()`` at the start of a transaction, and a ballot's
    transaction starts before it has loaded the post, authorized it, and waited
    its turn for the poll's row. This sets a deadline that passes *during* one
    transaction and asks the gate afterwards: read against the transaction's own
    beginning the poll is still open, and against the wall clock it is not.
    """
    guild_id, poll = await _poll(session)
    await session.commit()

    # Inside one transaction: a deadline a moment away, then wait past it.
    await session.exec(
        text(
            "UPDATE post_polls SET closes_at = clock_timestamp() + interval '150 milliseconds' "
            "WHERE id = :i"
        ).bindparams(i=poll.id)
    )
    await asyncio.sleep(0.5)

    # `now()` here is this transaction's start — earlier than the deadline that
    # was just written, so a transaction-time comparison would still say open.
    still_open_by_transaction_time = (
        await session.exec(
            text("SELECT closes_at > now() FROM post_polls WHERE id = :i").bindparams(
                i=poll.id
            )
        )
    ).one()
    assert still_open_by_transaction_time[0] is True

    assert (
        await post_polls_service.lock_open_poll(session, poll, guild_id=guild_id)
        is False
    )

    await session.rollback()
