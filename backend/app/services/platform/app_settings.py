from __future__ import annotations


import logging

from cryptography.fernet import InvalidToken
from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.transitions import Transition
from app.services import audit as audit_service
from app.core.config import settings as app_config
from app.core.encryption import (
    decrypt_field,
    encrypt_field,
    SALT_PLUGIN_PLATFORM_SIGNING_KEY,
    SALT_CAPTCHA_SECRET_KEY,
    SALT_FCM_SERVICE_ACCOUNT,
    SALT_S3_SECRET_KEY,
    SALT_SMTP_PASSWORD,
)
from app.core.security import use_stored_plugin_platform_signing_key
from app.core.login_methods import (
    DEFAULT_LOGIN_METHODS,
    LOGIN_METHOD_VALUES,
    PRIMARY_LOGIN_METHODS,
    LoginMethod,
)
from app.db import cohorts
from app.db import session as db_session
from app.db.session import guild_context
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.app_setting_secret import AppSettingSecret
from app.models.platform.user_dm_settings import DmPolicy
from app.models.tenant.guild_setting import GuildSetting
from app.services.marketplace import context_jwt
from app.services.platform import guilds as guilds_service
from app.services.platform import rules
from app.db.request_context import SystemGuild

GLOBAL_SETTINGS_ID = 1

logger = logging.getLogger(__name__)


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


async def _ensure_guild_setting(session: AsyncSession, guild_id: int) -> GuildSetting:
    stmt = select(GuildSetting).limit(1)
    result = await session.exec(stmt)
    settings_row = result.one_or_none()
    if settings_row:
        return settings_row
    # A PAM grantee can't write guild_settings (a config table deliberately
    # off-limits to grants), so the lazy INSERT would fault under RLS. Their
    # read is satisfied by a transient default — guild overrides simply don't
    # apply, which is correct for a non-member.
    context = guild_context(session)
    if context is not None and context.grant_content is not None:
        return GuildSetting()
    settings_row = GuildSetting()
    session.add(settings_row)
    # Flushed, not committed: a guild's settings row is normally seeded when the
    # guild is made (``guilds.create_guild_settings``), so getting here means
    # filling a gap in the middle of whatever the caller came to do. The INSERT
    # joins their transaction and lands or unwinds with the rest of it. The two
    # callers that own their transaction commit it themselves.
    await session.flush()
    await session.refresh(settings_row)
    return settings_row


async def get_or_create_guild_settings(
    session: AsyncSession, guild_id: int | None = None
) -> GuildSetting:
    resolved_guild_id = guild_id or await guilds_service.get_primary_guild_id(session)
    return await _ensure_guild_setting(session, resolved_guild_id)


def _seeded_login_methods(*, mail_configured: bool) -> list[str]:
    """The ways in a fresh deployment permits, from ``AUTH_LOGIN_METHODS``.

    First-boot only, like everything else the builder below takes from the
    env: the row is seeded once and Settings owns it from then on. Held to the
    two rules the settings surface enforces on a write — something must be
    able to begin a session, and the emailed code needs somewhere to send
    from — but by falling back rather than refusing: a typo in an env file
    must not hold up boot, and a row the column's CHECK would refuse is a
    deployment nobody can configure. Each fallback says so in the log.
    """
    default = [m.value for m in DEFAULT_LOGIN_METHODS]
    configured = app_config.AUTH_LOGIN_METHODS
    if not configured:
        return default
    resolved = {LoginMethod(v) for v in configured if v in LOGIN_METHOD_VALUES}
    unknown = sorted(set(configured) - {m.value for m in resolved})
    if unknown:
        logger.warning(
            "AUTH_LOGIN_METHODS names %s, which this version does not know; ignored",
            ", ".join(unknown),
        )
    if LoginMethod.email_otp in resolved and not mail_configured:
        logger.warning(
            "AUTH_LOGIN_METHODS permits the emailed code but no mail server is "
            "configured (SMTP_HOST and SMTP_FROM_ADDRESS); left off"
        )
        resolved.discard(LoginMethod.email_otp)
    if not resolved.intersection(PRIMARY_LOGIN_METHODS):
        logger.warning(
            "AUTH_LOGIN_METHODS=%s permits nothing that can begin a session; "
            "keeping the default",
            ",".join(configured),
        )
        return default
    # Sorted, as the settings page stores it.
    return sorted(m.value for m in resolved)


