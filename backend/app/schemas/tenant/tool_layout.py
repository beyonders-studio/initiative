"""Schemas for how an instance of a tool draws its items: its layouts.

A target has one layout of each kind its tool draws: how it lists its items (a
project's table, board and calendar), and how it shows one of them (its task).
A layout says how things are drawn; what a person narrows a list to and how
they sort it are theirs, not the layout's. A list can offer them presets: named
filters (and, for a table, a sort) that a person picks to start from.

A layout is a tree of registered parts: a ``card`` holds what an item shows, a
``stack`` lays its children out, a ``field`` draws one field, ``properties``
draws every property the item carries and ``plugin`` draws one of an installed
plug-in's parts. A detail layout adds ``section`` and the detail's own parts
(a task's status, dates, comments and the rest). The parts, their props, the kinds
and the built-in field ids are ``Literal``s or enums, so the generated client
carries the same vocabulary the renderer keys by. A property's field is named
``property:<definition id>``, so renaming it keeps every layout that shows it;
a plug-in's is ``plugin:<install id>:<metadata key>``.

A preset holds its tool's filter shape: ``TaskFilterSpec`` on a project's
lists, ``CalendarFilterSpec`` on the initiative's calendar. Each mirrors what
that list's filter controls show rather than the ``conditions`` DSL its
endpoint accepts, so a preset reads back as controls and a copied project can
remap its status ids.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Union, get_args

from pydantic import AfterValidator, ConfigDict, Field, field_validator, model_validator

from app.core.collection_shapes import RatingDisplay
from app.core.tools import LAYOUT_KIND_TARGETS, Tool
from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.schemas.base import SanitizedBaseModel
from app.schemas.query import DateBucket, FilterOp, SortDir
from app.services.marketplace import contract
from app.services.marketplace.manifest_values import (
    IDENTIFIER_CHARS,
    MAX_IDENTIFIER_LENGTH,
    MAX_METADATA_KEY_LENGTH,
    is_metadata_key,
)
from app.services.tenant.properties import MAX_PROPERTY_FILTERS

#: What one layout may hold. Every part of a tree counts as a
#: node, as does every column.
MAX_NODES = 300
MAX_DEPTH = 6
MAX_DEFINITION_BYTES = 64 * 1024
#: One plug-in's parts on one task: on a card, or across its detail.
MAX_PLUGIN_PARTS = contract.cap("partsPlacedPerItem")
#: Presets on one list.
MAX_PRESETS = 20
#: Groupings one list offers, and the groups one leaves out.
MAX_GROUPINGS = 50
MAX_HIDDEN_GROUPS = 200
#: The most a board column may be limited to, and columns one board limits.
MAX_COLUMN_LIMIT = 10_000
MAX_LIMITED_COLUMNS = 100

# An assignee list holds user ids as strings beside two tokens that mean
# something only when the list is read: "me" is whoever reads it, "none" a task
# with no assignee. That is what makes a preset, and a link to it, mean the
# same for everyone.
ASSIGNEE_ME = "me"
ASSIGNEE_NONE = "none"

#: The tokens the due filter uses; ``None`` is any date.
DueToken = Literal["overdue", "today", "7_days", "30_days"]

MAX_STATUS_IDS = 50
MAX_ASSIGNEES = 25
MAX_TAG_IDS = 25
MAX_COMMUNITY_IDS = 50

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_SLUG_LENGTH = 64


class _Strict(SanitizedBaseModel):
    model_config = ConfigDict(extra="forbid")


# -- Filters ------------------------------------------------------------------


class PresetPropertyFilter(_Strict):
    property_id: int
    op: FilterOp = FilterOp.eq
    value: Any = None


class PresetPluginFilter(_Strict):
    """A filter on a plug-in's field, ``plugin:<install id>:<key>``."""

    field: str
    op: FilterOp = FilterOp.eq
    value: Any = None

    @field_validator("field")
    @classmethod
    def _plugin_field(cls, value: str) -> str:
        if not value.startswith(PLUGIN_FIELD_PREFIX):
            raise ValueError("a plug-in field is 'plugin:<id>:<key>'")
        return _named_field(value)


