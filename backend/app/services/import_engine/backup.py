"""Backup-zip import: plan (pre-flight summary from ``manifest.json``) and
apply (the worker-side restore).

A backup is the export engine's zip: per-tool JSON envelopes under
``initiatives/{id}-{slug}/…`` indexed by a root manifest, plus optional
upload blobs under ``assets/``. Import creates **new initiatives** (names
suffixed on collision, tool switches from the manifest, the importer becomes
manager) — never merges — and dispatches every entry to the per-type
importer registry, so an envelope imports identically whether it arrives
alone or inside a backup.

How it runs:
* the zip is opened and each member read through ``zip_bounds``: the central
  directory is checked (member count, total declared size, relative names)
  before any member is read, and every member is read up to its cap;
* the plan step reads ONLY ``manifest.json`` — milliseconds, so it runs in
  the upload request (off the event loop);
* apply re-verifies the creator is a REAL guild admin (fail closed on
  revocation), restores assets under their original storage keys (embedded
  editor-state references resolve without rewriting) through
  ``archive_assets`` — each file checked for what it is, per-key dedup,
  storage-quota enforcement — and applies entries in per-entry savepoints —
  one corrupt entry fails alone, the job still completes with a report;
* long applies commit per chunk and refresh ``establish_guild_access``
  (RLS context is valid for at most RLS_CONTEXT_MAX_AGE_SECONDS).
"""

from __future__ import annotations

import asyncio
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import gucs
from app.db.session import raise_flag, routed_guild_id
from app.core.references import format_ref, parse_ref
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import BULK_EXPORT_TOOLS, Tool, tool_envelope_type
from app.core.messages import ImportEngineMessages
from app.models.platform.user import User
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.models.tenant.initiative import Initiative
from app.schemas.tenant.backup_export import (
    BACKUP_SCHEMA_VERSION,
    MIN_SUPPORTED_IMPORT_VERSION,
    BackupManifest,
    ManifestEntry,
)
from app.schemas.tenant.import_job import (
    BackupImportPlan,
    BackupImportResult,
    BackupPlanInitiative,
    BackupPlanPerson,
    EntryResult,
)
from app.services import guild_work
from app.services.import_engine import engine as import_engine
from app.services.import_engine import limits as import_limits
from app.services.import_engine.archive_assets import (
    ArchiveAsset,
    remove_written,
    restore_assets,
)
from app.services.import_engine.common import (
    handle_key,
    load_guild_member_handles,
    unique_name,
)
from app.services.tenant.attachments import claim_shown
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)
from app.services.import_engine.context import (
    ImportContext,
    excluded_property_names,
    exported_from_here,
)
from app.services.import_engine.links import resolve_page_links
from app.services.import_engine.references import SOURCE_REF, resolve_references
from app.services.marketplace.publish_profile import shift_dates
from app.services.import_engine.zip_bounds import (
    json_cap,
    open_zip,
    read_json_member,
    read_member,
)

# Apply order within an initiative — convention, not correctness (cross-tool
# references in envelopes are display text only).
# Derived from the same set the export side writes, so a tool cannot be
# exported into an envelope this refuses to read back.
_TOOL_ORDER = tuple(t.value for t in BULK_EXPORT_TOOLS)

# An initiative's own files: what it is shaped like, rather than anything made
# inside it. They carry no Tool and no registry importer — like ``file``
# entries, they are applied here — and they go FIRST, because the content
# behind them refers to what they establish: a value binds to a property
# definition, and a member holds a role.
_STRUCTURAL_TOOL = "initiative"
_STRUCTURAL_TYPES = frozenset({"initiative-structure", "initiative-properties"})

# Refresh the routed session's authorization context this often (see the
# export backup adapter's identical constant).
_REFRESH_EVERY = 25

_MANIFEST_NAME = "manifest.json"

#: What "filed in" means, per kind of far end. A file in a wiki is a
#: ``part_of`` — the wiki is a place, and the file is one of the things
#: in it, which is exactly the edge ``wikis.linked_files`` reads.
#:
#: One kind, because ``attach_to`` names another manifest ENTRY, and a wiki is
#: the only place a file can be filed that is an entry of its own. A task is
#: not: it lives inside its project's envelope, so a file attached to a
#: task is a link the envelope asserts by ref, not a placement recorded here.
#: A kind nothing here names is left alone rather than guessed at.
_ATTACH_RELATIONSHIPS: dict[str, RelationshipType] = {
    "wiki": RelationshipType.part_of,
}

#: How an archive written before files were called files names them: the
#: manifest's tool, its tool switches and envelope type, the keys holding a file's type and the
#: files filed in a wiki or attached to an item, the refs naming one, and the
#: role permissions for the tool. Read on restore and rewritten to this build's names before
#: anything else looks at the archive; nothing writes them.
_LEGACY_ENVELOPE_TYPES = {"initiative-document": tool_envelope_type(Tool.file)}
_LEGACY_TOOLS = {"document": Tool.file.value}
_LEGACY_KEYS = {"documents": "files", "document_type": "file_type"}
_LEGACY_REF_KEYS = ("external_ref", SOURCE_REF)
_LEGACY_PERMISSIONS = {
    "documents_enabled": Tool.file.view_permission,
    "create_documents": Tool.file.create_permission,
}


