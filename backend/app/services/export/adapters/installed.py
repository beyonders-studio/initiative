"""Every tool plug-in's source: its tool's rows and their items, written from
what the plug-in declared.

A tool plug-in's tables are built from its declaration (``app.db.plugin_tools``):
each keeps the declaration in ``table.info[DECLARED]`` and each declared
field's column its kind in ``info["field"]``. So one adapter exports any of
them, its source the tool's kind, in the formats its record offers
(``ToolSpec.export_formats``):

* ``json`` is the row as its envelope: its name, place and declared
  ``fields``, the tags, property values and links it carries, under
  ``items``, by each item table's key, the items in it, each written the same
  way, and under ``layouts``, by the same key, the layouts each item table
  keeps under it where they were changed. A person is named by handle and anything else by its ref
  (``<kind>:<id>``), never by id, so ``importers/installed.py`` restores it
  in any initiative.
* ``csv`` and ``xlsx``, for a tool with one item table, are a table of one
  row's items: their name and declared fields, each cell written as its kind
  reads.

Every row is loaded and refused as the universal routes load it
(``resource_access.load_kind``), and exported on the export action, or read
from an initiative or community backup.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, ValidationError, create_model
from sqlalchemy import Table
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages, KindMessages
from app.core.relationships import node_of
from app.core.tool_set import ToolRecord
from app.core.tools import kind_refusal
from app.core.user_display import display_name, handle_of
from app.core.user_input_validators import resolve_zone
from app.db.plugin_tools import DECLARED, TABULAR_FORMATS
from app.db.session import require_guild_context, routed_tools
from app.db.tool_rows import ToolRow
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.models.tenant.initiative import Initiative
from app.models.tenant.relationship import EntityRelationship
from app.models.tenant.tool_layout import ToolLayout
from app.schemas.tenant.import_envelopes import CURRENT_SCHEMA_VERSION
from app.services.export import values
from app.services.export.adapters._common import (
    BuildContext,
    export_stem,
    selection_ids,
)
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.export.i18n import export_locale
from app.services.export.property_values import exported_properties
from app.services.import_engine.mentions import (
    detach_markdown_mentions,
    load_mention_handles,
    markdown_mention_ids,
)
from app.services.import_engine.references import (
    detach_envelope_references,
    detach_markdown_references,
)
from app.services.marketplace.widget_meta import in_language
from app.services.permissions import (
    EXPORT_ACCESS,
    DacResource,
    require_export_access,
)
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant.archive import archive_filter_clause
from app.services.tenant.initiative_tools import tool_on_sql
from app.services.tenant.project_export import EXPORTED_LINK_TYPES
from app.services.tenant.tool_listing import initiative_switch_clause

#: What every installed tool's export may be narrowed by: whether it is
#: archived, as every tool's list is. Unset, it carries both.
InstalledFilters = create_model(
    "installed_tool_export_filters",
    __config__=ConfigDict(extra="forbid"),
    archived=(bool | None, None),
)


@dataclass(frozen=True)
class Prepared:
    """What a batch of one installed tool's rows is written from: the tool,
    each row's live items by item table (and theirs under them), the people
    they name and the handles of those their text mentions, by id, and what
    each row and item carries beside its fields, by kind and id
    (:func:`_carried`)."""

    tool: ToolRecord
    items: Mapping[int, Mapping[str, list[Mapping[str, Any]]]]
    people: Mapping[int, Any]
    handles: Mapping[int, str]
    carried: Mapping[tuple[str, int], Mapping[str, Any]]
    #: The layouts each item table keeps under a row, by the table's kind
    #: and the row's id.
    layouts: Mapping[tuple[str, int], list[dict[str, Any]]]


def envelope_type(tool: ToolRecord) -> str:
    """The ``type`` an installed tool's envelope carries, as a built-in
    tool's is ``initiative-<tool>``."""
    return f"initiative-{tool.kind}"


def table_kinds(tool: ToolRecord) -> dict[str, str]:
    """The kind of each of ``tool``'s tables, by table name: the tool's own
    and each item's."""
    return {tool.table.name: tool.kind} | {
        child.table: child.value for child in tool.children
    }


def _fields(table: Table) -> list[Any]:
    """The declared fields' columns of ``table``, in the declared order."""
    return [column for column in table.columns if "field" in column.info]


def _declared(table: Table, key: str) -> Mapping[str, Any]:
    return next(
        (f for f in table.info[DECLARED].get("fields", []) if f.get("key") == key), {}
    )


def _under(tool: ToolRecord, table: Table) -> list[tuple[Table, str]]:
    """The item tables directly under ``table``, each with its column naming
    the row above."""
    return [
        (item, fk.parent.name)
        for item in tool.items
        for fk in item.foreign_keys
        if fk.column.table is table
    ]


