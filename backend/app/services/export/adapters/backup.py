"""Aggregate export sources: a whole initiative or a whole guild, one zip.

Two modes ride one selector (persisted in the job row, replayed by the
worker):

* ``backup`` — every included tool in its importable format (the per-tool
  JSON envelopes the single-entity exports emit), plus optionally the upload
  blobs the exported files reference, indexed by a root ``manifest.json``
  (see ``schemas/tenant/backup_export.py``). One archive a future import
  wizard consumes whole.
* ``report`` — the same enumeration rendered in per-tool report formats
  chosen by the caller (a project PDF beside a queue CSV beside a calendar
  ICS), zipped with the same folder layout, no manifest/assets.

Layout (identical for both scopes — an initiative backup is a guild backup
with one ``initiatives/`` entry, so ONE import path serves both)::

    manifest.json                                   (backup mode)
    initiatives/{id}-{slug}/projects/{id}-{slug}.initiative-project.json
    initiatives/{id}-{slug}/files/{id}-{slug}.json
    initiatives/{id}-{slug}/queues/{id}-{slug}.initiative-queue.json
    initiatives/{id}-{slug}/counter-groups/{id}-{slug}.initiative-counter-group.json
    initiatives/{id}-{slug}/calendars/{id}-{slug}.initiative-calendar.json
    initiatives/{id}-{slug}/posts/{id}-{slug}.initiative-post.json
    initiatives/{id}-{slug}/wikis/{id}-{slug}.initiative-wiki.json
    initiatives/{id}-{slug}/dashboards/{id}-{slug}.initiative-dashboard.json
    initiatives/{id}-{slug}/structure.json          (backup mode)
    initiatives/{id}-{slug}/properties.json         (backup mode)
    initiatives/{id}-{slug}/collections.json        (backup mode)
    assets/{storage_key}                            (include_uploads only)

Authorization: the initiative source requires the creator to manage the
initiative (its managers, or a guild admin), as its settings page does;
the guild source requires the community's seat. Both are re-checked here so
the worker's render-time replay fails closed if either was lost between
request and render. Within an initiative, enumeration is
DAC-visible-only per tool, and every entity still passes its own
fetch+authorize seam. Projects are included with READ access — the
deliberate aggregate-export relaxation of the standalone write rule.

Per tool: what a tool's rows are, how one is loaded and how it serialises is
its export adapter's (``ADAPTERS``). A ``BackupSection`` states only what the
aggregate adds — which report formats it offers, and the hooks for the tools
whose entries carry more than their envelope — and one loop writes every
section.

Long builds: the worker's creator-routed session enforces
``RLS_CONTEXT_MAX_AGE_SECONDS``; ``build`` re-validates via
``establish_guild_access`` between tool chunks (which also fails closed on
mid-build access revocation).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, cast

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.user_display import handle_of
from app.core.config import settings
from app.core.messages import ExportMessages, InitiativeMessages
from app.models.platform.user import User
from app.core.file_types import FileType, is_stored
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    storage_key_of,
)
from app.services.export.adapters.file import file_type_of
from app.services.export.contract import RenderItem, RenderRequest
from app.core.tools import (
    BULK_EXPORT_TOOLS,
    Tool,
    plural_of,
    tool_envelope_type,
    tool_export_source,
)
from app.services.export.engine import ExportError
from app.services.export.filters import narrow, parse_filters
from app.services.export import delivery
from app.services.platform.csv_export import safe_filename_component
from app.services.export import limits as export_limits
from app.core.user_input_validators import resolve_zone

# Tool keys as they appear in the selector's include/formats maps. Derived:
# a backup covers what the engine can export, so a ninth tool is carried by
# registering it rather than by remembering this line.
_TOOLS = tuple(t.value for t in BULK_EXPORT_TOOLS)

# The rung an aggregate export reads each entity at: the initiative or
# community backup reads what its scope reaches.
_AGGREGATE_ACCESS = "read"

# The ``tool`` an initiative's own files carry. Not a Tool: they describe the
# initiative rather than anything made inside it, which is also why the import
# side applies them ahead of every real tool.
_STRUCTURAL_TOOL = "initiative"

_MIB = 1_048_576
# Refresh the routed session's authorization context this often during a long
# build (see module docstring).
_REFRESH_EVERY = 25


class InitiativeExportAdapter:
    source = "initiative"
    #: The scope a backup's manifest records, which an import reads back.
    scope_kind = "initiative"
    template_id = "data-table"  # protocol requirement; items override per se
    formats = ("zip",)
    always_job = True
    force_zip = True

    @property
    def max_rows(self) -> int:
        return export_limits.EXPORT_MAX_BACKUP_ROWS

    async def count(self, session, *, user, guild_id, params, format) -> int:
        scope = await _resolve_scope(
            session, user, guild_id, params, scope_kind=self.scope_kind
        )
        return await _count_scope(
            session, user, guild_id, params, scope, scope_kind=self.scope_kind
        )

    async def build(self, session, *, user, guild_id, params, format) -> RenderRequest:
        scope = await _resolve_scope(
            session, user, guild_id, params, scope_kind=self.scope_kind
        )
        return await _build_scope(
            session, user, guild_id, params, scope, self.scope_kind
        )


class GuildExportAdapter(InitiativeExportAdapter):
    source = "community"
    scope_kind = "guild"


# ---------------------------------------------------------------------------
# Scope resolution + authorization
# ---------------------------------------------------------------------------


async def _resolve_scope(
    session: AsyncSession, user: User, guild_id: int, params: dict, *, scope_kind: str
):
    """The initiatives this export covers, authorization included: guild scope
    demands the community's seat (re-checked on worker replay); initiative
    scope demands the creator reach the requested initiative. Returns the
    Initiative rows (name/flags feed the manifest)."""
    from sqlalchemy.orm import undefer
    from sqlmodel import select

    from app.models.tenant.initiative import Initiative
    from app.models.platform.guild import CommunityRole
    from app.services.membership import initiative_scope_clause
    from app.services.platform import guilds as guilds_service

    _validate_params(params, scope_kind=scope_kind)

    if scope_kind == "guild":
        membership = await guilds_service.get_membership(
            session, guild_id=guild_id, user_id=user.id
        )
        # The seat itself, held outright: the same rule the create endpoint
        # applies, re-asked here so a job outlives the request under the
        # authority it was started with and no other.
        if membership is None or membership.role is not CommunityRole.superadmin:
            raise ExportError(
                ExportMessages.EXPORT_SUPERADMIN_REQUIRED, status_code=403
            )
        statement = (
            select(Initiative)
            .where(
                initiative_scope_clause(user.id, Initiative.id),
            )
            .order_by(Initiative.id.asc())
        )
        return list(await session.exec(statement))

    initiative_id = params.get("initiative_id")
    try:
        initiative_id = int(initiative_id)
    except (TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    statement = (
        select(Initiative)
        .options(undefer(Initiative.actions))
        .where(
            Initiative.id == initiative_id,
            initiative_scope_clause(user.id, Initiative.id),
        )
    )
    initiative = (await session.exec(statement)).one_or_none()
    if initiative is None:
        # Unreachable initiative — indistinguishable from absent.
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS, status_code=404)
    # An initiative's export is its settings' to take: those who manage it.
    if "manage" not in (initiative.actions or ()):
        raise ExportError(InitiativeMessages.MANAGER_REQUIRED, status_code=403)
    return [initiative]


def _validate_params(params: dict, *, scope_kind: str) -> None:
    mode = params.get("mode") or "backup"
    if mode not in ("backup", "report"):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    include = params.get("include")
    if include is not None:
        if (
            not isinstance(include, dict)
            or not set(include) <= set(_TOOLS)
            or not all(isinstance(v, bool) for v in include.values())
        ):
            raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    filters = params.get("filters")
    if filters is not None:
        if not isinstance(filters, dict) or not set(filters) <= set(_TOOLS):
            raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
        for tool, raw in filters.items():
            parse_filters(Tool(tool), raw)
    if mode == "report":
        for tool, fmt in (params.get("formats") or {}).items():
            section = _SECTIONS_BY_KEY.get(tool)
            if section is not None and section.type_report_formats:
                allowed = section.type_report_formats
                if not isinstance(fmt, dict) or not all(
                    file_type in allowed and value in allowed[file_type]
                    for file_type, value in fmt.items()
                ):
                    raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)
            elif (
                section is None
                or not isinstance(fmt, str)
                or fmt not in section.report_formats
            ):
                raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)


def _included(params: dict, tool: str) -> bool:
    include = params.get("include")
    if include is None:
        return True
    return bool(include.get(tool, False))


def _filters(params: dict, section: BackupSection):
    return parse_filters(section.tool, (params.get("filters") or {}).get(section.key))


async def _section_ids(
    session: AsyncSession,
    user: User,
    params: dict,
    section: BackupSection,
    initiative_id: int,
) -> list[int]:
    """One tool's entities in one initiative that the creator may export and
    the tool's filters leave."""
    return await narrow(
        session,
        user,
        section.tool,
        _filters(params, section),
        await section.adapter.initiative_ids(session, initiative_id),
    )


