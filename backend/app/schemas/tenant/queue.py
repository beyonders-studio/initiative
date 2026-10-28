from __future__ import annotations

from datetime import datetime
from typing import List, Mapping, Optional, TYPE_CHECKING

from pydantic import ConfigDict, Field

from app.core.identity_boundary import PersonId
from app.schemas.base import (
    MentionStr,
    RichMentionStr,
    SanitizedBaseModel,
    TitleStr,
    reject_null,
)
from app.schemas.query import PageMeta

from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertySummary,
    annotated_properties,
)
from app.schemas.tenant.tag import TagSummary, annotated_tags
from app.schemas.tenant.tool import ToolSummaryBase, from_row, serialize_tool
from app.schemas.platform.user import UserPublic

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.queue import Queue, QueueItem


# ---------------------------------------------------------------------------
# Queue item schemas
# ---------------------------------------------------------------------------


class QueueItemBase(SanitizedBaseModel):
    label: str = Field(..., min_length=1, max_length=255)
    position: float = 0.0
    color: Optional[str] = None
    notes: Optional[RichMentionStr] = None
    is_visible: bool = True


class QueueItemCreate(QueueItemBase, PropertiesOnCreate):
    label: TitleStr = Field(..., min_length=1, max_length=255)
    user_id: Optional[PersonId] = None
    tag_ids: Optional[List[int]] = None
    task_ids: Optional[List[int]] = None


class QueueItemUpdate(PropertiesOnUpdate):
    label: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    position: Optional[float] = None
    user_id: Optional[PersonId] = None
    color: Optional[str] = None
    notes: Optional[RichMentionStr] = None
    is_visible: Optional[bool] = None
    #: Replaces every tag on the item; omitted leaves them as they are.
    tag_ids: Optional[List[int]] = Field(default=None, max_length=100)
    #: The notes these were written over, as their writer saw them. Given, a
    #: write over notes that have since changed is refused.
    notes_base: Optional[RichMentionStr] = None

    _required = reject_null("label", "position", "is_visible")


class QueueItemRead(QueueItemBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    queue_id: int
    user_id: Optional[PersonId] = None
    user: Optional[UserPublic] = None
    tags: List[TagSummary] = Field(default_factory=list)
    properties: List[PropertySummary] = Field(default_factory=list)
    #: How many things are pinned to this item, of whatever kind a link can
    #: name.
    attachment_count: int = 0
    # Round in which the user held this item (NULL = not held). The rotation
    # auto-releases the item at its natural slot in ``held_at_round + 1`` so
    # held participants can't be forgotten.
    held_at_round: Optional[int] = None
    #: Who added it: whoever wrote it is not offered a report of it.
    created_by: Optional[PersonId] = None
    created_at: datetime


class QueueReleaseRequest(SanitizedBaseModel):
    """Options for releasing a held queue item back into the rotation."""

    # When True (PF2e "Delay" semantics), the released item's position is
    # rewritten so it lands immediately after the current item in turn order
    # — i.e. they take their delayed turn at this point and stay at this new
    # initiative slot for the rest of the encounter. Default False preserves
    # their original initiative; they re-enter at their natural slot.
    reposition: bool = False


# ---------------------------------------------------------------------------
# Queue schemas
# ---------------------------------------------------------------------------


class QueueBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[MentionStr] = None


class QueueCreate(QueueBase, PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class QueueUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[MentionStr] = None

    _required = reject_null("name")


class QueueTurnPreview(SanitizedBaseModel):
    """One turn as a list's card draws it: who, in what colour, and whether it
    is theirs now."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    label: str
    color: Optional[str] = None
    current: bool = False


class QueueSummary(QueueBase, ToolSummaryBase):
    current_round: int
    is_active: bool
    #: Whose turn it is and who follows, when the list was asked for previews.
    preview: Optional[List[QueueTurnPreview]] = None


class QueueListResponse(PageMeta):
    items: List[QueueSummary]


class QueueRead(QueueSummary):
    items: List[QueueItemRead] = Field(default_factory=list)
    current_item_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def active_items(queue: "Queue") -> list["QueueItem"]:
    """The queue's items that are not in the trash."""
    items = getattr(queue, "items", None) or []
    return [item for item in items if item.deleted_at is None]


def serialize_queue_item(
    item: "QueueItem",
    *,
    attachment_count: int = 0,
) -> QueueItemRead:
    """One queue item.

    The attachment count is handed in rather than read off the item: links live
    in their own table, and a queue shows many items at once, so the caller
    counts them for the whole page in one go.
    """
    return from_row(
        QueueItemRead,
        item,
        tags=annotated_tags(item),
        properties=annotated_properties(item),
        attachment_count=attachment_count,
    )


def serialize_queue(
    queue: "Queue",
    *,
    context: ActorContext,
    user_id: Optional[int] = None,
    attachment_counts: Optional[Mapping[int, int]] = None,
) -> QueueRead:
    """A queue and the items in it that are not in the trash.

    ``attachment_counts`` is keyed by item id — what one batched read gives for
    the whole page. Omitting it says the items have no attachments rather than
    that nobody asked, so a caller with a session should pass it:
    ``_serialized_queue`` in the queues router is the one that does.
    """
    return serialize_tool(
        QueueRead,
        queue,
        context=context,
        user_id=user_id,
        items=[
            serialize_queue_item(
                item,
                attachment_count=(attachment_counts or {}).get(item.id, 0),
            )
            for item in active_items(queue)
        ],
    )
