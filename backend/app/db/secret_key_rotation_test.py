"""Tests for one-shot SECRET_KEY rotation.

The DB-backed tests follow the guild_conversion_test pattern: seed committed rows
via the (superuser) ``engine`` fixture, run the rotation — which reads
``db_session.provisioning_engine`` (pointed at the test engine by the autouse
``_schema_test_harness`` fixture) — then clean up in ``finally``.

Rotation scans ALL rows globally, so assertions target the specific seeded rows.
Rows encrypted under some *other* key are classified ``failed`` and left untouched
(no UPDATE), so they can't be corrupted by these tests.
"""

import json
import secrets

import pytest
from sqlalchemy import text
from sqlmodel import SQLModel

from app.core import config, security
from app.core.audit_events import AuditEventType
from app.core.encryption import (
    FERNET_SALT,
    SALT_AI_API_KEY,
    SALT_EMAIL,
    SALT_PLUGIN_CONFIG,
    SALT_PLUGIN_PLATFORM_SIGNING_KEY,
    SALT_PLUGIN_VENDOR,
    decrypt_field,
    encrypt_field,
    hash_email,
)
from app.db import cohorts
from app.db.schema_provisioning import (
    drop_guild_schema,
    guild_schema_name,
    provision_guild,
)
from app.db.secret_key_rotation import (
    _rotate_value,
    maybe_rotate_at_startup,
    rotate_secret_key,
)
from app.services.platform.app_settings import (
    load_plugin_platform_signing_key,
    seed_app_settings,
)
from app.testing import create_plugin_service_registration, sealed_vendor_values
from app.testing.audit import emitted

# Distinct test-only keys (≥32 chars). Deliberately different from the ambient
# test SECRET_KEY so unrelated rows fall into the (untouched) "failed" bucket.
OLD = "o" * 48
NEW = "n" * 48


def _use_keys(monkeypatch, *, old, new) -> None:
    """Point the live settings at NEW (current) + OLD (previous). validate_assignment
    is off, so these assignments don't re-run the strong-key validator."""
    monkeypatch.setattr(config.settings, "SECRET_KEY", new)
    monkeypatch.setattr(config.settings, "PREVIOUS_SECRET_KEY", old)


# ── pure classification (no DB) ──────────────────────────────────────────────


def test_rotate_value_skips_when_already_under_new_key():
    already_new = encrypt_field("x", SALT_EMAIL, secret_key=NEW)
    status, value = _rotate_value(already_new, SALT_EMAIL, OLD, NEW)
    assert status == "skipped"
    assert value == already_new


def test_rotate_value_reencrypts_from_old_key():
    old_ct = encrypt_field("x", SALT_EMAIL, secret_key=OLD)
    status, new_ct = _rotate_value(old_ct, SALT_EMAIL, OLD, NEW)
    assert status == "rotated"
    assert decrypt_field(new_ct, SALT_EMAIL, secret_key=NEW) == "x"


def test_rotate_value_reports_failed_when_neither_key_works():
    foreign = encrypt_field("x", SALT_EMAIL, secret_key="z" * 48)
    status, value = _rotate_value(foreign, SALT_EMAIL, OLD, NEW)
    assert status == "failed"
    assert value is None


# ── guards (no DB) ───────────────────────────────────────────────────────────


async def test_rotate_raises_without_previous_key(monkeypatch):
    monkeypatch.setattr(config.settings, "SECRET_KEY", NEW)
    monkeypatch.setattr(config.settings, "PREVIOUS_SECRET_KEY", None)
    with pytest.raises(RuntimeError, match="PREVIOUS_SECRET_KEY is not set"):
        await rotate_secret_key()


async def test_rotate_raises_when_keys_equal(monkeypatch):
    monkeypatch.setattr(config.settings, "SECRET_KEY", NEW)
    monkeypatch.setattr(config.settings, "PREVIOUS_SECRET_KEY", NEW)
    with pytest.raises(RuntimeError, match="equals SECRET_KEY"):
        await rotate_secret_key()


async def test_maybe_rotate_at_startup_is_noop_when_unset(monkeypatch):
    monkeypatch.setattr(config.settings, "SECRET_KEY", NEW)
    monkeypatch.setattr(config.settings, "PREVIOUS_SECRET_KEY", None)
    # Must NOT raise and must not touch the DB.
    await maybe_rotate_at_startup()


