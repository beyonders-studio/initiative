"""State the registry client keeps between refreshes.

Three `public` tables, all operator/system state rather than tenant data:

* :class:`MarketplaceTufMetadata` — the TUF metadata this deployment last
  verified, one row per role (and one per root version). A refresh loads it
  into a scratch directory for the TUF client and writes back what the client
  verified, so every replica starts from the same trusted state and a restart
  does not forget which versions were already seen.
* :class:`MarketplaceRegistryStatus` — one row: which trusted root the stored
  metadata was verified under, and how the last refresh went.
* :class:`MarketplaceMedia` — the artwork a verified listing named, kept
  locally and addressed by its own SHA-256. Listing media is served from this
  deployment, so a stored listing never carries a URL pointing at somebody
  else's host.

None of them names a guild. Like the catalog they describe they are
platform-wide, and their only writer is the system engine.
"""

from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlmodel import Field, SQLModel

#: A hex SHA-256 digest is always this long, and the columns holding one are
#: sized to it exactly.
DIGEST_LENGTH = 64

#: The widest TUF role name stored. Delegated roles are named after publisher
#: prefixes, which are shorter than this.
ROLE_NAME_LENGTH = 200

#: The id of the one status row.
STATUS_ROW_ID = 1


class MarketplaceTufMetadata(SQLModel, table=True):
    """One verified TUF metadata file.

    Keyed by role and version. ``root`` keeps a row per version, because the
    client replays the chain of roots from the one shipped in the image; every
    other role keeps only its current version.
    """

    __tablename__ = "marketplace_tuf_metadata"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    role: str = Field(
        sa_column=Column(String(ROLE_NAME_LENGTH), primary_key=True, nullable=False)
    )
    version: int = Field(
        sa_column=Column(Integer, primary_key=True, nullable=False, autoincrement=False)
    )
    # The metadata file exactly as it was verified.
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class MarketplaceRegistryStatus(SQLModel, table=True):
    """How this deployment stands with its registry: one row."""

    __tablename__ = "marketplace_registry_status"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)
    __table_args__ = (
        CheckConstraint(
            f"id = {STATUS_ROW_ID}", name="marketplace_registry_status_one_row"
        ),
    )

    id: int = Field(
        default=STATUS_ROW_ID,
        sa_column=Column(Integer, primary_key=True, autoincrement=False),
    )
    # SHA-256 of the trusted root the stored metadata was verified under. A
    # deployment pointed at a different root starts over rather than reading
    # metadata from another chain of trust.
    root_sha256: str | None = Field(
        default=None, sa_column=Column(String(DIGEST_LENGTH))
    )
    # The version of the newest root the last verified refresh reached.
    root_version: int | None = Field(default=None, sa_column=Column(Integer))
    # The snapshot version last applied. The same version again means the
    # repository has not changed, and its listings are not read again.
    snapshot_version: int | None = Field(default=None, sa_column=Column(Integer))
    # When the verified timestamp stops being valid. Past it the catalogue from
    # the registry is stale until a refresh succeeds.
    expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    # Where the last attempt read from: the registry URL, or ``bundle`` for an
    # uploaded bundle.
    source: str | None = Field(default=None, sa_column=Column(String(2000)))
    last_attempt_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    # When a refresh last completed with every listing applied.
    last_success_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    # Message code of the last refusal, or NULL after a clean refresh.
    last_error: str | None = Field(default=None, sa_column=Column(String(64)))
    # How many listings the last verified repository carried.
    listing_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class MarketplaceMedia(SQLModel, table=True):
    """One mirrored listing image, addressed by the digest of its bytes.

    Content-addressed, so re-publishing an unchanged image is a no-op and the
    serving URL can be cached forever. The bytes are small (icons and
    screenshots) and platform-wide rather than per-guild, which is why they
    live in Postgres beside the catalog rather than in the guild blob store.
    """

    __tablename__ = "marketplace_media"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int | None = Field(default=None, primary_key=True)
    sha256: str = Field(
        sa_column=Column(String(DIGEST_LENGTH), nullable=False, unique=True)
    )
    # Taken from the signed index, not from the response that delivered the
    # bytes, and restricted to a small set of raster image types.
    content_type: str = Field(sa_column=Column(String(64), nullable=False))
    byte_size: int = Field(sa_column=Column(Integer, nullable=False))
    data: bytes = Field(sa_column=Column(LargeBinary, nullable=False))
    # Where the bytes came from, for support questions about a mirrored image.
    source_url: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
