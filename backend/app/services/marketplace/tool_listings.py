"""The tool marketplaces: a listing is a tool's export envelope, and installing
it is that tool's import.

Every tool that exports and imports has a marketplace (``TOOL_LISTING_KINDS``).
No second format exists beside the envelope: what a listing version stores is
the envelope the tool's exporter writes, held to the tool's own importer, and
installing it runs that importer into an initiative as the member who asked —
under RLS, with the importer's own permission check, exactly as importing the
same file would.

Three things a listing stores differ from a file on disk:

* **The listing names the item.** An installed copy is called what the listing
  is called, whatever name the envelope carries, so the thing a member picked
  from the shelf is the thing that appears in their initiative.
* **What belongs to the community stays behind** — people, links out of the
  item, uploads — and dates become offsets from a fixed day
  (``publish_profile``). That applies to a listing from any source, so an
  install never names somebody or points somewhere in the installer's
  community by accident.
* **A listing may carry an example** beside what it installs: the same tool's
  envelope, filled in. A tool made of queries over a community's data does not
  take one from its publisher (``example_is_generated`` on the exporter); its
  preview data is generated instead.

Nothing here decides who may read the catalog or write it. Normalization runs
wherever a listing is ingested (the catalog's writer); installing runs on the
guild-routed session of the member installing.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.core.tools import Tool, tool_envelope_type, tool_export_source
from app.models.platform.marketplace import (
    MarketplaceListing,
    MarketplaceListingVersion,
)
from app.models.platform.user import User
from app.services.import_engine import limits as import_limits
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)
from app.services.marketplace.manifest_values import ListingDefinitionError
from app.services.marketplace.publish_profile import (
    DATE_ANCHOR,
    anchor_dates,
    shift_dates,
    strip_for_listing,
)

__all__ = [
    "ListingTooLargeError",
    "MAX_LISTING_BODY_BYTES",
    "example_is_generated",
    "installable_body",
    "install_tool_listing",
    "listing_example",
    "normalize_tool_example",
    "normalize_tool_listing",
]


class ListingTooLargeError(ListingDefinitionError):
    """A listing over the size or row ceiling — the one refusal a member
    sharing their own item can act on, by sharing less of it."""


#: The largest envelope a listing may carry, as stored JSON. A listing is a
#: template, not an archive: this is far above any real one and far below what
#: the catalog tables are for.
MAX_LISTING_BODY_BYTES = 1024 * 1024

#: Envelope fields a listing does not keep. Where an export was taken is a
#: fact about the community it was taken in, and provenance is the catalog's to
#: record on the installed copy rather than the envelope's to claim.
_NOT_STORED = frozenset(
    {"source_instance_url", "source_guild_id", "listing_uid", "listing_version"}
)

#: The name a pre-envelope dashboard listing is wrapped with. The item takes
#: the listing's name on install, so this is never shown; it is a constant so
#: the same definition always wraps to the same body.
_WRAPPED_NAME = ""


def _importer(tool: Tool):
    # Imported here: the importer registry reaches most of the app's models,
    # and the catalog's validators are imported far earlier than that.
    from app.services.import_engine.importers import IMPORTERS

    return IMPORTERS[tool_envelope_type(tool)]


def example_is_generated(tool: Tool) -> bool:
    """Whether this tool's listings preview on generated sample data rather
    than an example their publisher supplies — the exporter's declaration."""
    from app.services.export.adapters import ADAPTERS

    return bool(ADAPTERS[tool_export_source(tool)].example_is_generated)


def _wrap_dashboard_definition(body: dict[str, Any]) -> dict[str, Any]:
    """A dashboard listing published before listings were envelopes.

    Its body is the canvas alone — ``{widgets, layout, ...}`` — which is the
    ``definition`` field of a dashboard's envelope. Anything that has no
    ``type`` of its own is read that way, so a publisher still writing the
    older shape (a plug-in's bundled dashboards among them) lands in the same
    stored form as one writing the envelope.
    """
    return {
        "type": tool_envelope_type(Tool.dashboard),
        "name": _WRAPPED_NAME,
        "definition": body,
    }


