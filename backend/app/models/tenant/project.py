from datetime import date, datetime, timezone
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Column, Date, DateTime, Text, UniqueConstraint
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


if TYPE_CHECKING:  # pragma: no cover - imported lazily for type checking only
    from app.models.tenant.task import Task, TaskStatus, TaskType
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.resource_grant import ResourceGrant


class Project(
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
    table=True,
):
    __tablename__ = "projects"
    # A tool row is written before anything has been shared, so it is read
    # back by no RETURNING clause: the id comes from the sequence first and
    # the INSERT stands alone. See app/db/initiative_rls.py.
    __table_args__ = (
        # What a project's metadata is keyed to, so it is in the project's
        # initiative.
        UniqueConstraint("id", "initiative_id", name="uq_projects_id_initiative"),
        {"implicit_returning": False},
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, nullable=False)
    icon: Optional[str] = Field(default=None, max_length=8)
    # TEXT in DDL (unbounded); sa_column keeps autogen quiet vs AutoString
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    initiative_id: int = Field(foreign_key="initiatives.id", nullable=False, index=True)
    # Whole-day schedule for the project itself (both optional, independent of
    # each other). Stored as DATE, not a timestamp: a project runs for calendar
    # days, so there is no time-of-day to keep and no timezone to shift it by.
    start_date: Optional[date] = Field(
        default=None, sa_column=Column(Date, nullable=True)
    )
    end_date: Optional[date] = Field(
        default=None, sa_column=Column(Date, nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    is_template: bool = Field(default=False, nullable=False)
    pinned_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    initiative: Optional["Initiative"] = Relationship(back_populates="projects")

    tasks: List["Task"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    task_statuses: List["TaskStatus"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    task_types: List["TaskType"] = Relationship(
        back_populates="project",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    grants: List["ResourceGrant"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": (
                "and_(foreign(ResourceGrant.resource_id) == Project.id, "
                "ResourceGrant.resource_type == 'project')"
            ),
            "viewonly": True,
        }
    )


attach_actions(Project, Tool.project)
