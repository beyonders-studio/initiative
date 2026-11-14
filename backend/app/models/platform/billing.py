"""Shared tables backing the external billing service integration.

``BillingEventLog`` is the idempotency claim for a community notice (its
``event_id`` is the notice's key, claimed once it's written down), and the
append-only record of what billing asked for. ``guild_id`` is a weak
reference (no FK) so rows outlive the guild. A community's state needs no
claim: it carries a version, and ``guild_administration.billing_version`` says
which one is held.

``BillingJti`` is the one-shot redemption blocklist for billing's request
envelopes, the shape every jti blocklist shares (``app.db.jti_blocklist``).
``expires_at`` mirrors the envelope's ``exp`` so the shared jti janitor can
prune old rows (``app.services.platform.jti_purge``).

``BillingChange`` is the change log billing reads by cursor
(``app.services.platform.billing_changes``).

No pricing data, tier matrix, or plan definitions may ever live in this
repository — the billing service owns plan math and pushes only computed
numbers.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Identity,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class BillingOp(str, Enum):
    """Operations recorded in ``billing_event_log.op``: the one claimed verb,
    a notice billing asks to be delivered to a community's seat."""

    community_notice = "community_notice"


#: ``billing_event_log.source`` of every row this boundary writes. Who acted
#: is billing's to record, in its own audit stream.
BILLING_SOURCE = "billing"


class BillingEventLog(SQLModel, table=True):
    __tablename__ = "billing_event_log"

    event_id: str = Field(sa_column=Column(String(length=128), primary_key=True))
    guild_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    op: str = Field(sa_column=Column(String(length=32), nullable=False))
    source: str = Field(sa_column=Column(String(length=32), nullable=False))
    actor: str | None = Field(
        default=None, sa_column=Column(String(length=128), nullable=True)
    )
    applied_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class BillingJti(SQLModel, table=True):
    __tablename__ = "billing_jti_blocklist"

    jti: str = Field(sa_column=Column(String(length=64), primary_key=True))
    redeemed_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class BillingChange(SQLModel, table=True):
    """One fact billing reads from the change log: a community was created,
    deleted, restored, suspended, unsuspended or purged.

    Written by the trigger ``public.billing_record_change`` on ``guilds``, in
    the transaction that changed the fact, as the table's owner: no request
    role may write a row here, so a row means the fact happened. ``xid`` is
    that transaction's id, and the log is served in ``(xid, id)`` order only
    up to the oldest transaction still running, so a row that commits late is
    never skipped (``app.services.platform.billing_changes``).

    ``community_ref`` is the community's billing reference when it had one at
    the time, and is resolved when the row is served otherwise; a purged
    community's is captured here because its references go with it.
    ``data`` holds the kind's own fields by our ids (``owner_user_id``), which
    are turned into references when served. Retention: 30 days.
    """

    __tablename__ = "billing_changes"
    __table_args__ = (
        Index("ix_billing_changes_xid_id", "xid", "id"),
        Index("ix_billing_changes_occurred_at", "occurred_at"),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, Identity(always=True), primary_key=True),
    )
    xid: int = Field(sa_column=Column(BigInteger, nullable=False))
    guild_id: int = Field(sa_column=Column(Integer, nullable=False))
    kind: str = Field(sa_column=Column(String(48), nullable=False))
    community_ref: str | None = Field(
        default=None, sa_column=Column(String(128), nullable=True)
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    occurred_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=text("now()")
        )
    )
