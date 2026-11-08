"""A hook about a community's install, waiting to reach its plug-in.

The community hooks (``installed``, ``uninstalled``, ``erase``,
``community_status``, ``entitlement``) tell a plug-in what happened to the
community it is installed in. Each is written here, in the transaction that
caused it, and delivered by the ``plugin_hooks`` sweep timer
(:mod:`app.services.marketplace.community_hooks`), which retries it until the
plug-in answers.

The row names the plug-in by its ``public_id`` and the install by number only,
with no foreign key to ``guild_plugins``: an ``uninstalled`` or ``erase`` hook
is about an install that is already gone, and has to be retried after it has
gone. It lives in ``public`` for the same reason, beside the guild row it
cascades from.

A routed write appends rows for its own community; the system engine does the
rest.

``claimed_until`` is the lease that makes one sender per community and
plug-in: a sender claims the plug-in's head row (or writes a row for a hook it
sends at once) in a short transaction, sends with no connection held, and
clears the claim as it settles. A claim that lapses, a sender that died, is
simply claimed again.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.platform.identity_ref import SECTOR_PLUGIN_MAX_LENGTH

__all__ = ["HOOK_ERROR_MAX_LENGTH", "PluginCommunityHook"]

#: The widest error kept from a failed attempt.
HOOK_ERROR_MAX_LENGTH = 200


class PluginCommunityHook(SQLModel, table=True):
    __tablename__ = "plugin_community_hooks"
    __table_args__ = (
        # The worker's scan: each plug-in's hooks in one community, oldest first,
        # among those not yet answered.
        Index(
            "ix_plugin_community_hooks_pending",
            "guild_id",
            "public_id",
            "id",
            postgresql_where=text("done_at IS NULL"),
        ),
        # The sweep of answered hooks.
        Index("ix_plugin_community_hooks_done_at", "done_at"),
    )

    id: int | None = Field(
        default=None, sa_column=Column(BigInteger, primary_key=True, autoincrement=True)
    )
    guild_id: int = Field(
        sa_column=Column(
            Integer, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
        )
    )
    #: The plug-in, by its registration's ``public_id``.
    public_id: str = Field(
        sa_column=Column(String(SECTOR_PLUGIN_MAX_LENGTH), nullable=False)
    )
    #: The install the hook is about, as the token's ``plugin_install_id``.
    #: Null when the community no longer has one to name.
    install_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    #: One of ``community_hooks.COMMUNITY_HOOK_NAMES``.
    hook: str = Field(sa_column=Column(String(32), nullable=False))
    body: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: The earliest the worker may send it: now, or later after a failure.
    next_attempt_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    #: When the plug-in answered it, or the worker gave up on it.
    done_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: Who is sending it, until when: while this is in the future no other
    #: sender sends to the plug-in in the community.
    claimed_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    #: How it ended: ``delivered`` (a 2xx), ``not_taken`` (a 404: the plug-in
    #: does not take this hook), ``superseded`` (a newer one of its kind was
    #: waiting), ``gave_up``, ``unnamed`` (the plug-in may not be named here),
    #: or, for a hook sent at once, ``answered``, ``failed`` or ``lapsed`` (its
    #: sender died).
    outcome: str | None = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    #: What the last failed attempt met, for an operator reading the table.
    last_error: str | None = Field(
        default=None,
        sa_column=Column(String(HOOK_ERROR_MAX_LENGTH), nullable=True),
    )
