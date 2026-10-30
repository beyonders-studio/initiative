"""The account channel: who gets poked, when, and what the frame carries.

The point of the channel is that a tab learns its account changed even when
its owner did nothing — so most of these are about somebody *else's* action
reaching a socket.
"""

import pytest

from app.models.platform.guild import CommunityRole
from app.services.platform import account_stream, user_stream
from app.services.platform import rules
from app.services.platform import guilds as guilds_service
from app.testing.sockets import settle
from app.testing import create_guild, create_guild_membership, create_user


@pytest.fixture
def published_remotely(monkeypatch):
    """The ids this worker handed to the bus for the other workers to deliver."""
    seen: list[int] = []

    async def _record(user_ids: list[int], _frame) -> None:
        seen.extend(user_ids)

    monkeypatch.setattr(user_stream, "_publish_remote", _record)
    return seen


@pytest.fixture(autouse=True)
def bus_off(monkeypatch):
    """No cross-process half in these tests.

    The bus is additive and its absence must change nothing, which is also what
    makes it safe to leave out here — the local path is what is under test.
    """

    async def _unavailable(_channel: str, _payload: str) -> None:
        raise RuntimeError("bus not connected")

    from app.services.platform import notify_bus

    monkeypatch.setattr(notify_bus, "notify", _unavailable)


async def test_the_frame_says_nothing_about_the_account(
    session, account_socket
) -> None:
    """It names the channel and nothing else — the client re-reads to learn."""
    user = await create_user(session)
    tab = account_socket(user.id)

    account_stream.queue_account_signal(session, user.id, "membership")
    await session.commit()
    await settle()

    frame = tab.sent[0]
    assert frame["resource"] == "account"
    assert frame["action"] == "membership"
    assert frame["ids"] == {}
    assert set(frame) == {"resource", "action", "ids", "timestamp"}


async def test_no_frame_before_the_commit(session, account_socket) -> None:
    """A tab told to re-read before the COMMIT reads the state being replaced."""
    user = await create_user(session)
    tab = account_socket(user.id)

    account_stream.queue_account_signal(session, user.id, "membership")
    await settle()

    assert tab.sent == []


async def test_rollback_pokes_nobody(session, account_socket) -> None:
    user = await create_user(session)
    tab = account_socket(user.id)

    account_stream.queue_account_signal(session, user.id, "membership")
    await session.rollback()
    await settle()

    assert tab.sent == []


async def test_one_frame_per_channel_per_transaction(session, account_socket) -> None:
    """Three reasons to re-read one account is still one refetch."""
    user = await create_user(session)
    tab = account_socket(user.id)

    for reason in ("membership", "role", "community"):
        account_stream.queue_account_signal(session, user.id, reason)
    await session.commit()
    await settle()

    assert len(tab.sent) == 1


async def test_the_inbox_and_the_account_are_not_the_same_frame(
    session, account_socket
) -> None:
    """Two channels over one socket: one must not swallow the other."""
    from app.services.platform import notification_stream

    user = await create_user(session)
    tab = account_socket(user.id)

    account_stream.queue_account_signal(session, user.id, "membership")
    notification_stream.queue_signal(session, user.id, "created")
    await session.commit()
    await settle()

    assert {frame["resource"] for frame in tab.sent} == {"account", "notification"}


async def test_being_added_to_a_guild_pokes_the_arrival(
    session, account_socket
) -> None:
    """The case this channel exists for: somebody else put them there."""
    user = await create_user(session)
    guild = await create_guild(session)
    tab = account_socket(user.id)

    await guilds_service.ensure_membership(
        session, guild_id=guild.id, user_id=user.id, role=CommunityRole.member
    )
    await session.commit()
    await settle()

    assert [frame["resource"] for frame in tab.sent] == ["account"]


async def test_re_adding_an_existing_member_pokes_nobody(
    session, account_socket
) -> None:
    """Nothing changed, so there is nothing to re-read."""
    user = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild)
    await session.commit()
    tab = account_socket(user.id)

    await guilds_service.ensure_membership(
        session, guild_id=guild.id, user_id=user.id, role=CommunityRole.member
    )
    await session.commit()
    await settle()

    assert tab.sent == []


async def test_listing_a_community_pokes_every_member(
    session, account_socket, published_remotely
) -> None:
    """The fan-out: nobody in the guild did anything, and it changes them all.

    Addressed to the whole roster rather than to the sockets this process is
    holding. A member sitting on another worker has no socket *here*, and the
    frame that reaches them is the one this worker puts on the bus — so a
    roster narrowed by local sockets first would be deciding, from one
    process, that everybody else is absent.
    """
    here = await create_user(session)
    away = await create_user(session)
    guild = await create_guild(session)
    await create_guild_membership(session, user=here, guild=guild)
    await create_guild_membership(session, user=away, guild=guild)
    await session.commit()

    # The directory is a platform-owner switch and starts off, so listing a
    # community is refused until it is on.
    await rules.put(session, "community_directory_enabled", True)
    await session.commit()

    tab = account_socket(here.id)

    await guilds_service.update_guild(
        session,
        guild_id=guild.id,
        name=None,
        description=None,
        retention_days=None,
        retention_days_provided=False,
        is_community=True,
        categories=["other"],
        categories_provided=True,
        has_adult_content=False,
        has_adult_content_provided=True,
    )
    await session.commit()
    await settle()

    assert [frame["resource"] for frame in tab.sent] == ["account"]
    # And the one this worker holds nothing for: published, for whichever
    # worker does hold them. Without it their tab would sit on the old answer
    # until they navigated.
    assert away.id in published_remotely
    assert here.id in published_remotely


async def test_deleting_a_guild_tells_the_people_who_were_in_it(
    session, account_socket
) -> None:
    """The roster goes with the guild, by a cascade nothing in Python sees.

    Every other membership change is announced by the code that wrote the row.
    This one has no such code — the database clears the roster — so the people
    it happens to are resolved before the delete or not at all.
    """
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    member = await create_user(session)
    await create_guild_membership(
        session, user=member, guild=guild, role=CommunityRole.member
    )
    await session.commit()

    tab = account_socket(member.id)

    await guilds_service.delete_guild(session, guild)
    await session.commit()
    await settle()

    assert [frame["resource"] for frame in tab.sent] == ["account"]


async def test_letting_anyone_create_a_community_pokes_every_tab(
    session, account_socket
) -> None:
    """Whether an account may create a community is part of ``/me``, so the
    deployment's switch reaches every open tab, not only its writer's."""
    from app.models.platform.user import UserRole
    from app.services.platform import auth_posture

    owner = await create_user(session, role=UserRole.owner)
    member = await create_user(session)
    tab = account_socket(member.id)
    await rules.put(session, "community_creation_enabled", False)
    await session.commit()

    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner),
        {"community_creation_enabled": True},
    )
    await settle()

    assert [frame["resource"] for frame in tab.sent] == ["account"]
