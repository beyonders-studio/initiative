"""Wire shapes for archiving.

``ArchivableType`` is derived from ``ARCHIVE_TARGETS`` the same way the trash
can's ``EntityType`` is derived from ``TRASH_TARGETS``, so a new tool becomes
archivable by joining the ``Tool`` enum rather than by being listed again here.
"""

from datetime import datetime
from enum import Enum

from pydantic import ConfigDict

from app.core.tools import ARCHIVE_TARGETS
from app.schemas.base import SanitizedBaseModel

ArchivableType = Enum(
    "ArchivableType", {name: name for name in ARCHIVE_TARGETS}, type=str
)
ArchivableType.__doc__ = "Things that can be archived."


class ArchiveResponse(SanitizedBaseModel):
    """What archiving or unarchiving answers with.

    The stamp, not the entity: one endpoint serves ten kinds, and a caller that
    wants the whole row reads it back from the route that already serves it.
    """

    entity_type: ArchivableType
    entity_id: int
    archived_at: datetime | None = None


class ContentCan(SanitizedBaseModel):
    """What the caller may do to a piece of content, as the server answers it.

    Each flag is the check the route that does the thing runs, so a client
    reads its affordances here rather than working them out from a rung."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    edit: bool = False


class ToolCan(ContentCan):
    """What the caller may do to one of a tool's rows
    (``permissions.client_access``)."""

    #: Write what it holds: a calendar's events, a project's tasks. The same as
    #: ``edit`` inside an initiative; on a row that belongs to the whole
    #: community, ``edit`` is the row itself and stays with its administrators.
    contribute: bool = False
    delete: bool = False
    #: Change who it is shared with.
    share: bool = False
    #: Export it on its own. Still true while it is archived: an export
    #: changes nothing.
    export: bool = False
    #: Take it back out of the archive. False for a row archived along with the
    #: thing above it, which comes back with that thing.
    unarchive: bool = False


class ToolState[CanT: ToolCan](SanitizedBaseModel):
    """What every tool's read carries beside its own fields: the archive stamp
    and what the caller may do to it."""

    #: When this was put away, or ``null`` while it is live.
    archived_at: datetime | None = None
    can: CanT
