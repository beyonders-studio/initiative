"""Sample accounts: kept and put back by the demo plug-in, listed on the
sign-in page, signed in to by anyone, and held to their own sign-in."""

import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.messages import DemoMessages, GuildMessages
from app.demo import accounts, samples
from app.demo.copies_test import ADMIN, _api, _sales_install, demo  # noqa: F401
from app.models.platform.demo import DemoSample
from app.models.platform.sign_in_lock import SignInLock
from app.models.platform.user import User
from app.services import email as email_service
from app.testing import create_user, get_auth_headers
from app.testing.plugin_clients import install_headers

BAKERY = {
    "handle": "rosie#0001",
    "display_name": "Rosie Baker",
    "email": "bakery@example.com",
    "password": "password",
    "about": "Owns Rosie's Bakery",
}
LISTED = {
    "display_name": "Rosie Baker",
    "email": "bakery@example.com",
    "password": "password",
    "about": "Owns Rosie's Bakery",
}


@pytest.fixture
async def ops(demo, client, session, acting_user, role_session):  # noqa: F811
    """The demo plug-in's install in the operations community: its community
    and its headers."""
    installed = await _sales_install(session, acting_user, role_session)
    return installed.guild.id, install_headers(installed, [ADMIN])


async def _keep(client, ops, *sample: dict):
    community, headers = ops
    return await client.post(
        _api(community, "samples"), json={"samples": list(sample)}, headers=headers
    )


async def _sign_in(client, email: str = "bakery@example.com", password="password"):
    return await client.post(
        "/api/v1/auth/token", data={"username": email, "password": password}
    )


async def _as_sample(client, ops) -> dict[str, str]:
    kept = await _keep(client, ops, BAKERY)
    assert kept.status_code == 200, kept.text
    signed_in = await _sign_in(client)
    assert signed_in.status_code == 200, signed_in.text
    return {"Authorization": f"Bearer {signed_in.json()['access_token']}"}


async def test_a_sample_is_kept_listed_and_signed_in_to(client, ops, session):
    kept = await _keep(client, ops, BAKERY)
    assert kept.status_code == 200, kept.text
    assert kept.json() == {"handles": ["rosie#0001"]}

    listed = await client.get("/api/v1/demo/samples")
    assert listed.status_code == 200, listed.text
    assert listed.json() == [LISTED]

    signed_in = await _sign_in(client)
    assert signed_in.status_code == 200, signed_in.text

    again = await _keep(client, ops, BAKERY)
    assert again.status_code == 200, again.text
    rosie = await accounts.by_handle(session, "rosie#0001")
    assert rosie is not None
    assert len((await session.exec(select(DemoSample))).all()) == 1


async def test_nothing_is_listed_outside_the_demo(client, ops, monkeypatch):
    assert (await _keep(client, ops, BAKERY)).status_code == 200
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    assert (await client.get("/api/v1/demo/samples")).status_code == 404


async def test_a_sample_cannot_change_how_it_is_signed_in_to(client, ops, session):
    headers = await _as_sample(client, ops)

    refused = [
        await client.patch(
            "/api/v1/me",
            json={"password": "another-password", "current_password": "password"},
            headers=headers,
        ),
        await client.post(
            "/api/v1/me/api-keys", json={"name": "mine"}, headers=headers
        ),
        await client.get("/api/v1/auth/sessions", headers=headers),
        await client.post("/api/v1/auth/totp/enroll", json={}, headers=headers),
    ]
    for response in refused:
        assert response.status_code == 403, response.text
        assert response.json()["detail"] == DemoMessages.DEMO_SAMPLE_ACCOUNT

    created = await client.post(
        "/api/v1/communities/", json={"name": "Mine"}, headers=headers
    )
    assert created.status_code == 403
    assert created.json()["detail"] == GuildMessages.COMMUNITY_CREATION_DEMO_ACCOUNT

    me = await client.get("/api/v1/me", headers=headers)
    assert me.json()["demo_sample"] is True
    assert me.json()["can_create_communities"] is False

    # Its profile is its own to change, as any member's is.
    status = await client.patch(
        "/api/v1/me",
        json={"custom_status": {"text": "Out of flour"}},
        headers=headers,
    )
    assert status.status_code == 200, status.text

    # And nobody else is held to any of it.
    someone = await create_user(session, email="someone@example.com")
    theirs = await client.get(
        "/api/v1/auth/sessions", headers=get_auth_headers(someone)
    )
    assert theirs.status_code == 200, theirs.text


