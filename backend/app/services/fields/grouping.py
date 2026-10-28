"""Group a dataset's rows by one of its fields, as a grouped list shows them.

A grouping says which groups each row is in, the order the groups go in, and
what each is called. None of that is declared per field: it is read off what
the field already says about itself. A reference names the dataset it points
at, which has a name to show and often a position to order by. An enum carries
its values in their order. A tag field, and a custom property, are the same
for every dataset that has them. A field that is a relation away (a task's
assignees) reaches the dataset its kind names through the relation the
dataset declares for it.

A date groups by a bucket of the calendar (its day, week, month, quarter or
year) in the reader's zone, keyed by the bucket's first day.

A row can be in several groups (a task with two tags is listed under both), so
a grouping is not an ordering: :meth:`Grouping.ordered` lists each row under
every group it is in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Optional, TypeVar

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.user_display import display_name
from app.core.user_input_validators import resolve_zone
from app.models.tenant.metadata import MetadataType
from app.schemas.query import DateBucket
from app.schemas.tenant.tool_layout import PROPERTY_FIELD_PREFIX
from app.services.fields.derive import FK_CONTROLS
from app.services.fields.registry import dataset, dataset_names
from app.services.fields.spec import (
    _KIND_ORDER,
    HIDDEN_EVERYWHERE,
    ControlKind,
    Dataset,
    FieldSpec,
    SortContext,
)

Row = TypeVar("Row")

#: The key of the group a row with no value falls into.
NO_GROUP = ""


#: The property types whose values group cleanly, and the ones that group by
#: a bucket of the calendar.
_GROUPING_PROPERTIES = frozenset(
    {
        MetadataType.select,
        MetadataType.multi_select,
        MetadataType.user_reference,
        MetadataType.checkbox,
    }
)
_DATE_PROPERTIES = frozenset({MetadataType.date, MetadataType.datetime})


def property_groups(kind: MetadataType) -> bool:
    """Whether a property of this type groups a list."""
    return kind in _GROUPING_PROPERTIES or kind in _DATE_PROPERTIES


def property_needs_bucket(kind: MetadataType) -> bool:
    return kind in _DATE_PROPERTIES


class GroupingError(ValueError):
    """The field names no grouping this dataset has."""


@dataclass(frozen=True)
class Group:
    """One group a row is in."""

    key: str
    #: What it is called, when that is somebody's text (a tag's name, a
    #: person's); ``None`` for a value the reader's language names (an enum's,
    #: a checkbox's, the empty group).
    label: Optional[str]
    rank: tuple = ()


@dataclass(frozen=True)
class Grouping:
    """The groups of some rows, by one field."""

    #: The field, as the dataset names it, or ``property:<id>``.
    field: str
    #: The property's own name, for a property grouping.
    name: Optional[str]
    groups: dict[int, list[Group]]
    #: Whether a row can have no value, and so the list an empty group, last.
    empty: bool = True
    #: The groups there are whether or not a row is in them: a closed
    #: vocabulary's values (an enum's, a property's options, yes and no).
    values: tuple[Group, ...] = ()

    def _rank(self, group: Group) -> tuple[bool, tuple]:
        empty = group.key == NO_GROUP
        return (empty, () if empty else group.rank)

    def listed(self) -> list[Group]:
        """Every group, in order: those the vocabulary has, those a row is in,
        and the empty group where it can hold a row."""
        found = {group.key: group for group in self.values}
        for held in self.groups.values():
            found.update((group.key, group) for group in held)
        if self.empty:
            found.setdefault(NO_GROUP, Group(NO_GROUP, None))
        return sorted(found.values(), key=self._rank)

    def ordered(
        self, rows: Iterable[Row], id_of: Callable[[Row], int]
    ) -> list[tuple[Group, Row]]:
        """Each row under every group it is in, the groups in their order and
        the rows in each in the order given."""
        by_key: dict[str, tuple[Group, list[Row]]] = {}
        for row in rows:
            for group in self.groups.get(id_of(row)) or [Group(NO_GROUP, None)]:
                by_key.setdefault(group.key, (group, []))[1].append(row)
        return [
            (group, row)
            for key in sorted(by_key, key=lambda key: self._rank(by_key[key][0]))
            for group, held in [by_key[key]]
            for row in held
        ]


class _How(Enum):
    """How a built-in field's rows are put into groups."""

    tag = "tag"
    bucket = "bucket"
    date = "date"
    reference = "reference"
    value = "value"
    relation = "relation"
    reader = "reader"


