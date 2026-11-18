"""Counter-group source adapter: a counter table (pdf/csv/xlsx/md) beside the
envelope (json) every tool writes.

The envelope is the group and its counters, each with its current value,
bounds, step, initial value, view mode, color, and position, so an import can
rebuild the group exactly.

The report formats project the counters into the shared columns/rows payload:
name and the numeric fields, in the group's display order. Numeric cells stay
numbers (int when integral, float otherwise) so xlsx keeps them typed.

Access rule for every format: READ on the group (exporting is a formatted
read), enforced by ``ToolExportAdapter.fetch`` at both count and build time,
under the caller's RLS session.
"""

from __future__ import annotations

from typing import Any

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.counter import CounterGroup
from app.services.export import values
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    export_stem,
)
from app.services.export.contract import RenderItem
from app.services.export.i18n import et, export_locale


class CounterGroupAdapter(ToolExportAdapter):
    tool = Tool.counter_group

    def rows(self, group: CounterGroup, /) -> int:
        return len(group.counters)

    def item(self, group: CounterGroup, ctx: BuildContext, /) -> RenderItem:
        if ctx.format == "json":
            return super().item(group, ctx)
        return RenderItem(
            key=export_stem(group.name, ctx.date),
            data=_report_payload(group, ctx.user),
        )


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