def _option_label(field: Mapping[str, Any], value: Any, locale: str) -> str:
    for option in field.get("options", []):
        if option.get("value") == value:
            return in_language(option.get("label"), locale) or str(value)
    return str(value)


async def _carried(
    session: AsyncSession, ids: Mapping[str, list[int]]
) -> dict[tuple[str, int], dict[str, Any]]:
    """What each row of each kind in ``ids`` carries beside its fields: its
    tags by name, its property values (``exported_properties``), and the
    links it makes, each far end by its ref, as a task's are
    (``project_export.EXPORTED_LINK_TYPES``)."""
    tools = routed_tools(session)
    taggable = tags_service.tag_links(tools)
    carried: dict[tuple[str, int], dict[str, Any]] = {}
    nodes: dict[int, tuple[str, int]] = {}
    for kind, entity_ids in ids.items():
        tags = await tags_service.tags_for(session, taggable[kind], entity_ids)
        summaries = await metadata_service.summaries_by_id(session, kind, entity_ids)
        for entity_id in entity_ids:
            carried[(kind, entity_id)] = {
                "tags": sorted(tag.name for tag in tags.get(entity_id, [])),
                "properties": exported_properties(
                    SimpleNamespace(properties=summaries.get(entity_id, []))
                ),
                "links": [],
            }
            nodes[node_of(tools.kind_codes[kind], entity_id)] = (kind, entity_id)
    if nodes:
        edges = await session.exec(
            select(EntityRelationship)
            .where(
                EntityRelationship.source_node.in_(list(nodes)),
                EntityRelationship.relationship_type.in_(
                    [link.value for link in EXPORTED_LINK_TYPES]
                ),
                EntityRelationship.removed_at.is_(None),
            )
            .order_by(EntityRelationship.id)
        )
        for edge in edges:
            carried[nodes[edge.source_node]]["links"].append(
                {
                    "type": edge.relationship_type,
                    "target_external_ref": f"{edge.target_type}:{edge.target_id}",
                }
            )
    return carried


