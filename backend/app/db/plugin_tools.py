"""A tool plug-in's tool, built from its declaration.

An installed tool plug-in's ``tool`` block declares a tool: its key, the
fields of its rows, and the item tables under it. This module turns that
declaration into a :class:`~app.core.tool_set.ToolRecord` with SQLAlchemy
tables and no model class, so every renderer of a community's rules reads it
as it reads a built-in tool, and into the DDL that creates its tables.

* **Kinds** are the key, ``.`` and the plug-in's uid in lower case
  (``counter_group.tsjvtcm0s7gv2x``), the tool's and each item's. Built-in
  kinds hold no ``.``, so the two never meet; two plug-ins declaring the same
  key differ by their uids. Their codes are ``public.plugin_kind_codes``'.
* **Tables** are ``p_``, the uid in lower case and the key as written. The
  prefix keeps them apart from every table a release adds, the uid from
  another plug-in's.
* **Columns** are the ones a built-in tool's tables have, from the mixins
  their models are made of (a tool's own table those every built-in tool's
  is made of, an item table those every item table in the trash is, with the
  archive stamp beside them), and one typed column per declared field, its
  kind in the column's ``info``: NOT NULL where the field is required, and
  a colour that defaults to ``random`` picking from the app's palette per
  row. Their CHECKs and triggers are a built-in tool table's, from
  ``app.db.guild_ddl.tool_table_rules``, beside a CHECK per select field's
  options and per declared check.
* **Permissions** are ``<kind>:enabled``, the tool's switch in each initiative
  and the role key for viewing it, and ``<kind>:create``: a built-in tool's
  pair, written by the same writer and role defaults, owned by no install.

* **Versions** only add to the tables: the structure brings a table up to
  its declaration (new columns, a select's new options, a field's default,
  whether it is required, the checks) and takes nothing away. A field that
  becomes required fills its empty cells with its default first; a check
  holds every row written from then on. A field or an option a new major drops goes by
  :func:`drop_ddl`, once the community's admin confirms it.
* **Removal**: an uninstalled tool keeps its tables and every row naming it
  until its install's deletion window ends; then the deletion sweep purges
  its rows as the trash does, and the community's next provisioning drops
  the tables of that listing (:func:`drop_tool_tables`).

Every name is built from the declaration's keys and the listing's uid, so
each is checked again here, one character at a time, whatever registration
checked before: the renderers write table names into SQL as they are.
"""

from __future__ import annotations

import hashlib
import json
import math
import string
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import EllipsisType
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateColumn, CreateIndex, CreateTable
from sqlmodel import SQLModel
from sqlmodel.main import get_column_from_field

from app.core.palette import COLOR_PALETTE
from app.core.tool_set import BUILTIN_TOOLS, KEPT_TOOL_SETS, ToolRecord, ToolSet
from app.core.tools import Kind, ToolSpec
from app.db.base import MODELS_BY_TABLE
from app.db.names import object_name
from app.models.tenant import _mixins
from app.models.tenant.counter import COUNTER_NUMBER
from app.services.marketplace import contract
from app.services.marketplace.tool_plugins import (
    COMPARISONS,
    MAX_TOOL_CHECKS,
    MAX_TOOL_KEY_LENGTH,
    RANDOM_COLOR,
    TOOL_COLUMNS,
    TOOL_FIELD_KINDS,
    effective_defaults,
)

__all__ = [
    "DECLARED",
    "InstalledTool",
    "PluginKind",
    "PluginToolError",
    "build_tool",
    "community_tool_set",
    "drop_ddl",
    "drop_tool_tables",
    "is_plugin_kind",
    "kept_tool_set",
    "provisioned_tools",
    "structure_ddl",
    "tool_set",
    "tool_table_name",
    "tools_digest",
]

#: The ``info`` key of a tool plug-in's table holding its declaration: the
#: tool's block, or the item's.
DECLARED = "declared"

#: The prefix of every table a tool plug-in has.
TABLE_PREFIX = "p_"


