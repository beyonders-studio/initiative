"""Counter-group source adapter: importable backup envelope (json) and a
counter table (pdf/csv/xlsx/md).

The json envelope round-trips the group's full configuration — its tags by
name and every counter with its current value, bounds, step, initial value,
view mode, color, and position — so an import can rebuild the group exactly.

The report formats project the counters into the shared columns/rows payload:
name and the numeric fields, in the group's display order. Numeric cells stay
numbers (int when integral, float otherwise) so xlsx keeps them typed and the
json envelope stays plain-JSON serializable (the render path's ``json.dumps``
does not accept ``Decimal``).

Access rule for every format: READ on the group (exporting is a formatted
read), enforced by ``ToolExportAdapter.fetch`` at both count and build time,
under the caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.tools import Tool, tool_envelope_type
from app.models.platform.user import User
from app.models.tenant.counter import CounterGroup
from app.schemas.tenant.tag import annotated_tags
from app.services.export import values
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
)
from app.services.export.contract import RenderItem
from app.services.export.i18n import et, export_locale
from app.services.export.property_values import exported_properties


class CounterGroupAdapter(ToolExportAdapter):
    tool = Tool.counter_group
    formats = ("json", "pdf", "csv", "xlsx", "md")

    def rows(self, group: CounterGroup, /) -> int:
        return len(group.counters)

    def item(self, group: CounterGroup, ctx: BuildContext, /) -> RenderItem:
        return build_counter_group_item(group, ctx.format, ctx.user, ctx.now)


def build_counter_group_item(
    group: CounterGroup, format: str, user: User, now: datetime
) -> RenderItem:
    date = now.strftime("%Y-%m-%d")
    if format == "json":
        # The envelope is importable machine data — stays canonical, never
        # localized (translating field keys / enum values breaks import).
        return RenderItem(
            key=envelope_key(Tool.counter_group, group.name, date),
            data=_envelope(group),
        )
    return RenderItem(
        key=export_stem(group.name, date), data=_report_payload(group, user)
    )


def _envelope(group: CounterGroup) -> dict[str, Any]:
    return {
        "type": tool_envelope_type(Tool.counter_group),
        "schema_version": 1,
        "name": group.name,
        "description": group.description,
        "tags": sorted(tag.name for tag in annotated_tags(group)),
        "properties": exported_properties(group),
        "counters": [
            {
                "name": counter.name,
                "color": counter.color,
                "count": values.number(counter.count),
                "min": values.number(counter.min),
                "max": values.number(counter.max),
                "step": values.number(counter.step),
                "initial_count": values.number(counter.initial_count),
                "view_mode": counter.view_mode.value,
                "position": values.number(counter.position),
                "properties": exported_properties(counter),
                # What a reference to this counter — a chip reading its value
                # — points at across one import.
                "external_ref": f"counter:{counter.id}",
            }
            for counter in group.counters
        ],
    }


def _report_payload(group: CounterGroup, user: User) -> dict[str, Any]:
    counters = group.counters
    loc = export_locale(user)
    # A counter's name and its numbers, in the group's order.
    columns = [
        values.Column("title", values.label("name", loc), lambda c: c.name, "2fr"),
        *(
            values.Column(
                field,
                values.label(field, loc),
                lambda c, field=field: values.number(getattr(c, field)),
                "auto",
            )
            for field in ("count", "min", "max", "step")
        ),
    ]
    return {
        # The group name is user data — never translated.
        "title": group.name,
        "subtitle": et("summary.counters", loc, count=len(counters)),
        "footer": et("footer.counters", loc, name=group.name),
        "page_of": et("pageOf", loc),
        "description": group.description or "",
        "columns": values.head(columns),
        "empty_message": et("empty.generic", loc),
        "rows": [values.cells(columns, counter) for counter in counters],
    }
