"""What one webhook subscription calls the community, and the people writing in it.

A subscription a member registered against a URL of their own is a sector of
its own (``IdentityPurpose.webhook``): the names it is given are minted for it
and for nothing else, in the format every other reference has, and its
receiver is the only party that ever holds them. Nothing looks one up by its
value.

So they are the community's own and kept in its schema, under the
subscription: deleting the subscription, or the initiative it watches, takes
them with it. A subscription a plug-in registered is named in that plug-in's
sector instead (``services.tenant.webhook_refs``).

Read and written by the system engine alone (``app.db.tenancy.LEDGER_TABLES``),
which mints them where a subscription is shown or delivered to.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.platform.identity_ref import REF_MAX_LENGTH, IdentityEntity


class WebhookRef(SQLModel, table=True):
    """One name: what one subscription calls the community or one person."""

    __tablename__ = "webhook_refs"
    __table_args__ = (UniqueConstraint("ref", name="webhook_refs_unique_ref"),)

    subscription_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    #: ``guild`` for the community, whose id ``entity_id`` repeats, or
    #: ``user`` for a person.
    entity_type: IdentityEntity = Field(
        sa_column=Column(String(16), primary_key=True),
    )
    #: Plain integer, no foreign key: a person is a row in ``public.users``,
    #: and erasure removes the names it held here
    #: (``services.platform.users``).
    entity_id: int = Field(
        sa_column=Column(Integer, primary_key=True, autoincrement=False)
    )

    #: The value the receiver holds, prefix and all
    #: (``identity_refs.mint_ref``).
    ref: str = Field(sa_column=Column(String(REF_MAX_LENGTH), nullable=False))

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
