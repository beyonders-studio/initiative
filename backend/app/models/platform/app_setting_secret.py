from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, text
from sqlmodel import Field, SQLModel

from app.core.encryption import (
    FERNET_SALT,
    SALT_CAPTCHA_SECRET_KEY,
    SALT_FCM_SERVICE_ACCOUNT,
    SALT_PLUGIN_PLATFORM_SIGNING_KEY,
    SALT_PUSH_RELAY_KEY,
    SALT_S3_SECRET_KEY,
    SALT_SMTP_PASSWORD,
)


class AppSettingSecret(SQLModel, table=True):
    """The deployment's stored credentials — kept OUT of ``app_settings``.

    A companion to the settings singleton, read and written only by the system
    engine. The settings row carries everything the settings pages show; this
    row carries the credentials they only report as set or not set, and the
    plug-in platform's generated signing key, which they do not show at all.

    1:1 with the singleton — ``id`` is the PK and an FK to ``app_settings.id``
    (``ON DELETE CASCADE``), so it is ``1`` like the row it belongs to. Each
    column is Fernet-encrypted at rest with its own salt (declared on the
    column for the SECRET_KEY rotation) and ``NULL`` when no credential is stored.

    No row means none has been stored yet: readers are served the env-seeded
    values, as a settings row created on first boot would have carried them.
    """

    __tablename__ = "app_setting_secrets"

    id: int = Field(
        default=1,
        sa_column=Column(
            Integer,
            ForeignKey("app_settings.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
    )

    # The SMTP password (``SALT_SMTP_PASSWORD``).
    smtp_password_encrypted: str | None = Field(
        default=None,
        sa_column=Column(
            String(2000), nullable=True, info={FERNET_SALT: SALT_SMTP_PASSWORD}
        ),
    )

    # The S3 secret access key (``SALT_S3_SECRET_KEY``).
    s3_secret_access_key_encrypted: str | None = Field(
        default=None,
        sa_column=Column(
            String(2000), nullable=True, info={FERNET_SALT: SALT_S3_SECRET_KEY}
        ),
    )

    # The captcha provider's server-side verification secret
    # (``SALT_CAPTCHA_SECRET_KEY``).
    captcha_secret_key_encrypted: str | None = Field(
        default=None,
        sa_column=Column(
            String(2000), nullable=True, info={FERNET_SALT: SALT_CAPTCHA_SECRET_KEY}
        ),
    )

    # The FCM service-account JSON (``SALT_FCM_SERVICE_ACCOUNT``).
    #
    # Wider than its neighbours because the plaintext is a whole JSON document
    # -- a Google service account is around 2.4 kB, which Fernet takes to
    # roughly 3.3 kB of base64, past the 2000 the columns above are sized for.
    # Storing it truncated would fail at `json.loads` on the next push, a long
    # way from the settings page that accepted it.
    fcm_service_account_json_encrypted: str | None = Field(
        default=None,
        sa_column=Column(
            String(8000), nullable=True, info={FERNET_SALT: SALT_FCM_SERVICE_ACCOUNT}
        ),
    )

    # The plug-in platform's signing key as a PEM
    # (``SALT_PLUGIN_PLATFORM_SIGNING_KEY``): generated at the first start that
    # finds PLUGIN_PLATFORM_SIGNING_PRIVATE_KEY_PEM unset, and read by every
    # process after it. Never shown on a settings page.
    plugin_platform_signing_key_encrypted: str | None = Field(
        default=None,
        sa_column=Column(
            String(4000),
            nullable=True,
            info={FERNET_SALT: SALT_PLUGIN_PLATFORM_SIGNING_KEY},
        ),
    )

    # This server's registration with the push relay: its id, which is not a
    # secret, and its key (``SALT_PUSH_RELAY_KEY``). Written by the first push
    # that goes through the relay, and cleared when the relay no longer knows
    # the key, so the next push registers again.
    push_relay_server_id: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    push_relay_key_encrypted: str | None = Field(
        default=None,
        sa_column=Column(
            String(2000), nullable=True, info={FERNET_SALT: SALT_PUSH_RELAY_KEY}
        ),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=text("now()"),
            onupdate=lambda: datetime.now(UTC),
        ),
    )
