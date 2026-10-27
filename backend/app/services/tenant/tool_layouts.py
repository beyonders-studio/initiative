"""How an instance of a tool lists what it holds, and shows one of them: its
layouts, as shipped and as each is changed.

A target is one instance of a tool (a project) or, for a tool the initiative
shares, the initiative itself (its calendar). It has one layout of each kind
its tool draws: each way it lists what it holds, and its detail.
Each is drawn as shipped until it is changed, and stored when it is, on its
own; so is the list the target opens on. A project's lists also hold the
presets they offer.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import TaskTypeMessages, ToolLayoutMessages
from app.core.tools import (
    DETAIL_LAYOUTS,
    LAYOUT_DEFAULT,
    LAYOUT_KIND_TARGETS,
    LISTS_HIDDEN_AS_SHIPPED,
    LIST_LAYOUTS,
    TYPED_DETAILS,
    Tool,
)
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.session import require_guild_context
from app.models.tenant.task import TaskType
from app.models.tenant.tool_layout import ToolLayout
from app.schemas.tenant.tool_layout import (
    ASSIGNEE_ME,
    ASSIGNEE_NONE,
    MAX_DEFINITION_BYTES,
    PLUGIN_FIELD_PREFIX,
    PROPERTY_FIELD_PREFIX,
    MAX_DEPTH,
    MAX_NODES,
    MAX_PLUGIN_PARTS,
    CalendarFilterSpec,
    CardPart,
    DetailLayoutDefinition,
    DetailLayoutRead,
    DetailFieldPart,
    DetailLayoutWrite,
    DetailStackPart,
    CounterDetailFieldId,
    EventDetailFieldId,
    FieldPart,
    FileFieldId,
    PostDetailFieldId,
    QueueItemDetailFieldId,
    ListLayoutDefinition,
    ListLayoutRead,
    ListLayoutWrite,
    PluginPart,
    SectionPart,
    StackPart,
    TaskDetailFieldId,
    TaskFieldId,
    TaskFilterSpec,
    ToolLayoutDefaultWrite,
    ToolLayoutRead,
    ToolLayoutWrite,
)


#: The parts any detail lays out with.
_LAYOUT_PARTS = frozenset({"stack", "section", "field", "properties"})

#: The parts each kind of detail draws. A detail with ``plugin`` draws plug-ins.
DETAIL_PARTS: dict[str, frozenset[str]] = {
    "task": _LAYOUT_PARTS
    | {
        "plugin",
        "status",
        "dates",
        "byline",
        "notice",
        "actions",
        "relations",
        "case",
        "comments",
    },
    "calendar_event": _LAYOUT_PARTS
    | {"plugin", "dates", "rsvp", "actions", "relations"},
    "queue_item": _LAYOUT_PARTS | {"plugin", "actions", "relations"},
    "counter": _LAYOUT_PARTS | {"plugin", "actions", "relations", "count"},
    "post": _LAYOUT_PARTS
    | {
        "plugin",
        "byline",
        "schedule",
        "body",
        "reactions",
        "poll",
        "relations",
        "comments",
    },
    #: A file opened from a collection: its own fields, which it does not
    #: edit, and the collection's fields and the initiative's properties.
    "file": _LAYOUT_PARTS,
}

#: The built-in fields each kind of detail edits.
DETAIL_FIELDS: dict[str, frozenset[str]] = {
    "task": frozenset(field.value for field in TaskDetailFieldId),
    "calendar_event": frozenset(field.value for field in EventDetailFieldId),
    "queue_item": frozenset(field.value for field in QueueItemDetailFieldId),
    "counter": frozenset(field.value for field in CounterDetailFieldId),
    "post": frozenset(field.value for field in PostDetailFieldId),
    "file": frozenset(field.value for field in FileFieldId),
}


@dataclass(frozen=True)
class Target:
    """What a set of layouts is for."""

    #: A ``LAYOUT_TARGETS`` value: a tool, or a kind inside one that lays out
    #: what it holds (a collection).
    tool: str
    #: The instance, or None for the initiative's shared tool.
    tool_id: Optional[int]
    initiative_id: int

    def __post_init__(self) -> None:
        # A Tool member is held as the value it is stored as.
        object.__setattr__(self, "tool", getattr(self.tool, "value", self.tool))


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _of(target: Target) -> tuple[Any, ...]:
    return (
        ToolLayout.initiative_id == target.initiative_id,
        ToolLayout.tool == target.tool,
        col(ToolLayout.tool_id).is_not_distinct_from(target.tool_id),
    )


async def list_rows(session: AsyncSession, target: Target) -> list[ToolLayout]:
    rows = await session.exec(select(ToolLayout).where(*_of(target)))
    return list(rows.all())


async def rows_by_instance(
    session: AsyncSession, initiative_id: int, tool: Tool, tool_ids: list[int]
) -> dict[int, list[ToolLayout]]:
    """The stored rows of several instances of one tool, in one read. An
    instance with nothing stored is absent."""
    if not tool_ids:
        return {}
    rows = await session.exec(
        select(ToolLayout).where(
            ToolLayout.initiative_id == initiative_id,
            ToolLayout.tool == tool.value,
            col(ToolLayout.tool_id).in_(tool_ids),
        )
    )
    found: dict[int, list[ToolLayout]] = {}
    for row in rows.all():
        if row.tool_id is not None:
            found.setdefault(row.tool_id, []).append(row)
    return found


async def item_types(session: AsyncSession, target: Target) -> list[TaskType]:
    """The types of item the target lays out one page each for: a project's
    task types, in order. None for a target that has one page per kind."""
    if target.tool not in TYPED_DETAILS or target.tool_id is None:
        return []
    from app.services.tenant.task_types import list_types

    return await list_types(session, target.tool_id)


async def item_types_by_instance(
    session: AsyncSession, tool: Tool, tool_ids: list[int]
) -> dict[int, list[TaskType]]:
    """:func:`item_types` for several instances of one tool, in one read."""
    if tool not in TYPED_DETAILS or not tool_ids:
        return {}
    rows = await session.exec(
        select(TaskType)
        .where(col(TaskType.project_id).in_(tool_ids))
        .order_by(col(TaskType.position), col(TaskType.id))
    )
    found: dict[int, list[TaskType]] = {}
    for row in rows.all():
        found.setdefault(row.project_id, []).append(row)
    return found


def shown_lists(tool: str, stored: Mapping[str, dict[str, Any]]) -> tuple[str, ...]:
    """The lists a target shows, in order, from the definitions it stores by
    kind: each that its own definition does not hide. As shipped, every list
    shows but those ``LISTS_HIDDEN_AS_SHIPPED`` names."""
    hidden = LISTS_HIDDEN_AS_SHIPPED.get(tool, frozenset())
    return tuple(
        kind
        for kind in LIST_LAYOUTS.get(tool, ())
        if not stored.get(kind, {}).get("hidden", kind in hidden)
    )


def _stored_lists(rows: Iterable[ToolLayout]) -> dict[str, dict[str, Any]]:
    return {row.kind: row.definition for row in rows if row.task_type_id is None}


def _require_one_shown(
    target: Target, rows: list[ToolLayout], kind: str, definition: Optional[dict]
) -> None:
    """A 400 unless the target still shows a list with ``kind`` stored as
    ``definition`` (None: drawn as shipped)."""
    if kind not in LIST_LAYOUTS.get(target.tool, ()):
        return
    stored = _stored_lists(rows)
    stored.pop(kind, None)
    if definition is not None:
        stored[kind] = definition
    if not shown_lists(target.tool, stored):
        raise _bad_request(ToolLayoutMessages.ONE_LIST_SHOWN)


def read_set(
    tool: str, rows: list[ToolLayout], types: Sequence[TaskType] = ()
) -> list[ToolLayoutRead]:
    """Every layout the tool draws, its lists then its details, each as stored
    or as shipped. The target opens on its default list, or on the first. A
    detail laid out per type (:data:`TYPED_DETAILS`) is one per type, in the
    types' order."""
    stored = {row.kind: row for row in rows if row.task_type_id is None}
    typed = {row.task_type_id: row for row in rows if row.task_type_id is not None}
    lists = LIST_LAYOUTS.get(tool, ())
    # A target shows one list at least, whatever was stored.
    shown = shown_lists(tool, _stored_lists(rows)) or lists[:1]
    chosen = stored.get(LAYOUT_DEFAULT)
    default = chosen.definition.get("kind") if chosen is not None else None
    if default not in shown:
        default = shown[0] if shown else None

    def definition(kind: str) -> dict[str, Any]:
        row = stored.get(kind)
        return row.definition if row is not None else {}

    def when(kind: str) -> Optional[datetime]:
        row = stored.get(kind)
        return row.updated_at if row is not None else None

    layouts: list[ToolLayoutRead] = [
        ListLayoutRead(
            kind=kind,
            is_default=kind == default,
            hidden=kind not in shown,
            definition=ListLayoutDefinition.model_validate(definition(kind)),
            updated_at=when(kind),
        )
        for kind in lists
    ]
    for kind in DETAIL_LAYOUTS.get(tool, ()):
        if TYPED_DETAILS.get(tool) != kind:
            layouts.append(
                DetailLayoutRead(
                    kind=kind,
                    definition=DetailLayoutDefinition.model_validate(definition(kind)),
                    updated_at=when(kind),
                )
            )
            continue
        for task_type in types:
            row = typed.get(task_type.id)
            layouts.append(
                DetailLayoutRead(
                    kind=kind,
                    task_type_id=task_type.id,
                    task_type_name=task_type.name,
                    definition=DetailLayoutDefinition.model_validate(
                        row.definition if row is not None else {}
                    ),
                    updated_at=row.updated_at if row is not None else None,
                )
            )
    return layouts


