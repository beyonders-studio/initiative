"""The credential store and the ceremonies around it.

The ceremony arithmetic is the library's and is not re-tested here. What these
cover is everything this module adds: which relying party the deployment is,
what a row keeps, and the refusals.
"""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.user_passkey import UserPasskey
from app.services.auth import passkeys
from app.testing import create_user


def _registered(**overrides) -> passkeys.RegisteredCredential:
    base = {
        "credential_id": b"credential-one",
        "public_key": b"public-key-bytes",
        "sign_count": 0,
        "aaguid": "00000000-0000-0000-0000-000000000000",
        "user_verified": True,
        "backed_up": False,
        "transports": ["internal", "hybrid"],
    }
    base.update(overrides)
    return passkeys.RegisteredCredential(**base)


# ---------------------------------------------------------------------------
# Who this deployment is
# ---------------------------------------------------------------------------


def test_the_relying_party_is_the_deployments_host(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://initiative.example.org")
    assert passkeys.relying_party_id() == "initiative.example.org"
    assert passkeys.expected_origin() == "https://initiative.example.org"


def test_the_origin_keeps_a_port(monkeypatch):
    """A self-hosted deployment on a port is the ordinary case, and an origin
    that dropped it would match nothing."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "http://localhost:8000")
    assert passkeys.relying_party_id() == "localhost"
    assert passkeys.expected_origin() == "http://localhost:8000"


def test_the_origin_omits_a_default_port_like_the_browser_does(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://initiative.example.org:443")
    assert passkeys.expected_origin() == "https://initiative.example.org"


def test_the_origin_keeps_ipv6_brackets(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://[2001:db8::1]:8443")
    assert passkeys.expected_origin() == "https://[2001:db8::1]:8443"


def test_the_projects_android_apps_are_expected_origins_too(monkeypatch):
    """Android reports the hash of the app's signing certificate as the origin.
    Only a dev image accepts the dev app."""
    from app.core import version
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://initiative.example.org")
    release = "android:apk-key-hash:cvsXHKGKyjCmmYG4hA_hawNRfOSvgZbPTouRe7vbG78"
    dev = "android:apk-key-hash:QpphJvemX5-Tpxc2wJPiYbz0CXsKeHS5xgyGiYz-F_g"

    monkeypatch.setattr(version, "is_dev_image", lambda: False)
    assert passkeys.expected_origins() == ["https://initiative.example.org", release]

    monkeypatch.setattr(version, "is_dev_image", lambda: True)
    assert passkeys.expected_origins() == [
        "https://initiative.example.org",
        release,
        dev,
    ]


@pytest.mark.parametrize(
    ("app_url", "refusal"),
    [
        ("https://initiative.example.org", None),
        ("https://192.168.1.10", "ip_host"),
        ("http://intranet.local", "insecure_origin"),
        ("http://localhost:5173", None),
        ("http://127.0.0.1:5173", None),
        ("https://[::1]:8443", None),
        ("", "no_host"),
    ],
)
def test_which_addresses_can_carry_a_credential(monkeypatch, app_url, refusal):
    """A passkey is bound to a named host reached over https. The deployment's
    own address decides whether there is one to bind to, and the machine itself
    is the exception the browser already makes — however it is spelled."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", app_url)
    assert passkeys.site_refusal() == refusal


def test_a_plugin_url_naming_no_host_is_refused(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "not-a-url")
    with pytest.raises(RuntimeError):
        passkeys.relying_party_id()


# ---------------------------------------------------------------------------
# What a row keeps
# ---------------------------------------------------------------------------