# ── end-to-end against real tables ───────────────────────────────────────────


async def _insert_user(conn, email: str, *, key: str) -> int:
    """An account and the address row that carries its address."""
    user_id = await conn.scalar(
        text(
            "INSERT INTO public.users "
            "(hashed_password, username, discriminator, created_at, updated_at) "
            "VALUES ('x', :u, :d, now(), now()) RETURNING id"
        ),
        {
            "u": f"rotate-{secrets.token_hex(4)}",
            "d": secrets.randbelow(10000),
        },
    )
    await conn.execute(
        text(
            "INSERT INTO public.user_emails "
            "(user_id, email_hash, email_encrypted, is_primary, source, "
            "verified_at, created_at) "
            "VALUES (:uid, :h, :e, true, 'signup', now(), now())"
        ),
        {
            "uid": user_id,
            "h": hash_email(email, secret_key=key),
            "e": encrypt_field(email, SALT_EMAIL, secret_key=key),
        },
    )
    return user_id


async def test_rotate_user_email_hash_and_fernet_columns(engine, monkeypatch, capfd):
    """A user seeded under OLD has its email pair re-keyed to NEW; the recomputed
    email_hash matches a NEW-key lookup. Second run is idempotent. A run that
    sealed something is written down; one that found nothing is not."""
    email = "rot-user@example.com"
    old_hash = hash_email(email, secret_key=OLD)
    user_id = None
    try:
        async with engine.begin() as conn:
            user_id = await _insert_user(conn, email, key=OLD)

        _use_keys(monkeypatch, old=OLD, new=NEW)
        emitted(capfd)
        summary = await rotate_secret_key()
        assert summary.rotated >= 1  # email pair (counts once)
        (line,) = emitted(capfd, AuditEventType.PLATFORM_SECRET_KEY_ROTATED)
        assert line["detail"]["rotated"] == summary.rotated

        async with engine.connect() as conn:
            h, e = (
                await conn.execute(
                    text(
                        "SELECT email_hash, email_encrypted "
                        "FROM public.user_emails WHERE user_id = :i"
                    ),
                    {"i": user_id},
                )
            ).one()

        # email_hash recomputed under NEW → a NEW-key lookup now finds this user.
        assert h == hash_email(email, secret_key=NEW)
        assert h != old_hash
        assert decrypt_field(e, SALT_EMAIL, secret_key=NEW) == email

        # Idempotent: a second run re-keys nothing (this row is already under NEW).
        again = await rotate_secret_key()
        async with engine.connect() as conn:
            h2 = await conn.scalar(
                text("SELECT email_hash FROM public.user_emails WHERE user_id = :i"),
                {"i": user_id},
            )
        assert h2 == h  # unchanged
        # Nothing of *ours* rotated again (other rows under foreign keys are ignored).
        assert again.rotated == 0
        assert emitted(capfd, AuditEventType.PLATFORM_SECRET_KEY_ROTATED) == []
    finally:
        if user_id is not None:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM public.user_emails WHERE user_id = :i"),
                    {"i": user_id},
                )