def _how(ds: Dataset, spec: FieldSpec) -> Optional[_How]:
    """How ``spec`` groups ``ds``'s rows, or ``None`` where its values do not
    group: free text, numbers, and anything a reader is not offered."""
    if spec.buckets:
        return _How.bucket
    if not spec.offer or spec.name in HIDDEN_EVERYWHERE:
        return None
    if spec.groups is not None:
        return _How.reader
    if spec.kind is ControlKind.tag:
        return _How.tag
    if spec.column is not None:
        if _referenced_dataset(spec) is not None:
            return _How.reference
        if spec.kind is ControlKind.date:
            return _How.date
        if spec.kind in (ControlKind.select, ControlKind.boolean):
            return _How.value
        return None
    return _How.relation if _relation_for(ds, spec) is not None else None


def groupable(ds: Dataset, spec: FieldSpec) -> bool:
    """Whether a list of ``ds`` can be grouped by ``spec``."""
    return _how(ds, spec) is not None


def needs_bucket(ds: Dataset, spec: FieldSpec) -> bool:
    """Whether grouping by ``spec`` names a bucket of the calendar."""
    return _how(ds, spec) is _How.date


def describe_groupings(dataset_name: str) -> list[dict[str, Any]]:
    """The fields a list of the dataset groups by, in the order a client
    offers them: a bucketed ordering first (the date window), then by control
    as a filter list orders them."""
    ds = dataset(dataset_name)
    found = [spec for spec in ds.fields if groupable(ds, spec)]
    found.sort(key=lambda spec: (not spec.buckets, _KIND_ORDER[spec.kind], spec.name))
    return [
        {"name": spec.name, "kind": spec.kind.value, "bucket": needs_bucket(ds, spec)}
        for spec in found
    ]


async def group_rows(
    session: AsyncSession,
    dataset_name: str,
    field: str,
    ids: list[int],
    *,
    bucket: Optional[DateBucket] = None,
    tz: Optional[str] = None,
) -> Grouping:
    """The groups each of ``ids`` is in, by ``field`` of the dataset, a date
    by ``bucket`` in the zone ``tz``.

    Raises :class:`GroupingError` for a field that does not group, and for a
    bucket given to anything but a date or left off one.
    """
    ds = dataset(dataset_name)
    if field.startswith(PROPERTY_FIELD_PREFIX):
        return await _by_property(session, ds, field, ids, bucket, tz)
    spec = ds.by_name.get(field)
    how = _how(ds, spec) if spec is not None else None
    if spec is None or how is None or (bucket is not None) != (how is _How.date):
        raise GroupingError(field)
    if how is _How.tag:
        held = await _by_tag(session, ds, ids)
    elif how is _How.bucket:
        held = await _by_bucket(session, ds, spec, ids, tz)
    elif how is _How.date:
        assert bucket is not None
        held = await _by_date(session, ds, spec, ids, bucket, tz)
    elif how is _How.reference:
        referenced = _referenced_dataset(spec)
        assert referenced is not None
        held = await _by_reference(session, ds, spec, referenced, ids)
    elif how is _How.value:
        held = await _by_value(session, ds, spec, ids)
        return Grouping(field, None, held, empty=spec.nullable, values=_values_of(spec))
    elif how is _How.reader:
        assert spec.groups is not None
        held = await spec.groups(session, ids) if ids else {}
    else:
        held = await _by_relation(session, ds, _relation_for(ds, spec), ids)
    # A tag or a relation is a set a row may have none of, as a reader's
    # groups are; a column is empty where it can be null, and a bucket
    # expression always has a value.
    empty = how in (_How.tag, _How.relation, _How.reader) or (
        how is not _How.bucket and spec.nullable
    )
    return Grouping(field, None, held, empty=empty)


