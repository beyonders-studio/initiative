from datetime import UTC, datetime

from pydantic import ConfigDict
from sqlalchemy import Column, DateTime, String
from sqlmodel import Field

from app.models.tenant._mixins import CreatedByMixin, HoldMixin, SoftDeleteMixin


class Tag(HoldMixin, CreatedByMixin, SoftDeleteMixin, table=True):
    """Guild-scoped tag for categorizing tasks, projects, and files.

    Supports nested tag naming via "/" convention (e.g., "books/fiction").
    The "/" is purely visual/organizational - no parent-child DB relationships.
    """

    __tablename__ = "tags"
    __allow_unmapped__ = True
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(
        sa_column=Column(String(length=100), nullable=False),
    )
    color: str = Field(
        default="#6366F1",
        sa_column=Column(String(length=9), nullable=False, server_default="#6366F1"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
