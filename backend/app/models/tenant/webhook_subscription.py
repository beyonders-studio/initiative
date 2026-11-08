"""Outbound webhook subscription model.

Each row is one auto-side consumer registering for events on this
service. The ``hmac_secret`` is opaque-random per subscription —
shared with the receiver out-of-band on the create-response (and
never returned again) so the receiver can verify the signature on
every inbound delivery without us holding their long-term secret.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlmodel import Field

from app.models.tenant._mixins import CreatedByMixin


class WebhookSubscription(CreatedByMixin, table=True):
    __tablename__ = "webhook_subscriptions"

    id: int | None = Field(default=None, primary_key=True)

    initiative_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("initiatives.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )

    # Which install registered this, when a plug-in did. NULL for a subscription a
    # member registered against a URL of their own.
    #
    # It decides how an envelope names the guild and the actor: a plug-in already
    # holds references for both, minted at its install, and a delivery should
    # use those rather than introduce a second set it cannot match to anything.
    # No foreign key — ``guild_plugins`` rows go when a plug-in is uninstalled, and a
    # subscription outliving that is one whose deliveries stop, not one that
    # should disappear from the owner's list.
    plugin_install_id: int | None = Field(
        default=None,
        sa_column=Column(Integer, nullable=True, index=True),
    )

    target_url: str = Field(sa_column=Column(String(length=2048), nullable=False))
    # Stored opaque-random; never re-emitted after the create response.
    hmac_secret: str = Field(sa_column=Column(String(length=128), nullable=False))
    event_types: list[str] = Field(
        sa_column=Column(ARRAY(String(length=100)), nullable=False),
    )

    # Column names this subscription cares about. NULL means any change to a
    # named event type. An update is delivered when the changed set intersects
    # this one; created/deleted always are, since neither names columns.
    fields: list[str] | None = Field(
        default=None,
        sa_column=Column(ARRAY(String(length=63)), nullable=True),
    )

    active: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    # TZ-aware columns to match the migration.
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
