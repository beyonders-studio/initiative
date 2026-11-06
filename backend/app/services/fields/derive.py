"""Read a table's fields off the table.

A model already says almost everything a filter needs to know. A foreign key
names the table it points at, which is what decides the picker — an integer that
references ``users`` is a person, not a number. A SQL ``Enum`` carries its own
values, so a closed vocabulary needs no second copy. A column's SQL type says
whether it orders, and whether it can be compared at all.

So none of that is declared per dataset here. A dataset names its model and the
handful of things a table genuinely cannot say — which columns are a feature's
private state, and which fields are computed rather than stored — and gets the
rest. That is what keeps the second dataset from costing what the first one did.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase

from app.schemas.query import FilterOp
from app.services.fields.spec import (
    MEMBERSHIP,
    ORDERED,
    ControlKind,
    FieldSpec,
    column,
    computed,
)

#: Which picker a reference gets, by the table it references.
#:
#: The one place this is decided, for every dataset: a column referencing
#: ``users`` is filled by a member picker whether it is a task's author, a
#: file's owner, or a column added next year. A reference to anything absent
#: here has no picker, so it is filterable by a stored definition and not
#: offered as a control — the safe default for a table nobody has taught the UI
#: to browse.
FK_CONTROLS: dict[str, ControlKind] = {
    "users": ControlKind.member,
    "projects": ControlKind.project,
    "initiatives": ControlKind.initiative,
    "task_statuses": ControlKind.task_status,
    "task_types": ControlKind.task_type,
    "tasks": ControlKind.task,
    "tags": ControlKind.tag,
    "calendars": ControlKind.calendar,
    "counter_groups": ControlKind.counter_group,
    "metadata_definitions": ControlKind.property,
}

#: Tables a query never names. The guild is settled by the routing, so a column
#: pointing at one says nothing a reader could use and everything they read is
#: already inside it.
_NEVER_NAMED: frozenset[str] = frozenset({"guilds"})

#: Types that carry no filterable value. Structured blobs and binary: there is
#: nothing a comparison operator would mean against them.
_OPAQUE = (JSON, LargeBinary)

#: Types that hold a value but make a poor ordering. Long-form prose sorts
#: alphabetically by its first character, which is never what anybody wanted.
_UNSORTABLE = (Text,)


def _base_type(sql_type: Any) -> Any:
    """The type underneath any decorating wrappers.

    SQLModel gives a plain ``str`` field its own ``AutoString``, which wraps a
    ``String`` rather than subclassing it. Asking the wrapper what it is gets no
    answer, so unwrap first and ask the type that does the storing.
    """
    while isinstance(sql_type, TypeDecorator):
        sql_type = sql_type.impl_instance
    return sql_type


def _referenced_table(col: Any) -> Optional[str]:
    for fk in col.foreign_keys:
        return fk.target_fullname.split(".")[0]
    return None


def control_for(col: Any, *, references: Optional[str] = None) -> Optional[ControlKind]:
    """Which control fills this column, or ``None`` if none can.

    Asked in the order the answers are trustworthy: what a column *references*
    beats what it is stored as, because both a person and a project are stored
    as an integer.

    *references* names the table this column points at where the schema itself
    cannot say — a view records no foreign keys, so a projection of ``users``
    has an ``id`` that is a person and a type that says integer.
    """
    referenced = references or _referenced_table(col)
    if referenced is not None:
        if referenced in _NEVER_NAMED:
            return None
        # A reference the UI cannot browse is still a reference: it reads, it
        # compares, and a query may name it. Only the *control* is missing, and
        # `offer` is what says so — a column that vanished for want of a picker
        # would be a UI fact quietly deciding a data one.
        return FK_CONTROLS.get(referenced, ControlKind.reference)

    sql_type = _base_type(col.type)
    if isinstance(sql_type, _OPAQUE):
        return None
    # Before String: a SQL enum is one, and its values are the point.
    if isinstance(sql_type, SAEnum):
        return ControlKind.select
    if isinstance(sql_type, Boolean):
        return ControlKind.boolean
    if isinstance(sql_type, (DateTime, Date)):
        return ControlKind.date
    if isinstance(sql_type, (Integer, Numeric)):
        return ControlKind.number
    if isinstance(sql_type, String):
        return ControlKind.text
    return None


def options_for(col: Any) -> tuple[str, ...]:
    """A closed vocabulary's values, straight from the column that stores them.

    This is what lets a client offer the real choices without keeping its own
    copy of them — and pick up a new one the migration that adds it.
    """
    sql_type = _base_type(col.type)
    if isinstance(sql_type, SAEnum) and sql_type.enums:
        return tuple(sql_type.enums)
    return ()


def derive_fields(
    model: type[DeclarativeBase],
    *,
    internal: frozenset[str] = frozenset(),
    references: Mapping[str, str] = MappingProxyType({}),
    descending: frozenset[str] = frozenset(),
) -> tuple[FieldSpec, ...]:
    """Everything *model* itself implies: its columns, and its tags.

    *internal* names the columns that are a feature's own state rather than
    anything a reader would filter by — a recurrence rule's strategy and
    counter, say. They stay filterable by a stored definition and are not
    offered as controls, which is the same treatment a column gets when its
    meaning is real but its audience is the code.

    *descending* names the columns whose values read highest first, which an
    enum's declared order cannot say: a list grouped by priority starts with
    the most urgent.

    *references* supplies what a foreign key would have said, for a model over
    something that holds none. It is still a derivation and not a control list:
    it says which table a column points at, and the same rules as everywhere
    else decide what that makes it.
    """
    specs = []
    for col in model.__table__.columns:
        referenced = references.get(col.name)
        control = control_for(col, references=referenced)
        if control is None:
            continue
        specs.append(
            column(
                col.name,
                getattr(model, col.name),
                kind=control,
                # A row's own key names rows: "these rows" is a list of them.
                ops=ORDERED | MEMBERSHIP if col.primary_key else None,
                sortable=not isinstance(_base_type(col.type), _UNSORTABLE)
                and referenced is None
                and _referenced_table(col) is None,
                nullable=bool(col.nullable),
                # A reference with no picker has no control to offer, and a
                # column the feature keeps to itself is not a reader's to pick
                # either. Both stay nameable by a statement.
                offer=col.name not in internal and control is not ControlKind.reference,
                options=options_for(col),
                descending=col.name in descending,
            )
        )
    tags = _tag_field(model)
    return tuple(specs) + ((tags,) if tags is not None else ())


def _tag_field(model: type[DeclarativeBase]) -> Optional[FieldSpec]:
    """The ``tag_ids`` filter, for a model that has tags.

    Nearly everything is taggable and everything taggable binds the same way,
    so no dataset says it has tags: the model's entry in ``TAG_LINKS`` is the
    whole of the difference between one of these and the next. A model with no
    entry gets no tag field, which is the same answer it would have given by
    hand.
    """
    from app.services.tenant.tags import TAG_LINKS, tagged_entity_ids

    link = next(
        (spec for spec in TAG_LINKS.values() if spec.entity is model),
        None,
    )
    if link is None:
        return None

    def resolve_tag_ids(op: Any, value: Any, ctx: Any) -> Any:
        if not value:
            return None
        return link.entity.id.in_(
            tagged_entity_ids(link, tuple(value), guild_id=ctx.guild_id)
        )

    return computed(
        "tag_ids",
        resolve_tag_ids,
        kind=ControlKind.tag,
        ops=frozenset({FilterOp.in_}),
    )
