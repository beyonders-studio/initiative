"""Tests for the question a notice asks.

The poll's own concerns, beyond the tool contract the post already carries:
who may write the question versus who may answer it, what a rewrite is allowed
to change once somebody has answered, and how much of the answer each reader
is shown.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.tenant.post_poll import PostPoll, PostPollVote
from app.models.tenant.post_read import PostRead
from app.testing import create_post, create_post_poll, lexical_body, route_as


async def _posts_enabled(session: AsyncSession, initiative) -> None:
    initiative.posts_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


def _poll_payload(**overrides):
    return {
        "question": "Which night works?",
        "options": [{"text": "Tuesday"}, {"text": "Thursday"}],
        **overrides,
    }


def _option_id(body: dict, text: str) -> int:
    return next(o["id"] for o in body["poll"]["options"] if o["text"] == text)


# ---------------------------------------------------------------------------
# Writing the question
# ---------------------------------------------------------------------------


async def test_create_post_with_a_poll(client: AsyncClient, acting_user, session):
    """A notice and its question are one submission — there is no window where
    the post exists and the poll failed to attach."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)

    response = await client.post(
        a.g("/posts/"),
        headers=a.headers,
        json={
            "name": "Session night",
            "initiative_id": a.initiative.id,
            "body": lexical_body("Pick one."),
            "poll": _poll_payload(),
        },
    )

    assert response.status_code == 201, response.text
    poll = response.json()["poll"]
    assert poll["question"] == "Which night works?"
    assert [option["text"] for option in poll["options"]] == ["Tuesday", "Thursday"]
    assert [option["position"] for option in poll["options"]] == [0, 1]
    assert poll["total_voters"] == 0
    assert poll["has_voted"] is False
    assert poll["is_closed"] is False


async def test_a_post_without_a_poll_serializes_none(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    response = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)

    assert response.status_code == 200, response.text
    assert response.json()["poll"] is None


async def test_poll_needs_two_distinct_choices(
    client: AsyncClient, acting_user, session
):
    """One choice is not a question, and two that say the same thing are one
    choice wearing two labels."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    single = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(options=[{"text": "Tuesday"}]),
    )
    assert single.status_code == 422

    duplicate = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(options=[{"text": "Tuesday"}, {"text": "tuesday"}]),
    )
    assert duplicate.status_code == 422


async def test_poll_cannot_be_born_closed(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    response = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(closes_at=past),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_POLL_CLOSES_IN_PAST"


async def test_writing_a_poll_needs_write_access(
    client: AsyncClient, acting_user, session
):
    """Answering is a reader's gesture; asking is an edit of the notice."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.put(
        a.g(f"/posts/{post.id}/poll"), headers=b.headers, json=_poll_payload()
    )

    assert response.status_code == 403


async def test_deleting_the_poll_leaves_the_notice(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, post)

    response = await client.delete(a.g(f"/posts/{post.id}/poll"), headers=a.headers)

    assert response.status_code == 200, response.text
    assert response.json()["poll"] is None
    assert response.json()["id"] == post.id
    remaining = (
        await session.exec(select(PostPoll).where(PostPoll.post_id == post.id))
    ).all()
    assert remaining == []