def _parts(part: Any, depth: int) -> Iterable[tuple[Any, int]]:
    """Every part in a tree, with its depth."""
    yield part, depth
    if isinstance(part, (CardPart, StackPart, DetailStackPart, SectionPart)):
        for child in part.children:
            yield from _parts(child, depth + 1)


def _within_limits(stored: dict[str, Any], roots: list[Any], loose: int) -> None:
    """Refuse a layout past the node, depth, size or plug-in part limit.
    ``loose`` is the nodes outside any tree (columns)."""
    parts = [found for root in roots for found in _parts(root, 1)]
    if (
        len(parts) + loose > MAX_NODES
        or max((depth for _, depth in parts), default=0) > MAX_DEPTH
        or len(json.dumps(stored).encode()) > MAX_DEFINITION_BYTES
    ):
        raise _bad_request(ToolLayoutMessages.TOO_LARGE)
    installs = Counter(
        part.props.plugin for part, _ in parts if isinstance(part, PluginPart)
    )
    if any(count > MAX_PLUGIN_PARTS for count in installs.values()):
        raise CodedError(
            ToolLayoutMessages.TOO_MANY_PLUGIN_PARTS,
            params={"max": str(MAX_PLUGIN_PARTS)},
        )


def _drawn_on(part: Any, kind: str) -> bool:
    """Whether a kind of detail draws the part: one of its own parts, or one of
    its fields. A plug-in's field is drawn where its parts are, and a single
    property where its properties are."""
    if part.type not in DETAIL_PARTS[kind]:
        return False
    if not isinstance(part, DetailFieldPart):
        return True
    field = getattr(part.props.field, "value", part.props.field)
    if field.startswith(PLUGIN_FIELD_PREFIX):
        return "plugin" in DETAIL_PARTS[kind]
    if field.startswith(PROPERTY_FIELD_PREFIX):
        return "properties" in DETAIL_PARTS[kind]
    return field in DETAIL_FIELDS[kind]


