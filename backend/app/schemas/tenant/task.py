from datetime import datetime
from string import ascii_letters, digits
from typing import Final, List, Optional
from uuid import uuid4

from pydantic import AliasChoices, ConfigDict, Field, field_validator, model_validator

from app.core.identity_boundary import GuildId, PersonId
from app.schemas.base import (
    MentionStr,
    RichMentionStr,
    RichTextStr,
    SanitizedBaseModel,
    TitleStr,
    reject_null,
)
from app.schemas.query import PageMeta
from app.schemas.recurrence import OccurrenceScope, TaskRule, validate_task_recurrence

from app.schemas.platform.access_grant import AccessGrantRead
from app.schemas.platform.user import PersonShape, UserPublic
from app.schemas.tenant.evidence import EvidenceRead
from app.schemas.tenant.initiative import InitiativeSummary
from app.schemas.tenant.task_status import TaskStatusRead
from app.schemas.tenant.task_type import TaskTypeRead
from app.schemas.tenant.tag import TagSummary
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertiesOnUpdate,
    PropertySummary,
)

from app.core.intake import Conversation, IntakeStream
from app.models.tenant.task import RecurrenceStrategy, TaskPriority, TaskStatusCategory
from app.models.platform.user import UserStatus


class TaskAssigneeSummary(PersonShape):
    """Minimal assignee data for task lists.

    A person appears here, so it follows the same two rules every other
    guild-scoped shape does: the handle is always present and is what renders
    when there is no name to show, and ``display_name`` is the name the person
    set in this guild.
    """

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: PersonId
    username: str
    discriminator: int
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.active


#: Characters a checklist item id may hold. The client mints one per item so a
#: new line is addressable before it round-trips; anything arriving from an
#: import or the AI batch is minted here instead.
_ITEM_ID_CHARS: Final = frozenset(ascii_letters + digits + "-_")
_MAX_ITEM_ID_LENGTH: Final = 36

#: Flat code raised for an id outside that set, mapped in ``errors.json``.
INVALID_CHECKLIST_ITEM_ID = "INVALID_CHECKLIST_ITEM_ID"


def mint_checklist_item_id() -> str:
    """A fresh item id, for an item that arrived without one."""
    return uuid4().hex


class ChecklistItemInput(SanitizedBaseModel):
    """One checklist line as written. ``id`` is optional: an item that arrives
    without one is given a fresh id."""

    id: Optional[str] = Field(default=None, max_length=_MAX_ITEM_ID_LENGTH)
    text: MentionStr = Field(min_length=1, max_length=2000)
    done: bool = False

    @field_validator("id")
    def id_is_an_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and (not value or set(value) - _ITEM_ID_CHARS):
            raise ValueError(INVALID_CHECKLIST_ITEM_ID)
        return value


class ChecklistItem(SanitizedBaseModel):
    """One checklist line as stored and read back."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: str
    text: MentionStr
    done: bool = False


class ChecklistProgress(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    completed: int = 0
    total: int = 0


class TaskParentSummary(SanitizedBaseModel):
    """The task a task is part of: the target of its ``part_of`` edge."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    title: str


class ChecklistItemToggle(SanitizedBaseModel):
    """The one field a tick changes."""

    done: bool


#: Ceiling on a single task's checklist. A list past this is a project.
#: Enforced in ``services.tenant.task_checklist.normalize``, which can see both
#: the written list and the one it replaces — a longer list carried in by a
#: migration or an import has to stay shrinkable.
MAX_CHECKLIST_ITEMS: Final = 100


class TaskBase(SanitizedBaseModel):
    title: str
    priority: TaskPriority = TaskPriority.medium
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[str] = None
    recurrence_strategy: RecurrenceStrategy = RecurrenceStrategy.fixed
    recurrence_limit: Optional[int] = Field(default=None, ge=1, le=24, strict=True)


class TaskCreate(TaskBase, PropertiesOnCreate):
    title: TitleStr
    description: Optional[RichMentionStr] = None
    project_id: int
    recurrence: Optional[TaskRule] = None
    #: The zone ``recurrence``'s days were picked in, and ``recurrence_shift``
    #: is taken from it. Omitted, the rule's days are UTC days.
    tz: Optional[str] = Field(default=None, max_length=64)
    assignee_ids: List[PersonId] = Field(default_factory=list)
    task_status_id: Optional[int] = None
    #: One of the project's task types; its default when not given.
    task_type_id: Optional[int] = None
    tag_ids: List[int] = Field(default_factory=list, max_length=100)
    checklist: List[ChecklistItemInput] = Field(default_factory=list)
    #: The task this one is part of, written as its ``part_of`` edge.
    parent_task_id: Optional[int] = None

    @model_validator(mode="after")
    def _valid_recurrence(self) -> "TaskCreate":
        validate_task_recurrence(
            rule=self.recurrence,
            strategy=self.recurrence_strategy,
            limit=self.recurrence_limit,
            due=self.due_date,
        )
        return self