def _include_uploads(params: dict) -> bool:
    mode = params.get("mode") or "backup"
    if mode == "report":
        # Report mode has no uploads toggle: uploaded files ride as their
        # original blobs whenever files are included.
        return True
    return bool(params.get("include_uploads", True))


# ---------------------------------------------------------------------------
# Enumeration (shared by count / estimate / build)
# ---------------------------------------------------------------------------


async def _enumerate(
    session: AsyncSession, user: User, params: dict, initiatives
) -> dict[str, dict[int, list[int]]]:
    """Per tool, per initiative: the entity ids the creator may export."""
    ids: dict[str, dict[int, list[int]]] = {tool: {} for tool in _TOOLS}
    for initiative in initiatives:
        for section in _SECTIONS:
            if not _included(params, section.key):
                continue
            ids[section.key][initiative.id] = await _section_ids(
                session, user, params, section, initiative.id
            )
    return ids


async def _count_scope(
    session: AsyncSession,
    user: User,
    guild_id: int,
    params: dict,
    initiatives,
    *,
    scope_kind: str = "initiative",
) -> int:
    """Row proxy: entities + tasks + (uploads MiB when they ride). Also
    enforces the uploads byte cap up front so an oversized backup 400s before
    a job row exists.

    Guild scope measures the WHOLE blob store, because that is what it bundles
    — the blobs files reference plus the ones nothing points at. Counting
    only the referenced ones here would let an over-cap export through to the
    worker and fail it there instead of answering now."""

    ids = await _enumerate(session, user, params, initiatives)
    total = sum(
        len(v) for per_initiative in ids.values() for v in per_initiative.values()
    )

    total += await _task_rows(session, user, params, ids["project"])

    if _include_uploads(params) and (
        scope_kind == "guild" or _included(params, Tool.file.value)
    ):
        if scope_kind == "guild":
            from app.services.tenant.attachments import get_guild_storage_usage

            upload_bytes = await get_guild_storage_usage(guild_id)
        else:
            upload_bytes = await _known_upload_bytes(session, ids[Tool.file.value])
        if upload_bytes > export_limits.EXPORT_MAX_BACKUP_UPLOAD_BYTES:
            raise ExportError(ExportMessages.EXPORT_TOO_LARGE)
        total += upload_bytes // _MIB
    return total


async def _task_rows(
    session: AsyncSession,
    user: User,
    params: dict,
    project_ids: dict[int, list[int]],
) -> int:
    """How many tasks the projects' exports carry: every one, or those the
    project task filter leaves."""
    from sqlalchemy import func
    from sqlmodel import select

    from app.models.tenant.task import Task
    from app.services.export.adapters.project import count_matching_tasks

    ids = [project_id for per in project_ids.values() for project_id in per]
    if not ids:
        return 0
    tasks = getattr(_filters(params, _SECTIONS_BY_KEY["project"]), "tasks", None)
    if tasks is None:
        return (
            await session.exec(
                select(func.count()).select_from(Task).where(Task.project_id.in_(ids))
            )
        ).one()
    return await count_matching_tasks(
        session, user, ids, tasks, resolve_zone(params.get("tz")).key
    )


async def _known_upload_bytes(
    session: AsyncSession, file_ids: dict[int, list[int]]
) -> int:
    """Uploaded file blob bytes for the enumerated files (the cheap,
    pre-build number — embedded document images resolve at build time)."""
    from sqlalchemy import func
    from sqlmodel import select

    from app.models.tenant.file import File, FileVersion

    all_ids = [d for per in file_ids.values() for d in per]
    if not all_ids:
        return 0
    total = (
        await session.exec(
            select(func.coalesce(func.sum(FileVersion.file_size), 0))
            .join(File, File.current_version_id == FileVersion.id)
            .where(File.id.in_(all_ids))
        )
    ).one()
    return int(total or 0)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