def _mixins_of(tables: Iterable[str]) -> tuple[type[SQLModel], ...]:
    """The mixins the model of every one of ``tables`` is made of, in the
    order the first lists them."""
    models = [MODELS_BY_TABLE[name] for name in tables]
    return tuple(
        base
        for base in models[0].__mro__
        if issubclass(base, SQLModel)
        and base.__module__ == _mixins.__name__
        and all(issubclass(model, base) for model in models)
    )


#: The mixins of a tool's own table: those every built-in tool's is made of.
_TOOL_MIXINS = _mixins_of(record.table.name for record in BUILTIN_TOOLS)
#: The mixins of an item table: those every built-in item table in the trash
#: is made of, and the archive stamp, since an item is put away as its tool
#: is.
_ITEM_MIXINS = (
    *_mixins_of(
        table.name
        for record in BUILTIN_TOOLS
        for table in record.items
        if "deleted_at" in table.c
    ),
    _mixins.ArchiveMixin,
)

_KEY_START = frozenset("abcdefghijklmnopqrstuvwxyz")
_KEY_CHARS = _KEY_START | frozenset("0123456789_")
_UID_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_UID_LENGTH = 14
#: What a select option's value is written with, as registration holds it.
_OPTION_CHARS = frozenset(string.ascii_letters + string.digits + "_-")
_MAX_OPTION_LENGTH = contract.cap("optionValueLength")

_DIALECT = postgresql.dialect()

#: The ``info`` key marking a select field's CHECK of its options, which a
#: later version of the tool may widen.
_OPTIONS = "options"
#: The ``info`` key marking a declared check's CHECK, which a later version
#: may add, change or take away.
_DECLARED = "declared"
#: The kinds of field a check compares.
_NUMBERS = frozenset({"number", "counter"})


class PluginToolError(ValueError):
    """A declaration no tool can be built from."""


@dataclass(frozen=True)
class PluginKind(Kind):
    """A kind inside a tool plug-in's tool: its table is the plug-in's, not
    the plural of its name."""

    table_name: str = ""

    @property
    def table(self) -> str:
        return self.table_name


@dataclass(frozen=True)
class InstalledTool:
    """One installed tool plug-in, as its community's tool set reads it."""

    listing_uid: str
    definition: Mapping[str, Any]


# --- names ------------------------------------------------------------------


def _key(raw: Any, what: str) -> str:
    """A declared key, checked one character at a time."""
    if not isinstance(raw, str) or not raw or len(raw) > MAX_TOOL_KEY_LENGTH:
        raise PluginToolError(f"{what} {raw!r} is not a tool key")
    if raw[0] not in _KEY_START or any(c not in _KEY_CHARS for c in raw):
        raise PluginToolError(f"{what} {raw!r} is not a tool key")
    return raw


def _uid(raw: Any) -> str:
    """A listing's uid, in lower case."""
    if (
        not isinstance(raw, str)
        or len(raw) != _UID_LENGTH
        or any(c not in _UID_CHARS for c in raw)
    ):
        raise PluginToolError(f"{raw!r} is not a listing uid")
    return raw.lower()


def _option(raw: Any) -> str:
    """A select option's value, checked one character at a time: it is
    written into a CHECK and into the DDL that empties it."""
    if (
        not isinstance(raw, str)
        or not 0 < len(raw) <= _MAX_OPTION_LENGTH
        or not set(raw) <= _OPTION_CHARS
    ):
        raise PluginToolError(f"{raw!r} is not an option's value")
    return raw


def _field_key(raw: Any) -> str:
    key = _key(raw, "field key")
    if key in TOOL_COLUMNS or key.endswith("_id"):
        raise PluginToolError(f"field key {key!r} names a column every tool has")
    return key


def tool_table_name(listing_uid: str, key: str) -> str:
    """The table a tool plug-in's tool or item ``key`` is kept in."""
    return f"{TABLE_PREFIX}{_uid(listing_uid)}_{_key(key, 'key')}"


def _kind(listing_uid: str, key: str) -> str:
    return f"{_key(key, 'key')}.{_uid(listing_uid)}"