class TaskFilterSpec(_Strict):
    """The task filters a preset holds, the shape every task list filters by.
    Unknown keys are refused."""

    status_ids: List[int] = Field(default_factory=list, max_length=MAX_STATUS_IDS)
    status_categories: List[TaskStatusCategory] = Field(default_factory=list)
    #: The project's task types, by id.
    type_ids: List[int] = Field(default_factory=list, max_length=MAX_STATUS_IDS)
    priorities: List[TaskPriority] = Field(default_factory=list)
    #: Only a list that holds several communities' tasks narrows by them.
    community_ids: List[int] = Field(default_factory=list, max_length=MAX_COMMUNITY_IDS)
    assignees: List[str] = Field(default_factory=list, max_length=MAX_ASSIGNEES)
    tag_ids: List[int] = Field(default_factory=list, max_length=MAX_TAG_IDS)
    properties: List[PresetPropertyFilter] = Field(
        default_factory=list, max_length=MAX_PROPERTY_FILTERS
    )
    plugins: List[PresetPluginFilter] = Field(
        default_factory=list, max_length=MAX_PROPERTY_FILTERS
    )
    due: Optional[DueToken] = None
    include_archived: bool = False

    @field_validator("assignees")
    @classmethod
    def _validate_assignees(cls, value: List[str]) -> List[str]:
        for entry in value:
            if entry not in (ASSIGNEE_ME, ASSIGNEE_NONE) and not entry.isdigit():
                raise ValueError("assignees entries must be a user id, 'me', or 'none'")
        return value

    @field_validator("status_categories", "priorities")
    @classmethod
    def _dedupe(cls, value: List[Any]) -> List[Any]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _field_filters_within_limit(self) -> "TaskFilterSpec":
        # Property and plug-in filters share one limit, as a task list does.
        if len(self.properties) + len(self.plugins) > MAX_PROPERTY_FILTERS:
            raise ValueError(
                f"at most {MAX_PROPERTY_FILTERS} property and plug-in filters"
            )
        return self


class CalendarFilterSpec(_Strict):
    """The filters a preset on the initiative's calendar holds: what its tasks
    are, and the properties its events and tasks carry."""

    status_categories: List[TaskStatusCategory] = Field(default_factory=list)
    priorities: List[TaskPriority] = Field(default_factory=list)
    properties: List[PresetPropertyFilter] = Field(
        default_factory=list, max_length=MAX_PROPERTY_FILTERS
    )

    @field_validator("status_categories", "priorities")
    @classmethod
    def _dedupe(cls, value: List[Any]) -> List[Any]:
        return list(dict.fromkeys(value))


# -- Fields -------------------------------------------------------------------


class TaskFieldId(str, Enum):
    """A task's built-in fields, by the ids the renderer keys them by. An enum
    rather than a ``Literal`` so the generated client names the set."""

    title = "title"
    #: Which of the project's task types it is: its icon, or its icon and name.
    type = "type"
    description = "description"
    assignees = "assignees"
    startDate = "startDate"
    dueDate = "dueDate"
    recurrence = "recurrence"
    checklist = "checklist"
    priority = "priority"
    comments = "comments"
    blockers = "blockers"
    tags = "tags"


class FileFieldId(str, Enum):
    """A file's own fields, as a collection's lists show them."""

    name = "name"
    #: What kind of file it is.
    type = "type"
    size = "size"
    #: When it was added to the collection.
    added = "added"
    created = "created"


class EventDetailFieldId(str, Enum):
    """What an event's detail edits as a field. Its dates, its properties and
    your answer are parts of their own."""

    title = "title"
    description = "description"
    location = "location"
    recurrence = "recurrence"
    attendees = "attendees"
    tags = "tags"


class QueueItemDetailFieldId(str, Enum):
    """What a queue item's detail edits as a field. What is linked to it, and
    what can be done with it, are parts of their own."""

    label = "label"
    notes = "notes"
    position = "position"
    color = "color"
    visible = "visible"
    person = "person"
    tags = "tags"


