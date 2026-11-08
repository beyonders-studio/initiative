"""What each subscription has been told about, one transaction at a time.

This replaces a per-subscription cursor, and the reason is not tuning — a cursor
cannot be made correct here. Outbox ids come from a sequence at **insert** time
but become visible at **commit** time, and those orders are independent: a
transaction that opened earlier can publish a row beneath a watermark chosen
while it was still in flight, and an uncommitted row is invisible to every query
that watermark could have consulted. Any single number can therefore be jumped
from below, and the event that lands under it is never read again.

A row here is the whole of the progress state instead. A transaction is either
recorded for a subscription or it is not, so there is nothing for a late-arriving
row to be *beneath*. Interleaving, window boundaries, and batch limits stop being
correctness concerns and become throughput knobs: work not taken this pass is
simply still pending on the next.

The primary key doubles as the concurrency control. Every replica runs the
poller, and claiming a transaction is an insert on ``(subscription_id,
txn_id)`` — two replicas racing the same batch is settled by the database rather
than by a lease the application has to reason about.

Retry state lives per transaction, so a refusal backs off exactly the batch that
was refused, and the subscription's later transactions wait behind it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer
from sqlmodel import Field, SQLModel


class WebhookDelivery(SQLModel, table=True):
    __tablename__ = "webhook_deliveries"

    subscription_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )

    #: The ``txid_current()`` of the writing transaction — the same value its
    #: ``event_outbox`` rows carry, and the unit a batch is built from.
    txn_id: int = Field(sa_column=Column(BigInteger, primary_key=True))

    #: Set once the target answered 2xx. NULL means claimed or awaiting retry.
    delivered_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )

    attempts: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )

    #: While unclaimed, when this batch may next be attempted. While a pass holds
    #: it, the lease that pass must still own in order to settle. NULL once
    #: delivered.
    next_attempt_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    #: Set once the backoff schedule is exhausted without a 2xx. A terminal
    #: state alongside ``delivered_at``: the batch stops being retried, and
    #: later transactions for the same subscription are no longer held behind
    #: it.
    dead_lettered_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True, index=True),
    )
