from typing import Annotated

from pydantic import ConfigDict, Field, model_validator

from app.core.task_type_gallery import GALLERY_BY_KEY
from app.core.task_types import LAYOUT_SHAPES
from app.models.tenant.task import RecurrenceStrategy, TaskPriority
from app.schemas.base import MentionStr, RichMentionStr, SanitizedBaseModel
from app.schemas.recurrence import TaskRule
from app.schemas.tenant.task_status import HEX_COLOR_PATTERN

#: One of :data:`app.core.task_types.LAYOUT_SHAPES`.
_SHAPE_PATTERN = "^(" + "|".join(LAYOUT_SHAPES) + ")$"
#: One of :data:`app.core.task_type_gallery.GALLERY`'s keys.
_GALLERY_PATTERN = "^(" + "|".join(GALLERY_BY_KEY) + ")$"

#: How many checklist lines a type may start a task with.
MAX_STARTING_CHECKLIST = 50

_ChecklistLine = Annotated[MentionStr, Field(min_length=1, max_length=2000)]


class TaskTypeStartingValues(SanitizedBaseModel):
    """What a new task of a type starts with, field by field, where whoever
    makes it leaves that field empty. A repeat starts only on a task with a
    date to count from."""

    description: RichMentionStr | None = None
    checklist: list[_ChecklistLine] = Field(
        default_factory=list, max_length=MAX_STARTING_CHECKLIST
    )
    priority: TaskPriority | None = None
    recurrence: TaskRule | None = None
    recurrence_strategy: RecurrenceStrategy | None = None

    def is_empty(self) -> bool:
        return not (
            self.description or self.checklist or self.priority or self.recurrence
        )


class TaskTypeRead(SanitizedBaseModel):
    """One kind of task in a project, and the shape its page is drawn as until
    the page is changed."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    project_id: int
    name: str
    position: int
    is_default: bool
    color: str
    icon: str
    layout_preset: str
    starting_values: TaskTypeStartingValues | None = None


class TaskTypeCreated(TaskTypeRead):
    """A type just added, and the fields it brought from the gallery (the
    initiative's properties it created or reused), for its page to place."""

    field_ids: list[int] = Field(default_factory=list)


class TaskTypeCreate(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=100)
    position: int | None = Field(default=None, ge=0)
    is_default: bool = False
    color: str | None = Field(
        default=None, min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN
    )
    icon: str | None = Field(default=None, min_length=1, max_length=64)
    #: Another of the project's types to start from: its shape, colour and icon
    #: unless given, and its page as it is laid out.
    start_from_type_id: int | None = Field(default=None, gt=0)
    #: One of the gallery's types to start from: its shape, colour and icon
    #: unless given, its starting values, and its fields.
    gallery_key: str | None = Field(default=None, pattern=_GALLERY_PATTERN)
    layout_preset: str | None = Field(default=None, pattern=_SHAPE_PATTERN)
    starting_values: TaskTypeStartingValues | None = None

    @model_validator(mode="after")
    def _one_start(self) -> "TaskTypeCreate":
        if self.start_from_type_id is not None and self.gallery_key is not None:
            raise ValueError("start from one of the project's types or the gallery")
        return self


class TaskTypeUpdate(SanitizedBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    position: int | None = Field(default=None, ge=0)
    is_default: bool | None = None
    color: str | None = Field(
        default=None, min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN
    )
    icon: str | None = Field(default=None, min_length=1, max_length=64)
    layout_preset: str | None = Field(default=None, pattern=_SHAPE_PATTERN)
    #: Null clears them.
    starting_values: TaskTypeStartingValues | None = None


class TaskTypeDeleteRequest(SanitizedBaseModel):
    #: Where its tasks go; the project's default (or, deleting the default, the
    #: first other type) when not given.
    fallback_type_id: int | None = None


class TaskTypeReorderItem(SanitizedBaseModel):
    id: int
    position: int


class TaskTypeReorderRequest(SanitizedBaseModel):
    items: list[TaskTypeReorderItem]


class TaskTypeCopyRequest(SanitizedBaseModel):
    """Copy types from another project: each with its look, its page and its
    starting values. One whose name the project already has is left out."""

    source_project_id: int = Field(gt=0)
    #: Which of its types, in its order; every one when absent.
    type_ids: list[int] | None = Field(default=None, max_length=50)


class TaskTypeGalleryField(SanitizedBaseModel):
    name: str
    type: str


class TaskTypeGalleryEntry(SanitizedBaseModel):
    """One ready-made type, in the reader's language."""

    key: str
    name: str
    hint: str
    icon: str
    color: str
    layout_preset: str
    fields: list[TaskTypeGalleryField]
    starting_values: TaskTypeStartingValues | None = None


class TaskTypeGalleryGroup(SanitizedBaseModel):
    key: str
    name: str
    entries: list[TaskTypeGalleryEntry]