class CounterDetailFieldId(str, Enum):
    """What a counter's detail edits as a field. Its count, what is linked to
    it and what can be done with it are parts of their own."""

    name = "name"
    color = "color"
    min = "min"
    max = "max"
    step = "step"
    start = "start"
    view = "view"


class PostDetailFieldId(str, Enum):
    """What a notice's detail draws as a field. Its title, tags and properties
    are its tool's, in its header; what it says, asks and answers, and when it
    goes up, are parts of their own."""

    tags = "tags"


PROPERTY_FIELD_PREFIX = "property:"
PLUGIN_FIELD_PREFIX = "plugin:"
#: The characters a row id is written in.
_DIGITS = frozenset("0123456789")
#: A row id is a Postgres ``integer``: at most ten digits.
_MAX_ID_DIGITS = 10
#: The longest field id a layout names: a plug-in's, ``plugin:<install>:<key>``.
MAX_FIELD_ID_LENGTH = (
    len(PLUGIN_FIELD_PREFIX) + _MAX_ID_DIGITS + 1 + MAX_METADATA_KEY_LENGTH
)


def _is_row_id(value: str) -> bool:
    return (
        0 < len(value) <= _MAX_ID_DIGITS
        and set(value) <= _DIGITS
        and not value.startswith("0")
    )


def _named_field(value: str) -> str:
    """``property:<definition id>`` or ``plugin:<install id>:<metadata key>``.
    By id rather than by name, so renaming a property keeps every layout that
    shows it."""
    if value.startswith(PROPERTY_FIELD_PREFIX):
        if _is_row_id(value.removeprefix(PROPERTY_FIELD_PREFIX)):
            return value
    elif value.startswith(PLUGIN_FIELD_PREFIX):
        install, _, key = value.removeprefix(PLUGIN_FIELD_PREFIX).partition(":")
        if _is_row_id(install) and is_metadata_key(key):
            return value
    raise ValueError(
        "a field is a built-in field id, 'property:<id>' or 'plugin:<id>:<key>'"
    )


def _property_field(value: str) -> str:
    """``property:<definition id>``."""
    if value.startswith(PROPERTY_FIELD_PREFIX) and _is_row_id(
        value.removeprefix(PROPERTY_FIELD_PREFIX)
    ):
        return value
    raise ValueError("a property's field is 'property:<id>'")


NamedFieldId = Annotated[str, AfterValidator(_named_field)]
PropertyFieldId = Annotated[str, AfterValidator(_property_field)]
CardFieldId = Union[TaskFieldId, FileFieldId, NamedFieldId]


#: The characters a built-in field's name is written in.
_FIELD_NAME = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def _grouping_field(value: str) -> str:
    """A built-in field's name, or ``property:<id>``. Whether the list's
    items can be grouped by it is the field registry's answer, asked when the
    layout is written."""
    if value.startswith(PROPERTY_FIELD_PREFIX):
        if _is_row_id(value.removeprefix(PROPERTY_FIELD_PREFIX)):
            return value
    elif 0 < len(value) <= 64 and set(value) <= _FIELD_NAME:
        return value
    raise ValueError("a grouping is a field's name or 'property:<id>'")


#: What a list is grouped by: a field of what it lists, or a custom property.
GroupingField = Annotated[str, AfterValidator(_grouping_field)]


# The built-in fields each place draws, named for the generated client.
_COLUMNS = {
    "title",
    "type",
    "assignees",
    "startDate",
    "dueDate",
    "priority",
    "tags",
    "comments",
}
_PAGE = {
    "title",
    "type",
    "description",
    "assignees",
    "checklist",
    "priority",
    "recurrence",
    "tags",
}

