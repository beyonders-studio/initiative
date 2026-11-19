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
  their models are made of (a tool's own table as ``counter_groups``, an
  item table as ``counters``), and one typed column per declared field.
* **Permissions** are ``<kind>:enabled``, the tool's switch in each initiative
  and the role key for viewing it, and ``<kind>:create``. Their rows are the
  install's.

Every name is built from the declaration's keys and the listing's uid, so
each is checked again here, one character at a time, whatever registration
checked before: the renderers write table names into SQL as they are.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel
from sqlmodel.main import get_column_from_field

from app.core.tool_set import BUILTIN_TOOLS, ToolRecord, ToolSet
from app.core.tools import Kind, ToolSpec
from app.db.names import object_name
from app.models.tenant._mixins import (
    ActorKind,
    ArchiveMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    HoldMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
)
from app.models.tenant.counter import COUNTER_NUMBER
from app.services.marketplace.tool_plugins import (
    MAX_TOOL_KEY_LENGTH,
    TOOL_COLUMNS,
    TOOL_FIELD_KINDS,
)

__all__ = [
    "InstalledTool",
    "PluginKind",
    "build_tool",
    "community_tool_set",
    "installed_digest",
    "structure_ddl",
    "tool_table_name",
]

#: The prefix of every table a tool plug-in has.
TABLE_PREFIX = "p_"

#: The mixins of a tool's own table and of an item table: what
#: ``counter_groups`` and ``counters`` are made of.
_TOOL_MIXINS: tuple[type[SQLModel], ...] = (
    HoldMixin,
    CommentLockMixin,
    CommentsToggleMixin,
    CreatedByMixin,
    ArchiveMixin,
    ListingProvenanceMixin,
    SoftDeleteMixin,
)
_ITEM_MIXINS: tuple[type[SQLModel], ...] = (HoldMixin, CreatedByMixin, SoftDeleteMixin)

_KEY_START = frozenset("abcdefghijklmnopqrstuvwxyz")
_KEY_CHARS = _KEY_START | frozenset("0123456789_")
_UID_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_UID_LENGTH = 14

_DIALECT = postgresql.dialect()


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

    install_id: int
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


def _literal(value: Any, kind: str) -> Any:
    """A declared default as a server default, written by the dialect from a
    bound value rather than by pasting it."""
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


def _field_column(field: Mapping[str, Any]) -> sa.Column:
    key = _field_key(field.get("key"))
    kind = field.get("kind")
    if kind not in TOOL_FIELD_KINDS or kind not in _FIELD_TYPES:
        raise PluginToolError(f"field {key!r}: {kind!r} is not a field kind")
    default: Any = None
    if kind == "counter":
        start = (field.get("counter") or {}).get("initial")
        default = _literal(start if isinstance(start, int | float) else 0, "number")
    elif field.get("default") is not None:
        default = _literal(field["default"], kind)
    return sa.Column(key, _FIELD_TYPES[kind](), server_default=default)


def _checks(table: str, fields: Sequence[Mapping[str, Any]]) -> list[sa.Constraint]:
    """The CHECKs a tool's table carries: who made and binned a row, as on
    every tool table, and each select field held to its options."""
    actors = ", ".join(f"'{kind.value}'" for kind in ActorKind)
    system = ActorKind.system.value
    checks = [
        sa.CheckConstraint(
            f"(created_by_kind = '{system}') = (created_by IS NULL)",
            name=object_name("ck", table, "created_by"),
        ),
        sa.CheckConstraint(
            f"created_by_kind IN ({actors})",
            name=object_name("ck", table, "created_by_kind"),
        ),
        sa.CheckConstraint(
            "CASE WHEN deleted_at IS NULL"
            " THEN deleted_by IS NULL AND deleted_by_kind IS NULL"
            " ELSE deleted_by_kind IS NOT NULL"
            f" AND (deleted_by_kind = '{system}') = (deleted_by IS NULL) END",
            name=object_name("ck", table, "deleted_by"),
        ),
        sa.CheckConstraint(
            f"deleted_by_kind IN ({actors})",
            name=object_name("ck", table, "deleted_by_kind"),
        ),
    ]
    for field in fields:
        if field.get("kind") != "select":
            continue
        options = [option["value"] for option in field.get("options", [])]
        if not options or not all(isinstance(v, str) for v in options):
            raise PluginToolError(f"select field {field.get('key')!r} has no options")
        checks.append(
            sa.CheckConstraint(
                sa.column(field["key"]).in_(options),
                name=object_name("ck", table, f"{field['key']}_option"),
            )
        )
    return checks


def _table(
    metadata: sa.MetaData,
    name: str,
    *,
    parent: tuple[str, sa.Table] | None,
    fields: Sequence[Mapping[str, Any]],
) -> sa.Table:
    """A tool's own table (``parent`` None) or an item table under
    ``parent``, a ``(column, table)``."""
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
    declared = [_field_column(field) for field in fields]
    seen = {"id", anchor.name, "name", "position", "created_at", "updated_at"}
    for column in declared:
        if column.name in seen:
            raise PluginToolError(f"{name}: two columns named {column.name!r}")
        seen.add(column.name)
    table = sa.Table(
        name,
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        anchor,
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position", COUNTER_NUMBER, nullable=False, server_default="0"),
        *declared,
        *_mixin_columns(_TOOL_MIXINS if parent is None else _ITEM_MIXINS),
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
        *_checks(name, fields),
        # A tool row is read back by no RETURNING clause, as a built-in
        # tool's is (``CounterGroup``): nothing is shared with anyone yet.
        implicit_returning=parent is not None,
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
        fields=block.get("fields", []),
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
            fields=item.get("fields", []),
        )
        item_kind = _kind(uid, item_key)
        if item_kind not in codes:
            raise PluginToolError(f"{item_kind} has no kind code")
        children.append(
            PluginKind(item_kind, codes[item_kind], table_name=tables[item_key].name)
        )
    item_tables = tuple(tables[item["key"]] for item in items)
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
        install_id=tool.install_id,
    )


