"""Messages between two devices of one account while they verify each other.

Verifying a device is an interactive exchange: each side publishes a public key
and a commitment, both show the same short set of emoji, and each confirms with
a MAC. The two devices are not yet sure of each other, so none of it can travel
over an encrypted session between them. This table relays it instead.

Both ends belong to the same account, which ``user_id`` names. ``body`` is the
client's own JSON, stored as text and never parsed here: every value in it is a
public key, a commitment or a MAC.

A row lives for minutes, not days. Collecting is consuming — the recipient's
read deletes what it returns — and a row nobody collects stops being delivered
ten minutes after it was written and is deleted by the next send or collect on
the account. The table is ``UNLOGGED``: after a crash Postgres empties it,
which only cancels a verification in progress, and both devices start again.
"""

import uuid
from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    Uuid,
    text,
)
from sqlmodel import Field, SQLModel


class DmVerificationItem(SQLModel, table=True):
    __tablename__ = "dm_verification_messages"
    __table_args__ = (
        # Collection is "everything for this device, oldest first".
        Index(
            "ix_dm_verification_messages_device_id",
            "recipient_device_id",
            "id",
        ),
        {"prefixes": ["UNLOGGED"]},
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    sender_device_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("dm_devices.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    recipient_device_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("dm_devices.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    body: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        ),
    )