#: What a table draws as a column: the rest of a task (its checklist, how it
#: repeats) sits in the title's cell.
TaskColumnFieldId = Enum(
    "TaskColumnFieldId",
    {f.name: f.value for f in TaskFieldId if f.value in _COLUMNS},
    type=str,
)
#: What a task's layout edits as a field, beside a property or a plug-in's.
#: Its status and its dates are parts of their own, and its counts are a
#: card's.
TaskDetailFieldId = Enum(
    "TaskDetailFieldId",
    {f.name: f.value for f in TaskFieldId if f.value in _PAGE},
    type=str,
)
ColumnFieldId = Union[TaskColumnFieldId, FileFieldId, NamedFieldId]
DetailFieldId = Union[
    TaskDetailFieldId,
    EventDetailFieldId,
    QueueItemDetailFieldId,
    CounterDetailFieldId,
    PostDetailFieldId,
    NamedFieldId,
]


def _part_id(value: str) -> str:
    """One of a plug-in's parts, by the id its manifest gives it."""
    if not 0 < len(value) <= MAX_IDENTIFIER_LENGTH or not set(value) <= set(
        IDENTIFIER_CHARS
    ):
        raise ValueError("a part is named by its manifest id")
    return value


# -- Parts --------------------------------------------------------------------


class StackProps(_Strict):
    direction: Optional[Literal["column", "row"]] = None
    gap: Optional[Literal["xs", "sm"]] = None
    wrap: Optional[bool] = None
    #: Items keep their own width rather than filling the column.
    align: Optional[Literal["start"]] = None
    tone: Optional[Literal["muted"]] = None


class FieldProps(_Strict):
    field: CardFieldId


class CardPart(_Strict):
    type: Literal["card"]
    children: List[CardChild] = Field(default_factory=list)


class StackPart(_Strict):
    type: Literal["stack"]
    props: Optional[StackProps] = None
    children: List[CardChild] = Field(default_factory=list)


class FieldPart(_Strict):
    type: Literal["field"]
    props: FieldProps


class PropertiesPart(_Strict):
    """Every property the item carries, in its own order."""

    type: Literal["properties"]


class PluginPartProps(_Strict):
    #: The install, as the community's plug-in routes name it.
    plugin: int = Field(gt=0)
    part: Annotated[str, AfterValidator(_part_id)]


class PluginPart(_Strict):
    """One of an installed plug-in's parts, drawn as its manifest builds it.
    A part the install no longer declares draws nothing."""

    type: Literal["plugin"]
    props: PluginPartProps


CardChild = Annotated[
    Union[CardPart, StackPart, FieldPart, PropertiesPart, PluginPart],
    Field(discriminator="type"),
]

CardPart.model_rebuild()
StackPart.model_rebuild()


class DetailFieldProps(_Strict):
    field: DetailFieldId


class DetailFieldPart(_Strict):
    type: Literal["field"]
    props: DetailFieldProps


class SectionProps(_Strict):
    #: The initiative's own words, drawn as written.
    title: Optional[str] = Field(default=None, max_length=100)
    #: Drawn folded until the reader opens it.
    collapsed: Optional[bool] = None


class SectionPart(_Strict):
    """A bordered group of a detail layout's parts."""

    type: Literal["section"]
    props: Optional[SectionProps] = None
    children: List[DetailPart] = Field(default_factory=list)


class DetailStackPart(_Strict):
    type: Literal["stack"]
    props: Optional[StackProps] = None
    children: List[DetailPart] = Field(default_factory=list)


#: The parts a detail draws as its own, which edit or show more than one
#: field: a task's status, who made it, its read-only notice, its case and its
#: comments; an event's answer; a picture itself, where it came from and its
#: versions; a counter's count; a notice's body, schedule, reactions and poll;
#: and any item's dates, menu and relations. Which of them a kind of
#: detail draws is ``app.services.tenant.tool_layouts.DETAIL_PARTS``.
OwnPartType = Literal[
    "status",
    "dates",
    "byline",
    "notice",
    "actions",
    "relations",
    "case",
    "comments",
    "rsvp",
    "count",
    "body",
    "schedule",
    "reactions",
    "poll",
]


class OwnPart(_Strict):
    """One of a detail's own parts."""

    type: OwnPartType


