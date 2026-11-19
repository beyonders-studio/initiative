"""Deployment-level registrations for external plug-in services.

A marketplace **listing** says what a plug-in is and what it declares. A
**registration** is this deployment's record that it runs that plug-in. Every plug-in
splits the same way, whatever published its listing:

* **Plug-in facts** come from the plug-in's listing, and only a listing apply writes
  them: ``listing_uid``, ``scope_ceiling``, ``image_digest``, ``compose`` and,
  from its latest version's manifest, ``availability``. Every source reads the same
  ``registration`` block (the registry, a local upload, the operator's catalog
  directory, the build).
* **Deployment facts** come from the operator, through ``PLUGIN_SERVICES_CONFIG``
  or the settings form: where the plug-in runs, the public keys its container signs
  with, its vendor values, the mandatory flag and the origins. Suspending it
  everywhere is the owner's alone (``suspended_at``), and so is the list of
  communities a beta plug-in reaches (``plugin_beta_communities``).

A registration holds no secret beyond its vendor values. Every call the plug-in
makes to Initiative is a JWT it signs with a key published here (``jwks``, or
``jwks_uri`` on its own origin), and every call Initiative makes to the plug-in is
a JWT under the plug-in platform's own key.

Some columns exist only because of that split:

* ``listing_uid`` — the catalog listing this registration's plug-in facts come
  from. It is what ties the registration to the installs it may reach. Null on
  a registration the operator set up before its listing arrived.
* ``publisher_id`` — the publisher the ``public_id`` prefix names
  (:mod:`app.models.platform.publisher`). Its switch outranks the
  registration's own.
* ``scope_ceiling`` — the most any install of this plug-in may be granted, from
  the plug-in scope vocabulary (``app.core.plugin_scopes``). A community's seat grants
  within it; nothing outside it can be granted. Empty means nothing may be.
* ``mandatory`` — the deployment asserts this plug-in is part of what it *is*, so
  every guild has it and guild admins cannot remove it. A suspension
  (``suspended_at``) still outranks it.
* ``availability`` — which communities the plug-in reaches, as its manifest
  declares (:class:`PluginAvailability`): every one; for ``beta``, the communities
  the owner picks (:class:`PluginBetaCommunity`); for ``operations``, the
  deployment's operations community (``app_settings.operations_guild_id``),
  and none while none is named. Out of reach, it is suspended: offered
  nowhere, installed by the mandatory sweep nowhere, and live nowhere.
* ``shared_routes`` — one vendor installation may route to several communities.
  Off, each route of its installs is held by one community
  (``plugin_installs.exclusive``).

* ``vendor_values`` — what the operator supplies for the plug-in's vendor client,
  as the listing's manifest declares it under ``vendor``: one Fernet
  ciphertext per field. ``vendor_ready`` is whether every field the manifest
  requires (``vendor_required``) holds one, computed by the database.

* ``kind`` — ``container`` for a plug-in Initiative calls, ``declarative`` for
  one whose calls Initiative makes itself from its manifest, ``tool`` for one
  that declares a tool. Only a container's registration has a location and
  keys.

**Live** is one rule, stated once in :func:`registration_live_sql`: the
registration is not suspended, its publisher is enabled, its required vendor
values are set and, for a container, it has a location and a key set to verify
against; and, asked for one community, the community is in its reach
(``availability``), and the community's install is neither suspended, on hold
nor deleted (``plugin_installs``).
The install standing, the registration snapshot and every channel that reads
a single row ask it in that form.

**Where its plug-in facts came from** is ``source``: ``registry`` for a listing
the registry signed, ``operator`` for a listing this deployment published
itself, or for a registration whose listing has not arrived yet.

Lives in ``public``: a registration is platform-wide and carries no guild data.
It is written on the system engine by ``plugins.manage`` (owner) endpoints, by
boot reconciliation from ``PLUGIN_SERVICES_CONFIG``, and by listing applies.
"""

from collections.abc import Collection
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol

from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, SQLModel

from app.core.encryption import FERNET_SALT, SALT_PLUGIN_VENDOR
from app.models.platform.plugin_install import PluginInstallStatus

__all__ = [
    "IMAGE_REFERENCE_MAX_LENGTH",
    "LISTING_STATED_FIELDS",
    "MAX_PLUGIN_ID_LENGTH",
    "BrowserAddressed",
    "PluginAvailability",
    "PluginBetaCommunity",
    "PluginServiceRegistration",
    "RegistrationKind",
    "RegistrationSource",
    "browser_base",
    "in_reach_sql",
    "reach",
    "registration_live_sql",
]

#: The widest ``public_id`` a registration may carry. A plug-in id longer than
#: this cannot name a registration, so it is refused without a query.
MAX_PLUGIN_ID_LENGTH = 120

#: The widest container image reference stored.
IMAGE_REFERENCE_MAX_LENGTH = 500

#: What only a plug-in's listing states. A ``PLUGIN_SERVICES_CONFIG`` entry or a
#: settings request naming one is refused: it gives deployment facts only.
LISTING_STATED_FIELDS: tuple[str, ...] = (
    "listing_uid",
    "kind",
    "scope_ceiling",
    "image",
    "image_digest",
    "registry",
    "compose",
    "availability",
)


