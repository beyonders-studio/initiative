"""The people roster lists the people you could actually reach out to.

The two to keep are the last: an ignore governs what arrives, so it takes the
account you ignored off your own roster and leaves you on theirs.
"""

from datetime import UTC, datetime

import pytest
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


_NOW = datetime.now(UTC)


@pytest.mark.parametrize(
    ("reader_policy", "member_policy", "reader_edits", "member_edits"),
    [
        pytest.param(
            DmPolicy.community, DmPolicy.private, {}, {}, id="a-private-member"
        ),
        # The reader's own policy decides the whole page, which is what makes
        # the default empty and worth explaining.
        pytest.param(
            DmPolicy.private, DmPolicy.community, {}, {}, id="a-private-reader"
        ),
        pytest.param(
            DmPolicy.community,
            DmPolicy.community,
            {"age_confirmed_at": None},
            {},
            id="a-reader-with-an-unconfirmed-age",
        ),
        # Sharing a community is not enough on its own: an account that has
        # not answered cannot be messaged, so listing it would offer the reader
        # a person they cannot reach.
        pytest.param(
            DmPolicy.community,
            DmPolicy.community,
            {},
            {"age_confirmed_at": None},
            id="a-member-who-has-not-answered-the-age-question",
        ),
        # The other age answer, which is the one that stands.
        pytest.param(
            DmPolicy.community,
            DmPolicy.community,
            {},
            {"age_confirmed_at": None, "age_below_minimum_at": _NOW},
            id="a-member-below-the-minimum-age",
        ),
    ],
)
async def test_a_member_you_cannot_reach_is_not_listed(
    client,
    session,
    acting_user,
    reader_policy,
    member_policy,
    reader_edits,
    member_edits,
):
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, reader_policy)
    await _policy(session, bram.user, member_policy)
    for actor, edits in ((ada, reader_edits), (bram, member_edits)):
        for field, value in edits.items():
            setattr(actor.user, field, value)
        session.add(actor.user)
    await session.commit()

    assert bram.user.id not in await _roster(client, ada)


async def test_an_ignore_takes_the_ignored_off_your_roster_alone(
    client, session, acting_user
):
    """Ada ignores Bram. Bram's roster still has Ada on it, unchanged; the
    other direction is Ada's own doing, and hers to see."""
    ada = await acting_user(guild_role=CommunityRole.member)
    bram = await acting_user(guild_role=CommunityRole.member, guild=ada.guild)
    await _policy(session, ada.user, DmPolicy.community)
    await _policy(session, bram.user, DmPolicy.community)

    before = await _roster(client, bram)
    assert ada.user.id in before
    assert bram.user.id in await _roster(client, ada)

    session.add(UserIgnore(user_id=ada.user.id, ignored_user_id=bram.user.id))
    await session.commit()

    assert await _roster(client, bram) == before
    assert bram.user.id not in await _roster(client, ada)