DetailPart = Annotated[
    Union[
        DetailStackPart,
        SectionPart,
        DetailFieldPart,
        PropertiesPart,
        PluginPart,
        OwnPart,
    ],
    Field(discriminator="type"),
]

SectionPart.model_rebuild()
DetailStackPart.model_rebuild()


# -- Definitions --------------------------------------------------------------

#: Every way a layout can list a tool's items; which of them a tool draws is
#: ``app.core.tools.LIST_LAYOUTS``.
ListLayoutKind = Literal[
    "table", "board", "gantt", "calendar", "masonry", "grid", "timeline"
]
#: Every kind of thing a detail layout shows one of; which a tool holds is
#: ``app.core.tools.DETAIL_LAYOUTS``.
DetailLayoutKind = Literal["task", "calendar_event", "queue_item", "counter", "post"]


#: What a table can be sorted by, as the task list takes it.
TaskSortField = Literal[
    "title",
    "due_date",
    "start_date",
    "date_group",
    "priority",
    "status_position",
    "tag_name",
]


class PresetSort(_Strict):
    field: TaskSortField
    dir: SortDir = SortDir.asc


class LayoutPreset(_Strict):
    """Filters, and for a table a sort, that a person can pick to start from.
    Picking one makes them that person's own."""

    #: Left out for a shipped preset no one renamed, which each reader sees
    #: named in their own language.
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    #: What a link to the preset carries; kept when it is renamed.
    slug: str = Field(min_length=1, max_length=MAX_SLUG_LENGTH, pattern=SLUG_PATTERN)
    #: Its tool's shape, which the service holds it to.
    filters: Union[TaskFilterSpec, CalendarFilterSpec] = Field(
        default_factory=TaskFilterSpec
    )
    sort: List[PresetSort] = Field(
        default_factory=list, max_length=len(get_args(TaskSortField))
    )


class LayoutGrouping(_Strict):
    """One way a list offers to group its tasks, and the groups it leaves out
    while grouped by it."""

    field: GroupingField
    #: For a date, the bucket of the calendar it groups by.
    bucket: Optional[DateBucket] = None
    #: Each by its key: a status's, a person's or a tag's id, an option, a
    #: bucket's first day, or "" for the tasks with none.
    hidden: List[Annotated[str, Field(max_length=MAX_SLUG_LENGTH)]] = Field(
        default_factory=list, max_length=MAX_HIDDEN_GROUPS
    )


class ColumnLimit(_Strict):
    """How many open tasks one board column takes from a person."""

    status_id: int
    limit: int = Field(ge=1, le=MAX_COLUMN_LIMIT)


class ListLayoutDefinition(_Strict):
    """How a list draws its items, and the presets and groupings it offers.
    What it leaves out is drawn as shipped: a board with no ``card`` draws the
    shipped card, a table with no ``columns`` the shipped columns, a list with
    no ``presets`` the shipped presets and none with no ``groupings`` every
    field of what it lists that groups without a bucket."""

    card: Optional[CardPart] = None
    columns: Optional[List[ColumnFieldId]] = None
    presets: Optional[List[LayoutPreset]] = Field(default=None, max_length=MAX_PRESETS)
    groupings: Optional[List[LayoutGrouping]] = Field(
        default=None, max_length=MAX_GROUPINGS
    )
    #: What everyone starts grouped by, one of the groupings the list offers;
    #: none starts ungrouped. A person's own choice is kept over it.
    group_by: Optional[GroupingField] = None
    #: A board's columns that take at most so many open tasks.
    limits: Optional[List[ColumnLimit]] = Field(
        default=None, max_length=MAX_LIMITED_COLUMNS
    )
    #: Left out of the list's menu; none keeps what its tool ships.
    hidden: Optional[bool] = None
    #: How each rating it shows is drawn, by the field's ``property:<id>``: a
    #: collection's lists only. A rating with none is drawn as a number.
    displays: Optional[Dict[PropertyFieldId, RatingDisplay]] = Field(
        default=None, max_length=MAX_NODES
    )

    @model_validator(mode="after")
    def _offers_what_it_starts_on(self) -> "ListLayoutDefinition":
        # With no groupings of its own, what a list offers is the registry's
        # answer, which the write checks against.
        offered = [grouping.field for grouping in self.groupings or ()]
        if len(set(offered)) != len(offered):
            raise ValueError("each grouping is offered once")
        if (
            self.groupings is not None
            and self.group_by is not None
            and self.group_by not in offered
        ):
            raise ValueError("a list starts grouped by a grouping it offers")
        limited = [entry.status_id for entry in self.limits or ()]
        if len(set(limited)) != len(limited):
            raise ValueError("each column is limited once")
        return self

    @field_validator("presets")
    @classmethod
    def _one_preset_per_slug(
        cls, value: Optional[List[LayoutPreset]]
    ) -> Optional[List[LayoutPreset]]:
        slugs = [preset.slug for preset in value or ()]
        if len(set(slugs)) != len(slugs):
            raise ValueError("each preset needs its own slug")
        return value


