"""The people roster lists the people you could actually reach out to.

The two to keep are the last: an ignore governs what arrives, so it takes the
account you ignored off your own roster and leaves you on theirs.
"""

from datetime import UTC, datetime

from sqlalchemy import text

from app.models.platform.guild import CommunityRole
from app.models.platform.user_dm_settings import DmPolicy
from app.models.platform.user_ignore import UserIgnore


async def _policy(session, user, policy: DmPolicy) -> None:
    await session.exec(
        text(
            "UPDATE public.user_dm_settings SET dm_policy = CAST(:p AS user_dm_policy) "
            "WHERE user_id = :u"
        ).bindparams(p=policy.value, u=user.id)
    )
    await session.commit()


async def _roster(client, actor) -> set[int]:
    response = await client.get("/api/v1/me/people", headers=actor.headers)
    assert response.status_code == 200, response.text
    return {
        item["id"]
        for section in response.json()["sections"]
        for item in section["items"]
    }


async def test_a_community_member_you_can_ask_is_listed(client, session, acting_user):
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.community)
    await _policy(session, bram.user, DmPolicy.community)

    assert bram.user.id in await _roster(client, ada)


async def test_a_private_member_is_not_listed(client, session, acting_user):
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.community)
    await _policy(session, bram.user, DmPolicy.private)

    assert bram.user.id not in await _roster(client, ada)


async def test_a_private_reader_lists_nobody(client, session, acting_user):
    """The reader's own policy decides the whole page, which is what makes the
    default empty and worth explaining."""
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.private)
    await _policy(session, bram.user, DmPolicy.community)

    assert await _roster(client, ada) == set()


async def test_an_unconfirmed_age_lists_nobody(client, session, acting_user):
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.community)
    await _policy(session, bram.user, DmPolicy.community)
    ada.user.age_confirmed_at = None
    session.add(ada.user)
    await session.commit()

    assert await _roster(client, ada) == set()


async def test_a_member_who_has_not_answered_the_age_question_is_not_listed(
    client, session, acting_user
):
    """Sharing a community is not enough on its own.

    An account that has not answered cannot be messaged, so listing it would
    offer the reader a person they cannot reach.
    """
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.community)
    await _policy(session, bram.user, DmPolicy.community)
    bram.user.age_confirmed_at = None
    session.add(bram.user)
    await session.commit()

    assert bram.user.id not in await _roster(client, ada)


async def test_a_member_below_the_minimum_age_is_not_listed(
    client, session, acting_user
):
    """The other age answer, which is the one that stands."""
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.community)
    await _policy(session, bram.user, DmPolicy.community)
    bram.user.age_confirmed_at = None
    bram.user.age_below_minimum_at = datetime.now(UTC)
    session.add(bram.user)
    await session.commit()

    assert bram.user.id not in await _roster(client, ada)


async def test_being_ignored_does_not_remove_you_from_their_roster(
    client, session, acting_user
):
    """Ada ignores Bram. Bram's roster still has Ada on it, unchanged."""
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.community)
    await _policy(session, bram.user, DmPolicy.community)

    before = await _roster(client, bram)
    assert ada.user.id in before

    session.add(UserIgnore(user_id=ada.user.id, ignored_user_id=bram.user.id))
    await session.commit()

    assert await _roster(client, bram) == before


async def test_an_account_you_ignore_leaves_your_own_roster(
    client, session, acting_user
):
    """The other direction is the reader's own doing, and theirs to see."""
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.community)
    await _policy(session, bram.user, DmPolicy.community)
    assert bram.user.id in await _roster(client, ada)

    session.add(UserIgnore(user_id=ada.user.id, ignored_user_id=bram.user.id))
    await session.commit()

    assert bram.user.id not in await _roster(client, ada)
