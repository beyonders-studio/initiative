"""Settings rows: where they come from, and what asking for one costs."""

import base64
import hashlib
import json
import logging

from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings as app_config
from app.core.encryption import (
    SALT_PLUGIN_PLATFORM_SIGNING_KEY,
    SALT_CAPTCHA_SECRET_KEY,
    SALT_FCM_SERVICE_ACCOUNT,
    SALT_SMTP_PASSWORD,
    decrypt_field,
)
from app.core.login_methods import DEFAULT_LOGIN_METHODS
from app.models.platform.app_setting import AppSetting
from app.services.marketplace import context_jwt
from app.services.platform.app_settings import (
    GLOBAL_SETTINGS_ID,
    _build_default_app_settings,
    ensure_settings_row,
    get_app_setting_secrets,
    get_app_settings,
    get_or_create_guild_settings,
    load_plugin_platform_signing_key,
    seed_app_settings,
)
from app.testing import create_guild, route_session_to_guild


async def _stored_ids(session: AsyncSession) -> list[int]:
    return list((await session.exec(select(AppSetting.id))).all())


async def test_seeding_creates_the_singleton(session: AsyncSession):
    """Boot is where the row comes from, and saying so twice changes nothing."""
    assert await _stored_ids(session) == []

    first = await seed_app_settings(session)
    assert first.id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]

    second = await seed_app_settings(session)
    assert second.id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]


async def test_reading_settings_before_the_seed_stores_nothing(session: AsyncSession):
    """Configuration read on a database that has no row yet answers from the env."""
    row = await get_app_settings(session)
    assert row.id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == []


async def test_reading_settings_leaves_the_transaction_open(session: AsyncSession):
    """A read is a read: the caller's transaction is still theirs afterwards.

    Stated as the transaction id, which is what anything held for the length of
    a transaction — a row lock, an advisory lock — is keyed on.
    """
    before = (await session.exec(text("SELECT txid_current()"))).one()

    await get_app_settings(session)
    assert (await session.exec(text("SELECT txid_current()"))).one() == before

    await seed_app_settings(session)  # the row now exists; read it again
    started = (await session.exec(text("SELECT txid_current()"))).one()
    await get_app_settings(session)
    assert (await session.exec(text("SELECT txid_current()"))).one() == started


async def test_settings_row_for_a_writer_joins_the_transaction(session: AsyncSession):
    """``ensure_settings_row`` puts the row in place without ending the caller."""
    before = (await session.exec(text("SELECT txid_current()"))).one()

    row = await ensure_settings_row(session)
    assert row.id == GLOBAL_SETTINGS_ID
    assert (await session.exec(text("SELECT txid_current()"))).one() == before

    # Still one row, and the same one, when a second caller asks.
    assert (await ensure_settings_row(session)).id == GLOBAL_SETTINGS_ID
    assert await _stored_ids(session) == [GLOBAL_SETTINGS_ID]


async def test_guild_settings_gap_fill_joins_the_transaction(session: AsyncSession):
    """A guild missing its settings row gets one inside the caller's transaction.

    A guild is normally given the row when it is made, so this is the gap-fill
    path. Stated as the transaction id, the same way the platform singleton's
    is: whoever asked still has the transaction they asked from.
    """
    guild = await create_guild(session)
    await route_session_to_guild(session, guild.id)
    await session.exec(text("DELETE FROM guild_settings"))
    await session.commit()

    started = (await session.exec(text("SELECT txid_current()"))).one()
    row = await get_or_create_guild_settings(session, guild.id)
    assert row.id is not None
    assert (await session.exec(text("SELECT txid_current()"))).one() == started

    # Asking again answers with the row already there, same transaction still.
    assert (await get_or_create_guild_settings(session, guild.id)).id == row.id
    assert (await session.exec(text("SELECT txid_current()"))).one() == started


# --- The sign-in posture the env seeds ------------------------------------