def _require(kind: str, kinds: tuple[str, ...]) -> None:
    if kind not in kinds:
        raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)


def _typed(target: Target, kind: str) -> bool:
    """Whether the target lays out ``kind`` once per type of item."""
    return TYPED_DETAILS.get(target.tool) == kind


def check(target: Target, write: ToolLayoutWrite) -> dict[str, Any]:
    """A layout's definition as stored, or a 400 naming what is wrong with it.
    What it leaves out is left out, so it is drawn as shipped."""
    definition = write.definition
    # A null is what a read sends for what a layout leaves out, so a layout
    # read and sent back leaves it out too.
    stored = {
        key: value
        for key, value in definition.model_dump(mode="json", exclude_unset=True).items()
        if value is not None
    }
    if isinstance(write, DetailLayoutWrite):
        _require(write.kind, DETAIL_LAYOUTS.get(target.tool, ()))
        if _typed(target, write.kind) != (write.task_type_id is not None):
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
        assert isinstance(definition, DetailLayoutDefinition)
        roots = [
            part
            for region in (definition.header, definition.main, definition.side)
            for part in region or ()
        ]
        _within_limits(stored, roots, 0)
        if not all(
            _drawn_on(part, write.kind) for root in roots for part, _ in _parts(root, 1)
        ):
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
    else:
        _require(write.kind, LIST_LAYOUTS.get(target.tool, ()))
        assert isinstance(definition, ListLayoutDefinition)
        _check_list_fields(target, write.kind, stored, definition)
        _check_presets(target.tool, write.kind, stored.get("presets") or [])
        if write.kind not in GROUPED_LISTS and (
            "groupings" in stored or "group_by" in stored
        ):
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
        if write.kind != "board" and "limits" in stored:
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
        _check_groupings(write.kind, definition)
        _within_limits(
            stored,
            [definition.card] if definition.card is not None else [],
            len(definition.columns or ()),
        )
    return stored


