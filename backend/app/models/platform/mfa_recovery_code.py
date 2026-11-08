from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel


class MfaRecoveryCode(SQLModel, table=True):
    """One unused way back into an account whose factor is out of reach.

    Named ``mfa_`` rather than ``totp_`` because a code here answers for the
    account's second factor whatever that factor is: passkeys issue against the
    same table rather than bringing a second one.

    Codes are minted as a set, handed over once, and stored only as a SHA-256
    digest — the same treatment as a refresh token, and for the same reason:
    the value is ours and already full-entropy, so a deterministic hash keeps
    the lookup a single indexed one. ``used_at`` is what makes a code single
    use.

    app_admin-only: a code is presented while signing in, before there is
    anybody to scope a policy to.
    """

    __tablename__ = "mfa_recovery_codes"
    # One code is one row. Its index leads with user_id, which is also how an
    # account's codes are read, so there is no separate index on that column.
    __table_args__ = (
        UniqueConstraint(
            "user_id", "code_hash", name="uq_mfa_recovery_codes_user_code"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )

    code_hash: bytes = Field(sa_column=Column(LargeBinary, nullable=False))

    used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