def is_plugin_kind(value: Any) -> bool:
    """Whether ``value`` has the form of a tool plug-in's kind: the one check
    every place that writes one into SQL asks."""
    if not isinstance(value, str):
        return False
    key, dot, uid = value.partition(".")
    try:
        return bool(dot) and _key(key, "key") == key and _uid(uid.upper()) == uid
    except PluginToolError:
        return False


# --- columns ----------------------------------------------------------------


def _mixin_columns(mixins: Iterable[type[SQLModel]]) -> list[sa.Column]:
    """The columns the mixins give a model, each built afresh. The key to who
    made a row points at ``users``, as a model's does: metadata only, which
    the structure below leaves out as it leaves out every key out of the
    schema."""
    users = SQLModel.metadata.tables["users"]
    columns: dict[str, sa.Column] = {}
    for mixin in mixins:
        for name, info in mixin.model_fields.items():
            if name in columns:
                continue
            column = get_column_from_field(info)
            keys = [sa.ForeignKey(users.c.id)] if column.foreign_keys else []
            columns[name] = sa.Column(
                name,
                column.type,
                *keys,
                nullable=column.nullable,
                server_default=column.server_default,
            )
    return list(columns.values())


def _compiled(clause: Any) -> sa.TextClause:
    """``clause`` with its values written in by the dialect."""
    return sa.text(
        str(clause.compile(dialect=_DIALECT, compile_kwargs={"literal_binds": True}))
    )


#: A colour from the app's palette, picked as each row goes in.
_RANDOM_COLOR = sa.text(
    f"({_compiled(sa.literal(list(COLOR_PALETTE), postgresql.ARRAY(sa.Text)))})"
    f"[floor(random() * {len(COLOR_PALETTE)})::integer + 1]"
)


def _literal(value: Any, kind: str) -> Any:
    """A declared default as a server default, written by the dialect from a
    bound value rather than by pasting it."""
    if kind == "color" and value == RANDOM_COLOR:
        return _RANDOM_COLOR
    if kind == "multi_select":
        array = sa.literal(list(value), postgresql.ARRAY(sa.Text))
        return sa.text(
            str(array.compile(dialect=_DIALECT, compile_kwargs={"literal_binds": True}))
        )
    if isinstance(value, bool):
        return sa.true() if value else sa.false()
    if isinstance(value, int | float):
        return sa.text(
            str(
                sa.literal(value).compile(
                    dialect=_DIALECT, compile_kwargs={"literal_binds": True}
                )
            )
        )
    return str(value)


#: What a declared field's column holds, by its kind: the type its value is
#: kept as wherever Initiative keeps one.
_FIELD_TYPES: dict[str, Any] = {
    "text": sa.Text,
    "url": sa.Text,
    "color": sa.Text,
    "select": sa.Text,
    "number": lambda: COUNTER_NUMBER,
    "counter": lambda: COUNTER_NUMBER,
    "currency": sa.Numeric,
    "scale": sa.Integer,
    "user_reference": sa.Integer,
    "checkbox": sa.Boolean,
    "date": sa.Date,
    "datetime": lambda: sa.DateTime(timezone=True),
    "multi_select": lambda: postgresql.ARRAY(sa.Text),
}


def _field_column(field: Mapping[str, Any], start: Any) -> sa.Column:
    """A declared field's column, defaulting to ``start``."""
    key = _field_key(field.get("key"))
    kind = field.get("kind")
    if kind not in TOOL_FIELD_KINDS or kind not in _FIELD_TYPES:
        raise PluginToolError(f"field {key!r}: {kind!r} is not a field kind")
    default = (
        None
        if start is None
        else _literal(start, "number" if kind == "counter" else kind)
    )
    required = field.get("required") is True
    if required and default is None:
        raise PluginToolError(f"field {key!r} is required and has no default")
    return sa.Column(
        key,
        _FIELD_TYPES[kind](),
        server_default=default,
        nullable=not required,
        info={"field": kind},
    )


