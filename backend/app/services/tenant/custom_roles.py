"""A community's custom roles: defining them, and who holds which.

The routes in front of these say why a write is refused; the policies on
``custom_roles`` and ``custom_role_members`` refuse it either way
(``app.db.guild_ddl``).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, delete, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildMembership
from app.models.tenant.custom_role import CustomRole, CustomRoleMember


async def list_roles(session: AsyncSession) -> list[CustomRole]:
    return list(
        (await session.exec(select(CustomRole).order_by(col(CustomRole.name)))).all()
    )


async def get_role(session: AsyncSession, role_id: int) -> Optional[CustomRole]:
    return await session.get(CustomRole, role_id)


async def holders(session: AsyncSession, guild_id: int) -> list[tuple[int, int]]:
    """``(user_id, role_id)`` for each member holding a role given during the
    membership they have now: what the standing applies, rung aside."""
    rows = await session.exec(
        select(CustomRoleMember.user_id, CustomRoleMember.role_id)
        .join(
            GuildMembership,
            and_(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == CustomRoleMember.user_id,
                col(CustomRoleMember.assigned_at) >= GuildMembership.joined_at,
            ),
        )
        .order_by(col(CustomRoleMember.user_id))
    )
    return [(user_id, role_id) for user_id, role_id in rows.all()]


async def assign(
    session: AsyncSession, *, user_id: int, role_id: Optional[int]
) -> None:
    """Give ``user_id`` the role ``role_id``, from now, or take theirs off."""
    if role_id is None:
        await session.exec(
            delete(CustomRoleMember).where(CustomRoleMember.user_id == user_id)
        )
        return
    statement = pg_insert(CustomRoleMember).values(user_id=user_id, role_id=role_id)
    await session.exec(
        statement.on_conflict_do_update(
            index_elements=[CustomRoleMember.user_id],
            set_={"role_id": role_id, "assigned_at": func.now()},
        )
    )


async def held_role(session: AsyncSession, user_id: int) -> Optional[CustomRole]:
    """The role ``user_id``'s assignment names, whatever membership it was
    given in: what taking it off would take off."""
    return (
        await session.exec(
            select(CustomRole)
            .join(CustomRoleMember, CustomRoleMember.role_id == CustomRole.id)
            .where(CustomRoleMember.user_id == user_id)
        )
    ).one_or_none()
