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
generalised: ``purpose`` is the sector. A sector that lives inside one guild —
an installed plug-in — also carries ``sector_guild_id`` + ``sector_id``; see
``services.marketplace.plugin_refs``.

Minted on the system engine, and read there for every sector but one: the
request path holds ``SELECT`` and a policy admitting ``client``, the sector an
account's own access token names it by (``services.auth.subject``).
"""

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import (
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
    #: A demo deployment's link (``demo_links``), named to the install that
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
    platform. ``plugin``'s sector is a single **install**, so its rows carry one
    in ``sector_guild_id`` + ``sector_id``: a plug-in installed in two guilds
    sees an unrelated reference for the same person in each.

    ``webhook``'s sector is one subscription, for a target nothing else here
    knows: a member's own URL rather than an installed plug-in. A subscription
    a plug-in registered is named in that plug-in's ``plugin`` sector instead,
    so the guild and the member arrive under the names it already holds.

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


class IdentityRef(SQLModel, table=True):
    """One reference: what one purpose calls one entity."""

    __tablename__ = "identity_refs"
    __table_args__ = (
        UniqueConstraint("ref", name="identity_refs_unique_ref"),
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
            "sector_id",
            unique=True,
            postgresql_where=text("retired_at IS NULL"),
            postgresql_nulls_not_distinct=True,
        ),
        # Removing an install's references, and a guild's. Neither can be a
        # foreign key: ``guild_plugins`` lives in a guild schema and this table
        # does not, so both are deleted explicitly.
        Index("ix_identity_refs_sector", "sector_guild_id", "sector_id"),
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

    #: Which guild the sector belongs to, for a purpose that has one. NULL for
    #: a platform-wide sector such as ``billing``.
    sector_guild_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    #: Which thing inside that guild is the sector — an install, for ``plugin``.
    #: Paired with ``sector_guild_id`` because these ids are per-guild-schema
    #: and so are not unique on their own.
    sector_id: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
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
