"""The one read and write of the stored rules (``app.core.rules``).

A read fills in the default of every rule without a row. A community's value
counts only while it holds the option the rule needs, which every reader that
enforces a rule asks for (``applied``); the seat's own settings page reads
what it wrote whether or not it applies (``applied=False``).

A community's row says something of the whole community, or of one member
(``user_id``). For a member, their own row wins over the community's.

:func:`community_rule_sql` is the same answer as a SQL expression, for a query
that has to ask it of many communities or members at once.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import and_, func, literal, or_, select as sa_select
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.login_methods import LoginMethod
from app.core.rules import (
    COMMUNITY_RULES,
    PLATFORM_RULES,
    SignInRequirement,
    Slot,
    StoredRule,
)
from app.models.platform.rule import CommunityRule, PlatformRule
from app.services.platform import guild_entitlements

Values = dict[str, Any]


def _value(rule: StoredRule, row: PlatformRule | CommunityRule) -> Any:
    if rule.slot is Slot.methods:
        assert isinstance(row, CommunityRule)
        return SignInRequirement(
            "required",
            row.provider_id,
            frozenset(LoginMethod(m) for m in row.methods or ()),
        )
    return getattr(row, rule.slot.value)


def _slots(rule: StoredRule, value: Any) -> dict[str, Any]:
    """The columns a row of ``rule`` holding ``value`` sets."""
    if rule.slot is Slot.methods:
        return {
            "methods": sorted(m.value for m in value.methods),
            "provider_id": value.provider_id,
        }
    return {rule.slot.value: value}


async def platform_values(session: AsyncSession) -> Values:
    """Every rule the deployment keeps, each its own value or its default."""
    values = {key: rule.default for key, rule in PLATFORM_RULES.items()}
    for row in (await session.exec(select(PlatformRule))).all():
        rule = PLATFORM_RULES.get(row.key)
        if rule is not None:
            values[row.key] = _value(rule, row)
    return values


async def community_values(
    session: AsyncSession, guild_ids: Iterable[int], *, applied: bool = True
) -> dict[int, Values]:
    """Every rule each community keeps, in one read.

    ``applied``: a value counts only while the community holds the option its
    rule needs, and is its default otherwise.
    """
    wanted = set(guild_ids)
    values = {
        gid: {key: rule.default for key, rule in COMMUNITY_RULES.items()}
        for gid in wanted
    }
    if not wanted:
        return values
    options = {
        rule.entitlement for rule in COMMUNITY_RULES.values() if rule.entitlement
    }
    held_columns = [
        guild_entitlements.holds_option(CommunityRule.guild_id, option).label(
            option.value
        )
        for option in sorted(options)
    ]
    rows = (
        await session.exec(
            sa_select(CommunityRule, *held_columns).where(
                CommunityRule.guild_id.in_(wanted),  # type: ignore[attr-defined]
                CommunityRule.user_id.is_(None),  # type: ignore[union-attr]
            )
        )
    ).all()
    for row, *held in rows:
        rule = COMMUNITY_RULES.get(row.key)
        if rule is None:
            continue
        holds = dict(zip(sorted(options), held))
        if applied and rule.entitlement is not None and not holds[rule.entitlement]:
            continue
        values[row.guild_id][row.key] = _value(rule, row)
    return values


async def community_value(
    session: AsyncSession, guild_id: int, key: str, *, applied: bool = True
) -> Any:
    """One rule of one community."""
    return (await community_values(session, [guild_id], applied=applied))[guild_id][key]


def community_rule_sql(
    guild_id: Any, key: str, *, user_id: Any = None, applied: bool = True
) -> ColumnElement[Any]:
    """:func:`community_value` as an expression over ``guild_id``, or
    :func:`member_value` over ``guild_id`` and ``user_id``."""
    rule = COMMUNITY_RULES[key]
    stored = getattr(CommunityRule, rule.slot.value)
    subject = CommunityRule.user_id.is_(None)  # type: ignore[union-attr]
    if user_id is not None:
        subject = or_(subject, CommunityRule.user_id == user_id)
    conditions = [CommunityRule.guild_id == guild_id, CommunityRule.key == key, subject]
    if applied and rule.entitlement is not None:
        conditions.append(guild_entitlements.holds_option(guild_id, rule.entitlement))
    found = (
        sa_select(stored)
        .where(and_(*conditions))
        # The member's own row first.
        .order_by(CommunityRule.user_id.is_(None))  # type: ignore[union-attr]
        .limit(1)
        .scalar_subquery()
    )
    if rule.default is None:
        return found
    return func.coalesce(found, rule.default)


async def member_value(
    session: AsyncSession,
    guild_id: int,
    user_id: int,
    key: str,
    *,
    applied: bool = True,
) -> Any:
    """One rule as it stands for one member: their own row, the community's,
    or the default."""
    return await session.scalar(
        sa_select(
            community_rule_sql(
                literal(guild_id), key, user_id=literal(user_id), applied=applied
            )
        )
    )


async def put(
    session: AsyncSession,
    key: str,
    value: Any,
    *,
    guild_id: int | None = None,
    user_id: int | None = None,
) -> None:
    """Write one rule of the deployment, of ``guild_id``, or of one of its
    members. A value that is what the row would inherit removes it, so a rule
    that says nothing holds nothing: the default for the deployment and a
    community, and the community's own value for a member."""
    catalog = PLATFORM_RULES if guild_id is None else COMMUNITY_RULES
    rule = catalog[key]
    model = PlatformRule if guild_id is None else CommunityRule
    where = [model.key == key]
    if guild_id is not None:
        where += [
            CommunityRule.guild_id == guild_id,
            CommunityRule.user_id.is_(None)  # type: ignore[union-attr]
            if user_id is None
            else CommunityRule.user_id == user_id,
        ]
    inherited = rule.default
    if user_id is not None:
        # What the community says, this session's own writes included.
        await session.flush()
        inherited = await community_value(session, guild_id, key, applied=False)
    if value == inherited:
        await session.exec(delete(model).where(*where))  # type: ignore[arg-type]
        return
    row = (await session.exec(select(model).where(*where))).one_or_none()
    if row is None:
        row = (
            PlatformRule(key=key)
            if guild_id is None
            else CommunityRule(guild_id=guild_id, key=key, user_id=user_id)
        )
    held = _slots(rule, value)
    for column in ("enabled", "amount", "methods", "provider_id"):
        if hasattr(row, column):
            setattr(row, column, held.get(column))
    session.add(row)
