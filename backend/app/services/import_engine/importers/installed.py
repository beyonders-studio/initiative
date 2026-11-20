"""Every tool plug-in's importer: an ``initiative-<kind>`` envelope, as
``export/adapters/installed.py`` writes it, restored from what the plug-in
declared.

One importer serves every installed tool, built from the community's tool set
(``importers.importers_for``): its row and each item under it, at every depth,
are written as the generic create writes them (``plugin_tool_rows``), held to
the declaration and inserted through the routed session. A field the
declaration no longer has is left out; a value it does not take refuses the
envelope.

What crosses as a name is placed as the built-in importers place it: a person
in a person field, a mention and a property value by the people step's answer
or an initiative member's handle, tags by name, properties by name and type,
links and references by the ref each row had where it was exported.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import ImportEngineMessages
from app.core.tool_set import ToolRecord, ToolSet
from app.db.session import require_guild_context
from app.db.tool_rows import Located, ToolRow, text_columns
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.schemas.tenant.import_envelopes import InstalledToolEnvelope, InstalledToolRow
from app.services.export.adapters.installed import envelope_type
from app.services.import_engine.common import (
    load_initiative_member_handles,
    unique_name_in_initiative,
)
from app.services.import_engine.context import ImportContext
from app.services.import_engine.contract import (
    EnvelopeImportResult,
    ImportEngineError,
)
from app.services.import_engine.importers._base import (
    NamesPeopleInPassing,
    PropertyRestore,
    TagRestore,
    grant_ownership,
    parse_envelope,
)
from app.services.import_engine.mentions import place_markdown_mentions
from app.services.import_engine.people import PeopleMap, initiative_member_id
from app.services.import_engine.references import (
    has_source_references,
    place_markdown_references,
)
from app.services.tenant import plugin_tool_rows as rows
from app.services.tenant.tags import tag_links


class InstalledToolImporter(NamesPeopleInPassing):
    """The importer of one installed tool's envelope."""

    def __init__(self, tool: ToolRecord, tools: ToolSet) -> None:
        self.tool = tool
        self.tools = tools
        self.envelope_type = envelope_type(tool)
        self.permission = tool.create_permission

    def _walk(
        self, located: Located, row: InstalledToolRow
    ) -> Iterator[tuple[Located, InstalledToolRow]]:
        """``row`` and every item under it the declaration has, each with
        where its kind keeps its rows."""
        yield located, row
        for child in rows.children(located, self.tools):
            for item in row.items.get(child.kind.partition(".")[0], []):
                yield from self._walk(child, item)

    def _rows(self, validated: BaseModel) -> Iterator[tuple[Located, Any]]:
        return self._walk(rows.located_kind(self.tools, self.tool.kind), validated)

    def validate(self, envelope: dict[str, Any]) -> BaseModel:
        return parse_envelope(InstalledToolEnvelope, envelope)

    def count(self, validated: BaseModel) -> int:
        return sum(1 for _ in self._rows(validated))

    def handles(self, validated: BaseModel) -> list[str]:
        """The handles in passing, and every person field's."""
        return [
            *super().handles(validated),
            *(
                value
                for located, row in self._rows(validated)
                for key, field in rows.declared_fields(located).items()
                if field["kind"] == "user_reference"
                and isinstance(value := row.fields.get(key), str)
            ),
        ]

    async def apply(
        self,
        session: AsyncSession,
        *,
        envelope: BaseModel,
        target_initiative: Initiative,
        importer: User,
        context: ImportContext | None = None,
    ) -> EnvelopeImportResult:
        env: InstalledToolEnvelope = envelope  # ty: ignore[invalid-assignment] — validate() returned this model
        guild_context = require_guild_context(session)
        members = await load_initiative_member_handles(
            session, initiative_id=target_initiative.id
        )
        people = context.people if context is not None else PeopleMap()
        tags = TagRestore(session)
        props = PropertyRestore(
            session,
            initiative_id=target_initiative.id,
            context=context,
            member_handles=members,
        )
        unmatched: set[str] = set()
        made: dict[str, int] = {}

        def given(located: Located, row: InstalledToolRow) -> dict[str, Any]:
            """``row``'s fields as its table takes them: a person by who the
            handle is here, text with its mentions and references placed."""
            values: dict[str, Any] = {}
            for key, field in rows.declared_fields(located).items():
                if key not in row.fields:
                    continue
                value = row.fields[key]
                if field["kind"] == "user_reference" and isinstance(value, str):
                    handle, value = (
                        value,
                        initiative_member_id(
                            value, people=people, member_handles=members
                        ),
                    )
                    if value is None:
                        unmatched.add(handle)
                elif field["kind"] == "text" and isinstance(value, str):
                    value = place_markdown_mentions(
                        value,
                        row.mention_handles,
                        context=context,
                        initiative_member_handles=members,
                    )
                    # With no job to come back to, a reference is settled
                    # now; a job places it once every entry is written.
                    if context is None:
                        value = place_markdown_references(value, lambda _ref: None)
                values[key] = value
            return values

        async def write(
            located: Located,
            row: InstalledToolRow,
            placed: dict[str, int],
            name: str,
            tool: dict[str, int] | None = None,
        ) -> ToolRow:
            """Add ``row`` where ``placed`` says, called ``name``, and every
            item under it; ``tool`` is the tool's row it is in, none for the
            tool's own."""
            values = given(located, row)
            try:
                await rows.require_members(session, guild_context, located, values)
                columns = rows.column_values(located, values, current=None)
            except CodedError as exc:
                raise ImportEngineError(
                    ImportEngineMessages.IMPORT_INVALID_ENVELOPE
                ) from exc
            if row.position is not None:
                columns["position"] = Decimal(str(row.position))
            row_id = await rows.insert(
                session, located, {**columns, **placed, "name": name}
            )
            own = {"id": row_id, "initiative_id": target_initiative.id}
            if context is not None and any(
                has_source_references(values.get(column.name))
                for column in text_columns(located.table)
            ):
                context.links.note_references(located.kind, row_id)
            if tool is None:
                await grant_ownership(
                    session,
                    tool=located.tool,
                    entity_id=row_id,
                    target_initiative=target_initiative,
                    importer=importer,
                )
            written = ToolRow(located.table, own, tool=tool or own)
            noun = located.kind.partition(".")[0]
            made[noun] = made.get(noun, 0) + 1
            await tags.attach(
                written, row.tags, spec=tag_links(self.tools)[located.kind]
            )
            await props.attach(written, row.properties)
            if context is not None:
                context.links.register(
                    row.external_ref,
                    located.kind,
                    row_id,
                    code=self.tools.endpoint_codes[located.kind],
                )
                for link in row.links:
                    context.links.link(
                        row.external_ref, link.type, link.target_external_ref
                    )
            for child in rows.children(located, self.tools):
                for item in row.items.get(child.kind.partition(".")[0], []):
                    await write(
                        child,
                        item,
                        {rows.parent_column(child) or "": row_id},
                        item.name,
                        tool or own,
                    )
            return written

        top = rows.located_kind(self.tools, self.tool.kind)
        name = await unique_name_in_initiative(
            session, top.table.c, target_initiative.id, env.name
        )
        tool_row = await write(top, env, {"initiative_id": target_initiative.id}, name)
        return EnvelopeImportResult(
            entity_id=tool_row.id,
            entity_title=name,
            created={
                **made,
                "tags": tags.created,
                "properties": props.created,
            },
            matched={"tags": tags.matched, "properties": props.matched},
            unmatched_handles=sorted(unmatched | set(await props.settle(tool_row))),
        )