DEFAULT_METHODS = [m.value for m in DEFAULT_LOGIN_METHODS]


def _seed_env(monkeypatch, methods, *, mail: bool = True) -> None:
    monkeypatch.setattr(app_config, "AUTH_LOGIN_METHODS", methods)
    monkeypatch.setattr(app_config, "SMTP_HOST", "smtp.example.com" if mail else None)
    monkeypatch.setattr(
        app_config, "SMTP_FROM_ADDRESS", "app@example.com" if mail else None
    )


def test_env_decides_the_ways_in_of_a_fresh_row(monkeypatch):
    """AUTH_LOGIN_METHODS is stored the way the settings page stores it."""
    _seed_env(monkeypatch, ["sso", "passkey", "totp", "email_otp"])
    assert _build_default_app_settings().login_methods == [
        "email_otp",
        "passkey",
        "sso",
        "totp",
    ]


def test_env_unset_keeps_the_default(monkeypatch):
    _seed_env(monkeypatch, [])
    assert _build_default_app_settings().login_methods == DEFAULT_METHODS


def test_env_value_this_version_does_not_know_is_dropped_and_said(monkeypatch, caplog):
    _seed_env(monkeypatch, ["sso", "magic_link"])
    with caplog.at_level(logging.WARNING):
        assert _build_default_app_settings().login_methods == ["sso"]
    assert "magic_link" in caplog.text


def test_env_with_no_way_to_begin_keeps_the_default(monkeypatch, caplog):
    """The column's CHECK would refuse the row; falling back keeps the
    deployment one somebody can still configure."""
    _seed_env(monkeypatch, ["totp"])
    with caplog.at_level(logging.WARNING):
        assert _build_default_app_settings().login_methods == DEFAULT_METHODS
    assert "begin a session" in caplog.text


def test_env_emailed_code_needs_a_mail_server(monkeypatch, caplog):
    """The rule the settings page enforces on the way up, applied to the seed."""
    _seed_env(monkeypatch, ["sso", "email_otp"], mail=False)
    with caplog.at_level(logging.WARNING):
        assert _build_default_app_settings().login_methods == ["sso"]
    assert "mail server" in caplog.text


async def test_env_seeds_the_row_once(session: AsyncSession, monkeypatch):
    """The env decides a row it creates, and never one that already exists."""
    _seed_env(monkeypatch, ["sso", "passkey"])
    assert (await seed_app_settings(session)).login_methods == ["passkey", "sso"]

    _seed_env(monkeypatch, ["password"])
    assert (await seed_app_settings(session)).login_methods == ["passkey", "sso"]
    assert (await get_app_settings(session)).login_methods == ["passkey", "sso"]


async def test_first_boot_stores_every_env_credential(
    session: AsyncSession, monkeypatch
):
    """A fresh row keeps each secret the environment named, not only some."""
    monkeypatch.setattr(app_config, "SMTP_PASSWORD", "smtp-pass")
    monkeypatch.setattr(app_config, "CAPTCHA_SECRET_KEY", "captcha-secret")
    monkeypatch.setattr(app_config, "FCM_SERVICE_ACCOUNT_JSON", '{"type": "sa"}')

    await seed_app_settings(session)
    stored = await get_app_setting_secrets(session)

    assert (
        decrypt_field(stored.smtp_password_encrypted, SALT_SMTP_PASSWORD) == "smtp-pass"
    )
    assert (
        decrypt_field(stored.captcha_secret_key_encrypted, SALT_CAPTCHA_SECRET_KEY)
        == "captcha-secret"
    )
    assert (
        decrypt_field(
            stored.fcm_service_account_json_encrypted, SALT_FCM_SERVICE_ACCOUNT
        )
        == '{"type": "sa"}'
    )


# --- The plug-in platform's signing key ---------------------------------------


