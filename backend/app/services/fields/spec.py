"""What a field *is* — one declaration, read by every surface that names one.

A :class:`FieldSpec` says everything about a field once: how it resolves to SQL,
what kind of value it holds, which operators apply, and which control fills it.
That last one is what lets a filter UI be generic instead of carrying a branch
per field.

It is a *description*, not a second validator. ``apply_filters`` still owns how a
clause is assembled and ``parse_conditions`` still owns the payload limits;
restating either here would mean maintaining them twice.

Nothing in this module imports a model, so it stays cheap to import from
anywhere and a dataset declaration can live beside the thing it describes.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol

from app.core.tools import Tool
from app.schemas.query import FilterOp


class FieldType(str, Enum):
    """What a value *is*, for comparison and formatting.

    Coarser than a SQL type on purpose: a consumer needs to know that a due date
    orders and a title does not, never that one is ``timestamptz`` and the other
    ``varchar(200)``.
    """

    text = "text"
    number = "number"
    date = "date"
    boolean = "boolean"
    #: A closed vocabulary the app owns (priority, status category).
    enum = "enum"
    #: A reference to another row — filtered by id, shown by name.
    reference = "reference"


class ControlKind(str, Enum):
    """Which control fills this field.

    A presentation fact, kept here rather than on the client because it belongs
    to the field: that an assignee is chosen from a member picker is true of the
    field, not of any one screen that offers it.

    **Declared in the order a client lists them** — related controls together,
    free text last. That ordering is read straight off this enum, so adding a
    control in the right place is all there is to placing it.
    """

    #: A closed vocabulary, whose values ride along with the field. One control
    #: for every enum the database already defines, rather than one per list.
    select = "select"
    task_status = "task_status"
    #: One of a project's task types.
    task_type = "task_type"
    #: One task, chosen from the ones in reach. What a row hanging off a task
    #: points back at.
    task = "task"
    member = "member"
    tag = "tag"
    project = "project"
    initiative = "initiative"
    calendar = "calendar"
    counter_group = "counter_group"
    #: An id pointing at something the UI has not been taught to browse. It
    #: reads and it compares, so a query may name it; there is simply no picker,
    #: which is why a field of this kind is never offered as a control.
    reference = "reference"
    #: One of the initiative's custom properties, chosen by name.
    property = "property"
    #: Values only a lookup can enumerate (a custom property's options).
    property_value = "property_value"
    date = "date"
    boolean = "boolean"
    number = "number"
    text = "text"


#: Operator sets, named for what they mean rather than listed at each use.
EQUALITY: frozenset[FilterOp] = frozenset({FilterOp.eq, FilterOp.is_null})
ORDERED: frozenset[FilterOp] = EQUALITY | frozenset(
    {FilterOp.lt, FilterOp.lte, FilterOp.gt, FilterOp.gte}
)
TEXTUAL: frozenset[FilterOp] = EQUALITY | frozenset({FilterOp.ilike})
MEMBERSHIP: frozenset[FilterOp] = EQUALITY | frozenset({FilterOp.in_})

_IN = frozenset({FilterOp.in_})
_EQ = frozenset({FilterOp.eq})
_RANGE = frozenset({FilterOp.lt, FilterOp.lte, FilterOp.gt, FilterOp.gte})


#: What a control offers, and what it holds, by the control it is.
#:
#: Both derived from the kind rather than declared per field: "a member picker
#: is a multi-select of ids referring to people" is true of every member picker,
#: and restating it on each field is the parallel list this module exists to
#: remove. A field's own ``ops`` stays the engine's answer; this is intersected
#: with it, so a control can never offer an operator the engine would refuse.
#:
#: ``project`` is deliberately single-valued: a plain top-level equality on
#: ``project_id`` is the only shape that narrows a request to one project, and
#: the access path reads exactly that shape.
CONTROLS: dict[ControlKind, tuple[FieldType, frozenset[FilterOp]]] = {
    ControlKind.select: (FieldType.enum, _IN),
    ControlKind.task_status: (FieldType.reference, _IN),
    ControlKind.task_type: (FieldType.reference, _IN),
    ControlKind.task: (FieldType.reference, _IN),
    ControlKind.member: (FieldType.reference, _IN),
    ControlKind.tag: (FieldType.reference, _IN),
    ControlKind.project: (FieldType.reference, _EQ),
    ControlKind.initiative: (FieldType.reference, _IN),
    ControlKind.calendar: (FieldType.reference, _IN),
    ControlKind.counter_group: (FieldType.reference, _IN),
    ControlKind.reference: (FieldType.reference, _IN),
    ControlKind.property: (FieldType.reference, _IN),
    ControlKind.property_value: (FieldType.text, _EQ),
    ControlKind.date: (FieldType.date, _RANGE),
    ControlKind.boolean: (FieldType.boolean, _EQ),
    ControlKind.number: (FieldType.number, _EQ | _RANGE),
    ControlKind.text: (FieldType.text, frozenset({FilterOp.ilike})),
}

#: What a field of each type can be compared with, when nothing narrower is
#: declared. The engine's answer, not the control's.
_TYPE_OPS: dict[FieldType, frozenset[FilterOp]] = {
    FieldType.text: TEXTUAL,
    FieldType.number: ORDERED,
    FieldType.date: ORDERED,
    FieldType.boolean: EQUALITY,
    FieldType.enum: MEMBERSHIP,
    FieldType.reference: MEMBERSHIP,
}


@dataclass(frozen=True)
class SortContext:
    """What an ordering needs to know about the request.

    Only the timezone, today — a grouping by "today" has to mean the reader's
    day. Separate from :class:`FieldContext` because a sort genuinely has no
    identity to offer, and inventing one so the types line up is how a resolver
    ends up quietly filtering as user zero.
    """

    tz: Optional[str] = None


@dataclass(frozen=True)
class FieldContext:
    """What a resolver needs that the field itself cannot know.

    Passed per request rather than baked into the declaration, because every one
    of these is a property of *who is asking*.
    """

    guild_id: int
    #: The person asking; ``None`` for an installed plug-in, which is nobody.
    user_id: Optional[int]
    #: Custom property definitions by id, for the fields that dispatch on one.
    property_definitions: Mapping[int, Any] = dataclass_field(default_factory=dict)
    #: The plug-in fields the person may filter by, by field id.
    plugin_fields: Mapping[str, Any] = dataclass_field(default_factory=dict)
    #: IANA timezone, for sorts that group by the reader's local day rather than
    #: the server's. Present here too so one context serves a request that both
    #: filters and orders.
    tz: Optional[str] = None


class Resolver(Protocol):
    """A field that needs more than a column comparison to filter.

    Returns a SQLAlchemy clause, or ``None`` to contribute nothing — which is
    how an empty id list says "this narrows nothing" rather than "match nothing".
    """

    def __call__(self, op: FilterOp, value: Any, ctx: FieldContext) -> Any: ...


class SortExpression(Protocol):
    """A field that orders by something other than a plain column."""

    def __call__(self, ctx: SortContext) -> Any: ...


class GroupReader(Protocol):
    """A field whose groups no column or relation says: given a session and
    the rows' ids, the groups each row is in (``fields.grouping.Group``s)."""

    def __call__(self, session: Any, ids: list[int]) -> Any: ...