async def test_deleting_a_poll_that_is_not_there(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    response = await client.delete(a.g(f"/posts/{post.id}/poll"), headers=a.headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "POST_POLL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Rewriting a poll people have answered
# ---------------------------------------------------------------------------


async def test_rewrite_may_change_everything_but_the_choices(
    client: AsyncClient, acting_user, session
):
    """A ballot cast for "Tuesday" must not become a ballot for whatever takes
    third place — but the question and the switches around it stay editable."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, post)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    read = await client.get(a.g(f"/posts/{post.id}"), headers=b.headers)
    tuesday = _option_id(read.json(), "Tuesday")
    voted = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=b.headers,
        json={"option_ids": [tuesday]},
    )
    assert voted.status_code == 200, voted.text

    changed = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(options=[{"text": "Tuesday"}, {"text": "Friday"}]),
    )
    assert changed.status_code == 409
    assert changed.json()["detail"] == "POST_POLL_HAS_VOTES"

    reworded = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(question="Which evening suits?"),
    )
    assert reworded.status_code == 200, reworded.text
    body = reworded.json()["poll"]
    assert body["question"] == "Which evening suits?"
    # And the answer survived it. Rewriting the choices is destructive — the
    # option rows go and their ballots cascade with them — so a rewrite that
    # leaves them alone has to leave them ALONE, ids included.
    assert body["total_voters"] == 1
    assert [option["id"] for option in body["options"]] == [
        tuesday,
        _option_id(read.json(), "Thursday"),
    ]
    assert next(o for o in body["options"] if o["id"] == tuesday)["vote_count"] == 1


async def test_reordering_the_choices_is_a_change(
    client: AsyncClient, acting_user, session
):
    """Order is what a voter saw, so swapping two choices is not a cosmetic
    edit once somebody has picked one of them."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post)
    session.add(PostPollVote(poll_id=poll.id, option_id=poll.options[0].id, user_id=1))
    await session.commit()

    response = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(options=[{"text": "Thursday"}, {"text": "Tuesday"}]),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "POST_POLL_HAS_VOTES"


async def test_anonymity_can_be_turned_on_but_never_off(
    client: AsyncClient, acting_user, session
):
    """People answered on the understanding their names were not attached, and
    that cannot be revoked afterwards."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post, is_anonymous=True)
    session.add(PostPollVote(poll_id=poll.id, option_id=poll.options[0].id, user_id=1))
    await session.commit()

    revealed = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(is_anonymous=False),
    )
    assert revealed.status_code == 409
    assert revealed.json()["detail"] == "POST_POLL_ANONYMITY_LOCKED"

    kept = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(is_anonymous=True),
    )
    assert kept.status_code == 200, kept.text


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


async def test_a_reader_may_answer(client: AsyncClient, acting_user, session):
    """Answering is a read-level gesture, like reacting — not an edit. The
    answer is the post as this reader sees it, read state included."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, post)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    read = await client.get(a.g(f"/posts/{post.id}"), headers=b.headers)
    thursday = _option_id(read.json(), "Thursday")
    await client.post(
        a.g("/posts/read"), headers=b.headers, json={"post_ids": [post.id]}
    )

    response = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=b.headers,
        json={"option_ids": [thursday]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_read"] is True
    poll = response.json()["poll"]
    assert poll["has_voted"] is True
    assert poll["total_voters"] == 1
    counts = {option["text"]: option["vote_count"] for option in poll["options"]}
    assert counts == {"Tuesday": 0, "Thursday": 1}
    assert [o["voted_by_me"] for o in poll["options"] if o["id"] == thursday] == [True]


async def test_answering_again_replaces_the_first_answer(
    client: AsyncClient, acting_user, session
):
    """Changing your mind is a vote, not a second vote."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, post)
    read = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
    tuesday = _option_id(read.json(), "Tuesday")
    thursday = _option_id(read.json(), "Thursday")

    await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [tuesday]},
    )
    second = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [thursday]},
    )

    assert second.status_code == 200, second.text
    poll = second.json()["poll"]
    assert poll["total_voters"] == 1
    counts = {option["text"]: option["vote_count"] for option in poll["options"]}
    assert counts == {"Tuesday": 0, "Thursday": 1}


async def test_single_choice_refuses_two_answers(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post)
    ids = [option.id for option in poll.options]

    response = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"), headers=a.headers, json={"option_ids": ids}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_POLL_SINGLE_CHOICE"


async def test_multiple_choice_counts_a_voter_once(
    client: AsyncClient, acting_user, session
):
    """``total_voters`` is people, not ticks: somebody who picked both answers
    is one voter, and the larger number would say nothing."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post, allows_multiple=True)
    ids = [option.id for option in poll.options]

    response = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"), headers=a.headers, json={"option_ids": ids}
    )

    assert response.status_code == 200, response.text
    body = response.json()["poll"]
    assert body["total_voters"] == 1
    assert [option["vote_count"] for option in body["options"]] == [1, 1]


async def test_a_ballot_cannot_name_another_polls_choice(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    other = await create_post(session, a.initiative, a.user, name="Another notice")
    await create_post_poll(session, post)
    elsewhere = await create_post_poll(session, other)

    response = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [elsewhere.options[0].id]},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_POLL_OPTION_UNKNOWN"


async def test_a_closed_poll_takes_no_more_answers(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(
        session, post, closes_at=datetime.now(UTC) - timedelta(minutes=1)
    )

    response = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [poll.options[0].id]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "POST_POLL_CLOSED"


async def test_a_draft_collects_no_answers(client: AsyncClient, acting_user, session):
    """A question nobody has been asked yet has no answers to collect — not
    even from the author previewing their own draft."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(
        session,
        a.initiative,
        a.user,
        published_at=None,
        scheduled_for=datetime.now(UTC) + timedelta(days=1),
    )
    poll = await create_post_poll(session, post)

    response = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [poll.options[0].id]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "POST_POLL_NOT_PUBLISHED"


async def test_retracting_an_answer(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post)
    await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [poll.options[0].id]},
    )

    response = await client.delete(
        a.g(f"/posts/{post.id}/poll/vote"), headers=a.headers
    )

    assert response.status_code == 200, response.text
    body = response.json()["poll"]
    assert body["has_voted"] is False
    assert body["total_voters"] == 0


async def test_retracting_when_there_was_no_answer(
    client: AsyncClient, acting_user, session
):
    """Asking for a state a thing is already in is not an error."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, post)

    response = await client.delete(
        a.g(f"/posts/{post.id}/poll/vote"), headers=a.headers
    )

    assert response.status_code == 200, response.text


async def test_answering_a_notice_you_cannot_read(
    client: AsyncClient, acting_user, session
):
    """The poll is reached through the post, so the post's own sharing is the
    gate — a member outside the initiative never reaches the question."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post)
    outsider = await acting_user(guild_role=CommunityRole.member, guild=a.guild)

    response = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=outsider.headers,
        json={"option_ids": [poll.options[0].id]},
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# How much of the answer a reader sees
# ---------------------------------------------------------------------------


async def test_hidden_results_wait_for_this_readers_answer(
    client: AsyncClient, acting_user, session
):
    """Withheld only while there is still something to steer: once this reader
    has answered, the numbers are theirs to see."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post, hide_results=True)

    before = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
    hidden = before.json()["poll"]
    assert hidden["results_visible"] is False
    assert hidden["total_voters"] is None
    assert all(option["vote_count"] is None for option in hidden["options"])

    after = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [poll.options[0].id]},
    )
    shown = after.json()["poll"]
    assert shown["results_visible"] is True
    assert shown["total_voters"] == 1


async def test_hidden_results_open_when_the_poll_closes(
    client: AsyncClient, acting_user, session
):
    """A closed poll has nothing left to steer, so its numbers are shown even
    to somebody who never answered."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await create_post_poll(
        session,
        post,
        hide_results=True,
        closes_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    response = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)

    poll = response.json()["poll"]
    assert poll["is_closed"] is True
    assert poll["results_visible"] is True
    assert poll["total_voters"] == 0


# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------


async def test_a_ballot_and_a_receipt_are_their_owners_to_write(
    client: AsyncClient, acting_user, session, role_session
):
    """Another member and the community's admin read someone's answer and
    read receipt, which the tallies and rosters count, but neither writes nor
    removes one in their name in the database."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post)
    b, c = [
        await acting_user(
            guild_role=CommunityRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        for _ in range(2)
    ]
    await client.post(
        a.g("/posts/read"), headers=b.headers, json={"post_ids": [post.id]}
    )
    voted = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=b.headers,
        json={"option_ids": [poll.options[0].id]},
    )
    assert voted.status_code == 200, voted.text

    for outsider in (c, a):
        asking = await role_session("app_user")
        await route_as(asking, user_id=outsider.user.id, guild_id=a.guild.id)
        voters = (await asking.exec(select(PostPollVote.user_id))).all()
        assert voters == [b.user.id]
        assert (await asking.exec(select(PostRead.user_id))).all() == [b.user.id]
        for model in (PostPollVote, PostRead):
            gone = await asking.exec(delete(model).where(model.user_id == b.user.id))
            assert gone.rowcount == 0, model
        asking.add(
            PostPollVote(
                poll_id=poll.id, option_id=poll.options[1].id, user_id=b.user.id
            )
        )
        with pytest.raises(DBAPIError, match="row-level security"):
            await asking.flush()


async def test_the_roster_names_who_chose_what(
    client: AsyncClient, acting_user, session
):
    """Both sides add up: everybody named under a choice is counted by the
    tally above it, and the waiting side is the rest of the audience."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=b.headers,
        json={"option_ids": [poll.options[0].id]},
    )

    response = await client.get(a.g(f"/posts/{post.id}/poll/voters"), headers=a.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    voted = {
        entry["option_id"]: [voter["id"] for voter in entry["voters"]]
        for entry in body["options"]
    }
    assert voted[poll.options[0].id] == [b.user.id]
    assert voted[poll.options[1].id] == []
    # The author is on the waiting side: writing a question does not stop you
    # answering it, and they have not.
    assert [voter["id"] for voter in body["not_voted"]] == [a.user.id]


async def test_an_anonymous_poll_has_no_roster(
    client: AsyncClient, acting_user, session
):
    """Counts are shown either way; what anonymity hides is the names behind
    them, and it hides them from the author too."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post, is_anonymous=True)
    await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [poll.options[0].id]},
    )

    roster = await client.get(a.g(f"/posts/{post.id}/poll/voters"), headers=a.headers)
    assert roster.status_code == 403
    assert roster.json()["detail"] == "POST_POLL_IS_ANONYMOUS"

    read = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
    assert read.json()["poll"]["total_voters"] == 1


