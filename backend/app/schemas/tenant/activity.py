"""The activity feed's entries, as the API sends them."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.schemas.base import MentionStr, SanitizedBaseModel
from app.schemas.platform.user import UserPublic
from app.services.tenant.activity_feed import PAGE_SIZE, FeedView, Verb


class ActivityQuery(BaseModel):
    """What a request asks the feed for. Narrowed to one initiative, or to one
    tool: ``tool`` with ``tool_id``, which come together or not at all."""

    view: FeedView = FeedView.all
    initiative_id: Optional[int] = None
    tool: Optional[Tool] = None
    tool_id: Optional[int] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=PAGE_SIZE, ge=1, le=50)

    @model_validator(mode="after")
    def _tool_with_its_id(self) -> "ActivityQuery":
        if (self.tool is None) != (self.tool_id is None):
            raise ValueError("tool and tool_id come together")
        return self


class CatchUpRequest(BaseModel):
    """What a catch-up covers: what changed since ``since`` (the change log's
    whole window without one), in the community or in one tool."""

    since: Optional[AwareDatetime] = None
    tool: Optional[Tool] = None
    tool_id: Optional[int] = None

    @model_validator(mode="after")
    def _tool_with_its_id(self) -> "CatchUpRequest":
        if (self.tool is None) != (self.tool_id is None):
            raise ValueError("tool and tool_id come together")
        return self


class ActivityEntry(SanitizedBaseModel):
    """One item, and what people did to it lately."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    entity_type: SearchEntityType
    entity_id: int
    title: MentionStr
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    #: The tool it is in, and what that is called. ``tool_title`` is None for an
    #: item that IS a tool.
    tool: Optional[Tool] = None
    tool_id: Optional[int] = None
    tool_title: Optional[str] = None
    #: When the latest of it happened.
    latest: datetime
    #: What happened, each once.
    verbs: List[Verb]
    #: The people who did it, latest first, up to three.
    actors: List[UserPublic]
    #: How many people did, the ones named included.
    actor_count: int


class ActivityFeedPage(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[ActivityEntry]
    page: int
    page_size: int
    has_next: bool
