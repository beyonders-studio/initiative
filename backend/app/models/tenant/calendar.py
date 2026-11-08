from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Optional

from sqlalchemy import Column, DateTime, String, Text
from sqlmodel import Field, Relationship

from app.core.tools import Tool
from app.models.tenant._mixins import (
    ArchiveMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    HoldMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    attach_actions,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.tenant.calendar_event import CalendarEvent
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant


DEFAULT_CALENDAR_COLOR = "#6366f1"


class Calendar(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    """Initiative-scoped calendar — the shareable container for events.

    A calendar is to events what a project is to tasks: DAC grants attach to
    the calendar (``resource_type='calendar'``) and events inherit access from
    it. ``color`` is the display color for the calendar and its events, and
    every calendar has one — NOT NULL, defaulted at the schema layer.
    """

    __tablename__ = "calendars"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__: ClassVar[dict[str, bool]] = {"implicit_returning": False}

    id: int | None = Field(default=None, primary_key=True)
    # NULL means a guild-level calendar: it belongs to the guild rather than to
    # any initiative, and who may read or write it is decided by its grants.
    # Everything else about a calendar — its events, its UI, its permission
    # computation — is unchanged, which is the point of reusing the table rather
    # than adding a parallel one.
    initiative_id: int | None = Field(
        default=None, foreign_key="initiatives.id", nullable=True, index=True
    )
    name: str = Field(index=True, nullable=False, max_length=255)
    description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    color: str = Field(
        default=DEFAULT_CALENDAR_COLOR,
        sa_column=Column(
            String(length=32), nullable=False, server_default=DEFAULT_CALENDAR_COLOR
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="calendars")
    creator: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(Calendar.created_by) == MemberProfile.id,"
                " Calendar.created_by_kind == 'member')"
            ),
            "viewonly": True,
        },
    )
    events: list["CalendarEvent"] = Relationship(
        back_populates="calendar",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    grants: list["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Calendar.id, "
                "ResourceGrant.resource_type == 'calendar')"
            ),
            "viewonly": True,
        }
    )


attach_actions(Calendar, Tool.calendar)
