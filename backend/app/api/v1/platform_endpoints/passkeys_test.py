"""Registering, naming and removing a passkey — and signing in with one.

The ceremony arithmetic belongs to the library and is stood in for here: what
these cover is the surface around it — the password re-check, the challenge
that stands for exactly one ceremony, whose account a credential lands on, what
the account is told afterwards, and what a session opened by an assertion
records about how it was opened.
"""

import secrets
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from webauthn.helpers import bytes_to_base64url

from app.core.login_methods import LoginMethod
from app.core.audit_events import AuditEventType
from app.core.security import (
    REFRESH_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    get_password_hash,
)
from app.models.platform.auth_challenge import AuthChallenge
from app.models.platform.auth_session import AuthSession
from app.models.platform.user import User, UserStatus
from app.models.platform.user_passkey import UserPasskey
from app.core.email_i18n import email_t
from app.services.platform import email_outbox
from app.services.auth import passkeys as passkey_service
from app.testing import (
    assertion_for,
    create_passkey,
    create_user,
    emitted,
    get_auth_headers,
    get_auth_token,
    registration_for,
    signed_in_headers,
    stub_assertion,
    stub_registration,
)


PASSWORD = "correct-horse-battery-staple"

BEGIN = "/api/v1/auth/passkeys/register/begin"
FINISH = "/api/v1/auth/passkeys/register/finish"


@pytest.fixture
def ceremony(monkeypatch):
    stub_registration(monkeypatch)


async def _account(session: AsyncSession, email: str) -> User:
    return await create_user(
        session,
        email=email,
        hashed_password=get_password_hash(PASSWORD),
        status=UserStatus.active,
        email_verified=True,
    )


async def _begin(client: AsyncClient, user: User, *, name: str = "Laptop") -> str:
    """Begin a registration and hand back the challenge the options carry."""
    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": name},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    return response.json()["options"]["challenge"]


