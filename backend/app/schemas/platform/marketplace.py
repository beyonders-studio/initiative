"""What the marketplace surface sees.

Catalog metadata only. A listing carries no tenant data — no guild ever appears
in these payloads — and "who installed this" is answered per-guild by the tool's
own endpoints rather than by anything here.

Which listings a guild is *offered* is a different question, decided by the
guild-addressed shelf; these payloads describe a listing the same way wherever
it is served from, which is what keeps a card and the page it opens in
agreement.
"""

from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import RawTextStr, SanitizedBaseModel, TitleStr
from app.schemas.query import PageMeta
from app.services.import_engine.contract import EnvelopeImportResult
from app.services.marketplace.definitions import (
    LISTING_KINDS,
    LISTING_SOURCES,
    published_by_us,
)

if TYPE_CHECKING:
    from app.models.platform.marketplace import (
        MarketplaceListing,
        MarketplaceListingVersion,
    )

# Derived from the validator's own set rather than restated, the way WidgetType
# derives from the widget registry: a new kind reaches the API — and, through
# the generated types, the frontend — without an edit here.
ListingKind = Enum(
    "ListingKind", {name: name for name in sorted(LISTING_KINDS)}, type=str
)
ListingKind.__doc__ = "What a marketplace listing installs as."

# Derived the same way. The client branches on it — listings shipped in this
# build are credited to us rather than to whatever their manifest claims — so
# the closed vocabulary belongs in the schema the client is generated from
# rather than arriving as a bare string it has to guess at.
ListingSource = Enum(
    "ListingSource", {name: name for name in sorted(LISTING_SOURCES)}, type=str
)
ListingSource.__doc__ = "How a listing reached this deployment."


class MarketplaceVersionRead(SanitizedBaseModel):
    """One published version of a listing."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: str
    release_notes: str | None = None
    min_app_version: str | None = None
    published_at: datetime
    #: Whether this deployment can install it: new enough, and serving the
    #: plug-in API contract it needs. A version it cannot run is shown, not
    #: hidden, so the reason is legible.
    compatible: bool = True


class ListingUnavailableReason(str, Enum):
    """Why this community cannot install a listing it is offered."""

    #: The listing installs only in a community holding an active
    #: entitlement for it.
    entitlement_required = "entitlement_required"
    #: The deployment's term for the listing has no seat left for this
    #: community: the way on is a request to the deployment's owners, so the
    #: listing is shown with one, never hidden.
    term_full = "term_full"


class ListingUnavailable(SanitizedBaseModel):
    """A listing the asking community is shown and cannot install yet."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    reason: ListingUnavailableReason
    #: Where the community can do something about it, when this deployment
    #: has somewhere: a page of its billing portal, opened with a handoff.
    action_url: str | None = None


class MarketplaceListingSummary(SanitizedBaseModel):
    """A listing as it appears on a browse card."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: This deployment's row id. What a report names the listing by; the uid
    #: and public id are its identity everywhere else.
    id: int
    uid: str
    public_id: str
    kind: ListingKind  # type: ignore[valid-type]
    #: How the listing reached this deployment. The client credits listings
    #: shipped in this build to us rather than to whatever a manifest claims.
    source: ListingSource  # type: ignore[valid-type]
    name: str
    #: Who publishes it. Required in the catalog, so this is always present.
    publisher: str
    #: Whether this project publishes it, so it is neither reported nor
    #: introduced as somebody else's.
    first_party: bool
    description: str
    avatar_url: str
    images: list[str] = []
    installs_count: int = 0
    available: bool = True
    latest_version: MarketplaceVersionRead | None = None
    #: False when nothing about this listing can be installed on this build —
    #: withdrawn, or its only versions need a newer app.
    installable: bool = True
    #: Set when the asking community cannot install it yet, and why. Absent on
    #: every surface that is not asked from a community.
    unavailable: ListingUnavailable | None = None
    updated_at: datetime


class MarketplaceListingDetail(MarketplaceListingSummary):
    """A listing's full page, including what it would install."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    long_description: str | None = None
    #: The reference definition at the latest version — the preview the detail
    #: page renders. Installing does not send this back; the server re-reads the
    #: catalog, so nothing a client holds decides what gets stored.
    definition: dict[str, Any] | None = None
    #: What the preview's Example toggle shows. For a tool made of content,
    #: the same envelope filled in, when the listing carries one, and what
    #: "start from the example" installs. For a dashboard, sample answers by
    #: widget id (``{columns, rows, truncated, relations}``, the query
    #: surface's shape): generated from its queries unless the publisher
    #: supplied their own, always present, and never installable. Display
    #: data, like the definition above.
    example: dict[str, Any] | None = None
    #: For a plug-in: the scopes its latest version asks a community to grant,
    #: in vocabulary order. Using a plug-in the community does not have is left
    #: out. Empty for every other kind.
    requested_scopes: list[str] = []
    #: The requested scopes this deployment's registration lets a community
    #: grant. What the install dialog offers ticked; the rest are shown
    #: disabled.
    grantable_scopes: list[str] = []
    #: For each requested ``plugins:`` scope, the name the plug-in it lets this one
    #: use goes by, keyed by that plug-in's public id. Its public id when the
    #: catalog has no name for it.
    plugin_names: dict[str, str] = {}
    #: Whether the plug-in offers a surface inside initiatives — a page there,
    #: or fields, sections or actions on items — and so has somewhere to be
    #: placed.
    has_initiative_surfaces: bool = False
    #: For a plug-in: the installs here that ask to use it, which the install
    #: dialog asks the seat about.
    callers: list["MarketplaceListingCaller"] = []


class MarketplaceListingCaller(SanitizedBaseModel):
    """An install that asks to use the plug-in a listing would install."""

    id: int
    name: str


