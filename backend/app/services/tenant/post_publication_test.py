"""Tests for the publication worker — the moment a scheduled notice goes up.

Three things matter here and nothing else does: a notice due now is published
exactly once, a notice not yet due is left alone, and the people it reaches are
the ones it was shared with.
"""

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.post import Post
from app.models.tenant.post_poll import PostPoll
from app.models.tenant.resource_grant import ResourceGrant
from app.services.tenant.post_publication import publish_due_posts
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_post,
    create_post_poll,
    create_resource_grant,
    create_user,
    drain_notices,
    guild_of,
    route_session_to_guild,
    route_system,
)


async def _board(session: AsyncSession):
    """An author, a reader who shares their initiative, that initiative with
    posts turned on, and the guild holding it."""
    author = await create_user(session)
    guild = await create_guild(session, creator=author)
    reader = await create_user(session)
    await create_guild_membership(session, user=reader, guild=guild)
    initiative = await create_initiative(session, guild, author)
    await create_initiative_member(session, initiative, reader)
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    # Ids, not rows: publishing commits (the claim has to be durable before
    # anything is sent), and a commit expires whatever these tests still hold.
    return author, reader, initiative, guild


async def _draft(session, initiative, author, *, due_in: timedelta, **kw) -> int:
    """A scheduled notice, shared with the whole initiative the way the create
    endpoint shares one. Returns its id: publishing commits, and a commit
    expires whatever row a test was still holding.
    """
    post = await create_post(
        session,
        initiative,
        author,
        published_at=None,
        scheduled_for=datetime.now(UTC) + due_in,
        **kw,
    )
    return cast(int, post.id)


async def _publish(guild_id: int, *, now: datetime) -> list[int]:
    """Publish what is due as the sweep does: on a system session of its own,
    routed into the community with nobody behind it."""
    async with cohorts.system_session(guild_id) as system:
        await route_system(system, guild_id=guild_id)
        published = await publish_due_posts(system, now=now)
        await system.commit()
    return published


async def _notifications(session: AsyncSession, user_id: int) -> list[Notification]:
    await drain_notices()
    return list(
        await session.exec(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.type == NotificationType.post_published,
            )
        )
    )


async def test_a_due_notice_is_published_and_announced(session: AsyncSession):
    """It goes up once, to the people it was shared with, and a poll whose
    deadline passed while it waited is open."""
    author, reader, initiative, _ = await _board(session)
    author_id, reader_id = author.id, reader.id
    post_id = await _draft(session, initiative, author, due_in=timedelta(minutes=-1))
    # Its poll's deadline passed while it waited.
    await create_post_poll(
        session,
        await session.get(Post, post_id),
        closes_at=datetime.now(UTC) - timedelta(seconds=30),
    )

    await route_session_to_guild(session, guild_of(initiative))
    published = await _publish(guild_of(initiative), now=datetime.now(UTC))
    await session.commit()

    assert published == [post_id]
    refreshed = (await session.exec(select(Post).where(Post.id == post_id))).one()
    assert refreshed.published_at is not None
    # The schedule stays: it is the record of when this was meant to land.
    assert refreshed.scheduled_for is not None
    assert len(await _notifications(session, reader_id)) == 1
    assert await _notifications(session, author_id) == []
    poll = (
        await session.exec(select(PostPoll).where(PostPoll.post_id == post_id))
    ).one()
    assert poll.closes_at is None


async def test_a_notice_not_yet_due_is_left_alone(session: AsyncSession):
    author, reader, initiative, _ = await _board(session)
    reader_id = reader.id
    post_id = await _draft(session, initiative, author, due_in=timedelta(days=1))

    await route_session_to_guild(session, guild_of(initiative))
    assert await _publish(guild_of(initiative), now=datetime.now(UTC)) == []
    await session.commit()

    refreshed = (await session.exec(select(Post).where(Post.id == post_id))).one()
    assert refreshed.published_at is None
    assert await _notifications(session, reader_id) == []


