"""Which providers have asserted an address, and when they last did.

An address is one row in ``user_emails``; the providers that assert it are
many. A contractor at two organisations signs into both with one address, and
each organisation's directory asserts it independently — so this is its own
table rather than a column, and neither assertion displaces the other.

An address nobody asserted has no rows here at all: somebody typed it, and the
synthetic ``{subject}@oidc.local`` placeholder minted when a provider supplies
no email claim is invented rather than asserted.

**app_admin-only**, like ``user_emails`` itself.
"""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlmodel import Field, Index, SQLModel


class UserEmailAssertion(SQLModel, table=True):
    """One provider's standing claim that an account holds an address."""

    __tablename__ = "user_email_assertions"
    __table_args__ = (
        # The addresses one provider asserts — the per-guild read's direction.
        Index("ix_user_email_assertions_provider_id", "provider_id"),
    )

    user_email_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("user_emails.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    # CASCADE, not SET NULL: the row *is* the assertion, so a provider that no
    # longer exists has no standing claim. The address itself stays.
    provider_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("auth_providers.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    first_asserted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Refreshed on every sign-in that carries the claim, so a directory that
    # has stopped asserting an address is visible as a stale one.
    last_asserted_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
