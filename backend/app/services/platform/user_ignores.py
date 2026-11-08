"""The accounts one person has chosen not to hear from.

Every read and write here is the holder's own row, on their own platform-tier
session — the table's policies say so, and nothing in this module reaches the
other direction. What reads that direction is the rule in ``public``, which
answers with a decision.

Adding somebody is deliberately uneventful: the row goes in, nothing is deleted,
and nobody is told. A connection or a message grant the pair already has stays
exactly where it is, so removing the account from the list puts everything back
as it was.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.db.query import build_paginated_response, paginated_query
from app.models.platform.user_ignore import UserIgnore
from app.models.platform.user_profile_view import user_profiles
from app.services.platform import connections_stream
from app.schemas.platform.dm import IgnoredAccountRead, IgnoredAccountsResponse


async def list_ignored(
    session: AsyncSession, *, user_id: int, page: int = 1, page_size: int = 50
) -> IgnoredAccountsResponse:
    """The holder's own list, newest first, with the profile of each account."""
    statement = (
        select(
            UserIgnore.ignored_user_id,
            UserIgnore.created_at,
            user_profiles.c.username,
            user_profiles.c.discriminator,
            user_profiles.c.avatar_url,
        )
        .join(
            user_profiles,
            user_profiles.c.id == UserIgnore.ignored_user_id,
        )
        .where(UserIgnore.user_id == user_id)
        .order_by(col(UserIgnore.created_at).desc())
    )
    rows, total, page = await paginated_query(
        session,
        statement,
        select(func.count())
        .select_from(UserIgnore)
        .where(UserIgnore.user_id == user_id),
        page,
        page_size,
    )

    return IgnoredAccountsResponse(
        **build_paginated_response(
            [
                IgnoredAccountRead(
                    user_id=row[0],
                    created_at=row[1],
                    username=row[2],
                    discriminator=row[3],
                    avatar_url=row[4],
                )
                for row in rows
            ],
            total,
            page,
            page_size,
        )
    )


async def add(session: AsyncSession, *, user_id: int, ignored_user_id: int) -> None:
    """Start ignoring an account. Doing it twice is not an error."""
    await session.exec(
        pg_insert(UserIgnore)
        .values(
            user_id=user_id,
            ignored_user_id=ignored_user_id,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "ignored_user_id"])
    )
    # The holder's own lists moved. The other account is told nothing, here or
    # anywhere: a frame would land at exactly the moment the row appeared.
    connections_stream.queue_connections_signal(session, user_id)
    await session.commit()


async def remove(session: AsyncSession, *, user_id: int, ignored_user_id: int) -> None:
    """Stop ignoring an account.

    Everything the pair had before is still there, so what was suppressed
    simply starts arriving again. Nothing that happened in between is
    reconstructed — none of it was written.
    """
    row = await session.get(UserIgnore, (user_id, ignored_user_id))
    if row is not None:
        await session.delete(row)
        connections_stream.queue_connections_signal(session, user_id)
        await session.commit()


async def ignores(session: AsyncSession, *, user_id: int, other_user_id: int) -> bool:
    """Whether the holder ignores that account. Their own row, so this is a
    question the request path may ask."""
    return (
        await session.exec(
            select(func.count())
            .select_from(UserIgnore)
            .where(
                UserIgnore.user_id == user_id,
                UserIgnore.ignored_user_id == other_user_id,
            )
        )
    ).one() > 0
