"""A tool plug-in's rows and items, read and written as its declaration says.

Every tool plug-in's tool and each of its items is one kind
(``app.db.plugin_tools``), and one set of routes serves them all
(``tenant_endpoints/plugin_tools.py``). This is what those routes share:

* **Where a kind's rows are** is the community's tool set's
  (``app.db.tool_rows.locate``); a kind it does not have is not found.
* **Reads and writes** go through the routed session, so the policies a
  built-in tool's rows answer to answer here: the community, the initiative,
  the tool's switch and its install's state, its create permission and its
  sharing. The tool's switch and the reader's rung on the tool are asked here
  first, as a built-in tool's routes ask them, so a refusal names itself.
* **Values** are held to the declaration: a field the table declares, a value
  of its kind (``tool_plugins.value_fits``), a select's options, a person who
  is a member of the community, and a counter within its bounds, which may be
  the row's own fields.
* **A step** moves a counter field in one statement, from the value the
  database holds, so two steps landing together each count.
* **The declaration** a reader is answered is the tool's own block, less
  its layouts and its actions' expressions.
* **An action** runs its ``write`` through the expression evaluator
  declarative plug-ins' actions run through (``declarative.action_change``),
  over the row and the items directly under it, and its change is made as
  the reader's own writes would be: held to the declaration, through the
  routed session, all of it or none.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import InitiativeMessages, KindMessages, ToolPluginMessages
from app.core.tool_set import ToolSet
from app.core.tools import kind_refusal, plugin_kind
from app.db.errors import dbapi_constraint
from app.db.guild_standing import ActorContext, InstallContext
from app.db.plugin_tools import CHECKED_FIELD, NUMBER, NUMBER_LIMIT
from app.db.session import routed_tools
from app.db.tool_rows import Located, ToolRow, load_row, locate, row_of, select_rows
from app.models.platform.guild import GuildMembership
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.schemas.tenant.archive import ToolCan
from app.schemas.tenant.plugin_tool import (
    PluginToolActionRead,
    PluginToolFieldRead,
    PluginToolItemRead,
    PluginToolRead,
    PluginToolRowRead,
    PluginToolValues,
)
from app.schemas.tenant.tag import tag_summaries
from app.schemas.tenant.tool_layout import MAX_PREVIEW_ITEMS
from app.services.export import values as export_values
from app.services.marketplace.declarative import action_change
from app.services.marketplace.tool_plugins import (
    NEVER_EMPTY,
    NUMBER_KINDS,
    RANDOM_COLOR,
    effective_defaults,
    value_fits,
)
from app.services.membership import live_membership_clause
from app.services.permissions import (
    Action,
    DacResource,
    client_access,
    grants_of,
    require_access,
    serialize_grants,
)
from app.services.tenant import content_references, descriptions
from app.services.tenant import search as search_service
from app.services.tenant import tags as tags_service
from app.services.tenant.descriptions import newly_mentioned
from app.services.tenant.initiative_tools import tool_on_in, tool_on_sql
from app.services.tenant.relationships import Endpoint


def located_kind(tools: ToolSet, kind: str) -> Located:
    """Where ``kind``'s rows are, in a community with ``tools``: a tool
    plug-in's tool or one of its items. Anything else is not found."""
    found = locate(tools, kind)
    if found is None:
        raise kind_refusal(kind, KindMessages.NOT_FOUND, 404)
    return found


def declared_fields(located: Located) -> dict[str, Mapping[str, Any]]:
    """The fields ``located``'s table declares, by key."""
    return {field["key"]: field for field in located.declared.get("fields", [])}


def parent_column(located: Located) -> str | None:
    """The column naming the row an item sits under; none for the tool's."""
    return located.hops[0][0] if located.hops else None


def children(located: Located, tools: ToolSet) -> list[Located]:
    """The item tables directly under ``located``'s table."""
    return [
        located_kind(tools, item)
        for item, parent in tools.item_parents.items()
        if parent == located.kind
    ]


