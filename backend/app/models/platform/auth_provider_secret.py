from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_OIDC_CLIENT_SECRET


class AuthProviderSecret(SQLModel, table=True):
    """The client secret for one auth provider — kept OUT of ``auth_providers``.

    A companion table read and written only by the system engine. Provider
    metadata (``issuer``/``client_id`` — public in OIDC) stays on
    ``auth_providers``; only the secret lives here.

    1:1 with the provider — ``provider_id`` is the PK and an FK to
    ``auth_providers.id`` (``ON DELETE CASCADE``).
    ``client_secret_encrypted`` is Fernet-encrypted at rest with
    ``SALT_OIDC_CLIENT_SECRET`` (declared on the column for the SECRET_KEY rotation);
    it is ``NULL`` for public / PKCE-only providers with no secret.
    """

    __tablename__ = "auth_provider_secrets"

    provider_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    client_secret_encrypted: str | None = Field(
        default=None,
        sa_column=Column(
            Text, nullable=True, info={FERNET_SALT: SALT_OIDC_CLIENT_SECRET}
        ),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        # onupdate (Python-side, no DDL) so secret rotation via the provider-CRUD
        # service bumps this without the endpoint having to remember.
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(UTC),
        ),
    )
