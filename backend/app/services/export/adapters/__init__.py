"""Source-adapter registry: which sources exist and which formats each
supports. Unsupported source×format combos are rejected centrally by
``engine.get_adapter``.

A source per tool whose record exports (``BULK_EXPORT_TOOLS``), served by the
adapter the module named after the tool declares, then the sources that are
not one tool: the task and event lists, and the initiative and community
exports."""

from importlib import import_module

from app.core.tools import BULK_EXPORT_TOOLS, Tool, tool_export_source
from app.services.export.adapters._common import ToolExportAdapter
from app.services.export.adapters.backup import (
    GuildExportAdapter,
    InitiativeExportAdapter,
)
from app.services.export.adapters.calendar_events import CalendarEventsAdapter
from app.services.export.adapters.tasks_table import TasksTableAdapter


def _tool_adapter(tool: Tool) -> ToolExportAdapter:
    """The adapter ``adapters/<tool>.py`` declares for ``tool``."""
    module = import_module(f"{__name__}.{tool.value}")
    (adapter,) = (
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, ToolExportAdapter)
        and value.__dict__.get("tool") is tool
    )
    return adapter()


ADAPTERS = {
    **{tool_export_source(tool): _tool_adapter(tool) for tool in BULK_EXPORT_TOOLS},
    **{
        adapter.source: adapter
        for adapter in (
            TasksTableAdapter(),
            CalendarEventsAdapter(),
            InitiativeExportAdapter(),
            GuildExportAdapter(),
        )
    },
}

__all__ = ["ADAPTERS"]
