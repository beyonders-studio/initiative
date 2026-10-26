"""Per-type importer registry: envelope ``type`` → importer instance.

The single dispatch point for both the envelope endpoint and (later) the
backup orchestrator — an unknown discriminator is rejected centrally by
``engine.get_importer``.
"""

from app.services.import_engine.importers.calendar import CalendarImporter
from app.services.import_engine.importers.counter_group import CounterGroupImporter
from app.services.import_engine.importers.dashboard import DashboardImporter
from app.services.import_engine.importers.file import FileImporter
from app.services.import_engine.importers.catalog import CatalogImporter
from app.services.import_engine.importers.post import PostImporter
from app.services.import_engine.importers.project import ProjectImporter
from app.services.import_engine.importers.queue import QueueImporter
from app.services.import_engine.importers.wiki import WikiImporter

IMPORTERS = {
    importer.envelope_type: importer
    for importer in (
        ProjectImporter(),
        FileImporter(),
        QueueImporter(),
        CounterGroupImporter(),
        DashboardImporter(),
        CalendarImporter(),
        PostImporter(),
        WikiImporter(),
        CatalogImporter(),
    )
}

# Fail at import time, not request time: every importer's create permission
# must map back to a Tool (the engine reads the tool's master switch through
# that mapping — a permission that gates no tool would otherwise be treated
# as always-enabled).
from app.core.tools import tool_for_create_permission as _tool_lookup  # noqa: E402

for _importer in IMPORTERS.values():
    _tool_lookup(_importer.permission.value)

__all__ = ["IMPORTERS"]