def _build_default_app_settings() -> AppSetting:
    """A fresh, env-seeded ``AppSetting`` singleton (id=1), NOT persisted.

    Shared by the create path (persisted by a writer) and the privilege-tolerant
    read fallback (returned transient to a non-owner caller).
    """
    _smtp_host = _normalize_optional_string(app_config.SMTP_HOST)
    _smtp_from = _normalize_optional_string(app_config.SMTP_FROM_ADDRESS)
    return AppSetting(
        id=GLOBAL_SETTINGS_ID,
        light_accent_color="#2563eb",
        dark_accent_color="#60a5fa",
        login_methods=_seeded_login_methods(
            mail_configured=bool(_smtp_host and _smtp_from)
        ),
        smtp_host=_smtp_host,
        smtp_port=app_config.SMTP_PORT if app_config.SMTP_HOST else None,
        smtp_secure=bool(app_config.SMTP_SECURE),
        smtp_reject_unauthorized=bool(app_config.SMTP_REJECT_UNAUTHORIZED),
        smtp_username=_normalize_optional_string(app_config.SMTP_USERNAME),
        smtp_from_address=_smtp_from,
        smtp_test_recipient=_normalize_optional_string(app_config.SMTP_TEST_RECIPIENT),
        storage_backend=(app_config.STORAGE_BACKEND or "local").lower(),
        s3_bucket=_normalize_optional_string(app_config.S3_BUCKET),
        s3_region=app_config.S3_REGION or "us-east-1",
        s3_endpoint_url=_normalize_optional_string(app_config.S3_ENDPOINT_URL),
        s3_access_key_id=_normalize_optional_string(app_config.S3_ACCESS_KEY_ID),
        s3_use_path_style=bool(app_config.S3_USE_PATH_STYLE),
        s3_local_fallback=bool(app_config.S3_LOCAL_FALLBACK),
        captcha_provider=_normalize_optional_string(app_config.CAPTCHA_PROVIDER),
        captcha_site_key=_normalize_optional_string(app_config.CAPTCHA_SITE_KEY),
        fcm_enabled=bool(app_config.FCM_ENABLED),
        fcm_project_id=_normalize_optional_string(app_config.FCM_PROJECT_ID),
        fcm_application_id=_normalize_optional_string(app_config.FCM_APPLICATION_ID),
        fcm_api_key=_normalize_optional_string(app_config.FCM_API_KEY),
        fcm_sender_id=_normalize_optional_string(app_config.FCM_SENDER_ID),
    )


def _build_default_app_setting_secrets() -> AppSettingSecret:
    """The env-seeded credentials row (id=1), NOT persisted.

    What a settings row created on first boot carries for its credentials:
    the ``SMTP_PASSWORD`` / ``S3_SECRET_ACCESS_KEY`` / ``CAPTCHA_SECRET_KEY`` /
    ``FCM_SERVICE_ACCOUNT_JSON`` env values, encrypted.
    """
    smtp_password = _normalize_optional_string(app_config.SMTP_PASSWORD)
    s3_secret = _normalize_optional_string(app_config.S3_SECRET_ACCESS_KEY)
    captcha_secret = _normalize_optional_string(app_config.CAPTCHA_SECRET_KEY)
    fcm_account = _normalize_optional_string(app_config.FCM_SERVICE_ACCOUNT_JSON)
    return AppSettingSecret(
        id=GLOBAL_SETTINGS_ID,
        smtp_password_encrypted=encrypt_field(smtp_password, SALT_SMTP_PASSWORD)
        if smtp_password
        else None,
        s3_secret_access_key_encrypted=encrypt_field(s3_secret, SALT_S3_SECRET_KEY)
        if s3_secret
        else None,
        captcha_secret_key_encrypted=encrypt_field(
            captcha_secret, SALT_CAPTCHA_SECRET_KEY
        )
        if captcha_secret
        else None,
        fcm_service_account_json_encrypted=encrypt_field(
            fcm_account, SALT_FCM_SERVICE_ACCOUNT
        )
        if fcm_account
        else None,
    )


