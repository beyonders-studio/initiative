from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Enum as SQLEnum
from sqlmodel import Field, Relationship, SQLModel

from app.core import recurrence
from app.core.task_types import LAYOUT_SHAPES
from app.db.registry_checks import FROM_REGISTRY
from app.models.tenant._mixins import (
    ArchiveMixin,
    CommentLockMixin,
    CreatedByMixin,
    HoldMixin,
    SoftDeleteMixin,
)

if TYPE_CHECKING:  # pragma: no cover
    from app.models.platform.user_profile_view import MemberProfile
    from app.models.tenant.project import Project


class TaskStatusCategory(str, Enum):
    backlog = "backlog"
    todo = "todo"
    in_progress = "in_progress"
    done = "done"


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class RecurrenceStrategy(str, Enum):
    """How a repeating task's next date is counted."""

    #: "On schedule" in the app: from the task's due date.
    fixed = "fixed"
    #: "After completion": from when the task was finished.
    rolling = "rolling"


class TaskStatus(CreatedByMixin, table=True):
    __tablename__ = "task_statuses"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(
        foreign_key="projects.id", ondelete="CASCADE", nullable=False
    )
    name: str = Field(
        sa_column=Column(String(length=100), nullable=False),
    )
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    category: TaskStatusCategory = Field(
        sa_column=Column(
            SQLEnum(TaskStatusCategory, name="task_status_category"), nullable=False
        ),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    color: str = Field(
        default="#94A3B8",
        sa_column=Column(String(length=9), nullable=False, server_default="#94A3B8"),
    )
    icon: str = Field(
        default="circle-dashed",
        sa_column=Column(
            String(length=64), nullable=False, server_default="circle-dashed"
        ),
    )

    project: Optional["Project"] = Relationship(back_populates="task_statuses")
    tasks: list["Task"] = Relationship(back_populates="task_status")


_SHAPE_VALUES = ", ".join(f"'{shape}'" for shape in LAYOUT_SHAPES)


class TaskType(CreatedByMixin, table=True):
    """What kind of thing a task is, in one project, and how its page is laid
    out (its ``task`` layout, ``tool_layouts.task_type_id``).

    A project always holds at least one, and exactly one is its default: what a
    new task is unless it says otherwise. Names are unique in their project
    regardless of case, because a task moved between projects keeps the type of
    the same name. ``layout_preset`` is the shape its page is drawn as until the
    page is changed (``app.core.task_types``).
    """

    __tablename__ = "task_types"
    __table_args__ = (
        CheckConstraint(
            f"layout_preset IN ({_SHAPE_VALUES})",
            name="ck_task_types_layout_preset",
            info={FROM_REGISTRY: True},
        ),
        Index(
            "uq_task_types_project_name",
            "project_id",
            text("lower(name)"),
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    name: str = Field(sa_column=Column(String(length=100), nullable=False))
    position: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    is_default: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    color: str = Field(
        default="#94A3B8",
        sa_column=Column(String(length=9), nullable=False, server_default="#94A3B8"),
    )
    icon: str = Field(
        default="square-check",
        sa_column=Column(
            String(length=64), nullable=False, server_default="square-check"
        ),
    )
    layout_preset: str = Field(
        default="plain",
        sa_column=Column(String(length=32), nullable=False, server_default="plain"),
    )
    # What a new task of the type starts with where its creator left the field
    # empty: a description outline, checklist lines, a priority, a repeat
    # (``app.schemas.tenant.task_type.TaskTypeStartingValues``).
    starting_values: dict | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )

    project: Optional["Project"] = Relationship(back_populates="task_types")


class TaskAssignee(SQLModel, table=True):
    __tablename__ = "task_assignees"

    # ``Task.assignees`` is a read-only view over this table, so nothing in the
    # ORM clears these rows when a task is hard-deleted. The database does.
    task_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        )
    )
    user_id: int = Field(foreign_key="users.id", primary_key=True, index=True)