async def _build_scope(
    session: AsyncSession,
    user: User,
    guild_id: int,
    params: dict,
    initiatives,
    scope_kind: str,
) -> RenderRequest:
    from app.core.version import get_version
    from app.models.platform.guild import Guild
    from app.schemas.tenant.backup_export import (
        BACKUP_SCHEMA_VERSION,
        BackupManifest,
        ManifestCommunity,
        ManifestInitiative,
    )

    mode = params.get("mode") or "backup"
    now = datetime.now(resolve_zone(params.get("tz")))
    builder = _ScopeBuilder(
        session=session,
        user=user,
        guild_id=guild_id,
        params=params,
        now=now,
        mode=mode,
    )
    for initiative in initiatives:
        await builder.add_initiative(initiative)
    # The community itself, after its initiatives: what it owns directly.
    await builder.add_guild_sections(scope_kind)
    if scope_kind == "guild":
        await builder.add_remaining_uploads()

    items = builder.items
    if mode == "backup":
        guild = await session.get(Guild, guild_id)
        manifest = BackupManifest(
            type=f"{scope_kind}-backup",
            schema_version=BACKUP_SCHEMA_VERSION,
            app_version=get_version(),
            exported_at=datetime.now(timezone.utc),
            exported_by_handle=handle_of(user),
            source_instance_url=settings.APP_URL,
            guild=ManifestCommunity(
                id=guild_id,
                name=guild.name if guild else "",
                description=guild.description if guild else None,
                is_community=bool(guild.is_community) if guild else False,
            ),
            include_uploads=_include_uploads(params),
            initiatives=[
                ManifestInitiative(
                    id=i.id,
                    name=i.name,
                    description=i.description,
                    color=i.color,
                    tools=_initiative_tool_states(params, i),
                    join_policy=i.join_policy,
                )
                for i in initiatives
            ],
            guild_sections=builder.guild_sections,
            entries=builder.entries,
            assets=builder.assets,
            skipped=builder.skipped,
            people=await builder.people(),
        )
        items = [
            RenderItem(
                key="manifest",
                data=manifest.model_dump(mode="json"),
                filename="manifest.json",
                format="json",
            ),
            *items,
        ]
    return RenderRequest(
        guild_id=guild_id,
        template_id="data-table",
        format="zip",
        batch=tuple(items),
        initiative_ids=frozenset(
            {initiative.id for initiative in initiatives} | builder.reach
        ),
    )


def _initiative_tool_states(params: dict, initiative) -> dict[str, str]:
    states: dict[str, str] = {}
    for tool in _TOOLS:
        # The switch column via the enum, not `tool + "s"`: every tool now
        # carries a column, so a missing-attribute default would hide a real
        # mismatch rather than cover for the two that used to have none.
        flag = getattr(initiative, Tool(tool).view_permission)
        if not flag:
            states[tool] = "disabled"
        elif _included(params, tool):
            states[tool] = "included"
        else:
            states[tool] = "excluded"
    return states


def _permission_key(permission) -> str:
    """The permission's name — the enum's value, not its repr."""
    key = permission.permission_key
    return str(getattr(key, "value", key))


def _slug(entity_id: int, title: str) -> str:
    return f"{entity_id}-{safe_filename_component(title).lower() or 'untitled'}"


