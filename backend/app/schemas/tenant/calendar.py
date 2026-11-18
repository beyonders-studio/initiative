from __future__ import annotations

from pydantic import Field

from app.models.tenant.calendar import DEFAULT_CALENDAR_COLOR
from app.schemas.base import MentionStr, SanitizedBaseModel, TitleStr, reject_null
from app.schemas.query import PageMeta
from app.schemas.tenant.archive import ToolCan
from app.schemas.tenant.property import PropertiesOnCreate
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.tool import ToolSummaryBase


class CalendarBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: MentionStr | None = None
    # The calendar's display color — its events render in it. Every calendar
    # has one: creates default it, and the column is NOT NULL.
    color: str = Field(default=DEFAULT_CALENDAR_COLOR, max_length=32)


class CalendarCreate(CalendarBase, PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    #: Which initiative the calendar belongs to, or ``None`` for a guild
    #: calendar — one that belongs to the guild itself, the way the calendar
    #: plug-in's own does. Guild scope answers to no initiative's roles or feature
    #: switch; its grants decide who reads and writes it.
    initiative_id: int | None = None
    tag_ids: list[int] | None = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members, which at guild scope reads
    # as every member of the guild.
    grants: list[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class CalendarUpdate(SanitizedBaseModel):
    name: TitleStr | None = Field(default=None, min_length=1, max_length=255)
    description: MentionStr | None = None
    color: str | None = Field(default=None, min_length=1, max_length=32)

    _required = reject_null("name", "color")


class CalendarSummary(CalendarBase, ToolSummaryBase[ToolCan]):
    #: NULL on a guild-level calendar — one a plug-in mounted, belonging to the
    #: guild rather than to any initiative.
    initiative_id: int | None = None


class CalendarListResponse(PageMeta):
    items: list[CalendarSummary]


class CalendarRead(CalendarSummary):
    pass
