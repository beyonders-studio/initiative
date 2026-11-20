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


@pytest.mark.parametrize(
    ("app_url", "rp_id", "origin"),
    [
        (
            "https://initiative.example.org",
            "initiative.example.org",
            "https://initiative.example.org",
        ),
        # A self-hosted deployment on a port is the ordinary case, and an
        # origin that dropped it would match nothing.
        ("http://localhost:8000", "localhost", "http://localhost:8000"),
        # The default port is omitted, as the browser does.
        (
            "https://initiative.example.org:443",
            "initiative.example.org",
            "https://initiative.example.org",
        ),
        ("https://[2001:db8::1]:8443", "2001:db8::1", "https://[2001:db8::1]:8443"),
    ],
)
def test_the_relying_party_is_the_deployments_host(
    monkeypatch, app_url: str, rp_id: str, origin: str
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_URL", app_url)
    assert passkeys.relying_party_id() == rp_id
    assert passkeys.expected_origin() == origin


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
# Refusals
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# User verification
# ---------------------------------------------------------------------------


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
