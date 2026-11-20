"""Every mountable tool can be unmade.

Removal walks what the install owns through a per-type handler, so a tool added
to the manifest vocabulary without one would install fine and quietly leave its
row behind on uninstall. The drift test refuses that combination at CI rather
than at the first uninstall.
"""

from app.services.marketplace.definitions import MOUNTABLE_TOOLS
from app.services.tenant.guild_plugins import ARTIFACT_HANDLERS


def test_every_mountable_tool_has_exactly_one_handler():
    """A tool a plug-in may mount must have a handler, or uninstalling it would
    leave the row it created behind; a handler for something no manifest can
    name is dead code that reads as support."""
    assert set(ARTIFACT_HANDLERS) == MOUNTABLE_TOOLS
