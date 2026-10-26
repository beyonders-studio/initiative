"""Helpers shared by the source adapters, and the base every per-tool source
is built on.

A tool's export is the same shape every time: take the selection out of the
job params, fetch each entity under the caller's RLS session, count the rows
it is worth, and turn it into a render item named after the entity and the
date. ``ToolExportAdapter`` holds that shape and derives the registry key and
the envelope suffix from the tool's own ``Tool`` value, the way
``tool_envelope_type`` already does — so a per-tool module states only which
rows it loads and how one row serialises.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel
from sqlalchemy import ColumnElement
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages, InitiativeMessages
from app.core.relationships import Related
from app.core.tools import Tool, tool_envelope_type, tool_export_source
from app.db import session as db_session
from app.models.platform.user import User
from app.models.tenant._mixins import tool_models
from app.models.tenant.file import File, FileVersion
from app.models.tenant.catalog import CatalogItemVersion
from app.models.tenant.project import Project
from app.models.tenant.task import Task
from app.schemas.query import DateBucket
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.export.i18n import et, export_locale
from app.services.export.filters import narrow, parse_filters
from app.services.permissions import (
    DAC_RESOURCES,
    EXPORT_ACCESS,
    require_export_access,
)
from app.services.platform.csv_export import safe_filename_component
from app.services.tenant.initiatives import keeps_content_in
from app.services.tenant.tool_listing import initiative_switch_clause
from app.core.user_input_validators import resolve_zone

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.services.storage import StorageBackend

# Bound on a single selection: page-size multiples, not initiative dumps —
# each id costs a fetch+authorize round trip at count AND build time.
MAX_SELECTION = 100


def selection_ids(params: dict, *, single_key: str, multi_key: str) -> list[int]:
    """Normalize a selection selector to a validated id list. Accepts either
    the legacy single-id key or the multi-id key (job params round-trip
    through JSON — validate, don't trust). Order-preserving dedupe."""
    raw = params.get(multi_key)
    if raw is None and params.get(single_key) is not None:
        raw = [params[single_key]]
    if not isinstance(raw, list) or not raw or len(raw) > MAX_SELECTION:
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    try:
        ids = [int(value) for value in raw]
    except (TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    return list(dict.fromkeys(ids))


async def _export_grouping(
    session: AsyncSession, dataset_name: str, params: dict, ids: list[int]
) -> Any:
    """The grouping ``params`` names (``group_by``, a field of
    ``dataset_name``, a date's with its ``bucket``) of ``ids``, or ``None``
    for an ungrouped export."""
    from app.services.fields.grouping import GroupingError, group_rows

    field = params.get("group_by")
    if field is None:
        return None
    if not isinstance(field, str) or not isinstance(
        params.get("hidden_groups") or [], list
    ):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
    try:
        bucket = DateBucket(params["bucket"]) if params.get("bucket") else None
        return await group_rows(
            session, dataset_name, field, ids, bucket=bucket, tz=params.get("tz")
        )
    except (GroupingError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)


async def grouped_row_count(
    session: AsyncSession, dataset_name: str, params: dict, ids: list[int]
) -> int:
    """How many rows an export of ``ids`` renders: each once, or grouped, one
    under every group it is in that the list shows."""
    grouping = await _export_grouping(session, dataset_name, params, ids)
    if grouping is None:
        return len(ids)
    hidden = params.get("hidden_groups") or []
    return sum(
        1 for group, _ in grouping.ordered(ids, lambda i: i) if group.key not in hidden
    )


async def grouped_for_export(
    session: AsyncSession,
    dataset_name: str,
    params: dict,
    rows: list[Any],
    locale: str,
) -> tuple[str | None, list[tuple[str | None, Any]]]:
    """``rows`` as the list they came from groups them, when ``params`` names
    a grouping: what the group column is headed with, and each row under the
    heading of every group it is in, less the ``hidden_groups`` the list
    leaves out. Ungrouped, no heading and each row once."""
    from app.services.fields.grouping import NO_GROUP

    grouping = await _export_grouping(
        session, dataset_name, params, [row.id for row in rows]
    )
    if grouping is None:
        return None, [(None, row) for row in rows]
    field = params["group_by"]
    hidden = params.get("hidden_groups") or []
    bucket = DateBucket(params["bucket"]) if params.get("bucket") else None
    label = grouping.name or et(f"fields.{field}", locale)

    def heading(group: Any) -> str:
        if group.label is not None:
            return group.label
        if bucket is not None and group.key != NO_GROUP:
            start = date.fromisoformat(group.key)
            return et(
                f"groups.bucket.{bucket.value}",
                locale,
                date=group.key,
                year=start.year,
                month=f"{start.month:02d}",
                quarter=(start.month - 1) // 3 + 1,
            )
        if group.key == NO_GROUP:
            # A field with a name for its empty group of its own ("Untagged"),
            # and every other one's "No …".
            key = f"groups.empty.{field}"
            named = et(key, locale) if grouping.name is None else key
            return named if named != key else et("groups.none", locale, name=label)
        if grouping.name is not None:
            # A checkbox property, the one property whose values have no label.
            return et(f"groups.{group.key}", locale, name=label)
        return et(f"{field}.{group.key}", locale)

    return label, [
        (heading(group), row)
        for group, row in grouping.ordered(rows, lambda r: r.id)
        if group.key not in hidden
    ]


async def require_may_leave(
    session: AsyncSession, initiative_ids: Iterable[int]
) -> frozenset[int]:
    """``initiative_ids``, once none of them keeps its content in: a list
    export may span initiatives, and the file is refused if one does."""
    if await keeps_content_in(session, initiative_ids):
        raise ExportError(InitiativeMessages.CONTENT_KEPT_IN, status_code=403)
    return frozenset(initiative_ids)


async def related_reach(session: AsyncSession, related: Iterable[Related]) -> set[int]:
    """The initiatives of the files and tasks at the far end of these
    edges: a file's own, and a task's by its project."""
    entities = [r.entity for r in related if r.entity is not None]
    reach = {e.initiative_id for e in entities if isinstance(e, File)}
    project_ids = {e.project_id for e in entities if isinstance(e, Task)}
    if project_ids:
        reach |= set(
            await session.exec(
                select(Project.initiative_id).where(Project.id.in_(project_ids))
            )
        )
    return reach


async def get_for_export(
    session: AsyncSession,
    user: User,
    guild_id: int,
    tool: Tool,
    entity_id: int,
    load: Callable[[AsyncSession, int], Awaitable[Any]],
    /,
    *,
    access: str = EXPORT_ACCESS,
) -> Any:
    """Load one entity with ``load`` and authorize exporting it: the row must be
    there, its tool switched on in its initiative, and ``access`` held on it —
    the owner rung for an export of the entity itself, ``"read"`` from an
    initiative or community backup (``permissions.require_export_access``)."""
    from app.api.resource_access import require_tool_enabled
    from app.services import reachability

    row = await load(session, entity_id)
    if row is None:
        raise await reachability.missing_or_denied(
            tool,
            entity_id,
            user.id,
            guild_id,
        )
    if row.initiative is not None:
        require_tool_enabled(tool, row.initiative)
    require_export_access(
        DAC_RESOURCES[tool],
        row,
        context=db_session.guild_context(session),
        access=access,
    )
    return row


def export_stem(name: str, date: str) -> str:
    """The filename stem an export item is keyed by: the entity's own name,
    reduced to filename-safe characters, and the date the export was taken."""
    return f"{safe_filename_component(name).lower()}-{date}"


def envelope_key(tool: Tool, name: str, date: str) -> str:
    """The item key for a tool's importable envelope: the entity's stem plus
    the ``initiative-<tool>`` suffix the importer answers to."""
    return f"{export_stem(name, date)}.{tool_envelope_type(tool)}"


def storage_key_of(url: str | None) -> str:
    """The stored blob's key, as the manifest and the importer name it."""
    return (url or "").split("/")[-1]


def asset_item(
    storage: "StorageBackend",
    version: FileVersion | CatalogItemVersion | None,
) -> RenderItem | None:
    """A stored file's bytes, zipped under ``assets/`` by its storage key
    beside the envelope naming it — or ``None`` when the file is gone."""
    key = storage_key_of(version.file_url) if version is not None else ""
    if not key or not storage.exists(key):
        return None
    return RenderItem(
        key=key,
        data={"storage_key": key, "content_type": version.file_content_type},
        filename=f"assets/{key}",
        format="file",
    )


@dataclass(frozen=True)
class BuildContext:
    """What one batch of render items is built against: the requested format,
    the creator (locale and attribution), the guild, a single clock read, the
    tool's export filters, and whatever ``ToolExportAdapter.prepare`` loaded
    for the whole batch."""

    format: str
    user: User
    guild_id: int
    now: datetime
    filters: BaseModel | None = None
    prepared: Any = None

    @property
    def date(self) -> str:
        return self.now.strftime("%Y-%m-%d")


class ToolExportAdapter:
    """The per-tool export source: a selection of entities, each rendered as
    one item.

    A subclass names its ``Tool`` and fills in the tool-shaped hooks —
    :meth:`get_row` (how one row loads, when not the tool's registered
    loader), :meth:`in_initiative` (which of them one initiative's export
    holds, when not every row the initiative has), :meth:`rows` (how many
    rows one entity is worth) and :meth:`item` (how one entity serialises). Everything else — the registry key, the selection
    params, counting, and the ``RenderRequest`` — is the same for every tool
    and lives here.
    """

    tool: Tool
    source: str
    # Required by the SourceAdapter protocol; a json envelope renders no
    # template. A tool with report formats names its own.
    template_id: str = "data-table"
    #: The formats this tool exports in, in the order its route publishes
    #: them.
    formats: tuple[str, ...] = ("json",)
    #: What a marketplace listing of this tool shows beside what it installs.
    #: A tool made of content previews with an example the publisher filled in;
    #: a tool made of queries over the community's data previews with sample
    #: data generated from the queries' shapes, because its results are the
    #: publisher's community, not something they made for the listing.
    example_is_generated: bool = False
    #: Filters on what one entity holds rather than on which entities, by the
    #: key they take in the tool's export filters (``app.services.export.filters``).
    content_filters: ClassVar[dict[str, type[BaseModel]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.source = tool_export_source(cls.tool)

    # -- what a tool states --------------------------------------------------

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        entity_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> Any:
        """Load and authorize one selected entity under the caller's RLS
        session (:func:`get_for_export`). A tool whose export carries more
        than the row extends this."""
        return await get_for_export(
            session, user, guild_id, self.tool, entity_id, self.get_row, access=access
        )

    async def get_row(self, session: AsyncSession, entity_id: int, /) -> Any:
        """One row by id, or ``None``: the tool's registered loader, the wider
        one where it has two."""
        from app.api.resource_access import RESOURCE_ACCESS

        config = RESOURCE_ACCESS[self.tool]
        return await (config.hydrated_loader or config.loader)(session, entity_id)

    def in_initiative(self, initiative_id: int, /) -> list[ColumnElement[bool]]:
        """The WHERE legs naming this tool's rows that an initiative or
        community export of one initiative may include: that initiative's,
        where it has the tool switched on."""
        model = tool_models()[self.tool.plural]
        return [
            model.initiative_id == initiative_id,
            initiative_switch_clause(self.tool, model),
        ]

    async def initiative_ids(
        self, session: AsyncSession, initiative_id: int, /
    ) -> list[int]:
        """The ids of this tool's entities in one initiative that an initiative
        or community export may include, in id order."""
        model = tool_models()[self.tool.plural]
        return list(
            await session.exec(
                select(model.id)
                .where(*self.in_initiative(initiative_id))
                .order_by(model.id.asc())
            )
        )

    def title(self, entity: Any, /) -> str:
        """The entity's own name — what its archive entry is titled and its
        file is named after."""
        return entity.name

    def rows(self, entity: Any, /) -> int:
        """How many rows one entity is worth, for the inline-vs-job decision
        and the size bound. One per entity unless its contents are the size."""
        return 1

    def item(self, entity: Any, ctx: BuildContext, /) -> RenderItem:
        """Serialise one entity into its render item."""
        raise NotImplementedError

    def items(self, entity: Any, ctx: BuildContext, /) -> tuple[RenderItem, ...]:
        """Every file one entity becomes. One, unless its contents travel
        beside it — a catalog's pictures ride next to its envelope."""
        return (self.item(entity, ctx),)

    async def reach(
        self, session: AsyncSession, params: dict, entities: list[Any], /
    ) -> set[int]:
        """The initiatives whose content these entities hold. A guild-level
        entity holds none."""
        return {entity.initiative_id for entity in entities} - {None}

    async def prepared_reach(
        self, session: AsyncSession, ctx: BuildContext, /
    ) -> set[int]:
        """The initiatives of what :meth:`prepare` loaded beside the entities,
        when the items ``ctx.format`` writes name it."""
        return set()

    async def prepare(
        self, session: AsyncSession, entities: list[Any], ctx: BuildContext, /
    ) -> Any:
        """Anything the item builders need across the whole batch, loaded in
        one pass (they are synchronous and hold no session)."""
        return None

    @property
    def prepares(self) -> bool:
        """Whether :meth:`prepare` loads anything — whether a caller building
        many entities gains by loading them all before building any."""
        return type(self).prepare is not ToolExportAdapter.prepare

    # -- the shape every tool shares -----------------------------------------

    def selection(self, params: dict) -> list[int]:
        """The ids this request selected, read from the tool's own selector
        keys (``{tool}_ids``, or the single ``{tool}_id``)."""
        return selection_ids(
            params,
            single_key=f"{self.tool.value}_id",
            multi_key=f"{self.tool.value}_ids",
        )

    async def load(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> list[Any]:
        """Every selected entity, fetched and authorized one by one, then
        narrowed to those the tool's filters leave. A selection is refused
        whole if any of it is, filtered out or not."""
        ids = self.selection(params)
        entities = [
            await self.fetch(session, user, guild_id, entity_id) for entity_id in ids
        ]
        kept = set(
            await narrow(
                session,
                user,
                self.tool,
                parse_filters(self.tool, params.get("filters")),
                ids,
            )
        )
        return [entity for entity_id, entity in zip(ids, entities) if entity_id in kept]

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        entities = await self.load(session, user, guild_id, params, format)
        return sum(self.rows(entity) for entity in entities)

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        entities = await self.load(session, user, guild_id, params, format)
        ctx = BuildContext(
            format=format,
            user=user,
            guild_id=guild_id,
            # One clock read: the filename date and the subtitle timestamp
            # must not straddle midnight into disagreeing dates.
            now=datetime.now(resolve_zone(params.get("tz"))),
            filters=parse_filters(self.tool, params.get("filters")),
        )
        ctx = replace(ctx, prepared=await self.prepare(session, entities, ctx))
        batch = tuple(item for entity in entities for item in self.items(entity, ctx))
        if format == "json":
            # An envelope names people by handle, never by id — including the
            # people its body mentions, which the item builders cannot look
            # up because they hold no session.
            # Nor does it name other things by id: each reference carries the
            # ref it had, for the import to point at whatever that became.
            from app.services.import_engine.mentions import detach_envelope_mentions
            from app.services.import_engine.references import (
                detach_envelope_references,
            )

            for item in batch:
                await detach_envelope_mentions(session, item.data)
                detach_envelope_references(item.data, guild_id=guild_id)
        else:
            # A report is read away from the app, so each mention is written
            # with the name it reads as now.
            from app.services.import_engine.mentions import mention_namer

            named = await mention_namer(
                session,
                [item.data for item in batch],
                missing=et("fallback.formerMember", export_locale(user)),
            )
            for item in batch:
                item.data.update(named(item.data))
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=batch,
            initiative_ids=frozenset(
                await self.reach(session, params, entities)
                | await self.prepared_reach(session, ctx)
            ),
        )