async def test_rotate_the_addresses_inside_an_account_letter(engine, monkeypatch):
    """The removed address and the link's recipient are re-keyed where they sit
    in the change record; the plain values beside them are left alone."""
    email = "rot-letter@example.com"
    user_id = None
    try:
        async with engine.begin() as conn:
            user_id = await _insert_user(conn, email, key=OLD)
            sealed = encrypt_field(email, SALT_EMAIL, secret_key=OLD)
            letter = {"notice": "address.removed", "undo": {"email": sealed}}
            await conn.execute(
                text(
                    "INSERT INTO public.email_outbox (user_id, category, security, "
                    "locale, subject, headline, body, change, created_at, "
                    "deliver_after) VALUES (:uid, 'account', true, 'en', 's', 'h', "
                    "'b', CAST(:change AS jsonb), now(), now())"
                ),
                {"uid": user_id, "change": json.dumps(letter)},
            )
            await conn.execute(
                text(
                    "INSERT INTO public.user_tokens (user_id, token, purpose, change, "
                    "expires_at, created_at) VALUES (:uid, :token, 'account_change', "
                    "CAST(:change AS jsonb), now() + interval '1 day', now())"
                ),
                {
                    "uid": user_id,
                    "token": secrets.token_hex(16),
                    "change": json.dumps({**letter, "recipient": sealed}),
                },
            )

        _use_keys(monkeypatch, old=OLD, new=NEW)
        await rotate_secret_key()

        async with engine.connect() as conn:
            changes = [
                await conn.scalar(
                    text(f"SELECT change FROM public.{table} WHERE user_id = :i"),
                    {"i": user_id},
                )
                for table in ("email_outbox", "user_tokens")
            ]
        for change in changes:
            assert change["notice"] == "address.removed"
            sealed_now = [change["undo"]["email"], change.get("recipient")]
            for value in filter(None, sealed_now):
                assert decrypt_field(value, SALT_EMAIL, secret_key=NEW) == email
        assert changes[1]["recipient"] is not None
    finally:
        if user_id is not None:
            async with engine.begin() as conn:
                for table in ("email_outbox", "user_tokens", "user_emails"):
                    await conn.execute(
                        text(f"DELETE FROM public.{table} WHERE user_id = :i"),
                        {"i": user_id},
                    )


async def test_dry_run_reports_but_does_not_write(engine, monkeypatch):
    email = "rot-dry@example.com"
    old_hash = hash_email(email, secret_key=OLD)
    old_email_ct = encrypt_field(email, SALT_EMAIL, secret_key=OLD)
    user_id = None
    try:
        async with engine.begin() as conn:
            user_id = await conn.scalar(
                text(
                    "INSERT INTO public.users "
                    "(hashed_password, username, discriminator, created_at, "
                    "updated_at) "
                    "VALUES ('x', :u, :d, now(), now()) RETURNING id"
                ),
                {
                    "u": f"rotate-{secrets.token_hex(4)}",
                    "d": secrets.randbelow(10000),
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO public.user_emails "
                    "(user_id, email_hash, email_encrypted, is_primary, source, "
                    "verified_at, created_at) "
                    "VALUES (:uid, :h, :e, true, 'signup', now(), now())"
                ),
                {"uid": user_id, "h": old_hash, "e": old_email_ct},
            )

        _use_keys(monkeypatch, old=OLD, new=NEW)
        summary = await rotate_secret_key(dry_run=True)
        assert summary.rotated >= 1  # would rotate

        async with engine.connect() as conn:
            h, e = (
                await conn.execute(
                    text(
                        "SELECT email_hash, email_encrypted FROM public.user_emails WHERE user_id = :i"
                    ),
                    {"i": user_id},
                )
            ).one()
        # Untouched: still the OLD hash/ciphertext.
        assert h == old_hash
        assert e == old_email_ct
    finally:
        if user_id is not None:
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM public.user_emails WHERE user_id = :i"),
                    {"i": user_id},
                )


async def test_rotate_reencrypts_the_plugin_platform_key_and_vendor_values(
    session, monkeypatch
):
    """The key a deployment generated for its plug-ins and every value in a
    registration's vendor map move to the new key with the other stored
    credentials, and still read back as the same values."""
    monkeypatch.setattr(config.settings, "SECRET_KEY", OLD)
    monkeypatch.setattr(
        config.settings, "PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM", None
    )
    monkeypatch.setattr(security, "_stored_plugin_platform_key", None)
    await seed_app_settings(session)
    await load_plugin_platform_signing_key(session)
    pem, _ = security.resolve_plugin_platform_signing_material()
    await session.commit()
    vendor = {"client_id": "vendor-id", "client_secret": "vendor-secret"}
    registration = await create_plugin_service_registration(
        session, vendor_values=sealed_vendor_values(vendor)
    )

    _use_keys(monkeypatch, old=OLD, new=NEW)
    await rotate_secret_key()

    stored = await session.scalar(
        text("SELECT plugin_platform_signing_key_encrypted FROM app_setting_secrets")
    )
    assert (
        decrypt_field(stored, SALT_PLUGIN_PLATFORM_SIGNING_KEY, secret_key=NEW) == pem
    )
    vendor_values = await session.scalar(
        text("SELECT vendor_values FROM plugin_service_registrations WHERE id = :i"),
        {"i": registration.id},
    )
    assert {
        key: decrypt_field(value, SALT_PLUGIN_VENDOR, secret_key=NEW)
        for key, value in vendor_values.items()
    } == vendor