#: The built-in fields a list may show, by what it lists: a collection's files,
#: and every other list's tasks.
_FILE_FIELDS = frozenset(field.value for field in FileFieldId)
_TASK_FIELDS = frozenset(field.value for field in TaskFieldId)
#: The parts a collection's card is made of. A plug-in's parts and fields are
#: drawn on items, which a file is not.
_FILE_CARD_PARTS = frozenset({"card", "stack", "field", "properties"})


def _check_list_fields(
    target: Target, kind: str, stored: dict[str, Any], definition: ListLayoutDefinition
) -> None:
    """Each built-in field a list shows one of what it lists. A collection's
    list holds whether it is shown and what it shows of each file — its table
    its columns, its other lists a card — and how its ratings are drawn."""
    cards = [definition.card] if definition.card is not None else []
    parts = [part for root in cards for part, _ in _parts(root, 1)]
    shown = [
        getattr(field, "value", field)
        for field in (
            *(definition.columns or ()),
            *(part.props.field for part in parts if isinstance(part, FieldPart)),
        )
    ]
    builtin = {
        field
        for field in shown
        if not field.startswith((PROPERTY_FIELD_PREFIX, PLUGIN_FIELD_PREFIX))
    }
    if target.tool not in LAYOUT_KIND_TARGETS:
        if builtin - _TASK_FIELDS:
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
        return
    held = {"hidden", "displays", "columns" if kind == "table" else "card"}
    if (
        set(stored) - held
        or builtin - _FILE_FIELDS
        or any(field.startswith(PLUGIN_FIELD_PREFIX) for field in shown)
        or any(part.type not in _FILE_CARD_PARTS for part in parts)
    ):
        raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)


#: The lists that group their tasks: a project's table, board and Gantt.
GROUPED_LISTS = ("table", "board", "gantt")
#: What a grouped list lists, as the field registry names it.
_GROUPED_DATASET = "tasks"
#: A board's columns are its statuses already, so its bands never are.
_BOARD_COLUMNS = "task_status_id"
#: A task's type, as the field registry names it.
_TYPE_FIELD = "task_type_id"


def _check_groupings(kind: str, definition: ListLayoutDefinition) -> None:
    """Each grouping a field the list's items group by, a date's with its
    bucket and nothing else's with one."""
    from app.services.fields.grouping import describe_groupings

    groupable = {
        entry["name"]: entry["bucket"] for entry in describe_groupings(_GROUPED_DATASET)
    }
    for grouping in definition.groupings or ():
        if _of_property(grouping.field):
            continue
        if grouping.field not in groupable or groupable[grouping.field] != (
            grouping.bucket is not None
        ):
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
    offered = (
        [grouping.field for grouping in definition.groupings]
        if definition.groupings is not None
        else [name for name, bucket in groupable.items() if not bucket]
    )
    if definition.group_by is not None and definition.group_by not in offered:
        raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
    explicit = [grouping.field for grouping in definition.groupings or ()]
    if kind == "board" and _BOARD_COLUMNS in [*explicit, definition.group_by]:
        raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)


#: The filters a tool's presets hold: the shape its list filters by.
PRESET_FILTERS: dict[Tool, type[TaskFilterSpec] | type[CalendarFilterSpec]] = {
    Tool.project: TaskFilterSpec,
    Tool.calendar: CalendarFilterSpec,
}


def _check_presets(tool: str, kind: str, presets: list[dict[str, Any]]) -> None:
    """Refuse presets whose filters are not the tool's shape, or a sort on a
    list other than a table, the one a person sorts by its own."""
    shape = PRESET_FILTERS.get(tool)
    for preset in presets:
        if shape is None or (preset.get("sort") and kind != "table"):
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
        try:
            shape.model_validate(preset.get("filters", {}))
        except ValidationError:
            raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED) from None


async def _locked_rows(session: AsyncSession, target: Target) -> list[ToolLayout]:
    """The target's rows, read once the changes to it before this one are
    done: changes to one target take turns."""
    guild_id = require_guild_context(session).guild_id
    await advisory_lock(
        session,
        LockNamespace.TOOL_LAYOUTS,
        f"{guild_id}:{target.tool}:{target.tool_id}:{target.initiative_id}",
    )
    return await list_rows(session, target)