async def test_a_second_pass_publishes_nothing_twice(session: AsyncSession):
    """The claim is the ``published_at IS NULL`` predicate on the UPDATE, so a
    pass that overlaps another — or retries after a crash — announces once."""
    author, reader, initiative, _ = await _board(session)
    reader_id = reader.id
    await _draft(session, initiative, author, due_in=timedelta(minutes=-1))

    await route_session_to_guild(session, guild_of(initiative))
    now = datetime.now(UTC)
    assert len(await _publish(guild_of(initiative), now=now)) == 1
    await session.commit()
    assert await _publish(guild_of(initiative), now=now) == []
    await session.commit()

    assert len(await _notifications(session, reader_id)) == 1


async def test_a_trashed_draft_does_not_go_up(session: AsyncSession):
    """A notice somebody threw away must not publish itself on schedule."""
    author, reader, initiative, _ = await _board(session)
    reader_id = reader.id
    post_id = await _draft(session, initiative, author, due_in=timedelta(minutes=-1))
    await route_session_to_guild(session, guild_of(initiative))
    row = (await session.exec(select(Post).where(Post.id == post_id))).one()
    row.deleted_at = datetime.now(UTC)
    session.add(row)
    await session.commit()

    assert await _publish(guild_of(initiative), now=datetime.now(UTC)) == []
    await session.commit()
    assert await _notifications(session, reader_id) == []


async def test_the_announcement_follows_the_sharing_not_the_roster(
    session: AsyncSession,
):
    """The gate the feature hangs on: a notice shared with one person
    interrupts one person, however many are in the initiative."""
    author, bystander, initiative, guild = await _board(session)
    bystander_id = bystander.id
    named = await create_user(session)
    named_id = named.id
    await create_guild_membership(session, user=named, guild=guild)
    await create_initiative_member(session, initiative, named)

    post_id = await _draft(session, initiative, author, due_in=timedelta(minutes=-1))
    await route_session_to_guild(session, guild_of(initiative))
    # Replace the factory's all-members grant with one naming a single reader.
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "post",
                ResourceGrant.resource_id == post_id,
                ResourceGrant.all_initiative_members.is_(True),
            )
        )
    ).all()
    for grant in grants:
        await session.delete(grant)
    post = (await session.exec(select(Post).where(Post.id == post_id))).one()
    await create_resource_grant(session, post, user=named)

    await _publish(guild_of(initiative), now=datetime.now(UTC))
    await session.commit()

    assert len(await _notifications(session, named_id)) == 1
    assert await _notifications(session, bystander_id) == []


async def test_somebody_who_ignores_the_author_is_not_told(session: AsyncSession):
    """Ignoring is about contact: a notice the author writes still reaches the
    board, and does not reach the bell of somebody who has stopped hearing
    from them."""
    from app.models.platform.user_ignore import UserIgnore

    author, reader, initiative, _ = await _board(session)
    reader_id = reader.id
    await session.exec(text("SET search_path TO public"))
    session.add(UserIgnore(user_id=reader.id, ignored_user_id=author.id))
    await session.commit()

    await _draft(session, initiative, author, due_in=timedelta(minutes=-1))
    await route_session_to_guild(session, guild_of(initiative))
    await _publish(guild_of(initiative), now=datetime.now(UTC))
    await session.commit()

    assert await _notifications(session, reader_id) == []


async def test_a_failed_announcement_does_not_re_publish(session: AsyncSession):
    """Email and push leave the building, and a rollback cannot call them back.

    The claim is committed before anything is sent, so a crash part-way through
    the fan-out costs the rest of that pass's notifications — it does not hand
    the whole board a second set on the next one.
    """
    import app.services.tenant.post_publication as publication

    author, _reader, initiative, _ = await _board(session)
    post_id = await _draft(session, initiative, author, due_in=timedelta(minutes=-1))

    with patch.object(publication, "announce_post", _explode):
        await route_session_to_guild(session, guild_of(initiative))
        with pytest.raises(RuntimeError):
            await _publish(guild_of(initiative), now=datetime.now(UTC))

    # Published, despite the failure after it — the claim was committed before
    # the fan-out began — and so never claimed again.
    session.expunge_all()
    await route_session_to_guild(session, guild_of(initiative))
    refreshed = (await session.exec(select(Post).where(Post.id == post_id))).one()
    assert refreshed.published_at is not None
    assert await _publish(guild_of(initiative), now=datetime.now(UTC)) == []


async def _explode(*_args, **_kwargs):
    raise RuntimeError("the network went away mid-announcement")
