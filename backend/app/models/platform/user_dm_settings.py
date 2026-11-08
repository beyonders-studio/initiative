"""How one account answers "who may ask to message me".

One row per account, written when the account is created and seeded from
``AppSetting.default_dm_policy``. Deliberately not a column on ``public.users``:
that table is read whole by the platform tiers, and this is the account
holder's own business (see ``user_ignores`` for the same shape).

An account with no row here reads as ``private`` — the most closed value —
so a creation path that forgets to seed one is closed rather than open.
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import ConfigDict
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, text
from sqlmodel import Enum as SQLEnum
from sqlmodel import Field, SQLModel


class DmPolicy(str, Enum):
    """Who may ask to message this account, outside its connections.

    A connection satisfies every value here, which is what makes it the one
    thing that works whatever the holder picks.
    """

    #: Nobody. Only accounts this one is connected to may ask.
    private = "private"
    #: Anyone sharing a live community this account has not switched off.
    community = "community"
    #: Anyone at all.
    public = "public"


class UserDmSettings(SQLModel, table=True):
    __tablename__ = "user_dm_settings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    dm_policy: DmPolicy = Field(
        default=DmPolicy.private,
        sa_column=Column(
            SQLEnum(DmPolicy, name="user_dm_policy"),
            nullable=False,
            server_default=DmPolicy.private.value,
        ),
    )
    #: Whether this account's own clients tell a sender that a message reached
    #: a device and was read. Off is a request the *sender* never sees refused:
    #: nothing arrives, which is what "no receipt" looks like anyway.
    send_receipts: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("true")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