async def _register(
    client: AsyncClient,
    user: User,
    *,
    name: str = "Laptop",
    credential_id: str = "credential-one",
) -> dict:
    challenge = await _begin(client, user, name=name)
    response = await client.post(
        FINISH,
        json={
            "credential": registration_for(challenge, credential_id=credential_id),
            "name": name,
        },
        headers=get_auth_headers(user),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _seed(session: AsyncSession, user: User, count: int) -> None:
    for index in range(count):
        await passkey_service.store(
            session,
            user_id=user.id,
            registered=passkey_service.RegisteredCredential(
                credential_id=f"seeded-{user.id}-{index}".encode(),
                public_key=b"public-key-bytes",
                sign_count=0,
                aaguid=None,
                user_verified=True,
                backed_up=False,
                transports=["internal"],
            ),
            name=f"Key {index}",
        )
    await session.commit()


# ---------------------------------------------------------------------------
# What the account holds
# ---------------------------------------------------------------------------


async def test_an_account_with_none_is_told_what_it_would_take(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-empty@example.com")
    response = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passkeys"] == []
    assert body["password_required"] is True
    assert body["limit"] == passkey_service.MAX_PASSKEYS_PER_USER
    assert body["site_supported"] is True


async def test_the_list_says_when_this_address_cannot_carry_one(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """The deployment's own address decides this, so the server answers it
    rather than leaving the browser to."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "http://intranet.local")
    user = await _account(session, "pk-unsupported@example.com")

    response = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    assert response.json()["site_supported"] is False


async def test_an_account_with_no_password_is_not_asked_for_one(
    client: AsyncClient, session: AsyncSession
):
    """Provisioned through an identity provider: there is no password to
    re-check, so the form does not ask for one."""
    user = await create_user(
        session,
        email="pk-nopassword@example.com",
        hashed_password=None,
        status=UserStatus.active,
    )
    response = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    assert response.json()["password_required"] is False


async def test_the_list_reads_oldest_first(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-order@example.com")
    await _register(client, user, name="First", credential_id="credential-one")
    await _register(client, user, name="Second", credential_id="credential-two")

    response = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert response.status_code == 200, response.text
    assert [row["name"] for row in response.json()["passkeys"]] == ["First", "Second"]


# ---------------------------------------------------------------------------
# Beginning
# ---------------------------------------------------------------------------


async def test_beginning_asks_for_the_password(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-nopw@example.com")
    response = await client.post(
        BEGIN, json={"name": "Laptop"}, headers=get_auth_headers(user)
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_REQUIRED"


async def test_beginning_refuses_the_wrong_password(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-wrongpw@example.com")
    response = await client.post(
        BEGIN,
        json={"current_password": "not-it", "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_INCORRECT"


async def test_a_name_this_deployment_will_not_keep_is_refused_here(
    client: AsyncClient, session: AsyncSession
):
    """The same name rule the finish route holds, applied before a ceremony is
    begun — so nothing is issued for a name that will not be stored."""
    user = await _account(session, "pk-sigil@example.com")
    user_id = user.id

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop #1"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 422, response.text
    assert "RESERVED_SIGIL_IN_NAME" in response.text

    session.expire_all()
    challenges = (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.user_id == user_id)
        )
    ).all()
    assert challenges == []


async def test_a_plain_name_begins_a_ceremony(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-plainname@example.com")
    user_id = user.id

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text

    session.expire_all()
    challenges = (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.user_id == user_id)
        )
    ).all()
    assert len(challenges) == 1


async def test_the_options_name_this_deployment(
    client: AsyncClient, session: AsyncSession
):
    from app.core.config import settings

    user = await _account(session, "pk-options@example.com")
    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    options = response.json()["options"]
    assert options["rp"]["id"] == urlsplit(settings.APP_URL).hostname
    assert options["challenge"]


async def test_a_deployment_on_plain_http_cannot_begin_one_or_sign_in(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """A credential is bound to a named host reached over https, so a
    deployment addressed otherwise says so instead of sending options the
    browser will not answer — for a sign-in as for a registration."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "http://intranet.local")
    user = await _account(session, "pk-http@example.com")

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_SITE_UNSUPPORTED"

    signed_in = await client.post(SIGN_IN_BEGIN, json={})
    assert signed_in.status_code == 400
    assert signed_in.json()["detail"] == "PASSKEY_SITE_UNSUPPORTED"


async def test_an_account_at_the_limit_cannot_begin_another(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-limit@example.com")
    await _seed(session, user, passkey_service.MAX_PASSKEYS_PER_USER)

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PASSKEY_LIMIT_REACHED"


# ---------------------------------------------------------------------------
# Finishing
# ---------------------------------------------------------------------------


async def test_a_challenge_nobody_issued_is_refused(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-unknown@example.com")
    response = await client.post(
        FINISH,
        json={"credential": registration_for("never-issued"), "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"


async def test_finishing_keeps_the_credential(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-keep@example.com")
    user_id = user.id
    body = await _register(client, user, name="Work laptop")

    assert body["name"] == "Work laptop"
    assert body["backed_up"] is True
    assert body["user_verified"] is True
    assert body["transports"] == ["internal", "hybrid"]

    session.expire_all()
    rows = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == user_id))
    ).all()
    assert len(rows) == 1
    assert rows[0].rp_id == passkey_service.relying_party_id()
    assert rows[0].name == "Work laptop"


async def test_only_the_transports_webauthn_names_are_kept(
    client: AsyncClient, session: AsyncSession, ceremony
):
    """The list arrives from the client and is handed back to a browser later,
    so what is kept is what the specification names."""
    user = await _account(session, "pk-transports@example.com")
    challenge = await _begin(client, user)
    credential = registration_for(challenge)
    credential["response"]["transports"] = ["usb", "nonsense", 123, "<b>x</b>"]

    response = await client.post(
        FINISH,
        json={"credential": credential, "name": "Key"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 201, response.text
    assert response.json()["transports"] == ["usb"]


async def test_registering_is_recorded(
    client: AsyncClient, session: AsyncSession, ceremony, capfd
):
    user = await _account(session, "pk-audit@example.com")
    user_id = user.id
    capfd.readouterr()
    body = await _register(client, user)

    events = [
        row
        for row in emitted(capfd, AuditEventType.AUTH_PASSKEY_REGISTERED)
        if row["actor_user_id"] == user_id
    ]
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["passkey_id"] == body["id"]
    assert detail["backed_up"] is True
    assert detail["user_verified"] is True
    # The credential and its key are never in the record.
    assert "credential_id" not in detail
    assert "public_key" not in detail


async def test_a_challenge_answers_one_registration(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-once@example.com")
    user_id = user.id
    challenge = await _begin(client, user)
    credential = registration_for(challenge)

    first = await client.post(
        FINISH,
        json={"credential": credential, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert first.status_code == 201, first.text

    again = await client.post(
        FINISH,
        json={"credential": credential, "name": "Laptop again"},
        headers=get_auth_headers(user),
    )
    assert again.status_code == 400
    assert again.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"

    session.expire_all()
    rows = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == user_id))
    ).all()
    assert len(rows) == 1


async def test_a_challenge_belongs_to_the_account_that_began_it(
    client: AsyncClient, session: AsyncSession, ceremony
):
    """A credential lands on the account whose ceremony it answers, and on no
    other."""
    one = await _account(session, "pk-mine@example.com")
    two = await _account(session, "pk-theirs@example.com")
    challenge = await _begin(client, one)

    response = await client.post(
        FINISH,
        json={"credential": registration_for(challenge), "name": "Laptop"},
        headers=get_auth_headers(two),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"

    session.expire_all()
    rows = (await session.exec(select(UserPasskey))).all()
    assert rows == []


async def test_a_ceremony_that_does_not_verify_is_refused(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    def refuse(**kwargs):
        raise ValueError("the ceremony did not verify")

    monkeypatch.setattr(
        passkey_service.webauthn, "verify_registration_response", refuse
    )
    user = await _account(session, "pk-unverified@example.com")
    challenge = await _begin(client, user)

    response = await client.post(
        FINISH,
        json={"credential": registration_for(challenge), "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"


# ---------------------------------------------------------------------------
# Naming and removing
# ---------------------------------------------------------------------------


async def test_renaming_changes_only_the_name(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-rename@example.com")
    body = await _register(client, user, name="Laptop")

    response = await client.patch(
        f"/api/v1/auth/passkeys/{body['id']}",
        json={"name": "Desk key"},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Desk key"
    assert response.json()["id"] == body["id"]


async def test_another_accounts_passkey_cannot_be_renamed(
    client: AsyncClient, session: AsyncSession, ceremony
):
    owner = await _account(session, "pk-owner@example.com")
    other = await _account(session, "pk-other@example.com")
    body = await _register(client, owner, name="Laptop")

    response = await client.patch(
        f"/api/v1/auth/passkeys/{body['id']}",
        json={"name": "Mine now"},
        headers=get_auth_headers(other),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "PASSKEY_NOT_FOUND"


async def test_a_standing_credential_cannot_rename_one(
    client: AsyncClient, session: AsyncSession, ceremony
):
    from app.services.platform import api_keys as api_keys_service

    user = await _account(session, "pk-renamekey@example.com")
    body = await _register(client, user, name="Laptop")
    secret, _row = await api_keys_service.create_api_key(
        session, user=user, name="script"
    )
    await session.commit()

    response = await client.patch(
        f"/api/v1/auth/passkeys/{body['id']}",
        json={"name": "Renamed"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"


async def test_removing_asks_for_the_password(
    client: AsyncClient, session: AsyncSession, ceremony
):
    user = await _account(session, "pk-removepw@example.com")
    body = await _register(client, user)

    response = await client.post(
        f"/api/v1/auth/passkeys/{body['id']}/remove",
        json={},
        headers=get_auth_headers(user),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "USER_CURRENT_PASSWORD_REQUIRED"


async def test_removing_forgets_the_credential(
    client: AsyncClient, session: AsyncSession, ceremony, capfd
):
    user = await _account(session, "pk-remove@example.com")
    user_id = user.id
    body = await _register(client, user)
    capfd.readouterr()

    response = await client.post(
        f"/api/v1/auth/passkeys/{body['id']}/remove",
        json={"current_password": PASSWORD},
        headers=await signed_in_headers(session, user, amr=["hwk"]),
    )
    assert response.status_code == 200, response.text

    session.expire_all()
    rows = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == user_id))
    ).all()
    assert rows == []
    events = [
        row
        for row in emitted(capfd, AuditEventType.AUTH_PASSKEY_REMOVED)
        if row["actor_user_id"] == user_id
    ]
    assert len(events) == 1
    assert events[0]["detail"]["passkey_id"] == body["id"]


async def test_another_accounts_passkey_cannot_be_removed(
    client: AsyncClient, session: AsyncSession, ceremony
):
    owner = await _account(session, "pk-keepmine@example.com")
    other = await _account(session, "pk-taker@example.com")
    body = await _register(client, owner)

    response = await client.post(
        f"/api/v1/auth/passkeys/{body['id']}/remove",
        json={"current_password": PASSWORD},
        headers=get_auth_headers(other),
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "PASSKEY_NOT_FOUND"


# ---------------------------------------------------------------------------
# What the account is told, and who may ask
# ---------------------------------------------------------------------------


async def test_the_account_is_told_about_both_changes(
    client: AsyncClient, session: AsyncSession, ceremony, monkeypatch
):
    sent: list[dict] = []

    async def record(user, pieces, **_) -> None:
        sent.append(
            {"user_id": user.id, "subject": pieces.subject, "body": pieces.body}
        )

    monkeypatch.setattr(email_outbox, "enqueue_account_letter", record)

    user = await _account(session, "pk-letter@example.com")
    body = await _register(client, user, name="Phone")
    [added] = sent
    assert added["user_id"] == user.id
    assert added["subject"] == email_t("passkey.added.subject", "en", escape=False)
    assert "Phone" in added["body"]

    response = await client.post(
        f"/api/v1/auth/passkeys/{body['id']}/remove",
        json={"current_password": PASSWORD},
        headers=await signed_in_headers(session, user, amr=["hwk"]),
    )
    assert response.status_code == 200, response.text
    assert sent[-1]["subject"] == email_t("passkey.removed.subject", "en", escape=False)
    assert "Phone" in sent[-1]["body"]


async def test_a_letter_that_cannot_go_does_not_undo_the_change(
    client: AsyncClient, session: AsyncSession, ceremony, monkeypatch
):
    """A deployment with no mail configured still registered the credential."""

    async def fail(*args, **kwargs) -> None:
        raise RuntimeError("no mail")

    monkeypatch.setattr(email_outbox, "enqueue_account_letter", fail)

    user = await _account(session, "pk-nomail@example.com")
    user_id = user.id
    body = await _register(client, user)

    session.expire_all()
    rows = (
        await session.exec(select(UserPasskey).where(UserPasskey.user_id == user_id))
    ).all()
    assert len(rows) == 1
    assert str(rows[0].id) == body["id"]


async def test_a_standing_credential_cannot_register_one(
    client: AsyncClient, session: AsyncSession
):
    """Adding a way in is done while the person is here, not through a
    credential running without them."""
    from app.services.platform import api_keys as api_keys_service

    user = await _account(session, "pk-apikey@example.com")
    secret, _row = await api_keys_service.create_api_key(
        session, user=user, name="script"
    )
    await session.commit()

    response = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"


# ---------------------------------------------------------------------------
# Signing in with one
# ---------------------------------------------------------------------------

SIGN_IN_BEGIN = "/api/v1/auth/passkeys/authenticate/begin"
SIGN_IN_FINISH = "/api/v1/auth/passkeys/authenticate/finish"


@pytest.fixture
def assertion(monkeypatch):
    stub_assertion(monkeypatch)


async def _begin_sign_in(client: AsyncClient, **payload) -> str:
    response = await client.post(SIGN_IN_BEGIN, json=payload)
    assert response.status_code == 200, response.text
    return response.json()["options"]["challenge"]


async def _withdraw_passkeys(session: AsyncSession) -> None:
    """Leave the deployment permitting the other three."""
    from app.services.platform import rules

    await rules.put(
        session,
        "login_methods",
        frozenset({LoginMethod.password, LoginMethod.sso, LoginMethod.totp}),
    )
    await session.commit()


async def test_beginning_names_the_deployment_and_nobody_else(
    client: AsyncClient, session: AsyncSession
):
    """No allow-list is what lets somebody sign in without typing who they are,
    and the challenge it stores belongs to no account."""
    from app.core.config import settings

    response = await client.post(SIGN_IN_BEGIN, json={})
    assert response.status_code == 200, response.text
    options = response.json()["options"]
    assert options["rpId"] == urlsplit(settings.APP_URL).hostname
    assert not options.get("allowCredentials")

    session.expire_all()
    rows = (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.purpose == "passkey_sign_in")
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].user_id is None


async def test_an_assertion_opens_a_session(
    client: AsyncClient, session: AsyncSession, assertion, capfd
):
    """A device-bound key records ``hwk``, and ``mfa`` beside it because the
    ceremony proved the person as well as the device."""
    user = await _account(session, "pk-signin@example.com")
    user_id = user.id
    await create_passkey(session, user)
    capfd.readouterr()

    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH, json={"credential": assertion_for(challenge)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["redirect_to"] is None

    session.expire_all()
    sessions = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).all()
    assert len(sessions) == 1
    assert sessions[0].amr == ["hwk", "mfa"]

    events = [
        row
        for row in emitted(capfd, AuditEventType.AUTH_SIGNED_IN)
        if row["actor_user_id"] == user_id
    ]
    assert len(events) == 1
    assert events[0]["detail"]["method"] == "passkey"


async def test_a_synced_key_says_so(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """One a password manager syncs between devices records ``swk``."""
    stub_assertion(monkeypatch, backed_up=True)
    user = await _account(session, "pk-synced@example.com")
    user_id = user.id
    await create_passkey(session, user, backed_up=True)

    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH, json={"credential": assertion_for(challenge)}
    )
    assert response.status_code == 200, response.text

    session.expire_all()
    opened = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).one()
    assert opened.amr == ["swk", "mfa"]


async def test_the_credential_records_that_it_answered(
    client: AsyncClient, session: AsyncSession, assertion
):
    """The counter and the last-used stamp land in the same commit as the
    session."""
    user = await _account(session, "pk-counter-signin@example.com")
    row = await create_passkey(session, user)
    row_id = row.id

    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH, json={"credential": assertion_for(challenge)}
    )
    assert response.status_code == 200, response.text

    session.expire_all()
    stored = await session.get(UserPasskey, row_id)
    assert stored.sign_count == 1
    assert stored.last_used_at is not None


async def test_a_challenge_answers_one_sign_in(
    client: AsyncClient, session: AsyncSession, assertion
):
    user = await _account(session, "pk-once-signin@example.com")
    user_id = user.id
    await create_passkey(session, user)

    challenge = await _begin_sign_in(client)
    credential = assertion_for(challenge)

    first = await client.post(SIGN_IN_FINISH, json={"credential": credential})
    assert first.status_code == 200, first.text

    again = await client.post(SIGN_IN_FINISH, json={"credential": credential})
    assert again.status_code == 400
    assert again.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"

    session.expire_all()
    sessions = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).all()
    assert len(sessions) == 1


async def test_a_credential_nobody_registered_is_refused(
    client: AsyncClient, session: AsyncSession, assertion, capfd
):
    user = await _account(session, "pk-stranger@example.com")
    await create_passkey(session, user)
    capfd.readouterr()

    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH,
        json={"credential": assertion_for(challenge, credential_id="never-registered")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"

    events = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert len(events) == 1
    detail = events[0]["detail"]
    assert detail["method"] == "passkey"
    assert detail["reason"] == "unknown"
    # Nobody resolved, so the record names nobody.
    assert events[0]["target_user_id"] is None


async def test_a_credential_that_does_not_verify_names_its_account(
    client: AsyncClient, session: AsyncSession, monkeypatch, capfd
):
    """The client is told the same thing either way; the record is not. A
    credential this deployment holds names the account it belongs to."""
    user = await _account(session, "pk-unverified@example.com")
    user_id = user.id
    await create_passkey(session, user)

    def refuse(**kwargs):
        raise ValueError("signature")

    monkeypatch.setattr(
        passkey_service.webauthn, "verify_authentication_response", refuse
    )
    capfd.readouterr()

    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH, json={"credential": assertion_for(challenge)}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"

    events = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert len(events) == 1
    assert events[0]["target_user_id"] == user_id
    assert events[0]["detail"]["reason"] == "invalid"


async def test_a_credential_from_another_domain_is_recorded_and_left_there(
    client: AsyncClient, session: AsyncSession, assertion, capfd
):
    """A deployment that has moved domain refuses every credential made under
    the old one. The refusal is written down against the account the credential
    belongs to: what the record says is about the move, not about the
    account."""
    user = await _account(session, "pk-moved-domain@example.com")
    user_id = user.id
    row = await create_passkey(session, user)
    row.rp_id = "before.example.org"
    session.add(row)
    await session.commit()
    capfd.readouterr()

    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH, json={"credential": assertion_for(challenge)}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"

    events = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert len(events) == 1
    assert events[0]["target_user_id"] == user_id
    assert events[0]["detail"]["reason"] == "wrong_rp"


async def test_an_inactive_account_is_refused(
    client: AsyncClient, session: AsyncSession, assertion, capfd
):
    """No session, nothing kept from the assertion, and the refusal written
    down against the account the credential named."""
    user = await _account(session, "pk-gone@example.com")
    user_id = user.id
    row = await create_passkey(session, user)
    row_id = row.id

    user.status = UserStatus.deactivated
    session.add(user)
    await session.commit()
    capfd.readouterr()

    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH, json={"credential": assertion_for(challenge)}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INACTIVE_USER"

    session.expire_all()
    sessions = (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).all()
    assert sessions == []

    # The counter the assertion moved went back with the transaction.
    stored = await session.get(UserPasskey, row_id)
    assert stored.sign_count == 0
    assert stored.last_used_at is None

    events = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert len(events) == 1
    assert events[0]["target_user_id"] == user_id
    detail = events[0]["detail"]
    assert detail["method"] == "passkey"
    assert detail["reason"] == "inactive"


async def test_a_registration_challenge_cannot_finish_a_sign_in(
    client: AsyncClient, session: AsyncSession, ceremony, assertion
):
    """Each ceremony answers for its own purpose and no other."""
    user = await _account(session, "pk-crossed@example.com")
    await create_passkey(session, user)

    registration_challenge = await _begin(client, user)
    refused = await client.post(
        SIGN_IN_FINISH, json={"credential": assertion_for(registration_challenge)}
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"


async def test_a_sign_in_challenge_cannot_finish_a_registration(
    client: AsyncClient, session: AsyncSession, ceremony, assertion
):
    user = await _account(session, "pk-crossed-back@example.com")

    sign_in_challenge = await _begin_sign_in(client)
    refused = await client.post(
        FINISH,
        json={
            "credential": registration_for(
                sign_in_challenge, credential_id="credential-two"
            ),
            "name": "Laptop",
        },
        headers=get_auth_headers(user),
    )
    assert refused.status_code == 400
    assert refused.json()["detail"] == "PASSKEY_REGISTRATION_INVALID"


async def test_a_phone_is_handed_a_code(
    client: AsyncClient, session: AsyncSession, assertion, capfd
):
    """The relay page in the system browser opens no session of its own: it is
    given the address the app is waiting at, carrying a code bound to the app's
    challenge. The app's verifier opens the session this sign-in earned."""
    from app.core.security import decode_session_token
    from app.services.auth.oidc.flow_state import s256

    user = await _account(session, "pk-mobile@example.com")
    user_id = user.id
    await create_passkey(session, user)
    capfd.readouterr()

    verifier = secrets.token_urlsafe(48)
    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH,
        json={
            "credential": assertion_for(challenge),
            "mobile": True,
            "device_name": "Pixel 9",
            "code_challenge": s256(verifier),
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"] is None
    redirect = body["redirect_to"]
    assert redirect.startswith("initiative://oidc/callback?")
    assert SESSION_COOKIE_NAME not in response.cookies
    assert REFRESH_COOKIE_NAME not in response.cookies
    session.expire_all()
    assert (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).all() == []

    # So the session the app opens is the one this sign-in earned: a community
    # asking for a passkey is answered by the phone that just presented one.
    redeemed = await client.post(
        "/api/v1/auth/native/token",
        json={
            "code": parse_qs(urlsplit(redirect).query)["code"][0],
            "code_verifier": verifier,
        },
    )
    assert redeemed.status_code == 200, redeemed.text
    assert redeemed.json()["refresh_token"]
    opened = decode_session_token(redeemed.json()["access_token"])
    assert sorted(opened["amr"]) == ["hwk", "mfa"]

    events = [
        row
        for row in emitted(capfd, AuditEventType.AUTH_SIGNED_IN)
        if row["actor_user_id"] == user_id
    ]
    assert [event["detail"] for event in events] == [
        {"method": "passkey", "native": True}
    ]


async def test_an_older_app_is_asked_to_update(
    client: AsyncClient, session: AsyncSession, assertion
):
    """An app bundle from before the code flow sends no challenge, and can only
    be handed a session through the code, so it is asked to update and nothing
    is opened."""
    user = await _account(session, "pk-unnamed@example.com")
    user_id = user.id
    await create_passkey(session, user)

    challenge = await _begin_sign_in(client)
    response = await client.post(
        SIGN_IN_FINISH,
        json={
            "credential": assertion_for(challenge),
            "mobile": True,
            "device_name": "  ",
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "NATIVE_APP_UPDATE_REQUIRED"
    session.expire_all()
    assert (
        await session.exec(select(AuthSession).where(AuthSession.user_id == user_id))
    ).all() == []


# ---------------------------------------------------------------------------
# A deployment that does not offer them
# ---------------------------------------------------------------------------


async def test_a_withdrawn_method_closes_both_sign_in_routes(
    client: AsyncClient, session: AsyncSession, assertion
):
    user = await _account(session, "pk-withdrawn@example.com")
    await create_passkey(session, user)
    challenge = await _begin_sign_in(client)
    await _withdraw_passkeys(session)

    began = await client.post(SIGN_IN_BEGIN, json={})
    assert began.status_code == 403
    assert began.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"

    finished = await client.post(
        SIGN_IN_FINISH, json={"credential": assertion_for(challenge)}
    )
    assert finished.status_code == 403
    assert finished.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"


async def test_a_withdrawn_method_stops_new_registrations(
    client: AsyncClient, session: AsyncSession, ceremony
):
    """The credentials an account already holds are left alone; what stops is
    adding another."""
    user = await _account(session, "pk-noadd@example.com")
    await create_passkey(session, user)
    await _withdraw_passkeys(session)

    began = await client.post(
        BEGIN,
        json={"current_password": PASSWORD, "name": "Laptop"},
        headers=get_auth_headers(user),
    )
    assert began.status_code == 403
    assert began.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"

    listed = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert listed.status_code == 200, listed.text
    assert listed.json()["offered"] is False
    assert len(listed.json()["passkeys"]) == 1


async def test_a_deployment_that_offers_them_says_so(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-offered@example.com")
    listed = await client.get("/api/v1/auth/passkeys", headers=get_auth_headers(user))
    assert listed.status_code == 200, listed.text
    assert listed.json()["offered"] is True


# ---------------------------------------------------------------------------
# Presenting one against the session already open
# ---------------------------------------------------------------------------

STEP_UP_BEGIN = "/api/v1/auth/step-up/passkey/begin"
STEP_UP_FINISH = "/api/v1/auth/step-up/passkey/finish"


async def _open_session(
    session: AsyncSession,
    user: User,
    *,
    amr: list[str] | None = None,
    satisfied_providers: list[int] | None = None,
):
    """A token naming a real session row, which is what a step-up upgrades."""
    from app.services.auth import sessions as session_service

    amr = amr or ["pwd"]
    satisfied_providers = satisfied_providers or []
    issued = await session_service.create_session(
        session,
        user_id=user.id,
        amr=amr,
        satisfied_providers=satisfied_providers,
    )
    await session.commit()
    headers = {
        "Authorization": "Bearer "
        + get_auth_token(
            user,
            session_id=issued.session.id,
            amr=amr,
            satisfied_providers=satisfied_providers,
        )
    }
    return issued.session.id, headers


async def _begin_step_up(client: AsyncClient, headers: dict) -> str:
    response = await client.post(STEP_UP_BEGIN, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["options"]["challenge"]


async def test_stepping_up_offers_only_this_accounts_credentials(
    client: AsyncClient, session: AsyncSession
):
    """There is already an account here, so the browser is asked for one of its
    own credentials rather than for whatever the authenticator holds."""
    user = await _account(session, "pk-stepup-list@example.com")
    user_id = user.id
    await create_passkey(session, user)
    other = await _account(session, "pk-stepup-other@example.com")
    await create_passkey(session, other, credential_id="credential-two")
    _id, headers = await _open_session(session, user)

    response = await client.post(STEP_UP_BEGIN, headers=headers)
    assert response.status_code == 200, response.text
    offered = response.json()["options"]["allowCredentials"]
    assert [entry["id"] for entry in offered] == [bytes_to_base64url(b"credential-one")]

    session.expire_all()
    rows = (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.purpose == "passkey_step_up")
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].user_id == user_id


async def test_an_account_with_no_passkey_is_told_so(
    client: AsyncClient, session: AsyncSession
):
    """Nothing to present, so the answer sends the person to add one rather
    than opening a prompt that can only fail."""
    user = await _account(session, "pk-stepup-none@example.com")
    _id, headers = await _open_session(session, user)

    response = await client.post(STEP_UP_BEGIN, headers=headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_NOT_FOUND"


async def test_an_assertion_adds_the_passkey_to_the_session(
    client: AsyncClient, session: AsyncSession, assertion
):
    """The session is upgraded rather than replaced: what it had proved carries
    forward, the key it just presented is added, and the old row is retired."""
    from app.core.security import decode_session_token

    user = await _account(session, "pk-stepup@example.com")
    await create_passkey(session, user)
    prior_id, headers = await _open_session(
        session, user, amr=["pwd", "oidc:corp"], satisfied_providers=[9]
    )

    challenge = await _begin_step_up(client, headers)
    response = await client.post(
        STEP_UP_FINISH, json={"credential": assertion_for(challenge)}, headers=headers
    )
    assert response.status_code == 200, response.text
    claims = decode_session_token(response.json()["access_token"])
    assert set(claims["amr"]) >= {"pwd", "oidc:corp", "hwk", "mfa"}
    assert claims["sat"] == [9]

    session.expire_all()
    retired = await session.get(AuthSession, prior_id)
    assert retired.revoked_at is not None


async def test_another_accounts_credential_does_not_step_up_this_session(
    client: AsyncClient, session: AsyncSession, assertion, capfd
):
    """The assertion has to name this account's own credential; a refusal is
    recorded against the account that asked."""
    user = await _account(session, "pk-stepup-mine@example.com")
    user_id = user.id
    await create_passkey(session, user)
    other = await _account(session, "pk-stepup-theirs@example.com")
    await create_passkey(session, other, credential_id="credential-two")
    _id, headers = await _open_session(session, user)
    capfd.readouterr()

    challenge = await _begin_step_up(client, headers)
    response = await client.post(
        STEP_UP_FINISH,
        json={"credential": assertion_for(challenge, credential_id="credential-two")},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"

    events = [
        row
        for row in emitted(capfd, AuditEventType.AUTH_SECOND_FACTOR_FAILED)
        if row["actor_user_id"] == user_id
    ]
    assert len(events) == 1
    assert events[0]["detail"] == {
        "method": "passkey",
        "during": "step_up",
        "reason": "other_account",
    }


async def test_a_step_up_records_which_refusal_it_was(
    client: AsyncClient, session: AsyncSession, assertion, capfd
):
    """A credential this deployment holds no row for proves nothing, and the
    record says which of the refusals it was — the same account the sign-in
    route writes down."""
    user = await _account(session, "pk-stepup-unknown@example.com")
    user_id = user.id
    await create_passkey(session, user)
    _id, headers = await _open_session(session, user)
    capfd.readouterr()

    challenge = await _begin_step_up(client, headers)
    response = await client.post(
        STEP_UP_FINISH,
        json={
            "credential": assertion_for(challenge, credential_id="credential-nobody")
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"

    events = [
        row
        for row in emitted(capfd, AuditEventType.AUTH_SECOND_FACTOR_FAILED)
        if row["actor_user_id"] == user_id
    ]
    assert len(events) == 1
    assert events[0]["detail"] == {
        "method": "passkey",
        "during": "step_up",
        "reason": "unknown",
    }


async def test_a_sign_in_challenge_cannot_step_up_a_session(
    client: AsyncClient, session: AsyncSession, assertion
):
    """Each ceremony is finished as the one it was begun as."""
    user = await _account(session, "pk-stepup-crossed@example.com")
    await create_passkey(session, user)
    _id, headers = await _open_session(session, user)

    challenge = await _begin_sign_in(client)
    response = await client.post(
        STEP_UP_FINISH, json={"credential": assertion_for(challenge)}, headers=headers
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"


async def test_a_step_up_challenge_answers_one_ceremony(
    client: AsyncClient, session: AsyncSession, assertion
):
    user = await _account(session, "pk-stepup-twice@example.com")
    await create_passkey(session, user)
    _id, headers = await _open_session(session, user)

    challenge = await _begin_step_up(client, headers)
    credential = assertion_for(challenge)
    first = await client.post(
        STEP_UP_FINISH, json={"credential": credential}, headers=headers
    )
    assert first.status_code == 200, first.text

    again = await client.post(
        STEP_UP_FINISH, json={"credential": credential}, headers=headers
    )
    assert again.status_code == 400
    assert again.json()["detail"] == "PASSKEY_SIGN_IN_INVALID"


async def test_a_standing_credential_cannot_step_up(
    client: AsyncClient, session: AsyncSession
):
    """The step-up hands back an interactive session, so it is made by the
    person in one of their own."""
    from app.services.platform import api_keys as api_keys_service

    user = await _account(session, "pk-stepup-apikey@example.com")
    await create_passkey(session, user)
    secret, _row = await api_keys_service.create_api_key(
        session, user=user, name="script"
    )
    await session.commit()

    response = await client.post(
        STEP_UP_BEGIN, headers={"Authorization": f"Bearer {secret}"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"

    # Answered before a ceremony is begun: nothing is stored for a request
    # that has no session to add the key to.
    session.expire_all()
    rows = (
        await session.exec(
            select(AuthChallenge).where(AuthChallenge.purpose == "passkey_step_up")
        )
    ).all()
    assert rows == []


async def test_a_withdrawn_method_stops_a_step_up(
    client: AsyncClient, session: AsyncSession
):
    """Withdrawing passkeys closes the ceremony against an open session too,
    not only the ones that open a new one."""
    user = await _account(session, "pk-stepup-withdrawn@example.com")
    await create_passkey(session, user)
    _id, headers = await _open_session(session, user)
    await _withdraw_passkeys(session)

    began = await client.post(STEP_UP_BEGIN, headers=headers)
    assert began.status_code == 403
    assert began.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"

    finished = await client.post(
        STEP_UP_FINISH,
        json={"credential": assertion_for("challenge-value")},
        headers=headers,
    )
    assert finished.status_code == 403
    assert finished.json()["detail"] == "SETTINGS_LOGIN_METHOD_NOT_PERMITTED"


# ---------------------------------------------------------------------------
# The last way in
# ---------------------------------------------------------------------------


async def _passwordless(session: AsyncSession, email: str) -> User:
    return await create_user(
        session,
        email=email,
        hashed_password=None,
        status=UserStatus.active,
        email_verified=True,
    )


async def test_the_last_credential_of_a_passwordless_account_stays(
    client: AsyncClient, session: AsyncSession
):
    """Nothing else opens a session for this account, so the credential is not
    somebody's to remove."""
    user = await _passwordless(session, "pk-last@example.com")
    row = await create_passkey(session, user, credential_id="last-one")

    response = await client.post(
        f"/api/v1/auth/passkeys/{row.id}/remove",
        json={},
        headers=await signed_in_headers(session, user, amr=["webauthn"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PASSKEY_IS_LAST_METHOD"


async def test_a_withdrawn_method_does_not_free_the_last_credential(
    client: AsyncClient, session: AsyncSession
):
    """A deployment that stopped accepting passkeys leaves such an account
    with nothing that opens a session, so the credential stays."""
    user = await _passwordless(session, "pk-last-withdrawn@example.com")
    row = await create_passkey(session, user, credential_id="last-withdrawn")
    headers = await signed_in_headers(session, user, amr=["webauthn"])
    await _withdraw_passkeys(session)

    response = await client.post(
        f"/api/v1/auth/passkeys/{row.id}/remove", json={}, headers=headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PASSKEY_IS_LAST_METHOD"


async def test_a_password_beside_it_lets_the_credential_go(
    client: AsyncClient, session: AsyncSession
):
    user = await _account(session, "pk-last-password@example.com")
    row = await create_passkey(session, user, credential_id="last-with-password")

    response = await client.post(
        f"/api/v1/auth/passkeys/{row.id}/remove",
        json={"current_password": PASSWORD},
        headers=await signed_in_headers(session, user, amr=["hwk"]),
    )
    assert response.status_code == 200, response.text


async def test_a_second_credential_lets_the_first_go(
    client: AsyncClient, session: AsyncSession
):
    user = await _passwordless(session, "pk-two-keys@example.com")
    first = await create_passkey(session, user, credential_id="one-of-two")
    await create_passkey(session, user, credential_id="two-of-two")

    response = await client.post(
        f"/api/v1/auth/passkeys/{first.id}/remove",
        json={},
        headers=await signed_in_headers(session, user, amr=["webauthn"]),
    )
    assert response.status_code == 200, response.text


async def test_the_last_passkey_removed_from_a_new_sign_in_waits(
    client: AsyncClient, session: AsyncSession
):
    """One of two goes at once. The last one waits, and stays until then."""
    user = await _account(session, "pk-held@example.com")
    first = await create_passkey(session, user, credential_id="held-one")
    last = await create_passkey(session, user, credential_id="held-two", name="Phone")
    first_id, last_id = first.id, last.id
    headers = await signed_in_headers(session, user)

    gone = await client.post(
        f"/api/v1/auth/passkeys/{first_id}/remove",
        json={"current_password": PASSWORD},
        headers=headers,
    )
    assert gone.status_code == 200, gone.text

    held = await client.post(
        f"/api/v1/auth/passkeys/{last_id}/remove",
        json={"current_password": PASSWORD},
        headers=headers,
    )
    assert held.status_code == 202, held.text
    assert held.json()["held"]["kind"] == "last_passkey"
    assert held.json()["held"]["subject"] == "Phone"
    session.expire_all()
    assert await session.get(UserPasskey, last_id) is not None
