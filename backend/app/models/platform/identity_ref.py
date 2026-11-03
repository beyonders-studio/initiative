"""What a party outside this deployment calls a user or a guild.

An integer primary key is the right thing to join on and the right thing to
show a person who has to tell two rows apart. It is the wrong thing to hand to
a payment processor or an installed plug-in: it is sequential, it is the same value
everywhere, and every party holding one holds the same one.

So each entity gets a separate reference per *purpose* — billing, one installed
plug-in, the next — minted at random and stored here. Two references to the same
guild are unrelated values, and the party holding one learns nothing about the
other from it.

Random rather than derived from a key: a derived value is only stable while its
key is, and this deployment rotates ``SECRET_KEY``
(``app.db.secret_key_rotation``). A reference has to outlast that.

This is the pairwise pseudonymous identifier of OpenID Connect Core §8.1,
generalised: ``purpose`` is the sector. A plug-in's sector lives inside one
guild, so it also carries ``sector_guild_id``, and the plug-in's ``public_id``
in ``sector_plugin``. See ``services.marketplace.plugin_refs``. A webhook
subscription's sector is a row in a guild's own schema, and so are its names
(``models.tenant.webhook_ref``).

Minted on the system engine, and read there for every sector but one: the
request path holds ``SELECT`` and a policy admitting ``client``, the sector an
account's own access token names it by (``services.auth.subject``).
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import Field, SQLModel


class IdentityEntity(str, Enum):
    """What kind of row a reference names.

    Carried in the reference's own prefix, so a value minted for a user is
    rejected where a guild is expected rather than silently looked up.
    """

    user = "user"
    guild = "guild"
    #: A demo deployment's link (an invite into a pitch), named to the install that
    #: makes pitches there.
    demo_link = "demo_link"

    @property
    def code(self) -> str:
        """This entity's letter in a rendered reference."""
        return self.value[0]


class IdentityPurpose(str, Enum):
    """Which party a reference was minted for.

    The sector, in the OpenID Connect §8.1 sense: one entity has one reference
    per purpose, and the purposes are unrelated to each other.

    ``billing``'s sector is the deployment's billing service, one for the whole
    platform. ``plugin``'s sector is one **plug-in in one guild**, so its rows
    carry the guild in ``sector_guild_id`` and the plug-in's ``public_id`` in
    ``sector_plugin``: a plug-in installed in two guilds sees an unrelated
    reference for the same person in each, and the same reference again when a
    guild uninstalls it and installs it back. Only erasing the plug-in's data,
    or purging the guild, drops them.

    ``webhook``'s sector is one subscription, for a target nothing else here
    knows: a member's own URL rather than an installed plug-in. Its names are
    the guild's own, kept in its schema under the subscription
    (``models.tenant.webhook_ref``) and never in this table. A subscription a
    plug-in registered is named in that plug-in's ``plugin`` sector instead, so
    the guild and the member arrive under the names it already holds.

    ``client``'s sector is the deployment's own front ends — the browser tab
    and the native app, one sector for the platform. It names the account in an
    access token's ``sub`` (see ``services.auth.subject``), which makes it the
    one sector the request path resolves; the rest are read on the system
    engine.
    """

    billing = "billing"
    plugin = "plugin"
    webhook = "webhook"
    client = "client"

    @property
    def code(self) -> str:
        """This purpose's three letters in a rendered reference."""
        return self.value[:3]


def ref_prefix(entity_type: IdentityEntity, purpose: IdentityPurpose) -> str:
    """The prefix a reference for this entity and purpose is rendered with.

    Derived from the two enums rather than listed, so a new purpose gets a
    prefix by existing.
    """
    return f"{entity_type.code}{purpose.code}"


#: Characters of base64url in the random half — ``token_urlsafe(24)`` renders
#: as 32. Wide enough to sit in a JWT claim and a URL.
REF_ENTROPY_BYTES = 24
REF_RANDOM_LENGTH = 32

#: Width the column holds: prefix, separator, and the random half, with room
#: for a longer prefix than any purpose uses today.
REF_MAX_LENGTH = 64

#: How long a replaced reference keeps resolving. Long enough for the other
#: party to pick up the new value and for anything already in flight to land.
#: Held here rather than beside the minting code so the install standing
#: statement (``app.db.guild_standing``) honours the same window.
REF_GRACE_PERIOD = timedelta(days=30)


#: The widest ``sector_plugin`` held: a registration's ``public_id``
#: (``plugin_service_registration.MAX_PLUGIN_ID_LENGTH``).
SECTOR_PLUGIN_MAX_LENGTH = 120


class IdentityRef(SQLModel, table=True):
    """One reference: what one purpose calls one entity."""

    __tablename__ = "identity_refs"
    __table_args__ = (
        UniqueConstraint("ref", name="identity_refs_unique_ref"),
        # A ``plugin`` reference names its plug-in and the guild it is in, and
        # nothing else names either. A ``webhook`` one is kept in its guild's
        # own schema.
        CheckConstraint(
            "(purpose = 'plugin') = (sector_plugin IS NOT NULL)"
            " AND (purpose = 'plugin') = (sector_guild_id IS NOT NULL)"
            " AND purpose <> 'webhook'",
            name="identity_refs_plugin_sector",
        ),
        # One live reference per entity per sector. Retired rows are excluded
        # so a re-issue can sit beside the value it replaces for its grace
        # window.
        #
        # NULLS NOT DISTINCT so an unset sector compares equal to another
        # unset one: a platform-wide purpose leaves both columns NULL, and
        # Postgres's default reads NULLs as distinct, which is not the
        # uniqueness this index is for.
        Index(
            "ix_identity_refs_live",
            "entity_type",
            "entity_id",
            "purpose",
            "sector_guild_id",
            "sector_plugin",
            unique=True,
            postgresql_where=text("retired_at IS NULL"),
            postgresql_nulls_not_distinct=True,
        ),
        # Removing what one plug-in calls everyone in a guild, when the guild
        # erases its data, and what every plug-in there does, when it is
        # purged. Not a foreign key: a plug-in's sector outlives its install.
        Index("ix_identity_refs_sector_plugin", "sector_guild_id", "sector_plugin"),
        # Sweeping the rows a re-issue left behind.
        Index("ix_identity_refs_retired_at", "retired_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)

    #: The value the other party holds, prefix and all.
    ref: str = Field(sa_column=Column(String(REF_MAX_LENGTH), nullable=False))

    entity_type: IdentityEntity = Field(
        sa_column=Column(String(16), nullable=False),
    )
    #: Plain integer, no foreign key. Erasure husks the row it names
    #: (``services.platform.users.anonymize_user``) rather than removing it,
    #: and this row is dropped by the same path.
    entity_id: int = Field(sa_column=Column(Integer, nullable=False))

    #: Which sector this reference is for — see ``IdentityPurpose``.
    purpose: IdentityPurpose = Field(sa_column=Column(String(64), nullable=False))

    #: Which guild the sector belongs to, for ``plugin``. NULL for a
    #: platform-wide sector such as ``billing``.
    sector_guild_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    #: Which plug-in inside that guild is the sector, by its registration's
    #: ``public_id``, for ``plugin``. A name rather than a row id: an install
    #: row goes at uninstall and a registration row can be deleted and made
    #: again, and the reference has to outlast both.
    sector_plugin: Optional[str] = Field(
        default=None,
        sa_column=Column(String(SECTOR_PLUGIN_MAX_LENGTH), nullable=True),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    #: When this value was replaced. NULL while it is the live one; set by a
    #: re-issue, after which the row stays resolvable for the grace window.
    retired_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