async def _require_type(
    session: AsyncSession, target: Target, task_type_id: Optional[int]
) -> None:
    """A 404 unless a type named is one of the target's own."""
    if task_type_id is None:
        return
    if task_type_id not in {t.id for t in await item_types(session, target)}:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=TaskTypeMessages.NOT_FOUND,
        )


async def _keep(
    session: AsyncSession,
    target: Target,
    kind: str,
    definition: dict[str, Any],
    task_type_id: Optional[int] = None,
    *,
    rows: Optional[list[ToolLayout]] = None,
) -> None:
    """Store ``definition`` as the target's ``kind`` (for one type of item,
    when it is laid out per type), marking when it changed. The target's other
    rows are not touched. ``rows`` are the target's, read under its lock by a
    caller that checked them first."""
    if rows is None:
        rows = await _locked_rows(session, target)
    row = next(
        (row for row in rows if row.kind == kind and row.task_type_id == task_type_id),
        None,
    )
    if row is None:
        session.add(
            ToolLayout(
                initiative_id=target.initiative_id,
                tool=target.tool,
                tool_id=target.tool_id,
                kind=kind,
                task_type_id=task_type_id,
                definition=definition,
            )
        )
    elif row.definition != definition:
        row.definition = definition
        row.updated_at = datetime.now(timezone.utc)
        session.add(row)
    await session.flush()


async def start(
    session: AsyncSession,
    target: Target,
    lists: Mapping[str, dict[str, Any]],
    default: str,
) -> None:
    """Lay out a target made in this transaction: each of ``lists`` as its
    definition, held to what a write of it would be, opening on ``default``.
    Nothing else can have laid it out yet, so nothing is read first."""
    for kind, definition in lists.items():
        stored = check(
            target,
            ListLayoutWrite.model_validate({"kind": kind, "definition": definition}),
        )
        session.add(
            ToolLayout(
                initiative_id=target.initiative_id,
                tool=target.tool,
                tool_id=target.tool_id,
                kind=kind,
                definition=stored,
            )
        )
    _require(default, shown_lists(target.tool, lists))
    session.add(
        ToolLayout(
            initiative_id=target.initiative_id,
            tool=target.tool,
            tool_id=target.tool_id,
            kind=LAYOUT_DEFAULT,
            definition={"kind": default},
        )
    )
    await session.flush()


async def save(session: AsyncSession, target: Target, write: ToolLayoutWrite) -> None:
    """Change one of the target's layouts, so long as it still shows a list."""
    definition = check(target, write)
    task_type_id = getattr(write, "task_type_id", None)
    await _require_type(session, target, task_type_id)
    rows = await _locked_rows(session, target)
    _require_one_shown(target, rows, write.kind, definition)
    await _keep(session, target, write.kind, definition, task_type_id, rows=rows)


async def save_default(session: AsyncSession, target: Target, kind: str) -> None:
    """Open the target on its ``kind`` list, one it shows."""
    rows = await _locked_rows(session, target)
    _require(kind, shown_lists(target.tool, _stored_lists(rows)))
    await _keep(session, target, LAYOUT_DEFAULT, {"kind": kind}, rows=rows)


async def reset(
    session: AsyncSession,
    target: Target,
    kind: str,
    task_type_id: Optional[int] = None,
) -> None:
    """Draw one of the target's layouts as shipped again: for one type of
    item, when it is laid out per type."""
    _require(
        kind, LIST_LAYOUTS.get(target.tool, ()) + DETAIL_LAYOUTS.get(target.tool, ())
    )
    if _typed(target, kind) != (task_type_id is not None):
        raise _bad_request(ToolLayoutMessages.KIND_NOT_ALLOWED)
    await _require_type(session, target, task_type_id)
    rows = await _locked_rows(session, target)
    _require_one_shown(target, rows, kind, None)
    for row in rows:
        if row.kind == kind and row.task_type_id == task_type_id:
            await session.delete(row)
    await session.flush()


#: A status's, a property's or a row of a tool's id where a layout is written,
#: or None for one that has no counterpart there and is left out.
IdMap = Callable[[int], Optional[int]]

#: The groupings whose groups are the community's people, tags or projects.
_COMMUNITY_GROUPINGS = frozenset(
    {"assignee_ids", "created_by", "tag_ids", "project_id"}
)