class _ScopeBuilder:
    """Accumulates render items + manifest records, one initiative at a time,
    refreshing the routed session's authorization between chunks."""

    def __init__(self, *, session, user, guild_id, params, now, mode):
        self.session = session
        self.user = user
        self.guild_id = guild_id
        self.params = params
        self.now = now
        self.mode = mode
        self.items: list[RenderItem] = []
        self.entries: list = []
        self.assets: list = []
        self.skipped: list = []
        self.guild_sections: list = []
        # Handle -> (display name, comments seen). Accumulated as the project
        # envelopes are built, because that is where comment authors are, and
        # written into the manifest so the import plan can ask about them
        # without opening a single envelope.
        self._people: dict[str, tuple[str | None, int]] = {}
        self._asset_index: dict[str, Any] = {}
        self._asset_bytes = 0
        self._since_refresh = 0
        #: The initiatives beyond those in scope whose files and tasks
        #: the items name.
        self.reach: set[int] = set()
        # The images each native file embeds, and the stored size and
        # type of each, loaded once per initiative's files.
        self._embedded: dict[int, list[dict]] = {}
        self._upload_info: dict[str, tuple[int, str | None]] = {}
        # The community's member profiles, read once for every initiative's
        # roster.
        self._profiles: dict[int, Any] | None = None

    async def _refresh_access(self, force: bool = False) -> None:
        """Re-validate the creator's guild access mid-build — keeps a long
        build under RLS_CONTEXT_MAX_AGE_SECONDS and fails closed if access
        was revoked while the job ran. always_job guarantees this session is
        the worker's own, never a request session."""
        self._since_refresh += 1
        if not force and self._since_refresh < _REFRESH_EVERY:
            return
        from app.api.deps import establish_guild_access

        await establish_guild_access(
            self.session,
            self.user,
            self.guild_id,
            on_behalf=True,
        )
        self._since_refresh = 0

    async def add_initiative(self, initiative) -> None:
        await self._refresh_access(force=True)
        folder = f"initiatives/{_slug(initiative.id, initiative.name)}"
        for section in _SECTIONS:
            await self._add_section(section, initiative, folder)
        await self._add_initiative_structure(initiative, folder)
        await self._add_initiative_properties(initiative, folder)
        await self._add_initiative_collections(initiative, folder)
        await self._link_wiki_files(initiative)

    # -- per-tool sections ---------------------------------------------------

    async def _add_section(
        self, section: BackupSection, initiative, folder: str
    ) -> None:
        """Every entity of one tool in this initiative, in the order the tool
        lists them.

        Each entity is loaded through the adapter's own seam. Where the adapter
        or the section loads something across a batch, the initiative's whole
        list is loaded first and prepared in one pass; otherwise each entity is
        loaded and written in turn, so no more than one is held at a time.
        """
        if not _included(self.params, section.key):
            return
        if self.mode != "backup" and not section.in_reports:
            return
        adapter = section.adapter
        ids = await _section_ids(
            self.session, self.user, self.params, section, initiative.id
        )
        if ids:
            batched = adapter.prepares or section.preload is not None
            for batch in [ids] if batched else [[entity_id] for entity_id in ids]:
                entities = []
                for entity_id in batch:
                    await self._refresh_access()
                    entities.append(await self._fetch(section, entity_id))
                ctx = BuildContext(
                    format="json",
                    user=self.user,
                    guild_id=self.guild_id,
                    now=self.now,
                    filters=_filters(self.params, section),
                )
                ctx = replace(
                    ctx, prepared=await adapter.prepare(self.session, entities, ctx)
                )
                self.reach |= await adapter.prepared_reach(
                    self.session, replace(ctx, format=self._tool_format(section))
                )
                if section.preload is not None:
                    await section.preload(self, entities)
                for entity_id, entity in zip(batch, entities):
                    await self._add_entity(
                        section, initiative, folder, entity_id, entity, ctx
                    )
        if section.finish is not None:
            await section.finish(self, initiative, ids)

    async def _fetch(self, section: BackupSection, entity_id: int) -> Any:
        if section.fetch is not None:
            return await section.fetch(
                section.adapter, self.session, self.user, self.guild_id, entity_id
            )
        return await section.adapter.fetch(
            self.session,
            self.user,
            self.guild_id,
            entity_id,
            access=_AGGREGATE_ACCESS,
        )

    async def _add_entity(
        self,
        section: BackupSection,
        initiative,
        folder: str,
        entity_id: int,
        entity: Any,
        ctx: BuildContext,
    ) -> None:
        """One entity: its envelope (and manifest entry), or its report file."""
        adapter = section.adapter
        title = adapter.title(entity)
        path_stem = f"{folder}/{section.folder}/{_slug(entity_id, title)}"
        if section.write_apart is not None and section.write_apart(
            self, entity, initiative, path_stem
        ):
            return
        fmt = (
            section.format_for(self, entity)
            if section.format_for is not None
            else self._tool_format(section)
        )
        item = adapter.item(entity, replace(ctx, format=fmt))
        if fmt != "json":
            self._append_report(item, f"{path_stem}.{fmt}", fmt, adapter.template_id)
            return
        path = f"{path_stem}{section.envelope_suffix}"
        if section.before_envelope is not None:
            await section.before_envelope(self, entity, path)
        await self._append_backup(
            item,
            path=path,
            tool=section.key,
            type=tool_envelope_type(section.tool),
            schema_version=item.data["schema_version"],
            entity_id=entity_id,
            title=title,
            initiative_id=initiative.id,
        )

    def _skip(
        self, tool: Tool, entity_id: int, title: str, initiative, reason: str
    ) -> None:
        """Record an entity the archive leaves out, and why."""
        from app.schemas.tenant.backup_export import ManifestSkipped

        self.skipped.append(
            ManifestSkipped(
                tool=tool.value,
                entity_id=entity_id,
                title=title,
                initiative_id=initiative.id,
                reason=reason,
            )
        )

    # -- section hooks: projects -----------------------------------------------

    async def _note_project_people(self, envelope, path: str) -> None:
        """Note who the project's envelope names, for the manifest's people."""
        self._record_people(envelope)

    # -- section hooks: files ----------------------------------------------

    def _file_format(self, file) -> str:
        """Report mode offers per-type choices for native/spreadsheet;
        everything else (whiteboards, smart links) rides as its canonical json
        envelope in both modes."""
        file_type = file_type_of(file)
        doc_formats = self._file_formats()
        if self.mode == "backup" or file_type not in doc_formats:
            return "json"
        return doc_formats[file_type]

    def _write_uploaded_file(self, file, initiative, path_stem: str) -> bool:
        """An uploaded file is its blob, registered as an asset — or, with
        uploads left out, a skipped entry."""
        if not is_stored(file_type_of(file)):
            return False
        if not _include_uploads(self.params):
            self._skip(
                Tool.file,
                file.id,
                file.name,
                initiative,
                "uploads_excluded",
            )
            return True
        self._add_uploaded_file(file, initiative, path_stem, _file_metadata(file))
        return True

    def _add_uploaded_file(self, file, initiative, path_stem: str, metadata) -> None:
        from app.schemas.tenant.backup_export import ManifestEntry

        version = file.current_version
        storage_key = storage_key_of(version.file_url)
        asset_path = self._register_asset(
            storage_key,
            original_filename=version.original_filename,
            content_type=version.file_content_type,
            size_bytes=int(version.file_size or 0),
            referenced_by=path_stem,
        )
        if self.mode == "backup":
            self.entries.append(
                ManifestEntry(
                    path=asset_path,
                    tool=Tool.file.value,
                    type="file",
                    schema_version=None,
                    entity_id=file.id,
                    title=file.name,
                    initiative_id=initiative.id,
                    tags=metadata["tags"],
                    properties=metadata["properties"],
                    asset=asset_path,
                )
            )

    async def _preload_embedded_assets(self, files: list) -> None:
        """The images the native files embed, and each one's stored size
        and type in one query, for the envelopes about to be written."""
        self._embedded = {}
        self._upload_info = {}
        if not _include_uploads(self.params):
            return
        from app.services.export.lexical import blocks_from_editor_state

        keys: list[str] = []
        for file in files:
            if file_type_of(file) != FileType.lexical.value:
                continue
            if self._file_format(file) != "json":
                continue
            _, assets = blocks_from_editor_state(
                file.content or {}, guild_id=self.guild_id
            )
            if not assets:
                continue
            self._embedded[file.id] = assets
            keys.extend(a["key"] for a in assets if a["key"] not in self._asset_index)
        self._upload_info = await self._upload_rows(list(dict.fromkeys(keys)))

    async def _collect_embedded_assets(self, file, entry_path: str) -> None:
        """Native files can embed same-guild images; when uploads ride,
        those blobs join the archive too — at their REAL stored size, so they
        count against the byte cap exactly like uploaded file blobs (the
        pre-flight count only sees uploaded files, so build is where embedded
        bytes get bounded; an over-cap build fails the job closed)."""
        for asset in self._embedded.pop(file.id, []):
            size_bytes, content_type = self._upload_info.get(asset["key"], (0, None))
            self._register_asset(
                asset["key"],
                original_filename=asset.get("name"),
                content_type=content_type,
                size_bytes=size_bytes,
                referenced_by=entry_path,
            )

    # -- section hooks: dashboards ---------------------------------------------

    async def _record_foreign_dashboards(self, initiative, exported: list[int]) -> None:
        """Dashboards built on a plug-in this build does not ship.

        The dashboard listing applies the provenance filter, so the ones it
        left out are recovered here separately in order to record them: an
        archive that just omitted them would not say they existed.
        """
        if self.mode != "backup":
            return
        if not getattr(initiative, Tool.dashboard.view_permission, False):
            return
        from sqlmodel import select

        from app.models.tenant.dashboard import Dashboard
        from app.services.export.provenance import THIRD_PARTY_REASON

        kept = set(exported)
        rows = await self.session.exec(
            select(Dashboard.id, Dashboard.name).where(
                Dashboard.initiative_id == initiative.id
            )
        )
        for dashboard_id, name in rows:
            if dashboard_id in kept:
                continue
            self._skip(
                Tool.dashboard, dashboard_id, name, initiative, THIRD_PARTY_REASON
            )

    # -- people ----------------------------------------------------------------

    def _record_people(self, envelope) -> None:
        """Note everyone a project envelope names, and how often they are
        quoted.

        Counted per handle across the whole archive rather than per project:
        the importer answers "who is this" once, and one answer covers every
        comment and every assignment that name is on. An assignee who wrote
        nothing is listed with a count of none — the restore still has to be
        told who they are, or their tasks arrive unassigned.
        """
        for task in envelope.tasks:
            for comment in task.comments:
                handle = (comment.author_handle or "").strip()
                if not handle:
                    continue
                name, count = self._people.get(handle, (None, 0))
                self._people[handle] = (name or comment.author_name, count + 1)
            for raw in task.assignee_handles:
                handle = (raw or "").strip()
                if handle and handle not in self._people:
                    self._people[handle] = (None, 0)

    def _record_property_people(self, *payloads) -> None:
        """Note everyone a user-type property value names, in any entry.

        Every tool's properties pass through here — a task's, a file's,
        an event's, an uploaded file's — because a restore places those values
        through the people step's answer, and the step only asks about the
        people the manifest lists. Counted as quoting nothing, like an
        assignee: the number is for comments.
        """
        from app.services.import_engine.people import user_reference_handles

        for payload in payloads:
            for handle in user_reference_handles(payload):
                if handle not in self._people:
                    self._people[handle] = (None, 0)

    def _record_mentioned_people(self, payload) -> None:
        """Note everyone an entry's text mentions — a description, a comment,
        a file, a page. A restore links a mention through the people
        step's answer, so the step has to ask about them; counted as quoting
        nothing, because the number is for comments."""
        from app.services.import_engine.mentions import mention_handles_in

        for handle in mention_handles_in(payload):
            if handle not in self._people:
                self._people[handle] = (None, 0)

    async def people(self) -> list:
        """The archive's people, most-quoted first — which is the order the
        wizard should ask about them in. Each named as the community names
        them, where they are still in it."""
        from app.schemas.tenant.backup_export import ManifestPerson

        names = {
            handle_of(profile): profile.display_name
            for profile in (await self._guild_profiles()).values()
        }
        return [
            ManifestPerson(
                handle=handle, name=names.get(handle) or name, comment_count=count
            )
            for handle, (name, count) in sorted(
                self._people.items(), key=lambda kv: (-kv[1][1], kv[0])
            )
        ]

    async def _link_wiki_files(self, initiative) -> None:
        """Say which wiki each uploaded file sits in, now that both entries
        exist.

        A file joins a wiki by an edge (``file part_of wiki``), not
        by a column, and the edge names rows this archive is about to stop
        being able to identify. So it crosses as ``attach_to`` on the
        file's own entry, naming the wiki by **entry path** — which is
        the one thing both sides agree on — and the importer rebuilds the
        edge once both ends have been applied.

        Runs after both tools have been written for this initiative, because
        files are added before wikis and a path cannot be named before it
        exists. A file in more than one wiki keeps the first: one entry
        carries one placement, and a second copy of the file is not what the
        edge said. The page it is filed under in that wiki travels with it, by
        the page's slug.
        """
        if self.mode != "backup":
            return
        from sqlmodel import select

        from app.core.relationships import RelationshipType, node_id
        from app.core.search import SearchEntityType
        from app.models.tenant.relationship import EntityRelationship
        from app.schemas.tenant.backup_export import ManifestAttachTo

        wiki_paths = {
            entry.entity_id: entry.path
            for entry in self.entries
            if entry.tool == Tool.wiki.value
            and entry.type == tool_envelope_type(Tool.wiki)
            and entry.initiative_id == initiative.id
        }
        file_entries = {
            entry.entity_id: entry
            for entry in self.entries
            if entry.type == "file" and entry.initiative_id == initiative.id
        }
        if not wiki_paths or not file_entries:
            return

        edges = (
            await self.session.exec(
                select(EntityRelationship).where(
                    EntityRelationship.source_node.in_(
                        [
                            node_id(SearchEntityType.file, file_id)
                            for file_id in file_entries
                        ]
                    ),
                    EntityRelationship.target_node.in_(
                        [
                            node_id(SearchEntityType.wiki, wiki_id)
                            for wiki_id in wiki_paths
                        ]
                    ),
                    EntityRelationship.relationship_type
                    == RelationshipType.part_of.value,
                    EntityRelationship.removed_at.is_(None),
                )
            )
        ).all()
        # The page each file is filed under, by the slug its page is
        # written with in the wiki's envelope.
        from app.models.tenant.wiki import Wiki, WikiPage
        from app.services.tenant.wikis import file_parent

        wikis = {
            wiki.id: wiki
            for wiki in (
                await self.session.exec(
                    select(Wiki).where(Wiki.id.in_(list(wiki_paths)))
                )
            ).all()
        }
        page_slugs = dict(
            (
                await self.session.exec(
                    select(WikiPage.id, WikiPage.slug).where(
                        WikiPage.wiki_id.in_(list(wiki_paths))
                    )
                )
            ).all()
        )
        for edge in edges:
            entry = file_entries.get(edge.source_id)
            path = wiki_paths.get(edge.target_id)
            if entry is None or path is None or entry.attach_to is not None:
                continue
            wiki = wikis.get(edge.target_id)
            parent = file_parent(wiki, edge.source_id) if wiki else None
            entry.attach_to = ManifestAttachTo(
                kind="wiki", ref=path, page=page_slugs.get(parent) if parent else None
            )

    # -- helpers ---------------------------------------------------------------

    def _tool_format(self, section: BackupSection) -> str:
        if self.mode == "backup":
            return "json"
        formats = self.params.get("formats") or {}
        value = formats.get(section.key)
        return value if isinstance(value, str) else "json"

    def _file_formats(self) -> dict[str, str]:
        if self.mode == "backup":
            return {}
        formats = self.params.get("formats") or {}
        value = formats.get(Tool.file.value)
        return dict(value) if isinstance(value, dict) else {}

    async def _guild_profiles(self) -> dict[int, Any]:
        """The community's member profiles by user id, read once per build.
        Narrowed to this guild's members; an initiative's roster is a subset
        of it. ``display_name`` is the name the member set, or ``None``."""
        if self._profiles is None:
            from sqlmodel import select

            from app.models.platform.user_profile_view import (
                GuildMember,
                MemberProfile,
            )

            self._profiles = {
                profile.id: profile
                for profile in await self.session.exec(
                    select(MemberProfile).where(
                        MemberProfile.id.in_(select(GuildMember.id))
                    )
                )
            }
        return self._profiles

    async def _add_initiative_structure(self, initiative, folder: str) -> None:
        """The initiative itself: who was in it, the roles they held, and what
        each role could do.

        Tool envelopes carry content and name people by handle; none of them
        carries the access structure the content sat inside. Without it a
        restored initiative is a pile of work with nobody in it.

        Report mode skips this — it renders content for people to read, and a
        role matrix is not a report.
        """
        if self.mode != "backup":
            return
        from sqlmodel import select

        from app.core.user_display import handle_of
        from app.models.tenant.initiative import (
            InitiativeMember,
            InitiativeRoleModel,
            InitiativeRolePermission,
        )

        roles = list(
            await self.session.exec(
                select(InitiativeRoleModel)
                .where(InitiativeRoleModel.initiative_id == initiative.id)
                .order_by(InitiativeRoleModel.position.asc())
            )
        )
        permissions: dict[int, list] = {}
        if roles:
            rows = await self.session.exec(
                select(InitiativeRolePermission).where(
                    InitiativeRolePermission.initiative_role_id.in_(
                        [r.id for r in roles]
                    )
                )
            )
            for permission in rows:
                permissions.setdefault(permission.initiative_role_id, []).append(
                    permission
                )

        members = list(
            await self.session.exec(
                select(InitiativeMember)
                .where(InitiativeMember.initiative_id == initiative.id)
                .order_by(InitiativeMember.user_id.asc())
            )
        )
        profiles = await self._guild_profiles() if members else {}
        if not roles and not members:
            return

        role_names = {role.id: role.name for role in roles}
        payload = {
            "type": "initiative-structure",
            "schema_version": 1,
            "initiative_id": initiative.id,
            "name": initiative.name,
            "roles": [
                {
                    "name": role.name,
                    "display_name": role.display_name,
                    "is_builtin": role.is_builtin,
                    "is_manager": role.is_manager,
                    "override_share_restrictions": role.override_share_restrictions,
                    "position": role.position,
                    # Permission keys by name, enabled-only: a role is what it
                    # CAN do, and a disabled row is the default restated.
                    "permissions": sorted(
                        _permission_key(p)
                        for p in permissions.get(role.id, [])
                        if p.enabled
                    ),
                }
                for role in roles
            ],
            "members": [
                {
                    "user_id": member.user_id,
                    "handle": handle_of(profiles[member.user_id])
                    if member.user_id in profiles
                    else None,
                    "name": getattr(profiles.get(member.user_id), "display_name", None),
                    # By role NAME: role ids are per-initiative and mean
                    # nothing once the archive is opened somewhere else.
                    "role": role_names.get(member.role_id),
                    "joined_at": member.joined_at.isoformat()
                    if member.joined_at
                    else None,
                }
                for member in members
            ],
        }
        path = f"{folder}/structure.json"
        await self._append_backup(
            RenderItem(key=path, data=payload, filename=path, format="json"),
            path=path,
            tool=_STRUCTURAL_TOOL,
            type="initiative-structure",
            schema_version=1,
            entity_id=initiative.id,
            title=initiative.name,
            initiative_id=initiative.id,
        )

    async def _add_initiative_properties(self, initiative, folder: str) -> None:
        """The initiative's property definitions.

        Envelopes carry property VALUES by name and type; the definitions are
        what say a property exists at all, what a select may be set to, and
        what order they read in. Without them an import rebuilds a definition
        from the first value it sees, so a select arrives holding only the
        options somebody happened to use.
        """
        if self.mode != "backup":
            return
        from sqlmodel import select

        from app.models.tenant.property import PropertyDefinition

        rows = list(
            await self.session.exec(
                select(PropertyDefinition)
                .where(PropertyDefinition.initiative_id == initiative.id)
                .order_by(PropertyDefinition.position.asc())
            )
        )
        if not rows:
            return
        payload = {
            "type": "initiative-properties",
            "schema_version": 1,
            "initiative_id": initiative.id,
            "properties": [
                {
                    "name": row.name,
                    "type": row.type.value,
                    "position": float(row.position),
                    "color": row.color,
                    "options": list(row.options or []),
                }
                for row in rows
            ],
        }
        path = f"{folder}/properties.json"
        await self._append_backup(
            RenderItem(key=path, data=payload, filename=path, format="json"),
            path=path,
            tool=_STRUCTURAL_TOOL,
            type="initiative-properties",
            schema_version=1,
            entity_id=initiative.id,
            title=initiative.name,
            initiative_id=initiative.id,
        )

    async def _add_initiative_collections(self, initiative, folder: str) -> None:
        """The initiative's collections the creator can see, each under the id
        it has here, holding its files by theirs: an import puts each one
        together from the files it made of them."""
        if self.mode != "backup" or not _included(self.params, Tool.file.value):
            return
        from sqlmodel import col, select

        from app.db.query import ids_in
        from app.models.tenant.collection import Collection, CollectionFile
        from app.models.tenant.file import File
        from app.services.tenant import properties as properties_service
        from app.services.tenant import tags as tags_service

        rows = list(
            await self.session.exec(
                select(Collection)
                .where(Collection.initiative_id == initiative.id)
                .order_by(col(Collection.id))
            )
        )
        if not rows:
            return
        held: dict[int, list[int]] = {}
        for collection_id, file_id in await self.session.exec(
            select(CollectionFile.collection_id, CollectionFile.file_id)
            .join(File, col(File.id) == CollectionFile.file_id)
            .where(ids_in(CollectionFile.collection_id, [row.id for row in rows]))
            .order_by(col(CollectionFile.added_at), col(CollectionFile.file_id))
        ):
            held.setdefault(collection_id, []).append(file_id)
        await tags_service.annotate_tags(self.session, rows)
        await properties_service.annotate_properties(self.session, rows)
        payload = {
            "type": "initiative-collections",
            "schema_version": 1,
            "initiative_id": initiative.id,
            "collections": [
                {
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "cover_file_id": row.cover_file_id
                    if row.cover_file_id in held.get(row.id, [])
                    else None,
                    "file_ids": held.get(row.id, []),
                    **_file_metadata(row),
                }
                for row in rows
            ],
        }
        path = f"{folder}/collections.json"
        await self._append_backup(
            RenderItem(key=path, data=payload, filename=path, format="json"),
            path=path,
            tool=_STRUCTURAL_TOOL,
            type="initiative-collections",
            schema_version=1,
            entity_id=initiative.id,
            title=initiative.name,
            initiative_id=initiative.id,
        )

    async def add_guild_sections(self, scope_kind: str) -> None:
        """What the community owns outside any initiative.

        Backup mode only, and gated by each section's own scope — see
        ``guild_sections.GuildSection.scopes``.
        """
        if self.mode != "backup":
            return
        from app.schemas.tenant.backup_export import ManifestCommunitySection
        from app.services.export.guild_sections import SectionContext, sections_for

        # The manifest's own list, so anything a section leaves out is
        # reported beside everything else that was.
        ctx = SectionContext(
            session=self.session,
            user=self.user,
            guild_id=self.guild_id,
            skipped=self.skipped,
        )
        for section in sections_for(scope_kind):
            await self._refresh_access()
            built = await section.build(ctx)
            if built is None:  # nothing of this kind — absent reads as none
                continue
            payload, count = built
            self.items.append(
                RenderItem(
                    key=section.path,
                    data=payload,
                    filename=section.path,
                    format="json",
                )
            )
            self.guild_sections.append(
                ManifestCommunitySection(
                    key=section.key, path=section.path, count=count
                )
            )

    async def add_remaining_uploads(self) -> None:
        """Every blob in the guild's store that nothing already pulled in.

        Assets otherwise ride with the entity that references them, so a file
        nobody currently points at — an image removed from a page, anything
        uploaded and not yet placed — would be the one thing a "full backup"
        silently dropped. Guild scope only: the store is guild-wide, and an
        initiative export has no claim on it. Listed on
        :func:`~app.services.tenant.attachments.guild_wide`, so it is every
        file whoever can read it.
        """
        if self.mode != "backup" or not _include_uploads(self.params):
            return
        from sqlmodel import col, select

        from app.models.tenant.upload import Upload
        from app.services.tenant.attachments import THUMBNAIL_PREFIX, guild_wide

        async with guild_wide(self.guild_id) as session:
            rows = (
                await session.exec(
                    select(Upload.filename, Upload.size_bytes, Upload.content_type)
                    # A thumbnail is made again from its picture.
                    .where(~col(Upload.filename).startswith(THUMBNAIL_PREFIX))
                    .order_by(Upload.id.asc())
                )
            ).all()
        for storage_key, size_bytes, content_type in rows:
            if storage_key in self._asset_index:
                continue
            await self._refresh_access()
            self._register_asset(
                storage_key,
                original_filename=None,
                content_type=content_type,
                size_bytes=int(size_bytes or 0),
                referenced_by=None,
            )

    async def _append_backup(
        self, item: RenderItem, *, path: str, **entry_kwargs
    ) -> None:
        from app.services.import_engine.mentions import detach_envelope_mentions
        from app.services.import_engine.references import detach_envelope_references

        await detach_envelope_mentions(self.session, item.data)
        detach_envelope_references(item.data, guild_id=self.guild_id)
        self._record_property_people(item.data, entry_kwargs.get("properties"))
        self._record_mentioned_people(item.data)
        self.items.append(replace(item, filename=path, format="json"))
        if self.mode == "backup":
            from app.schemas.tenant.backup_export import ManifestEntry

            self.entries.append(ManifestEntry(path=path, **entry_kwargs))

    def _append_report(
        self, item: RenderItem, path: str, fmt: str, template_id: str
    ) -> None:
        self.items.append(
            replace(item, filename=path, format=fmt, template_id=template_id)
        )

    async def _upload_rows(self, storage_keys: list) -> dict:
        """Stored size + content type per storage key (``uploads.filename`` IS
        the storage key). Legacy blobs without an uploads row contribute 0."""
        if not storage_keys:
            return {}
        from sqlmodel import select

        from app.models.tenant.upload import Upload

        rows = await self.session.exec(
            select(Upload.filename, Upload.size_bytes, Upload.content_type).where(
                Upload.filename.in_(storage_keys)
            )
        )
        return {
            filename: (int(size or 0), content_type)
            for filename, size, content_type in rows
        }

    def _register_asset(
        self,
        storage_key: str,
        *,
        original_filename,
        content_type,
        size_bytes: int,
        referenced_by: str | None,
    ) -> str:
        from app.schemas.tenant.backup_export import ManifestAsset

        path = f"assets/{storage_key}"
        existing = self._asset_index.get(storage_key)
        if existing is not None:
            if referenced_by and referenced_by not in existing.referenced_by:
                existing.referenced_by.append(referenced_by)
            return path
        self._asset_bytes += size_bytes
        if self._asset_bytes > export_limits.EXPORT_MAX_BACKUP_UPLOAD_BYTES:
            raise ExportError(ExportMessages.EXPORT_TOO_LARGE)
        record = ManifestAsset(
            path=path,
            storage_key=storage_key,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size_bytes,
            referenced_by=[referenced_by] if referenced_by else [],
        )
        self._asset_index[storage_key] = record
        if self.mode == "backup":
            self.assets.append(record)
        self.items.append(
            RenderItem(
                key=path,
                data={
                    "storage_key": storage_key,
                    "filename": original_filename or storage_key,
                    "content_type": content_type,
                },
                filename=path,
                format="file",
            )
        )
        return path


