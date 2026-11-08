from pydantic import ConfigDict, Field

from app.models.tenant.task import TaskStatusCategory
from app.schemas.base import SanitizedBaseModel

# Accepts #RGB, #RRGGBB, and #RRGGBBAA — matching the 4/7/9 char lengths the
# model column allows. Keeps arbitrary strings ("red", "notcolor", …) out of
# the database so the swatch renderer never receives garbage.
HEX_COLOR_PATTERN = r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$"


class TaskStatusBase(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: TaskStatusCategory
    position: int = Field(ge=0)
    is_default: bool = False
    color: str = Field(min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN)
    icon: str = Field(min_length=1, max_length=64)


class TaskStatusCreate(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=100)
    category: TaskStatusCategory
    position: int | None = Field(default=None, ge=0)
    is_default: bool = False
    color: str | None = Field(
        default=None, min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN
    )
    icon: str | None = Field(default=None, min_length=1, max_length=64)


class TaskStatusUpdate(SanitizedBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: TaskStatusCategory | None = None
    position: int | None = Field(default=None, ge=0)
    is_default: bool | None = None
    color: str | None = Field(
        default=None, min_length=4, max_length=9, pattern=HEX_COLOR_PATTERN
    )
    icon: str | None = Field(default=None, min_length=1, max_length=64)


class TaskStatusRead(TaskStatusBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    project_id: int


class TaskStatusDeleteRequest(SanitizedBaseModel):
    fallback_status_id: int | None = None


class TaskStatusReorderItem(SanitizedBaseModel):
    id: int
    position: int


class TaskStatusReorderRequest(SanitizedBaseModel):
    items: list[TaskStatusReorderItem]


class InitiativeTaskStatusRead(SanitizedBaseModel):
    """A status column as it appears across one initiative's projects.

    Entries are aggregated by ``(name, category)``, so the same column
    configured in several projects collapses to a single row; ``color`` and
    ``icon`` come from the first project that defines it. ``project_count`` is
    how many of the projects the caller can read carry the column, out of
    ``projects_total``.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    name: str
    category: TaskStatusCategory
    color: str
    icon: str
    project_count: int
    projects_total: int
