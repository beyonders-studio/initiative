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
* **An action** runs its ``write`` through the expression evaluator
  declarative plug-ins' actions run through (``declarative.action_change``),
  over the row and the items directly under it, and its change is made as
  the reader's own writes would be: held to the declaration, through the
  routed session, all of it or none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.errors import CodedError
from app.core.messages import InitiativeMessages, KindMessages, ToolPluginMessages
from app.core.tool_set import ToolSet
from app.core.tools import kind_refusal
from app.db.guild_standing import ActorContext, InstallContext
from app.db.query import apply_pagination
from app.db.tool_rows import Located, ToolRow, load_row, locate, row_of, select_rows
from app.models.platform.guild import GuildMembership
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant
from app.schemas.tenant.archive import ToolCan
from app.schemas.tenant.plugin_tool import PluginToolRowRead, PluginToolValues
from app.services.marketplace.declarative import action_change
from app.services.marketplace.tool_plugins import (
    NEVER_EMPTY,
    RANDOM_COLOR,
    effective_defaults,
    tool_row_problems,
    value_fits,
)
from app.services.membership import live_membership_clause
from app.services.permissions import (
    Action,
    DacResource,
    client_access,
    require_access,
    serialize_grants,
)
from app.services.tenant import descriptions
from app.services.tenant.descriptions import newly_mentioned
from app.services.tenant.initiative_tools import tool_on

#: The largest number a number or counter field's column holds.
_NUMBER_LIMIT = Decimal(10) ** 10


def located_kind(tools: ToolSet, kind: str) -> Located:
    """Where ``kind``'s rows are, in a community with ``tools``: a tool
    plug-in's tool or one of its items. Anything else is not found."""
    found = locate(tools, kind)
    if found is None:
        raise kind_refusal(kind, KindMessages.NOT_FOUND, 404)
    return found


def _key(kind: str) -> str:
    return kind.partition(".")[0]


def _table_block(located: Located) -> Mapping[str, Any]:
    """What the declaration says of ``located``'s table: the tool's block, or
    its item's."""
    block = located.tool.declaration
    key = _key(located.kind)
    if key == block["key"]:
        return block
    return next(item for item in block.get("items", []) if item["key"] == key)


def declared_fields(located: Located) -> dict[str, Mapping[str, Any]]:
    """The fields ``located``'s table declares, by key."""
    return {field["key"]: field for field in _table_block(located).get("fields", [])}


def parent_column(located: Located) -> str | None:
    """The column naming the row an item sits under; none for the tool's."""
    return located.hops[0][0] if located.hops else None


def children(located: Located, tools: ToolSet) -> list[Located]:
    """The item tables directly under ``located``'s table."""
    block = located.tool.declaration
    key = _key(located.kind)
    uid = located.tool.kind.partition(".")[2]
    return [
        located_kind(tools, f"{item['key']}.{uid}")
        for item in block.get("items", [])
        if item.get("parent", block["key"]) == key
    ]


# --- gates -------------------------------------------------------------------


async def require_on(
    session: AsyncSession, context: ActorContext, located: Located, initiative_id: int
) -> Initiative:
    """The initiative ``initiative_id`` names, once ``located``'s tool is on in
    it, as a built-in tool's routes ask: a community admin reaches a switched
    off tool's rows, and is still refused here."""
    initiative = await session.get(Initiative, initiative_id)
    if initiative is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    if not tool_on(context, initiative, located.tool):
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
    await require_on(session, context, located, int(row.tool["initiative_id"]))
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
        if kind in NEVER_EMPTY:
            raise _invalid(key)
        return None
    if not value_fits(dict(field), raw):
        raise _invalid(key)
    if kind in ("number", "counter", "currency"):
        number = Decimal(str(raw))
        if kind != "currency" and abs(number) >= _NUMBER_LIMIT:
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
    counter is held to its bounds whenever it or a field bounding it changes,
    and the row as it would be stored to its required fields and checks
    (``tool_row_problems``)."""
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
    for key, _ in tool_row_problems(_table_block(located), merged):
        raise _invalid(key)
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
        return int(value) if value == value.to_integral_value() else float(value)
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


async def rows_under(
    session: AsyncSession,
    located: Located,
    tools: ToolSet,
    under: int,
    *,
    archived: bool = False,
    page_number: int | None = None,
    page_size: int = 0,
    for_update: bool = False,
) -> list[ToolRow]:
    """``located``'s rows under ``under`` in their order: every one, or the
    page ``page_number`` names, windowed as every list is. ``for_update``
    locks every one, in the order of their ids, so two writers that each lock
    a parent's items never wait on each other in turn."""
    table = located.table
    statement = select_rows(located, tools).where(
        *_under(located, under, archived=archived)
    )
    if for_update:
        statement = statement.order_by(table.c.id).with_for_update(of=table)
    else:
        statement = statement.order_by(table.c.position, table.c.id)
    if page_number is not None:
        statement = apply_pagination(statement, page_number, page_size)
    rows = [row_of(table, found) for found in (await session.exec(statement)).all()]
    return sorted(rows, key=lambda row: (row.position, row.id))


