import uuid as uuid_module
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_EMAIL


class AuthChallenge(SQLModel, table=True):
    """A sign-in that has proved one thing and is waiting on the next.

    Between a correct password and an accepted code there is a moment that has
    to be carried across two requests. It is carried here rather than in
    ``auth_sessions``, where every row means somebody is signed in.
    ``consumed_at`` spends the challenge, ``attempts`` counts refused answers
    against it, ``expires_at`` ends it, and a password change or a factor being
    removed deletes it.

    ``challenge_hash`` is SHA-256 of the value handed to the client, following
    ``auth_sessions.refresh_token_hash``. The raw value exists once, in the
    response that issues it.

    ``purpose`` names what the challenge is for, so passkeys and step-up reuse
    the table instead of adding one.
    """

    __tablename__ = "auth_challenges"

    id: uuid_module.UUID | None = Field(
        default_factory=uuid_module.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )

    challenge_hash: bytes = Field(
        sa_column=Column(LargeBinary, nullable=False, unique=True)
    )

    #: The account the challenge belongs to, where one is known. A passkey
    #: sign-in begins from the credential rather than from an address, so the
    #: account is named by the assertion that answers rather than by the row.
    user_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )

    purpose: str = Field(sa_column=Column(Text, nullable=False))

    #: The answer this challenge is waiting for, where that is not the value it
    #: was issued under. A code sent by mail hands out two things — a handle to
    #: the browser and the code to the mailbox — so the handle stays in
    #: ``challenge_hash``, where the lookup and the attempt count are one
    #: statement, and the code is kept here. ``NULL`` wherever presenting the
    #: issued value is itself the proof.
    answer_hash: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )

    #: The address a challenge names when no account holds it yet — a code
    #: sent to somebody signing up. Fernet ciphertext under ``SALT_EMAIL``,
    #: the way ``user_emails`` keeps one, so an address waiting on a sign-up
    #: is stored no differently from one already held.
    email_encrypted: str | None = Field(
        default=None,
        sa_column=Column(String(2000), nullable=True, info={FERNET_SALT: SALT_EMAIL}),
    )

    #: Which of the account's addresses the challenge went to, where it went
    #: to one. Following ``user_tokens.user_email_id``: an account may hold
    #: more than one address, and what arriving at a particular one proves is
    #: about that address rather than about the account.
    user_email_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("user_emails.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    attempts: int = Field(
        default=0, sa_column=Column(SmallInteger, nullable=False, server_default="0")
    )

    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )

    consumed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