async def test_a_stored_credential_records_the_domain_it_was_made_under(
    session, monkeypatch
):
    """The failure this is for: a deployment that changes domain derives a
    different relying party, and a credential made under the old one cannot
    answer under the new. The row says which it was."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://first.example.org")
    user = await create_user(session, email="pk-rp@example.com")

    row = await passkeys.store(
        session, user_id=user.id, registered=_registered(), name="Laptop"
    )
    assert row.rp_id == "first.example.org"


async def test_a_stored_credential_keeps_what_the_ceremony_reported(
    session, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://kept.example.org")
    user = await create_user(session, email="pk-keep@example.com")

    row = await passkeys.store(
        session,
        user_id=user.id,
        registered=_registered(user_verified=True, backed_up=True, sign_count=7),
        name="Phone",
    )
    assert row.user_verified is True
    assert row.backed_up is True
    assert row.sign_count == 7
    assert row.transports == ["internal", "hybrid"]


async def test_a_name_longer_than_the_column_is_cut_not_refused(session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://name.example.org")
    user = await create_user(session, email="pk-name@example.com")

    row = await passkeys.store(
        session, user_id=user.id, registered=_registered(), name="x" * 200
    )
    assert len(row.name) == passkeys.MAX_NAME_LENGTH


async def test_two_registrations_racing_for_the_last_slot_cannot_both_win(
    session, engine, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://limit.example.org")
    user = await create_user(session, email="pk-limit@example.com")
    for index in range(passkeys.MAX_PASSKEYS_PER_USER - 1):
        await passkeys.store(
            session,
            user_id=user.id,
            registered=_registered(credential_id=f"existing-{index}".encode()),
            name=f"Existing {index}",
        )
    await session.commit()

    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def register(credential_id: bytes) -> bool:
        async with maker() as racing:
            try:
                await passkeys.store(
                    racing,
                    user_id=user.id,
                    registered=_registered(credential_id=credential_id),
                    name="Racing key",
                )
                await racing.commit()
                return True
            except passkeys.PasskeyLimitReached:
                await racing.rollback()
                return False

    outcomes = await asyncio.gather(register(b"racer-one"), register(b"racer-two"))

    assert sum(outcomes) == 1
    assert await passkeys.count_for_user(session, user_id=user.id) == (
        passkeys.MAX_PASSKEYS_PER_USER
    )


# ---------------------------------------------------------------------------
# Ceremonies
# ---------------------------------------------------------------------------


async def test_registration_excludes_what_the_account_already_holds(
    session, monkeypatch
):
    """An authenticator that already has a credential for this deployment says
    so rather than quietly making a second."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://exclude.example.org")
    user = await create_user(session, email="pk-exclude@example.com")
    await passkeys.store(
        session, user_id=user.id, registered=_registered(), name="First"
    )

    ceremony = await passkeys.begin_registration(
        session, user_id=user.id, account_name="a@example.com", display_name="A"
    )
    assert ceremony.options["excludeCredentials"]
    assert ceremony.options["rp"]["id"] == "exclude.example.org"
    assert len(ceremony.challenge) >= 16


async def test_signing_in_may_start_without_naming_an_account(session, monkeypatch):
    """No allow-list is what lets somebody sign in without typing who they are:
    the authenticator offers what it holds and the assertion names it."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://anon.example.org")

    ceremony = passkeys.begin_authentication()
    assert not ceremony.options.get("allowCredentials")


async def test_answering_for_one_account_offers_only_its_own(session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://named.example.org")
    user = await create_user(session, email="pk-named@example.com")
    await passkeys.store(session, user_id=user.id, registered=_registered(), name="Key")

    ceremony = passkeys.begin_authentication(
        credentials=await passkeys.list_for_user(session, user_id=user.id)
    )
    assert len(ceremony.options["allowCredentials"]) == 1


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


async def test_a_credential_nobody_registered_does_not_answer(session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://unknown.example.org")

    result = await passkeys.finish_authentication(
        session,
        credential={"rawId": "bm90LWEtY3JlZGVudGlhbA"},
        expected_challenge=b"challenge",
    )
    assert result.reason == "unknown"
    # Nothing to name an account with.
    assert result.passkey is None


async def test_a_credential_from_another_domain_does_not_answer(session, monkeypatch):
    """The whole reason the domain is on the row. It is refused before any
    signature is checked, so the answer can be about the domain."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://before.example.org")
    user = await create_user(session, email="pk-moved@example.com")
    await passkeys.store(
        session, user_id=user.id, registered=_registered(), name="Old key"
    )

    monkeypatch.setattr(settings, "APP_URL", "https://after.example.org")
    import base64

    raw_id = base64.urlsafe_b64encode(b"credential-one").rstrip(b"=").decode()
    result = await passkeys.finish_authentication(
        session, credential={"rawId": raw_id}, expected_challenge=b"challenge"
    )
    assert result.reason == "wrong_rp"
    # The row is handed back, so the caller can write the refusal down against
    # the account whose credential it is.
    assert result.passkey.user_id == user.id


