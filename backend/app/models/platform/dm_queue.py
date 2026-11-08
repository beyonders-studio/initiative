"""Ciphertext waiting for one device to collect it.

This is a queue, not an archive. A row is deleted the moment its recipient
acknowledges it, and nothing on the server side ever deletes one on a timer: a
message waits as long as it takes, because a phone in a drawer belongs to
somebody who still expects their messages. What bounds the table is a per-account
byte ceiling enforced at the send path, which refuses a message rather than
accepting one it means to drop later.

There is no sender column. The recipient identifies the sender by which session
decrypts, so nothing would read it — in a two-person conversation the sender is
whoever is not the recipient anyway.

``payload`` is opaque. ``message_type`` is Olm's own framing (pre-key or
normal), which the client needs in order to decide whether to establish a
session or continue one.
"""

import uuid
from datetime import datetime, timezone

from pydantic import ConfigDict
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    Uuid,
)
from sqlmodel import Field, SQLModel


class DmQueueItem(SQLModel, table=True):
    __tablename__ = "dm_queue"
    __table_args__ = (
        # Collection is "everything for this device, oldest first". Strict order
        # is not a nicety: a ratchet keeps a bounded number of skipped message
        # keys, so delivering in order is what keeps a client able to decrypt.
        Index("ix_dm_queue_device_id", "recipient_device_id", "id"),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    conversation_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("dm_conversations.id", ondelete="CASCADE"),
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
    message_type: int = Field(sa_column=Column(SmallInteger, nullable=False))
    payload: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
