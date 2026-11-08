"""Schemas for what a member keeps about items: opens, bookmarks, subscriptions,
reminders."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import ConfigDict

from app.core.tools import CONTENT_KINDS, Tool
from app.models.tenant.personal_item import ViewSource
from app.schemas.base import SanitizedBaseModel

#: Every tool and everything inside one, as a str enum so a path parameter is
#: validated and OpenAPI lists the values.
ContentKind = Enum("ContentKind", [(k, k) for k in CONTENT_KINDS], type=str)


class ListedMark(str, Enum):
    """The marks a list of tools is read by: the tabs, and the bookmarks."""

    view = "view"
    bookmark = "bookmark"


class PersonalItemState(SanitizedBaseModel):
    """What the reader keeps about one item."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entity_type: ContentKind
    entity_id: int
    viewed_at: Optional[datetime] = None
    view_source: Optional[ViewSource] = None
    bookmarked_at: Optional[datetime] = None
    #: When they subscribed by hand.
    subscribed_at: Optional[datetime] = None
    #: Whether they are subscribed, by hand or by making it or being named on
    #: it (``personal_items.subscribers_of``). Left out of a recorded open,
    #: which does not ask.
    subscribed: Optional[bool] = None
    #: When to remind them of it: tasks only.
    remind_at: Optional[datetime] = None
    #: When that reminder went out, if it has.
    reminded_at: Optional[datetime] = None


class ReminderSet(SanitizedBaseModel):
    """When to remind the reader of a task."""

    remind_at: datetime


class PersonalItemRead(SanitizedBaseModel):
    """One tool in the reader's tabs or bookmarks: enough to draw its icon and link
    to it without a fetch per kind, and nothing of its content."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    entity_type: Tool
    entity_id: int
    community_id: int
    # The initiative it lives in, which its URL addresses. NULL for a
    # community-level tool: only calendars have any.
    initiative_id: Optional[int] = None
    name: str
    viewed_at: Optional[datetime] = None
    bookmarked_at: Optional[datetime] = None
    # Projects: the emoji on the project itself.
    icon: Optional[str] = None
    # Files: what picks the file's own icon and colour.
    file_type: Optional[str] = None
    mime_type: Optional[str] = None
    original_filename: Optional[str] = None
