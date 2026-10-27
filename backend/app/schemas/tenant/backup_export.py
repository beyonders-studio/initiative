"""Initiative/guild backup manifest — the index at the root of a backup zip.

A backup is a zip of per-tool JSON envelopes (each independently versioned by
its own ``type`` + ``schema_version``) plus optional upload blobs under
``assets/``. The manifest is what a future import wizard reads first: it
inventories every entry by type so files dispatch to the right importer, maps
assets back to the files that reference them, and records what was
deliberately left out (``skipped``) so a backup never silently loses data.

Privacy rule: ``skipped`` lists only items the exporter can SEE but policy
excluded (e.g. uploaded files when uploads are excluded). Rows invisible to
the exporter under sharing rules are simply absent everywhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.models.tenant.initiative import InitiativeJoinPolicy
from app.schemas.base import SanitizedBaseModel

BACKUP_SCHEMA_VERSION = 1
MIN_SUPPORTED_IMPORT_VERSION = 1


class ManifestAttachTo(SanitizedBaseModel):
    """Where an entry belongs once both ends of the archive exist.

    An uploaded file has one home — the initiative's file list — and this
    says what it is *also* filed in, as the relation that is the second view
    of it. It names the far end by **manifest entry path**, not by id, for the
    reason every cross-entry reference does: an id means nothing until the
    entry it names has been applied, and entries apply in tool order.
    """

    kind: str  # "wiki"
    ref: str  # the far end's manifest entry path
    #: The page it is filed under in that wiki, by the page's slug in the
    #: wiki's envelope. Absent is the top of the wiki.
    page: Optional[str] = None


class ManifestEntry(SanitizedBaseModel):
    """One exported file inside the archive."""

    path: str
    tool: str  # "project" | "file" | "queue" | "counter_group" |
    #           "calendar" | "post"
    type: str  # envelope type, or "file"
    schema_version: Optional[int] = None  # None for foreign formats
    entity_id: int
    title: str
    # Absent for a guild-level entry — a thing the community owns directly
    # rather than through one of its initiatives.
    initiative_id: Optional[int] = None
    # Metadata for entries whose file format can't carry it itself
    # (file entries are raw blobs; envelopes carry their own tags/properties).
    tags: list[str] = []
    properties: list[dict] = []
    # ``assets/{storage_key}`` for uploaded files (the blob IS the file).
    asset: Optional[str] = None
    # What this entry is filed in besides its own list, resolved after every
    # entry has been applied. Absent for everything that is only where it is.
    attach_to: Optional[ManifestAttachTo] = None


class ManifestPerson(SanitizedBaseModel):
    """Somebody the archive quotes, and how often.

    A comment names its author by handle, inside an envelope. The plan reads
    only the manifest, so the people an importer will be asked about are
    inventoried here rather than found by opening every file — the same reason
    the entry list exists.

    ``comment_count`` is what makes the question worth asking: it says how
    much of the archive hangs on getting this one row right.
    """

    handle: str
    name: Optional[str] = None
    comment_count: int = 0


class ManifestAsset(SanitizedBaseModel):
    """One upload blob under ``assets/``, keyed by its storage key (unique by
    construction); the original filename lives here, not in the entry name."""

    path: str
    storage_key: str
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: int = 0
    referenced_by: list[str] = []


class ManifestSkipped(SanitizedBaseModel):
    tool: str
    entity_id: int
    title: str
    # Absent for a guild-level entry — a thing the community owns directly
    # rather than through one of its initiatives.
    initiative_id: Optional[int] = None
    reason: str  # "uploads_excluded" | ...


class ManifestInitiative(SanitizedBaseModel):
    id: int
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    # tool -> "included" | "excluded" | "disabled" (per-initiative flag off)
    tools: dict[str, str]
    # How members come to join it. Absent from an archive written before it
    # was carried, which restores as a new initiative's default.
    join_policy: Optional[InitiativeJoinPolicy] = None
    # Apply into an initiative that already exists, rather than creating one.
    # An exporter never writes this — a backup describes where it came from,
    # not where it is going. A foreign source (an Atlassian fetch) writes it,
    # because a Jira project belongs in an initiative somebody already runs.
    target_initiative_id: Optional[int] = None


class ManifestCommunitySection(SanitizedBaseModel):
    """One guild-level file in the archive — what the community owns directly
    rather than through an initiative.

    Listed here for the same reason ``entries`` is: the import plan reads the
    manifest and nothing else, so it must be able to see that a roster or a
    tag vocabulary is present without opening every file. ``count`` is how
    many records the file holds, which is what makes the section worth
    reporting in a plan ("42 members, 17 tags").
    """

    key: str  # "settings" | "tags" | "members" | "plugins"
    path: str
    count: int = 0


class ManifestCommunity(SanitizedBaseModel):
    """The community the archive came from.

    A model rather than a loose dict because a backup that cannot say what
    the community was called, how it was configured, or who was in it is not
    a backup of the community — only of the work done inside it.
    """

    id: int
    name: str
    description: Optional[str] = None
    is_community: bool = False


class BackupManifest(SanitizedBaseModel):
    type: str  # "initiative-backup" | "guild-backup"
    schema_version: int = BACKUP_SCHEMA_VERSION
    app_version: str
    exported_at: datetime
    exported_by_handle: Optional[str] = None
    source_instance_url: Optional[str] = None
    guild: ManifestCommunity
    include_uploads: bool
    initiatives: list[ManifestInitiative]
    # Guild-level files: what the community owns outside its initiatives.
    guild_sections: list[ManifestCommunitySection] = []
    entries: list[ManifestEntry]
    assets: list[ManifestAsset]
    skipped: list[ManifestSkipped]
    # Everyone the archive quotes. Absent in a backup taken before it was
    # inventoried, which reads as "nobody to ask about" and leaves those
    # comments to the exact-handle match.
    people: list[ManifestPerson] = []


class BackupToolEstimate(SanitizedBaseModel):
    count: int = 0
    disabled: bool = False


class BackupEstimate(SanitizedBaseModel):
    """The wizard's pre-flight numbers: per-tool entity counts, the uploads
    footprint (approximate — embedded document images resolve at build time),
    and the row/byte ceilings so the client can warn before submitting."""

    tools: dict[str, BackupToolEstimate]
    uploads_count: int = 0
    uploads_bytes: int = 0
    uploads_approximate: bool = True
    estimated_rows: int = 0
    max_rows: int = 0
    max_upload_bytes: int = 0
    # Past this, the archive is written to the operator's destination rather
    # than handed back as a download — so the wizard can say which of the two
    # is going to happen before anybody submits.
    max_download_bytes: int = 0
    # Whether this deployment has a destination configured at all. Without
    # one, an export over the download bound is refused instead of delivered.
    delivery_available: bool = False
