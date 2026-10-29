"""The stored rules: no row is the default, and a community's value applies
while it holds the option its rule needs."""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildMembership
from app.models.platform.rule import CommunityRule, PlatformRule
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
