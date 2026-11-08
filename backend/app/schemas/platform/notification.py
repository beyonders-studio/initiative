from datetime import datetime
from typing import Any

from pydantic import AliasChoices, ConfigDict, Field

from app.models.platform.notification import NotificationType
from app.schemas.base import SanitizedBaseModel


class NotificationRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    type: NotificationType
    data: dict[str, Any]
    created_at: datetime
    read_at: datetime | None = None
    #: Where it happened, each level independently optional. The row shows the
    #: community; the navigation lights from the same three values.
    community_id: int | None = Field(
        default=None, validation_alias=AliasChoices("community_id", "guild_id")
    )
    initiative_id: int | None = None
    tool: str | None = None


class RedactedAlert(SanitizedBaseModel):
    """The kind-only wording a phone's push carries where content is
    redacted."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    title: str
    body: str


class NotificationAlertRead(SanitizedBaseModel):
    """What the desktop app shows for one line."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notification: NotificationRead
    #: Set where the deployment or the line's community redacts notifications
    #: that leave the app: show this instead of the line's own wording.
    redacted: RedactedAlert | None = None


class NotificationListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    notifications: list[NotificationRead]
    #: Every unread notification the reader has, on the first page; null on
    #: the pages after it.
    unread_count: int | None = None
    #: The next page, or null at the end of the list.
    next_cursor: str | None = None


class NotificationPlace(SanitizedBaseModel):
    """One place with unread activity. Every level is optional: a direct
    message names none of them, a membership notice only a community, a
    comment on a task all of them down to the task."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    community_id: int | None = Field(
        default=None, validation_alias=AliasChoices("community_id", "guild_id")
    )
    initiative_id: int | None = None
    tool: str | None = None
    #: The tool's row: the project, calendar or wiki the item is in.
    resource_id: int | None = None
    #: The item itself: ``task``, ``calendar_event``, ``wiki_page``, or a
    #: tool's own kind, and its id.
    subject_type: str | None = None
    subject_id: int | None = None


class UnreadPlacesResponse(SanitizedBaseModel):
    """Where the dots go. No counts anywhere — the popover shows the list."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    places: list[NotificationPlace]


class SubjectReadRequest(SanitizedBaseModel):
    """The item its reader just opened."""

    community_id: int
    subject_type: str = Field(max_length=32)
    subject_id: int


class SubjectReadResponse(SanitizedBaseModel):
    """What was unread on the item, for its page to show for this visit."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: The comments the read lines named.
    comment_ids: list[int]
    #: Where a rolled-up comment line began: every comment after it by somebody
    #: else was unread. Null when no such line was.
    since: datetime | None = None


class NotificationCountResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    unread_count: int