@dataclass(frozen=True)
class Remap:
    """What a layout's row ids become where it is written. Statuses are the
    instance's own rows and properties the initiative's, so each goes through
    its map, and one with no counterpart is left out; ``properties`` None keeps
    them as they are, beside the instance. People, tags and plug-in installs
    are the community's, so a layout leaving it (``community`` False) keeps
    none of them: their parts, fields, filters and the groups they name, the
    filters and groups of a person property (``people``, by the ids the layout
    names) among them."""

    statuses: IdMap
    properties: Optional[IdMap] = None
    #: The instance's task types, as its statuses are; None keeps them.
    types: Optional[IdMap] = None
    community: bool = True
    people: frozenset[int] = frozenset()


def remapped_definition(definition: dict[str, Any], remap: Remap) -> dict[str, Any]:
    """``definition`` with its row ids as ``remap`` has them. Only what it
    holds is rewritten, so what it leaves out is still drawn as shipped."""

    def field(value: Any) -> Optional[Any]:
        if _of_property(value):
            if remap.properties is None:
                return value
            mapped = remap.properties(int(value.removeprefix(PROPERTY_FIELD_PREFIX)))
            return None if mapped is None else f"{PROPERTY_FIELD_PREFIX}{mapped}"
        if isinstance(value, str) and value.startswith(PLUGIN_FIELD_PREFIX):
            return value if remap.community else None
        return value

    def nodes(parts: list[Any]) -> list[Any]:
        kept: list[Any] = []
        for node in parts:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "plugin" and not remap.community:
                continue
            node = dict(node)
            if node.get("type") == "field":
                mapped = field((node.get("props") or {}).get("field"))
                if mapped is None:
                    continue
                node["props"] = {**node["props"], "field": mapped}
            if isinstance(node.get("children"), list):
                node["children"] = nodes(node["children"])
            kept.append(node)
        return kept

    def statuses(ids: Iterable[Any]) -> list[int]:
        return [
            mapped
            for old in ids
            if isinstance(old, int) and (mapped := remap.statuses(old)) is not None
        ]

    def filters(spec: dict[str, Any]) -> dict[str, Any]:
        spec = dict(spec)
        if "status_ids" in spec:
            spec["status_ids"] = statuses(spec["status_ids"])
        if "type_ids" in spec and remap.types is not None:
            spec["type_ids"] = [
                mapped
                for old in spec["type_ids"]
                if isinstance(old, int) and (mapped := remap.types(old)) is not None
            ]
        if "properties" in spec:
            spec["properties"] = [
                {
                    **entry,
                    "property_id": int(mapped.removeprefix(PROPERTY_FIELD_PREFIX)),
                }
                for entry in spec["properties"]
                if (remap.community or entry["property_id"] not in remap.people)
                and (mapped := field(f"{PROPERTY_FIELD_PREFIX}{entry['property_id']}"))
            ]
        if not remap.community:
            for key in ("plugins", "tag_ids", "community_ids"):
                if key in spec:
                    spec[key] = []
            if "assignees" in spec:
                spec["assignees"] = [
                    who
                    for who in spec["assignees"]
                    if who in (ASSIGNEE_ME, ASSIGNEE_NONE)
                ]
        return spec

    def hidden(grouping: dict[str, Any]) -> list[str]:
        keys = grouping.get("hidden", [])
        rows = {_BOARD_COLUMNS: remap.statuses, _TYPE_FIELD: remap.types}.get(
            grouping.get("field")
        )
        if rows is not None:
            return [
                str(mapped)
                for key in keys
                if key.isdigit() and (mapped := rows(int(key))) is not None
            ]
        if not remap.community and (
            grouping.get("field") in _COMMUNITY_GROUPINGS
            or _person_property(grouping.get("field"), remap.people)
        ):
            return []
        return keys

    copy = dict(definition)
    for region in ("header", "main", "side"):
        if isinstance(definition.get(region), list):
            copy[region] = nodes(definition[region])
    if isinstance(definition.get("card"), dict):
        [copy["card"]] = nodes([definition["card"]])
    if isinstance(definition.get("columns"), list):
        copy["columns"] = [
            mapped for column in definition["columns"] if (mapped := field(column))
        ]
    if isinstance(definition.get("displays"), dict):
        copy["displays"] = {
            mapped: display
            for key, display in definition["displays"].items()
            if (mapped := field(key))
        }
    if isinstance(definition.get("limits"), list):
        copy["limits"] = [
            {**entry, "status_id": mapped}
            for entry in definition["limits"]
            if (mapped := remap.statuses(entry.get("status_id"))) is not None
        ]
    if isinstance(definition.get("groupings"), list):
        copy["groupings"] = [
            {**grouping, "field": mapped, "hidden": hidden(grouping)}
            for grouping in definition["groupings"]
            if (mapped := field(grouping.get("field")))
        ]
    if "group_by" in definition:
        mapped = field(definition["group_by"])
        if mapped is None:
            copy.pop("group_by")
        else:
            copy["group_by"] = mapped
    if isinstance(definition.get("presets"), list):
        copy["presets"] = [
            {**preset, "filters": filters(preset.get("filters", {}))}
            for preset in definition["presets"]
        ]
    return copy