async def test_keeping_a_sample_again_puts_it_back(client, ops, session):
    headers = await _as_sample(client, ops)
    rosie = await accounts.by_handle(session, "rosie#0001")
    assert rosie is not None
    rosie_id, version = rosie.id, rosie.token_version
    rosie.custom_status = {"text": "Gone fishing"}
    session.add(rosie)
    await session.commit()

    assert (await _keep(client, ops, BAKERY)).status_code == 200

    session.expire_all()
    rosie = await session.get(User, rosie_id)
    assert rosie is not None
    assert rosie.custom_status == {}
    assert rosie.token_version > version
    # The session it had is over.
    assert (await client.get("/api/v1/me", headers=headers)).status_code == 401
    assert (await _sign_in(client)).status_code == 200


async def test_wrong_passwords_never_lock_a_sample(client, ops, session):
    assert (await _keep(client, ops, BAKERY)).status_code == 200
    for _ in range(8):
        wrong = await _sign_in(client, password="not-the-password")
        assert wrong.status_code == 400, wrong.text
    rosie = await accounts.by_handle(session, "rosie#0001")
    assert rosie is not None
    locks = await session.exec(select(SignInLock).where(SignInLock.user_id == rosie.id))
    assert locks.first() is None
    assert (await _sign_in(client)).status_code == 200


async def test_a_sample_not_named_again_is_a_persona_again(client, ops, session):
    assert (await _keep(client, ops, BAKERY)).status_code == 200
    rosie = await accounts.by_handle(session, "rosie#0001")
    assert rosie is not None
    rosie_id = rosie.id

    emptied = await _keep(client, ops)
    assert emptied.status_code == 200, emptied.text

    assert (await client.get("/api/v1/demo/samples")).json() == []
    assert (await _sign_in(client)).status_code == 400
    session.expire_all()
    persona = (
        await session.exec(
            select(User.id).where(User.id == rosie_id, accounts.unloginable())
        )
    ).first()
    assert persona == rosie_id


async def test_a_sample_is_never_made_over_an_account(client, ops, session):
    await create_user(session, username="sam", discriminator=7)
    taken = await _keep(client, ops, {**BAKERY, "handle": "sam#0007"})
    assert taken.status_code == 409
    assert taken.json()["detail"] == DemoMessages.DEMO_PERSONA_TAKEN

    await create_user(session, email="bakery@example.com")
    held = await _keep(client, ops, BAKERY)
    assert held.status_code == 409
    assert held.json()["detail"] == DemoMessages.DEMO_SAMPLE_ADDRESS_TAKEN
    assert await accounts.by_handle(session, "rosie#0001") is None
    assert (await client.get("/api/v1/demo/samples")).json() == []


async def test_two_samples_may_not_share_an_address(client, ops):
    twice = await _keep(
        client, ops, BAKERY, {**BAKERY, "handle": "rosie#0002", "display_name": "R"}
    )
    assert twice.status_code == 422


async def test_no_mail_is_sent_to_a_sample(client, ops, session, monkeypatch):
    assert (await _keep(client, ops, BAKERY)).status_code == 200
    sent: list[object] = []
    monkeypatch.setattr(email_service, "_deliver", lambda *args: sent.append(args))
    # Returns before it would need a mail server at all.
    await email_service.send_email(
        session,
        recipients=["Bakery@Example.com"],
        subject="Hello",
        html_body="<p>Hello</p>",
    )
    assert sent == []
    assert await samples.addresses_of(["someone@example.com"]) == set()
