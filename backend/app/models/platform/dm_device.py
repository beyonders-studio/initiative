"""One installed client of one account, and the keys that identify it.

A device is where a ratchet lives. It is deliberately *not* the same row as an
``auth_session``: a session tracks a sign-in, which rotates and expires, and a
key store has to outlive it — a laptop shut for three months comes back
expecting its history. ``session_id`` names the sign-in it last collected
under, followed across renewals, which is what its push registration names
too.

``identity_key`` and ``fingerprint_key`` are public keys. The private halves
are generated on the client and stay there.

Read by another account only through the directory leg — see the migration —
and only where ``public.dm_apparent_permission`` already says ``open``.
"""

import uuid
from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    Uuid,
    text,
)
from sqlmodel import Field, SQLModel


class DmDevice(SQLModel, table=True):
    __tablename__ = "dm_devices"
    __table_args__ = (Index("ix_dm_devices_user", "user_id"),)
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(
            Uuid, primary_key=True, server_default=text("gen_random_uuid()")
        ),
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    #: Curve25519. What a sender encrypts to.
    identity_key: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    #: Ed25519. What a safety number is computed over.
    fingerprint_key: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    #: The device's Ed25519 signature over its keys and account.
    signature: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    #: The sign-in this key store last collected under, at the live row its
    #: chain has reached. A plain uuid, as ``push_tokens.session_id`` is:
    #: session rows are purged on their own schedule.
    session_id: uuid.UUID | None = Field(
        default=None, sa_column=Column(Uuid, nullable=True, index=True)
    )
    #: Derived at registration from the user agent.
    #: Never typed by hand — a device list nobody has to curate is one people
    #: actually read.
    label: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: Moved on every collection, so Settings › Security can surface a device
    #: that has stopped syncing before its queue copy grows without bound.
    last_seen_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