def _of_property(field: Any) -> bool:
    return isinstance(field, str) and field.startswith(PROPERTY_FIELD_PREFIX)


def _person_property(field: Any, people: frozenset[int]) -> bool:
    return (
        _of_property(field) and int(field.removeprefix(PROPERTY_FIELD_PREFIX)) in people
    )


async def copy_layouts(
    session: AsyncSession,
    source: Target,
    copy: Target,
    *,
    status_mapping: dict[int, int],
    type_mapping: dict[int, int],
    fields: Optional[Mapping[int, int]] = None,
) -> None:
    """Give ``copy`` what ``source`` stored, its presets' statuses and its
    pages' types its own, and a collection's own fields (``fields``, by the
    source's field id) the copy's."""
    same = copy.initiative_id == source.initiative_id
    fields = fields or {}
    for row in await list_rows(session, source):
        if row.task_type_id is not None and row.task_type_id not in type_mapping:
            continue
        session.add(
            ToolLayout(
                initiative_id=copy.initiative_id,
                tool=copy.tool,
                tool_id=copy.tool_id,
                kind=row.kind,
                task_type_id=(
                    type_mapping[row.task_type_id]
                    if row.task_type_id is not None
                    else None
                ),
                definition=remapped_definition(
                    row.definition,
                    Remap(
                        statuses=status_mapping.get,
                        properties=lambda property_id: fields.get(
                            property_id, property_id if same else None
                        ),
                        types=type_mapping.get,
                    ),
                ),
            )
        )
    await session.flush()


@dataclass(frozen=True)
class Restored:
    """A layout an import brings: its kind, its definition with the ids the
    instance has, and the type of item it lays out when it is one of a
    kind's per type (a page whose type is not there is ``None``)."""

    kind: str
    definition: dict[str, Any]
    task_type_id: Optional[int] = None


async def restore_layouts(
    session: AsyncSession, target: Target, layouts: Iterable[Restored]
) -> None:
    """Give a new instance the layouts an import brings, each held to what a
    write of it would be. One that is not, that names a kind its tool does
    not draw, or that is one of a kind's per type without its type, is drawn
    as shipped."""
    lists = LIST_LAYOUTS.get(target.tool, ())
    # Two pages for one type (two of the file's types are one here) keep the
    # first.
    restored: set[tuple[str, Optional[int]]] = set()
    for layout in layouts:
        kind, definition = layout.kind, layout.definition
        task_type_id = layout.task_type_id if _typed(target, kind) else None
        if (kind, task_type_id) in restored:
            continue
        try:
            if kind == LAYOUT_DEFAULT:
                stored = ToolLayoutDefaultWrite.model_validate(definition).model_dump()
                _require(stored["kind"], lists)
            else:
                write = ListLayoutWrite if kind in lists else DetailLayoutWrite
                stored = check(
                    target,
                    write.model_validate(
                        {
                            "kind": kind,
                            "definition": definition,
                            **(
                                {"task_type_id": task_type_id}
                                if write is DetailLayoutWrite
                                else {}
                            ),
                        }
                    ),
                )
        except (HTTPException, CodedError, ValidationError):
            continue
        restored.add((kind, task_type_id))
        session.add(
            ToolLayout(
                initiative_id=target.initiative_id,
                tool=target.tool,
                tool_id=target.tool_id,
                kind=kind,
                task_type_id=task_type_id,
                definition=stored,
            )
        )
    await session.flush()


async def drop_for_instances(
    session: AsyncSession, tool: str, tool_ids: Iterable[int]
) -> None:
    """Remove these instances' layouts, as they are purged."""
    ids = list(tool_ids)
    if ids:
        await session.exec(
            delete(ToolLayout).where(
                ToolLayout.tool == tool, col(ToolLayout.tool_id).in_(ids)
            )
        )


#: The details that draw plug-ins, each named as the kind of item it shows.
PLUGIN_DETAILS = tuple(
    kind for kind, parts in DETAIL_PARTS.items() if "plugin" in parts
)


