from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_OIDC_REFRESH_TOKEN


class FederatedIdentitySecret(SQLModel, table=True):
    """The IdP refresh token for one federated identity.

    A companion table to ``federated_identities`` (the ``auth_provider_secrets``
    pattern): link metadata stays on the main table, the token lives here and is
    read and written only by the system engine.

    1:1 with the identity link — ``identity_id`` is the PK and an FK to
    ``federated_identities.id`` (``ON DELETE CASCADE``).
    ``refresh_token_encrypted`` is Fernet-encrypted at rest under the salt
    its column declares for the SECRET_KEY rotation; it is ``NULL`` when the IdP
    issued no refresh token or the token was revoked.
    """

    __tablename__ = "federated_identity_secrets"

    identity_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("federated_identities.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    refresh_token_encrypted: str | None = Field(
        default=None,
        sa_column=Column(
            Text, nullable=True, info={FERNET_SALT: SALT_OIDC_REFRESH_TOKEN}
        ),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        # onupdate (Python-side, no DDL) so token rotation in the background
        # re-sync bumps this without the caller having to remember.
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            onupdate=lambda: datetime.now(UTC),
        ),
    )