def _operand(raw: Any, numbers: frozenset[str]) -> Any:
    """What a check compares its field with, checked again: a finite number,
    or ``{"field": key}``, a number or counter field of the same table."""
    if isinstance(raw, Mapping):
        key = raw.get("field")
        if set(raw) != {"field"} or key not in numbers:
            raise PluginToolError(f"{raw!r} is not a number field of its table")
        return sa.column(_field_key(key))
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise PluginToolError(f"{raw!r} is not a number")
    try:
        finite = math.isfinite(raw)
    except OverflowError:
        finite = False
    if not finite:
        raise PluginToolError(f"{raw!r} is not a number")
    return sa.literal(raw)


def _declared_checks(
    table: str,
    fields: Sequence[Mapping[str, Any]],
    checks: Sequence[Mapping[str, Any]],
) -> list[sa.Constraint]:
    """A CHECK per declared check, each one comparison of a number or counter
    field with a number or another such field. An empty side passes, as a
    CHECK that reads NULL does."""
    if len(checks) > MAX_TOOL_CHECKS:
        raise PluginToolError(f"{table}: more than {MAX_TOOL_CHECKS} checks")
    numbers = frozenset(
        field.get("key") for field in fields if field.get("kind") in _NUMBERS
    )
    built: list[sa.Constraint] = []
    for index, check in enumerate(checks):
        terms = [term for term in check if term != "field"]
        if len(terms) != 1 or terms[0] not in COMPARISONS:
            raise PluginToolError(f"{table}: check {index} is not one comparison")
        if check.get("field") not in numbers:
            raise PluginToolError(f"{table}: check {index} reads no number field")
        compare = COMPARISONS[terms[0]]
        built.append(
            sa.CheckConstraint(
                compare(
                    sa.column(_field_key(check["field"])),
                    _operand(check[terms[0]], numbers),
                ),
                name=object_name("ck", table, f"check_{index}"),
                info={_DECLARED: True},
            )
        )
    return built


def _checks(
    table: str,
    columns: Iterable[str],
    fields: Sequence[Mapping[str, Any]],
    declared: Sequence[Mapping[str, Any]],
) -> list[sa.Constraint]:
    """The CHECKs a tool's table carries: a built-in tool table's, from the
    columns it has, each select field held to its options, and its declared
    checks."""
    from app.db.guild_ddl import tool_table_rules

    shared, _ = tool_table_rules(table, frozenset(columns), None)
    checks: list[sa.Constraint] = [
        sa.CheckConstraint(expression, name=name) for name, expression in shared.items()
    ]
    for field in fields:
        if field.get("kind") != "select":
            continue
        options = [_option(option.get("value")) for option in field.get("options", [])]
        if not options:
            raise PluginToolError(f"select field {field.get('key')!r} has no options")
        checks.append(
            sa.CheckConstraint(
                sa.column(field["key"]).in_(options),
                name=object_name("ck", table, f"{field['key']}_option"),
                info={_OPTIONS: True},
            )
        )
    return checks + _declared_checks(table, fields, declared)


def _table(
    metadata: sa.MetaData,
    name: str,
    *,
    parent: tuple[str, sa.Table] | None,
    declared: Mapping[str, Any],
) -> sa.Table:
    """A tool's own table (``parent`` None) or an item table under
    ``parent``, a ``(column, table)``, as ``declared``: the tool's block or
    the item's, kept in the table's ``info`` for what reads a declared fact
    (an item's ``open_while``, a field's name)."""
    fields = declared.get("fields", [])
    initiatives = SQLModel.metadata.tables["initiatives"]
    if parent is None:
        anchor = sa.Column(
            "initiative_id", sa.Integer, sa.ForeignKey(initiatives.c.id), nullable=False
        )
    else:
        column, table = parent
        anchor = sa.Column(
            column,
            sa.Integer,
            sa.ForeignKey(table.c.id, ondelete="CASCADE"),
            nullable=False,
        )
    starts = effective_defaults(fields)
    columns = [_field_column(field, starts.get(field.get("key"))) for field in fields]
    seen = {"id", anchor.name, "name", "position", "created_at", "updated_at"}
    for column in columns:
        if column.name in seen:
            raise PluginToolError(f"{name}: two columns named {column.name!r}")
        seen.add(column.name)
    universal = _mixin_columns(_TOOL_MIXINS if parent is None else _ITEM_MIXINS)
    table = sa.Table(
        name,
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        anchor,
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", COUNTER_NUMBER, nullable=False, server_default="0"),
        *columns,
        *universal,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_checks(
            name,
            (column.name for column in universal),
            fields,
            declared.get("checks", []),
        ),
        # A tool row is read back by no RETURNING clause, as a built-in
        # tool's is (``CounterGroup``): nothing is shared with anyone yet.
        implicit_returning=parent is not None,
        info={DECLARED: declared},
    )
    sa.Index(object_name("ix", name, anchor.name), table.c[anchor.name])
    sa.Index(
        object_name("ix", name, "purge"),
        table.c.purge_at,
        postgresql_where=table.c.purge_at.isnot(None),
    )
    return table