async def add_to_saved_details(
    session: AsyncSession,
    kind: str,
    initiative_ids: Iterable[int],
    nodes: list[dict[str, Any]],
    *,
    only: Optional[Target] = None,
) -> None:
    """Add parts to the end of the side of every saved ``kind`` detail in these
    initiatives: what a plug-in shows as it arrives. A detail already holding
    one keeps it where it is, a plug-in's parts stop at its limit, and a detail
    the parts would take past its limits is left as it is. A detail not saved
    draws them as shipped. ``only`` keeps to one target's."""
    ids = sorted(set(initiative_ids))
    if not ids or not nodes:
        return
    rows = await session.exec(
        select(ToolLayout)
        .where(
            col(ToolLayout.initiative_id).in_(ids),
            ToolLayout.kind == kind,
            *(_of(only) if only is not None else ()),
        )
        .with_for_update()
    )
    for row in rows.all():
        side = row.definition.get("side")
        if not isinstance(side, list):
            continue
        held = [
            node
            for region in ("header", "main", "side")
            for node in _nodes(row.definition.get(region) or [])
        ]
        placed = {_placed_as(node) for node in held}
        installs = Counter(
            node["props"]["plugin"] for node in held if node.get("type") == "plugin"
        )
        added: list[dict[str, Any]] = []
        for node in nodes:
            if _placed_as(node) in placed:
                continue
            if node["type"] == "plugin":
                install = node["props"]["plugin"]
                if installs[install] >= MAX_PLUGIN_PARTS:
                    continue
                installs[install] += 1
            added.append(node)
        if not added:
            continue
        _rewrite(
            session, row, DetailLayoutWrite, {**row.definition, "side": [*side, *added]}
        )
    await session.flush()


#: The lists that draw a task's fields: a board's card and a table's columns.
TASK_FIELD_LISTS = ("board", "table")


async def add_to_saved_lists(
    session: AsyncSession,
    initiative_ids: Iterable[int],
    fields: list[str],
    *,
    only: Optional[Target] = None,
) -> None:
    """Add a task's fields to the end of every saved board card and table in
    these initiatives: what a plug-in shows as it arrives. A list already
    showing one keeps it where it is, and a list the fields would take past
    its limits is left as it is. A card or columns not saved draw them as
    shipped. ``only`` keeps to one target's."""
    ids = sorted(set(initiative_ids))
    if not ids or not fields:
        return
    rows = await session.exec(
        select(ToolLayout)
        .where(
            col(ToolLayout.initiative_id).in_(ids),
            col(ToolLayout.kind).in_(TASK_FIELD_LISTS),
            *(_of(only) if only is not None else ()),
        )
        .with_for_update()
    )
    for row in rows.all():
        if row.kind == "board":
            card = row.definition.get("card")
            if not isinstance(card, dict):
                continue
            shown = {
                (node.get("props") or {}).get("field")
                for node in _nodes([card])
                if node.get("type") == "field"
            }
            added = [
                {"type": "field", "props": {"field": field}}
                for field in fields
                if field not in shown
            ]
            if added:
                children = [*(card.get("children") or []), *added]
                _rewrite(
                    session,
                    row,
                    ListLayoutWrite,
                    {**row.definition, "card": {**card, "children": children}},
                )
        else:
            columns = row.definition.get("columns")
            if not isinstance(columns, list):
                continue
            added_columns = [field for field in fields if field not in columns]
            if added_columns:
                _rewrite(
                    session,
                    row,
                    ListLayoutWrite,
                    {**row.definition, "columns": [*columns, *added_columns]},
                )
    await session.flush()


def _rewrite(
    session: AsyncSession,
    row: ToolLayout,
    write: type[ListLayoutWrite] | type[DetailLayoutWrite],
    definition: dict[str, Any],
) -> None:
    """Store ``definition`` on ``row``, unless it is not a layout it could hold."""
    target = Target(row.tool, row.tool_id, row.initiative_id)
    try:
        typed = {"task_type_id": row.task_type_id} if row.task_type_id else {}
        check(
            target,
            write.model_validate({"kind": row.kind, **typed, "definition": definition}),
        )
    except (HTTPException, CodedError, ValidationError):
        return
    row.definition = definition
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)


def _placed_as(node: dict[str, Any]) -> tuple[Any, ...]:
    """What a part is placed as: its kind and what it draws."""
    props = node.get("props") or {}
    return (
        node.get("type"),
        props.get("field"),
        props.get("plugin"),
        props.get("part"),
    )


def _nodes(nodes: list[Any]) -> Iterable[dict[str, Any]]:
    """Every part in stored regions, at any depth."""
    for node in nodes:
        if isinstance(node, dict):
            yield node
            yield from _nodes(node.get("children") or [])