def installed_digest(installed: Sequence[InstalledTool]) -> str:
    """What a community's tool plug-ins are, as one digest: the install, its
    listing and its declaration, in install order."""
    body = json.dumps(
        [[t.install_id, t.listing_uid, t.definition] for t in installed],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode()).hexdigest()[:16]


_SETS: dict[str, ToolSet] = {}


def community_tool_set(
    installed: Sequence[InstalledTool], codes: Mapping[str, int]
) -> ToolSet:
    """The built-in tools and ``installed``'s, kept per digest so a
    community's set is built once per process. :data:`BUILTIN_TOOLS` itself
    where nothing is installed."""
    if not installed:
        return BUILTIN_TOOLS
    ordered = sorted(installed, key=lambda tool: tool.install_id)
    digest = installed_digest(ordered)
    found = _SETS.get(digest)
    if found is None:
        metadata = sa.MetaData()
        records = tuple(build_tool(tool, codes, metadata) for tool in ordered)
        found = _SETS.setdefault(
            digest, ToolSet((*BUILTIN_TOOLS, *records), digest=digest)
        )
    return found


# --- structure ---------------------------------------------------------------


def _structure(table: sa.Table, record: ToolRecord) -> list[str]:
    create = CreateTable(
        table,
        if_not_exists=True,
        include_foreign_key_constraints=[
            fk.constraint
            for fk in table.foreign_keys
            if fk.column.table.name != "users"
        ],
    )
    statements = [str(create.compile(dialect=_DIALECT)).strip()]
    statements += [
        str(CreateIndex(index, if_not_exists=True).compile(dialect=_DIALECT))
        for index in sorted(table.indexes, key=lambda index: str(index.name))
    ]
    quoted = _DIALECT.identifier_preparer.quote(table.name)
    statements.append(
        f"CREATE OR REPLACE TRIGGER {object_name('tr', table.name, 'set_created_by')}"
        f" BEFORE INSERT ON {quoted} FOR EACH ROW"
        " EXECUTE FUNCTION public.fn_set_author()"
    )
    if table is record.table:
        statements.append(
            f"CREATE OR REPLACE TRIGGER {object_name('tr', table.name, 'install_owns')}"
            f" AFTER INSERT ON {quoted} FOR EACH ROW"
            f" EXECUTE FUNCTION public.fn_install_owns_what_it_creates('{record.kind}')"
        )
    return statements


def structure_ddl(tools: ToolSet) -> str:
    """The tables of every installed tool in ``tools``, their keys, indexes
    and CHECKs, and the triggers a tool's table carries from its migration
    (who made a row, and the owner grant a request's new row takes).
    Schema-relative and idempotent, like the template's structure."""
    statements = [
        statement
        for record in tools.installed
        for table in (record.table, *record.items)
        for statement in _structure(table, record)
    ]
    return "".join(f"{statement};\n" for statement in statements)


# --- loading -----------------------------------------------------------------

#: A community's installed tool plug-ins, by install. Read from the routed
#: session of whoever asks: a member reads its community's installs.
_INSTALLED = sa.text(
    "SELECT id, listing_uid, md5(definition::text) AS digest FROM guild_plugins"
    " WHERE plugin_kind = 'tool' ORDER BY id"
)
_DEFINITIONS = sa.text(
    "SELECT id, listing_uid, definition FROM guild_plugins"
    " WHERE plugin_kind = 'tool' ORDER BY id"
)

#: The sets read at request time, by what the installs' rows were.
_BY_ROWS: dict[tuple[tuple[Any, ...], ...], ToolSet] = {}


async def _codes() -> dict[str, int]:
    """Every plug-in kind's code, read on the system engine: the table is the
    deployment's, and no community's role reads it."""
    from app.db import session as db_session
    from app.db.kind_codes import plugin_kind_codes

    async with db_session.system_engine.connect() as conn:
        return await plugin_kind_codes(conn)


async def _installed(session: Any) -> list[InstalledTool]:
    rows = (await session.execute(_DEFINITIONS)).all()
    return [InstalledTool(row.id, row.listing_uid, row.definition) for row in rows]


async def community_tools(session: Any) -> ToolSet:
    """The tool set of the community ``session`` is routed to. One read of
    its installs; their declarations and the kind codes are read only the
    first time this process sees them."""
    rows = tuple(tuple(row) for row in (await session.execute(_INSTALLED)).all())
    if not rows:
        return BUILTIN_TOOLS
    found = _BY_ROWS.get(rows)
    if found is None:
        found = community_tool_set(await _installed(session), await _codes())
        _BY_ROWS[rows] = found
    return found


async def provisioned_tools(guild_id: int) -> ToolSet:
    """The tool set of ``guild_id`` as its installs stand, read on the
    system engine, for provisioning: :data:`BUILTIN_TOOLS` for a community
    whose schema does not exist yet."""
    from app.db import session as db_session
    from app.db.request_context import SystemGuild
    from app.db.schema_provisioning import guild_schema_name

    async with db_session.SystemSessionLocal() as session:
        exists = await session.scalar(
            sa.text("SELECT to_regclass(:t) IS NOT NULL"),
            {"t": f'"{guild_schema_name(guild_id)}".guild_plugins'},
        )
        if not exists:
            return BUILTIN_TOOLS
        await db_session.set_rls_context(session, SystemGuild(guild_id))
        installed = await _installed(session)
        await session.rollback()
    if not installed:
        return BUILTIN_TOOLS
    return community_tool_set(installed, await _codes())
