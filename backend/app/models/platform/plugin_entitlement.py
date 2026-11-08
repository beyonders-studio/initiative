"""What a community holds of a plug-in, and what the plug-in reports it used.

Two ``public`` tables, both keyed by the community and the listing's uid, and
neither naming anything but those, a version and the plug-in's own values:

* ``plugin_entitlements`` — the latest **statement** this deployment's
  entitlement issuer sent for one (community, listing): the signed statement
  itself (``statement``, a compact JWS kept exactly as sent, which is what the
  plug-in is handed), and beside it the two claims this deployment reads for
  itself: a ``version`` that rises with every change, and ``values``, a flat
  object whose keys belong to the plug-in. A higher version replaces the row;
  an equal or lower one changes nothing. Only a listing whose package names
  terms for it (``marketplace_listings.access``) is ever sent one.
* ``plugin_usage`` — the latest **total** a plug-in reported for one of its
  meters in one calendar month. A total only ever rises within a period.

Both are the system engine's alone: no request-path role holds a grant, and the
routes that read or write them authenticate the caller first and then work on
the system engine. A community's deletion takes its rows with it.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.platform.marketplace import UID_LENGTH

__all__ = [
    "METER_MAX_LENGTH",
    "METER_PATTERN",
    "PERIOD_PATTERN",
    "PluginEntitlement",
    "PluginUsage",
]

#: A meter's name: what a package's terms list and a usage report names.
METER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
METER_MAX_LENGTH = 64
#: A usage period: one calendar month, ``YYYY-MM``.
PERIOD_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


class PluginEntitlement(SQLModel, table=True):
    """The current statement for one (community, listing)."""

    __tablename__ = "plugin_entitlements"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_plugin_entitlements_version"),
        CheckConstraint(
            "jsonb_typeof(\"values\") = 'object'",
            name="ck_plugin_entitlements_values_object",
        ),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    listing_uid: str = Field(sa_column=Column(String(UID_LENGTH), primary_key=True))
    #: The signed statement as the issuer sent it (compact JWS). Never
    #: re-encoded: the plug-in verifies the issuer's signature over it.
    statement: str = Field(sa_column=Column(Text, nullable=False))
    #: The statement's ``version`` and ``values`` claims, read for this
    #: deployment's own use (the install gate, the delivery's dedup).
    version: int = Field(sa_column=Column(BigInteger, nullable=False))
    values: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False)
    )
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class PluginUsage(SQLModel, table=True):
    """The latest total one plug-in reported for one meter and month."""

    __tablename__ = "plugin_usage"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_plugin_usage_quantity"),
        CheckConstraint(f"period ~ '{PERIOD_PATTERN}'", name="ck_plugin_usage_period"),
        CheckConstraint(f"meter ~ '{METER_PATTERN}'", name="ck_plugin_usage_meter"),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    listing_uid: str = Field(sa_column=Column(String(UID_LENGTH), primary_key=True))
    meter: str = Field(sa_column=Column(String(METER_MAX_LENGTH), primary_key=True))
    period: str = Field(sa_column=Column(String(7), primary_key=True))
    quantity: int = Field(sa_column=Column(BigInteger, nullable=False))
    #: When the plug-in says the total was counted.
    as_of: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
