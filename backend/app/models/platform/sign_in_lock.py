"""How many wrong answers an account has taken lately, and whether it is locked.

One row per account that has had a wrong password or code recently; an account
with no row has none. Wrong passwords, authenticator codes, recovery codes and
emailed codes all count toward the same number.

**app_admin-only**: every write happens before anybody is signed in.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class SignInLock(SQLModel, table=True):
    """One account's recent wrong answers and the locks they placed."""

    __tablename__ = "sign_in_locks"

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    #: Wrong answers since ``first_failure_at``.
    failures: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    first_failure_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    #: Password and codes are refused until then.
    locked_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Locks placed since ``first_lock_at``.
    locks: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    first_lock_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
