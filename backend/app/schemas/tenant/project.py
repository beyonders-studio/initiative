from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict, Field
from sqlalchemy import inspect as sa_inspect

from app.core.identity_boundary import PersonId
from app.schemas.base import (
    RichMentionStr,
    SanitizedBaseModel,
    TitleStr,
    reject_null,
)
from app.schemas.platform.user import UserPublic
from app.schemas.query import PageMeta
from app.schemas.tenant.archive import ToolCan
from app.schemas.tenant.initiative import InitiativeSummary
from app.schemas.tenant.ownership import OwnerPluginSummary, owner_profile
from app.schemas.tenant.property import PropertiesOnCreate
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.task_status import TaskStatusRead
from app.schemas.tenant.task_type import TaskTypeRead
from app.schemas.tenant.tool import ToolSummaryBase

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext


# Matches ``Project.icon``'s column width.
PROJECT_ICON_MAX_LENGTH = 8


class ProjectBase(SanitizedBaseModel):
    name: str
    description: RichMentionStr | None = None
    # The emoji shown beside the project's name, bounded to match the column.
    icon: str | None = Field(default=None, max_length=PROJECT_ICON_MAX_LENGTH)
    # Optional whole-day schedule; either end may be set on its own.
    start_date: date | None = None
    end_date: date | None = None


class ProjectCreate(ProjectBase, PropertiesOnCreate):
    name: TitleStr
    initiative_id: int | None = None
    is_template: bool = False
    template_id: int | None = None
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    grants: list[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class ProjectUpdate(SanitizedBaseModel):
    name: TitleStr | None = None
    description: RichMentionStr | None = None
    icon: str | None = Field(default=None, max_length=PROJECT_ICON_MAX_LENGTH)
    is_template: bool | None = None
    pinned: bool | None = None
    # Send ``null`` to clear a date; omit the field to leave it untouched.
    start_date: date | None = None
    end_date: date | None = None

    _required = reject_null("name", "is_template")


class ProjectTaskSummary(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    total: int = 0
    completed: int = 0


class ProjectCan(ToolCan):
    #: Configure the project itself — pin it, set its default view and its
    #: views (``resource_actions``).
    configure: bool = False


class ProjectRead(ProjectBase, ToolSummaryBase):
    # ``validate_by_name`` so ``derived_fields`` can set ``owner``,
    # ``owner_plugin``, ``task_statuses`` and ``task_types`` by name; their aliases keep
    # ``from_attributes`` from reading an ORM relationship.
    model_config = ConfigDict(validate_by_name=True)

    # Who owns the project: the person holding its owner-level grant, or None
    # when nobody does or a plug-in does (``owner_plugin``). ``owner`` carries the
    # same fact with the user attached.
    owner_id: PersonId | None = None
    is_template: bool
    pinned_at: datetime | None = None
    owner: UserPublic | None = Field(default=None, validation_alias="owner_source")
    #: The installed plug-in holding the owner grant, or None when a person owns
    #: the project or nobody does. At most one of ``owner_id`` and this is set.
    owner_plugin: OwnerPluginSummary | None = Field(
        default=None, validation_alias="owner_plugin_source"
    )
    initiative: InitiativeSummary | None = None
    can: ProjectCan = Field(default_factory=ProjectCan)
    task_summary: ProjectTaskSummary = Field(default_factory=ProjectTaskSummary)
    # The project's task statuses (ordered by position), on a read that loaded
    # them — the detail read and a write's answer — so a caller has the status
    # ids it needs to place or move a task. Empty on a list.
    task_statuses: list[TaskStatusRead] = Field(
        default_factory=list, validation_alias="task_statuses_source"
    )
    #: The project's task types by position, on the same reads.
    task_types: list[TaskTypeRead] = Field(
        default_factory=list, validation_alias="task_types_source"
    )

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: int | None
    ) -> dict[str, Any]:
        from app.services.tenant.ownership import owner_plugin_of, owner_user_id_of

        return {
            "can": project_can(row, user_id, context=context),
            "owner_id": owner_user_id_of(row),
            "owner": owner_profile(row),
            "owner_plugin": owner_plugin_of(row),
            "task_statuses": _task_statuses(row),
            "task_types": _task_types(row),
        }


def project_can(
    project: Any, user_id: int | None, *, context: ActorContext
) -> ProjectCan:
    """What the reader may do to the project, configuring it included."""
    from app.services.permissions import Action, allows, client_access

    return ProjectCan(
        **client_access(project, user_id, context=context),
        configure=allows(project, Action.configure),
    )


def _task_statuses(project: Any) -> list[TaskStatusRead]:
    """The project's task statuses by position, or none when the read did not
    load them — a list never does, and reaching for them would lazy-load."""
    if "task_statuses" in sa_inspect(project).unloaded:
        return []
    statuses = sorted(project.task_statuses, key=lambda s: (s.position, s.id or 0))
    return [TaskStatusRead.model_validate(status) for status in statuses]


def _task_types(project: Any) -> list[TaskTypeRead]:
    """The project's task types by position, or none when the read did not
    load them."""
    if "task_types" in sa_inspect(project).unloaded:
        return []
    types = sorted(project.task_types, key=lambda t: (t.position, t.id or 0))
    return [TaskTypeRead.model_validate(task_type) for task_type in types]


class ProjectListResponse(PageMeta):
    items: list[ProjectRead]


class ProjectReorderRequest(SanitizedBaseModel):
    project_ids: list[int] = Field(default_factory=list)
