from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, String
from sqlmodel import Field

from app.models.tenant._mixins import CreatedByMixin, HoldMixin


class Upload(HoldMixin, CreatedByMixin, table=True):
    __tablename__ = "uploads"
    __table_args__ = (
        CheckConstraint(
            "initiative_id IS NULL OR claimed_at IS NOT NULL",
            name="ck_uploads_initiative_claimed",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(unique=True, index=True)
    size_bytes: int = Field(default=0)
    # MIME type recorded at upload time, so serving can set Content-Type without
    # sniffing the bytes (and a future object-store backend can set it on the
    # object).
    content_type: str = Field(sa_column=Column(String(255), nullable=False))
    # SHA-256 hex of the stored bytes — integrity verification for the eventual
    # object-store migration, and the basis for future content dedup.
    content_hash: str | None = Field(
        default=None, sa_column=Column(String(64), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    # When the file was first saved into something. Until then only its
    # uploader reaches it; from then on its initiative's members do, and edits
    # and purges release it.
    claimed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # The initiative whose content shows the file. NULL on a claimed file means
    # it is shown by content that belongs to the whole guild.
    initiative_id: int | None = Field(
        default=None, foreign_key="initiatives.id", nullable=True, index=True
    )