@dataclass(frozen=True)
class FieldSpec:
    """One field, described once."""

    name: str
    kind: ControlKind
    ops: frozenset[FilterOp]
    #: The column this field is, when it is one. Mutually exclusive with
    #: ``resolve`` — a field is either a column or a computation, never both.
    column: Optional[Any] = None
    resolve: Optional[Resolver] = None
    #: How this field orders, when it is not simply its column — a grouping
    #: whose expression depends on the reader's timezone, say.
    sort: Optional[SortExpression] = None
    #: Whether a consumer may offer this field for filtering. A column can exist
    #: and still be nobody's business to filter on.
    filterable: bool = True
    #: Whether a consumer may order by it. Off by default: most columns are
    #: filterable and only some are a sensible ordering, and offering a sort
    #: nobody wants is how a field list stops being readable.
    sortable: bool = False
    #: Whether the underlying column admits NULL. Decides whether a control
    #: offers "is empty" at all — asking it of a NOT NULL column is a filter
    #: that can only ever match everything.
    nullable: bool = True
    #: Whether a client offers this field as a control. Off for a field that is
    #: real but is the code's business rather than a reader's. It stays
    #: filterable by a stored definition either way — declared on the field
    #: rather than in a list of names elsewhere, which could name a field that
    #: no longer exists.
    offer: bool = True
    #: The values this field accepts, when it accepts a closed set of them.
    #: Read off the column that stores them, so a client needs no copy.
    options: tuple[str, ...] = ()
    #: Whether its values read highest first: a list grouped by it starts at
    #: the last of ``options`` (the most urgent priority).
    descending: bool = False
    #: Whether what it orders by is a set of groups: a sort expression whose
    #: values a list is grouped into (a task's date window).
    buckets: bool = False
    #: How a list is grouped by it, for a field that is neither a column nor
    #: a declared relation (the task a task is part of).
    groups: Optional[GroupReader] = None

    @property
    def type(self) -> FieldType:
        """What this field holds. A fact about the control that fills it."""
        return CONTROLS[self.kind][0]

    @property
    def offered_ops(self) -> frozenset[FilterOp]:
        """The operators a control offers for this field.

        The control's own set, narrowed to what the engine accepts, plus "is
        empty" only where the column can actually be empty.
        """
        ops = CONTROLS[self.kind][1] & self.ops
        if self.nullable and FilterOp.is_null in self.ops:
            ops = ops | frozenset({FilterOp.is_null})
        return ops

    @property
    def multiple(self) -> bool:
        """Whether the control picks several values at once — which is exactly
        whether it offers ``in_``, rather than a second list saying so."""
        return FilterOp.in_ in self.offered_ops

    def __post_init__(self) -> None:
        if (
            self.column is None
            and self.resolve is None
            and self.sort is None
            and self.groups is None
        ):
            raise ValueError(f"field {self.name!r} declares no way to be used")
        if self.column is not None and self.resolve is not None:
            raise ValueError(f"field {self.name!r} is both a column and a computation")
        if self.filterable and self.column is None and self.resolve is None:
            raise ValueError(f"field {self.name!r} is filterable but cannot filter")
        if self.sortable and self.column is None and self.sort is None:
            raise ValueError(f"field {self.name!r} is sortable but cannot sort")