def _fields_read(block: Mapping[str, Any]) -> list[PluginToolFieldRead]:
    """A table's fields as a read answers them, validated from a copy: the
    declaration is the community's kept tool set's, and stays as declared."""
    return [
        PluginToolFieldRead.model_validate(copy.deepcopy(field))
        for field in block.get("fields", [])
    ]


def declaration(located: Located) -> PluginToolRead:
    """The tool ``located`` is or sits in, as its plug-in declares it: its
    names, the fields of its rows and its items', which item sits under
    which, and its actions with the fields they ask for, each table named by
    its kind, and the formats its rows export in. Not its layouts, which are
    the app's to draw, nor what an action writes."""
    block = located.tool.declaration

    def kind(key: str) -> str:
        return plugin_kind(key, located.tool.listing_uid)

    return PluginToolRead(
        kind=located.tool.kind,
        key=block["key"],
        name=block["name"],
        instance_name=block["instance_name"],
        icon=block["icon"],
        fields=_fields_read(block),
        items=[
            PluginToolItemRead(
                kind=kind(item["key"]),
                key=item["key"],
                name=item["name"],
                parent=kind(item.get("parent", block["key"])),
                fields=_fields_read(item),
            )
            for item in block.get("items", [])
        ],
        actions=[
            PluginToolActionRead(
                id=action["id"],
                name=action["name"],
                on=kind(action["on"]),
                params=action.get("params", []),
                confirm=action.get("confirm"),
            )
            for action in block.get("actions", [])
        ],
        export_formats=list(located.tool.spec.export_formats or ()),
    )


async def placed_anywhere(
    session: AsyncSession, context: ActorContext, located: Located
) -> bool:
    """Whether ``located``'s tool is on in some initiative the reader
    reaches: one they are in, by the standing's pairs, or for a reader who
    reaches every initiative, any initiative it is on in."""
    kind = located.tool.kind
    if any(pair.endswith(f":{kind}") for pair in context.enabled_tools):
        return True
    if not (context.is_admin or context.pam_read) or kind not in context.open_tools:
        return False
    on = select(Initiative.id).where(tool_on_sql(located.tool))
    return bool(await session.scalar(sa.select(on.exists())))


# --- gates -------------------------------------------------------------------


async def require_on(
    session: AsyncSession, located: Located, initiative_id: int
) -> Initiative:
    """The initiative ``initiative_id`` names, once ``located``'s tool is on in
    it, as a built-in tool's routes ask: its switch on there, and its install
    placed there. A community admin reaches such a tool's rows, and is still
    refused here."""
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    if not await tool_on_in(session, initiative, located.tool):
        raise located.tool.disabled()
    return initiative


async def load_authorized(
    session: AsyncSession,
    context: ActorContext,
    located: Located,
    tools: ToolSet,
    row_id: int,
    *,
    action: Action | None = None,
) -> ToolRow:
    """One row of ``located``'s table, once the reader may take ``action`` on
    it (a read when none): its tool on, and the action among what the request
    may do to the tool it is in. A row the reader does not read is not
    found."""
    row = await load_row(session, located, tools, row_id, for_update=action is not None)
    if row is None:
        raise located.tool.not_found()
    await require_on(session, located, int(row.tool["initiative_id"]))
    require_access(DacResource(located.tool), row, context=context, action=action)
    return row


# --- values ------------------------------------------------------------------


def _invalid(key: str) -> CodedError:
    return CodedError(
        ToolPluginMessages.FIELD_INVALID,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        params={"field": key},
    )


