"""Data job — one asynchronous import or export request (guild-content,
own-row).

The row stores job metadata and the caller's *options* only (an export's
filter selector, an import's target and include map) — never resolved rows,
exported or imported content, or tokens; it must not become a second copy of
sensitive data. The job's one stored file (an import's staged payload, an
export's rendered artifact) lives behind the guild's storage backend at
``file_ref`` and is reached only through its job. Small imports and exports
run in-request and persist no row at all.

Every query by status or by person names a ``direction``: the two kinds share
a record, not a lifecycle. Unlike an export, a stale ``running`` import is
never re-claimed and re-applied: the interrupted apply has already committed
chunks under the always-create policy, so a re-run would duplicate them. The
import worker fails such rows closed instead.

RLS: guild-level placement with the ``own_row_*`` policy overlay
(``app.db.tenancy.OWN_ROW_TABLES``) — a job may span initiatives ("export all
my tasks", a backup), so it can't be initiative-scoped, but its options, plan,
report and file must not be guild-wide-readable either. Owner or routed guild
admin only.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.core.encryption import FERNET_SALT, SALT_IMPORT_CREDENTIAL
from app.models.tenant._mixins import CreatedByMixin


class DataJobDirection(str, Enum):
    import_ = "import"
    export = "export"


class DataJobStatus(str, Enum):
    # Import only: payload uploaded, plan persisted, awaiting user confirm.
    staged = "staged"
    # Import only: a foreign source is being read into a bundle. Nothing has
    # been written to any content table yet, which is what makes this the one
    # status a stale import is RE-CLAIMED from rather than failed: the fetch
    # has no partial result to duplicate, only a partial payload to throw away.
    fetching = "fetching"
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    # Import only: user-cancelled while staged/queued (payload deleted).
    cancelled = "cancelled"
    # The job's file was deleted at its deadline: an export's artifact, or an
    # import's payload left unconfirmed.
    expired = "expired"


#: The statuses in which a job still holds its file: an export's artifact once
#: it is rendered, an import's payload until it is applied.
HOLDS_FILE: dict[DataJobDirection, tuple[DataJobStatus, ...]] = {
    DataJobDirection.export: (DataJobStatus.done,),
    DataJobDirection.import_: (
        DataJobStatus.staged,
        DataJobStatus.fetching,
        DataJobStatus.queued,
    ),
}


class DataJob(CreatedByMixin, table=True):
    __tablename__ = "data_jobs"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('import', 'export')", name="ck_data_jobs_direction"
        ),
        Index("ix_data_jobs_direction_status", "direction", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    created_by: int = Field(foreign_key="users.id", nullable=False)

    # Plain string columns (no shared PG enum type to provision per schema);
    # both are str-enums, so members compare and bind directly.
    direction: DataJobDirection = Field(sa_column=Column(String, nullable=False))
    status: DataJobStatus = Field(
        default=DataJobStatus.queued,
        sa_column=Column(String, nullable=False, server_default="queued"),
    )

    # Import: the envelope type ("initiative-file", …) or "backup".
    # Export: what is exported ("tasks", "community", …).
    source: str = Field(nullable=False)
    # The caller's OPTIONS — an export's filter selector, replayed through
    # the source adapter at render time; an import's target initiative,
    # include map, the ``anchor`` a backup's dates are moved from, who
    # ``join``s what it creates. Never content or results.
    params: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # Storage key relative to the guild prefix: an import's staged payload
    # ("imports/{uuid4hex}.json|.zip") or an export's artifact
    # ("exports/{id}.pdf").
    file_ref: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    # When ``file_ref`` is deleted: an unconfirmed import payload's, or a
    # finished export artifact's.
    expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # --- import only ---
    # Backup pre-flight summary (counts/names shown at confirm) — not content.
    plan: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    # Terminal report (per-entry outcomes, unmatched emails, renames).
    result: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    # The secret a job needs to read a foreign site, for as long as that job
    # needs it: set when the import starts and cleared at every terminal
    # transition. Fernet-encrypted at rest under ``SALT_IMPORT_CREDENTIAL``
    # and re-keyed by the SECRET_KEY rotation. Not a field of
    # ``DataJobRead``, so it is never serialized.
    secret_encrypted: Optional[str] = Field(
        default=None,
        sa_column=Column(
            Text, nullable=True, info={FERNET_SALT: SALT_IMPORT_CREDENTIAL}
        ),
    )

    # --- export only ---
    template_id: Optional[str] = Field(default=None)
    format: Optional[str] = Field(default=None)
    # Where a delivered archive was written, when it was too large to hand
    # back over HTTP. Exactly one of this and ``file_ref`` is set on a
    # finished export: the app either has the bytes or it does not, and a
    # delivered archive lives under the operator's retention rather than the
    # artifact GC's.
    destination_ref: Optional[str] = Field(default=None)
    #: How many times the stale sweep has queued this export again.
    restarts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    # The initiatives whose content the artifact holds, recorded when it is
    # rendered. The download asks for each again; ``None`` is a job rendered
    # before this was recorded, whose artifact is not served.
    initiative_ids: Optional[list[int]] = Field(
        default=None, sa_column=Column(ARRAY(Integer), nullable=True)
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
