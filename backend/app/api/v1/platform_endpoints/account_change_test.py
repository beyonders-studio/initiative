"""Answering an account letter: "This wasn't me".

The links are minted by the outbox worker as it sends each copy. A link reads
without spending, signs the account out everywhere once, and holds only while
the address it went to stands on the same proof. A risky change can be undone
from a copy sent to an address older than the newest one involved.
"""

import re
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import SALT_EMAIL, decrypt_field
from app.models.platform.account_change_hold import HeldChangeKind
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User
from app.models.platform.user_email import UserEmail
from app.models.platform.user_passkey import UserPasskey
from app.models.platform.user_token import UserTokenPurpose
from app.services import email as email_service
from app.services.auth import account_changes, addresses, held_changes
from app.services.auth import sessions as session_service
from app.services.platform import email_outbox, user_tokens
from app.services.platform import security_signals_test as signals
from app.testing import create_user, signed_in_headers

READ = "/api/v1/auth/account-change/read"
SIGN_OUT = "/api/v1/auth/account-change/sign-out"
UNDO = "/api/v1/auth/account-change/undo"


# The security suite's fixture, by name.
security_desk = signals.security_desk


@pytest.fixture
def mailed(monkeypatch) -> dict[str, str | None]:
    """Account letters sent as the worker sends them, keeping the token in
    each copy's link by the address it went to."""
    links: dict[str, str | None] = {}

    async def deliver(session, user, *, recipient: str, html_body: str, **_):
        found = re.search(r"/account/not-me\?token=([\w-]+)", html_body)
        links[recipient] = found.group(1) if found else None

    monkeypatch.setattr(email_service, "email_configured", AsyncMock(return_value=True))
    monkeypatch.setattr(email_service, "deliver", deliver)
    monkeypatch.setattr(
        email_service, "email_context", AsyncMock(return_value=(None, "#123456"))
    )
    return links


async def _send(
    session: AsyncSession,
    links: dict[str, str | None],
    user: User,
    *,
    notice: str = "passkey.added",
    risky: bool | None = None,
    undo: dict[str, Any] | None = None,
    also_to: tuple[str, ...] = (),
) -> dict[str, str | None]:
    """Queue and send one account letter; the link each address got."""
    change: dict[str, Any] = {"notice": notice}
    if undo is not None:
        change |= await account_changes.change_record(
            session, user_id=user.id, risky=bool(risky), undo=undo
        )
    links.clear()
    await email_outbox.enqueue_account_letter(
        user,
        email_service.EmailPieces(subject="s", headline="h", body="b"),
        change=change,
        also_to=also_to,
    )
    await email_outbox._run_pass(session, now=datetime.now(UTC))
    return dict(links)


async def _address(
    session: AsyncSession, user: User, email: str, *, primary: bool = False
) -> UserEmail:
    """A proved address, newer than every one before it."""
    row = addresses.record_address(
        session,
        user_id=user.id,
        email=email,
        source=addresses.SOURCE_ADDED,
        verified=True,
        is_primary=False,
        now=datetime.now(UTC),
    )
    await session.commit()
    if primary:
        await addresses.set_primary_for_user(
            session, user_id=user.id, address_id=row.id
        )
        await session.commit()
    await session.refresh(row)
    return row


async def _primary(session: AsyncSession, user_id: int) -> str | None:
    session.expire_all()
    return await addresses.primary_address(session, user_id=user_id)


async def _held(session: AsyncSession, user_id: int) -> set[str]:
    session.expire_all()
    return {
        decrypt_field(row.email_encrypted, SALT_EMAIL)
        for row in await addresses.list_for_user(session, user_id=user_id)
    }


async def test_reading_a_link_says_what_it_may_do_and_spends_nothing(
    client: AsyncClient, session: AsyncSession, mailed
):
    user = await create_user(session, email="reads@example.com")
    token = (await _send(session, mailed, user))["reads@example.com"]

    for _ in range(2):
        response = await client.post(READ, json={"token": token})
        assert response.status_code == 200, response.text
        assert response.json() == {
            "notice": "passkey.added",
            "sign_out": True,
            "undo": None,
            "subject": None,
        }
    assert (await client.post(SIGN_OUT, json={"token": token})).status_code == 200