# --- the record --------------------------------------------------------------


def build_tool(
    tool: InstalledTool, codes: Mapping[str, int], metadata: sa.MetaData
) -> ToolRecord:
    """The record of ``tool``'s tool, its tables on ``metadata``. ``codes`` are
    the plug-in kinds' codes. Raises :class:`PluginToolError` for a
    declaration no tool is built from."""
    block = tool.definition.get("tool")
    if tool.definition.get("plugin_kind") != "tool" or not isinstance(block, Mapping):
        raise PluginToolError("not a tool plug-in's definition")
    uid = tool.listing_uid
    key = _key(block.get("key"), "tool key")
    kind = _kind(uid, key)
    if kind not in codes:
        raise PluginToolError(f"{kind} has no kind code")
    own = _table(
        metadata,
        tool_table_name(uid, key),
        parent=None,
        declared=block,
    )
    tables = {key: own}
    children: list[Kind] = []
    items = list(block.get("items", []))
    # An item under another item is built after it.
    for item in sorted(items, key=lambda entry: entry.get("parent") is not None):
        item_key = _key(item.get("key"), "item key")
        parent_key = item.get("parent", key)
        if item_key in tables or parent_key not in tables:
            raise PluginToolError(f"item {item_key!r} sits under no table")
        tables[item_key] = _table(
            metadata,
            tool_table_name(uid, item_key),
            parent=(f"{_key(parent_key, 'parent key')}_id", tables[parent_key]),
            declared=item,
        )
        item_kind = _kind(uid, item_key)
        if item_kind not in codes:
            raise PluginToolError(f"{item_kind} has no kind code")
        # Every item holds a conversation and is put away when finished
        # with, as a tool does.
        children.append(
            PluginKind(
                item_kind,
                codes[item_kind],
                commentable=True,
                archivable=True,
                table_name=tables[item_key].name,
            )
        )
    # Parents first, as they were built, so each table's key names a table
    # created before it.
    item_tables = tuple(table for item_key, table in tables.items() if item_key != key)
    return ToolRecord(
        kind=kind,
        plural=own.name,
        spec=ToolSpec(
            code=codes[kind],
            # Installing the tool switches it on in every initiative, and a
            # member may view it as a member may view a tool that is on.
            on_by_default=True,
            # Exporting it is for the registries that read the community's
            # tool set at request time, which do not read one yet.
            export_formats=(),
            item_tables=tuple(table.name for table in item_tables),
        ),
        table=own,
        items=item_tables,
        children=tuple(children),
        view_permission=f"{kind}:enabled",
        create_permission=f"{kind}:create",
        scope=kind,
        declaration=block,
    )


def _ordered(installed: Iterable[InstalledTool]) -> list[InstalledTool]:
    return sorted(installed, key=lambda tool: tool.listing_uid)