def _current_shape(value: Any) -> Any:
    """``value``, read from an archive, with the names an older build gave
    files spelled as this one spells them."""
    if isinstance(value, list):
        return [_current_shape(item) for item in value]
    if not isinstance(value, dict):
        return value
    shaped = {
        _LEGACY_KEYS.get(key, key): _current_shape(item) for key, item in value.items()
    }
    tools = shaped.get("tools")
    if isinstance(tools, dict):
        shaped["tools"] = {
            _LEGACY_TOOLS.get(key, key): item for key, item in tools.items()
        }
    kind = shaped.get("type")
    if isinstance(kind, str) and kind in _LEGACY_ENVELOPE_TYPES:
        shaped["type"] = _LEGACY_ENVELOPE_TYPES[kind]
    tool = shaped.get("tool")
    if isinstance(tool, str) and tool in _LEGACY_TOOLS:
        shaped["tool"] = _LEGACY_TOOLS[tool]
    for key in _LEGACY_REF_KEYS:
        ref = shaped.get(key)
        parsed = parse_ref(ref) if isinstance(ref, str) else None
        if parsed is not None:
            shaped[key] = format_ref(*parsed)
    permissions = shaped.get("permissions")
    if isinstance(permissions, list):
        shaped["permissions"] = [
            _LEGACY_PERMISSIONS.get(key, key) if isinstance(key, str) else key
            for key in permissions
        ]
    return shaped


def _entry_ref(path: str) -> str:
    """The name an entry answers to inside one job.

    Namespaced so it cannot collide with an external ref an envelope chose
    for itself (``"jira:ACME-123"``) — both live in the same map, because
    both are "a name that resolves to a row once the import has run"."""
    return f"entry:{path}"


def _entry_kind(entry: ManifestEntry) -> SearchEntityType | None:
    """What kind of thing this entry becomes. A file entry is a file
    whatever tool it was filed under; everything else is its own tool. A
    tool this build has no endpoint kind for cannot be an end of an edge,
    which is a reason to skip it rather than to fail the restore."""
    name = Tool.file.value if entry.type == "file" else entry.tool
    try:
        return SearchEntityType(name)
    except ValueError:
        return None


logger = logging.getLogger(__name__)


def read_manifest(archive: zipfile.ZipFile, *, fetched: bool = False) -> BackupManifest:
    """The backup's manifest, read up to the JSON cap and checked.

    ``fetched`` is as for :func:`zip_bounds.open_zip`."""
    try:
        raw = read_json_member(
            archive,
            _MANIFEST_NAME,
            max_bytes=json_cap(fetched=fetched),
            invalid=ImportEngineMessages.IMPORT_ZIP_INVALID,
        )
    except ImportEngineError:
        raise
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    try:
        manifest = BackupManifest.model_validate(_current_shape(raw))
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    if not (
        MIN_SUPPORTED_IMPORT_VERSION <= manifest.schema_version <= BACKUP_SCHEMA_VERSION
    ):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SCHEMA_VERSION_UNSUPPORTED)
    _reject_non_flat_asset_keys(manifest)
    return manifest


def _reject_non_flat_asset_keys(manifest: BackupManifest) -> None:
    """A backup asset key is both the ``uploads`` row identity and the storage
    write target; the storage backends reduce it to ``Path(key).name``, so it
    must already be flat for the two to match. Legit exports only ever emit flat
    keys, so a key with path components is a malformed backup — reject it."""
    from app.services.storage import is_flat_storage_key

    for asset in manifest.assets:
        if not is_flat_storage_key(asset.storage_key):
            raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)
    for entry in manifest.entries:
        if entry.asset is not None and not is_flat_storage_key(
            entry.asset.removeprefix("assets/")
        ):
            raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)