class Task(
    HoldMixin,
    CommentLockMixin,
    CreatedByMixin,
    ArchiveMixin,
    SoftDeleteMixin,
    table=True,
):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "recurrence_limit BETWEEN 1 AND 24", name="ck_tasks_recurrence_limit"
        ),
    )
    _display_field = "title"

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", nullable=False)
    task_status_id: int = Field(
        foreign_key="task_statuses.id", ondelete="RESTRICT", nullable=False
    )
    task_type_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("task_types.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
    )
    title: str = Field(nullable=False)
    # TEXT in DDL (unbounded); sa_column keeps autogen quiet vs AutoString
    description: str | None = Field(default=None, sa_column=Column(Text))
    # Ordered ``{"id", "text", "done"}`` objects — the task's checklist. JSONB
    # so one item can be addressed by id and rewritten in place; see
    # ``app.services.tenant.task_checklist``.
    checklist: list[dict] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    priority: TaskPriority = Field(
        default=TaskPriority.medium,
        sa_column=Column(SQLEnum(TaskPriority, name="task_priority"), nullable=False),
    )
    start_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    due_date: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # RFC 5545 recurrence lines as picked (``app.core.recurrence``).
    recurrence: str | None = Field(default=None, sa_column=Column(Text))
    # Minutes from the start's UTC time to where the repeat was picked: whole
    # days for a rule of days, the offset for a rule of hours.
    recurrence_shift: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    # The fixed series' phase survives extra dates and in-place skips. Unlike
    # series_id it remains usable after older task rows have been purged.
    recurrence_anchor: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # Already-consumed starts before a retained anchor when older history was
    # purged (or skipped in place before anchors existed). A conservative
    # legacy bound; new series always retain their complete phase with zero.
    recurrence_anchor_count: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
    # No occurrence of the series starts after this; null when it never ends.
    # Written from ``recurrence`` on every save (see the listener below).
    recurrence_until: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    recurrence_strategy: RecurrenceStrategy = Field(
        default=RecurrenceStrategy.fixed,
        sa_column=Column(String(length=20), nullable=False, server_default="fixed"),
    )
    recurrence_occurrence_count: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0"),
    )
    # An optional maximum number of actual completions on the completer's day.
    recurrence_limit: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    # The first task of the repeating series this task is in, set when the
    # series first moves on. A name for the series rather than a key: the
    # series goes on when its first task is purged.
    series_id: int | None = Field(
        default=None, sa_column=Column(Integer, nullable=True, index=True)
    )
    # What an edit of just this task changed from, by field; the next task in
    # the series is made with these (``app.services.tenant.task_series``).
    recurrence_carry: dict | None = Field(
        default=None, sa_column=Column(JSONB, nullable=True)
    )
    position: float = Field(
        default=0,
        sa_column=Column(
            Numeric(20, 10, asdecimal=False), nullable=False, server_default="0"
        ),
    )
    # When the task entered a ``done``-category status, cleared when it leaves
    # one. Kept in step with ``task_status.category`` by
    # ``app.services.tenant.task_completion`` — never set directly.
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    project: Optional["Project"] = Relationship(back_populates="tasks")
    task_status: TaskStatus | None = Relationship(back_populates="tasks")
    task_type: TaskType | None = Relationship()
    assignees: list["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "secondary": "task_assignees",
            "primaryjoin": "Task.id == foreign(TaskAssignee.task_id)",
            "secondaryjoin": "foreign(TaskAssignee.user_id) == MemberProfile.id",
            "viewonly": True,
        }
    )
    # Read-only link to the author (``created_by``) so reads can expose a
    # ``creator`` summary without a separate roster fetch. The join is spelled
    # out because the target is a view, which carries no foreign key.
    creator: Optional["MemberProfile"] = Relationship(
        sa_relationship_kwargs={
            "primaryjoin": "foreign(Task.created_by) == MemberProfile.id",
            "viewonly": True,
        }
    )


@event.listens_for(Task, "before_insert")
@event.listens_for(Task, "before_update")
def _write_recurrence_until(_mapper, _connection, task: Task) -> None:
    # A task series starts at its due date, or its start date without one.
    start = task.due_date or task.start_date
    if task.recurrence and task.recurrence_strategy == RecurrenceStrategy.fixed:
        if task.recurrence_anchor is None:
            from app.services.tenant.task_series import anchor_from_dates

            task.recurrence_anchor, task.recurrence_anchor_count = anchor_from_dates(
                task
            )
        start = task.recurrence_anchor or start
    task.recurrence_until = (
        recurrence.last_start(
            task.recurrence,
            start,
            task.recurrence_shift,
            done=task.recurrence_anchor_count
            if task.recurrence_strategy == RecurrenceStrategy.fixed
            and task.recurrence_anchor
            else task.recurrence_occurrence_count,
        )
        if task.recurrence and start
        else None
    )