class DetailLayoutDefinition(_Strict):
    """How one task (or event) is shown on its own, in three regions, each its
    parts in order. A region it leaves out is drawn as shipped; what it places
    nowhere is not shown."""

    header: Optional[List[DetailPart]] = None
    main: Optional[List[DetailPart]] = None
    side: Optional[List[DetailPart]] = None


# -- Requests -----------------------------------------------------------------


class ListLayoutWrite(_Strict):
    kind: ListLayoutKind
    definition: ListLayoutDefinition


class DetailLayoutWrite(_Strict):
    kind: DetailLayoutKind
    #: The type of task a project's task page is for; required there, and
    #: nowhere else.
    task_type_id: Optional[int] = Field(default=None, gt=0)
    definition: DetailLayoutDefinition


#: One layout as it is changed.
ToolLayoutWrite = Annotated[
    Union[ListLayoutWrite, DetailLayoutWrite], Field(discriminator="kind")
]


class ToolLayoutDefaultWrite(_Strict):
    """The list a target opens on."""

    kind: ListLayoutKind


# -- Responses ----------------------------------------------------------------


class ListLayoutRead(SanitizedBaseModel):
    """One way a target lists its items: as shipped until it is changed."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: ListLayoutKind
    #: Whether the target opens on it.
    is_default: bool
    #: Whether its menu leaves it out.
    hidden: bool = False
    definition: ListLayoutDefinition
    #: When it was last changed; None as shipped.
    updated_at: Optional[datetime] = None


class DetailLayoutRead(SanitizedBaseModel):
    """How a target shows one of its items: as shipped until it is changed."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: DetailLayoutKind
    #: The type of task a project's task page is for, and its name; None for
    #: every other detail.
    task_type_id: Optional[int] = None
    task_type_name: Optional[str] = None
    definition: DetailLayoutDefinition
    #: When it was last changed; None as shipped.
    updated_at: Optional[datetime] = None


#: One of a target's layouts.
ToolLayoutRead = Annotated[
    Union[ListLayoutRead, DetailLayoutRead], Field(discriminator="kind")
]


#: What a request names a set of layouts by: any tool, or a kind inside one
#: that lays out what it holds. Which of them have layouts is
#: ``app.core.tools.LAYOUT_TARGETS``; the others are refused by name.
LayoutTarget = Enum(
    "LayoutTarget",
    {value: value for value in (*(t.value for t in Tool), *LAYOUT_KIND_TARGETS)},
    type=str,
)
LayoutTarget.__doc__ = "What a set of layouts is for."


class ToolLayoutSetRead(SanitizedBaseModel):
    """A target's layouts, one of each kind its tool draws: its lists, then its
    items, in the order the tool names them."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    layouts: List[ToolLayoutRead]
    #: Whether this reader may change them, computed server-side.
    can_configure: bool


class InitiativeToolLayoutsRead(ToolLayoutSetRead):
    """One instance's layouts, as its initiative's list of them shows them."""

    tool: Tool
    tool_id: int
    #: The instance's own name.
    name: str