def plan_backup(
    payload: bytes | Path,
    *,
    existing_initiative_names: set[str],
    member_ids_by_handle: dict[str, int] | None = None,
    fetched: bool = False,
) -> BackupImportPlan:
    """The confirm-screen summary. Reads only the manifest — cheap enough to
    run inside the upload request.

    ``member_ids_by_handle`` is the guild's own roster, normalised, and it is
    what turns the archive's people into suggestions. It is passed in rather
    than read here because this function holds no session: the plan is a
    reading of one file, and the roster is a fact about the community it is
    being read into.

    ``fetched`` is as for :func:`zip_bounds.open_zip`. Blocking; run it in a
    thread from async code.
    """
    from app.services.import_engine.importers import IMPORTERS

    with open_zip(payload, fetched=fetched) as archive:
        manifest = read_manifest(archive, fetched=fetched)

    unknown_types = sorted(
        {
            entry.type
            for entry in manifest.entries
            if entry.type != "file"
            and entry.type not in _STRUCTURAL_TYPES
            and entry.type not in IMPORTERS
        }
    )
    # Suffix previews compound: two imported initiatives can collide with
    # each other, not just with existing ones.
    taken = set(existing_initiative_names)
    initiatives: list[BackupPlanInitiative] = []
    for mi in manifest.initiatives:
        if mi.target_initiative_id is not None:
            # Filed into one that exists: no name is claimed, so none is
            # proposed, and it cannot push a created one into a suffix.
            proposed = mi.name
        else:
            proposed = unique_name(taken, mi.name)
            taken.add(proposed)
        counts: dict[str, int] = {}
        for entry in manifest.entries:
            if entry.initiative_id == mi.id:
                counts[entry.tool] = counts.get(entry.tool, 0) + 1
        initiatives.append(
            BackupPlanInitiative(
                source_id=mi.id,
                name=mi.name,
                proposed_name=proposed,
                tools=mi.tools,
                entry_counts=counts,
                target_initiative_id=mi.target_initiative_id,
            )
        )
    roster = member_ids_by_handle or {}
    people = [
        BackupPlanPerson(
            handle=person.handle,
            name=person.name,
            comment_count=person.comment_count,
            suggested_user_id=roster.get(handle_key(person.handle)),
        )
        for person in manifest.people
    ]
    return BackupImportPlan(
        source_community_name=manifest.guild.name,
        app_version=manifest.app_version,
        exported_at=manifest.exported_at.isoformat(),
        schema_version=manifest.schema_version,
        initiatives=initiatives,
        asset_count=len(manifest.assets),
        asset_bytes=sum(a.size_bytes for a in manifest.assets),
        skipped=[s.model_dump(mode="json") for s in manifest.skipped],
        unknown_types=unknown_types,
        people=people,
    )


async def stage_backup_job(
    session: AsyncSession,
    *,
    guild_id: int,
    user: User,
    payload: Path,
    status: ImportJobStatus,
    anchor: datetime | None = None,
) -> ImportJob:
    """Plan the backup zip at ``payload``, stage it in the community's storage
    and add its job, created by ``user``, to ``session`` without committing.

    ``session`` is routed into the community, and the plan suggests who each
    name in the archive is from the roster it reads there. A ``staged`` job
    waits for the seat to confirm the plan; a ``queued`` one goes straight to
    the worker. ``anchor`` is as for :func:`apply_backup`. Raises
    ``IMPORT_JOB_LIMIT_REACHED`` once ``user`` has too many jobs open."""
    existing_names = set((await session.exec(select(Initiative.name))).all())
    roster = await load_guild_member_handles(session, guild_id=guild_id)
    plan = await asyncio.to_thread(
        plan_backup,
        payload,
        existing_initiative_names=existing_names,
        member_ids_by_handle=roster,
    )
    await import_engine.count_active_jobs_locked(session, user=user)
    payload_ref = await asyncio.to_thread(
        import_engine.stage_payload_file, guild_id, payload, suffix="zip"
    )
    job = ImportJob(
        created_by=user.id,
        source="backup",
        params={"anchor": anchor.isoformat()} if anchor is not None else {},
        payload_ref=payload_ref,
        plan=plan.model_dump(mode="json"),
        status=status,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=import_limits.IMPORT_STAGED_TTL_HOURS),
    )
    session.add(job)
    if status is ImportJobStatus.queued:
        guild_work.wake(session, guild_work.DATA_JOBS, guild_id)
    return job


def _manifest_tool_flags(tools: dict[str, str] | None) -> dict[str, bool]:
    """A manifest's per-tool states as initiative master-switch fields.

    "disabled" -> off; "included"/"excluded" -> on, because the switch records
    the source's configuration rather than what this import was asked to carry.

    Spelled through the enum rather than ``tool + "s"``, which is wrong for
    ``gallery``. A manifest also names things that are not tools — a backup
    written by a newer version, or a sub-resource like ``calendar_event`` — and
    those name no switch, so they are skipped rather than raising on an
    initiative that is otherwise importable.
    """
    flags: dict[str, bool] = {}
    for name, state in (tools or {}).items():
        try:
            tool = Tool(name)
        except ValueError:
            continue
        flags[tool.view_permission] = state != "disabled"
    return flags