def _file_metadata(file) -> dict:
    from app.services.export.property_values import exported_properties

    return {
        "tags": sorted(tag.name for tag in file.tags or []),
        "properties": exported_properties(file),
    }


# ---------------------------------------------------------------------------
# Sections: one per tool
# ---------------------------------------------------------------------------

#: Loads one entity for an aggregate, given the tool's adapter.
Fetch = Callable[[Any, AsyncSession, User, int, int], Awaitable[Any]]


async def _fetch_wiki_pages(
    adapter: Any, session: AsyncSession, user: User, guild_id: int, wiki_id: int
) -> Any:
    """A wiki and its pages. The files filed in it are written by the
    files section and placed in the wiki by ``attach_to``."""
    return await adapter.fetch_pages(
        session, user, guild_id, wiki_id, access=_AGGREGATE_ACCESS
    )


@dataclass(frozen=True)
class BackupSection:
    """How one tool is written into an initiative or community export.

    Which rows the tool has, how one is loaded and how it serialises are its
    export adapter's. A section states what the aggregate adds: the formats a
    report may ask for, and the hooks for a tool whose entries carry more than
    their envelope. Every hook is optional; a tool with none writes each entity
    as its envelope, or in the report format chosen for it.
    """

    tool: Tool
    #: The formats a report-mode export may choose for this tool. With none
    #: chosen — or none offered — the tool rides as its envelope.
    report_formats: frozenset[str] = frozenset()
    #: Report formats per file type, for the tool whose formats depend on
    #: the entity rather than the tool.
    type_report_formats: Mapping[str, frozenset[str]] = field(default_factory=dict)
    #: Whether a report-mode export carries this tool at all. A tool with no
    #: report shape is left out rather than dropping a lone JSON file into a
    #: zip of PDFs and spreadsheets.
    in_reports: bool = True
    #: Whether an envelope's file name carries its envelope type
    #: (``<slug>.initiative-queue.json``). A file's is ``<slug>.json``.
    type_in_filename: bool = True
    #: Loads one entity; the adapter's ``fetch`` at the read rung otherwise.
    fetch: Fetch | None = None
    #: Loads what the initiative's entities of this tool need across the
    #: batch, before any of them is written.
    preload: Callable[[_ScopeBuilder, list], Awaitable[None]] | None = None
    #: The format one entity is written in; the format chosen for the tool
    #: otherwise.
    format_for: Callable[[_ScopeBuilder, Any], str] | None = None
    #: Writes an entity in some other shape — or records it as skipped — and
    #: answers ``True``; ``False`` writes it the usual way.
    write_apart: Callable[[_ScopeBuilder, Any, Any, str], bool] | None = None
    #: Runs just before an entity's envelope is written, with its path.
    before_envelope: Callable[[_ScopeBuilder, Any, str], Awaitable[None]] | None = None
    #: Runs once after an initiative's entities of this tool are written, with
    #: the ids that were.
    finish: Callable[[_ScopeBuilder, Any, list[int]], Awaitable[None]] | None = None

    @property
    def key(self) -> str:
        """The tool's key in the selector's include/formats maps and on its
        manifest entries."""
        return self.tool.value

    @property
    def adapter(self) -> ToolExportAdapter:
        from app.services.export.adapters import ADAPTERS

        return cast(ToolExportAdapter, ADAPTERS[tool_export_source(self.tool)])

    @property
    def folder(self) -> str:
        """The folder an initiative's entries of this tool sit in."""
        return plural_of(tool_export_source(self.tool))

    @property
    def envelope_suffix(self) -> str:
        if self.type_in_filename:
            return f".{tool_envelope_type(self.tool)}.json"
        return ".json"


