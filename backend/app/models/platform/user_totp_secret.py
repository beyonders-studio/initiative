from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_TOTP_SECRET


class UserTotpSecret(SQLModel, table=True):
    """The shared secret behind one account's authenticator factor.

    A companion table to ``user_totp``, following ``auth_provider_secrets`` and
    ``federated_identity_secrets``: read and written only by the system engine.

    1:1 with the factor — ``user_id`` is the PK and an FK to
    ``user_totp.user_id`` (``ON DELETE CASCADE``), so removing the factor takes
    the secret with it. ``secret_encrypted`` is the base32 seed, Fernet-encrypted
    at rest with ``SALT_TOTP_SECRET`` and registered in the secret-key rotation
    registry. It is handed out once, while enrolling, and has no read-back path
    afterwards.
    """

    __tablename__ = "user_totp_secrets"

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("user_totp.user_id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    secret_encrypted: str = Field(
        sa_column=Column(Text, nullable=False, info={FERNET_SALT: SALT_TOTP_SECRET})
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(UTC),
        ),
    )
