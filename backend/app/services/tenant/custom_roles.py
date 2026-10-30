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
from app.models.tenant.custom_role import (
    CustomRole,
    CustomRoleClaimRule,
    CustomRoleMember,
)


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
    session: AsyncSession,
    *,
    user_id: int,
    role_id: Optional[int],
    provider_id: Optional[int] = None,
) -> None:
    """Give ``user_id`` the role ``role_id``, from now, or take theirs off.
    ``provider_id`` is the sign-in provider whose claims gave it; a role given
    by hand names none, and the claims leave it alone from then on."""
    if role_id is None:
        await session.exec(
            delete(CustomRoleMember).where(CustomRoleMember.user_id == user_id)
        )
        return
    statement = pg_insert(CustomRoleMember).values(
        user_id=user_id, role_id=role_id, oidc_provider_id=provider_id
    )
    await session.exec(
        statement.on_conflict_do_update(
            index_elements=[CustomRoleMember.user_id],
            set_={
                "role_id": role_id,
                "assigned_at": func.now(),
                "oidc_provider_id": provider_id,
            },
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


async def claim_rules(session: AsyncSession) -> list[CustomRoleClaimRule]:
    """The community's claim rules, in the order a sign-in reads them."""
    return list(
        (
            await session.exec(
                select(CustomRoleClaimRule).order_by(
                    col(CustomRoleClaimRule.position), col(CustomRoleClaimRule.id)
                )
            )
        ).all()
    )


async def add_claim_rule(
    session: AsyncSession, *, provider_id: int, claim_value: str, role_id: int
) -> CustomRoleClaimRule:
    """A rule after every other: the first matching rule wins."""
    last = await session.scalar(select(func.max(CustomRoleClaimRule.position)))
    rule = CustomRoleClaimRule(
        provider_id=provider_id,
        claim_value=claim_value,
        role_id=role_id,
        position=(last or 0) + 1,
    )
    session.add(rule)
    await session.flush()
    return rule


async def order_claim_rules(session: AsyncSession, rule_ids: list[int]) -> bool:
    """Put the rules in the order ``rule_ids`` lists, which names each once.
    ``False`` where it names other rules than the community has."""
    rules = {rule.id: rule for rule in await claim_rules(session)}
    if sorted(rule_ids) != sorted(rules):
        return False
    for position, rule_id in enumerate(rule_ids, start=1):
        rules[rule_id].position = position
        session.add(rules[rule_id])
    await session.flush()
    return True


async def apply_claims(
    session: AsyncSession,
    *,
    guild_id: int,
    user_id: int,
    provider_id: int,
    claim_values: set[str],
    admitted: bool,
) -> Optional[tuple[Optional[int], Optional[int]]]:
    """A sign-in through ``provider_id``'s say over ``user_id``'s custom role:
    the role of the first rule for the provider whose group the claims carry,
    while the community counts the arrival as its own, or none.

    Only a role this provider gave is changed or taken back; one given by hand
    or by another provider is left as it is. A role from an earlier membership
    counts as none. Returns ``(from, to)`` role ids when it changed anything.
    """
    wanted: Optional[int] = None
    if admitted:
        for rule in await claim_rules(session):
            if (
                rule.provider_id == provider_id
                and rule.claim_value.lower() in claim_values
            ):
                wanted = rule.role_id
                break
    held = (
        await session.exec(
            select(CustomRoleMember)
            .join(
                GuildMembership,
                and_(
                    GuildMembership.guild_id == guild_id,
                    GuildMembership.user_id == CustomRoleMember.user_id,
                    col(CustomRoleMember.assigned_at) >= GuildMembership.joined_at,
                ),
            )
            .where(CustomRoleMember.user_id == user_id)
        )
    ).one_or_none()
    if held is not None and held.oidc_provider_id != provider_id:
        return None
    previous = held.role_id if held is not None else None
    if previous == wanted:
        return None
    await assign(session, user_id=user_id, role_id=wanted, provider_id=provider_id)
    return previous, wanted
