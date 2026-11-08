from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_BIRTHDATE


class UserBirthdate(SQLModel, table=True):
    """An account's date of birth, encrypted at rest.

    A companion to ``users`` in the shape of ``user_totp_secrets``: read and
    written only by the system engine, so no request role can see a date. It is
    kept so a plug-in's minimum age, which differs by country, can be checked
    against the person's actual age rather than against one yes-or-no answer.

    1:1 with the account — ``user_id`` is the PK and an FK to ``users.id``
    (``ON DELETE CASCADE``). ``birthdate_encrypted`` is the ISO date,
    Fernet-encrypted with ``SALT_BIRTHDATE``, which its column declares for
    the SECRET_KEY rotation. Erasing an account deletes the row
    (``users._erase_personal_rows``). The date is never sent back to anyone,
    the person included: an API says only whether one is on file.
    """

    __tablename__ = "user_birthdates"

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    birthdate_encrypted: str = Field(
        sa_column=Column(Text, nullable=False, info={FERNET_SALT: SALT_BIRTHDATE})
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