async def apply_backup(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    payload: bytes | Path,
    include: dict[str, bool] | None,
    people_map: Any = None,
    exclude_properties: Any = None,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
    fetched: bool = False,
    anchor: datetime | None = None,
) -> BackupImportResult:
    """Restore a backup zip into new initiatives, as ``user``, on the
    worker's creator-routed session. Flushes and COMMITS per chunk (the
    always-create policy makes partial progress durable and never re-run).

    ``heartbeat`` is called after each asset and each entry, so the job can
    show it is still being applied. ``fetched`` is as for
    :func:`zip_bounds.open_zip`. ``anchor``, when given, moves every date the
    envelopes carry by the whole days from it to now, so a bundle reads as if
    it had been exported today (a repeat by its own rule, :func:`shift_dates`)."""
    from app.api.deps import establish_guild_access
    from app.services.import_engine.importers import IMPORTERS
    from app.models.platform.guild import CommunityRole
    from app.services.platform import guilds as guilds_service
    from app.services.tenant import initiatives as initiatives_service

    with await asyncio.to_thread(open_zip, payload, fetched=fetched) as archive:
        manifest = await asyncio.to_thread(read_manifest, archive, fetched=fetched)
        max_json_bytes = json_cap(fetched=fetched)
        result = BackupImportResult()
        shift_days = (
            round((datetime.now(timezone.utc) - anchor) / timedelta(days=1))
            if anchor is not None
            else 0
        )

        # Re-verify the seat, held outright, at apply time — enqueue-time
        # authority can be gone by now, and standing up a new initiative in the
        # community is the seat's act. It is asked for only when something here
        # actually creates one: a bundle that applies into initiatives somebody
        # already runs is gated by the per-tool create permission in those
        # initiatives instead (§8.2), which is the same gate a lone envelope
        # passes.
        if any(mi.target_initiative_id is None for mi in manifest.initiatives):
            membership = await guilds_service.get_membership(
                session, guild_id=guild_id, user_id=user.id
            )
            if membership is None or membership.role is not CommunityRole.superadmin:
                raise ImportEngineError(
                    ImportEngineMessages.IMPORT_SUPERADMIN_REQUIRED, status_code=403
                )

        # Assets first, one chunk: written under their ORIGINAL storage keys so
        # embedded editor-state image references resolve without rewriting.
        if manifest.assets:
            written = await _restore_assets(
                session, archive, manifest, guild_id, user, result, heartbeat
            )
            try:
                await session.commit()
            except BaseException:
                remove_written(guild_id, written)
                raise

        assets_by_key = {a.storage_key: a for a in manifest.assets}
        entries_by_initiative: dict[int, list[ManifestEntry]] = {}
        for entry in manifest.entries:
            entries_by_initiative.setdefault(entry.initiative_id, []).append(entry)

        since_refresh = 0

        # One context for the whole bundle. Its collector matters because an edge
        # routinely crosses two entries applied by two different importers, so
        # nothing resolves until the last of them has flushed; its people map is
        # what the confirm's mapping step recorded, re-checked against real
        # membership here rather than trusted from the job row.
        from app.services.import_engine.people import resolve_people_map

        context = ImportContext(
            people=await resolve_people_map(session, guild_id=guild_id, raw=people_map),
            excluded_properties=excluded_property_names(exclude_properties),
            source_url=manifest.source_instance_url,
            same_community=exported_from_here(
                manifest.source_instance_url, manifest.guild.id, guild_id=guild_id
            ),
        )

        for mi in manifest.initiatives:
            # System sentinel: user-attributed job, gate passed at enqueue.
            await establish_guild_access(session, user, guild_id, on_behalf=True)
            entries_here = entries_by_initiative.get(mi.id, [])
            if mi.target_initiative_id is not None:
                initiative = await _resolve_target_initiative(
                    session,
                    target_initiative_id=mi.target_initiative_id,
                    entries=entries_here,
                    user=user,
                    guild_id=guild_id,
                    include=include,
                )
            else:
                initiative = await initiatives_service.create_imported_initiative(
                    session,
                    guild_id=guild_id,
                    name=mi.name,
                    description=mi.description,
                    color=mi.color,
                    tool_flags=_manifest_tool_flags(mi.tools),
                    manager_id=user.id,
                    join_policy=mi.join_policy,
                )
            result.initiatives.append(
                {
                    "source_id": mi.id,
                    "initiative_id": initiative.id,
                    "name": initiative.name,
                }
            )

            entries = sorted(
                entries_here,
                key=lambda e: (
                    -1
                    if e.tool == _STRUCTURAL_TOOL
                    else _TOOL_ORDER.index(e.tool)
                    if e.tool in _TOOL_ORDER
                    else len(_TOOL_ORDER)
                ),
            )
            for entry in entries:
                since_refresh += 1
                if since_refresh >= _REFRESH_EVERY:
                    await session.commit()
                    await establish_guild_access(
                        session, user, guild_id, on_behalf=True
                    )
                    # Re-load the initiative on the refreshed transaction.
                    initiative = (
                        await session.exec(
                            select(Initiative).where(Initiative.id == initiative.id)
                        )
                    ).one()
                    since_refresh = 0
                outcome = await _apply_entry(
                    session,
                    archive=archive,
                    entry=entry,
                    initiative=initiative,
                    user=user,
                    include=include,
                    importers=IMPORTERS,
                    assets_by_key=assets_by_key,
                    result=result,
                    context=context,
                    max_json_bytes=max_json_bytes,
                    shift_days=shift_days,
                )
                result.entries.append(outcome)
                bucket = result.per_tool.setdefault(
                    entry.tool, {"created": 0, "failed": 0, "skipped": 0}
                )
                bucket[outcome.status] += 1
                if heartbeat is not None:
                    await heartbeat()
            await session.commit()

        # Everything is in the database; now the names can become edges.
        await establish_guild_access(session, user, guild_id, on_behalf=True)
        resolution = await context.links.resolve(session, created_by=user.id)
        result.links_created = resolution.created
        result.links_unresolved = resolution.unresolved
        # What a body names is placed on what it became here.
        await resolve_references(session, context, author_id=user.id)
        # And a link written in a task to a page that came over in the same
        # bundle becomes a mention of that page.
        await resolve_page_links(session, context.links, site_url=context.source_url)
        await _place_files_under_pages(session, context)
        # The files the entries show are kept for the initiative each went into.
        await claim_shown(session, set(assets_by_key))
        await session.commit()

        return result


