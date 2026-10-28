"""Publication of bulletin-board notices — the moment a post goes live.

A post carries two instants: ``scheduled_for``, when its author asked for it to
go up, and ``published_at``, when it did. Everything else keys off the second
one, so "has this been published" is a column test rather than a comparison
against the clock, and the surfaces that list posts cannot disagree with this
worker about what exists.

Two ways in, one fan-out:

* **Posted now** — the endpoint stamps ``published_at`` itself and calls
  :func:`announce_post` before it commits, so the notice and the notices about
  it land together.
* **Scheduled** — the row is written with neither column resolved, and
  :func:`publish_due_posts` stamps it when its time comes. The stamp is an
  ``UPDATE … WHERE published_at IS NULL … RETURNING``, so a row is claimed by
  exactly one worker however many are running, and it is **committed before
  anything is sent**. Email and push leave the building; a rollback cannot
  call them back. Committing the claim first means a crash mid-announce costs
  some notifications, where the other order would send the whole board a
  second set on the next pass. Making delivery exactly-once needs a
  per-recipient ledger, and that is a bar to raise everywhere at once rather
  than for one tool.

Publishing is also what puts a notice into the search index. The index is
maintained by triggers, and no trigger fires on the passage of time — but the
claim above is a real write to the row, and ``published_at`` is one of the
columns the search trigger watches. The statement that publishes is therefore
the statement that indexes.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import cast

from sqlalchemy import ColumnElement, and_, func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user import User
from app.models.tenant.guild_plugin import GuildPlugin
from app.models.tenant.post import Post
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.services import notifications as notifications_service
from app.services.notifications import PluginAuthor
from app.models.platform.notification import NotificationType
from app.core.tools import Tool
from app.services.platform import accounts as accounts_service
from app.services.tenant import post_polls as post_polls_service
from app.services.tenant import posts as posts_service
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service

logger = logging.getLogger(__name__)


async def announce_post(
    session: AsyncSession,
    post: Post,
    *,
    author: User | PluginAuthor,
) -> None:
    """Tell everyone the notice was shared with that it is up.

    The audience is the post's own sharing — :func:`posts.audience_user_ids`,
    which resolves the same grant rows the per-request check reads. A notice
    shared with three people interrupts three people; posting to a subset of a
    large initiative does not ring everyone's bell.

    Delivered through ``notifications.notify``, which is where somebody who
    ignores the author drops out.

    ``author`` is the person who posted it, or the installed plug-in that did,
    named by the plug-in's name and by no account.
    """
    recipient_ids = sorted(
        await posts_service.audience_user_ids(session, post, exclude=author.id)
    )
    author_name = await notifications_service.actor_name(session, author)
    await notifications_service.notify(
        session,
        NotificationType.post_published,
        recipient_ids,
        about=(Tool.post.value, cast(int, post.id)),
        key="post.published",
        values={"actor": author_name, "post": post.name},
        data={"post_id": post.id, "author_name": author_name, "author_id": author.id},
        actor=author,
    )


async def _author_of(session: AsyncSession, post: Post) -> User | PluginAuthor | None:
    """Who posted a notice, for its announcement: the person, or the installed
    plug-in whose install owns it. ``None`` when that account or install is gone."""
    if post.created_by is not None:
        return await accounts_service.load_one(post.created_by)
    install_id = next(
        (
            grant.plugin_install_id
            for grant in post.grants or []
            if grant.plugin_install_id is not None
            and grant.level == ResourceAccessLevel.owner
        ),
        None,
    )
    if install_id is None:
        return None
    name = (
        await session.exec(select(GuildPlugin.name).where(GuildPlugin.id == install_id))
    ).first()
    return PluginAuthor(name=name) if name is not None else None


def scheduled() -> ColumnElement[bool]:
    """A notice waiting for its time: scheduled, not yet up, not in the trash."""
    return and_(
        Post.published_at.is_(None),  # type: ignore[union-attr]
        Post.scheduled_for.is_not(None),  # type: ignore[union-attr]
        Post.deleted_at.is_(None),  # type: ignore[union-attr]
    )


def next_due(_now: datetime):
    """When the community's next scheduled notice goes up."""
    return select(func.min(Post.scheduled_for)).where(scheduled())


async def publish_due_posts(session: AsyncSession, *, now: datetime) -> list[int]:
    """Publish every scheduled notice whose time has come, in one guild.

    The session is already routed into that guild's schema. Returns the ids
    published, which is what the tests assert on. Commits: the claim has to be
    durable before anything leaves for an inbox or a device.

    Trashed drafts are left alone: a notice somebody threw away must not go up
    on schedule. Restoring it puts it back in scope, and the next pass sends it.
    """
    claimed = (
        await session.exec(
            update(Post)
            .where(scheduled(), Post.scheduled_for <= now)  # type: ignore[operator]
            .values(published_at=now, updated_at=now)
            .returning(Post.id)
        )
    ).all()
    post_ids = [row[0] for row in claimed]
    if not post_ids:
        return []
    await post_polls_service.open_lapsed_polls(session, post_ids, now=now)

    # The claim is durable before a single email or push goes out. Sending
    # first would mean a failure anywhere below rolls ``published_at`` back
    # while the messages stay sent, and the next pass — seeing NULL again —
    # announces the same notices to the same people.
    await session.commit()

    posts = (
        (
            await session.exec(
                select(Post)
                .where(Post.id.in_(post_ids))
                .options(*posts_service.list_loader_options())
            )
        )
        .unique()
        .all()
    )
    await tags_service.annotate_tags(session, posts)
    await metadata_service.annotate_properties(session, posts)
    for post in posts:
        author = await _author_of(session, post)
        if author is None:
            # The account is gone; the notice still goes up, silently.
            logger.warning("Post %s published with no author to attribute", post.id)
            continue
        await announce_post(session, post, author=author)
    return post_ids