def _check_size(body: Any, *, what: str) -> None:
    size = len(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    if size > MAX_LISTING_BODY_BYTES:
        raise ListingTooLargeError(
            f"{what} is {size} bytes; a listing carries at most "
            f"{MAX_LISTING_BODY_BYTES}"
        )


def normalize_tool_listing(
    tool: Tool, body: Any, *, what: str = "definition"
) -> dict[str, Any]:
    """Validate and canonicalize a tool listing's envelope.

    Held to the tool's own importer — its schema and its ``schema_version``
    gate — and stored as the importer read it, so unknown keys are dropped and
    the stored body always has one shape. Bounded twice: by size, and by the
    importer's own row count, at the ceiling under which an import is applied
    in the request. An install is therefore always one statement's work, never
    a queued job.
    """
    if not isinstance(body, dict):
        raise ListingDefinitionError(f"{what} must be an object")
    envelope_type = tool_envelope_type(tool)
    if tool is Tool.dashboard and "type" not in body:
        body = _wrap_dashboard_definition(body)
    if body.get("type") != envelope_type:
        raise ListingDefinitionError(
            f"{what} must be an {envelope_type!r} envelope, got {body.get('type')!r}"
        )
    _check_size(body, what=what)

    # What belongs to the community stays behind, and the dates become offsets,
    # before the importer reads it — so the importer's own dump is the last
    # word on the stored form, and normalizing a stored body again is a no-op.
    body = anchor_dates(tool, strip_for_listing(tool, body))

    importer = _importer(tool)
    try:
        validated = importer.validate(body)
    except ImportEngineError as exc:
        raise ListingDefinitionError(f"{what} is not a valid {envelope_type}: {exc}")
    rows = importer.count(validated)
    if rows > import_limits.IMPORT_INLINE_MAX_ROWS:
        raise ListingTooLargeError(
            f"{what} holds {rows} rows; a listing holds at most "
            f"{import_limits.IMPORT_INLINE_MAX_ROWS}"
        )

    stored = validated.model_dump(mode="json", exclude=set(_NOT_STORED))
    if tool is Tool.dashboard:
        stored = _canonical_dashboard(stored, what=what)
    return stored


def _canonical_dashboard(envelope: dict[str, Any], *, what: str) -> dict[str, Any]:
    """A dashboard envelope's canvas, held to the renderer's vocabulary.

    The importer is lenient on purpose — a backup restores a dashboard it
    cannot draw as an empty one rather than losing it — but a listing is
    published to be installed, so a canvas this build cannot draw is refused
    here, by the same validator the create endpoint runs.

    ``config`` is dropped. It fills the binding slots a definition leaves open
    with one community's own counters and files, which a listing has none
    of: that is the installer's to fill.
    """
    from app.services.tenant.dashboard_definition import (
        DashboardDefinitionError,
        normalize_dashboard_definition,
    )

    try:
        envelope["definition"] = normalize_dashboard_definition(
            envelope.get("definition") or {}
        )
    except DashboardDefinitionError as exc:
        raise ListingDefinitionError(f"invalid dashboard {what}: {exc}") from exc
    envelope["config"] = {}
    return envelope


#: How each tool whose example is generated draws it, and checks the sample a
#: publisher supplies in its place. ``tool_listings_test`` holds every such
#: tool to having one.
def _sample_makers() -> dict[Tool, tuple[Any, Any]]:
    from app.services.marketplace.dashboard_samples import (
        generate_dashboard_sample,
        normalize_dashboard_sample,
    )

    return {Tool.dashboard: (generate_dashboard_sample, normalize_dashboard_sample)}


def normalize_tool_example(
    tool: Tool, body: Any, definition: dict[str, Any]
) -> dict[str, Any] | None:
    """The example a publisher supplies beside a tool listing, or ``None``.

    For a tool made of content it is the same envelope filled in, held to
    exactly the rules the listing itself is, because installing from it is
    the same import. For a tool whose example is generated it is sample data
    of the publisher's own in place of the generated sample, checked against
    the listing (``definition``, already normalized) — and never installable.
    """
    if body is None:
        return None
    if example_is_generated(tool):
        _generate, normalize = _sample_makers()[tool]
        return normalize(definition, body)
    return normalize_tool_listing(tool, body, what="example")


def listing_example(
    tool: Tool, listing_uid: str, version: MarketplaceListingVersion
) -> dict[str, Any] | None:
    """What a listing previews as beside itself.

    The stored example when there is one. For a tool whose example is
    generated and whose publisher supplied none, the sample is drawn here,
    seeded by the listing and version, so a query listing is never shown
    empty and always shows the same rows.
    """
    if version.example:
        return dict(version.example)
    if not example_is_generated(tool):
        return None
    generate, _normalize = _sample_makers()[tool]
    return generate(
        dict(version.definition or {}), seed=f"{listing_uid}:{version.version}"
    )


def installable_body(
    version: MarketplaceListingVersion, start_from: str
) -> dict[str, Any] | None:
    """The envelope an install applies, or ``None`` when the version has
    nothing to start from on that choice."""
    if start_from == "example":
        # A generated sample is a preview, not something to install.
        tool = _tool_of(version)
        if tool is not None and example_is_generated(tool):
            return None
        return dict(version.example) if version.example else None
    return dict(version.definition or {})


def _tool_of(version: MarketplaceListingVersion) -> Tool | None:
    envelope_type = (version.definition or {}).get("type")
    for tool in Tool:
        if tool_envelope_type(tool) == envelope_type:
            return tool
    return None


def _named(tool: Tool, envelope: dict[str, Any], name: str) -> dict[str, Any]:
    """The envelope with the item named ``name``.

    A project's envelope keeps its name inside ``project``, which predates the
    shape every later envelope shares; everything else names itself at the top.
    """
    if tool is Tool.project:
        project = dict(envelope.get("project") or {})
        project["name"] = name
        return {**envelope, "project": project}
    return {**envelope, "name": name}


async def install_tool_listing(
    session: AsyncSession,
    *,
    tool: Tool,
    listing: MarketplaceListing,
    version: MarketplaceListingVersion,
    user: User,
    guild_id: int,
    initiative_id: int,
    start_from: str = "blank",
    starts_on: date | None = None,
) -> EnvelopeImportResult:
    """Import a copy of a tool listing into an initiative, as ``user``.

    The same sequence a file import takes: the importer validates the envelope,
    :func:`load_target_initiative` resolves the initiative under RLS and asks
    for the tool's switch and the member's create permission, and the importer
    applies it. The copy then records which listing and version it came from.

    A listing keeps its dates as offsets from :data:`DATE_ANCHOR`; they land
    relative to ``starts_on``, today when it is not given.

    Flush-only, like every apply: the caller commits.
    """
    from app.services.import_engine.engine import (
        apply_one_envelope,
        load_target_initiative,
    )
    from app.services.marketplace.listing_assets import copy_assets_in
    from app.services.tenant.attachments import StorageQuotaExceededError

    body = installable_body(version, start_from)
    if body is None:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_PARAMS)

    start = starts_on or datetime.now(timezone.utc).date()
    body = shift_dates(tool, body, (start - DATE_ANCHOR).days)

    importer = _importer(tool)
    importer.validate(_named(tool, body, listing.name))
    initiative = await load_target_initiative(
        session,
        guild_id=guild_id,
        initiative_id=initiative_id,
        importer=importer,
        user=user,
    )
    # Only once the member may create it here are its pictures copied into
    # this community's storage.
    try:
        body = await copy_assets_in(
            session,
            envelope=body,
            guild_id=guild_id,
            user_id=user.id,
            initiative_id=initiative.id,
        )
    except StorageQuotaExceededError as exc:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_QUOTA_EXCEEDED, status_code=400
        ) from exc
    validated = importer.validate(_named(tool, body, listing.name))
    result = await apply_one_envelope(
        session,
        importer=importer,
        envelope=validated,
        target_initiative=initiative,
        user=user,
    )
    if result.entity_id is not None:
        await _record_provenance(
            session, tool, result.entity_id, listing.uid, version.version
        )
    return result


async def _record_provenance(
    session: AsyncSession,
    tool: Tool,
    entity_id: int,
    listing_uid: str,
    listing_version: str,
) -> None:
    from sqlalchemy import update

    from app.models.tenant._mixins import tool_models

    model = tool_models()[tool.plural]
    await session.exec(
        update(model)
        .where(model.id == entity_id)
        .values(listing_uid=listing_uid, listing_version=listing_version)
    )
    await session.flush()