async def _place_files_under_pages(
    session: AsyncSession, context: ImportContext
) -> None:
    """Place each file an entry placed under a page of its wiki, now that
    the file, the wiki and the page all exist. One whose page or wiki did
    not arrive stays at the top of the wiki, where joining it put it."""
    from app.models.tenant.wiki import Wiki
    from app.services.import_engine.links import wiki_page_slug_ref
    from app.services.tenant import wikis as wikis_service

    wikis: dict[int, Wiki] = {}
    for file_ref, wiki_ref, page_slug in context.placements:
        file = context.links.lookup(file_ref)
        wiki_end = context.links.lookup(wiki_ref)
        if file is None or wiki_end is None:
            continue
        page = context.links.lookup(wiki_page_slug_ref(wiki_end.id, page_slug))
        if page is None:
            continue
        wiki = wikis.get(wiki_end.id)
        if wiki is None:
            wiki = await session.get(Wiki, wiki_end.id)
            if wiki is None:
                continue
            wikis[wiki_end.id] = wiki
        wikis_service.place_file(wiki, file.id, parent_page_id=page.id)
        session.add(wiki)


async def _resolve_target_initiative(
    session: AsyncSession,
    *,
    target_initiative_id: int,
    entries: list[ManifestEntry],
    user: User,
    guild_id: int,
    include: dict[str, bool] | None,
):
    """Resolve an initiative the bundle wants to apply INTO, and prove the
    importer may write each kind of thing it is about to receive.

    The gate is the same one a lone envelope passes, run once per kind the
    bundle carries: ``load_target_initiative`` resolves the initiative under
    the caller's own RLS (unreachable reads as absent — 404), checks the
    tool's master switch, and checks the create permission. So a bundle
    naming four tools is refused unless its importer may create all four,
    and nothing is written before that is known.

    Only kinds this apply will actually reach are checked: an entry excluded
    by the include map is not going to be written, and demanding a permission
    for it would refuse an import that was never going to need it.
    """
    from app.services.import_engine.importers import IMPORTERS

    initiative = None
    seen: set[str] = set()
    for entry in entries:
        if include is not None and not include.get(entry.tool, True):
            continue
        # A file entry is a file whatever tool it was filed under, so it
        # is the file importer's permission that governs it.
        envelope_type = (
            tool_envelope_type(Tool.file) if entry.type == "file" else entry.type
        )
        if envelope_type in seen:
            continue
        seen.add(envelope_type)
        importer = IMPORTERS.get(envelope_type)
        if importer is None:
            # An unknown type is skipped at apply time with a code in the
            # report; it names no permission to check here.
            continue
        initiative = await import_engine.load_target_initiative(
            session,
            guild_id=guild_id,
            initiative_id=target_initiative_id,
            importer=importer,
            user=user,
        )
    if initiative is None:
        # Nothing to apply, or nothing whose type this build knows. Resolve
        # the initiative anyway so the rest of the pass has one to work with
        # and an unreachable id still fails here rather than later.
        initiative = await import_engine.load_target_initiative(
            session,
            guild_id=guild_id,
            initiative_id=target_initiative_id,
            importer=IMPORTERS[tool_envelope_type(Tool.file)],
            user=user,
        )
    return initiative


