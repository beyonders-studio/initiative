"""API payload for data jobs, imports and exports alike. ``params`` is the
caller's own options (an export's filter selector, an import's target and
include map), echoed back so a client can re-run the job; ``plan``/``result``
are an import's pre-flight summary and terminal report. The row never carries
imported or exported content — an export's artifact is fetched via the
download route."""

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import AliasChoices, ConfigDict, Field, computed_field

from app.models.tenant.data_job import (
    HOLDS_FILE,
    DataJob,
    DataJobDirection,
    DataJobStatus,
)
from app.schemas.base import SanitizedBaseModel


class DataJobRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    community_id: int = Field(validation_alias=AliasChoices("community_id", "guild_id"))
    direction: DataJobDirection
    created_by: int
    source: str
    params: dict[str, Any]
    status: DataJobStatus
    error: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Import only.
    plan: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    # Export only.
    template_id: Optional[str] = None
    format: Optional[str] = None
    # Read from the row so ``delivered`` can be computed, and excluded from
    # the payload: the destination is a path on the server, which the operator
    # configured and already knows. A community administrator needs to know
    # that an archive was delivered rather than where this deployment keeps
    # its files.
    destination_ref: Optional[str] = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delivered(self) -> bool:
        """The export's archive went to the operator's destination; there is
        nothing here to download."""
        return self.destination_ref is not None


def file_expired(job: DataJob, now: Optional[datetime] = None) -> bool:
    """Whether the job's file is past its expiry: swept already, or still
    held with an ``expires_at`` that has passed and waiting for the next GC
    pass to delete it."""
    if job.status == DataJobStatus.expired:
        return True
    if job.status not in HOLDS_FILE[job.direction] or job.expires_at is None:
        return False
    expires_at = job.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= (now or datetime.now(timezone.utc))


def serialize_data_job(job: DataJob, *, guild_id: int) -> DataJobRead:
    """The wire shape of one job row.

    The row lives in its guild's schema and carries no guild column of its
    own, so the guild is handed in by whoever routed the session. A job whose
    file is past its expiry reads as ``expired`` before GC has swept it, as
    the download and confirm routes treat it.
    """
    fields = {
        name: getattr(job, name)
        for name in DataJobRead.model_fields
        if name != "community_id"
    }
    if file_expired(job):
        fields["status"] = DataJobStatus.expired
    return DataJobRead(community_id=guild_id, **fields)
