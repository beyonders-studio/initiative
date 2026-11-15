"""Which communities have installed which plug-in, in one place.

An install is a row in its community's own schema (``guild_plugins``). This is
the index of them across communities: the listing an install came from, the
community and install, whether the install is switched on, and the value a
vendor webhook is routed to it by. It holds no content.

It also holds the community status each install's plug-in was last told
(``community_status_sent``), which is how a change of status reaches it.

**The install's state.** Beside the index, each row holds what the platform
decided about the install, never the community's content: its ``status``
(:class:`PluginInstallStatus`, set by staff or by billing's sync), whether
staff suspended it there (``suspended_at``), and the status its plug-in was
last told (``plugin_status_sent``). The index sweep writes none of these.

It answers two questions without visiting a guild schema: which installs an
plug-in has (``GET /plugin-platform/installations``), and which installs a vendor
delivery belongs to (``POST /plugin-hooks/{public_id}``). ``hook_route`` is the
stored value of the field the plug-in's ``webhooks.route`` names, written when a
connect stores it and cleared when it is removed. While ``exclusive``, the
negation of the registration's ``shared_routes``, one community holds each route
of a listing's installs.

Beside it, ``plugin_install_claims`` holds the values each install holds for
its plug-in's unique settings, current and earlier, in one index over every
community, so no two communities hold the same one. An install writes its own
in the transaction that stores the value; they go with the community, and with
the install when it is removed.

Written by the ``plugin_index`` sweep from each community's installs, which
their writes arm (:mod:`app.services.marketplace.plugin_installs`); a connect
claims its route first. Reached by the system engine; besides it, an installed
plug-in's standing reads its own install's row, and billing's sync writes the
statuses of the community it is routed to.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlmodel import Field, SQLModel

__all__ = [
    "EXCLUSIVE_ROUTE_INDEX",
    "HOOK_ROUTE_MAX_LENGTH",
    "SERVING_STATES",
    "SETTING_KEY_LENGTH",
    "SETTING_VALUE_LENGTH",
    "PluginInstall",
    "PluginInstallClaim",
    "PluginInstallStatus",
    "PluginState",
]

#: The widest route value kept.
HOOK_ROUTE_MAX_LENGTH = 200

#: The index holding each route of an exclusive install to one community.
EXCLUSIVE_ROUTE_INDEX = "uq_plugin_installs_exclusive_route"

#: A setting's key and a unique setting's value at their widest: the contract's
#: ``identifierLength`` and ``uniqueSettingValueLength``, as column widths.
SETTING_KEY_LENGTH = 64
SETTING_VALUE_LENGTH = 16


class PluginInstallStatus(str, Enum):
    """An install's status, set by staff or, where billing sets plans, by
    billing. Initiative keeps no plug-in data by it: the plug-in is told and
    decides what each means to it."""

    #: Everything flows.
    active = "active"
    #: The plug-in reads; its writes are refused by its standing.
    read_only = "read_only"
    #: Nothing flows, and the community sees nothing of it.
    on_hold = "on_hold"
    #: As on hold, and uninstalled once its window ends
    #: (``retention.PLUGIN_INSTALL_DELETION``).
    deleted = "deleted"


class PluginState(str, Enum):
    """A plug-in's state in one community: suspended when the platform, the
    install or its reach suspends it, otherwise the install's status."""

    active = "active"
    read_only = "read_only"
    on_hold = "on_hold"
    deleted = "deleted"
    suspended = "suspended"


#: The states in which the plug-in is there for the community.
SERVING_STATES: frozenset[PluginState] = frozenset(
    {PluginState.active, PluginState.read_only}
)


class PluginInstall(SQLModel, table=True):
    __tablename__ = "plugin_installs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'read_only', 'on_hold', 'deleted')",
            name="ck_plugin_installs_status",
        ),
        Index("ix_plugin_installs_hook_route", "listing_uid", "hook_route"),
        Index("ix_plugin_installs_listing", "listing_uid", "guild_id", "install_id"),
        Index(
            EXCLUSIVE_ROUTE_INDEX,
            "listing_uid",
            "hook_route",
            unique=True,
            postgresql_where=text("exclusive AND hook_route IS NOT NULL"),
        ),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    #: ``guild_plugins.id`` in that community's schema.
    install_id: int = Field(sa_column=Column(Integer, primary_key=True))
    #: The listing the install came from, which names its registration.
    listing_uid: str = Field(sa_column=Column(String(length=14), nullable=False))
    enabled: bool = Field(sa_column=Column(Boolean, nullable=False))
    hook_route: str | None = Field(
        default=None,
        sa_column=Column(String(length=HOOK_ROUTE_MAX_LENGTH), nullable=True),
    )
    #: The negation of its registration's ``shared_routes``: while true, this
    #: install's route is held by this community alone.
    exclusive: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    #: The community's status as its plug-in was last told it, by the
    #: ``community_status`` hook. The community-hook worker compares it with
    #: ``guilds.status`` and tells the plug-in when the two differ, so a status
    #: is told however it was changed.
    community_status_sent: str | None = Field(
        default=None, sa_column=Column(String(length=16), nullable=True)
    )
    #: The install's status (:class:`PluginInstallStatus`).
    status: str = Field(
        default=PluginInstallStatus.active.value,
        sa_column=Column(Text, nullable=False, server_default="active"),
    )
    #: When ``status`` last moved: a deletion's window counts from it.
    status_changed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Staff suspended the install here, and who did.
    suspended_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    suspended_by: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    #: The status its plug-in was last told, by the ``plugin_status`` hook;
    #: compared with ``status`` as ``community_status_sent`` is with the
    #: community's. Unset reads as told ``active``, which an install starts as.
    plugin_status_sent: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )


class PluginInstallClaim(SQLModel, table=True):
    """A value one install holds for one of its plug-in's unique settings: the
    one it holds now, or one it was renamed from, written in the transaction
    that stores it on the install. The unique index keeps two installs of a
    plug-in from holding the same value; values are kept in lowercase."""

    __tablename__ = "plugin_install_claims"
    __table_args__ = (
        Index(
            "uq_plugin_install_claims_value", "listing_uid", "key", "value", unique=True
        ),
    )

    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True
        )
    )
    install_id: int = Field(sa_column=Column(Integer, primary_key=True))
    #: The setting's key in the install's pinned definition.
    key: str = Field(
        sa_column=Column(String(length=SETTING_KEY_LENGTH), primary_key=True)
    )
    value: str = Field(
        sa_column=Column(String(length=SETTING_VALUE_LENGTH), primary_key=True)
    )
    #: The install's listing, so one index holds every community's values for
    #: a plug-in.
    listing_uid: str = Field(sa_column=Column(String(length=14), nullable=False))