async def test_rotate_visits_per_guild_schema_settings(engine, monkeypatch):
    """The guild AI key columns are guild-scoped, so they live in guild_<id>
    schemas — the sweep re-keys them there. This covers a guild-level table
    (guild_ai_connection_keys) and every value of an install's plug-in secrets
    map, by connection then field (guild_plugin_secrets). Guild data is re-keyed
    ONLY through its guild schema, never an unrouted public pathway."""
    gid = None
    plugin_secrets = {
        "admin_read": {"api_key": "read-key", "region": "eu"},
        "member_write": {"token": "write-token"},
    }
    try:
        async with engine.begin() as conn:
            gid = await conn.scalar(
                text(
                    "INSERT INTO public.guilds (name) VALUES ('Rot Guild') RETURNING id"
                )
            )
        await provision_guild(gid)  # creates the guild_<id> schema (own transaction)
        schema = guild_schema_name(gid)
        async with engine.begin() as conn:
            # FK checks off so we can seed without a schema-local guild/user row.
            await conn.execute(
                text("SELECT set_config('session_replication_role', 'replica', true)")
            )
            await conn.execute(
                text(
                    f'INSERT INTO "{schema}".guild_ai_connection_keys '
                    "(connection_id, api_key_encrypted) VALUES (1, :a)"
                ),
                {
                    "a": encrypt_field("guild-ai", SALT_AI_API_KEY, secret_key=OLD),
                },
            )
            await conn.execute(
                text(
                    f'INSERT INTO "{schema}".guild_plugin_secrets '
                    "(install_id, secrets) VALUES (1, CAST(:s AS jsonb))"
                ),
                {
                    "s": json.dumps(
                        {
                            connection: {
                                field: encrypt_field(
                                    value, SALT_PLUGIN_CONFIG, secret_key=OLD
                                )
                                for field, value in fields.items()
                            }
                            for connection, fields in plugin_secrets.items()
                        }
                    )
                },
            )

        _use_keys(monkeypatch, old=OLD, new=NEW)
        await rotate_secret_key()

        async with engine.connect() as conn:
            conn_ct = await conn.scalar(
                text(
                    f'SELECT api_key_encrypted FROM "{schema}".guild_ai_connection_keys'
                ),
            )
            sealed = await conn.scalar(
                text(f'SELECT secrets FROM "{schema}".guild_plugin_secrets'),
            )
        assert decrypt_field(conn_ct, SALT_AI_API_KEY, secret_key=NEW) == "guild-ai"
        assert {
            connection: {
                field: decrypt_field(value, SALT_PLUGIN_CONFIG, secret_key=NEW)
                for field, value in fields.items()
            }
            for connection, fields in sealed.items()
        } == plugin_secrets

        # The per-guild sweep routes pooled connections from the guild's
        # cohort; a fresh checkout afterwards runs as the plain system login.
        async with cohorts.system_session(gid) as check:
            conn = await check.connection()
            who = await conn.scalar(text("SELECT current_user"))
            visible = await conn.scalar(text("SELECT count(*) FROM public.guilds"))
        assert who == "app_admin"
        assert visible >= 1
    finally:
        if gid is not None:
            async with engine.begin() as conn:
                await drop_guild_schema(conn, gid)
                await conn.execute(
                    text("DELETE FROM public.guilds WHERE id = :g"), {"g": gid}
                )


@pytest.mark.always
def test_every_encrypted_column_declares_its_salt():
    """A column named ``*_encrypted`` holds Fernet ciphertext, and the rotation
    re-keys every column whose ``info`` declares the salt it is sealed under.
    Each column the name marks as ciphertext, on every table, declares one."""
    undeclared = sorted(
        f"{table.name}.{column.name}"
        for table in SQLModel.metadata.tables.values()
        for column in table.columns
        if column.name.endswith("_encrypted")
        and not isinstance(column.info.get(FERNET_SALT), bytes)
    )
    assert not undeclared, (
        f"encrypted columns declare no FERNET_SALT in their info: {undeclared}"
    )
