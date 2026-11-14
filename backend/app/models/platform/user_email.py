"""An address an account can be reached at and sign in with.

One account, many addresses — the shape GitHub uses. ``users.email_hash`` /
``email_encrypted`` hold the one address an account was created with; this
table holds every address it has, with the same two representations: a keyed
HMAC for equality lookups and a Fernet ciphertext for reading it back.

**app_admin-only.** Resolving an address to an account is a pre-auth lookup —
the user is unknown until it returns — so it structurally cannot run under
own-row RLS, exactly like ``auth_sessions``. The schema-default request-path
DML is REVOKEd in the migration.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlmodel import Field, Index, SQLModel

from app.core.encryption import EMAIL_HASH_COLUMN, FERNET_SALT, SALT_EMAIL


class UserEmail(SQLModel, table=True):
    """One address belonging to one account."""

    __tablename__ = "user_emails"
    __table_args__ = (
        # An address belongs to one account once it has been proven. An
        # unproven row is a claim in progress: two accounts may each hold one
        # for the same address, and proving it settles which.
        Index("ix_user_emails_email_hash", "email_hash"),
        Index(
            "uq_user_emails_proven_hash",
            "email_hash",
            unique=True,
            postgresql_where=text("verified_at IS NOT NULL"),
        ),
        Index("ix_user_emails_user_id", "user_id"),
        # One primary per account, as a partial unique index rather than a
        # pointer on ``users`` — no nullable column and no circular foreign key.
        Index(
            "uq_user_emails_one_primary",
            "user_id",
            unique=True,
            postgresql_where=text("is_primary"),
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

    # Keyed HMAC of the normalised address (app.core.encryption.hash_email) —
    # what an equality lookup and the unique constraint run on.
    email_hash: str = Field(sa_column=Column(String(64), nullable=False))
    # Fernet ciphertext under SALT_EMAIL. Re-keyed with email_hash, in the
    # same statement, so the hash and the ciphertext never disagree.
    email_encrypted: str = Field(
        sa_column=Column(
            String(2000),
            nullable=False,
            info={FERNET_SALT: SALT_EMAIL, EMAIL_HASH_COLUMN: "email_hash"},
        )
    )

    # When the holder proved they hold it. NULL means unproven.
    verified_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # The address that receives account mail. Exactly one per account.
    #
    # Not constrained to a verified address: accounts predating this table may
    # never have verified the one they signed up with, and they still receive
    # mail there. "You cannot move your primary to an address you have not
    # proved you hold" is a rule about the change, and it lives in the code
    # that makes the change.
    is_primary: bool = Field(
        sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    # signup | added | oidc | synthetic — a note for whoever reads the row, not an
    # enum column, so a new way to acquire an address needs no migration.
    source: str = Field(sa_column=Column(Text, nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # Last time a sign-in resolved through this address, for the account page
    # and for telling a stale address from one in use.
    last_login_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