class PluginAvailability(str, Enum):
    """Which communities a plug-in reaches, as its manifest declares it (the
    contract's ``availability``)."""

    #: Every community.
    none = "none"
    #: The communities the owner picks, none until they do.
    beta = "beta"
    #: The deployment's operations community.
    operations = "operations"


def reach(
    availability: str,
    *,
    operations_guild_id: int | None,
    beta: Collection[int],
) -> frozenset[int] | None:
    """The communities a plug-in of ``availability`` reaches, ``None`` for
    every one: the operations community ``operations_guild_id`` names, or the
    owner's ``beta`` list. The Python spelling of the reach clause in
    :func:`registration_live_sql`."""
    if availability == PluginAvailability.operations.value:
        return frozenset(() if operations_guild_id is None else (operations_guild_id,))
    if availability == PluginAvailability.beta.value:
        return frozenset(beta)
    return None


class RegistrationKind:
    """Which kind of plug-in a registration is for, as its listing says."""

    #: Initiative calls the plug-in's container.
    CONTAINER = "container"
    #: Initiative makes the plug-in's calls itself, from its manifest.
    DECLARATIVE = "declarative"
    #: The plug-in declares a tool, which Initiative serves as its own.
    TOOL = "tool"


class RegistrationSource:
    """Where a registration's plug-in facts came from."""

    #: A listing this deployment published itself, or none yet.
    OPERATOR = "operator"
    #: A listing the registry signed.
    REGISTRY = "registry"


def in_reach_sql(registration: str, community: str) -> str:
    """Whether the registration row ``registration`` names reaches the
    community the SQL expression ``community`` names: the SQL spelling of
    :func:`reach`. ``NULL`` for an ``operations`` registration where the
    deployment names no operations community."""
    return (
        f"({registration}.availability = '{PluginAvailability.none.value}'"
        f" OR ({registration}.availability = '{PluginAvailability.operations.value}'"
        f" AND {community} = (SELECT s.operations_guild_id"
        " FROM public.app_settings s WHERE s.id = 1))"
        f" OR ({registration}.availability = '{PluginAvailability.beta.value}'"
        " AND EXISTS (SELECT 1 FROM public.plugin_beta_communities b"
        f" WHERE b.listing_uid = {registration}.listing_uid"
        f" AND b.community_id = {community})))"
    )


def registration_live_sql(
    registration: str = "plugin_service_registrations",
    publisher: str = "publishers",
    community: str | None = None,
) -> str:
    """Whether a registration is live, as a SQL boolean over one registration
    row and its publisher's row, named by ``registration`` and ``publisher``.

    Given ``community``, a SQL expression naming one community's id, it is live
    in that community: the community is in its reach (an ``operations``
    registration's is the community ``app_settings.operations_guild_id``
    names, a ``beta`` one's the communities on its list), and the community's
    install of its listing is not suspended, on hold or deleted. Without it, the answer is the registration's own, wherever it is
    limited to.

    Not suspended, its publisher enabled, and every required vendor value set; and
    for a container, a location and a key set to verify against (a pasted set
    with at least one key, or a key set address). ``-> 0`` reads the first key
    and is null for an empty or absent set.

    A container's registration lacks both until the operator gives them: its
    listing names the plug-in, and the operator says where it runs and which keys
    it signs with. A declarative plug-in runs nowhere and signs nothing.
    """
    reach = (
        ""
        if community is None
        else (
            f" AND {in_reach_sql(registration, community)}"
            " AND NOT EXISTS (SELECT 1 FROM public.plugin_installs i"
            f" WHERE i.guild_id = {community}"
            f" AND i.listing_uid = {registration}.listing_uid"
            " AND (i.suspended_at IS NOT NULL"
            f" OR i.status IN ('{PluginInstallStatus.on_hold.value}',"
            f" '{PluginInstallStatus.deleted.value}')))"
        )
    )
    return (
        f"({registration}.suspended_at IS NULL AND {publisher}.enabled"
        f" AND {registration}.vendor_ready"
        f" AND ({registration}.kind = '{RegistrationKind.DECLARATIVE}'"
        f" OR ({registration}.base_url IS NOT NULL"
        f" AND ({registration}.jwks_uri IS NOT NULL"
        f" OR {registration}.jwks -> 'keys' -> 0 IS NOT NULL))){reach})"
    )


