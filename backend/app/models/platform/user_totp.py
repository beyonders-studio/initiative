from datetime import UTC, datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class UserTotp(SQLModel, table=True):
    """One account's authenticator-app factor, without the secret.

    The secret lives in ``user_totp_secrets`` (the ``auth_provider_secrets``
    pattern): what is true *about* the factor is here, the material it is made
    of is next door, and only the system engine reads either.

    A row appears when somebody starts enrolling and is not asked for at
    sign-in until ``confirmed_at`` is set — proof that the authenticator they
    scanned produces codes this secret accepts. An unconfirmed row is replaced
    by the next enrolment attempt.

    ``last_timestep`` is the 30-second interval a code was last accepted from.
    A code is taken once: the interval it came from is recorded, and the next
    code has to come from a later one.
    """

    __tablename__ = "user_totp"

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    confirmed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    #: Unix time divided by the 30-second step, so it outgrows an int.
    last_timestep: int | None = Field(
        default=None, sa_column=Column(BigInteger, nullable=True)
    )

    last_used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
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