async def test_the_roster_waits_with_the_results(
    client: AsyncClient, acting_user, session
):
    """A roster is the results with names on, so it is withheld wherever they
    are — otherwise counting the names would read them out."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, post, hide_results=True)

    response = await client.get(a.g(f"/posts/{post.id}/poll/voters"), headers=a.headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "POST_POLL_RESULTS_HIDDEN"


async def test_the_board_carries_its_polls(client: AsyncClient, acting_user, session):
    """A board renders its questions, so the list carries them — a page of five
    cards must not be five more requests."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post)
    await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [poll.options[0].id]},
    )

    response = await client.get(
        a.g("/posts/"), headers=a.headers, params={"initiative_id": a.initiative.id}
    )

    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["items"] if item["id"] == post.id)
    assert row["poll"]["total_voters"] == 1
    assert row["poll"]["has_voted"] is True


# ---------------------------------------------------------------------------
# A notice you wrote
# ---------------------------------------------------------------------------


async def test_your_own_notice_is_never_unread_and_never_counted(
    client: AsyncClient, acting_user, session
):
    """The author is on neither side of the read roster, so the card must not
    count them either — a "Read by 1" over a roster listing nobody is the same
    receipt being counted and then not listed."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    # Reading your own board is not reading your own notice: the receipt is
    # refused, and the notice reads as read regardless.
    marked = await client.post(
        a.g("/posts/read"), headers=a.headers, json={"post_ids": [post.id]}
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["marked"] == 0

    read = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
    assert read.json()["is_read"] is True
    assert read.json()["read_count"] == 0

    roster = await client.get(a.g(f"/posts/{post.id}/reads"), headers=a.headers)
    assert roster.json()["read"] == []


async def test_the_unread_filter_skips_your_own_notices(
    client: AsyncClient, acting_user, session
):
    """Otherwise every notice somebody ever posted would sit in their own
    unread filter forever — there is no receipt that could ever clear it."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    mine = await create_post(session, a.initiative, a.user, name="Mine")
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    theirs = await create_post(session, a.initiative, b.user, name="Theirs")

    response = await client.get(
        a.g("/posts/"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "unread": True},
    )

    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()["items"]]
    assert theirs.id in ids
    assert mine.id not in ids