async def _session_can_write_app_settings(session: AsyncSession) -> bool:
    """Whether the current DB role may WRITE ``app_settings``.

    After Phase 2 ``app_settings`` is owner-only at the GRANT layer (write granted
    only to ``platform_owner`` + the ``app_admin`` engine; revoked from ``app_user``,
    ``platform_base``, and ``app_guild_base``), and that GRANT is the single writer
    gate. Boot asks this before seeding the singleton, so a deployment whose
    system engine cannot write the table serves the env-seeded defaults in
    memory instead of faulting: a failed flush dooms the whole session
    transaction (a SAVEPOINT doesn't isolate one the way it does a plain
    statement). ``has_table_privilege`` respects role inheritance, so it is
    authoritative now that the grant alone gates writes.
    """
    return bool(
        await session.scalar(
            text("SELECT has_table_privilege('app_settings', 'UPDATE')")
        )
    )


async def _session_can_write_app_setting_secrets(session: AsyncSession) -> bool:
    """Whether the current DB role may INSERT into ``app_setting_secrets``.

    The system engine can; every request-path role cannot.
    """
    return bool(
        await session.scalar(
            text("SELECT has_table_privilege('app_setting_secrets', 'INSERT')")
        )
    )


async def _write_app_settings(session: AsyncSession, settings_row: AppSetting) -> None:
    session.add(settings_row)
    await session.commit()
    await session.refresh(settings_row)


async def _stored_app_settings(session: AsyncSession) -> AppSetting | None:
    stmt = select(AppSetting).where(AppSetting.id == GLOBAL_SETTINGS_ID)
    result = await session.exec(stmt)
    return result.one_or_none()


async def _stored_app_setting_secrets(
    session: AsyncSession,
) -> AppSettingSecret | None:
    stmt = select(AppSettingSecret).where(AppSettingSecret.id == GLOBAL_SETTINGS_ID)
    result = await session.exec(stmt)
    return result.one_or_none()


async def get_app_setting_secrets(session: AsyncSession) -> AppSettingSecret:
    """The deployment's stored credentials — a read, on the system engine.

    ``session`` must be a system-engine session: ``app_setting_secrets`` is
    granted to no request-path role. With no row stored yet the env-seeded
    values are served as a value not attached to the session, as
    :func:`get_app_settings` serves its defaults.
    """
    secrets_row = await _stored_app_setting_secrets(session)
    if secrets_row is not None:
        return secrets_row
    return _build_default_app_setting_secrets()


async def load_app_setting_secrets() -> AppSettingSecret:
    """:func:`get_app_setting_secrets` on a system-engine session of its own.

    For readers that hold whatever session their caller runs on — the mailer
    and the storage client — so the credential read never depends on it.
    """
    async with db_session.SystemSessionLocal() as system_session:
        return await get_app_setting_secrets(system_session)