async def count_under(
    session: AsyncSession, located: Located, under: int, *, archived: bool
) -> int:
    """How many of ``located``'s rows :func:`rows_under` lists."""
    where = _under(located, under, archived=archived)
    return int(
        (
            await session.exec(
                select(sa.func.count()).select_from(located.table).where(*where)
            )
        ).one()
    )


async def grants_of(
    session: AsyncSession, kind: str, ids: Sequence[int]
) -> dict[int, list[ResourceGrant]]:
    """Who each of a tool's rows ``ids`` is shared with, by id."""
    grants: dict[int, list[ResourceGrant]] = {}
    if not ids:
        return grants
    for grant in (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == kind,
                col(ResourceGrant.resource_id).in_(ids),
            )
        )
    ).all():
        grants.setdefault(grant.resource_id, []).append(grant)
    return grants


def parent_of(located: Located, tools: ToolSet) -> Located:
    """The table an item's rows sit under: its tool's, or another item's."""
    _column, table = located.hops[0]
    if table == located.tool.table.name:
        return located_kind(tools, located.tool.kind)
    (kind,) = (child.value for child in located.tool.children if child.table == table)
    return located_kind(tools, kind)


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
    """``rows`` of ``located``'s table as a read returns them: a tool's row
    with who it is shared with."""
    parent = parent_column(located)
    grants = (
        await grants_of(session, located.kind, [row.id for row in rows])
        if parent is None
        else {}
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
                grants=serialize_grants(
                    SimpleNamespace(grants=grants.get(row.id, [])), context=context
                ),
                created_by=row.created_by,
                created_by_kind=row.created_by_kind,
                archived_at=row.archived_at,
                can=ToolCan(**client_access(row, context.user_id, context=context)),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return read


# --- writing ------------------------------------------------------------------


async def insert(
    session: AsyncSession, located: Located, columns: Mapping[str, Any]
) -> int:
    """Add a row of ``located``'s table, and its id. A tool's row is not read
    back, as a built-in tool's is not: it is shared with nobody until its
    owner row is written after it."""
    table = located.table
    new_id = (
        await session.exec(
            select(sa.func.nextval(sa.func.pg_get_serial_sequence(table.name, "id")))
        )
    ).one()
    await session.exec(sa.insert(table).values(id=new_id, **columns))
    return int(new_id)


async def update(
    session: AsyncSession, located: Located, row_id: int, columns: Mapping[str, Any]
) -> None:
    """Write ``columns`` to one row of ``located``'s table, as the reader. A
    row the reader may not change is refused."""
    if not columns:
        return
    table = located.table
    result = await session.exec(
        sa.update(table)
        .where(table.c.id == row_id)
        .values(**columns, updated_at=sa.func.now())
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
    declaration and made as the reader, and tell whoever its text now newly
    mentions. The caller has authorized the edit and commits."""
    columns = column_values(located, given, current=dict(row.values))
    if name is not None:
        columns["name"] = name
    if position is not None:
        columns["position"] = Decimal(str(position))
    await update(session, located, row.id, columns)
    await tell_mentioned(
        session,
        located,
        row.id,
        name=name or row.name,
        before=row.values,
        after=columns,
        author=author,
    )


def _action(located: Located, action_id: str) -> Mapping[str, Any]:
    key = _key(located.kind)
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
        items[_key(child.kind)] = await rows_under(
            session, child, tools, row.id, for_update=True
        )
    change = await action_change(
        action["write"],
        item=document(located, row),
        params=params,
        items={
            key: [document(child, item) for item in items[key]]
            for child in under
            for key in [_key(child.kind)]
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
    by_key = {_key(child.kind): child for child in under}
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


async def tell_mentioned(
    session: AsyncSession,
    located: Located,
    row_id: int,
    *,
    name: str,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
    author: User | None,
) -> None:
    """Tell whoever ``after``'s text fields newly mention, as a description's
    save does (``descriptions.tell_mentioned``). An installed plug-in's write
    tells nobody, as its description's does not."""
    if author is None:
        return
    mentioned: set[int] = set()
    for key, field in declared_fields(located).items():
        if field["kind"] == "text" and key in after:
            mentioned |= newly_mentioned(after[key], (before or {}).get(key))
    if mentioned:
        await descriptions.tell_mentioned(
            session, (located.kind, row_id), mentioned, title=name, author=author
        )


async def carried(
    session: AsyncSession,
    located: Located,
    tools: ToolSet,
    source: ToolRow,
    copy_id: int,
) -> None:
    """Copy the items under ``source`` to sit under its copy ``copy_id``, and
    theirs under theirs: their names, places and declared fields."""
    for child in children(located, tools):
        for row in await rows_under(session, child, tools, source.id):
            made = await insert(
                session,
                child,
                {
                    cast(str, parent_column(child)): copy_id,
                    "name": row.name,
                    **copy_columns(child, row),
                },
            )
            await carried(session, child, tools, row, made)


def copy_columns(located: Located, row: ToolRow) -> dict[str, Any]:
    """What a copy of ``row`` takes from it beside its name and where it sits:
    its place among its siblings, its declared fields, and a tool's comment
    switch."""
    keep = ["position", *declared_fields(located)]
    if parent_column(located) is None:
        keep.append("comments_enabled")
    return {key: row.values[key] for key in keep}


def refuse_placement() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=ToolPluginMessages.PLACEMENT_INVALID,
    )