def bucket_start(value: date | datetime, bucket: DateBucket, tz: Optional[str]) -> date:
    """The first day of the bucket ``value`` falls in, in the zone ``tz``."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        value = aware.astimezone(resolve_zone(tz)).date()
    if bucket is DateBucket.week:
        return value - timedelta(days=value.weekday())
    if bucket is DateBucket.month:
        return value.replace(day=1)
    if bucket is DateBucket.quarter:
        return value.replace(month=(value.month - 1) // 3 * 3 + 1, day=1)
    if bucket is DateBucket.year:
        return value.replace(month=1, day=1)
    return value


def _date_group(value: Any, bucket: DateBucket, tz: Optional[str]) -> list[Group]:
    if isinstance(value, str):
        try:
            value = (
                datetime.fromisoformat(value)
                if "T" in value
                else date.fromisoformat(value)
            )
        except ValueError:
            return []
    if not isinstance(value, (date, datetime)):
        return []
    start = bucket_start(value, bucket, tz).isoformat()
    return [Group(start, None, (start,))]


async def _by_date(
    session: AsyncSession,
    ds: Dataset,
    spec: FieldSpec,
    ids: list[int],
    bucket: DateBucket,
    tz: Optional[str],
) -> dict[int, list[Group]]:
    rows = await session.exec(
        select(ds.model.id, spec.column).where(ds.model.id.in_(ids))
    )
    return {row_id: _date_group(value, bucket, tz) for row_id, value in rows}


def _dataset_for_table(table: str) -> Optional[Dataset]:
    """The dataset a reference to ``table`` names: the one over that table, or
    the one whose rows are that table's under another name (the guild's
    members are its ``users``)."""
    kind = FK_CONTROLS.get(table)
    for name in dataset_names():
        candidate = dataset(name)
        if getattr(candidate.model, "__tablename__", None) == table:
            return candidate
    for name in dataset_names():
        candidate = dataset(name)
        own = candidate.by_name.get("id")
        if kind is not None and own is not None and own.kind is kind:
            return candidate
    return None


def _referenced_dataset(spec: FieldSpec) -> Optional[Dataset]:
    for fk in getattr(spec.column, "foreign_keys", ()):
        return _dataset_for_table(fk.target_fullname.split(".")[0])
    return None


def _relation_for(ds: Dataset, spec: FieldSpec) -> Any:
    """The one relation that reaches the dataset this field's kind names."""
    tables = [table for table, kind in FK_CONTROLS.items() if kind is spec.kind]
    targets = {
        found.name
        for found in (_dataset_for_table(table) for table in tables)
        if found is not None
    }
    reaching = [relation for relation in ds.relations if relation.dataset in targets]
    return reaching[0] if len(reaching) == 1 else None


def _label_and_rank(model: Any) -> tuple[Any, list[Any]]:
    """What a row of ``model`` is called, and what its groups order by: its
    position where it has one, then that name."""
    label = next(
        getattr(model, name)
        for name in ("display_name", "name", "title")
        if hasattr(model, name)
    )
    position = getattr(model, "position", None)
    return label, [position, label] if position is not None else [label]


def _ranked(label: Any, *rest: Any) -> tuple:
    return tuple(
        value.casefold() if isinstance(value, str) else value
        for value in (*rest, label)
    )


async def _by_reference(
    session: AsyncSession,
    ds: Dataset,
    spec: FieldSpec,
    referenced: Dataset,
    ids: list[int],
) -> dict[int, list[Group]]:
    target = referenced.model
    label, rank = _label_and_rank(target)
    rows = await session.exec(
        select(ds.model.id, target.id, label, *rank[:-1])
        .join(target, target.id == spec.column)
        .where(ds.model.id.in_(ids))
    )
    return {
        row_id: [Group(str(key), name, _ranked(name, *rest))]
        for row_id, key, name, *rest in rows
    }


async def _by_relation(
    session: AsyncSession, ds: Dataset, relation: Any, ids: list[int]
) -> dict[int, list[Group]]:
    hops = [(hop, dataset(hop.dataset).model) for hop in relation.hops]
    target = hops[-1][1]
    label, rank = _label_and_rank(target)
    statement = select(ds.model.id, target.id, label, *rank[:-1])
    previous = ds.model
    for hop, model in hops:
        statement = statement.join(
            model, getattr(previous, hop.left) == getattr(model, hop.right)
        )
        previous = model
    groups: dict[int, list[Group]] = {}
    for row_id, key, name, *rest in await session.exec(
        statement.where(ds.model.id.in_(ids))
    ):
        groups.setdefault(row_id, []).append(
            Group(str(key), name, _ranked(name, *rest))
        )
    return groups


