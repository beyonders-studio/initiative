"""Bans and timeouts, as a community's roster holders give and lift them.

Written on the community's own routed session, where the table's policies
admit whoever holds the members surface. Removing a banned person, and the
checks on who may be removed, stay with the removal route; refusing them on the
way back in is ``guilds.ensure_membership``'s. A timeout takes effect through
the membership lookup and the standing, which read the row as the person.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import GuildMembership
from app.models.platform.member_moderation import MemberModeration, ModerationKind
from app.models.platform.user_profile_view import MemberProfile
from app.services import audit as audit_service


async def _put(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    kind: ModerationKind,
    ends_at: datetime | None,
) -> None:
    """Make the person's row this one, whatever it was."""
    now = datetime.now(UTC)
    await session.exec(
        insert(MemberModeration)
        .values(
            guild_id=guild_id,
            user_id=user_id,
            kind=kind.value,
            ends_at=ends_at,
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=["guild_id", "user_id"],
            set_={"kind": kind.value, "ends_at": ends_at, "created_at": now},
        )
    )


async def _lift(
    session: AsyncSession, *, guild_id: int, user_id: int, kind: ModerationKind
) -> bool:
    """Delete the person's row of ``kind``. Says whether there was one."""
    lifted = (
        await session.exec(
            delete(MemberModeration)
            .where(
                col(MemberModeration.guild_id) == guild_id,
                col(MemberModeration.user_id) == user_id,
                col(MemberModeration.kind) == kind.value,
            )
            .returning(col(MemberModeration.user_id))
        )
    ).first()
    return lifted is not None


async def ban(
    session: AsyncSession, *, guild_id: int, user_id: int, actor_user_id: int
) -> None:
    """Keep ``user_id`` out of the community until the ban is lifted. A
    timeout they had goes with it."""
    await _put(
        session,
        guild_id=guild_id,
        user_id=user_id,
        kind=ModerationKind.ban,
        ends_at=None,
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.COMMUNITY_MEMBER_BANNED,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
    )


async def unban(
    session: AsyncSession, *, guild_id: int, user_id: int, actor_user_id: int
) -> None:
    """Lift a ban, so they can be invited or join again."""
    if await _lift(
        session, guild_id=guild_id, user_id=user_id, kind=ModerationKind.ban
    ):
        await audit_service.record(
            session,
            event_type=AuditEventType.COMMUNITY_MEMBER_UNBANNED,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
        )


async def list_bans(
    session: AsyncSession, *, guild_id: int
) -> Sequence[tuple[MemberProfile, datetime]]:
    """Everybody the community has banned, the most recent first."""
    return (
        await session.exec(
            select(MemberProfile, MemberModeration.created_at)
            .join(MemberModeration, MemberModeration.user_id == MemberProfile.id)
            .where(
                MemberModeration.guild_id == guild_id,
                MemberModeration.kind == ModerationKind.ban,
            )
            .order_by(col(MemberModeration.created_at).desc())
        )
    ).all()


async def time_out(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    ends_at: datetime,
    actor_user_id: int,
) -> None:
    """Hold ``user_id``'s content in the community read-only until ``ends_at``."""
    await _put(
        session,
        guild_id=guild_id,
        user_id=user_id,
        kind=ModerationKind.timeout,
        ends_at=ends_at,
    )
    await audit_service.record(
        session,
        event_type=AuditEventType.COMMUNITY_MEMBER_TIMED_OUT,
        actor_user_id=actor_user_id,
        target_user_id=user_id,
        guild_id=guild_id,
        target_type="guild",
        target_id=guild_id,
        detail={"ends_at": ends_at.isoformat()},
    )


async def lift_timeout(
    session: AsyncSession, *, guild_id: int, user_id: int, actor_user_id: int
) -> None:
    """End a timeout early."""
    if await _lift(
        session, guild_id=guild_id, user_id=user_id, kind=ModerationKind.timeout
    ):
        await audit_service.record(
            session,
            event_type=AuditEventType.COMMUNITY_MEMBER_TIMEOUT_LIFTED,
            actor_user_id=actor_user_id,
            target_user_id=user_id,
            guild_id=guild_id,
            target_type="guild",
            target_id=guild_id,
        )


def live_timeout_end():
    """A column: when the timeout of the row's person in the row's community
    ends, where one is running. Correlated on ``GuildMembership``."""
    return (
        select(MemberModeration.ends_at)
        .where(
            MemberModeration.guild_id == GuildMembership.guild_id,
            MemberModeration.user_id == GuildMembership.user_id,
            MemberModeration.kind == ModerationKind.timeout,
            col(MemberModeration.ends_at) > func.now(),
        )
        .scalar_subquery()
    )


async def live_timeouts(
    session: AsyncSession, *, user_id: int, guild_ids: Collection[int]
) -> dict[int, datetime]:
    """When each of ``user_id``'s running timeouts in ``guild_ids`` ends."""
    if not guild_ids:
        return {}
    rows = (
        await session.exec(
            select(MemberModeration.guild_id, MemberModeration.ends_at).where(
                MemberModeration.user_id == user_id,
                col(MemberModeration.guild_id).in_(guild_ids),
                MemberModeration.kind == ModerationKind.timeout,
                col(MemberModeration.ends_at) > func.now(),
            )
        )
    ).all()
    return {guild_id: ends_at for guild_id, ends_at in rows if ends_at is not None}
