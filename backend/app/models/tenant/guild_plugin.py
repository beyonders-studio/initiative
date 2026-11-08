"""A plug-in installed into a guild.

Guild-level by definition: a plug-in belongs to the guild rather than to any
initiative, which is the whole reason it exists — some content is guild-wide by
nature (a club's own events calendar), and a tool that lives in one initiative
cannot be that.

The row is *installation state*, not content. It records which listing was
installed, at which version, how the guild configured it (``config`` /
``secret_fields``) and what its settings hold (``settings`` /
``setting_aliases``). The content itself is an ordinary row in an ordinary table
— a guild-level ``calendars`` row, for instance — owned by the install and
governed by its own grants like anything else. That split is
deliberate: plug-ins mount existing tools at guild scope rather than introducing a
parallel one.

What an install produced is the guild-level content it owns: an owner grant
naming the install (``resource_grants.plugin_install_id``), which goes when the
install does. There is no list on this row to keep in step with it.

The secret values a guild admin typed into a plug-in's connection form live in
``guild_plugin_secrets``, encrypted per key, which the seat and the system engine
alone read. This row carries ``secret_fields``, which keys hold a value, so a
read reports only whether a value is present.

Managing plug-ins is the seat's action, which only its role writes; the row is readable by any member of the
guild, because the sidebar has to know a plug-in is there. What a member may do
*inside* a plug-in is decided by that instance's grants, not here.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import ConfigDict
from sqlalchemy import Boolean, Column, DateTime, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field

from app.models.tenant._mixins import CreatedByMixin


class GuildPlugin(CreatedByMixin, table=True):
    __tablename__ = "guild_plugins"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    __table_args__ = (
        # One install per listing. Enforced here rather than by the endpoint's
        # look-before-insert alone: two installs arriving together would both
        # find nothing and both create a calendar.
        UniqueConstraint("listing_uid", name="guild_plugins_unique_listing"),
    )

    id: int | None = Field(default=None, primary_key=True)

    # Provenance, exactly as an installed dashboard records it: the uid is the
    # identity that means the same listing on every deployment.
    listing_uid: str = Field(sa_column=Column(String(14), nullable=False, index=True))
    listing_version: str = Field(sa_column=Column(String(32), nullable=False))
    # Which kind of plug-in this is, copied from the installed definition so the
    # sidebar can render it without re-reading the catalog.
    plugin_kind: str = Field(sa_column=Column(String(32), nullable=False))

    # Display name, seeded from the listing and renameable per guild.
    name: str = Field(sa_column=Column(String(255), nullable=False))
    # Turned off without uninstalling: the plug-in disappears from the sidebar and
    # its content stays exactly where it is.
    enabled: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    # Whether a version the publisher releases is applied on its own.
    #
    # On by default, because an install that quietly falls behind its publisher
    # is the worse resting state: a fix reaches the guild without anyone having
    # to notice it exists. A guild that would rather read each version first
    # turns this off in its plug-in settings and applies them by hand — the same
    # re-pin, asked for rather than swept in.
    auto_update: bool = Field(
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )

    # The pinned snapshot of what was installed, so the plug-in keeps working at the
    # version this guild chose even if the listing changes or goes away.
    definition: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # Non-secret connection values, keyed by connection id then field key:
    # ``{"admin_read": {"shop_domain": "example.myshopify.com"}}``.
    config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # The same shape, holding a SHA-256 hex digest of each ciphertext in
    # ``guild_plugin_secrets``: the keys say which secret fields hold a value, and
    # a digest changes when its value does. Written by the trigger on
    # ``guild_plugin_secrets``, never by the plug-in.
    secret_fields: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # What the plug-in reported back about the configuration it was given:
    # ``unverified`` until it says otherwise, then ``ok`` or ``invalid``.
    # Presence of values is what this build can know by itself; whether a
    # credential carries the permissions it needs is the plug-in's to report.
    config_state: str = Field(
        default="unverified",
        sa_column=Column(String(16), nullable=False, server_default="unverified"),
    )
    #: The plug-in's own short code for an ``invalid`` state, shown beside it.
    config_state_detail: str | None = Field(
        default=None, sa_column=Column(String(120), nullable=True)
    )

    # The opaque handle the plug-in writes a guild-wide connection's result
    # against, keyed by connection id: ``{"workspace": "9f3c…"}``.
    #
    # Only for a ``static`` connection the plug-in fills by running the vendor's own
    # flow — an organization-wide install, which a guild admin performs once for
    # everybody. A typed connection needs none: nothing comes back from anywhere
    # to be matched to it.
    #
    # Minted when an admin starts the flow and kept afterwards, so reconnecting
    # keeps one identity rather than minting a new one each time; clearing the
    # connection drops it. The handle is what a write-back is matched on: it is
    # accepted for the connection its handle names, and only for a handle this
    # map holds.
    connection_refs: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    # The value of each setting the pinned definition declares, by key, as the
    # seat set it or Initiative assigned it: ``{"task_prefix": "acme"}``.
    settings: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # Each unique setting's earlier values, newest first, by key:
    # ``{"task_prefix": ["acmeold"]}``. They stay this install's
    # (``public.plugin_install_claims``) until it is removed. A setting never
    # renamed has no entry.
    setting_aliases: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    # The scopes the community's seat consented to for this install, from
    # ``app.core.plugin_scopes``. A subset of the scopes the manifest requested
    # and of the registration's ``scope_ceiling`` when it is written, at
    # install or afterwards. An upgrade does not rewrite it: what a token
    # carries is this set intersected with what the pinned manifest requests
    # now, so a scope a later version stops asking for stops working with it.
    granted_scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )

    # A newer version of the listing that asks for more than this install
    # holds: a scope it has not been granted, or a surface inside initiatives
    # the pinned version does not have. The auto-update sweep records it here
    # rather than applying it, and tells the seat once; the install keeps
    # running its pinned version until the seat accepts. Cleared when a
    # version is applied or the seat declines this one.
    pending_version: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    # The version the seat declined. The sweep does not ask about it again;
    # a newer version is asked about afresh. Cleared when a version is
    # applied.
    declined_version: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )

    created_by: int = Field(foreign_key="users.id", nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