class TaskUpdate(PropertiesOnUpdate):
    title: Optional[TitleStr] = None
    description: Optional[RichMentionStr] = None
    #: The description this ``description`` was written over. Given and no
    #: longer the stored one, the update is refused with
    #: ``DESCRIPTION_CHANGED``.
    description_base: Optional[RichMentionStr] = None
    task_status_id: Optional[int] = None
    #: Another of the project's task types. Nothing the task holds is lost:
    #: what the new type's page does not show is kept, not cleared.
    task_type_id: Optional[int] = None
    #: Move the task to its project's column of this category (the nearest
    #: one before it where the project has none), for a caller that knows
    #: "done" but not which column that is. Ignored with ``task_status_id``,
    #: and a task already in this category stays in its column.
    status_category: Optional[TaskStatusCategory] = None
    priority: Optional[TaskPriority] = None
    assignee_ids: Optional[List[PersonId]] = None
    #: People put on the task beside whoever is on it when the change is
    #: written, rather than a list that replaces them all. Not with
    #: ``assignee_ids``.
    add_assignee_ids: Optional[List[PersonId]] = Field(default=None, max_length=100)
    #: People taken off the task, leaving whoever else is on it. Not with
    #: ``assignee_ids``.
    remove_assignee_ids: Optional[List[PersonId]] = Field(default=None, max_length=100)
    start_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    recurrence: Optional[TaskRule] = None
    #: The zone ``recurrence``'s days were picked in, and ``recurrence_shift``
    #: is taken from it. Omitted, the rule's days are UTC days.
    tz: Optional[str] = Field(default=None, max_length=64)
    recurrence_strategy: Optional[RecurrenceStrategy] = None
    recurrence_limit: Optional[int] = Field(default=None, ge=1, le=24, strict=True)
    #: ``properties`` writes only the values it names, leaving the rest: what
    #: a change of type (or a move) sends for the fields the new page requires.
    merge_properties: bool = False
    # PATCH semantics: None = "leave unchanged"; a list (incl. []) = replace-all.
    tag_ids: Optional[List[int]] = Field(default=None, max_length=100)
    checklist: Optional[List[ChecklistItemInput]] = None
    #: The task this one is part of, written as its ``part_of`` edge in place
    #: of the one it has; null takes it out of its parent.
    parent_task_id: Optional[int] = None
    #: Which tasks of a repeating series the edit is for (``task_series``).
    #: Omitted, it carries forward from this task ("following"). The repeat
    #: itself always changes from this task on.
    scope: Optional[OccurrenceScope] = None

    _required = reject_null("title", "priority")

    @model_validator(mode="after")
    def _one_way_to_change_assignees(self) -> "TaskUpdate":
        if self.assignee_ids is not None and (
            self.add_assignee_ids is not None or self.remove_assignee_ids is not None
        ):
            raise ValueError(
                "assignee_ids replaces the assignees; send it without "
                "add_assignee_ids or remove_assignee_ids"
            )
        return self


class TaskMoveRequest(SanitizedBaseModel):
    target_project_id: int = Field(gt=0)
    #: Written to the task once it is in the destination, in the same
    #: request: the fields its page there requires that it does not fill.
    changes: Optional[TaskUpdate] = None