class InstalledToolAdapter:
    """The export source of one installed tool, named by its kind."""

    template_id = "data-table"
    #: The most any installed tool exports; which of them one does is its
    #: record's, asked once the community's tools are known.
    formats = ("json", *TABULAR_FORMATS)
    prepares = True

    def __init__(self, kind: str) -> None:
        self.source = kind

    # -- the tool --------------------------------------------------------------

    def tool(self, session: AsyncSession) -> ToolRecord:
        """The community's installed tool of this kind, or not found."""
        found = routed_tools(session).by_kind.get(self.source)
        if found is None or not found.installed:
            raise kind_refusal(self.source, KindMessages.NOT_FOUND, 404)
        return found

    # -- the rows --------------------------------------------------------------

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        entity_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> ToolRow:
        """One of the tool's live rows, loaded as the universal routes load
        it, on its tool's switch, and held to ``access``."""
        from app.api.resource_access import load_kind

        tool = self.tool(session)
        context = require_guild_context(session)
        row = await load_kind(session, self.source, entity_id, user, context)
        if row.deleted_at is not None:
            raise tool.not_found()
        switched_on = await session.scalar(
            select(Initiative.id).where(
                Initiative.id == row.initiative_id, tool_on_sql(tool)
            )
        )
        if switched_on is None:
            raise tool.disabled()
        require_export_access(DacResource(tool), row, context=context, access=access)
        return row

    async def initiative_ids(
        self, session: AsyncSession, initiative_id: int, /
    ) -> list[int]:
        """The tool's live rows in one initiative, where it has the tool
        switched on, in id order."""
        tool = self.tool(session)
        table = tool.table
        return list(
            await session.exec(
                select(table.c.id)
                .where(
                    table.c.initiative_id == initiative_id,
                    table.c.deleted_at.is_(None),
                    initiative_switch_clause(tool, table.c),
                )
                .order_by(table.c.id.asc())
            )
        )

    def filters_of(self, raw: Any) -> BaseModel | None:
        """The tool's export filters from a job's params, or ``None``."""
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
        try:
            return InstalledFilters.model_validate(raw)
        except ValidationError:
            raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)

    async def narrow(
        self,
        session: AsyncSession,
        user: User,
        filters: BaseModel | None,
        ids: list[int],
    ) -> list[int]:
        """The ids, in their order, that ``filters`` leave."""
        archived = getattr(filters, "archived", None)
        if archived is None or not ids:
            return ids
        table = self.tool(session).table
        kept = set(
            await session.exec(
                select(table.c.id).where(
                    table.c.id.in_(ids), archive_filter_clause(table.c, archived)
                )
            )
        )
        return [entity_id for entity_id in ids if entity_id in kept]

    def title(self, row: ToolRow, /) -> str:
        return row.name

    async def _items(
        self, session: AsyncSession, tool: ToolRecord, rows: list[ToolRow]
    ) -> dict[int, dict[str, list[Mapping[str, Any]]]]:
        """Each row's live items by item table, each table's in its order:
        one read per item table for the whole batch."""
        held: dict[int, dict[str, list[Mapping[str, Any]]]] = {
            row.id: {} for row in rows
        }
        # Which of ``rows`` each row read so far sits under.
        owner = {(tool.table.name, row.id): row.id for row in rows}

        async def walk(table: Table, ids: list[int]) -> None:
            for item, column in _under(tool, table):
                live = [item.c[column].in_(ids)]
                if "deleted_at" in item.c:
                    live.append(item.c.deleted_at.is_(None))
                loaded = [
                    found._mapping
                    for found in await session.exec(
                        sa.select(item)
                        .where(*live)
                        .order_by(item.c.position.asc(), item.c.id.asc())
                    )
                ]
                for found in loaded:
                    top = owner[(table.name, found[column])]
                    owner[(item.name, found["id"])] = top
                    held[top].setdefault(item.name, []).append(found)
                if loaded:
                    await walk(item, [found["id"] for found in loaded])

        if rows:
            await walk(tool.table, list(held))
        return held

    async def prepare(
        self, session: AsyncSession, rows: list[ToolRow], ctx: BuildContext, /
    ) -> Prepared:
        """The rows' items, the people they and their items name, and what
        each carries beside its fields."""
        tool = self.tool(session)
        items = await self._items(session, tool, rows)
        by_name = {item.name: item for item in tool.items}
        cells = [(tool.table, row.values) for row in rows] + [
            (by_name[name], found)
            for held in items.values()
            for name, found_rows in held.items()
            for found in found_rows
        ]
        people = {
            value
            for table, row in cells
            for column in _fields(table)
            if column.info["field"] == "user_reference"
            and (value := row[column.name]) is not None
        }
        profiles = (
            await session.exec(
                select(MemberProfile).where(MemberProfile.id.in_(people))
            )
            if people
            else ()
        )
        mentioned = {
            user_id
            for table, row in cells
            for column in _fields(table)
            if column.info["field"] == "text"
            for user_id in markdown_mention_ids(row[column.name])
        }
        kinds = table_kinds(tool)
        ids: dict[str, list[int]] = {}
        for table, row in cells:
            ids.setdefault(kinds[table.name], []).append(row["id"])
        layouts: dict[tuple[str, int], list[dict[str, Any]]] = {}
        if tool.children:
            for layout in await session.exec(
                select(ToolLayout)
                .where(
                    col(ToolLayout.tool).in_([child.value for child in tool.children]),
                    col(ToolLayout.tool_id).in_([row["id"] for _, row in cells]),
                )
                .order_by(col(ToolLayout.id))
            ):
                assert layout.tool_id is not None
                layouts.setdefault((layout.tool, layout.tool_id), []).append(
                    {"kind": layout.kind, "definition": layout.definition}
                )
        return Prepared(
            tool,
            items,
            {profile.id: profile for profile in profiles},
            await load_mention_handles(session, mentioned),
            await _carried(session, ids),
            layouts,
        )

    async def prepared_reach(
        self, session: AsyncSession, ctx: BuildContext, /
    ) -> set[int]:
        return set()

    # -- writing ---------------------------------------------------------------

    def _json(
        self,
        table: Table,
        row: Mapping[str, Any],
        items: Mapping[str, list[Mapping[str, Any]]],
        prepared: Prepared,
    ) -> dict[str, Any]:
        """A row, or an item, and the items under it, as the envelope holds
        them."""
        kinds = table_kinds(prepared.tool)
        kind = kinds[table.name]
        under = _under(prepared.tool, table)
        laid = {
            item.info[DECLARED]["key"]: found
            for item, _column in under
            if (found := prepared.layouts.get((kinds[item.name], row["id"])))
        }
        fields: dict[str, Any] = {}
        mentioned: list[str] = []
        for column in _fields(table):
            value = row[column.name]
            field_kind = column.info["field"]
            if value is None:
                pass
            elif field_kind == "user_reference":
                profile = prepared.people.get(value)
                value = handle_of(profile) if profile is not None else None
            elif field_kind == "text":
                value, named = detach_markdown_mentions(value, prepared.handles)
                value = detach_markdown_references(value)
                mentioned += [handle for handle in named if handle not in mentioned]
            elif isinstance(value, (datetime, date)):
                value = value.isoformat()
            elif field_kind in ("number", "counter", "currency"):
                value = values.number(value)
            elif isinstance(value, list):
                value = list(value)
            fields[column.name] = value
        return {
            "name": row["name"],
            "position": values.number(row["position"]),
            "external_ref": f"{kind}:{row['id']}",
            "fields": fields,
            "mention_handles": mentioned,
            **prepared.carried[(kind, row["id"])],
            "items": {
                item.info[DECLARED]["key"]: [
                    self._json(item, child, items, prepared)
                    for child in items.get(item.name, [])
                    if child[column] == row["id"]
                ]
                for item, column in under
            },
            **({"layouts": laid} if laid else {}),
        }

    def _cell(
        self, table: Table, column: Any, value: Any, prepared: Prepared, ctx: Any
    ) -> Any:
        """One declared field's value as a table cell, by its kind."""
        kind = column.info["field"]
        locale = export_locale(ctx.user)
        if value is None:
            return None
        if kind in ("number", "counter", "currency", "scale"):
            return values.number(value)
        if kind == "checkbox":
            return values.yes_no(value, locale)
        if kind == "date":
            return values.date(value)
        if kind == "datetime":
            return values.moment(value, getattr(ctx.now.tzinfo, "key", None))
        if kind == "user_reference":
            return display_name(prepared.people.get(value)) or None
        field = _declared(table, column.name)
        if kind == "select":
            return _option_label(field, value, locale)
        if kind == "multi_select":
            return ", ".join(_option_label(field, each, locale) for each in value)
        return values.text(value)

    def item(self, row: ToolRow, ctx: BuildContext, /) -> RenderItem:
        prepared: Prepared = ctx.prepared
        tool = prepared.tool
        items = prepared.items.get(row.id, {})
        if ctx.format == "json":
            data = {
                "type": envelope_type(tool),
                "schema_version": CURRENT_SCHEMA_VERSION,
                **self._json(tool.table, row.values, items, prepared),
            }
            detach_envelope_references(data, guild_id=ctx.guild_id)
            return RenderItem(
                key=f"{export_stem(row.name, ctx.date)}.{envelope_type(tool)}",
                data=data,
            )
        # A table of the row's items, the one item table a tabular tool has.
        (table,) = tool.items
        locale = export_locale(ctx.user)
        columns = [
            # Headed by what the item is called, as each field is by its name.
            values.Column(
                "title",
                in_language(table.info[DECLARED].get("name"), locale) or "name",
                lambda r: r["name"],
            ),
            *(
                values.Column(
                    column.name,
                    in_language(_declared(table, column.name).get("name"), locale)
                    or column.name,
                    lambda r, column=column: self._cell(
                        table, column, r[column.name], prepared, ctx
                    ),
                    "auto",
                )
                for column in _fields(table)
            ),
        ]
        return RenderItem(
            key=export_stem(row.name, ctx.date),
            data={
                # The row's name is user data, never translated.
                "title": row.name,
                "columns": values.head(columns),
                "rows": [values.cells(columns, r) for r in items.get(table.name, [])],
            },
        )

    def batch(
        self, rows: list[ToolRow], ctx: BuildContext, /
    ) -> tuple[RenderItem, ...]:
        return tuple(self.item(row, ctx) for row in rows)

    # -- the source ------------------------------------------------------------

    async def load(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> list[ToolRow]:
        """Every selected row, fetched and authorized one by one, then
        narrowed to those the filters leave. A selection is refused whole if
        any of it is."""
        if format not in (self.tool(session).spec.export_formats or ()):
            raise ExportError(ExportMessages.EXPORT_INVALID_FORMAT)
        ids = selection_ids(
            params, single_key=f"{self.source}_id", multi_key=f"{self.source}_ids"
        )
        rows = [
            await self.fetch(session, user, guild_id, entity_id) for entity_id in ids
        ]
        kept = set(
            await self.narrow(
                session, user, self.filters_of(params.get("filters")), ids
            )
        )
        return [row for row in rows if row.id in kept]

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        """One for each row, and one for each item under it."""
        rows = await self.load(session, user, guild_id, params, format)
        items = await self._items(session, self.tool(session), rows)
        return len(rows) + sum(
            len(found) for held in items.values() for found in held.values()
        )

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        rows = await self.load(session, user, guild_id, params, format)
        ctx = BuildContext(
            format=format,
            user=user,
            guild_id=guild_id,
            now=datetime.now(resolve_zone(params.get("tz"))),
        )
        ctx = replace(ctx, prepared=await self.prepare(session, rows, ctx))
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=self.batch(rows, ctx),
            initiative_ids=frozenset(row.initiative_id for row in rows),
        )
