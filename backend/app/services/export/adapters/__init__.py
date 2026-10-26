"""Source-adapter registry: which sources exist and which formats each
supports. Unsupported source×format combos are rejected centrally by
``engine.get_adapter``."""

from app.services.export.adapters.backup import (
    GuildExportAdapter,
    InitiativeExportAdapter,
)
from app.services.export.adapters.calendar import CalendarAdapter
from app.services.export.adapters.calendar_events import CalendarEventsAdapter
from app.services.export.adapters.counter_group import CounterGroupAdapter
from app.services.export.adapters.dashboard import DashboardAdapter
from app.services.export.adapters.file import FileAdapter
from app.services.export.adapters.catalog import CatalogAdapter
from app.services.export.adapters.post import PostAdapter
from app.services.export.adapters.project import ProjectAdapter
from app.services.export.adapters.queue import QueueAdapter
from app.services.export.adapters.tasks_table import TasksTableAdapter
from app.services.export.adapters.wiki import WikiAdapter

ADAPTERS = {
    adapter.source: adapter
    for adapter in (
        TasksTableAdapter(),
        CalendarEventsAdapter(),
        ProjectAdapter(),
        FileAdapter(),
        QueueAdapter(),
        CounterGroupAdapter(),
        DashboardAdapter(),
        CalendarAdapter(),
        PostAdapter(),
        WikiAdapter(),
        CatalogAdapter(),
        InitiativeExportAdapter(),
        GuildExportAdapter(),
    )
}

__all__ = ["ADAPTERS"]
