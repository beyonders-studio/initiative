"""The prekeys a sender claims to open a session with a device.

One row is one published public key. A claim **deletes** the row rather than
marking it spent: there is no UPDATE grant anywhere on this table, and a key
that cannot be claimed twice by construction needs no state to say so.

``fallback`` marks the last-resort key, which is the exception — it is reusable
and survives a claim, so a sender who arrives after the pool is drained can
still start a conversation instead of being told to come back later.
"""

import uuid
from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlmodel import Field, SQLModel


class DmOneTimeKey(SQLModel, table=True):
    __tablename__ = "dm_one_time_keys"
    __table_args__ = (
        # The fallback key is numbered in its own sequence on the client, so a
        # device's fallback key id can be the same string as one of its prekey
        # ids. They are separate namespaces here too.
        UniqueConstraint(
            "device_id",
            "fallback",
            "key_id",
            name="uq_dm_one_time_keys_device_key",
        ),
        # The claim reads "an unclaimed key for this device, cheapest first",
        # which is this index and its partial ordering on ``fallback``.
        Index("ix_dm_one_time_keys_device_fallback", "device_id", "fallback"),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            Uuid, primary_key=True, server_default=text("gen_random_uuid()")
        ),
    )
    device_id: uuid.UUID = Field(
        sa_column=Column(
            Uuid,
            ForeignKey("dm_devices.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    #: The client's own name for the key, echoed back so it can find the
    #: matching private half.
    key_id: str = Field(sa_column=Column(Text, nullable=False))
    public_key: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    #: The publishing device's signature over the key.
    signature: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    fallback: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