def _without_a_platform_key(monkeypatch) -> None:
    monkeypatch.setattr(app_config, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None)
    monkeypatch.setattr(app_config, "PLUGIN_PLATFORM_SIGNING_KEY_ID", None)
    monkeypatch.setattr(security, "_stored_plugin_platform_key", None)
    monkeypatch.setattr(context_jwt, "_jwks_cache", None)


async def _stored_platform_key(session: AsyncSession) -> str | None:
    return (
        await session.exec(
            text(
                "SELECT plugin_platform_signing_key_encrypted FROM app_setting_secrets"
            )
        )
    ).one()[0]


async def test_a_deployment_with_no_platform_key_generates_one_and_keeps_it(
    session: AsyncSession, monkeypatch
):
    """The first start stores a key, and a later start loads that same key."""
    _without_a_platform_key(monkeypatch)
    await seed_app_settings(session)
    assert not security.plugin_platform_signing_enabled()

    await load_plugin_platform_signing_key(session)
    pem, kid = security.resolve_plugin_platform_signing_material()
    stored = await _stored_platform_key(session)
    assert decrypt_field(stored, SALT_PLUGIN_PLATFORM_SIGNING_KEY) == pem

    # The published key carries the same kid: its RFC 7638 thumbprint.
    (entry,) = context_jwt.context_jwks()["keys"]
    assert entry["alg"] == "EdDSA"
    members = json.dumps(
        {"crv": "Ed25519", "kty": "OKP", "x": entry["x"]}, separators=(",", ":")
    )
    thumbprint = base64.urlsafe_b64encode(hashlib.sha256(members.encode()).digest())
    assert kid == entry["kid"] == thumbprint.rstrip(b"=").decode()

    # Another process starting afterwards signs with the stored key.
    monkeypatch.setattr(security, "_stored_plugin_platform_key", None)
    await load_plugin_platform_signing_key(session)
    assert security.resolve_plugin_platform_signing_material() == (pem, kid)
    assert await _stored_platform_key(session) == stored


async def test_a_stored_rsa_platform_key_is_replaced_with_an_ed25519_one(
    session: AsyncSession, monkeypatch
):
    """A key stored before the platform key became Ed25519 is replaced once, and
    a later start keeps the replacement."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.core.encryption import encrypt_field

    _without_a_platform_key(monkeypatch)
    await seed_app_settings(session)
    await load_plugin_platform_signing_key(session)
    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    await session.exec(
        text(
            "UPDATE app_setting_secrets SET plugin_platform_signing_key_encrypted = :v"
        ).bindparams(v=encrypt_field(rsa_pem, SALT_PLUGIN_PLATFORM_SIGNING_KEY))
    )
    await session.commit()
    monkeypatch.setattr(security, "_stored_plugin_platform_key", None)

    await load_plugin_platform_signing_key(session)
    pem, _ = security.resolve_plugin_platform_signing_material()
    assert context_jwt.is_platform_key(pem)
    replaced = await _stored_platform_key(session)
    assert decrypt_field(replaced, SALT_PLUGIN_PLATFORM_SIGNING_KEY) == pem

    monkeypatch.setattr(security, "_stored_plugin_platform_key", None)
    await load_plugin_platform_signing_key(session)
    assert security.resolve_plugin_platform_signing_material()[0] == pem
    assert await _stored_platform_key(session) == replaced


async def test_the_env_platform_key_wins(session: AsyncSession, monkeypatch):
    """A key in env is used as given, and none is generated beside it."""
    _without_a_platform_key(monkeypatch)
    monkeypatch.setattr(
        app_config, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", "env-pem"
    )
    monkeypatch.setattr(app_config, "PLUGIN_PLATFORM_SIGNING_KEY_ID", "env-kid")
    await seed_app_settings(session)

    await load_plugin_platform_signing_key(session)

    assert await _stored_platform_key(session) is None
    assert security.resolve_plugin_platform_signing_material() == (
        "env-pem",
        "env-kid",
    )
