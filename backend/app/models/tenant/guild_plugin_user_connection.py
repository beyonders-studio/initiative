"""One member's own connection to an installed plug-in's vendor.

Some vendors authorize an *organization* and some authorize a *person*. The
first kind is a credential a guild admin types once and the whole guild uses,
which lives in ``guild_plugin_secrets``. This table is the second kind: an OAuth
grant, or anything else where the vendor's answer to "who is this?" is a human
being. Whatever such a credential can reach is what *that person* can reach, so
each member connects their own account and the plug-in holds one credential per
person rather than one for everybody.

Two consequences shape the columns:

* **Installing a plug-in never waits on this.** A plug-in whose only connections are
  per-member is fully installed with no rows here at all; members connect when
  and if they want the features that need it.
* **The plug-in never learns who the member is.** It addresses a connection by
  ``connection_ref`` — an opaque random handle minted per (install, connection,
  member) — so it can select the right credential without holding a user id, an
  email, or a display name, and the same person looks unrelated across plug-ins.

A personal connection is still community-governed access rather than private
property, so the row is readable and removable by its owner **or** by the
community's seat (``app.db.tenancy.MEMBER_CREDENTIAL_TABLES``). What the seat
gets is management — see who connected as which vendor account, disconnect
them, stop them reconnecting. Never the values: they are in
``plugin_connection_secrets``, which only the member and the system engine
reach, and this row carries only which keys hold one (``secret_fields``).

``blocked_at`` leaves the row behind as a tombstone once the values are gone, so
"this person may not reach that system through us" survives without uninstalling
the plug-in for everyone.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ConfigDict
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


#: How wide a manifest connection id is stored, and therefore the widest one
#: any caller can name.
CONNECTION_ID_LENGTH = 64


class GuildPluginUserConnection(SQLModel, table=True):
    __tablename__ = "guild_plugin_user_connections"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    __table_args__ = (
        # One row per member per connection of an install. Reconnecting reuses
        # it, so a member's history is one row rather than a pile of them.
        UniqueConstraint(
            "plugin_id",
            "connection_id",
            "user_id",
            name="guild_plugin_user_connections_unique_member",
        ),
        # The handle the plug-in addresses. Unique so it resolves to exactly one
        # credential.
        UniqueConstraint(
            "connection_ref", name="guild_plugin_user_connections_unique_ref"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    plugin_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guild_plugins.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    #: Which of the pinned definition's connections this is, by manifest id.
    connection_id: str = Field(
        sa_column=Column(String(CONNECTION_ID_LENGTH), nullable=False)
    )

    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("users.id"),
            nullable=False,
            index=True,
        )
    )
    #: Random, not derived: the same person is uncorrelated across plug-ins.
    connection_ref: str = Field(sa_column=Column(String(32), nullable=False))

    #: Non-secret values, keyed by field key.
    config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    #: Which keys of ``plugin_connection_secrets`` hold a value, each with a
    #: digest of it; kept in step by a trigger on that table.
    secret_fields: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    #: Where a connection has got to, as far as this side can tell.
    #:
    #: ``pending`` — the member started the vendor flow and the plug-in has not
    #: written a result back yet. ``connected`` — values are present. ``blocked``
    #: — an admin stopped this member reconnecting, and the row is a tombstone.
    status: str = Field(
        default="pending",
        sa_column=Column(String(16), nullable=False, server_default="pending"),
    )
    #: What the plug-in says the member connected as, e.g. ``@alice``. Display only,
    #: reported by the plug-in, never a credential.
    account_label: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    blocked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    blocked_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(Integer, ForeignKey("users.id"), nullable=True),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