async def _apply_entry(
    session: AsyncSession,
    *,
    archive: zipfile.ZipFile,
    entry: ManifestEntry,
    initiative,
    user: User,
    include: dict[str, bool] | None,
    importers: dict,
    assets_by_key: dict[str, Any],
    result: BackupImportResult,
    max_json_bytes: int,
    context: ImportContext | None = None,
    shift_days: int = 0,
) -> EntryResult:
    """Apply one manifest entry in its own savepoint and report how it went.
    Its envelope is read up to ``max_json_bytes``, and its dates moved by
    ``shift_days``."""
    base = {
        "path": entry.path,
        "tool": entry.tool,
        "type": entry.type,
        "title": entry.title,
    }
    if include is not None and not include.get(entry.tool, True):
        return EntryResult(**base, status="skipped")
    if entry.type == "file":
        outcome = await _apply_file_entry(
            session,
            archive,
            entry,
            initiative,
            user,
            assets_by_key,
            base,
            context=context,
        )
        _record_entry(context, entry, outcome)
        return outcome
    if entry.type in _STRUCTURAL_TYPES:
        return await _apply_structural_entry(
            session,
            archive,
            entry,
            initiative,
            user,
            base,
            max_json_bytes,
            context=context,
        )
    importer = importers.get(entry.type)
    if importer is None:
        return EntryResult(
            **base, status="skipped", error=ImportEngineMessages.IMPORT_UNKNOWN_TYPE
        )
    try:
        raw = await asyncio.to_thread(
            read_json_member, archive, entry.path, max_bytes=max_json_bytes
        )
        envelope = _current_shape(raw)
        if shift_days and isinstance(envelope, dict) and entry.tool in _TOOL_ORDER:
            envelope = shift_dates(Tool(entry.tool), envelope, shift_days)
        validated = importer.validate(envelope)
        async with session.begin_nested():
            await raise_flag(session, gucs.IMPORTING)
            detail = await importer.apply(
                session,
                envelope=validated,
                target_initiative=initiative,
                importer=user,
                context=context,
            )
            await raise_flag(session, gucs.IMPORTING, False)
    except ImportEngineError as exc:
        logger.warning(
            "backup entry failed path=%s tool=%s code=%s",
            entry.path,
            entry.tool,
            exc.code,
        )
        return EntryResult(**base, status="failed", error=exc.code)
    except Exception:
        # Savepoint isolation stands, but the traceback must reach the logs —
        # the result JSON carries only a status code.
        logger.exception("backup entry failed path=%s tool=%s", entry.path, entry.tool)
        return EntryResult(
            **base, status="failed", error=ImportEngineMessages.IMPORT_APPLY_FAILED
        )
    result.unmatched_handles = sorted(
        set(result.unmatched_handles) | set(detail.unmatched_handles)
    )
    outcome = EntryResult(**base, status="created", detail=detail)
    _record_entry(context, entry, outcome)
    return outcome


def _record_entry(
    context: ImportContext | None, entry: ManifestEntry, outcome: EntryResult
) -> None:
    """Put a successfully applied entry into the job's ref map, and record
    what it said it is filed in.

    Both halves are names, not ids: the far end of an ``attach_to`` is
    another entry that may not have been applied yet, and resolving it is the
    deferred pass's job.
    """
    if context is None or outcome.status != "created":
        return
    kind = _entry_kind(entry)
    entity_id = outcome.detail.entity_id if outcome.detail is not None else None
    if kind is None or entity_id is None:
        return
    context.links.register(_entry_ref(entry.path), kind, entity_id)
    # And by what it was where it was exported, which is how a reference in
    # somebody else's body names it.
    context.links.register(format_ref(kind, entry.entity_id), kind, entity_id)
    if entry.attach_to is None:
        return
    relationship = _ATTACH_RELATIONSHIPS.get(entry.attach_to.kind)
    if relationship is None:
        return
    context.links.link(
        _entry_ref(entry.path), relationship, _entry_ref(entry.attach_to.ref)
    )
    if entry.attach_to.kind == "wiki" and entry.attach_to.page:
        context.placements.append(
            (
                _entry_ref(entry.path),
                _entry_ref(entry.attach_to.ref),
                entry.attach_to.page,
            )
        )


async def _apply_structural_entry(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    entry: ManifestEntry,
    initiative,
    user: User,
    base: dict,
    max_json_bytes: int,
    *,
    context: ImportContext | None = None,
) -> EntryResult:
    """An initiative's own shape: its property definitions, or its roles and
    members.

    Both are **additive**. They create what the target does not have and leave
    what it does alone: a role of the same name, or a definition of the same
    name and type, is the target's answer, not the archive's, and nobody is
    removed or demoted by an import. A definition whose name the target uses
    for something else is made beside it, as every importer makes one.
    """
    invalid = EntryResult(
        **base, status="failed", error=ImportEngineMessages.IMPORT_INVALID_ENVELOPE
    )
    try:
        payload = await asyncio.to_thread(
            read_json_member, archive, entry.path, max_bytes=max_json_bytes
        )
    except ImportEngineError as exc:
        return EntryResult(**base, status="failed", error=exc.code)
    except Exception:
        return invalid
    if not isinstance(payload, dict):
        return invalid
    payload = _current_shape(payload)
    try:
        async with session.begin_nested():
            if entry.type == "initiative-properties":
                created = await _apply_property_definitions(
                    session, initiative, payload, context=context
                )
            else:
                created = await _apply_initiative_structure(
                    session, initiative, user, payload
                )
    except Exception:
        logger.exception("backup import: structural entry %s failed", entry.path)
        return invalid
    return EntryResult(
        **base,
        status="created",
        detail=EnvelopeImportResult(
            entity_id=initiative.id, entity_title=initiative.name, created=created
        ),
    )


