"""The one read and write of the stored rules (``app.core.rules``).

A read fills in the default of every rule without a row. A community's value
counts only while it holds the option the rule needs, which every reader that
enforces a rule asks for (``applied``); the seat's own settings page reads
what it wrote whether or not it applies (``applied=False``).

:func:`community_rule_sql` is the same answer as a SQL expression, for a query
that has to ask it of many communities at once.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import and_, func, select as sa_select
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.rules import COMMUNITY_RULES, PLATFORM_RULES, Slot, StoredRule
from app.models.platform.rule import CommunityRule, PlatformRule
from app.services.platform import guild_entitlements

Values = dict[str, Any]


def _value(rule: StoredRule, row: PlatformRule | CommunityRule) -> Any:
    return getattr(row, rule.slot.value)


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
                CommunityRule.guild_id.in_(wanted)  # type: ignore[attr-defined]
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


def community_rule_sql(guild_id: Any, key: str) -> ColumnElement[Any]:
    """:func:`community_value`, applied, as an expression over ``guild_id``."""
    rule = COMMUNITY_RULES[key]
    stored = getattr(CommunityRule, rule.slot.value)
    conditions = [CommunityRule.guild_id == guild_id, CommunityRule.key == key]
    if rule.entitlement is not None:
        conditions.append(guild_entitlements.holds_option(guild_id, rule.entitlement))
    found = sa_select(stored).where(and_(*conditions)).scalar_subquery()
    if rule.default is None:
        return found
    return func.coalesce(found, rule.default)


async def put(
    session: AsyncSession, key: str, value: Any, *, guild_id: int | None = None
) -> None:
    """Write one rule of the deployment, or of ``guild_id``. Its default
    removes the row, so a rule that says nothing holds nothing."""
    catalog = PLATFORM_RULES if guild_id is None else COMMUNITY_RULES
    rule = catalog[key]
    model = PlatformRule if guild_id is None else CommunityRule
    where = [model.key == key]
    if guild_id is not None:
        where.append(CommunityRule.guild_id == guild_id)
    if value == rule.default:
        await session.exec(delete(model).where(*where))  # type: ignore[arg-type]
        return
    row = (await session.exec(select(model).where(*where))).one_or_none()
    if row is None:
        row = (
            PlatformRule(key=key)
            if guild_id is None
            else CommunityRule(guild_id=guild_id, key=key)
        )
    for slot in Slot:
        setattr(row, slot.value, value if slot is rule.slot else None)
    session.add(row)
