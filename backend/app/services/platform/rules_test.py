"""The stored rules: no row is the default, and a community's value applies
while it holds the option its rule needs."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.login_methods import LoginMethod, SecondFactorRequirement
from app.core.rules import PLATFORM_RULES, Slot, choices
from app.models.platform.guild import GuildMembership
from app.models.platform.rule import CommunityRule, PlatformRule, RuleChoice
from app.services.platform import rules
from app.testing import create_guild, create_user, guild_administration


async def test_a_rule_without_a_row_is_its_default_and_writing_it_removes_the_row(
    session: AsyncSession,
):
    guild = await create_guild(session)
    assert (await rules.platform_values(session))["session_max_hours"] is None
    assert await rules.community_value(session, guild.id, "allow_ai") is True

    await rules.put(session, "session_max_hours", 12)
    await rules.put(session, "allow_ai", False, guild_id=guild.id)
    await session.commit()
    assert (await rules.platform_values(session))["session_max_hours"] == 12
    assert await rules.community_value(session, guild.id, "allow_ai") is False

    await rules.put(session, "session_max_hours", None)
    await rules.put(session, "allow_ai", True, guild_id=guild.id)
    await session.commit()
    assert (await session.exec(select(PlatformRule))).all() == []
    assert (await session.exec(select(CommunityRule))).all() == []


async def test_a_community_value_applies_while_it_holds_the_option(
    session: AsyncSession,
):
    """Withdrawing the option leaves the row and stops the rule; the seat's
    own page still reads what it wrote. The SQL form agrees."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await rules.put(session, "enforce_compliance_session", True, guild_id=guild.id)
    await session.commit()

    async def applied_in_sql() -> bool:
        return (
            await session.exec(
                select(
                    rules.community_rule_sql(
                        GuildMembership.guild_id, "enforce_compliance_session"
                    )
                ).where(
                    GuildMembership.guild_id == guild.id,
                    GuildMembership.user_id == user.id,
                )
            )
        ).one()

    assert await rules.community_value(session, guild.id, "enforce_compliance_session")
    assert await applied_in_sql() is True

    await guild_administration(session, guild, auth_options=[])
    assert not await rules.community_value(
        session, guild.id, "enforce_compliance_session"
    )
    assert await applied_in_sql() is False
    assert await rules.community_value(
        session, guild.id, "enforce_compliance_session", applied=False
    )


async def test_a_member_keeps_a_value_that_differs_from_the_community(
    session: AsyncSession,
):
    """A member's row equal to the default still says something when the
    community says otherwise, so it stays; equal to the community's, it goes."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await rules.put(session, "api_keys", False, guild_id=guild.id)
    await rules.put(session, "api_keys", True, guild_id=guild.id, user_id=user.id)
    await session.commit()
    assert await rules.member_value(session, guild.id, user.id, "api_keys") is True

    await rules.put(session, "api_keys", False, guild_id=guild.id, user_id=user.id)
    await session.commit()
    assert await rules.member_value(session, guild.id, user.id, "api_keys") is False
    members = (
        await session.exec(
            select(CommunityRule).where(CommunityRule.user_id.is_not(None))
        )
    ).all()
    assert members == []


@pytest.mark.always
async def test_rule_choices_are_the_catalogs(session: AsyncSession):
    """The migrations write ``rule_choices``; the catalog says what they
    should hold. A new choice rule, or a new value on one, needs both."""
    stored = set((await session.exec(select(RuleChoice.key, RuleChoice.value))).all())
    assert stored == {
        (key, value)
        for key, rule in PLATFORM_RULES.items()
        if rule.slot is Slot.choice
        for value in choices(rule)
    }


async def test_a_choice_and_the_ways_in_are_rows_like_any_other(
    session: AsyncSession,
):
    """A value its rule does not have is refused by the database, and the
    ways in must include one that can begin a session."""
    await rules.put(session, "second_factor_requirement", "everyone")
    await rules.put(session, "login_methods", frozenset({LoginMethod.sso}))
    await session.commit()
    stored = await rules.platform_values(session)
    assert stored["second_factor_requirement"] is SecondFactorRequirement.everyone
    assert stored["login_methods"] == {LoginMethod.sso}

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(PlatformRule(key="default_dm_policy", choice="everyone"))
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(PlatformRule(key="login_methods_probe", methods=["totp"]))
