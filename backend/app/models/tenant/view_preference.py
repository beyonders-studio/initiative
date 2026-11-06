"""One person's view of one of the community's lists: how they show it, and
what they narrow it to, order it by and group it by.

The community's half of the view-preference store
(``app.models.platform.user_view_preference`` keeps the account's own): a
project's, an initiative tool's, a collection's or the roster's view, whose
filters name the community's tags and people. Keyed by ``(user_id,
scope_key)``; the key names the list inside this community
(``view:project:12``) and the ``value`` is the frontend's own JSON, kept
verbatim.

RLS: guild-level placement with the ``own_row_*`` policy overlay
(``app.db.tenancy.OWN_ROW_TABLES``).
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.platform.user_view_preference import MAX_SCOPE_KEY_LENGTH


class ViewPreference(SQLModel, table=True):
    __tablename__ = "view_preferences"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    scope_key: str = Field(
        sa_column=Column(String(MAX_SCOPE_KEY_LENGTH), primary_key=True)
    )
    value: Any = Field(sa_column=Column(JSONB, nullable=False))
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
