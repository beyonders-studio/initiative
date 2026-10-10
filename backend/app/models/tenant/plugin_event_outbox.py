"""The events installed plug-ins emit, kept until each subscription has them.

A plug-in emits one of the events its pinned definition declares
(``POST /plugin-platform/installation/events``) and the row lands here, in the
community's own schema. The outbox poller delivers it with the change log
(``event_outbox``): the same ledger, backoff, dead-letter and retention, and
the same envelope, where a plug-in event is one entry in ``changes``.

Unlike the change log, a row carries its payload: it is the emitting plug-in's own
vendor data, bounded in size, and a subscriber hears it only while it holds
``plugins:<emitter>``.

Written by the system engine alone and read by the poller.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class PluginEventOutbox(SQLModel, table=True):
    __tablename__ = "plugin_event_outbox"

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )

    #: ``txid_current()`` of the emitting transaction: the unit the poller's
    #: ledger records, shared with ``event_outbox``.
    txn_id: int = Field(sa_column=Column(BigInteger, nullable=False, index=True))

    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

    #: The install that emitted it, or for one of the demo deployment's own
    #: events (``demo.*``), the install it is addressed to. A weak reference,
    #: like the change log's actor: removing the plug-in leaves the row to
    #: retention, and delivery names an emitter only while its install is there.
    install_id: int = Field(sa_column=Column(Integer, nullable=False))

    #: ``plugin.<public_id>.<event>``, an ``emit`` endpoint the pinned definition
    #: declares, or one of the demo's (``webhook_events.DEMO_EVENT_TYPES``).
    event_type: str = Field(sa_column=Column(String(length=200), nullable=False))

    #: The initiative the event is about, or NULL for one about the community.
    initiative_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )

    payload: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