class PluginServiceRegistration(SQLModel, table=True):
    """One plug-in service this deployment has wired up."""

    __tablename__ = "plugin_service_registrations"
    __table_args__ = (
        CheckConstraint(
            "availability IN ("
            + ", ".join(f"'{value.value}'" for value in PluginAvailability)
            + ")",
            name="ck_plugin_service_registrations_availability",
        ),
    )
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int | None = Field(default=None, primary_key=True)
    # '<publisher>.<slug>', matching the listing's public_id. Unique: one
    # registration per plug-in per deployment.
    public_id: str = Field(
        sa_column=Column(String(MAX_PLUGIN_ID_LENGTH), nullable=False, unique=True)
    )
    # The catalog uid of the listing this registration's plug-in facts come from,
    # written by that listing's apply. Null until the listing arrives; such a
    # row reaches no install.
    listing_uid: str | None = Field(
        default=None, sa_column=Column(String(14), nullable=True, index=True)
    )
    # The publisher the public_id's prefix names.
    publisher_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("publishers.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    # Base of the service's wire surface: its data and lifecycle endpoints
    # hang off it, and a ``jwks_uri`` must share its origin. Every consumer of
    # this column is Initiative's own server calling the plug-in. NULL until the
    # operator places it, and not live until they do.
    base_url: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    # Base of the service's browser surface: the iframe a page opens in and the
    # page a member is sent to for an interactive connection. Unset means the
    # plug-in answers both surfaces at one address, which is the ordinary case and
    # what every registration written before this column existed says.
    page_origin: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    # Origins this plug-in's pages may be framed from and postMessage'd
    # to. Defaults to the browser base's own origin.
    allowed_origins: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    # Public half of the keys this plug-in signs with, in JWKS shape: the client
    # assertions it presents at the token endpoint.
    # A set rather than one key because a plug-in rotates by publishing the
    # replacement alongside the current entry while JWTs signed by the first
    # drain out; every entry carries a ``kid``, which is what a JWT names.
    # Public keys only. Null on a plug-in that has not been provisioned with one.
    jwks: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    # Where the plug-in publishes that key set instead, on ``base_url``'s own
    # origin over https. Fetched and cached for a minute; either or both may
    # be set, and a key found in either verifies.
    jwks_uri: str | None = Field(
        default=None, sa_column=Column(String(1000), nullable=True)
    )
    # The most an install of this plug-in may be granted (see module docstring),
    # from its listing. Only scopes ``app.core.plugin_scopes`` defines are kept.
    scope_ceiling: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    # Auto-installed into every guild and not removable by guild admins.
    mandatory: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Which communities it reaches (``PluginAvailability``), from its listing's
    # latest version.
    availability: str = Field(
        default=PluginAvailability.none.value,
        sa_column=Column(Text, nullable=False, server_default="none"),
    )
    # One vendor installation may route to several communities.
    shared_routes: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # The owner suspended it everywhere, and who did: nothing flows through it
    # and no community sees it until the suspension is lifted.
    suspended_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    suspended_by: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    # Which kind of plug-in it is for (``RegistrationKind``), from its listing.
    kind: str = Field(
        default=RegistrationKind.CONTAINER,
        sa_column=Column(String(16), nullable=False, server_default="container"),
    )
    # Where its plug-in facts came from (``RegistrationSource``).
    source: str = Field(
        default=RegistrationSource.OPERATOR,
        sa_column=Column(String(16), nullable=False, server_default="operator"),
    )
    # The container image its listing names, pinned by digest
    # (``<repository>@sha256:<hex>``). NULL when the listing names none.
    image_digest: str | None = Field(
        default=None,
        sa_column=Column(String(IMAGE_REFERENCE_MAX_LENGTH), nullable=True),
    )
    # The Compose service its listing's publisher wrote for running the plug-in
    # beside Initiative: ``{"service": <YAML text>, "base_url": <address on
    # the Compose network>}``, its placeholders unfilled. NULL when the listing
    # carries none.
    compose: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    # What the operator supplies for the plug-in's vendor client, by the key the
    # listing's manifest declares under ``vendor``. Every value is a Fernet
    # ciphertext under ``SALT_PLUGIN_VENDOR``, secret or not.
    vendor_values: dict = Field(
        default_factory=dict,
        sa_column=Column(
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
            info={FERNET_SALT: SALT_PLUGIN_VENDOR},
        ),
    )
    # The keys the listing's manifest marks required, kept in step whenever the
    # registration or its listing is written.
    vendor_required: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    # Whether every required key holds a value. Computed by the database.
    vendor_ready: bool | None = Field(
        default=None,
        sa_column=Column(
            Boolean,
            Computed("vendor_values ?& vendor_required", persisted=True),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class BrowserAddressed(Protocol):
    """Anything carrying a registration's two addresses.

    The row and the request path's snapshot of it both do, and both need the
    same answer, so the rule that relates them is written once.
    """

    base_url: str
    page_origin: str | None


def browser_base(registration: BrowserAddressed) -> str:
    """The base a person's browser resolves for this plug-in's surfaces.

    ``page_origin`` when the deployment gave one, ``base_url`` otherwise — an
    plug-in reachable at a single address needs no second field to say so.
    """
    return registration.page_origin or registration.base_url


class PluginBetaCommunity(SQLModel, table=True):
    """A community the owner picked for a beta plug-in, by its listing.

    The list is the whole reach of a plug-in whose ``availability`` is
    ``beta``, and goes when it stops being: the apply that moves it off
    ``beta`` deletes its listing's rows.
    """

    __tablename__ = "plugin_beta_communities"

    listing_uid: str = Field(
        sa_column=Column(
            String(14),
            ForeignKey("marketplace_listings.uid", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    community_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("guilds.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        )
    )
    added_by: int | None = Field(
        default=None,
        sa_column=Column(
            Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
