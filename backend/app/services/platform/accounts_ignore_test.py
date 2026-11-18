"""An ignored account is not a recipient.

The filter lives at the one place a recipient is resolved, so these tests are
about ``accounts.load`` and one fan-out that goes through it end to end. The
seam is what makes the other five fan-outs true without a rule each.
"""

from sqlmodel import select

from app.models.platform.notification import Notification, NotificationType
from app.models.platform.user_ignore import UserIgnore
from app.services.platform import accounts as accounts_service
from app.testing import create_resource_grant, create_user, drain_notices, thread_path


def _mentions(rows: list[Notification]) -> list[Notification]:
    """``Notification.type`` is a string column, so a row reads back as ``str``
    rather than the enum — comparing identity against ``NotificationType``
    would match nothing and pass every assertion."""
    return [row for row in rows if str(row.type) == NotificationType.mention.value]


async def _inbox(session, user_id: int) -> list[Notification]:
    """Read the inbox on a connection of its own.

    The endpoint commits on its own session, so this asks the database rather
    than the test session's snapshot.
    """
    from app.db.session import SystemSessionLocal

    await drain_notices()
    async with SystemSessionLocal() as system_session:
        return list(
            (
                await system_session.exec(
                    select(Notification).where(Notification.user_id == user_id)
                )
            ).all()
        )


async def test_an_account_that_ignores_the_actor_is_not_returned(session):
    ada = await create_user(session)
    bram = await create_user(session)
    session.add(UserIgnore(user_id=ada.id, ignored_user_id=bram.id))
    await session.commit()

    everyone = await accounts_service.load([ada.id])
    assert set(everyone) == {ada.id}

    from_bram = await accounts_service.load([ada.id], excluding_ignorers_of=bram.id)
    assert from_bram == {}


async def test_the_other_direction_is_untouched(session):
    """Ada ignoring Bram silences Bram towards Ada, and nothing else.

    Ada still hears from everyone, and Bram still hears from Ada — ignoring
    governs arrival at the person who did it.
    """
    ada = await create_user(session)
    bram = await create_user(session)
    session.add(UserIgnore(user_id=ada.id, ignored_user_id=bram.id))
    await session.commit()

    # Bram is told about what Ada does: Ada switched off her own inbox, not his.
    to_bram = await accounts_service.load([bram.id], excluding_ignorers_of=ada.id)
    assert set(to_bram) == {bram.id}

    # And Ada is told about everyone except Bram.
    cleo = await create_user(session)
    to_ada = await accounts_service.load([ada.id], excluding_ignorers_of=cleo.id)
    assert set(to_ada) == {ada.id}


async def test_only_the_ignoring_recipient_drops_out(session):
    """One person's ignore does not cost anybody else their notice."""
    ada = await create_user(session)
    cleo = await create_user(session)
    bram = await create_user(session)
    session.add(UserIgnore(user_id=ada.id, ignored_user_id=bram.id))
    await session.commit()

    recipients = await accounts_service.load(
        [ada.id, cleo.id], excluding_ignorers_of=bram.id
    )
    assert set(recipients) == {cleo.id}


async def test_omitting_the_actor_filters_nothing(session):
    """The export worker re-runs a job as the person who asked for it, and is
    not telling anybody anything."""
    ada = await create_user(session)
    bram = await create_user(session)
    session.add(UserIgnore(user_id=ada.id, ignored_user_id=bram.id))
    await session.commit()

    assert set(await accounts_service.load([ada.id])) == {ada.id}


async def test_stopping_lets_the_next_one_through(session):
    """Nothing from the quiet period is reconstructed — none of it was written
    — but everything after it arrives."""
    ada = await create_user(session)
    bram = await create_user(session)
    row = UserIgnore(user_id=ada.id, ignored_user_id=bram.id)
    session.add(row)
    await session.commit()
    assert await accounts_service.load([ada.id], excluding_ignorers_of=bram.id) == {}

    await session.delete(row)
    await session.commit()

    assert set(
        await accounts_service.load([ada.id], excluding_ignorers_of=bram.id)
    ) == {ada.id}


async def test_a_mention_from_an_ignored_account_writes_no_notification(
    client, session, acting_user
):
    """End to end through a comment: the mention is written and rendered, and
    the person who is ignoring hears nothing about it."""
    from app.models.platform.guild import CommunityRole

    bram = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    ada = await acting_user(
        guild_role=CommunityRole.member,
        guild=bram.guild,
        initiative=bram.initiative,
        initiative_role="member",
    )
    session.add(UserIgnore(user_id=ada.user.id, ignored_user_id=bram.user.id))
    await session.commit()

    task = await _a_task(session, bram)
    before = len(await _inbox(session, ada.user.id))

    posted = await client.post(
        bram.g(thread_path("task", task.id)),
        json={
            "content": f"hello @[{ada.user.username}]({ada.user.id})",
        },
        headers=bram.headers,
    )
    assert posted.status_code in (200, 201), posted.text

    after = await _inbox(session, ada.user.id)
    assert len(after) == before
    assert not _mentions(after)

    # The control, without which the assertion above passes even if mentions
    # notify nobody: the same comment from the same person, once Ada is no
    # longer ignoring them, does arrive.
    ignore = await session.get(UserIgnore, (ada.user.id, bram.user.id))
    await session.delete(ignore)
    await session.commit()

    again = await client.post(
        bram.g(thread_path("task", task.id)),
        json={
            "content": f"still here @[{ada.user.username}]({ada.user.id})",
        },
        headers=bram.headers,
    )
    assert again.status_code in (200, 201), again.text

    assert len(_mentions(await _inbox(session, ada.user.id))) == 1


async def _a_task(session, actor):
    """A task in a project every member of the initiative can read, so the
    people mentioned on it are people who may be told."""
    from app.testing import create_task

    await create_resource_grant(
        session, actor.project, all_initiative_members=True, commit=False
    )
    task = await create_task(session, actor.project)
    await session.commit()
    return task
