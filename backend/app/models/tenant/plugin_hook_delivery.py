"""Vendor webhook deliveries waiting for an install, and those it has had.

Initiative receives a vendor's webhooks for a plug-in and queues each one here,
once for every community it belongs to, by the vendor's delivery id: the
community's delivery sweep then maps it (a declarative plug-in) or forwards
it to the plug-in's ``webhook`` hook (a container). A row holds the body and
the vendor's headers until that is done, and a visit holds it (``taken_until``)
while it works; one whose work failed waits and is tried again
(``attempts``). A row whose body is gone is done, and a redelivery of its id
is not queued again. A row lives 24 hours; the outbox retention pass removes
it after that.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

#: The widest delivery id kept.
DELIVERY_ID_MAX_LENGTH = 200


class PluginHookDelivery(SQLModel, table=True):
    __tablename__ = "plugin_hook_deliveries"

    install_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    delivery_id: str = Field(
        sa_column=Column(String(length=DELIVERY_ID_MAX_LENGTH), primary_key=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    received_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default="now()"
        )
    )
    #: The delivery as the vendor sent it, until it is done.
    body: bytes | None = Field(
        default=None, sa_column=Column(LargeBinary, nullable=True)
    )
    #: The vendor's own ``x-`` headers.
    headers: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    #: The value it was routed to the install by.
    route: str | None = Field(
        default=None, sa_column=Column(String(length=200), nullable=True)
    )
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    #: Until when the visit working on it holds it.
    taken_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
