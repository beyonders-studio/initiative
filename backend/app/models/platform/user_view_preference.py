"""Per-user, per-scope JSON preference rows backing view state.

Stores the filter sets, sort orders, view modes, and similar layout
preferences that used to live in client-side ``localStorage``. Keyed by
``(user_id, scope_key)`` so each device sees the same state for a given
view. The ``value`` blob is opaque to the backend — the frontend owns
its shape and is responsible for keeping it small and resilient to
stale references inside it.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel

# Schema-layer caps. Mirror these in any future migration; the DB itself
# does not constrain length beyond the column type, so the request schema
# is the only line of defense against very large blobs.
MAX_SCOPE_KEY_LENGTH = 128
MAX_VALUE_JSON_BYTES = 16 * 1024  # 16 KiB


class UserViewPreference(SQLModel, table=True):
    __tablename__ = "user_view_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "scope_key", name="uq_user_view_preferences_user_scope"
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(
        foreign_key="users.id", ondelete="CASCADE", index=True, nullable=False
    )
    scope_key: str = Field(max_length=MAX_SCOPE_KEY_LENGTH, nullable=False)
    value: Any = Field(sa_column=Column(JSON, nullable=False))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