async def test_a_link_signs_the_account_out_everywhere_once(
    client: AsyncClient, session: AsyncSession, mailed
):
    user = await create_user(session, email="not-me@example.com")
    user_id, version = user.id, user.token_version
    opened = await session_service.create_session(
        session, user_id=user_id, amr=["pwd"], satisfied_providers=[]
    )
    session_id = opened.session.id
    await session.commit()
    token = (await _send(session, mailed, user))["not-me@example.com"]

    response = await client.post(SIGN_OUT, json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "signed_out"

    session.expire_all()
    assert (await session.get(User, user_id)).token_version == version + 1
    assert (await session.get(AuthSession, session_id)).revoked_at is not None

    again = await client.post(SIGN_OUT, json={"token": token})
    assert again.status_code == 400
    assert again.json()["detail"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_only_a_live_link_of_its_own_purpose_answers(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="stale@example.com")
    for purpose, minutes in (
        (UserTokenPurpose.account_change, -1),
        (UserTokenPurpose.password_reset, 60),
    ):
        token = await user_tokens.create_token(
            session, user_id=user.id, purpose=purpose, expires_minutes=minutes
        )
        for route in (READ, SIGN_OUT, UNDO):
            response = await client.post(route, json={"token": token})
            assert response.status_code == 400, response.text
            assert response.json()["detail"] == "INVALID_OR_EXPIRED_TOKEN"


async def test_a_link_holds_only_while_its_address_stands_on_the_same_proof(
    client: AsyncClient, session: AsyncSession, mailed
):
    """Removed, added back unproved, and proved again: each leaves the link
    sent to it dead."""
    user = await create_user(session, email="stays@example.com")
    spare = await _address(session, user, "leaves@example.com")
    token = (await _send(session, mailed, user))["leaves@example.com"]
    assert (await client.post(READ, json={"token": token})).status_code == 200

    await session.delete(spare)
    await session.commit()
    assert (await client.post(READ, json={"token": token})).status_code == 400

    again = addresses.record_address(
        session,
        user_id=user.id,
        email="leaves@example.com",
        source=addresses.SOURCE_ADDED,
        verified=False,
        is_primary=False,
    )
    await session.commit()
    assert (await client.post(READ, json={"token": token})).status_code == 400

    again.verified_at = datetime.now(UTC)
    session.add(again)
    await session.commit()
    for route in (READ, SIGN_OUT):
        assert (await client.post(route, json={"token": token})).status_code == 400


async def test_an_address_removed_before_its_copy_goes_gets_no_link(
    session: AsyncSession, mailed
):
    user = await create_user(session, email="keeps@example.com")
    spare = await _address(session, user, "gone-first@example.com")
    await email_outbox.enqueue_account_letter(
        user,
        email_service.EmailPieces(subject="s", headline="h", body="b"),
        change={"notice": "passkey.added"},
    )
    await session.delete(spare)
    await session.commit()

    await email_outbox._run_pass(session, now=datetime.now(UTC))
    assert mailed["gone-first@example.com"] is None
    assert mailed["keeps@example.com"] is not None


async def test_a_sign_out_that_fails_leaves_the_link_good(
    client: AsyncClient, session: AsyncSession, mailed, monkeypatch
):
    user = await create_user(session, email="retry-link@example.com")
    token = (await _send(session, mailed, user))["retry-link@example.com"]

    async def fail(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(user_tokens, "revoke_user_sessions", fail)
    with pytest.raises(RuntimeError):
        await client.post(SIGN_OUT, json={"token": token})

    monkeypatch.undo()
    response = await client.post(SIGN_OUT, json={"token": token})
    assert response.status_code == 200, response.text


async def test_only_an_older_address_may_undo_and_only_a_risky_change(
    client: AsyncClient, session: AsyncSession, mailed
):
    user = await create_user(session, email="older@example.com")
    newer = await _address(session, user, "newer@example.com")
    undo = {"kind": "proved", "address_id": newer.id}

    owners = await _send(session, mailed, user, risky=False, undo=undo)
    risky = await _send(session, mailed, user, risky=True, undo=undo)

    for token in (owners["older@example.com"], risky["newer@example.com"]):
        response = await client.post(READ, json={"token": token})
        assert response.json()["undo"] is None
        assert (await client.post(UNDO, json={"token": token})).status_code == 400

    response = await client.post(READ, json={"token": risky["older@example.com"]})
    assert response.json() == {
        "notice": "passkey.added",
        "sign_out": True,
        "undo": "proved",
        "subject": "newer@example.com",
    }


async def test_undoing_a_proved_address_takes_it_back_and_the_primary_with_it(
    client: AsyncClient, session: AsyncSession, mailed
):
    user = await create_user(session, email="mine@example.com")
    user_id, version = user.id, user.token_version
    theirs = await _address(session, user, "theirs@example.com", primary=True)
    links = await _send(
        session,
        mailed,
        user,
        notice="address.proved",
        risky=True,
        undo={"kind": "proved", "address_id": theirs.id},
    )

    response = await client.post(UNDO, json={"token": links["mine@example.com"]})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "undone"
    assert await _held(session, user_id) == {"mine@example.com"}
    assert await _primary(session, user_id) == "mine@example.com"
    assert (await session.get(User, user_id)).token_version == version + 1


async def test_undoing_a_primary_change_moves_it_back_unless_it_moved_again(
    client: AsyncClient, session: AsyncSession, mailed
):
    user = await create_user(session, email="first@example.com")
    user_id = user.id
    previous = (await addresses.list_for_user(session, user_id=user_id))[0]
    second = await _address(session, user, "second@example.com", primary=True)
    undo = {"kind": "primary", "address_id": previous.id, "made_primary": second.id}
    links = await _send(
        session, mailed, user, notice="address.primary", risky=True, undo=undo
    )
    stale = await _send(
        session, mailed, user, notice="address.primary", risky=True, undo=undo
    )

    response = await client.post(UNDO, json={"token": links["first@example.com"]})
    assert response.status_code == 200, response.text
    assert await _primary(session, user_id) == "first@example.com"

    # The primary has moved since that change, so its other notice stands down.
    response = await client.post(UNDO, json={"token": stale["first@example.com"]})
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "ACCOUNT_CHANGE_MOVED_ON"


async def test_undoing_a_removal_puts_the_address_back_over_the_later_ones(
    client: AsyncClient, session: AsyncSession, mailed
):
    """The removed address's own copy reverses the run: it comes back, proved
    and primary, and the address proved after it goes. One added after the
    removal stays."""
    user = await create_user(session, email="original@example.com")
    user_id = user.id
    original = (await addresses.list_for_user(session, user_id=user_id))[0]
    taker = await _address(session, user, "taker@example.com", primary=True)
    undo = account_changes.removal_undo(original, primary_id=taker.id)
    record = await account_changes.change_record(
        session, user_id=user_id, risky=True, undo=undo
    )
    await session.delete(original)
    await session.commit()
    await _address(session, user, "later@example.com")

    mailed.clear()
    await email_outbox.enqueue_account_letter(
        user,
        email_service.EmailPieces(subject="s", headline="h", body="b"),
        change={"notice": "address.removed", **record},
        also_to=["original@example.com"],
    )
    await email_outbox._run_pass(session, now=datetime.now(UTC))
    token = mailed["original@example.com"]

    read = await client.post(READ, json={"token": token})
    assert read.json() == {
        "notice": "address.removed",
        "sign_out": False,
        "undo": "removed",
        "subject": "original@example.com",
    }
    assert (await client.post(SIGN_OUT, json={"token": token})).status_code == 400

    response = await client.post(UNDO, json={"token": token})
    assert response.status_code == 200, response.text
    assert await _held(session, user_id) == {
        "original@example.com",
        "later@example.com",
    }
    assert await _primary(session, user_id) == "original@example.com"


async def test_a_removal_undo_works_over_a_minted_primary(
    client: AsyncClient, session: AsyncSession, mailed
):
    """An account a provider made with no address keeps the address minted
    for it as primary beside the ones it proved. Removing one of those
    through the route, held and then made, still leaves its copy able to put
    it back, and the minted address, proved in the same hour, is not one of
    the run it reverses."""
    user = await create_user(session, email="older-sso@example.com")
    user_id = user.id
    older = (await addresses.list_for_user(session, user_id=user_id))[0]
    minted = addresses.record_address(
        session,
        user_id=user_id,
        email=f"idp-{user_id}@oidc.local",
        source=addresses.SOURCE_SYNTHETIC,
        verified=True,
        is_primary=False,
        now=datetime.now(UTC),
    )
    older.is_primary = False
    session.add(older)
    await session.flush()
    minted.is_primary = True
    session.add(minted)
    await session.commit()
    minted_id = minted.id
    await _address(session, user, "newer-sso@example.com")

    held = await client.post(
        f"/api/v1/me/emails/{older.id}/remove",
        json={"current_password": "testpassword123"},
        headers=await signed_in_headers(session, user),
    )
    assert held.status_code == 202, held.text
    await email_outbox._run_pass(session, now=datetime.now(UTC))
    await held_changes.apply_due(session, now=datetime.now(UTC) + held_changes.HOLD_FOR)
    mailed.clear()
    await email_outbox._run_pass(session, now=datetime.now(UTC))

    response = await client.post(UNDO, json={"token": mailed["older-sso@example.com"]})
    assert response.status_code == 200, response.text
    assert await _primary(session, user_id) == "older-sso@example.com"
    assert await session.get(UserEmail, minted_id) is not None


async def test_undoing_a_move_off_a_minted_primary_makes_the_clicker_primary(
    client: AsyncClient, session: AsyncSession, mailed
):
    """A minted address takes no mail, so the copy to an older address puts
    the primary on that address rather than back on the minted one."""
    user = await create_user(session, email="kept@example.com")
    user_id = user.id
    kept = (await addresses.list_for_user(session, user_id=user_id))[0]
    minted = addresses.record_address(
        session,
        user_id=user_id,
        email=f"idp-{user_id}@oidc.local",
        source=addresses.SOURCE_SYNTHETIC,
        verified=False,
        is_primary=False,
    )
    kept.is_primary = False
    session.add(kept)
    await session.flush()
    minted.is_primary = True
    session.add(minted)
    await session.commit()
    taker = await _address(session, user, "taker@example.com")

    held = await client.put(
        f"/api/v1/me/emails/{taker.id}/primary",
        json={"current_password": "testpassword123"},
        headers=await signed_in_headers(session, user),
    )
    assert held.status_code == 202, held.text
    await email_outbox._run_pass(session, now=datetime.now(UTC))
    await held_changes.apply_due(session, now=datetime.now(UTC) + held_changes.HOLD_FOR)
    mailed.clear()
    await email_outbox._run_pass(session, now=datetime.now(UTC))
    token = mailed["kept@example.com"]

    read = await client.post(READ, json={"token": token})
    assert (read.json()["undo"], read.json()["subject"]) == (
        "primary",
        "kept@example.com",
    )
    response = await client.post(UNDO, json={"token": token})
    assert response.status_code == 200, response.text
    assert await _primary(session, user_id) == "kept@example.com"


async def test_the_newest_address_removed_gets_no_link(session: AsyncSession, mailed):
    """An owner removing the address added last: that address is the newest,
    so its copy may not put it back."""
    user = await create_user(session, email="owner@example.com")
    newest = await _address(session, user, "removed-newest@example.com")
    record = await account_changes.change_record(
        session,
        user_id=user.id,
        risky=True,
        undo=account_changes.removal_undo(newest, primary_id=None),
    )
    await session.delete(newest)
    await session.commit()

    await email_outbox.enqueue_account_letter(
        user,
        email_service.EmailPieces(subject="s", headline="h", body="b"),
        change={"notice": "address.removed", **record},
        also_to=["removed-newest@example.com"],
    )
    await email_outbox._run_pass(session, now=datetime.now(UTC))
    assert mailed["removed-newest@example.com"] is None
    assert mailed["owner@example.com"] is not None


async def test_undoing_a_passkey_removes_it_unless_it_is_the_last_way_in(
    client: AsyncClient, session: AsyncSession, mailed
):
    for email, password in (
        ("pk-undo@example.com", True),
        ("pk-last@example.com", False),
    ):
        user = await create_user(session, email=email)
        if not password:
            user.hashed_password = None
            session.add(user)
            await session.commit()
        await _address(session, user, f"newer-{email}")
        passkey = UserPasskey(
            user_id=user.id,
            credential_id=f"undo-{user.id}".encode(),
            public_key=b"public-key-bytes",
            rp_id="localhost",
            sign_count=0,
            transports=["internal"],
            name="Laptop",
        )
        session.add(passkey)
        await session.commit()
        passkey_id = passkey.id
        links = await _send(
            session,
            mailed,
            user,
            risky=True,
            undo={"kind": "passkey", "passkey_id": str(passkey_id)},
        )

        response = await client.post(UNDO, json={"token": links[email]})
        session.expire_all()
        if password:
            assert response.status_code == 200, response.text
            assert await session.get(UserPasskey, passkey_id) is None
        else:
            assert response.status_code == 409, response.text
            assert response.json()["detail"] == "ACCOUNT_CHANGE_MOVED_ON"
            assert await session.get(UserPasskey, passkey_id) is not None


async def test_a_waiting_change_is_cancelled_from_an_older_address(
    client: AsyncClient, session: AsyncSession, mailed
):
    """The letter about a waiting primary move cancels it from an address
    older than the one it moves to; that one's copy only signs out. A waiting
    change that names no address can be cancelled from every one."""
    user = await create_user(session, email="holder@example.com")
    user_id = user.id
    newer = await _address(session, user, "moves-to@example.com")
    held = await client.put(
        f"/api/v1/me/emails/{newer.id}/primary",
        json={"current_password": "testpassword123"},
        headers=await signed_in_headers(session, user),
    )
    assert held.status_code == 202, held.text
    mailed.clear()
    await email_outbox._run_pass(session, now=datetime.now(UTC))
    links = dict(mailed)

    response = await client.post(READ, json={"token": links["moves-to@example.com"]})
    assert response.json()["undo"] is None
    response = await client.post(READ, json={"token": links["holder@example.com"]})
    assert response.json() == {
        "notice": "address.primaryHeld",
        "sign_out": True,
        "undo": "hold",
        "subject": "moves-to@example.com",
    }
    response = await client.post(UNDO, json={"token": links["holder@example.com"]})
    assert response.status_code == 200, response.text
    assert await held_changes.pending_for_user(session, user_id=user_id) is None
    due = datetime.now(UTC) + held_changes.HOLD_FOR
    assert await held_changes.apply_due(session, now=due) == 0
    assert await _primary(session, user_id) == "holder@example.com"

    single = await create_user(session, email="only-one@example.com")
    mailed.clear()
    await held_changes.hold(
        session, single, kind=HeldChangeKind.second_factor_off, session_id=None
    )
    await email_outbox._run_pass(session, now=datetime.now(UTC))
    response = await client.post(READ, json={"token": mailed["only-one@example.com"]})
    assert response.json()["undo"] == "hold"


async def test_saying_it_wasnt_them_tells_the_people_running_the_server(
    client: AsyncClient, session: AsyncSession, mailed, security_desk
):
    """A security case about the account, once however many links it
    follows."""
    from sqlmodel import select

    from app.db.request_context import SystemGuild, Unattributed
    from app.db.session import set_rls_context
    from app.models.tenant.intake import IntakeCase

    user = await create_user(session, email="told@example.com")
    first = (await _send(session, mailed, user))["told@example.com"]
    response = await client.post(SIGN_OUT, json={"token": first})
    assert response.status_code == 200, response.text
    assert response.json()["platform_told"] is True
    assert response.json()["contact"] is None

    second = (await _send(session, mailed, user))["told@example.com"]
    assert (await client.post(SIGN_OUT, json={"token": second})).status_code == 200

    await set_rls_context(session, SystemGuild(security_desk.id))
    (case,) = (await session.exec(select(IntakeCase))).all()
    assert case.dedupe_key == f"compromise:{user.id}"
    assert case.occurrences == 2
    await set_rls_context(session, Unattributed())


async def test_with_nobody_to_tell_the_page_names_the_address(
    client: AsyncClient, session: AsyncSession, mailed
):
    from app.api.v1.platform_endpoints import tickets_test

    await tickets_test._set_contacts(session, security="security@example.org")
    user = await create_user(session, email="alone@example.com")
    token = (await _send(session, mailed, user))["alone@example.com"]
    response = await client.post(SIGN_OUT, json={"token": token})
    assert response.status_code == 200, response.text
    assert response.json()["platform_told"] is False
    assert response.json()["contact"] == "security@example.org"
