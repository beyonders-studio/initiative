"""A tool plug-in's rows and items, as its declaration's fields.

One shape serves every tool plug-in's tool and each of its items: the
universal fields every tool row has, and ``fields``, its declared fields by
key, as a JSON object held to the declaration when the request arrives
(``app.services.tenant.plugin_tool_rows``). A value is one of JSON's: a
string (which may mention people, as a description does), a number, a
boolean or a list of option values. A field naming a person
(``user_reference``) sits in ``people`` instead, read as every person is, so
an installed plug-in names them by its references.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import ConfigDict, Field, model_validator

from app.core.identity_boundary import GuildId, PersonId
from app.schemas.base import MentionStr, SanitizedBaseModel, TitleStr, reject_null
from app.schemas.query import PageMeta
from app.schemas.tenant.archive import ToolCan, ToolState
from app.schemas.tenant.created_by import CreatedByRead
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable

#: Its declared fields' values by key, but the ones naming a person.
FieldValues = dict[str, MentionStr | bool | int | float | list[str] | None]
#: Its declared fields naming a person, by key.
PersonValues = dict[str, PersonId | None]


class PluginToolValues(SanitizedBaseModel):
    """Values for a row's declared fields. A null clears one; a counter and a
    checkbox are never empty."""

    fields: FieldValues = Field(default_factory=dict)
    people: PersonValues = Field(default_factory=dict)


class PluginToolRowCreate(PluginToolValues):
    """A new row: of the tool, in the initiative ``initiative_id`` names, or of
    an item, under the row ``parent_id`` names. A field left out starts at its
    default, and a counter at its start."""

    initiative_id: int | None = None
    parent_id: int | None = None
    name: TitleStr = Field(..., min_length=1, max_length=255)
    position: float | None = Field(default=None, allow_inf_nan=False)
    #: The tool's row's initial sharing, as a built-in tool's create takes it.
    #: An item is shared as its tool is, and takes none.
    grants: list[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class PluginToolRowUpdate(PluginToolValues):
    """A change to a row. Only what is sent changes."""

    name: TitleStr | None = Field(default=None, min_length=1, max_length=255)
    position: float | None = Field(default=None, allow_inf_nan=False)

    _required = reject_null("name", "position")


class PluginToolActionRun(PluginToolValues):
    """The answers to an action's ``params``, as values of the fields they
    name."""


class PluginToolStep(SanitizedBaseModel):
    """Move one counter field of a row: by ``by``, a signed amount, or, left
    out, by the field's own step, up, or down where ``down`` says so."""

    #: The key of the counter field to move.
    field: str = Field(..., min_length=1)
    by: float | None = Field(default=None, allow_inf_nan=False)
    down: bool = False

    @model_validator(mode="after")
    def _one_way(self) -> Self:
        if self.by is not None and self.down:
            raise ValueError("by is signed: send it alone, or down alone")
        return self


class PluginToolRowRead(ToolState[ToolCan], CreatedByRead):
    """One row of a tool plug-in's tool or of one of its items."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: str
    id: int
    community_id: GuildId
    #: The initiative it is in: an item's is its tool's.
    initiative_id: int
    #: The row an item sits under; none for the tool's own row.
    parent_id: int | None = None
    name: str
    position: float
    fields: FieldValues
    people: PersonValues
    #: Whether its comment thread is on: an item's follows its tool's.
    comments_enabled: bool = True
    #: Who the tool's row is shared with; an item answers to its tool's.
    grants: list[ResourceGrantSchema] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PluginToolRowList(PageMeta):
    items: list[PluginToolRowRead]


#: Text in each language it is given in, by language code.
LocalizedText = dict[str, str]


class PluginToolOptionRead(SanitizedBaseModel):
    """One option of a select or multi-select field."""

    value: str
    label: LocalizedText
    #: Its colour, a hex ``#rrggbb``, where it declares one.
    color: str | None = None


class PluginToolCounterRead(SanitizedBaseModel):
    """A counter field's bounds, step and start: each a number, or the key of
    a number field of the same row. Left out, a side is open, the step is 1
    and the start is 0."""

    min: str | int | float | None = None
    max: str | int | float | None = None
    step: str | int | float | None = None
    initial: str | int | float | None = None


class PluginToolFieldRead(SanitizedBaseModel):
    """One field a table of the tool declares, by its key in ``fields`` (or
    in ``people``, for a ``user_reference``)."""

    key: str
    name: LocalizedText
    #: The contract's field kind: ``text``, ``number``, ``counter``,
    #: ``select``, ``user_reference`` and the rest.
    kind: str
    #: What a new row holds when nothing is written to it.
    default: str | bool | int | float | list[str] | None = None
    required: bool = False
    #: A select's or a multi-select's options.
    options: list[PluginToolOptionRead] = Field(default_factory=list)
    #: A currency field's currency.
    currency: str | None = None
    #: A counter field's bounds.
    counter: PluginToolCounterRead | None = None


class PluginToolItemRead(SanitizedBaseModel):
    """One item table of the tool: its rows sit under the rows of
    ``parent``."""

    kind: str
    key: str
    name: LocalizedText
    #: The kind its rows sit under: the tool's, or another item's.
    parent: str
    fields: list[PluginToolFieldRead]


class PluginToolActionRead(SanitizedBaseModel):
    """One action of the tool, run on a row of ``on``."""

    id: str
    name: LocalizedText
    #: The kind of the rows it runs on.
    on: str
    #: The fields of that row whose values it asks for when it runs.
    params: list[str] = Field(default_factory=list)
    #: What to ask before it runs, where it asks.
    confirm: LocalizedText | None = None


class PluginToolRead(SanitizedBaseModel):
    """A tool plug-in's tool as it declares it: its names, its own rows'
    fields, its items and its actions. Its layouts are the app's to draw."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: str
    key: str
    name: LocalizedText
    #: What one row of the tool is called.
    instance_name: LocalizedText
    icon: str
    fields: list[PluginToolFieldRead]
    items: list[PluginToolItemRead]
    actions: list[PluginToolActionRead]
