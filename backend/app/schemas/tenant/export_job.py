"""API payloads about exports beyond the job itself (``DataJobRead``)."""

from datetime import datetime
from typing import Optional

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel
from app.schemas.tenant.data_job import DataJobRead


class CommunityExportStatus(SanitizedBaseModel):
    """What the community settings page knows about whole-community exports
    without opening the wizard.

    A community takes one of these at a time and rarely — so the page says
    who took the last one and how it ended, rather than leaving the next
    person to find out by being refused.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The window between whole-community exports; ``0`` where the deployment
    #: has turned the wait off.
    cooldown_hours: int
    #: When the next one may start. ``None`` means now.
    next_available_at: Optional[datetime] = None
    #: The newest whole-community export, whatever became of it — a failed or
    #: expired one is still what somebody needs to know about.
    latest: Optional[DataJobRead] = None
    #: Who started ``latest``, as this community names people. ``None`` where
    #: that account is gone.
    latest_started_by: Optional[str] = None
