from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_STORAGE_KEY


class GuildStorageKey(SQLModel, table=True):
    """The key a community's stored objects are encrypted under, wrapped.

    One row per community, made the first time the community stores something
    while ``STORAGE_ENCRYPTION`` is set (``app.services.storage_keys``). The key
    itself is 32 random bytes and never stored in the clear. It is wrapped by
    the deployment's root, in whichever of the two columns that root fills:

    - ``local_sealed``: the root is ``SECRET_KEY``. Fernet-encrypted with
      ``SALT_STORAGE_KEY`` and registered in the secret-key rotation registry,
      so rotating ``SECRET_KEY`` re-wraps it with the rest.
    - ``kms_sealed`` + ``kms_key``: the root is a Cloud KMS key, which wrapped
      it. Unwrapping it is a call to KMS as the app, written in the project's
      audit log.

    Deleting the row destroys the key, and with it every object the community
    stored encrypted (``deprovision_guild``). The FK cascades for the same
    reason: a community's row going takes its key.

    app_admin-only, like ``user_totp_secrets``: no request role reads a key.
    """

    __tablename__ = "guild_storage_keys"
    __table_args__ = (
        # Exactly one root wrapped it, and a KMS wrap names its key.
        CheckConstraint(
            "(local_sealed IS NULL) <> (kms_sealed IS NULL)",
            name="guild_storage_keys_one_root",
        ),
        CheckConstraint(
            "(kms_sealed IS NULL) = (kms_key IS NULL)",
            name="guild_storage_keys_kms_names_key",
        ),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    #: Which key this is, for the community. Written into every object's
    #: header; a new key (after a suspected compromise) is a new generation.
    generation: int = Field(default=1, sa_column=Column(Integer, nullable=False))

    local_sealed: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True, info={FERNET_SALT: SALT_STORAGE_KEY}),
    )

    kms_sealed: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    #: The KMS key that wrapped ``kms_sealed``: the crypto key, not a version
    #: (KMS reads the version from the ciphertext).
    kms_key: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    #: When the backfill finished encrypting what the community had stored
    #: before encryption was on. ``None`` until then.
    backfilled_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