#: Columns no dataset offers as a filter, by convention rather than per model.
#:
#: Soft-delete, hold, moderation and purge bookkeeping, the surrogate key, the
#: tenant key (a request is already scoped to one guild, so filtering by it
#: narrows nothing), and the drag-ordering float. None of these means anything
#: to somebody building a filter, and every table has them.
HIDDEN_EVERYWHERE: frozenset[str] = frozenset(
    {
        "id",
        "guild_id",
        "position",
        "deleted_at",
        "deleted_by",
        "purge_at",
        "held_at",
        "hold_id",
        # Moderation bookkeeping: a thread a moderator locked, a tombstone.
        "comments_locked_at",
        "removed_at",
        "removed_reason",
        "removal_id",
    }
)

_KIND_ORDER: dict[ControlKind, int] = {kind: i for i, kind in enumerate(ControlKind)}


@dataclass(frozen=True)
class Hop:
    """One join on the way to a related dataset.

    ``left`` is a field of whatever came before — the dataset itself for the
    first hop, the previous hop's dataset after that — and ``right`` is the
    field of this one it is matched against.
    """

    dataset: str
    left: str
    right: str


@dataclass(frozen=True)
class Relation:
    """Another dataset this one can be read alongside, and how to get there.

    Declared rather than written out, so somebody building a query by clicking
    can ask for "tasks, by the person doing them" without writing a join — and
    so the join that is written is one the surface will run, because it is
    built from the same declarations the columns are.

    A relation may pass through a dataset nobody wants to see: a task reaches a
    person through the table that assigns them, which is a hop and not a
    destination.
    """

    #: What a reader calls it, and what a column of it is prefixed with.
    name: str
    hops: tuple[Hop, ...]

    @property
    def dataset(self) -> str:
        """The dataset it arrives at — the last hop's."""
        return self.hops[-1].dataset