async def _ensure_secrets_row(session: AsyncSession) -> AppSettingSecret:
    """The stored credentials row, put in place (env-seeded) if it is missing.

    System engine only. The settings row it hangs off must already be
    committed. The INSERT joins the caller's transaction; a row another
    connection inserted first is kept rather than overwritten.
    """
    secrets_row = await _stored_app_setting_secrets(session)
    if secrets_row is not None:
        return secrets_row
    defaults = _build_default_app_setting_secrets()
    await session.exec(
        pg_insert(AppSettingSecret.__table__)
        .values(
            {
                column.name: getattr(defaults, column.name)
                for column in AppSettingSecret.__table__.columns
            }
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    secrets_row = await _stored_app_setting_secrets(session)
    if secrets_row is None:  # pragma: no cover - the INSERT landed or conflicted
        raise RuntimeError("app_setting_secrets row could not be created")
    return secrets_row


async def ensure_settings_row(session: AsyncSession) -> AppSetting:
    """The stored singleton, put in place here if boot has not already.

    For callers that are about to write the row or lock it, and so need a
    stored row rather than the transient value a read is served. The INSERT
    joins the caller's transaction and does not end it; a row another
    connection inserted first is kept rather than overwritten.

    The caller must hold write access to the table — every caller does, since
    it is on its way to a write. A read wants :func:`get_app_settings`.
    """
    settings_row = await _stored_app_settings(session)
    if settings_row is not None:
        return settings_row
    defaults = _build_default_app_settings()
    columns = AppSetting.__table__.columns
    await session.exec(
        pg_insert(AppSetting.__table__)
        .values({name: getattr(defaults, name) for name in columns.keys()})
        .on_conflict_do_nothing(index_elements=["id"])
    )
    settings_row = await _stored_app_settings(session)
    if settings_row is None:  # pragma: no cover - the INSERT landed or conflicted
        raise RuntimeError("app_settings singleton could not be created")
    return settings_row


async def locked_settings(session: AsyncSession) -> AppSetting:
    """The settings row, held for the rest of this transaction."""
    await ensure_settings_row(session)
    return (
        await session.exec(
            select(AppSetting)
            .where(AppSetting.id == GLOBAL_SETTINGS_ID)
            .with_for_update()
        )
    ).one()


async def seed_app_settings(session: AsyncSession) -> AppSetting:
    """Create the settings singleton, once, at boot.

    This is the only place the row is created outside a write somebody asked
    for, and it runs on the system engine before any request is served. A
    deployment whose session cannot write the table gets the env-seeded
    defaults in memory and no row, which is what it had before.
    """
    settings_row = await _stored_app_settings(session)
    if settings_row is None:
        if not await _session_can_write_app_settings(session):
            return _build_default_app_settings()
        settings_row = await ensure_settings_row(session)
        await session.commit()
        await session.refresh(settings_row)
    # The credentials row, beside it. Checked separately: a settings row made
    # on another path leaves this one to be put in place here.
    if (
        await _session_can_write_app_setting_secrets(session)
        and await _stored_app_setting_secrets(session) is None
    ):
        await _ensure_secrets_row(session)
        await session.commit()
    return settings_row


async def load_plugin_platform_signing_key(session: AsyncSession) -> None:
    """Load the plug-in platform's stored signing key into this process.

    Only while ``PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM`` is unset; the env key
    is used as it is. The first start generates a key and stores it, and every
    start after it, on any replica, loads that one: the write only fills an
    empty column, and the key is read back from the row. A key stored before
    the platform key became Ed25519 is RSA, and is replaced once, the same
    way: the write only lands over the value it read. System engine only,
    after :func:`seed_app_settings`. Commits.
    """
    if app_config.PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM:
        return
    column = AppSettingSecret.__table__.c.plugin_platform_signing_key_encrypted
    stored_query = select(column).where(
        AppSettingSecret.__table__.c.id == GLOBAL_SETTINGS_ID
    )
    encrypted = await session.scalar(stored_query)
    if encrypted is None:
        if await _stored_app_settings(session) is None:
            logger.warning(
                "plug-in platform: the settings row is not stored, so no signing "
                "key can be kept; plug-in services stay unavailable."
            )
            return
        await _ensure_secrets_row(session)
        await session.exec(
            update(AppSettingSecret.__table__)
            .where(
                AppSettingSecret.__table__.c.id == GLOBAL_SETTINGS_ID,
                column.is_(None),
            )
            .values(
                {
                    column: encrypt_field(
                        context_jwt.generate_signing_key(),
                        SALT_PLUGIN_PLATFORM_SIGNING_KEY,
                    )
                }
            )
        )
        await session.commit()
        encrypted = await session.scalar(stored_query)
        if encrypted is None:  # pragma: no cover - the UPDATE landed or lost a race
            raise RuntimeError("plug-in platform signing key could not be stored")
    try:
        private_pem = decrypt_field(encrypted, SALT_PLUGIN_PLATFORM_SIGNING_KEY)
    except InvalidToken:
        logger.error(
            "plug-in platform: the stored signing key does not decrypt under "
            "SECRET_KEY; plug-in services stay unavailable. Set PREVIOUS_SECRET_KEY "
            "to the key it was stored under."
        )
        return
    if not context_jwt.is_platform_key(private_pem):
        await session.exec(
            update(AppSettingSecret.__table__)
            .where(
                AppSettingSecret.__table__.c.id == GLOBAL_SETTINGS_ID,
                column == encrypted,
            )
            .values(
                {
                    column: encrypt_field(
                        context_jwt.generate_signing_key(),
                        SALT_PLUGIN_PLATFORM_SIGNING_KEY,
                    )
                }
            )
        )
        await session.commit()
        logger.warning(
            "plug-in platform: replaced the stored RSA signing key with an Ed25519 one"
        )
        private_pem = decrypt_field(
            await session.scalar(stored_query), SALT_PLUGIN_PLATFORM_SIGNING_KEY
        )
    use_stored_plugin_platform_signing_key(
        private_pem, context_jwt.key_thumbprint(private_pem)
    )


async def record_running_version(
    session: AsyncSession,
    *,
    version: str,
    transitions: Sequence[str] = (),
    demo_mode: bool = False,
) -> str | None:
    """Roll the deployment's version pair forward, and say what it was before.
    Also records whether it runs as the demo (``DEMO_MODE``), which the
    database reads where a guest's rung is decided.

    Called once at boot. When the running version differs from what was last
    recorded, the old value becomes ``previous_version`` — which is what tells
    a notice meant for people upgrading past some release whether this
    deployment is one of them. A fresh install has neither, and that is the
    honest answer: it never upgraded from anything.

    Idempotent across restarts on the same version: the pair only moves when
    the running version actually changed. Each of ``transitions`` not yet
    dated is dated now (see ``app.core.transitions``).
    """
    if not await _session_can_write_app_settings(session):
        return (await get_app_settings(session)).previous_version
    settings_row = await ensure_settings_row(session)
    now = datetime.now(timezone.utc).isoformat()
    started = {
        name: now for name in transitions if name not in settings_row.transitions
    }
    # The demo's visitors are guests of their copies.
    guests_off = (
        demo_mode and not (await rules.platform_values(session))["guests_enabled"]
    )
    if (
        settings_row.last_seen_version == version
        and not started
        and settings_row.demo_mode == demo_mode
        and not guests_off
    ):
        return settings_row.previous_version
    settings_row.demo_mode = demo_mode
    if guests_off:
        await rules.put(session, "guests_enabled", True)
    if started:
        settings_row.transitions = {**settings_row.transitions, **started}
    if settings_row.last_seen_version != version:
        settings_row.previous_version = settings_row.last_seen_version
        settings_row.last_seen_version = version
    await _write_app_settings(session, settings_row)
    return settings_row.previous_version


async def transition_over(session: AsyncSession, transition: Transition) -> bool:
    """Whether ``transition``'s grace period has run out on this deployment."""
    started = (await get_app_settings(session)).transitions.get(transition.name)
    return started is not None and (
        datetime.fromisoformat(started) + transition.grace < datetime.now(timezone.utc)
    )


async def previous_running_version(session: AsyncSession) -> str | None:
    """What this deployment was running before its current version, if anything."""
    return (await get_app_settings(session)).previous_version


async def get_app_settings(session: AsyncSession) -> AppSetting:
    """What this deployment's configuration says — a read, and only a read.

    Boot puts the singleton in place (:func:`seed_app_settings`). Until it has,
    or where it could not, the caller is served the env-seeded defaults as a
    value that is not attached to the session: reading configuration writes
    nothing, and so never ends the transaction of whoever asked.

    An existing row is served as-is — env values seed a *new* row once
    (``_build_default_app_settings``); after that the database is
    authoritative. (The OIDC env values seed the platform provider registry row
    instead — see ``platform_provider.seed_platform_provider_from_env``.)
    """
    settings_row = await _stored_app_settings(session)
    if settings_row is not None:
        return settings_row
    return _build_default_app_settings()


# Which columns of the settings singleton each area of the owner's settings
# page can move. A record names the ones that actually moved; a value rides
# along only where its type rules out a secret.
INTERFACE_FIELDS: tuple[str, ...] = ("light_accent_color", "dark_accent_color")
COMMUNITY_FIELDS: tuple[str, ...] = ("default_dm_policy",)
EMAIL_FIELDS: tuple[str, ...] = (
    "smtp_host",
    "smtp_port",
    "smtp_secure",
    "smtp_reject_unauthorized",
    "smtp_username",
    "smtp_from_address",
    "smtp_test_recipient",
)
#: The credential each of those areas keeps on ``app_setting_secrets``. Named in
#: a record like any other field when it moves; its value never is.
EMAIL_SECRET_FIELD = "smtp_password_encrypted"
STORAGE_SECRET_FIELD = "s3_secret_access_key_encrypted"
STORAGE_FIELDS: tuple[str, ...] = (
    "storage_backend",
    "s3_bucket",
    "s3_region",
    "s3_endpoint_url",
    "s3_access_key_id",
    "s3_use_path_style",
    "s3_local_fallback",
)
CAPTCHA_SECRET_FIELD = "captcha_secret_key_encrypted"
CAPTCHA_FIELDS: tuple[str, ...] = (
    "captcha_provider",
    "captcha_site_key",
)
PUSH_SECRET_FIELD = "fcm_service_account_json_encrypted"
PUSH_FIELDS: tuple[str, ...] = (
    "fcm_enabled",
    "fcm_project_id",
    "fcm_application_id",
    "fcm_api_key",
    "fcm_sender_id",
)


@dataclass(frozen=True)
class _SecretChange:
    """An area's credential column: the stored row, and what this save leaves."""

    row: AppSettingSecret
    field: str
    stored: str | None
    new: str | None
    provided: bool


async def _secret_change(
    system_session: AsyncSession,
    *,
    field: str,
    salt: str,
    value: str | None,
    provided: bool,
) -> _SecretChange:
    """Read the area's stored credential and encrypt the one being saved.

    Left as stored unless ``provided``; a provided blank clears it.
    """
    row = await get_app_setting_secrets(system_session)
    stored = new = getattr(row, field)
    if provided:
        normalized = _normalize_optional_string(value)
        new = encrypt_field(normalized, salt) if normalized else None
    return _SecretChange(row, field, stored, new, provided)


@asynccontextmanager
async def _settings_area(
    session: AsyncSession,
    *,
    area: str,
    fields: tuple[str, ...],
    actor_user_id: int | None,
    secret: _SecretChange | None = None,
    commit: bool = True,
) -> AsyncIterator[AppSetting]:
    """Save one area of the settings row with its record, in one commit.

    Yields the stored row for the caller to change. On leaving, the fields
    that moved are recorded and the row is committed, or with ``commit``
    off staged for the caller's own commit. ``secret`` is the
    area's credential: named in the record when it moves, never valued, and
    stored afterwards by :func:`_store_secret`, once the row it hangs off is
    committed.
    """
    row = await ensure_settings_row(session)
    before = audit_service.snapshot(row, fields)
    yield row
    session.add(row)
    after = audit_service.snapshot(row, fields)
    extras = None
    if secret is not None:
        before[secret.field] = secret.stored
        after[secret.field] = secret.new
        extras = {"secret_changed": secret.stored != secret.new}
    await audit_service.record_settings_change(
        session,
        guild_id=None,
        actor_user_id=actor_user_id,
        area=area,
        before=before,
        after=after,
        extras=extras,
    )
    if not commit:
        await session.flush()
        return
    await session.commit()
    await session.refresh(row)


async def _store_secret(
    system_session: AsyncSession, secret: _SecretChange
) -> AppSettingSecret:
    """Store the area's credential on the system engine when it was provided,
    and return the credentials row as it now stands."""
    if not secret.provided:
        return secret.row
    secrets_row = await _ensure_secrets_row(system_session)
    setattr(secrets_row, secret.field, secret.new)
    system_session.add(secrets_row)
    await system_session.commit()
    return await get_app_setting_secrets(system_session)


async def update_interface_settings(
    session: AsyncSession,
    *,
    light_accent_color: str,
    dark_accent_color: str,
    actor_user_id: int | None = None,
) -> None:
    """The two accent colours, staged for the caller's commit: the page saves
    them with its rule in one change (``auth_posture.change``)."""
    async with _settings_area(
        session,
        area="interface",
        fields=INTERFACE_FIELDS,
        actor_user_id=actor_user_id,
        commit=False,
    ) as settings_row:
        settings_row.light_accent_color = light_accent_color.strip() or "#2563eb"
        settings_row.dark_accent_color = dark_accent_color.strip() or "#60a5fa"


async def community_directory_enabled(session: AsyncSession) -> bool:
    """Whether the platform owner has the community directory switched on.

    The one read of the switch. Everything the directory consists of — browsing
    it, joining from it, and a guild listing itself in it — asks this first, so
    turning it off closes all three at once.
    """
    return (await rules.platform_values(session))["community_directory_enabled"]


async def community_age_gate_enabled(session: AsyncSession) -> bool:
    """Whether this deployment checks age. Off, every account counts as an adult.

    The one read of the switch, for the same reason
    :func:`community_directory_enabled` is: every place that asks — sign-up,
    the directory's join, the standing check at a listed guild's door, a
    plug-in's minimum age and the direct-message policy — must agree at every
    moment. The direct-message rule in the database (``dm_reachable``) reads
    the same rule.
    """
    return (await rules.platform_values(session))["community_age_gate_enabled"]


async def direct_messages_enabled(session: AsyncSession) -> bool:
    """Whether this deployment offers direct messages at all.

    The one read of the switch. Every direct-message endpoint is gated on it,
    and so is the roster of people My Contacts says you could reach, so turning
    it off closes the feature and everything that advertises it at once.
    """
    return (await rules.platform_values(session))["direct_messages_enabled"]


async def marketplace_members_publish_directly(session: AsyncSession) -> bool:
    """Whether a member's share to the marketplace skips the owner's review.

    The one read of the switch, taken when a share is submitted: a version
    submitted while it was off keeps waiting after it is turned on.
    """
    return (await rules.platform_values(session))[
        "marketplace_members_publish_directly"
    ]


async def marketplace_registry_enabled(session: AsyncSession) -> bool:
    """Whether this deployment follows the marketplace registry.

    The one read of the switch: the background refresh and the "refresh now"
    button both ask it before fetching anything.
    """
    return (await rules.platform_values(session))["marketplace_registry_enabled"]


async def update_community_settings(
    session: AsyncSession,
    *,
    default_dm_policy: "DmPolicy",
    actor_user_id: int | None = None,
) -> None:
    """The direct-message policy a newly created account starts on, staged
    for the caller's commit: the page saves it with its rules in one change.

    Read once, when an account is made. Changing it moves no existing account:
    raising it would open accounts that never chose to be open, and lowering
    it would revoke channels people are using.
    """
    async with _settings_area(
        session,
        area="community",
        fields=COMMUNITY_FIELDS,
        actor_user_id=actor_user_id,
        commit=False,
    ) as settings_row:
        settings_row.default_dm_policy = default_dm_policy


async def update_email_settings(
    session: AsyncSession,
    *,
    system_session: AsyncSession,
    host: str | None,
    port: int | None,
    secure: bool,
    reject_unauthorized: bool,
    username: str | None,
    password: str | None,
    password_provided: bool,
    from_address: str | None,
    test_recipient: str | None,
    actor_user_id: int | None = None,
) -> tuple[AppSetting, AppSettingSecret]:
    """Save the mail settings; the password on ``system_session``.

    ``session`` writes the settings row (under the owner's tier) and
    ``system_session`` — the system engine — the password. The settings row and
    its record commit first, then the password: the credentials row hangs off
    the settings row, and a password is never stored without the save it came
    with. Returns both rows.
    """
    secret = await _secret_change(
        system_session,
        field=EMAIL_SECRET_FIELD,
        salt=SALT_SMTP_PASSWORD,
        value=password,
        provided=password_provided,
    )
    async with _settings_area(
        session,
        area="email",
        fields=EMAIL_FIELDS,
        actor_user_id=actor_user_id,
        secret=secret,
    ) as settings_row:
        settings_row.smtp_host = _normalize_optional_string(host)
        settings_row.smtp_port = port if port else None
        settings_row.smtp_secure = bool(secure)
        settings_row.smtp_reject_unauthorized = bool(reject_unauthorized)
        settings_row.smtp_username = _normalize_optional_string(username)
        settings_row.smtp_from_address = _normalize_optional_string(from_address)
        settings_row.smtp_test_recipient = _normalize_optional_string(test_recipient)
    return settings_row, await _store_secret(system_session, secret)


async def update_storage_settings(
    session: AsyncSession,
    *,
    system_session: AsyncSession,
    backend: str,
    s3_bucket: str | None,
    s3_region: str | None,
    s3_endpoint_url: str | None,
    s3_access_key_id: str | None,
    s3_secret_access_key: str | None,
    secret_provided: bool,
    s3_use_path_style: bool,
    s3_local_fallback: bool,
    actor_user_id: int | None = None,
) -> tuple[AppSetting, AppSettingSecret]:
    """Save the storage settings; the secret key on ``system_session``.

    Written in the order :func:`update_email_settings` writes: the settings
    row and its record, then the secret key on the system engine, then the
    process-wide storage config is reloaded. Returns both rows.
    """
    secret = await _secret_change(
        system_session,
        field=STORAGE_SECRET_FIELD,
        salt=SALT_S3_SECRET_KEY,
        value=s3_secret_access_key,
        provided=secret_provided,
    )
    async with _settings_area(
        session,
        area="storage",
        fields=STORAGE_FIELDS,
        actor_user_id=actor_user_id,
        secret=secret,
    ) as settings_row:
        settings_row.storage_backend = (backend or "local").lower()
        settings_row.s3_bucket = _normalize_optional_string(s3_bucket)
        settings_row.s3_region = (s3_region or "us-east-1").strip() or "us-east-1"
        settings_row.s3_endpoint_url = _normalize_optional_string(s3_endpoint_url)
        settings_row.s3_access_key_id = _normalize_optional_string(s3_access_key_id)
        settings_row.s3_use_path_style = bool(s3_use_path_style)
        settings_row.s3_local_fallback = bool(s3_local_fallback)
    secrets_row = await _store_secret(system_session, secret)
    # Refresh the process-wide resolved storage config so the live request path
    # picks up new creds/backend immediately (lazy import avoids a cycle: the
    # storage_config module reads get_app_settings from here).
    from app.services import storage_config

    await storage_config.refresh_storage_config(session)
    return settings_row, secrets_row


async def update_captcha_settings(
    session: AsyncSession,
    *,
    system_session: AsyncSession,
    provider: str | None,
    site_key: str | None,
    secret_key: str | None,
    secret_provided: bool,
    actor_user_id: int | None = None,
) -> tuple[AppSetting, AppSettingSecret]:
    """Save the captcha settings; the verification secret on ``system_session``.

    The order :func:`update_storage_settings` writes in: the settings row and
    its record, then the secret on the system engine, then the process-wide
    resolved config, so the next registration verifies against what was just
    saved rather than what was saved at boot.
    """
    secret = await _secret_change(
        system_session,
        field=CAPTCHA_SECRET_FIELD,
        salt=SALT_CAPTCHA_SECRET_KEY,
        value=secret_key,
        provided=secret_provided,
    )
    async with _settings_area(
        session,
        area="captcha",
        fields=CAPTCHA_FIELDS,
        actor_user_id=actor_user_id,
        secret=secret,
    ) as settings_row:
        settings_row.captcha_provider = _normalize_optional_string(provider)
        settings_row.captcha_site_key = _normalize_optional_string(site_key)
    secrets_row = await _store_secret(system_session, secret)
    from app.services import captcha_config

    await captcha_config.refresh_captcha_config(session)
    return settings_row, secrets_row


async def update_push_settings(
    session: AsyncSession,
    *,
    system_session: AsyncSession,
    enabled: bool,
    project_id: str | None,
    application_id: str | None,
    api_key: str | None,
    sender_id: str | None,
    service_account_json: str | None,
    secret_provided: bool,
    actor_user_id: int | None = None,
) -> tuple[AppSetting, AppSettingSecret]:
    """Save the push settings; the service-account JSON on ``system_session``.

    Same order and the same reasons as :func:`update_captcha_settings`.
    """
    secret = await _secret_change(
        system_session,
        field=PUSH_SECRET_FIELD,
        salt=SALT_FCM_SERVICE_ACCOUNT,
        value=service_account_json,
        provided=secret_provided,
    )
    async with _settings_area(
        session,
        area="push",
        fields=PUSH_FIELDS,
        actor_user_id=actor_user_id,
        secret=secret,
    ) as settings_row:
        settings_row.fcm_enabled = bool(enabled)
        settings_row.fcm_project_id = _normalize_optional_string(project_id)
        settings_row.fcm_application_id = _normalize_optional_string(application_id)
        settings_row.fcm_api_key = _normalize_optional_string(api_key)
        settings_row.fcm_sender_id = _normalize_optional_string(sender_id)
    secrets_row = await _store_secret(system_session, secret)
    from app.services.platform import push_config

    await push_config.refresh_push_config(session)
    return settings_row, secrets_row


async def ensure_defaults(session: AsyncSession) -> None:
    await seed_app_settings(session)
    primary_guild_id = await guilds_service.get_primary_guild_id(session)
    # guild_settings lives only in the guild schema, so it is seeded on a
    # system session from the primary guild's cohort, routed into it.
    async with cohorts.system_session(primary_guild_id) as guild_session:
        await set_rls_context(guild_session, SystemGuild(primary_guild_id))
        await _ensure_guild_setting(guild_session, primary_guild_id)
        await guild_session.commit()