async def test_the_counter_row_stays_locked_until_the_update_commits(
    session, engine, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://counter.example.org")
    user = await create_user(session, email="pk-counter@example.com")
    await passkeys.store(
        session,
        user_id=user.id,
        registered=_registered(sign_count=10),
        name="Counter key",
    )
    await session.commit()

    seen_counts: list[int] = []

    def verify(**kwargs):
        current = kwargs["credential_current_sign_count"]
        seen_counts.append(current)
        return SimpleNamespace(
            new_sign_count=current + 1,
            credential_backed_up=False,
            user_verified=True,
        )

    monkeypatch.setattr(passkeys.webauthn, "verify_authentication_response", verify)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    credential = {"rawId": "Y3JlZGVudGlhbC1vbmU"}

    async with maker() as first, maker() as second:
        answered = await passkeys.finish_authentication(
            first, credential=credential, expected_challenge=b"challenge"
        )
        assert isinstance(answered, passkeys.Assertion)
        waiting = asyncio.create_task(
            passkeys.finish_authentication(
                second, credential=credential, expected_challenge=b"challenge"
            )
        )
        await asyncio.sleep(0.05)
        assert not waiting.done()

        await first.commit()
        answered_again = await asyncio.wait_for(waiting, timeout=1)
        assert isinstance(answered_again, passkeys.Assertion)
        await second.commit()

    assert seen_counts == [10, 11]


async def test_a_malformed_credential_id_does_not_raise(session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://bad.example.org")

    result = await passkeys.finish_authentication(
        session, credential={}, expected_challenge=b"challenge"
    )
    assert result.reason == "unknown"
    assert result.passkey is None


async def test_an_assertion_that_does_not_verify_names_its_credential(
    session, monkeypatch
):
    """The refusal the caller writes down is about an account, even though
    what it answers the client with says nothing about one."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://unverified.example.org")
    user = await create_user(session, email="pk-unverified@example.com")
    await passkeys.store(session, user_id=user.id, registered=_registered(), name="Key")

    def refuse(**kwargs):
        raise ValueError("signature")

    monkeypatch.setattr(passkeys.webauthn, "verify_authentication_response", refuse)

    result = await passkeys.finish_authentication(
        session,
        credential={"rawId": "Y3JlZGVudGlhbC1vbmU"},
        expected_challenge=b"challenge",
    )
    assert result.reason == "invalid"
    assert result.passkey.user_id == user.id


# ---------------------------------------------------------------------------
# Managing them
# ---------------------------------------------------------------------------


async def test_a_passkey_belongs_to_one_account(session, monkeypatch):
    """Rename and remove are refused for somebody else's, rather than reporting
    a row that is not theirs to know about."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://own.example.org")
    owner = await create_user(session, email="pk-owner@example.com")
    other = await create_user(session, email="pk-other@example.com")
    row = await passkeys.store(
        session, user_id=owner.id, registered=_registered(), name="Mine"
    )

    assert (
        await passkeys.rename(
            session, user_id=other.id, passkey_id=row.id, name="Yours"
        )
        is None
    )
    assert await passkeys.remove(session, user_id=other.id, passkey_id=row.id) is False
    renamed = await passkeys.rename(
        session, user_id=owner.id, passkey_id=row.id, name="Renamed"
    )
    assert renamed is not None and renamed.name == "Renamed"

    kept = await session.get(UserPasskey, row.id)
    assert kept is not None and kept.name == "Renamed"


# ---------------------------------------------------------------------------
# User verification
# ---------------------------------------------------------------------------


async def test_both_ceremonies_ask_for_the_person(session, monkeypatch):
    """A PIN, a fingerprint or a face, not merely the device — at registration
    and at every sign-in, so an assertion stands for both."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://uv.example.org")
    user = await create_user(session, email="pk-uv-options@example.com")

    registration = await passkeys.begin_registration(
        session, user_id=user.id, account_name="a@example.com", display_name="A"
    )
    assert (
        registration.options["authenticatorSelection"]["userVerification"] == "required"
    )

    authentication = passkeys.begin_authentication()
    assert authentication.options["userVerification"] == "required"


def test_the_registration_check_insists_on_it(monkeypatch):
    """Asking is one half; the finished ceremony is checked against what was
    asked for."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://uv-reg.example.org")
    seen: dict = {}

    def verify(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            credential_id=b"credential-one",
            credential_public_key=b"public-key-bytes",
            sign_count=0,
            aaguid=None,
            user_verified=True,
            credential_backed_up=False,
        )

    monkeypatch.setattr(passkeys.webauthn, "verify_registration_response", verify)
    passkeys.finish_registration(
        credential={"response": {"transports": []}}, expected_challenge=b"challenge"
    )
    assert seen["require_user_verification"] is True
    assert seen["expected_origin"] == passkeys.expected_origins()


async def test_the_assertion_check_insists_on_it(session, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", "https://uv-auth.example.org")
    user = await create_user(session, email="pk-uv-assert@example.com")
    await passkeys.store(session, user_id=user.id, registered=_registered(), name="Key")

    seen: dict = {}

    def verify(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            new_sign_count=1, credential_backed_up=False, user_verified=True
        )

    monkeypatch.setattr(passkeys.webauthn, "verify_authentication_response", verify)
    result = await passkeys.finish_authentication(
        session,
        credential={"rawId": "Y3JlZGVudGlhbC1vbmU"},
        expected_challenge=b"challenge",
    )
    assert isinstance(result, passkeys.Assertion)
    assert seen["require_user_verification"] is True
    assert seen["expected_origin"] == passkeys.expected_origins()
