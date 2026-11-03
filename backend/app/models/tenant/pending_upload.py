"""Pending upload — a file arriving in pieces over tus (guild-content, own-row).

A resumable upload (``app.services.resumable``) is staged behind the guild's
storage backend at ``staging_key`` until it is complete; the endpoint the
upload is for (its ``purpose``) then takes it as it would a multipart file.
Until then this row is the upload's only record: how much has arrived, the
storage backend's own state (an S3 multipart upload's id and parts), and the
lease that lets one request at a time append to it.

A staged file has no ``uploads`` row, so nothing serves it; its declared
``length`` counts toward the community's storage from the moment it is
created. The ``resumable_uploads`` sweep deletes a row and its staged bytes
once ``expires_at`` passes.

RLS: guild-level placement with the ``own_row_*`` policy overlay
(``app.db.tenancy.OWN_ROW_TABLES``): owner or routed guild admin only.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import BigInteger, Column, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from app.models.tenant._mixins import CreatedByMixin


class PendingUpload(CreatedByMixin, table=True):
    __tablename__ = "pending_uploads"

    #: The tus id, random and unguessable; the upload's address.
    id: str = Field(sa_column=Column(Text, primary_key=True))
    created_by: int = Field(foreign_key="users.id", nullable=False)
    #: The endpoint the file is for (``app.services.resumable.purposes``).
    purpose: str = Field(sa_column=Column(Text, nullable=False))
    initiative_id: Optional[int] = Field(default=None, nullable=True)
    #: The name the person's file had, as the consuming endpoint will keep it.
    filename: str = Field(sa_column=Column(Text, nullable=False))
    length: int = Field(sa_column=Column(BigInteger, nullable=False))
    offset: int = Field(
        default=0, sa_column=Column(BigInteger, nullable=False, server_default="0")
    )
    #: The flat storage key the bytes are staged under.
    staging_key: str = Field(sa_column=Column(Text, nullable=False))
    #: The storage backend's own state for the upload.
    blob_state: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    lease_token: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    lease_until: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