def tools_digest(installed: Sequence[InstalledTool]) -> str | None:
    """What a community's tool plug-ins are, as one digest of each listing
    and its declaration, by listing: what its schema's stamp names them by,
    and None for a community with none. Communities with the same versions
    share it."""
    if not installed:
        return None
    body = json.dumps(
        [[t.listing_uid, t.definition] for t in _ordered(installed)],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()[:16]


#: The tool sets this process built, by digest, the least recently used
#: first.
_SETS: OrderedDict[str, ToolSet] = OrderedDict()


def kept_tool_set(digest: str) -> ToolSet | None:
    """The tool set this process built for ``digest``, if it keeps one."""
    found = _SETS.get(digest)
    if found is not None:
        _SETS.move_to_end(digest)
    return found


def community_tool_set(
    installed: Sequence[InstalledTool], codes: Mapping[str, int]
) -> ToolSet:
    """The built-in tools and ``installed``'s, kept by digest so a set is
    built once per process. :data:`BUILTIN_TOOLS` itself where nothing is
    installed."""
    digest = tools_digest(installed)
    if digest is None:
        return BUILTIN_TOOLS
    found = kept_tool_set(digest)
    if found is None:
        metadata = sa.MetaData()
        records = (build_tool(tool, codes, metadata) for tool in _ordered(installed))
        found = _SETS[digest] = ToolSet((*BUILTIN_TOOLS, *records), digest=digest)
        while len(_SETS) > KEPT_TOOL_SETS:
            _SETS.popitem(last=False)
    return found


# --- structure ---------------------------------------------------------------


def _structure(table: sa.Table, record: ToolRecord) -> list[str]:
    """``table`` as its tool declares it now: made where it is missing, and
    otherwise brought up to it by adding what a later version adds (a column,
    a select's options, a field's default, its checks). A field made required
    is filled last, once its options and the checks are the version's own.
    Nothing here removes anything."""
    create = CreateTable(
        table,
        if_not_exists=True,
        include_foreign_key_constraints=[
            fk.constraint
            for fk in table.foreign_keys
            if fk.column.table.name != "users"
        ],
    )
    quoted = _DIALECT.identifier_preparer.quote(table.name)
    ddl = _DIALECT.ddl_compiler(_DIALECT, None)
    statements = [str(create.compile(dialect=_DIALECT)).strip()]
    fills: list[str] = []
    for column in table.columns:
        if column.primary_key:
            continue
        spec = str(CreateColumn(column).compile(dialect=_DIALECT))
        statements.append(f"ALTER TABLE {quoted} ADD COLUMN IF NOT EXISTS {spec}")
        if "field" in column.info:
            default = ddl.get_column_default_string(column)
            name = _DIALECT.identifier_preparer.quote(column.name)
            statements.append(
                f"ALTER TABLE {quoted} ALTER COLUMN {name}"
                + (" DROP DEFAULT" if default is None else f" SET DEFAULT {default}")
                + (
                    ""
                    if not column.nullable
                    else f", ALTER COLUMN {name} DROP NOT NULL"
                )
            )
            if not column.nullable:
                fills.append(_required(quoted, name))
    for check in sorted(
        (c for c in table.constraints if c.info.get(_OPTIONS)),
        key=lambda c: str(c.name),
    ):
        add = str(AddConstraint(check).compile(dialect=_DIALECT))
        name = _DIALECT.identifier_preparer.quote(str(check.name))
        statements.append(
            f"ALTER TABLE {quoted} DROP CONSTRAINT IF EXISTS {name},"
            + add.removeprefix(f"ALTER TABLE {quoted}")
        )
    # A declared check holds the rows written from now on: one a later
    # version adds does not refuse the rows already there.
    declared = sorted(
        (c for c in table.constraints if c.info.get(_DECLARED)),
        key=lambda c: str(c.name),
    )
    retired = (
        "DROP CONSTRAINT IF EXISTS "
        + _DIALECT.identifier_preparer.quote(
            object_name("ck", table.name, f"check_{index}")
        )
        for index in range(MAX_TOOL_CHECKS)
    )
    added = (
        str(AddConstraint(check).compile(dialect=_DIALECT)).removeprefix(
            f"ALTER TABLE {quoted} "
        )
        + " NOT VALID"
        for check in declared
    )
    statements.append(f"ALTER TABLE {quoted} " + ", ".join((*retired, *added)))
    statements += fills
    statements += [
        str(CreateIndex(index, if_not_exists=True).compile(dialect=_DIALECT))
        for index in sorted(table.indexes, key=lambda index: str(index.name))
    ]
    from app.db.guild_ddl import tool_table_rules

    _, triggers = tool_table_rules(
        table.name, table.c.keys(), record.kind if table is record.table else None
    )
    return statements + triggers


def _required(table: str, column: str) -> str:
    """Makes ``column`` of ``table`` (both quoted) NOT NULL where it is not
    yet, its empty cells first taking its default, as each row would have
    had it been required from the start."""
    regclass = _compiled(sa.literal(table, sa.Text))
    attname = _compiled(sa.literal(column.strip('"'), sa.Text))
    return (
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_attribute"
        f" WHERE attrelid = {regclass}::regclass AND attname = {attname}"
        " AND NOT attnotnull) THEN"
        f" ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;"
        f" ALTER TABLE {table} DISABLE TRIGGER USER;"
        f" UPDATE {table} SET {column} = DEFAULT WHERE {column} IS NULL;"
        f" ALTER TABLE {table} ENABLE TRIGGER USER;"
        f" ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"
        f" ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL;"
        " END IF; END $$"
    )


def structure_ddl(tools: ToolSet) -> str:
    """The tables of every installed tool in ``tools``, their keys, indexes
    and CHECKs, and the triggers a built-in tool's table carries from its
    migration. Schema-relative and idempotent, like the template's
    structure."""
    statements = [
        statement
        for record in tools.installed
        for table in (record.table, *record.items)
        for statement in _structure(table, record)
    ]
    return "".join(f"{statement};\n" for statement in statements)


async def drop_tool_tables(conn: Any, schema: str, listing_uid: str) -> list[str]:
    """Drop the tables in ``schema`` of the tool plug-in ``listing_uid``
    (``p_<uid>_``), whose install the deletion sweep removed once its window
    ended. Returns their names. Run on the provisioning connection, under the
    community's provisioning lock."""
    found = (
        (
            await conn.execute(
                sa.text(
                    "SELECT c.relname FROM pg_class c"
                    " WHERE c.relnamespace = to_regnamespace(:schema)"
                    " AND c.relkind = 'r' AND starts_with(c.relname, :prefix)"
                    " ORDER BY c.relname"
                ),
                {"schema": schema, "prefix": f"{TABLE_PREFIX}{_uid(listing_uid)}_"},
            )
        )
        .scalars()
        .all()
    )
    quote = _DIALECT.identifier_preparer.quote
    for name in found:
        await conn.exec_driver_sql(
            f"DROP TABLE IF EXISTS {quote(schema)}.{quote(name)} CASCADE"
        )
    return list(found)


def drop_ddl(listing_uid: str, before: Mapping[str, Any], changes: Any) -> str:
    """The DDL that takes from a tool plug-in's tables what a new major
    version stops declaring, once the community's admin confirms it:
    ``changes`` (``tool_plugins.ToolChanges``) against the definition
    ``before``. A dropped field's column goes, with whatever reads it; a
    dropped option is emptied from the cells holding it (a select's set to
    NULL, or to the new version's default where the field is required, a
    multi-select's without it) and the rest keep their values. A cell
    the platform holds is never emptied: the version is refused instead.
    Schema-relative; the parts rendered after it put back what reads the
    tables and their row security."""
    quote = _DIALECT.identifier_preparer.quote
    tool = before["tool"]
    kinds = {
        (table["key"], field["key"]): field["kind"]
        for table in (tool, *tool.get("items", []))
        for field in table.get("fields", [])
    }
    emptied: dict[tuple[str, str], list[str]] = {}
    for name in changes.dropped_options:
        table_key, field_key, value = name.split(".", 2)
        emptied.setdefault((table_key, field_key), []).append(_option(value))
    statements: list[str] = []
    for (table_key, field_key), values in emptied.items():
        table = quote(tool_table_name(listing_uid, table_key))
        column = quote(_field_key(field_key))
        listed = ", ".join(
            str(
                sa.literal(value).compile(
                    dialect=_DIALECT, compile_kwargs={"literal_binds": True}
                )
            )
            for value in values
        )
        if kinds[(table_key, field_key)] == "select":
            holding, kept = f"{column} IN ({listed})", "NULL"
        else:
            holding = f"{column} && ARRAY[{listed}]::text[]"
            kept = (
                f"ARRAY(SELECT v FROM unnest({column}) AS v WHERE v NOT IN ({listed}))"
            )
        statements += [
            (
                f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {table}"
                f" WHERE held_at IS NOT NULL AND {holding}) THEN"
                " RAISE EXCEPTION 'a held row holds a dropped option'; END IF; END $$"
            ),
            f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} DISABLE TRIGGER USER",
            # A required select's emptied cells take the version's default
            # as the structure rendered after this brings it back to NOT NULL.
            f"ALTER TABLE {table} ALTER COLUMN {column} DROP NOT NULL",
            f"UPDATE {table} SET {column} = {kept} WHERE {holding}",
            f"ALTER TABLE {table} ENABLE TRIGGER USER",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        ]
    for name in changes.dropped_fields:
        table_key, _, field_key = name.partition(".")
        table = quote(tool_table_name(listing_uid, table_key))
        # What reads the column goes with it, and the parts rendered after
        # this put back what the version still has.
        statements.append(
            f"ALTER TABLE {table}"
            f" DROP COLUMN IF EXISTS {quote(_field_key(field_key))} CASCADE"
        )
    return "".join(f"{statement};\n" for statement in statements)


