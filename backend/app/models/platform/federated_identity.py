from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel


class FederatedIdentity(SQLModel, table=True):
    """A link between one global Initiative user and one external identity.

    Identity is keyed on ``(provider_id, subject)`` — the IdP ``sub``; email is
    a display attribute, never a join key. One user may have many linked
    identities (a work SSO, a personal passkey provider, …); the user row stays
    Initiative's system of record.

    Own-row RLS: a user sees/manages only their own links on the request path —
    there is **no** staff read-all policy. Cross-user identity management (support)
    runs on the system engine (``app_admin``), never a platform-tier request role,
    so a support UI must not assume request-path access here. The IdP refresh token
    (for group re-sync) lives in the companion ``federated_identity_secrets``.
    """

    __tablename__ = "federated_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "subject", name="uq_federated_identities_provider_subject"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    provider_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )

    # The IdP-asserted subject identifier — the stable join key.
    subject: str = Field(sa_column=Column(Text, nullable=False))

    # Whether the IdP asserted a verified email at link time (a snapshot used for
    # the linking-safety check, not a join key). The email itself is not stored
    # here — identity is resolved by (provider, subject).
    email_verified: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_login_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # When the background group re-sync (or a login, which also syncs) last ran
    # for this link — the due-date the re-sync sweep filters on.
    last_synced_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
