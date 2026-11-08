"""The change an account has waiting.

It is read and cancelled from the account's settings, made at once from a
session proved with a passkey, and cancelled by the sweep where the account no
longer allows it by the time it is due.
"""

from datetime import UTC, datetime

from httpx2 import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.account_change_hold import AccountChangeHold, HeldChangeKind
from app.models.platform.user import User
from app.services.auth import addresses, held_changes
from app.testing import create_user, get_auth_headers, signed_in_headers

HELD = "/api/v1/me/held-change"


async def _held_primary(
    client: AsyncClient, session: AsyncSession, email: str
) -> tuple[User, dict]:
    """An account whose move of the primary to a second address waits."""
    user = await create_user(session, email=email)
    spare = addresses.record_address(
        session,
        user_id=user.id,
        email=f"spare-{email}",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()
    spare_id = spare.id
    response = await client.put(
        f"/api/v1/me/emails/{spare_id}/primary",
        json={"current_password": "testpassword123"},
        headers=await signed_in_headers(session, user),
    )
    assert response.status_code == 202, response.text
    return user, response.json()


async def test_the_waiting_change_is_read_and_cancelled(
    client: AsyncClient, session: AsyncSession
):
    user, held = await _held_primary(client, session, "cancels@example.com")
    headers = get_auth_headers(user)

    read = await client.get(HELD, headers=headers)
    assert read.status_code == 200, read.text
    assert read.json() == held

    cancelled = await client.post(f"{HELD}/{held['id']}/cancel", headers=headers)
    assert cancelled.status_code == 204, cancelled.text
    again = await client.post(f"{HELD}/{held['id']}/cancel", headers=headers)
    assert again.status_code == 404
    assert again.json()["detail"] == "HELD_CHANGE_NOT_FOUND"
    assert (await client.get(HELD, headers=headers)).json() is None

    due = datetime.now(UTC) + held_changes.HOLD_FOR
    assert await held_changes.apply_due(session, now=due) == 0
    assert (
        await addresses.primary_address(session, user_id=user.id)
        == "cancels@example.com"
    )


async def test_a_passkey_makes_the_waiting_change_at_once(
    client: AsyncClient, session: AsyncSession
):
    user, held = await _held_primary(client, session, "now@example.com")
    user_id, headers = user.id, get_auth_headers(user)
    apply = f"{HELD}/{held['id']}/apply"

    refused = await client.post(apply, headers=await signed_in_headers(session, user))
    assert refused.status_code == 403
    assert refused.json()["detail"] == "HELD_CHANGE_NEEDS_PASSKEY"

    made = await client.post(
        apply, headers=await signed_in_headers(session, user, amr=["hwk"])
    )
    assert made.status_code == 204, made.text
    session.expire_all()
    assert await addresses.primary_address(session, user_id=user_id) == (
        "spare-now@example.com"
    )
    assert (await client.get(HELD, headers=headers)).json() is None


async def test_a_change_the_account_no_longer_allows_is_cancelled_when_due(
    session: AsyncSession,
):
    """Its address became the primary meanwhile, which is not removed."""
    user = await create_user(session, email="lapses@example.com")
    user_id = user.id
    spare = addresses.record_address(
        session,
        user_id=user_id,
        email="lapsing@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()
    await held_changes.hold(
        session,
        user,
        kind=HeldChangeKind.remove_address,
        session_id=None,
        address_id=spare.id,
    )
    await addresses.set_primary_for_user(session, user_id=user_id, address_id=spare.id)
    await session.commit()

    due = datetime.now(UTC) + held_changes.HOLD_FOR
    assert await held_changes.apply_due(session, now=due) == 0
    assert await held_changes.pending_for_user(session, user_id=user_id) is None
    assert await addresses.primary_address(session, user_id=user_id) == (
        "lapsing@example.com"
    )


async def test_a_made_removal_keeps_its_hold(session: AsyncSession):
    """For the run of changes it counts towards, past the address it took."""
    user = await create_user(session, email="keeps-hold@example.com")
    spare = addresses.record_address(
        session,
        user_id=user.id,
        email="taken@example.com",
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
    )
    await session.commit()
    hold = await held_changes.hold(
        session,
        user,
        kind=HeldChangeKind.remove_address,
        session_id=None,
        address_id=spare.id,
    )
    hold_id = hold.id
    assert hold_id is not None

    assert await held_changes.apply(session, user, hold_id=hold_id, risky=True)
    session.expire_all()
    row = await session.get(AccountChangeHold, hold_id)
    assert row is not None and row.applied_at is not None