#: Every exportable tool's section, in the order an initiative's folder is
#: written.
_SECTIONS: tuple[BackupSection, ...] = (
    BackupSection(
        Tool.project,
        report_formats=frozenset({"pdf", "csv", "xlsx"}),
        before_envelope=_ScopeBuilder._note_project_people,
    ),
    BackupSection(
        Tool.file,
        type_report_formats={
            FileType.lexical.value: frozenset({"pdf", "md", "docx"}),
            FileType.sheet.value: frozenset({"csv", "xlsx"}),
        },
        type_in_filename=False,
        preload=_ScopeBuilder._preload_embedded_assets,
        format_for=_ScopeBuilder._file_format,
        write_apart=_ScopeBuilder._write_uploaded_file,
        before_envelope=_ScopeBuilder._collect_embedded_assets,
    ),
    BackupSection(Tool.queue, report_formats=frozenset({"pdf", "csv", "xlsx", "md"})),
    BackupSection(
        Tool.counter_group, report_formats=frozenset({"pdf", "csv", "xlsx", "md"})
    ),
    BackupSection(Tool.calendar, report_formats=frozenset({"ics", "json"})),
    BackupSection(Tool.post, in_reports=False),
    BackupSection(Tool.wiki, in_reports=False, fetch=_fetch_wiki_pages),
    # A dashboard is a live canvas, not a document, so a report carries its
    # envelope too.
    BackupSection(Tool.dashboard, finish=_ScopeBuilder._record_foreign_dashboards),
)
_SECTIONS_BY_KEY: dict[str, BackupSection] = {s.key: s for s in _SECTIONS}