async def _apply_property_definitions(
    session: AsyncSession,
    initiative,
    payload: dict,
    *,
    context: ImportContext | None,
) -> dict:
    """Bind the archive's definitions in the target, the way every importer
    binds the definitions an envelope declares."""
    from pydantic import ValidationError

    from app.schemas.tenant.project_export import ProjectExportPropertyDefinition
    from app.services.import_engine.importers._base import PropertyRestore

    declared = []
    for raw in payload.get("properties") or []:
        try:
            declared.append(ProjectExportPropertyDefinition.model_validate(raw))
        except ValidationError:
            continue  # a type this build has no column for, or no name
    props = PropertyRestore(session, initiative_id=initiative.id, context=context)
    await props.declare(declared)
    await session.flush()
    return {"property_definitions": props.created}


async def _apply_initiative_structure(session, initiative, user: User, payload) -> dict:
    """Create the roles the target lacks, then place people it can name.

    A member is placed only where the handle resolves to somebody already in
    this community — an archive names people, it does not create accounts —
    and never over a membership that already exists.
    """
    from sqlmodel import select

    from app.models.tenant.initiative import (
        InitiativeMember,
        InitiativeRoleModel,
        InitiativeRolePermission,
        PermissionKey,
    )

    roles = {
        role.name: role
        for role in await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == initiative.id
            )
        )
    }
    roles_created = 0
    for raw in payload.get("roles") or []:
        name = str(raw.get("name") or "").strip()
        if not name or name in roles:
            continue
        role = InitiativeRoleModel(
            initiative_id=initiative.id,
            name=name,
            display_name=str(raw.get("display_name") or name),
            # Built-in-ness is this build's answer, not the archive's: a role
            # the target did not ship with is a custom one here.
            is_builtin=False,
            is_manager=bool(raw.get("is_manager")),
            override_share_restrictions=bool(raw.get("override_share_restrictions")),
            position=int(raw.get("position") or 0),
            created_by=user.id,
        )
        session.add(role)
        await session.flush()
        for key in raw.get("permissions") or []:
            try:
                permission_key = PermissionKey(key)
            except ValueError:
                continue  # a permission this build does not have
            session.add(
                InitiativeRolePermission(
                    initiative_role_id=role.id,
                    permission_key=permission_key,
                    enabled=True,
                )
            )
        roles[name] = role
        roles_created += 1

    placed = 0
    members = payload.get("members") or []
    if members:
        handles = await load_guild_member_handles(
            session, guild_id=routed_guild_id(session)
        )
        already = {
            row
            for row in await session.exec(
                select(InitiativeMember.user_id).where(
                    InitiativeMember.initiative_id == initiative.id
                )
            )
        }
        for raw in members:
            handle = (raw.get("handle") or "").strip().lower()
            user_id = handles.get(handle)
            if user_id is None or user_id in already:
                continue
            role = roles.get(raw.get("role") or "")
            session.add(
                InitiativeMember(
                    initiative_id=initiative.id,
                    user_id=user_id,
                    role_id=role.id if role is not None else None,
                )
            )
            already.add(user_id)
            placed += 1
    await session.flush()
    return {"initiative_roles": roles_created, "initiative_members": placed}


