import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlmodel import Field, SQLModel


class HeldChangeKind(str, Enum):
    """The changes to how an account is signed into that can wait."""

    primary = "primary"
    remove_address = "remove_address"
    second_factor_off = "second_factor_off"
    last_passkey = "last_passkey"


class AccountChangeHold(SQLModel, table=True):
    """A change to the account that waits before it is made.

    Pending while neither ``cancelled_at`` nor ``applied_at`` is set; an
    account has one pending at a time. ``address_id`` or ``passkey_id`` names
    what it changes, and the hold goes with that row.

    ``app_admin``-only, like the session and credential rows it acts on.
    """

    __tablename__ = "account_change_holds"
    __table_args__ = (
        Index(
            "uq_account_change_holds_pending",
            "user_id",
            unique=True,
            postgresql_where=text("cancelled_at IS NULL AND applied_at IS NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        )
    )
    kind: HeldChangeKind = Field(sa_column=Column(String(32), nullable=False))
    address_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("user_emails.id", ondelete="CASCADE"), nullable=True
        ),
    )
    passkey_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            Uuid, ForeignKey("user_passkeys.id", ondelete="CASCADE"), nullable=True
        ),
    )
    # The sign-in that asked for it, which a change ending other sessions
    # leaves signed in.
    session_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(
            Uuid, ForeignKey("auth_sessions.id", ondelete="SET NULL"), nullable=True
        ),
    )
    requested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    applies_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    cancelled_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    applied_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