class ListingStartFrom(str, Enum):
    """What an install copies: the listing itself, or its example."""

    blank = "blank"
    example = "example"


class MarketplaceInstallRequest(SanitizedBaseModel):
    """Install a tool listing: import a copy of it into an initiative."""

    initiative_id: int
    start_from: ListingStartFrom = ListingStartFrom.blank
    #: Where the listing's dates land: its earliest one falls on this day, and
    #: the rest keep their distance from it. Today when omitted.
    starts_on: date | None = None


class MarketplaceInstallResult(SanitizedBaseModel):
    """What installing a tool listing created."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: ListingKind  # type: ignore[valid-type]
    listing_uid: str
    listing_version: str
    #: The import's own report: what was created, under which id and name.
    result: EnvelopeImportResult


class MarketplaceShareRequest(SanitizedBaseModel):
    """Share an item from this community to the deployment's marketplace.

    The item is exported and stripped to what belongs to the work: nobody it
    names, nothing it links to outside itself, no uploads. ``listing_uid``
    publishes it as a new version of a listing the member shared before, which
    keeps that listing's name and description.
    """

    kind: ListingKind  # type: ignore[valid-type]
    entity_id: int
    #: The same tool's item, filled in, shown beside the listing as its example.
    example_entity_id: int | None = None
    name: TitleStr = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=500)
    long_description: str | None = Field(default=None, max_length=10_000)
    release_notes: str | None = Field(default=None, max_length=2_000)
    listing_uid: str | None = Field(default=None, max_length=14)


class MarketplaceShareResult(SanitizedBaseModel):
    """What a share published, and whether it waits for the owner's review."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    uid: str
    public_id: str
    version: str
    awaiting_review: bool


class MarketplaceSharedListingRead(MarketplaceListingSummary):
    """A listing the signed-in member shared, with anything still waiting."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Versions submitted and not yet approved, oldest first.
    pending_versions: list[str] = []


class MarketplacePendingVersionRead(SanitizedBaseModel):
    """A shared version waiting for the owner's review, with what it would
    publish."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    uid: str
    public_id: str
    kind: ListingKind  # type: ignore[valid-type]
    name: str
    publisher: str
    description: str
    version: str
    release_notes: str | None = None
    submitted_at: datetime
    #: Whether this is the listing's first version, or a new one of a listing
    #: already on the shelf.
    is_new_listing: bool
    definition: dict[str, Any]
    example: dict[str, Any] | None = None


class ListingUploadRequest(SanitizedBaseModel):
    """A listing file the owner uploads: the manifest a catalog directory or a
    registry carries, published as a ``local`` listing."""

    manifest: dict[str, Any]


class ListingMediaRead(SanitizedBaseModel):
    """A picture uploaded to the marketplace's media."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Where it is served from, for a manifest to name.
    path: str


class ListingUploadResult(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    uid: str
    public_id: str
    version: str


class MarketplaceLocalSettings(SanitizedBaseModel):
    """How this deployment takes its members' shares."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: Whether a share goes on the shelf straight away. Off, each one waits for
    #: the owner to approve it.
    members_publish_directly: bool


class MarketplaceListingPage(PageMeta):
    items: list[MarketplaceListingSummary]


def serialize_version(
    version: Optional["MarketplaceListingVersion"],
) -> MarketplaceVersionRead | None:
    # Local import avoids a schema -> service import cycle.
    from app.services.marketplace.catalog import version_runs_here

    if version is None:
        return None
    return MarketplaceVersionRead(
        version=version.version,
        release_notes=version.release_notes,
        min_app_version=version.min_app_version,
        published_at=version.published_at,
        compatible=version_runs_here(version),
    )


def serialize_listing_summary(
    listing: "MarketplaceListing",
    latest: Optional["MarketplaceListingVersion"],
) -> MarketplaceListingSummary:
    """One browse card. Shared by every surface that lists or reads a listing,
    so a card and the page it opens describe the same thing."""
    version = serialize_version(latest)
    assert listing.id is not None
    return MarketplaceListingSummary(
        id=listing.id,
        uid=listing.uid,
        public_id=listing.public_id,
        kind=listing.kind,
        source=listing.source,
        name=listing.name,
        publisher=listing.publisher,
        first_party=published_by_us(listing.source, listing.public_id),
        # Attribution travels with the provenance that bounds it: a card, the
        # detail page and the install dialog all answer "who wrote this?" from
        # these two fields together, so neither is served without the other.
        description=listing.description,
        avatar_url=listing.avatar_url,
        images=list(listing.images or []),
        installs_count=listing.installs_count or 0,
        available=listing.available,
        latest_version=version,
        # Everything that has to be true for the install button to do anything:
        # still offered, has a version, and that version runs on this build.
        installable=bool(listing.available and version and version.compatible),
        updated_at=listing.updated_at,
    )


class OperatorCatalogProblem(SanitizedBaseModel):
    """A manifest the scan would not publish, named so it can be fixed."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The file's name inside the catalog directory.
    file: str
    #: Why it was skipped, in the words the validator used. Carried verbatim
    #: and length-bounded at the source: a diagnostic quoting the offending
    #: character is only useful if it still says which character.
    reason: RawTextStr


class OperatorCatalogScanResult(SanitizedBaseModel):
    """What a rescan of the operator's catalog directory did.

    Read by the person who just dropped a file in, so it reports the skipped
    files as well as the count: a listing that did not appear should say why
    without a trip to the server log.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    published: int = 0
    #: Listings retired because no manifest in the directory publishes them.
    withdrawn: int = 0
    skipped: int = 0
    problems: list[OperatorCatalogProblem] = []
