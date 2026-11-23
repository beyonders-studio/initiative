"""Per-type importer registry: envelope ``type`` → importer instance.

The single dispatch point for both the envelope endpoint and the backup
orchestrator — an unknown discriminator is rejected centrally by
``engine.get_importer``. Every tool whose record exports
(``BULK_EXPORT_TOOLS``) imports too, through the importer the module named
after the tool declares; and every tool plug-in a community has installed,
through the one importer its declaration drives (:func:`importers_for`).
"""

from importlib import import_module

from app.core.tool_set import ToolSet
from app.core.tools import BULK_EXPORT_TOOLS, Tool, tool_envelope_type
from app.services.import_engine.contract import EnvelopeImporter


def _tool_importer(tool: Tool) -> EnvelopeImporter:
    """The importer ``importers/<tool>.py`` declares for ``tool``'s envelope."""
    module = import_module(f"{__name__}.{tool.value}")
    (importer,) = (
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and value.__dict__.get("envelope_type") == tool_envelope_type(tool)
    )
    return importer()


IMPORTERS: dict[str, EnvelopeImporter] = {
    tool_envelope_type(tool): _tool_importer(tool) for tool in BULK_EXPORT_TOOLS
}

# Fail at import time, not request time: every importer's create permission
# must map back to a Tool (the engine reads the tool's master switch through
# that mapping — a permission that gates no tool would otherwise be treated
# as always-enabled).
from app.core.tools import tool_for_create_permission as _tool_lookup

for _importer in IMPORTERS.values():
    _tool_lookup(_importer.permission)


def importers_for(tools: ToolSet) -> dict[str, EnvelopeImporter]:
    """Every envelope type a community with ``tools`` imports: the built-in
    tools', and each installed tool plug-in's."""
    from app.services.import_engine.importers.installed import (
        InstalledToolImporter,
    )

    installed = (InstalledToolImporter(tool, tools) for tool in tools.installed)
    return IMPORTERS | {importer.envelope_type: importer for importer in installed}


__all__ = ["IMPORTERS", "importers_for"]