# --- loading -----------------------------------------------------------------

#: A community's installed tool plug-ins, read from the routed session of
#: whoever asks: a member reads its community's installs.
_DEFINITIONS = sa.text(
    "SELECT listing_uid, definition FROM guild_plugins"
    " WHERE plugin_kind = 'tool' ORDER BY id"
)


async def _installed(session: Any) -> list[InstalledTool]:
    """The community's installed tool plug-ins, read on ``session``."""
    return [
        InstalledTool(row.listing_uid, row.definition)
        for row in (await session.exec(_DEFINITIONS)).all()
    ]


async def _built(installed: list[InstalledTool]) -> ToolSet:
    """The tool set of ``installed``: the one this process keeps, or one built
    with every plug-in kind's code, read on a system connection of its own
    (the table is the deployment's, and no community's role reads it). The
    caller holds no other system connection while this reads, so one
    connection is all a cold set ever takes."""
    from app.db import session as db_session
    from app.db.kind_codes import plugin_kind_codes

    digest = tools_digest(installed)
    found = BUILTIN_TOOLS if digest is None else kept_tool_set(digest)
    if found is not None:
        return found
    async with db_session.system_engine.connect() as conn:
        codes = await plugin_kind_codes(conn)
    return community_tool_set(installed, codes)


async def tool_set(session: Any, stamped: str | None | EllipsisType = ...) -> ToolSet:
    """The tool set of the community ``session`` is routed into, as its
    installs stand. ``stamped`` is the digest its schema's stamp names, where
    the caller read it (``schema_provisioning.stamp_tools``): the built-in
    tools where it names none, and the set this process keeps for it, with no
    query. The codes are read only to build a set this process does not keep
    (:func:`_built`). While a community's provisioning lags its installs, this
    is the set they make now."""
    if stamped is None:
        return BUILTIN_TOOLS
    found = None if stamped is ... else kept_tool_set(stamped)
    if found is not None:
        return found
    return await _built(await _installed(session))


async def provisioned_tools(guild_id: int) -> ToolSet:
    """The tool set of ``guild_id`` as its installs stand, read on the system
    engine: the built-in tools for a community whose schema does not exist
    yet."""
    from app.db import cohorts
    from app.db import session as db_session
    from app.db.request_context import SystemGuild
    from app.db.schema_provisioning import guild_schema_name

    async with cohorts.system_session(guild_id) as session:
        exists = await session.scalar(
            sa.text("SELECT to_regclass(:t) IS NOT NULL"),
            {"t": f'"{guild_schema_name(guild_id)}".guild_plugins'},
        )
        if not exists:
            return BUILTIN_TOOLS
        await db_session.set_rls_context(session, SystemGuild(guild_id))
        installed = await _installed(session)
        await session.rollback()
    # Built once the community's connection is back in its pool.
    return await _built(installed)