class TaskProjectSummary(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    icon: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative: Optional[InitiativeSummary] = None
    archived_at: Optional[datetime] = None
    is_template: Optional[bool] = None


class TaskRead(TaskBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    description: Optional[RichMentionStr] = None
    id: int
    project_id: int
    task_status_id: int
    task_status: TaskStatusRead
    #: Which of its project's task types the task is.
    task_type_id: int
    task_type: TaskTypeRead
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    position: float
    archived_at: Optional[datetime] = None
    created_by: Optional[PersonId] = None
    # Author summary — lets the detail view render "Created by …" without
    # fetching the whole guild roster to resolve ``created_by``.
    creator: Optional[UserPublic] = None
    assignees: List[UserPublic] = []
    recurrence_occurrence_count: int = 0
    recurrence_shift: int = 0
    recurrence_anchor: Optional[datetime] = None
    recurrence_anchor_count: int = Field(default=0, ge=0)
    #: No occurrence of the series starts after this; None while it goes on.
    recurrence_until: Optional[datetime] = None
    #: The first task of the repeating series; None until the series moves on.
    series_id: Optional[int] = None
    #: How many live tasks the series holds, this one included.
    series_size: int = 1
    comment_count: int = 0
    #: How many things are still holding this task up: live ``depends_on``
    #: edges whose far end has not finished. Only kinds with a reading of
    #: "finished" count — see :mod:`app.db.blocking`.
    blocked_by_open_count: int = 0
    project: Optional[TaskProjectSummary] = None
    checklist: List[ChecklistItem] = []
    checklist_progress: Optional[ChecklistProgress] = None
    #: The task this one is part of, where it is part of one the reader can
    #: open (``app.services.tenant.task_hierarchy``).
    parent: Optional[TaskParentSummary] = None
    #: How many of the tasks that are part of this one are done, of those
    #: not archived; None for a task with none.
    subtask_progress: Optional[ChecklistProgress] = None
    tags: List[TagSummary] = []
    properties: List[PropertySummary] = []


class TaskListRead(TaskBase):
    """Lightweight schema for task list endpoints - excludes heavy nested data"""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    #: The description's opening words as plain text, ending on a word
    #: boundary with an ellipsis when cut, and a mention as its markdown,
    #: ``@[](42)``. The whole text is on ``TaskRead``.
    description_excerpt: Optional[MentionStr] = None
    has_description: bool = False
    id: int
    project_id: int
    task_status_id: int
    task_status: TaskStatusRead
    #: Which of its project's task types the task is.
    task_type_id: int
    task_type: TaskTypeRead
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    position: float
    archived_at: Optional[datetime] = None
    created_by: Optional[PersonId] = None
    assignees: List[TaskAssigneeSummary] = []
    recurrence_occurrence_count: int = 0
    recurrence_shift: int = 0
    recurrence_anchor: Optional[datetime] = None
    recurrence_anchor_count: int = Field(default=0, ge=0)
    #: No occurrence of the series starts after this; None while it goes on.
    recurrence_until: Optional[datetime] = None
    comment_count: int = 0
    #: How many things are still holding this task up: live ``depends_on``
    #: edges whose far end has not finished. Only kinds with a reading of
    #: "finished" count — see :mod:`app.db.blocking`.
    blocked_by_open_count: int = 0
    community_id: Optional[GuildId] = Field(
        default=None, validation_alias=AliasChoices("community_id", "guild_id")
    )
    community_name: Optional[str] = Field(
        default=None, validation_alias=AliasChoices("community_name", "guild_name")
    )
    project_name: Optional[str] = None
    initiative_id: Optional[int] = None
    initiative_name: Optional[str] = None
    initiative_color: Optional[str] = None
    checklist_progress: Optional[ChecklistProgress] = None
    #: The task this one is part of, where it is part of one the reader can
    #: open (``app.services.tenant.task_hierarchy``).
    parent: Optional[TaskParentSummary] = None
    #: How many of the tasks that are part of this one are done, of those
    #: not archived; None for a task with none.
    subtask_progress: Optional[ChecklistProgress] = None
    tags: List[TagSummary] = []
    properties: List[PropertySummary] = []


class ColumnFillRead(SanitizedBaseModel):
    """One limited column of a project's board: its limit, and how many open
    tasks it holds."""

    project_id: int
    status_id: int
    limit: int
    count: int


class TaskListResponse(PageMeta):
    items: List[TaskListRead]
    sorting: Optional[str] = None


class TaskReorderItem(SanitizedBaseModel):
    id: int
    task_status_id: int
    # Bounded to reject NaN/±inf (which would silently defeat the rebalance
    # gap check, where `abs(a - b) < gap` is always False for NaN). Negative
    # values are valid — dropping above a card with a fractional position can
    # legitimately produce one.
    position: float = Field(ge=-1e18, le=1e18)


class TaskReorderRequest(SanitizedBaseModel):
    project_id: int
    items: list[TaskReorderItem]


class CaseMessageRead(SanitizedBaseModel):
    """One part of the conversation with whoever filed a case."""

    id: int
    #: Who wrote it: the requester, or the person on the team who answered.
    author: Optional[UserPublic] = None
    from_requester: bool
    #: Kept as written, like any comment body.
    content: RichTextStr
    created_at: datetime


class CaseEvidenceRead(EvidenceRead):
    """A file attached to a case, and where in the conversation it came."""

    #: The message it came with, where it came with one.
    comment_id: Optional[int] = None
    #: Sent by whoever filed the case.
    from_requester: bool = False


class TaskCaseRead(SanitizedBaseModel):
    """How an operations case was filed, for the people working it."""

    stream: IntakeStream
    opened_at: datetime
    #: Who filed it, where somebody did. Not necessarily a member here.
    filer: Optional[UserPublic] = None
    #: What they called it when they filed it. The task's title is the team's.
    filer_subject: Optional[str] = None
    #: What it is about within its stream, as they chose: a support topic,
    #: a security topic, ``appeal``.
    topic: Optional[str] = None
    #: What the case allows with the filer: ``open``, ``staff_first`` (the
    #: team speaks first), or ``none`` — also where nobody filed it.
    conversation: Conversation
    #: The binding's statuses that mean "waiting on the filer" and "being
    #: worked", where it names them.
    awaiting_filer_status_id: Optional[int] = None
    active_status_id: Optional[int] = None
    #: The conversation with the requester, oldest first. Kept apart from the
    #: task's comments: it is what they read, and only that.
    messages: List[CaseMessageRead] = Field(default_factory=list)
    #: What was attached to the case, oldest first.
    evidence: List[CaseEvidenceRead] = Field(default_factory=list)
    #: The access grants asked for this case, newest first: who holds each,
    #: on which community, at what level, and where it stands.
    grants: List[AccessGrantRead] = Field(default_factory=list)
    #: What the case is about, as it was opened with: the community, and the
    #: kind and id of the thing in it, where it names them.
    subject_community_id: Optional[int] = None
    resource_type: Optional[str] = None
    resource_id: Optional[int] = None