async def _apply_file_entry(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    entry: ManifestEntry,
    initiative,
    user: User,
    assets_by_key: dict[str, Any],
    base: dict,
    *,
    context: ImportContext | None = None,
) -> EntryResult:
    """An uploaded file: its content is the restored ``assets/`` blob. A table
    of text, which an uploaded file cannot hold, becomes a spreadsheet read
    from the zip instead."""
    from app.models.tenant.file import File, FileType
    from app.models.tenant.upload import Upload
    from app.schemas.tenant.import_envelopes import EnvelopePropertyValue
    from app.services.import_engine.importers._base import (
        PropertyRestore,
        TagRestore,
        grant_ownership,
    )
    from app.services.tenant import file_versions
    from app.services.tenant.attachments import MAX_FILE_SIZE
    from app.services.tenant.files_spreadsheet import FileContentError
    from app.services.tenant.spreadsheet_import import (
        TEXT_TABLE_SUFFIXES,
        parse_spreadsheet_file,
    )

    storage_key = (entry.asset or "").removeprefix("assets/")
    if not storage_key:
        return EntryResult(
            **base, status="failed", error=ImportEngineMessages.IMPORT_INVALID_ENVELOPE
        )
    asset = assets_by_key.get(storage_key)
    stored: dict[str, Any] = {}
    if storage_key.lower().endswith(TEXT_TABLE_SUFFIXES):
        try:
            data = await asyncio.to_thread(
                read_member, archive, entry.asset, max_bytes=MAX_FILE_SIZE
            )
            sheets = await asyncio.to_thread(parse_spreadsheet_file, storage_key, data)
        except KeyError:
            return EntryResult(
                **base,
                status="skipped",
                error=ImportEngineMessages.IMPORT_ASSET_MISSING,
            )
        except (ImportEngineError, FileContentError) as exc:
            return EntryResult(**base, status="failed", error=exc.code)
        file = File(
            name=entry.title,
            file_type=FileType.spreadsheet,
            content={"schema_version": 3, "kind": "spreadsheet", "sheets": sheets},
            initiative_id=initiative.id,
            created_by=user.id,
        )
    else:
        upload = (
            await session.exec(select(Upload).where(Upload.filename == storage_key))
        ).one_or_none()
        # The original name lives in the manifest's asset record — the
        # uploads row's filename IS the storage key.
        filename = asset.original_filename if asset is not None else storage_key
        content_type = (
            await file_versions.stored_file_type(
                File,
                routed_guild_id(session),
                storage_key,
                filename=filename,
                hint=upload.content_type,
            )
            if upload is not None
            else None
        )
        if upload is None or content_type is None:
            # Uploads were excluded from this backup, the blob was not
            # restored, or it is not a type an uploaded file holds — recorded, not
            # silently dropped.
            return EntryResult(
                **base,
                status="skipped",
                error=ImportEngineMessages.IMPORT_ASSET_MISSING,
            )
        file = File(
            name=entry.title,
            file_type=FileType.file,
            content={},
            initiative_id=initiative.id,
            created_by=user.id,
        )
        stored = {
            "file_url": f"/uploads/{routed_guild_id(session)}/{storage_key}",
            "original_filename": filename,
            "file_content_type": content_type,
            "file_size": upload.size_bytes,
        }

    try:
        async with session.begin_nested():
            session.add(file)
            await session.flush()
            await grant_ownership(
                session,
                tool=Tool.file,
                entity_id=file.id,
                target_initiative=initiative,
                importer=user,
            )
            if stored:
                await file_versions.add_version(
                    session, file, created_by=user.id, **stored
                )

            await TagRestore(session).attach(file, entry.tags)
            props = PropertyRestore(
                session, initiative_id=initiative.id, context=context
            )
            await props.attach(
                file,
                [EnvelopePropertyValue.model_validate(p) for p in entry.properties],
            )
            unmatched_handles = await props.settle(file)
    except Exception:
        logger.exception(
            "backup file entry failed path=%s asset=%s", entry.path, entry.asset
        )
        return EntryResult(
            **base, status="failed", error=ImportEngineMessages.IMPORT_APPLY_FAILED
        )
    # The id is reported so the entry can be an end of an edge — a file
    # placed in a wiki is a ``file part_of wiki``, resolved by the
    # deferred pass once the wiki entry has been applied too.
    return EntryResult(
        **base,
        status="created",
        detail=EnvelopeImportResult(
            entity_id=file.id,
            entity_title=file.name,
            created={Tool.file.plural: 1},
            unmatched_handles=unmatched_handles,
        ),
    )


async def _restore_assets(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    manifest: BackupManifest,
    guild_id: int,
    user: User,
    result: BackupImportResult,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
) -> list[str]:
    """Restore the manifest's ``assets/`` files through
    :func:`archive_assets.restore_assets`, each held to the rule for any
    upload, and count what happened on ``result``. Returns the keys written.

    A file named but not in the zip is reported as ``asset_missing``; one that
    is not a file this app holds is left out and reported as such. Either way
    an entry that needed it is skipped with ``IMPORT_ASSET_MISSING``.
    """
    from app.services.tenant.spreadsheet_import import TEXT_TABLE_SUFFIXES

    assets: dict[str, ArchiveAsset] = {}
    for asset in manifest.assets:
        if asset.storage_key.lower().endswith(TEXT_TABLE_SUFFIXES):
            # Read into a spreadsheet by its entry, not stored as a file.
            continue
        assets.setdefault(
            asset.storage_key,
            ArchiveAsset(
                key=asset.storage_key,
                member=asset.path,
                kind="upload",
                original_filename=asset.original_filename,
                content_type=asset.content_type,
            ),
        )
    restored = await restore_assets(
        session,
        archive,
        list(assets.values()),
        guild_id=guild_id,
        user=user,
        heartbeat=heartbeat,
    )
    result.assets_deduped += restored.deduped
    result.assets_restored += len(restored.written)
    result.asset_bytes += restored.restored_bytes
    result.warnings.extend(f"asset_missing:{key}" for key in restored.missing)
    result.warnings.extend(restored.warnings)
    return restored.written