def _column_value(field: Mapping[str, Any], raw: Any) -> Any:
    """``raw`` as ``field``'s column holds it, or a refusal."""
    key, kind = field["key"], field["kind"]
    if raw is None:
        if kind in NEVER_EMPTY or field.get("required"):
            raise _invalid(key)
        return None
    if not value_fits(dict(field), raw):
        raise _invalid(key)
    if kind in (*NUMBER_KINDS, "currency"):
        number = Decimal(str(raw))
        if kind != "currency" and abs(number) > NUMBER_LIMIT:
            raise _invalid(key)
        return number
    if kind == "scale":
        return int(raw)
    if kind == "date":
        return date.fromisoformat(raw)
    if kind == "datetime":
        return datetime.fromisoformat(raw)
    return raw


def _bound(raw: Any, values: Mapping[str, Any]) -> Decimal | None:
    """A counter's bound: a number, or a number field of the row."""
    value = values.get(raw) if isinstance(raw, str) else raw
    return None if value is None else Decimal(str(value))


def _clamped(
    field: Mapping[str, Any], values: Mapping[str, Any], start: Any
) -> Decimal:
    """A counter field's value in ``values``, or ``start``, held to its
    bounds there."""
    counter = field.get("counter") or {}
    count = values.get(field["key"])
    if count is None:
        count = Decimal(str(start))
    low = _bound(counter.get("min"), values)
    high = _bound(counter.get("max"), values)
    if low is not None:
        count = max(count, low)
    if high is not None:
        count = min(count, high)
    return count


