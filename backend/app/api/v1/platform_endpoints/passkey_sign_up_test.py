"""Registering an account whose way in is a key.

An existing account could give its password up once it held a passkey, but a
new one still had to be made with a password — so a deployment that had
withdrawn passwords could take a registration only through an identity
provider. These cover the door that closes that: the gates asked before the
browser is sent to an authenticator, the account that comes out holding no
password, and the recovery set that is its way back to one.
"""

from __future__ import annotations

import secrets

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.login_methods import LoginMethod
from app.core.security import decode_session_token, has_usable_password
from app.models.platform.user import User
from app.models.platform.user_passkey import UserPasskey
from app.services.auth.oidc.flow_state import s256
from app.services.platform import auth_posture
from app.testing import create_user, registration_for, stub_registration

BEGIN = "/api/v1/auth/register/passkey/begin"
FINISH = "/api/v1/auth/register/passkey/finish"

DETAILS = {
    "email": "keys-only@example.com",
    "username": "keysonly",
}


@pytest.fixture
def ceremony(monkeypatch):
    stub_registration(monkeypatch)


async def _begin(client: AsyncClient, **overrides) -> str:
    response = await client.post(BEGIN, json={**DETAILS, **overrides})
    assert response.status_code == 200, response.text
    return response.json()["options"]["challenge"]


async def test_an_account_is_made_with_a_key_instead_of_a_password(
    client: AsyncClient, session: AsyncSession, ceremony
):
    """The whole door: the ceremony makes the credential, the credential makes
    the account, and the account is signed in holding no password."""
    challenge = await _begin(client)
    response = await client.post(
        FINISH, json={**DETAILS, "credential": registration_for(challenge)}
    )
    assert response.status_code == 201, response.text
    body = response.json()

    # Signed in on the spot, carrying what the ceremony proved — the ceremony
    # verified the person as well as the device, so a sign-in right after it
    # would say nothing new.
    claims = decode_session_token(body["access_token"])
    assert sorted(claims["amr"]) == ["mfa", "swk"]

    account = (
        await session.exec(select(User).where(User.username == "keysonly"))
    ).one()
    assert not has_usable_password(account.hashed_password)
    assert account.password_set_at is None
    held = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == account.id))
    ).all()
    assert len(held) == 1

    # And a way back to a password, since there is no reset to send.
    assert len(body["codes"]) > 0
    # A browser keeps its refresh token in a cookie it never reads.
    assert body["refresh_token"] is None


async def test_the_app_finishes_the_account_it_began(client: AsyncClient, ceremony):
    """The app begins with its S256 challenge, so only the verifier behind it
    finishes the registration, wherever the prompt ran. The app keeps its own
    refresh token, so the account stays signed in across a restart."""
    verifier = secrets.token_urlsafe(48)
    challenge = await _begin(client, code_challenge=s256(verifier))
    credential = registration_for(challenge)
    app = {"Origin": "https://studio.beyonders.initiative"}

    refused = await client.post(
        FINISH, json={**DETAILS, "credential": credential}, headers=app
    )
    assert refused.status_code == 400, refused.text

    response = await client.post(
        FINISH,
        json={**DETAILS, "credential": credential, "code_verifier": verifier},
        headers=app,
    )
    assert response.status_code == 201, response.text
    assert response.json()["refresh_token"]


async def test_the_address_is_checked_before_the_browser_is_sent_anywhere(
    client: AsyncClient, session: AsyncSession, ceremony
):
    """A refusal that arrives after the ceremony has already cost an
    authenticator a resident credential is the thing this order avoids."""
    await create_user(session, email=DETAILS["email"])
    await session.commit()

    refused = await client.post(BEGIN, json=DETAILS)
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "EMAIL_ALREADY_REGISTERED"


async def test_a_challenge_nobody_issued_makes_no_account(
    client: AsyncClient, session: AsyncSession, ceremony
):
    credential = registration_for("never-issued")
    refused = await client.post(FINISH, json={**DETAILS, "credential": credential})
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"
    assert (
        await session.exec(select(User).where(User.username == "keysonly"))
    ).all() == []


async def test_one_challenge_makes_one_account(
    client: AsyncClient, session: AsyncSession, ceremony
):
    """The challenge is spent by the registration it bought, so the same
    answer does not make a second account."""
    challenge = await _begin(client)
    credential = registration_for(challenge)
    first = await client.post(FINISH, json={**DETAILS, "credential": credential})
    assert first.status_code == 201, first.text

    again = await client.post(
        FINISH,
        json={
            **DETAILS,
            "email": "second@example.com",
            "username": "second",
            "credential": credential,
        },
    )
    assert again.status_code == 400, again.text
    assert (
        await session.exec(select(User).where(User.username == "second"))
    ).all() == []


async def test_the_key_it_registered_with_signs_it_in(
    client: AsyncClient, session: AsyncSession, ceremony, monkeypatch
):
    """The credential the account was made with is the account's, so the
    ordinary passkey sign-in finds it."""
    from app.testing import assertion_for, stub_assertion

    challenge = await _begin(client)
    made = await client.post(
        FINISH, json={**DETAILS, "credential": registration_for(challenge)}
    )
    assert made.status_code == 201, made.text

    stub_assertion(monkeypatch, backed_up=True)
    begun = await client.post("/api/v1/auth/passkeys/authenticate/begin", json={})
    assert begun.status_code == 200, begun.text
    signed_in = await client.post(
        "/api/v1/auth/passkeys/authenticate/finish",
        json={"credential": assertion_for(begun.json()["options"]["challenge"])},
    )
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["access_token"]


async def test_a_deployment_that_does_not_permit_passkeys_has_no_such_door(
    client: AsyncClient, session: AsyncSession, acting_user, ceremony
):
    owner = await acting_user("owner")
    await auth_posture.change(
        auth_posture.RuleContext.platform(session, owner.user),
        {"login_methods": frozenset([LoginMethod.password])},
    )

    refused = await client.post(BEGIN, json=DETAILS)
    assert refused.status_code == 403, refused.text
