from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, List, Literal, Optional, TYPE_CHECKING

from pydantic import AliasChoices, BeforeValidator, ConfigDict, Field, model_validator

from app.core.identity_boundary import GuildId
from app.core.messages import CounterMessages
from app.models.tenant.counter import COUNTER_DIGITS, COUNTER_PLACES, CounterViewMode
from app.schemas.base import MentionStr, SanitizedBaseModel, TitleStr, reject_null
from app.schemas.query import PageMeta
from app.schemas.tenant.property import (
    PropertiesOnCreate,
    PropertySummary,
    annotated_properties,
)
from app.schemas.tenant.resource_grant import ResourceGrantSchema, initiative_readable
from app.schemas.tenant.tool import ToolSummaryBase, from_row

if TYPE_CHECKING:  # pragma: no cover
    from app.db.guild_standing import ActorContext
    from app.models.tenant.counter import Counter, CounterGroup


# ---------------------------------------------------------------------------
# Counter schemas
# ---------------------------------------------------------------------------

#: A number a counter can store. Anything longer is refused here rather than
#: by the database, and nothing is rounded away on the way in.
CounterNumber = Annotated[
    Decimal, Field(max_digits=COUNTER_DIGITS, decimal_places=COUNTER_PLACES)
]


def format_decimal(value: Decimal) -> str:
    """Return a plain decimal string with no exponent and no trailing zeros.

    PostgreSQL's ``Numeric(20, 10)`` round-trips zeros as ``Decimal('0E-10')``,
    which Python's default JSON encoder emits as ``"0E-10"`` — confusing to
    display and parse on the client. ``format(value, "f")`` gives fixed-point
    notation; we then trim trailing zeros after the decimal point but keep
    a single ``"0"`` when there's no integer part.
    """
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


#: A counter's number as a read sends it: plain decimal text
#: (:func:`format_decimal`), never ``Decimal``'s exponent notation.
DecimalText = Annotated[
    str,
    BeforeValidator(lambda v: format_decimal(v) if isinstance(v, Decimal) else v),
]


def _validate_counter_constraints(
    *,
    view_mode: CounterViewMode,
    min_value: Optional[Decimal],
    max_value: Optional[Decimal],
) -> None:
    if view_mode != CounterViewMode.number and (min_value is None or max_value is None):
        raise ValueError(CounterMessages.VIEW_MODE_REQUIRES_BOUNDS)
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ValueError(CounterMessages.MIN_GREATER_THAN_MAX)


class CounterBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    color: Optional[str] = None
    count: CounterNumber = Decimal("0")
    min: Optional[CounterNumber] = None
    max: Optional[CounterNumber] = None
    step: CounterNumber = Decimal("1")
    initial_count: CounterNumber = Decimal("0")
    view_mode: CounterViewMode = CounterViewMode.number
    position: CounterNumber = Decimal("0")

    @model_validator(mode="after")
    def _check(self) -> "CounterBase":
        _validate_counter_constraints(
            view_mode=self.view_mode,
            min_value=self.min,
            max_value=self.max,
        )
        if self.step <= 0:
            raise ValueError(CounterMessages.STEP_MUST_BE_POSITIVE)
        return self


class CounterCreate(CounterBase, PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)


class CounterUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    color: Optional[str] = None
    # ``min``/``max`` are nullable columns — an explicit null clears the bound.
    # The remaining fields back NOT NULL columns, so they refuse a null.
    # ``gt=0`` rejects a provided step
    # of 0/negative with a clean 422. ``position`` allows negatives so a
    # fractional drop-to-front (prev - 1) still validates.
    min: Optional[CounterNumber] = None
    max: Optional[CounterNumber] = None
    step: Optional[CounterNumber] = Field(default=None, gt=0)
    initial_count: Optional[CounterNumber] = None
    view_mode: Optional[CounterViewMode] = None
    position: Optional[CounterNumber] = None

    _required = reject_null("name", "step", "initial_count", "view_mode", "position")


class CounterSetCountRequest(SanitizedBaseModel):
    count: CounterNumber


class CounterStepRequest(SanitizedBaseModel):
    """Move a counter up or down. ``amount`` left out moves it by the counter's
    own ``step``; given, it must be more than nothing, since which way the
    counter goes is ``direction``'s to say."""

    direction: Literal["up", "down"]
    amount: Optional[CounterNumber] = Field(default=None, gt=0)


class CounterSortField(str, Enum):
    name = "name"
    count = "count"


class CounterSortDirection(str, Enum):
    asc = "asc"
    desc = "desc"


class CounterSortRequest(SanitizedBaseModel):
    field: CounterSortField
    direction: CounterSortDirection = CounterSortDirection.asc


class CounterRead(SanitizedBaseModel):
    """Serialized counter. Numeric fields are plain decimal strings (e.g. "0",
    "12.5"), never exponent notation."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    counter_group_id: int
    community_id: GuildId = Field(
        validation_alias=AliasChoices("community_id", "guild_id")
    )
    name: str
    color: Optional[str] = None
    count: DecimalText
    min: Optional[DecimalText] = None
    max: Optional[DecimalText] = None
    step: DecimalText
    initial_count: DecimalText
    view_mode: CounterViewMode
    position: DecimalText
    properties: List[PropertySummary] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Counter Group schemas
# ---------------------------------------------------------------------------


class CounterGroupBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[MentionStr] = None


class CounterGroupCreate(CounterGroupBase, PropertiesOnCreate):
    name: TitleStr = Field(..., min_length=1, max_length=255)
    initiative_id: int
    # Initial sharing — the same grant list the PUT /grants endpoint takes.
    # Defaults to Viewer for all initiative members.
    grants: List[ResourceGrantSchema] = Field(default_factory=initiative_readable)


class CounterGroupUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=255)
    description: Optional[MentionStr] = None

    _required = reject_null("name")


class CounterPreview(SanitizedBaseModel):
    """One counter as a list's card draws it: its name, colour and count."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    name: str
    color: Optional[str] = None
    count: DecimalText


class CounterGroupSummary(CounterGroupBase, ToolSummaryBase):
    """A counter group in a list: the group alone, without its counters —
    unless the list was asked for previews, when its first few come along."""

    preview: Optional[List[CounterPreview]] = None


class CounterGroupListResponse(PageMeta):
    items: List[CounterGroupSummary]


class CounterGroupRead(CounterGroupSummary):
    counters: List[CounterRead] = Field(default_factory=list)

    @classmethod
    def derived_fields(
        cls, row: Any, *, context: ActorContext, user_id: Optional[int]
    ) -> dict[str, Any]:
        counters = sorted(_active_counters(row), key=lambda c: c.position)
        return {
            **super().derived_fields(row, context=context, user_id=user_id),
            "counters": [serialize_counter(c, context=context) for c in counters],
        }


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def serialize_counter(
    counter: "Counter",
    *,
    context: ActorContext,
) -> CounterRead:
    return from_row(
        CounterRead,
        counter,
        guild_id=context.guild_id,
        properties=annotated_properties(counter),
    )


def _active_counters(group: "CounterGroup") -> list:
    counters = getattr(group, "counters", None) or []
    return [c for c in counters if getattr(c, "deleted_at", None) is None]