async def test_multiple_choice_can_be_turned_on_but_never_off(
    client: AsyncClient, acting_user, session
):
    """Somebody who ticked two answers would otherwise be left holding two
    ballots on a poll that takes one, and the roster would list them twice."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post, allows_multiple=True)
    ids = [option.id for option in poll.options]
    voted = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"), headers=a.headers, json={"option_ids": ids}
    )
    assert voted.status_code == 200, voted.text

    narrowed = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(allows_multiple=False),
    )
    assert narrowed.status_code == 409
    assert narrowed.json()["detail"] == "POST_POLL_MULTIPLE_LOCKED"

    kept = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(allows_multiple=True),
    )
    assert kept.status_code == 200, kept.text


async def test_two_choices_that_say_the_same_thing_answer_with_a_code(
    client: AsyncClient, acting_user, session
):
    """A rule somebody trips over while typing answers with something the
    composer can put into words, not a validation error nobody can read."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)

    response = await client.put(
        a.g(f"/posts/{post.id}/poll"),
        headers=a.headers,
        json=_poll_payload(options=[{"text": "Tuesday"}, {"text": " tuesday "}]),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "POST_POLL_DUPLICATE_CHOICE"


async def test_the_lock_is_answered_even_when_the_numbers_are_not(
    client: AsyncClient, acting_user, session
):
    """An author of a hidden-results poll needs to know the question is fixed
    before they start editing it. ``total_voters`` cannot tell them — it is the
    withheld number — so the lock is its own answer."""
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    poll = await create_post_poll(session, post, hide_results=True)
    b = await acting_user(
        guild_role=CommunityRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=b.headers,
        json={"option_ids": [poll.options[0].id]},
    )

    seen = (await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)).json()[
        "poll"
    ]

    assert seen["results_visible"] is False
    assert seen["total_voters"] is None
    assert seen["has_voted"] is False
    assert seen["is_locked"] is True


