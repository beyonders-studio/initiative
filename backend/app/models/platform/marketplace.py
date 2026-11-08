"""The marketplace catalog — what is *installable*, platform-wide.

Two `public` tables. They hold catalog metadata only: a listing's identity,
its artwork, and the reference definition at each published version. There is
deliberately **no `guild_id` column anywhere here** — installs are per-guild
data and stay in the guild's own schema, so the catalog carries none of it.

Guild-schema serials restart per guild, so a shared surface cannot key anything
off a local id. `uid` is the catalog's answer: a publisher-assigned, immutable
14-character code that means the same listing on every deployment carrying that
catalog. Instances need no uid — one is already addressable as
`/c/{community_id}/dashboards/{id}` — they just store `listing_uid` to point back at
where they came from, which is what keeps provenance across an export/import.

Writes happen on the system-engine path only (boot seeding, and later the
registry refresh). A user request reads the catalog and writes its own guild
schema; nothing about installing a listing writes here.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import ConfigDict
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, Relationship, SQLModel

#: Length of a listing uid. Crockford base32 at 14 characters is short enough to
#: read aloud or print, and long enough that codes are not guessable.
UID_LENGTH = 14

#: Crockford base32 minus the letters it treats as ambiguous (I, L, O, U), so a
#: code can be transcribed by hand without a legend.
UID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


#: Who may install a listing a package names (``MarketplaceListing.access``).
ACCESS_OPEN = "open"
ACCESS_ENTITLED = "entitled"

#: The two shapes a listing's package terms take, and the shape of none.
LISTING_TERMS_CHECK = (
    "(access IS NULL AND NOT mandatory AND cardinality(meters) = 0)"
    " OR (access = 'entitled' AND NOT mandatory AND cardinality(meters) = 0)"
    " OR (access = 'open' AND mandatory)"
)


class MarketplaceListing(SQLModel, table=True):
    """One installable product, at whatever versions it has published."""

    __tablename__ = "marketplace_listings"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        CheckConstraint(
            LISTING_TERMS_CHECK, name="ck_marketplace_listings_package_terms"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    # The catalog UPC. Assigned by the publisher and carried in the manifest —
    # minting it per deployment would make the code deployment-specific, so a
    # shared link or a printed code would resolve to nothing anywhere else.
    # UNIQUE and never reassigned: a uid keeps meaning the listing it was first
    # published for.
    uid: str = Field(sa_column=Column(String(UID_LENGTH), nullable=False, unique=True))
    # Human-readable identity: 'core.project-health', '<publisher>.<slug>'.
    public_id: str = Field(sa_column=Column(String(120), nullable=False, unique=True))
    kind: str = Field(sa_column=Column(String(16), nullable=False, index=True))
    source: str = Field(sa_column=Column(String(16), nullable=False))

    name: str = Field(sa_column=Column(String(200), nullable=False))
    # Who publishes it, and the namespace it publishes under. Required, so the
    # question "who is this from?" is answered before install rather than after;
    # NOT NULL, so the requirement holds at the database as well as in the
    # validator. A registry listing's prefix is the delegation that signed it.
    publisher: str = Field(sa_column=Column(String(200), nullable=False))
    # The publisher record a registry listing arrived under, and whether that
    # record was verified when it was applied. NULL and false for every other
    # source.
    publisher_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("publishers.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    publisher_verified: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    description: str = Field(sa_column=Column(String(500), nullable=False))
    long_description: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # Custom art, required: a listing is branded, not a default icon.
    avatar_url: str = Field(sa_column=Column(String(2000), nullable=False))
    images: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )

    latest_version_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            # SET NULL rather than CASCADE: losing the pointer must never take
            # the listing with it.
            ForeignKey(
                "marketplace_listing_versions.id",
                ondelete="SET NULL",
                # The two tables point at each other, so neither can be created
                # with both constraints in place; `use_alter` adds this one
                # afterwards, which is what the migration does by hand.
                use_alter=True,
                name="fk_marketplace_listings_latest_version",
            ),
            nullable=True,
        ),
    )
    # A cumulative count of installs on this deployment. Just the number: no
    # guild is recorded. Uninstalling does not decrement.
    installs_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    # Set on a dashboard listing a plug-in ships with itself; NULL on anything
    # published on its own.
    #
    # A bundled dashboard is an ordinary listing in every other respect — same
    # kind, same uid rules, installed by the same call — because a dashboard
    # somebody publishes to share and a dashboard that arrives with a plug-in are
    # the same thing to the guild installing it. This column carries the two
    # ways they differ: it is offered only to guilds that have that plug-in, and it
    # is published and withdrawn with the plug-in rather than on its own.
    #
    # The uid rather than a foreign key. Both rows come from one manifest, and a
    # referential cascade here would be a second mechanism for a lifecycle the
    # publish already owns.
    bundled_with_uid: str | None = Field(
        default=None,
        sa_column=Column(String(UID_LENGTH), nullable=True, index=True),
    )
    # Who shared a ``local`` listing, when a member did: the one account that
    # may publish a new version of it or take it down. NULL for every other
    # source, and for one the operator uploaded.
    submitted_by: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    # The terms a package signs for this listing (``entitlements/<uid>.json``
    # under the registry's ``package`` role), honoured only from the registry
    # verified under the root shipped in the image. ``access`` is who may
    # install it: ``open`` (anyone) or ``entitled`` (a community holding an
    # active entitlement statement); NULL for every listing no package names,
    # which is every listing from any other source. ``meters`` are the usage
    # counters its plug-in may report, and ``mandatory`` makes it part of every
    # community. Only two shapes exist: ``entitled`` with neither, or ``open``
    # and mandatory, which may meter.
    access: str | None = Field(
        default=None, sa_column=Column(String(16), nullable=True)
    )
    meters: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default=text("'{}'")),
    )
    mandatory: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # False once a registry withdraws a listing. Never deleted: installed
    # instances keep working and keep their provenance.
    available: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    versions: list["MarketplaceListingVersion"] = Relationship(
        back_populates="listing",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "foreign_keys": "MarketplaceListingVersion.listing_id",
        },
    )


class MarketplaceListingVersion(SQLModel, table=True):
    """One published version of a listing, with the definition it ships.

    The definition lives here so the catalog is self-describing and installing is
    a pure server-side copy — nothing a client sends decides what gets stored.
    The installed instance keeps its own snapshot, so a new version reaches a
    guild only when someone there chooses it.
    """

    __tablename__ = "marketplace_listing_versions"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        # A listing publishes each version string once.
        UniqueConstraint("listing_id", "version"),
    )

    id: int | None = Field(default=None, primary_key=True)
    listing_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("marketplace_listings.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )
    version: str = Field(sa_column=Column(String(32), nullable=False))
    definition: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # The same thing filled in, for a tool listing that has one: a finished
    # character beside the blank sheet, a project mid-flight beside its
    # skeleton. Held to the same validator as ``definition``, and installable
    # in its place when the installer asks to start from it. NULL on every
    # other kind, and on a listing that shows only what it installs.
    example: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    release_notes: str | None = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # Compared against this deployment's VERSION. A version that needs a newer
    # app is hidden from browse and refused on upgrade, rather than installing
    # something that cannot render.
    min_app_version: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    # The oldest plug-in API contract (``MAJOR.MINOR``) the version needs,
    # compared against the contract this deployment serves (the plug-in SDK
    # version it vendors). A version this deployment cannot run is refused on
    # install and upgrade. NULL runs on any contract.
    min_plugin_api: str | None = Field(
        default=None, sa_column=Column(String(32), nullable=True)
    )
    published_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # A version a member shared that the operator has not yet approved. It is
    # stored but not the listing's latest, so nothing offers or installs it;
    # approving it makes it the latest, and refusing it deletes it.
    awaiting_review: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )

    listing: MarketplaceListing | None = Relationship(
        back_populates="versions",
        sa_relationship_kwargs={"foreign_keys": "MarketplaceListingVersion.listing_id"},
    )