@dataclass(frozen=True)
class Dataset:
    """A queryable thing, and the fields it offers.

    ``tool`` names the tool whose **sharing governs** these rows, which is not
    always the tool they are — a task is governed by its project, the same
    answer the sharing gate reaches for. Naming it lets everything the enum
    already derives be derived rather than restated: the default dataset name,
    and in turn the master switch and resource type the gates read off it. Only
    the field list is genuinely per-dataset.

    ``name_override`` is for a dataset whose name is not the tool's plural —
    ``tasks`` under ``Tool.project`` — and is required when there is no tool.
    """

    model: Any
    fields: tuple[FieldSpec, ...]
    tool: Optional[Tool] = None
    #: Overrides the name derived from ``tool``. Required when there is no tool.
    name_override: Optional[str] = None
    #: The datasets this one can be read alongside, by the name a reader uses
    #: for each. Empty means a query about it names it and nothing else.
    relations: tuple[Relation, ...] = ()

    @property
    def by_relation(self) -> dict[str, Relation]:
        return {relation.name: relation for relation in self.relations}

    @property
    def name(self) -> str:
        if self.name_override is not None:
            return self.name_override
        if self.tool is not None:
            return self.tool.plural
        raise ValueError("a dataset needs a tool or a name_override")

    @property
    def by_name(self) -> dict[str, FieldSpec]:
        return {spec.name: spec for spec in self.fields}

    @property
    def offered(self) -> tuple[FieldSpec, ...]:
        """The fields a client offers, in the order it lists them.

        Derived: everything filterable, minus the conventions every dataset
        hides and this one's own additions, minus anything whose control has no
        operator to offer. Ordering comes from the control group, so nobody
        maintains a running list as fields are added.
        """
        candidates = [
            spec
            for spec in self.fields
            if spec.filterable
            and spec.offer
            and spec.name not in HIDDEN_EVERYWHERE
            and spec.offered_ops
        ]
        return tuple(sorted(candidates, key=lambda s: (_KIND_ORDER[s.kind], s.name)))


def column(
    name: str,
    col: Any,
    *,
    kind: ControlKind,
    ops: Optional[frozenset[FilterOp]] = None,
    filterable: bool = True,
    sortable: bool = False,
    nullable: bool = True,
    offer: bool = True,
    options: tuple[str, ...] = (),
    descending: bool = False,
) -> FieldSpec:
    """A field that is a column. ``ops`` defaults to what its type supports."""
    return FieldSpec(
        name=name,
        kind=kind,
        ops=_TYPE_OPS[CONTROLS[kind][0]] if ops is None else ops,
        column=col,
        filterable=filterable,
        sortable=sortable,
        nullable=nullable,
        offer=offer,
        options=options,
        descending=descending,
    )


def computed(
    name: str,
    resolver: Callable[..., Any],
    *,
    kind: ControlKind,
    ops: frozenset[FilterOp],
    filterable: bool = True,
    nullable: bool = False,
    offer: bool = True,
    options: tuple[str, ...] = (),
) -> FieldSpec:
    """A field that needs a subquery, a lookup, or a literal expanded.

    ``ops`` must be exactly what the resolver handles, not what its type could
    in principle support, so that every declared operator produces a clause.
    ``nullable`` says whether "is empty" means something for it — for most
    computed fields it does not.
    """
    return FieldSpec(
        name=name,
        kind=kind,
        ops=ops,
        resolve=resolver,
        filterable=filterable,
        nullable=nullable,
        offer=offer,
        options=options,
    )
