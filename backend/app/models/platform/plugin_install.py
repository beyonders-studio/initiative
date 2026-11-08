"""Which communities have installed which plug-in, in one place.

An install is a row in its community's own schema (``guild_plugins``). This is
the index of them across communities: the listing an install came from, the
community and install, whether the install is switched on, and the value a
vendor webhook is routed to it by. It holds no content.

It also holds the community status each install's plug-in was last told
(``community_status_sent``), which is how a change of status reaches it.

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
claims its route first. Reached only by the system engine.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlmodel import Field, SQLModel

__all__ = [
    "EXCLUSIVE_ROUTE_INDEX",
    "HOOK_ROUTE_MAX_LENGTH",
    "SETTING_KEY_LENGTH",
    "SETTING_VALUE_LENGTH",
    "PluginInstall",
    "PluginInstallClaim",
]

#: The widest route value kept.
HOOK_ROUTE_MAX_LENGTH = 200

#: The index holding each route of an exclusive install to one community.
EXCLUSIVE_ROUTE_INDEX = "uq_plugin_installs_exclusive_route"

#: A setting's key and a unique setting's value at their widest: the contract's
#: ``identifierLength`` and ``uniqueSettingValueLength``, as column widths.
SETTING_KEY_LENGTH = 64
SETTING_VALUE_LENGTH = 16


class PluginInstall(SQLModel, table=True):
    __tablename__ = "plugin_installs"
    __table_args__ = (
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
