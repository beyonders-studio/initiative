"""Telling a change the owner made from a risky one.

A passkey makes it the owner's. So does somewhere the account already uses,
unless the change is one of a run. A step-up proves the person again without
starting their time here over.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.requests import Request

from app.api.v1.platform_endpoints.change_assessment import risky_session
from app.api.v1.platform_endpoints.session_opening import issue_session
from app.models.platform.account_change_hold import HeldChangeKind
from app.models.platform.auth_session import AuthSession
from app.models.platform.email_outbox import EmailOutboxItem
from app.models.platform.user import User
from app.services.auth import held_changes
from app.services.auth import sessions as session_service
from app.testing import create_user


async def _session(
    session: AsyncSession,
    user: User,
    *,
    amr: tuple[str, ...] = ("pwd",),
    hours_ago: float = 0,
    device: bool = False,
) -> AuthSession:
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=list(amr),
        satisfied_providers=[],
        install_id=uuid.uuid4() if device else None,
    )
    issued.session.created_at = datetime.now(UTC) - timedelta(hours=hours_ago)
    session.add(issued.session)
    await session.commit()
    return issued.session


async def _notice(
    session: AsyncSession,
    user: User,
    *,
    minutes_ago: float,
    change: dict | None = None,
) -> None:
    """One earlier change's letter, as the outbox keeps it."""
    at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    session.add(
        EmailOutboxItem(
            user_id=user.id,
            category="account",
            security=True,
            change=change or {"notice": "passkey.added"},
            locale="en",
            subject="s",
            headline="h",
            body="b",
            created_at=at,
            deliver_after=at,
        )
    )
    await session.commit()


async def test_a_passkey_makes_a_change_the_owners(session: AsyncSession):
    user = await create_user(session, email="passkey-owner@example.com")
    fresh = await _session(session, user, amr=("hwk", "mfa"))
    assert not await risky_session(session, fresh)


async def test_a_fresh_sign_in_without_a_passkey_is_risky(session: AsyncSession):
    user = await create_user(session, email="fresh@example.com")
    fresh = await _session(session, user)
    assert await risky_session(session, fresh)


async def test_somewhere_the_account_already_uses_is_the_owners(
    session: AsyncSession,
):
    user = await create_user(session, email="usual-place@example.com")
    app = await _session(session, user, device=True)
    browser = await _session(session, user, hours_ago=25)
    assert not await risky_session(session, app)
    assert not await risky_session(session, browser)


async def test_a_run_of_changes_is_risky_even_from_the_usual_place(
    session: AsyncSession,
):
    user = await create_user(session, email="run@example.com")
    browser = await _session(session, user, hours_ago=48)
    await _notice(session, user, minutes_ago=30)
    assert not await risky_session(session, browser)

    await _notice(session, user, minutes_ago=10)
    assert await risky_session(session, browser)


async def test_a_held_change_counts_towards_a_run_once(session: AsyncSession):
    """From its hold, which is there with no mail sent, and not again from
    its letter."""
    user = await create_user(session, email="held-run@example.com")
    user_id = user.id
    browser = await _session(session, user, hours_ago=48)
    for count in (1, 2):
        held = await held_changes.hold(
            session, user, kind=HeldChangeKind.second_factor_off, session_id=None
        )
        await _notice(
            session,
            user,
            minutes_ago=0,
            change={"notice": "secondFactor.disableHeld", "undo": {"kind": "hold"}},
        )
        assert await risky_session(session, browser) is (count == 2)
        await held_changes.cancel(
            session, user_id=user_id, hold_id=held.id, via="settings"
        )
        await session.commit()


async def test_a_step_up_keeps_how_long_the_person_has_been_signed_in(
    session: AsyncSession,
):
    user = await create_user(session, email="stepped-up@example.com")
    signed_in = await _session(session, user, hours_ago=48)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [],
        }
    )

    opened = await issue_session(
        request,
        session,
        user_id=user.id,
        token_version=user.token_version,
        amr=["pwd", "otp"],
        replaces=signed_in.id,
    )
    await session.commit()

    assert opened.session.continues_since == signed_in.created_at
    assert not await risky_session(session, opened.session)

    # And across the renewals after it.
    rotated = await session_service.rotate_session(
        session, raw_refresh_token=opened.refresh_token
    )
    await session.commit()
    assert rotated.issued is not None
    renewed = rotated.issued.session
    assert renewed.continues_since == signed_in.created_at
    assert not await risky_session(session, renewed)
