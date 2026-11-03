"""The two surfaces that decide what a notification leaves the app carrying.

One is the operator's, on Platform → Security, and binds the whole deployment.
The other is a community's own seat, and narrows its half of the same three
questions. The tests below cover who may reach each of them, that the stricter
answer is what the community's page is told, and the one thing switching push
off promises beyond silence: the deployment stops holding device tokens and
declines new ones.
"""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import CommunityRole
from app.models.platform.push_token import PushToken
from app.models.platform.user import UserRole
from app.services.platform import notification_policy, push_tokens
from app.testing import (
    create_guild,
    create_user,
    get_auth_headers,
    guild_administration,
)
from app.services.platform import rules


PLATFORM = "/api/v1/settings/notifications"


def _settings(guild_id: int) -> str:
    return f"/api/v1/communities/{guild_id}/auth-settings"


def _all(**overrides: bool) -> dict:
    body = {
        "push_notifications_enabled": True,
        "email_notifications_enabled": True,
        "redact_notification_content": False,
    }
    body.update(overrides)
    return body


async def _owner(session: AsyncSession, email: str):
    user = await create_user(session, email=email, role=UserRole.owner)
    return user, get_auth_headers(user)


# --- the deployment's answers ------------------------------------------------


async def test_a_fresh_deployment_restricts_nothing(client, session) -> None:
    """An upgrade asks nothing of anybody it was not already asking."""
    _, headers = await _owner(session, "fresh-notify@example.com")

    body = (await client.get(PLATFORM, headers=headers)).json()

    assert body["push_notifications_enabled"] is True
    assert body["email_notifications_enabled"] is True
    assert body["redact_notification_content"] is False


async def test_only_the_owner_reaches_the_deployments_answers(client, session) -> None:
    member = await create_user(session, email="member-notify@example.com")
    headers = get_auth_headers(member)

    assert (await client.get(PLATFORM, headers=headers)).status_code == 403
    assert (await client.put(PLATFORM, json=_all(), headers=headers)).status_code == 403


async def test_the_owner_sets_all_three_and_they_stick(client, session) -> None:
    _, headers = await _owner(session, "sets-notify@example.com")

    written = await client.put(
        PLATFORM,
        json=_all(
            push_notifications_enabled=False,
            email_notifications_enabled=False,
            redact_notification_content=True,
        ),
        headers=headers,
    )

    assert written.status_code == 200, written.text
    assert written.json()["push_notifications_enabled"] is False
    read = (await client.get(PLATFORM, headers=headers)).json()
    assert read["email_notifications_enabled"] is False
    assert read["redact_notification_content"] is True


# --- what switching push off actually does -----------------------------------


async def test_switching_push_off_drops_the_tokens_and_declines_new_ones(
    client, session
) -> None:
    """The deployment stops sending, and stops holding the addresses it was
    sending to. A device registers again when it is switched back on."""
    owner, headers = await _owner(session, "drops-tokens@example.com")
    await push_tokens.register_push_token(
        session=session,
        user_id=owner.id,
        push_token="a-device",
        platform="android",
    )
    assert len((await session.exec(select(PushToken))).all()) == 1

    off = await client.put(
        PLATFORM, json=_all(push_notifications_enabled=False), headers=headers
    )

    assert off.status_code == 200, off.text
    assert (await session.exec(select(PushToken))).all() == []

    declined = await client.post(
        "/api/v1/push/register",
        json={"push_token": "another-device", "platform": "android"},
        headers=headers,
    )
    assert declined.status_code == 403
    assert declined.json()["detail"] == "PUSH_NOTIFICATIONS_DISABLED"

    back_on = await client.put(PLATFORM, json=_all(), headers=headers)
    assert back_on.status_code == 200
    accepted = await client.post(
        "/api/v1/push/register",
        json={"push_token": "another-device", "platform": "android"},
        headers=headers,
    )
    assert accepted.status_code == 200


async def test_email_off_leaves_the_tokens_alone(client, session) -> None:
    """Only the push switch drops them; the other two are about wording and
    mail."""
    owner, headers = await _owner(session, "keeps-tokens@example.com")
    await push_tokens.register_push_token(
        session=session,
        user_id=owner.id,
        push_token="kept-device",
        platform="android",
    )

    response = await client.put(
        PLATFORM,
        json=_all(email_notifications_enabled=False, redact_notification_content=True),
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert len((await session.exec(select(PushToken))).all()) == 1


# --- a community's own answers -----------------------------------------------


async def test_the_seat_sets_its_communitys_answers(
    client, session, acting_user
) -> None:
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    await guild_administration(session, seat.guild, auth_options=["restrictions"])

    written = await client.patch(
        _settings(seat.guild.id),
        json={
            "allow_push_notifications": False,
            "allow_email_notifications": True,
            "redact_notification_content": True,
        },
        headers=seat.headers,
    )

    assert written.status_code == 200, written.text
    body = written.json()
    assert body["allow_push_notifications"] is False
    assert body["redact_notification_content"] is True
    stored = (await rules.community_values(session, [seat.guild.id], applied=False))[
        seat.guild.id
    ]
    assert stored["allow_push_notifications"] is False
    assert stored["redact_notification_content"] is True
    assert not (await notification_policy.resolve(session, seat.guild.id)).push

    # They apply while it holds the ``restrictions`` option they need.
    await guild_administration(session, seat.guild, auth_options=[])
    assert await notification_policy.resolve(
        session, seat.guild.id
    ) == await notification_policy.resolve(session, None)


async def test_the_page_is_told_what_the_deployment_already_asks(
    client, session, acting_user
) -> None:
    """So a switch with nothing to add says so rather than offering the same
    answer twice."""
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    await guild_administration(session, seat.guild, auth_options=["restrictions"])
    await rules.put(session, "push_notifications_enabled", False)
    await rules.put(session, "redact_notification_content", True)
    await session.commit()

    body = (await client.get(_settings(seat.guild.id), headers=seat.headers)).json()

    assert body["push_allowed_by_platform"] is False
    assert body["email_allowed_by_platform"] is True
    assert body["redacted_by_platform"] is True
    # The community's own answers are unchanged by the deployment's; the
    # stricter of the pair is what binds when a notification is sent.
    assert body["allow_push_notifications"] is True
    assert body["redact_notification_content"] is False


async def test_one_communitys_answer_does_not_reach_another(
    client, session, acting_user
) -> None:
    seat = await acting_user(guild_role=CommunityRole.superadmin)
    await guild_administration(session, seat.guild, auth_options=["restrictions"])
    elsewhere = await create_guild(session)

    await client.patch(
        _settings(seat.guild.id),
        json={
            "allow_push_notifications": False,
            "allow_email_notifications": False,
            "redact_notification_content": True,
        },
        headers=seat.headers,
    )

    stored = (await rules.community_values(session, [elsewhere.id], applied=False))[
        elsewhere.id
    ]
    assert stored["allow_push_notifications"] is True
    assert stored["allow_email_notifications"] is True
    assert stored["redact_notification_content"] is False