def _values_of(spec: FieldSpec) -> tuple[Group, ...]:
    """An enum's values or yes and no, in the order a list groups them."""
    if spec.kind is ControlKind.boolean:
        order = ["true", "false"]
    else:
        order = list(reversed(spec.options) if spec.descending else spec.options)
    return tuple(Group(key, None, (i,)) for i, key in enumerate(order))


async def _by_value(
    session: AsyncSession, ds: Dataset, spec: FieldSpec, ids: list[int]
) -> dict[int, list[Group]]:
    order = [group.key for group in _values_of(spec)]
    groups: dict[int, list[Group]] = {}
    for row_id, value in await session.exec(
        select(ds.model.id, spec.column).where(ds.model.id.in_(ids))
    ):
        if value is None:
            continue
        key = (
            str(value).lower()
            if isinstance(value, bool)
            else str(getattr(value, "value", value))
        )
        groups[row_id] = [
            Group(key, None, (order.index(key) if key in order else len(order),))
        ]
    return groups


async def _by_bucket(
    session: AsyncSession,
    ds: Dataset,
    spec: FieldSpec,
    ids: list[int],
    tz: Optional[str],
) -> dict[int, list[Group]]:
    assert spec.sort is not None  # buckets are read off the field's ordering
    rows = await session.exec(
        select(ds.model.id, spec.sort(SortContext(tz=tz))).where(ds.model.id.in_(ids))
    )
    return {row_id: [Group(str(value), None, (value,))] for row_id, value in rows}


async def _by_tag(
    session: AsyncSession, ds: Dataset, ids: list[int]
) -> dict[int, list[Group]]:
    from app.services.tenant.tags import spec_for, tags_for

    held = await tags_for(session, spec_for(ds.model), ids)
    return {
        row_id: [Group(str(tag.id), tag.name, _ranked(tag.name)) for tag in tags]
        for row_id, tags in held.items()
    }


async def _by_property(
    session: AsyncSession,
    ds: Dataset,
    field: str,
    ids: list[int],
    bucket: Optional[DateBucket],
    tz: Optional[str],
) -> Grouping:
    from app.services.tenant import metadata as metadata_service

    raw = field.removeprefix(PROPERTY_FIELD_PREFIX)
    property_id = int(raw) if raw.isdigit() else None
    definition = (
        await metadata_service.load_definitions_by_ids(session, [property_id])
        if property_id is not None
        else {}
    ).get(property_id)
    if (
        definition is None
        or not property_groups(definition.type)
        or (bucket is not None) != property_needs_bucket(definition.type)
    ):
        raise GroupingError(field)
    options = [option.get("value") for option in definition.options or []]
    labels = {
        option.get("value"): option.get("label") for option in definition.options or []
    }
    summaries = await metadata_service.summaries_by_id(
        session, metadata_service.link_for(ds.model).target, ids
    )

    def held(row_id: int) -> Any:
        return next(
            (
                summary.value
                for summary in summaries.get(row_id, [])
                if summary.property_id == property_id
            ),
            None,
        )

    def option(value: str) -> Group:
        rank = options.index(value) if value in options else len(options)
        return Group(value, labels.get(value) or value, (rank,))

    groups: dict[int, list[Group]] = {}
    for row_id in ids:
        value = held(row_id)
        if bucket is not None:
            groups[row_id] = _date_group(value, bucket, tz)
        elif definition.type is MetadataType.checkbox:
            key = str(value is True).lower()
            groups[row_id] = [Group(key, None, (key != "true",))]
        elif (
            definition.type is MetadataType.select and isinstance(value, str) and value
        ):
            groups[row_id] = [option(value)]
        elif definition.type is MetadataType.multi_select and isinstance(value, list):
            groups[row_id] = [option(each) for each in value if isinstance(each, str)]
        elif definition.type is MetadataType.user_reference and isinstance(value, dict):
            name = display_name(SimpleNamespace(**value))
            groups[row_id] = [Group(str(value.get("id")), name, _ranked(name))]
    if definition.type is MetadataType.checkbox:
        values = tuple(Group(key, None, (key != "true",)) for key in ("true", "false"))
    elif bucket is None and definition.type is not MetadataType.user_reference:
        values = tuple(option(value) for value in options)
    else:
        values = ()
    return Grouping(
        field,
        definition.name,
        groups,
        # Unchecked is a value of its own, so nothing is in no group.
        empty=definition.type is not MetadataType.checkbox,
        values=values,
    )