async def test_an_unanswered_poll_is_not_locked(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user)
    await create_post_poll(session, post)

    seen = (await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)).json()[
        "poll"
    ]

    assert seen["is_locked"] is False


async def test_a_copy_is_a_draft_whose_lapsed_poll_opens_when_posted(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    await _posts_enabled(session, a.initiative)
    post = await create_post(session, a.initiative, a.user, pinned_at=datetime.now(UTC))
    await create_post_poll(session, post)
    read = await client.get(a.g(f"/posts/{post.id}"), headers=a.headers)
    voted = await client.put(
        a.g(f"/posts/{post.id}/poll/vote"),
        headers=a.headers,
        json={"option_ids": [_option_id(read.json(), "Tuesday")]},
    )
    assert voted.status_code == 200, voted.text
    poll = (
        await session.exec(select(PostPoll).where(PostPoll.post_id == post.id))
    ).one()
    poll.closes_at = datetime.now(UTC) - timedelta(days=1)
    session.add(poll)
    await session.commit()

    response = await client.post(a.g(f"/posts/{post.id}/duplicate"), headers=a.headers)

    assert response.status_code == 201, response.text
    copy = response.json()
    assert (copy["published_at"], copy["pinned_at"]) == (None, None)
    options = copy["poll"]["options"]
    assert [o["text"] for o in options] == ["Tuesday", "Thursday"]
    assert not any(o["voted_by_me"] for o in options)
    # The deadline is copied as written, and posting the draft after it has
    # passed opens the poll.
    assert datetime.fromisoformat(copy["poll"]["closes_at"]) == poll.closes_at
    posted = await client.patch(
        a.g(f"/posts/{copy['id']}"), headers=a.headers, json={"scheduled_for": None}
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["published_at"] is not None
    assert posted.json()["poll"]["closes_at"] is None