def column_values(
    located: Located,
    given: Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The columns a write of ``given`` (declared fields by key) sets, held to
    the declaration: a new row's (``current`` None), with each field's start
    (``effective_defaults``), or a change to a row holding ``current``. A
    counter is held to its bounds whenever it or a field bounding it changes.
    The table's own checks refuse the row as it is written (:func:`update`)."""
    declared = declared_fields(located)
    values: dict[str, Any] = {}
    for key, raw in given.items():
        field = declared.get(key)
        if field is None:
            raise _invalid(key)
        values[key] = _column_value(field, raw)
    starts = effective_defaults(declared.values(), {**(current or {}), **values})
    if current is None:
        # A counter starts as its bounds say, below; a random colour as its
        # column picks it.
        values = {
            **{
                key: _column_value(field, starts[key])
                for key, field in declared.items()
                if field["kind"] != "counter"
                and starts[key] is not None
                and starts[key] != RANDOM_COLOR
            },
            **values,
        }
    merged = {**(current or {}), **values}
    for key, field in declared.items():
        if field["kind"] != "counter":
            continue
        bounds = {
            b for b in (field.get("counter") or {}).values() if isinstance(b, str)
        }
        if current is not None and key not in values and not bounds & values.keys():
            continue
        count = _clamped(field, merged, starts[key])
        if current is None or key in values or count != current.get(key):
            values[key] = merged[key] = count
    return values


def given_values(located: Located, given: PluginToolValues) -> dict[str, Any]:
    """A request's values as one mapping: a person-valued field's from
    ``people``, every other field's from ``fields``."""
    declared = declared_fields(located)
    for key in given.fields:
        if key not in declared or declared[key]["kind"] == "user_reference":
            raise _invalid(key)
    for key in given.people:
        if key not in declared or declared[key]["kind"] != "user_reference":
            raise _invalid(key)
    return {**given.fields, **given.people}


async def require_members(
    session: AsyncSession,
    context: ActorContext,
    located: Located,
    values: Mapping[str, Any],
) -> None:
    """Refuse a person-valued field naming somebody who is not a member of the
    community. An installed plug-in names only the members its references
    resolve to."""
    declared = declared_fields(located)
    named = {
        key: value
        for key, value in values.items()
        if value is not None and declared.get(key, {}).get("kind") == "user_reference"
    }
    if not named:
        return
    if isinstance(context, InstallContext):
        members = set(context.named_members)
    else:
        members = set(
            (
                await session.exec(
                    select(GuildMembership.user_id).where(
                        GuildMembership.guild_id == context.guild_id,
                        col(GuildMembership.user_id).in_(set(named.values())),
                        live_membership_clause(),
                    )
                )
            ).all()
        )
    for key, user_id in named.items():
        if user_id not in members:
            raise _invalid(key)


# --- reading ------------------------------------------------------------------


def _json(value: Any) -> Any:
    """A column's value as JSON carries it."""
    if isinstance(value, Decimal):
        return export_values.number(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def document(located: Located, row: ToolRow) -> dict[str, Any]:
    """A row as an action's expression reads it: its id, name and declared
    fields by key."""
    return {
        "id": row.id,
        "name": row.name,
        **{key: _json(row.values.get(key)) for key in declared_fields(located)},
    }


def _under(located: Located, under: int, *, archived: bool) -> list[Any]:
    """``located``'s live rows under ``under`` (an initiative for the tool's
    rows, the parent row for an item's), archived or not."""
    table = located.table
    column = parent_column(located) or "initiative_id"
    return [
        table.c[column] == under,
        table.c.deleted_at.is_(None),
        table.c.archived_at.isnot(None) if archived else table.c.archived_at.is_(None),
    ]


#: The columns every row has that a list sorts by, beside its declared fields.
_SORTED_COLUMNS = frozenset({"name", "created_at", "updated_at"})


def listed(
    located: Located,
    tools: ToolSet,
    under: int,
    *,
    archived: bool,
    context: ActorContext,
    search: str | None = None,
    tag_ids: Sequence[int] = (),
    sort_by: str | None = None,
    descending: bool = False,
) -> tuple[sa.Select[Any], sa.Select[Any]]:
    """What reads ``located``'s rows under ``under``, and what counts them:
    narrowed to those whose indexed text matches ``search`` and those
    carrying any of ``tag_ids``, as a built-in tool's list narrows, and in
    their own order, or by ``sort_by``, a declared field or one every row has,
    where it names one."""
    table = located.table
    where = _under(located, under, archived=archived)
    record = next(
        (kind for kind in tools.child_kinds if kind.value == located.kind), located.tool
    )
    matched = search_service.tool_search_clause(record, table.c.id, search, context)
    if matched is not None:
        where.append(matched)
    if tag_ids:
        where.append(
            table.c.id.in_(
                tags_service.tagged_entity_ids(
                    tags_service.tag_links(tools)[located.kind],
                    tuple(tag_ids),
                    guild_id=context.guild_id,
                )
            )
        )
    order = [table.c.position, table.c.id]
    if sort_by in _SORTED_COLUMNS or sort_by in declared_fields(located):
        column = table.c[sort_by]
        order = [
            (column.desc() if descending else column.asc()).nulls_last(),
            table.c.id,
        ]
    return (
        select_rows(located, tools).where(*where).order_by(*order),
        select(sa.func.count()).select_from(table).where(*where),
    )


async def rows_under(
    session: AsyncSession,
    located: Located,
    tools: ToolSet,
    under: int,
    *,
    for_update: bool = False,
) -> list[ToolRow]:
    """``located``'s live rows under ``under`` in their order. ``for_update``
    locks every one, in the order of their ids, so two writers that each lock
    a parent's items never wait on each other in turn."""
    table = located.table
    statement = select_rows(located, tools).where(
        *_under(located, under, archived=False)
    )
    if for_update:
        statement = statement.order_by(table.c.id).with_for_update(of=table)
    rows = [row_of(table, found) for found in (await session.exec(statement)).all()]
    return sorted(rows, key=lambda row: (row.position, row.id))


def parent_of(located: Located, tools: ToolSet) -> Located:
    """The table an item's rows sit under: its tool's, or another item's."""
    return located_kind(tools, tools.item_parents[located.kind])


def writing(located: Located) -> Action:
    """What changing a row of ``located``'s table asks of its tool: an edit of
    the tool's own row, and contributing to it for an item, as a task asks of
    its project."""
    return Action.edit if parent_column(located) is None else Action.contribute


async def serialize(
    session: AsyncSession,
    context: ActorContext,
    located: Located,
    rows: Sequence[ToolRow],
) -> list[PluginToolRowRead]:
    """``rows`` of ``located``'s table as a read returns them, with their
    tags, and a tool's row with who it is shared with."""
    parent = parent_column(located)
    ids = [row.id for row in rows]
    grants = await grants_of(session, located.kind, ids) if parent is None else {}
    tags = await tags_service.tags_for(
        session, tags_service.tag_links(routed_tools(session))[located.kind], ids
    )
    declared = declared_fields(located)
    read: list[PluginToolRowRead] = []
    for row in rows:
        values = {key: _json(row.values.get(key)) for key in declared}
        read.append(
            PluginToolRowRead(
                kind=located.kind,
                id=row.id,
                community_id=context.guild_id,
                initiative_id=row.tool["initiative_id"],
                parent_id=row.values[parent] if parent else None,
                name=row.name,
                position=float(row.position),
                fields={
                    key: value
                    for key, value in values.items()
                    if declared[key]["kind"] != "user_reference"
                },
                people={
                    key: value
                    for key, value in values.items()
                    if declared[key]["kind"] == "user_reference"
                },
                comments_enabled=bool(row.tool.get("comments_enabled", True)),
                grants=serialize_grants(grants.get(row.id, []), context=context),
                tags=tag_summaries(tags.get(row.id, [])),
                created_by=row.created_by,
                created_by_kind=row.created_by_kind,
                archived_at=row.archived_at,
                can=ToolCan(**client_access(row, context.user_id, context=context)),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return read


async def previews(
    session: AsyncSession,
    context: ActorContext,
    located: Located,
    tools: ToolSet,
    rows: Sequence[ToolRow],
) -> dict[int, dict[str, list[PluginToolRowRead]]]:
    """What a card shows of what is under each of ``rows``: the first live
    items of each item table directly under its table, in their order, by
    the item table's kind, read for the whole page at once."""
    ids = [row.id for row in rows]
    previewed: dict[int, dict[str, list[PluginToolRowRead]]] = {
        row_id: {} for row_id in ids
    }
    if not ids:
        return previewed
    for child in children(located, tools):
        table = child.table
        parent = table.c[cast(str, parent_column(child))]
        ranked = (
            sa.select(
                table.c.id,
                sa.func.row_number()
                .over(partition_by=parent, order_by=(table.c.position, table.c.id))
                .label("place"),
            )
            .where(
                parent.in_(ids),
                table.c.deleted_at.is_(None),
                table.c.archived_at.is_(None),
            )
            .subquery()
        )
        statement = select_rows(child, tools).where(
            table.c.id.in_(
                sa.select(ranked.c.id).where(ranked.c.place <= MAX_PREVIEW_ITEMS)
            )
        )
        found = [row_of(table, each) for each in (await session.exec(statement)).all()]
        found.sort(key=lambda row: (row.position, row.id))
        for item in await serialize(session, context, child, found):
            previewed[cast(int, item.parent_id)].setdefault(child.kind, []).append(item)
    return previewed


# --- writing ------------------------------------------------------------------


async def _written(session: AsyncSession, table: sa.Table, statement: Any) -> Any:
    """Run a write to ``table``. A row its checks refuse is refused as a value
    of the field the check holds."""
    try:
        return await session.exec(statement)
    except IntegrityError as error:
        fields = {
            c.name: c.info[CHECKED_FIELD]
            for c in table.constraints
            if CHECKED_FIELD in c.info
        }
        field = fields.get(dbapi_constraint(error))
        if field is None:
            raise
        raise _invalid(field) from None


async def insert(
    session: AsyncSession, table: sa.Table, columns: Mapping[str, Any]
) -> int:
    """Add a row to a tool plug-in's ``table``, and its id. A tool's row is
    not read back, as a built-in tool's is not: it is shared with nobody until
    its owner row is written after it."""
    new_id = (
        await session.exec(
            select(sa.func.nextval(sa.func.pg_get_serial_sequence(table.name, "id")))
        )
    ).one()
    await _written(session, table, sa.insert(table).values(id=new_id, **columns))
    return int(new_id)


async def update(
    session: AsyncSession, located: Located, row_id: int, columns: Mapping[str, Any]
) -> None:
    """Write ``columns`` to one row of ``located``'s table, as the reader. A
    row the reader may not change is refused."""
    if not columns:
        return
    table = located.table
    result = await _written(
        session,
        table,
        sa.update(table)
        .where(table.c.id == row_id)
        .values(**columns, updated_at=sa.func.now()),
    )
    if result.rowcount != 1:
        raise located.tool.write_required()


async def write(
    session: AsyncSession,
    located: Located,
    row: ToolRow,
    given: Mapping[str, Any],
    *,
    author: User | None,
    name: str | None = None,
    position: float | None = None,
) -> None:
    """Change ``row`` of ``located``'s table to ``given`` (declared fields by
    key), and its ``name`` and ``position`` where given, held to the
    declaration and made as the reader, and record what its text now points
    at (:func:`text_saved`). The caller has authorized the edit and commits."""
    columns = column_values(located, given, current=dict(row.values))
    if name is not None:
        columns["name"] = name
    if position is not None:
        columns["position"] = Decimal(str(position))
    await update(session, located, row.id, columns)
    await text_saved(
        session,
        located,
        row.id,
        name=name or row.name,
        before=row.values,
        after=columns,
        author=author,
    )


def _term(table: sa.Table, raw: Any) -> sa.ColumnElement[Any] | None:
    """A counter's bound, step or start in SQL: a number, or the column of
    the number field of the row it names; none where it is left out."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return table.c[raw]
    return sa.literal(Decimal(str(raw)), NUMBER)


async def step(
    session: AsyncSession,
    located: Located,
    row_id: int,
    key: str,
    *,
    by: float | None = None,
    down: bool = False,
) -> None:
    """Move the counter field ``key`` of a row of ``located``'s table, as the
    reader: by ``by``, or by its own step (up, or ``down``), held to its
    bounds and to the largest number a counter stores. One statement, so the
    new value is the database's own plus the step, and two steps landing
    together each count; ``GREATEST`` and ``LEAST`` skip an open bound. The
    caller has authorized the edit and commits."""
    field = declared_fields(located).get(key)
    if field is None or field["kind"] != "counter":
        raise _invalid(key)
    table = located.table
    counter = field.get("counter") or {}
    if by is None:
        amount = sa.func.coalesce(
            _term(table, counter.get("step")), sa.literal(Decimal(1), NUMBER)
        )
        if down:
            amount = -amount
    else:
        amount = sa.literal(_column_value({"key": key, "kind": "number"}, by), NUMBER)
    start = _term(table, counter.get("initial"))
    current = sa.func.coalesce(
        table.c[key],
        *([] if start is None else [start]),
        sa.literal(Decimal(0), NUMBER),
    )
    low = _term(table, counter.get("min"))
    high = _term(table, counter.get("max"))
    moved = sa.func.least(
        sa.func.greatest(
            current + amount,
            *([] if low is None else [low]),
            sa.literal(-NUMBER_LIMIT, NUMBER),
        ),
        *([] if high is None else [high]),
        sa.literal(NUMBER_LIMIT, NUMBER),
    )
    await update(session, located, row_id, {key: moved})


def _action(located: Located, action_id: str) -> Mapping[str, Any]:
    key = located.declared["key"]
    for action in located.tool.declaration.get("actions", []):
        if action["id"] == action_id and action["on"] == key:
            return action
    raise CodedError(ToolPluginMessages.ACTION_NOT_FOUND, status.HTTP_404_NOT_FOUND)


def _changes(raw: Any, what: str) -> Mapping[str, Any]:
    """A change's ``set``: values by field key."""
    if not isinstance(raw, Mapping):
        raise _invalid(what)
    return raw


async def run_action(
    session: AsyncSession,
    context: ActorContext,
    located: Located,
    tools: ToolSet,
    row: ToolRow,
    action_id: str,
    given: PluginToolValues,
    *,
    author: User | None,
) -> None:
    """Run the action ``action_id`` declared on ``located``'s table on
    ``row``, which the caller loaded for an edit: evaluate its ``write`` over
    the row and the items directly under it, and make the change it answers,
    each value held to its field, as the reader. The items it reads are
    locked with the row until the caller commits, so a change made beside it
    is not lost under it."""
    action = _action(located, action_id)
    params = given_values(located, given)
    asked = set(action.get("params", []))
    if not params.keys() <= asked:
        raise _invalid(next(iter(params.keys() - asked)))
    column_values(located, params, current=dict(row.values))
    await require_members(session, context, located, params)
    under = children(located, tools)
    items: dict[str, list[ToolRow]] = {}
    for child in under:
        items[child.declared["key"]] = await rows_under(
            session, child, tools, row.id, for_update=True
        )
    change = await action_change(
        action["write"],
        item=document(located, row),
        params=params,
        items={
            key: [document(child, item) for item in items[key]]
            for child in under
            for key in [child.declared["key"]]
        },
    )
    if change is None:
        return
    if not change.keys() <= {"set", "items"}:
        raise _invalid(action_id)
    if "set" in change:
        own = _changes(change["set"], action_id)
        await require_members(session, context, located, own)
        await write(session, located, row, own, author=author)
    by_key = {child.declared["key"]: child for child in under}
    for key, entries in _changes(change.get("items", {}), action_id).items():
        child = by_key.get(key)
        if child is None or not isinstance(entries, list):
            raise _invalid(key)
        held = {item.id: item for item in items[key]}
        for entry in entries:
            if (
                not isinstance(entry, Mapping)
                or entry.keys() != {"id", "set"}
                or type(entry["id"]) is not int
            ):
                raise _invalid(key)
            item = held.get(entry["id"])
            if item is None:
                # An id not under the row changes nothing.
                continue
            values = _changes(entry["set"], key)
            await require_members(session, context, child, values)
            await write(session, child, item, values, author=author)


async def text_saved(
    session: AsyncSession,
    located: Located,
    row_id: int,
    *,
    name: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
    author: User | None,
) -> None:
    """Where ``after`` writes a text field, make the row's ``references``
    edges match its text fields and comments, and tell whoever they newly
    mention, as a description's save does (``descriptions.description_saved``).
    An installed plug-in's write tells nobody, as its description's does not."""
    texts = [
        key
        for key, field in declared_fields(located).items()
        if field["kind"] == "text" and key in after
    ]
    if not texts:
        return
    entity = Endpoint.of(routed_tools(session), located.kind, row_id)
    await content_references.sync_for_entity(
        session,
        entity,
        body=await content_references.own_body(session, entity),
        author_id=author.id if author is not None else None,
    )
    if author is None:
        return
    mentioned: set[int] = set()
    for key in texts:
        mentioned |= newly_mentioned(after[key], (before or {}).get(key))
    if mentioned:
        await descriptions.tell_mentioned(
            session, (located.kind, row_id), mentioned, title=name, author=author
        )


def placed(
    located: Located, initiative_id: int | None, parent_id: int | None
) -> int | None:
    """Where a request puts a row of ``located``'s table: in an initiative
    for the tool's row, under the row it names for an item's. None where it
    names the other, or neither."""
    own, other = (
        (initiative_id, parent_id)
        if parent_column(located) is None
        else (parent_id, initiative_id)
    )
    return own if other is None else None


def refuse_placement() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=ToolPluginMessages.PLACEMENT_INVALID,
    )