if len(_SECTIONS_BY_KEY) != len(_SECTIONS) or set(_SECTIONS_BY_KEY) != set(_TOOLS):
    raise RuntimeError(
        "every exportable tool needs exactly one backup section: "
        f"{sorted(set(_TOOLS) ^ set(_SECTIONS_BY_KEY))}"
    )


# ---------------------------------------------------------------------------
# Estimate (the wizard's pre-flight numbers)
# ---------------------------------------------------------------------------


async def estimate_backup(
    session: AsyncSession,
    user: User,
    guild_id: int,
    *,
    scope: str,
    initiative_id: int | None,
    include_uploads: bool,
    filters: dict | None = None,
):
    from sqlalchemy import func
    from sqlmodel import select

    from app.models.tenant.file import File
    from app.schemas.tenant.backup_export import BackupEstimate, BackupToolEstimate
    from app.services.tenant.attachments import get_guild_storage_usage

    params = {
        "initiative_id": initiative_id,
        "include_uploads": include_uploads,
        "filters": filters,
    }
    _validate_params(params, scope_kind=scope)
    initiatives = await _resolve_scope(
        session, user, guild_id, params, scope_kind=scope
    )
    ids = await _enumerate(session, user, params, initiatives)

    tools: dict[str, BackupToolEstimate] = {}
    estimated_rows = 0
    for tool in _TOOLS:
        count = sum(len(v) for v in ids[tool].values())
        disabled = all(not getattr(i, Tool(tool).view_permission) for i in initiatives)
        tools[tool] = BackupToolEstimate(count=count, disabled=disabled)
        estimated_rows += count

    estimated_rows += await _task_rows(session, user, params, ids["project"])

    uploads_count = 0
    uploads_bytes = 0
    if include_uploads:
        file_ids = [d for per in ids[Tool.file.value].values() for d in per]
        if file_ids:
            uploads_count = (
                await session.exec(
                    select(func.count())
                    .select_from(File)
                    .where(
                        File.id.in_(file_ids),
                        File.current_version_id.is_not(None),
                    )
                )
            ).one()
        if scope == "guild":
            # Exact total blob usage — an upper bound on what ships.
            uploads_bytes = await get_guild_storage_usage(guild_id)
        else:
            uploads_bytes = await _known_upload_bytes(session, ids[Tool.file.value])
        estimated_rows += uploads_bytes // _MIB

    return BackupEstimate(
        tools=tools,
        uploads_count=uploads_count,
        uploads_bytes=uploads_bytes,
        uploads_approximate=True,
        estimated_rows=estimated_rows,
        max_rows=export_limits.EXPORT_MAX_BACKUP_ROWS,
        max_upload_bytes=export_limits.EXPORT_MAX_BACKUP_UPLOAD_BYTES,
        max_download_bytes=settings.EXPORT_MAX_DOWNLOAD_BYTES,
        delivery_available=delivery.is_configured(),
    )
