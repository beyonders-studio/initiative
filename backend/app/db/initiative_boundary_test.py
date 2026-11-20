"""The initiative boundary, proven by behaviour on every table that has one.

Nothing in initiative A is read or written by somebody who is not in A, as
nothing in one community's schema is reached from another. The structural
tests (``guild_rls_test``, ``tenancy_test``) check every table carries its
policies; this one checks what the policies answer.

The tables are ``INITIATIVE_PATHS`` itself, so a table is swept the day it is
registered. For each, rows are put in initiative A on the setup session, with
every parent they need, built from the table's own columns, CHECKs and
foreign keys (:class:`_Seeder`). Every tool row in A is shared by name, at
write, with the two people below who are not in A. The community's rows that
are not A's are then cleared, so a statement over a whole table reaches only
A's rows. On the request login routed through the seam:

- a moderator of initiative B and a community member in no initiative each
  read none of A's rows, are refused an INSERT into A, and UPDATE and DELETE
  none of A's rows, by statements that read no column, so each command's own
  policy answers alone;
- a moderator of A reads its row, and inserts, updates and deletes one, so
  the rows the others are refused are well formed.

A table whose row names its subject by kind (a comment) is swept once per
kind it may name, so every kind's arm of its policy answers.

Then each tool is switched off in A in turn, and with every tool's switch row
gone: a moderator of A reads none of the rows of a table a switched-off tool
governs, is refused an INSERT into it, and updates and deletes none of them.

Then the tool plug-in's placement: placed in B and not in A, its rows in A
are to A's moderator, A's member and the community's admin exactly what they
are with its switch in A off, and A's moderator reads none of a table it
governs; placed in A again, A's moderator reads them.

Last, the tool plug-in's state: suspended, and uninstalled by its community
with its content kept for the deletion window, its rows (and the comments on
them) read as absent to A's moderator and to the community's admin, and every
write is refused; read-only, they read and every write is refused; installed
again, A's moderator reads and writes its row and nobody outside A reads it.
A custom role made after the install adds the tool's row in A once given its
create permission, and not before. Through the universal routes and the tool
plug-in routes (``tenant_endpoints/plugin_tools.py``), the tool plug-in's row
and its item answer A's moderator and are not found by the other two.

Its webhooks: a change to its rows in A is told by their kinds to an install
holding the tool's read scope and placed in A, and to the community's own
subscription; an install whose grant no longer holds the scope hears nothing,
and nobody hears a change in A while the tool is not placed there.

A table the seeder cannot fill fails here; it is never skipped.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.core.tool_set import BUILTIN_TOOLS, ToolSet
from app.core.tools import Tool
from app.db.guild_ddl import _WRITTEN_BY
from app.db.initiative_rls import (
    INITIATIVE_PATHS,
    entity_tables,
    governing_walk,
    initiative_of,
    paths_for,
)
from app.db.plugin_tools import provisioned_tools
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.db.tool_rows import load_row, locate
from app.models.platform.guild import CommunityRole
from app.models.platform.notification import Notification, NotificationType
from app.models.platform.plugin_install import PluginInstall, PluginInstallStatus
from app.models.tenant._mixins import ActorKind
from app.models.tenant.initiative import InitiativeRule
from app.models.tenant.metadata import MetadataType
from app.models.tenant.personal_item import PersonalItem
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.tenant.initiative_tools import write_switches
from app.testing import (
    COUNTERS_UID,
    Actor,
    add_counter,
    convert_counters,
    create_initiative,
    create_property_definition,
    create_tag,
    drain_notices,
    install_tool_plugin,
    make_operations_community,
    route_as,
    route_session_to_guild,
)

pytestmark = pytest.mark.always

#: insufficient_privilege: a missing grant, and a row a policy refuses.
_REFUSED = "42501"

#: object_not_in_prerequisite_state: a table's own trigger refusing a change.
_FROZEN = "55000"

_SET_ASIDE_FREEZE_GUARDS = sa.text(
    """
    DO $$
    DECLARE r record;
    BEGIN
        FOR r IN
            SELECT c.relname, t.tgname
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_proc p ON p.oid = t.tgfoid
            WHERE c.relnamespace = current_schema()::regnamespace
              AND p.proname IN (
                  'fn_frozen_row_guard', 'fn_frozen_parent_guard',
                  'fn_frozen_ancestor_guard'
              )
        LOOP
            EXECUTE format('ALTER TABLE %I DISABLE TRIGGER %I', r.relname, r.tgname);
        END LOOP;
    END
    $$
    """
)


@dataclass(frozen=True)
class _Parent:
    """A foreign key the row's own CHECK requires set, though it may be NULL."""

    table: str


#: A person column the row's own CHECK requires set, though it may be NULL.
_PERSON = object()

#: A column whose value is unique in the community: each row takes the next
#: value its CHECK allows.
_DISTINCT = object()

#: When a row of a table is made in A, values the generic fill cannot work out
#: from the catalog: a rule over several columns, or a trigger's. ``_Parent(t)``
#: is a fresh row of ``t`` in A, ``_PERSON`` the row's person.
_SHAPES: dict[str, dict[str, Any]] = {
    # A grant names exactly one grantee.
    "resource_grants": {"user_id": _PERSON},
    # Evidence belongs to exactly one report or case.
    "evidence": {"report_id": _Parent("moderation_reports")},
    # A layout of a project names the project.
    "tool_layouts": {"tool": Tool.project.value, "tool_id": _Parent("projects")},
    # An upload that names an initiative has been claimed.
    "uploads": {"claimed_at": datetime(2026, 1, 1, tzinfo=UTC)},
    # A personal row holds something.
    "personal_items": {"bookmarked_at": datetime(2026, 1, 1, tzinfo=UTC)},
    # A queued line is about a task, a comment or a post.
    "batched_notices": {"target_type": "task"},
    # Making the subject indexes it as chunk 0.
    "search_entries": {"chunk_ix": 99},
    # One binding per stream.
    "intake_bindings": {"stream": _DISTINCT},
}

#: A row of the table on the left is read only with a row of the one on the
#: right naming it in the column given: a collection is seen through its files.
_SEEN_WITH: dict[str, tuple[str, str]] = {
    "collections": ("collection_files", "collection_id"),
}

#: Commands a moderator of A is refused on a table by a rule other than the
#: initiative's, which the positive control leaves out. A tool plug-in's
#: tables are added by :func:`_not_a_moderators`.
_NOT_A_MODERATORS: dict[str, frozenset[str]] = {
    # Hard deletion is the community admin's purge; a member's is the trash.
    **{t: frozenset({"DELETE"}) for t in SOFT_DELETE_TABLES if t in INITIATIVE_PATHS},
    # Written by the system engine or a trigger alone.
    **{t: frozenset(commands) for t, commands in _WRITTEN_BY.items()},
    # A request is removed by the system alone.
    "share_requests": frozenset({"DELETE"}),
    # The moderation log is only appended to.
    "moderation_actions": frozenset({"UPDATE", "DELETE"}),
}


def _not_a_moderators(tools: ToolSet) -> dict[str, frozenset[str]]:
    """:data:`_NOT_A_MODERATORS` in a community with ``tools``: a tool
    plug-in's tables have the trash from the same mixin."""
    trashed = tools.tables_carrying("deleted_at")
    return {**_NOT_A_MODERATORS, **{t: frozenset({"DELETE"}) for t in trashed}}


#: Tables the community's administration reads and writes rather than an
#: initiative's members, whose positive control is the community admin.
_ADMINISTERED: frozenset[str] = frozenset({"guest_invite_grants"})

#: Tables whose row names its subject by kind, swept once per kind it may name
#: in the community, so every kind's arm of the policy is proven and not only
#: the first.
_EVERY_SUBJECT: dict[str, tuple[str, Callable[[ToolSet], tuple[str, ...]]]] = {
    "comments": ("subject_type", lambda tools: tools.comment_targets),
    # A built-in tool's entry, and an entry of each kind a tool plug-in brings.
    "search_entries": (
        "entity_type",
        lambda tools: (Tool.project.value, *_installed_kinds(tools)),
    ),
}


def _installed_kinds(tools: ToolSet) -> tuple[str, ...]:
    """Every kind the community's tool plug-ins bring: each tool's, then its
    items'."""
    return tuple(
        kind
        for tool in tools.installed
        for kind in (tool.kind, *(child.value for child in tool.children))
    )


def _layout_targets(tools: ToolSet) -> list[tuple[str, dict[str, Any]]]:
    """A project's layouts, and each tool plug-in's tables': its tool's own,
    which are the initiative's, and each item's under a row of the table it
    sits in."""
    kinds = entity_tables(tools)
    return [
        ("tool_layouts", {}),
        *(
            (
                f"tool_layouts of a {tool.kind}",
                {"tool": tool.kind, "tool_id": None, "kind": _DISTINCT},
            )
            for tool in tools.installed
        ),
        *(
            (
                f"tool_layouts of a {item}",
                {"tool": item, "tool_id": _Parent(kinds[parent])},
            )
            for item, parent in tools.item_parents.items()
        ),
    ]


def _variants(name: str, tools: ToolSet) -> list[tuple[str, dict[str, Any] | None]]:
    """The cases one table is swept as: once, or once per subject kind."""
    if name == "tool_layouts":
        return [(label, inherit or None) for label, inherit in _layout_targets(tools)]
    if name not in _EVERY_SUBJECT:
        return [(name, None)]
    column, kinds = _EVERY_SUBJECT[name]
    return [(f"{name} on a {kind}", {column: kind}) for kind in kinds(tools)]


@dataclass(frozen=True)
class _People:
    moderator_a: int
    moderator_b: int
    outsider: int

    @property
    def outsiders(self) -> tuple[int, int]:
        return (self.moderator_b, self.outsider)


def _names_a_person(column: sa.Column) -> bool:
    return column.name in ("user_id", "reporter_id", "created_by") or any(
        fk.column.table.name == "users" for fk in column.foreign_keys
    )


def _kind_pairs(table: sa.Table) -> list[tuple[str, str]]:
    """``(kind column, id column)`` pairs naming a subject as a kind and an id."""
    pairs = []
    for column in table.columns:
        if not column.name.endswith("_type"):
            continue
        stem = column.name.removesuffix("_type")
        id_column = table.columns.get(f"{stem}_id")
        if id_column is not None and not id_column.foreign_keys:
            pairs.append((column.name, id_column.name))
    return pairs


_REQUIRED_SQL = sa.text(
    """
    SELECT c.relname, a.attname
    FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
    WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind = 'r'
      AND a.attnum > 0 AND NOT a.attisdropped AND a.attnotnull
      AND NOT a.atthasdef AND a.attidentity = '' AND a.attgenerated = ''
    """
)

_ALLOWED_SQL = sa.text(
    """
    SELECT c.relname, a.attname, pg_get_constraintdef(k.oid)
    FROM pg_constraint k
    JOIN pg_class c ON c.oid = k.conrelid
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.conkey[1]
    WHERE k.contype = 'c' AND cardinality(k.conkey) = 1
      AND c.relnamespace = current_schema()::regnamespace
    """
)


@dataclass(frozen=True)
class _Catalog:
    """What the routed schema itself says about its columns."""

    #: ``(table, column)`` pairs that are NOT NULL with no default.
    required: frozenset[tuple[str, str]]
    #: The values a one-column CHECK names, in its order.
    allowed: dict[tuple[str, str], tuple[str, ...]]

    @classmethod
    async def read(cls, session: AsyncSession) -> _Catalog:
        required = frozenset(
            (t, c) for t, c in (await session.exec(_REQUIRED_SQL)).all()
        )
        allowed: dict[tuple[str, str], tuple[str, ...]] = {}
        for t, c, definition in (await session.exec(_ALLOWED_SQL)).all():
            literals = tuple(
                piece.rsplit("'", 1)[-1] for piece in definition.split("'::")[:-1]
            )
            if literals:
                allowed[(t, c)] = literals
        return cls(required, allowed)


@dataclass
class _Seeder:
    """Builds rows in initiative A on the setup session, parents first."""

    session: AsyncSession
    catalog: _Catalog
    #: The initiative rows are made in; switched to B once A's are done.
    initiative_id: int
    #: Who makes the grants on tool rows, and who they are made to.
    grantor: int
    grantees: tuple[int, ...]
    #: The community's tools, a tool plug-in's among them.
    tools: ToolSet = BUILTIN_TOOLS
    counter: int = 0
    #: How many rows took a ``_DISTINCT`` value, by ``(table, column)``.
    taken: dict[tuple[str, str], int] = field(default_factory=dict)

    def table(self, name: str) -> sa.Table:
        found = SQLModel.metadata.tables.get(name)
        if found is not None:
            return found
        return next(
            table
            for record in self.tools.installed
            for table in (record.table, *record.items)
            if table.name == name
        )

    def required(self, table: sa.Table, column: sa.Column) -> bool:
        """NOT NULL in the schema, with nothing on either side to fill it."""
        return (
            table.name,
            column.name,
        ) in self.catalog.required and column.default is None

    def sets_person(self, table: sa.Table, column: sa.Column) -> bool:
        """Whether a row's person is written into ``column``."""
        return _names_a_person(column) and (
            self.required(table, column)
            or column.name == "created_by"
            or _SHAPES.get(table.name, {}).get(column.name) is _PERSON
        )

    def personal(self, table: sa.Table) -> bool:
        """Whether a row is somebody's, beyond who made it."""
        return any(
            self.sets_person(table, c) for c in table.columns if c.name != "created_by"
        )

    def _kind(self, table: str, column: str) -> str:
        """The kind a row names its subject by: a project where the column's
        CHECK allows one, else the first kind it allows."""
        allowed = self.catalog.allowed.get((table, column))
        if allowed is None or Tool.project.value in allowed:
            return Tool.project.value
        return next(kind for kind in allowed if kind in entity_tables(self.tools))

    def _fill(self, table: sa.Table, column: sa.Column) -> Any:
        """A value for a NOT NULL column nothing else decided: the first its
        CHECK allows, else one of its type."""
        allowed = self.catalog.allowed.get((table.name, column.name))
        if allowed:
            return allowed[0]
        kind = column.type
        enum_class = getattr(kind, "enum_class", None)
        if enum_class is not None:
            return next(iter(enum_class))
        base = getattr(kind, "impl_instance", kind)
        if isinstance(base, sa.Boolean):
            return False
        if isinstance(base, sa.Integer | sa.Numeric):
            return 1
        if isinstance(base, sa.DateTime):
            return datetime.now(UTC)
        if isinstance(base, sa.Date):
            return date.today()
        if isinstance(base, sa.Interval):
            return timedelta(hours=1)
        if isinstance(base, sa.Uuid):
            return uuid.uuid4()
        if isinstance(base, sa.LargeBinary):
            return b"\x00"
        if isinstance(base, sa.JSON):
            return {}
        if isinstance(base, sa.ARRAY):
            return []
        if isinstance(base, sa.String):
            self.counter += 1
            text = f"boundary-{self.counter}"
            return text[: base.length] if base.length else text
        if type(base).__name__ == "TSVECTOR":
            return "boundary"
        raise AssertionError(
            f"{table.name}.{column.name}: no value for type {kind!r}; teach "
            "_Seeder._fill the type or give the table a shape in _SHAPES"
        )

    async def values(
        self, name: str, owner: int, inherit: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Values for a fresh row of ``name`` in A whose person is ``owner``,
        with every parent it needs already written."""
        table = self.table(name)
        values: dict[str, Any] = {}
        for column, value in _SHAPES.get(name, {}).items():
            if isinstance(value, _Parent):
                values[column] = (await self.make(value.table, owner))["id"]
            elif value is _DISTINCT:
                taken = self.taken.get((name, column), 0)
                values[column] = self.catalog.allowed[(name, column)][taken]
                self.taken[(name, column)] = taken + 1
            elif value is not _PERSON:
                values[column] = value
        for column in table.columns:
            if column.name == "initiative_id":
                values["initiative_id"] = self.initiative_id
            elif column.name not in values and self.sets_person(table, column):
                values[column.name] = owner
                # An author column says what kind of author it names.
                if f"{column.name}_kind" in table.c:
                    values[f"{column.name}_kind"] = ActorKind.member.value
        for column, value in (inherit or {}).items():
            if isinstance(value, _Parent):
                values[column] = (await self.make(value.table, owner))["id"]
            elif value is _DISTINCT:
                taken = self.taken.get((name, column), 0)
                values[column] = self.catalog.allowed[(name, column)][taken]
                self.taken[(name, column)] = taken + 1
            elif column in table.c:
                values[column] = value

        for fk in table.foreign_key_constraints:
            local = [element.parent for element in fk.elements]
            target = fk.referred_table.name
            if target in ("users", "initiatives"):
                continue
            if all(c.name in values for c in local):
                continue
            if not any(self.required(table, c) for c in local):
                continue
            target_columns = self.table(target).c
            # The parent takes the row's own anchors (its project, say), so a
            # row and its parents sit under one tool instance.
            passed = {
                k: v
                for k, v in values.items()
                if k in target_columns and target_columns[k].foreign_keys
            }
            parent = await self.make(target, owner, inherit=passed)
            for element in fk.elements:
                values[element.parent.name] = parent[element.column.name]

        for kind_column, id_column in _kind_pairs(table):
            if id_column in values:
                continue
            if kind_column not in values:
                if not self.required(table, table.c[kind_column]):
                    continue
                values[kind_column] = self._kind(name, kind_column)
            kind = values[kind_column]
            # A grant is made on a subject nobody holds one on yet.
            subject = await self.make(
                entity_tables(self.tools).get(kind, kind),
                owner,
                share=name != "resource_grants",
            )
            values[id_column] = subject["id"]

        for column in table.columns:
            if column.name not in values and self.required(table, column):
                values[column.name] = self._fill(table, column)
        return values

    async def make(
        self,
        name: str,
        owner: int,
        inherit: dict[str, Any] | None = None,
        *,
        share: bool = True,
    ) -> dict[str, Any]:
        """Write a row of ``name`` and return it. A tool's row is shared with
        the grantees by name, at write."""
        table = self.table(name)
        values = await self.values(name, owner, inherit)
        statement = sa.insert(table).values(**values).returning(*table.c)
        row = dict((await self.session.exec(statement)).mappings().one())
        if name in _SEEN_WITH:
            child, column = _SEEN_WITH[name]
            await self.make(child, owner, inherit={column: row["id"]})
        tool = self.tools.by_table.get(name)
        if tool is not None and share:
            grants = self.table("resource_grants")
            for person in self.grantees:
                shared = await self.values(
                    "resource_grants",
                    self.grantor,
                    inherit={
                        "resource_type": tool.kind,
                        "resource_id": row["id"],
                        "user_id": person,
                        "level": "write",
                    },
                )
                await self.session.exec(sa.insert(grants).values(**shared))
        return row


def _pk(table: sa.Table, row: Any) -> tuple[Any, ...]:
    return tuple(row[c.name] for c in table.primary_key.columns)


def _matching(table: sa.Table, rows: list[tuple[Any, ...]]) -> sa.ColumnElement[bool]:
    return sa.tuple_(*table.primary_key.columns).in_(rows)


@dataclass
class _Case:
    """One table's rows in A and the rows each person would insert."""

    table: sa.Table
    #: The row each person owns, or one row for all where none is personal.
    rows: dict[int, tuple[Any, ...]]
    #: What each person tries to insert, with its parents already written.
    candidates: dict[int, dict[str, Any]]
    #: What the case's rows are made with beyond the generic fill: the
    #: subject kind, for one of several cases on its table.
    inherit: dict[str, Any] | None = None
    #: One of several cases on its table, each naming a different subject
    #: kind: what is read is counted on its own rows.
    one_of_several: bool = False

    def counted(self) -> sa.ColumnElement[bool] | None:
        """Which rows a read is counted on: the whole table, which holds only
        A's rows, or this case's own."""
        if not self.one_of_several:
            return None
        return _matching(self.table, list(set(self.rows.values())))


def _sqlstate(error: DBAPIError) -> str | None:
    orig = error.orig
    return getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )


async def _attempt(session: AsyncSession, statement: sa.Executable) -> int | str:
    """Run ``statement`` in a savepoint that is always rolled back: the rows
    it touched, or the SQLSTATE it raised."""
    savepoint = await session.begin_nested()
    try:
        touched = (await session.exec(statement)).rowcount
    except DBAPIError as error:
        await savepoint.rollback()
        return _sqlstate(error) or repr(error.orig)
    await savepoint.rollback()
    return touched


async def _count(session: AsyncSession, table: sa.Table, where: Any = None) -> int:
    statement = sa.select(sa.func.count()).select_from(table)
    if where is not None:
        statement = statement.where(where)
    return (await session.exec(statement)).scalar_one()


def _insert(case: _Case, person: int) -> sa.Insert:
    # Inline, so no RETURNING asks the read policy about the new row too.
    return sa.insert(case.table).values(**case.candidates[person]).inline()


def _blind_writes(case: _Case) -> dict[str, sa.Executable]:
    """Each writing command over the whole table, reading no column, so the
    command's own policy alone decides which rows it reaches."""
    table = case.table
    first = next(iter(table.primary_key.columns))
    some_row = next(iter(case.rows.values()))
    return {
        "UPDATE": sa.update(table).values({first.name: some_row[0]}),
        "DELETE": sa.delete(table),
    }


def _own_writes(case: _Case, person: int) -> dict[str, sa.Executable]:
    """Each writing command on ``person``'s own row in A, or adding one."""
    table = case.table
    own = _matching(table, [case.rows[person]])
    first = next(iter(table.primary_key.columns))
    return {
        "INSERT": _insert(case, person),
        "UPDATE": sa.update(table).where(own).values({first.name: first}),
        "DELETE": sa.delete(table).where(own),
    }


def _locating(table: sa.Table, paths: dict[str, Any]) -> list[str]:
    """The columns that say which initiative a row is in: its own
    ``initiative_id``, its foreign keys to initiative-scoped rows, and the
    ``(kind, id)`` pairs naming its subject."""
    columns = ["initiative_id"] if "initiative_id" in table.c else []
    for fk in table.foreign_key_constraints:
        if fk.referred_table.name in paths:
            columns += [element.parent.name for element in fk.elements]
    for pair in _kind_pairs(table):
        columns += pair
    return list(dict.fromkeys(columns))


@dataclass
class _Move:
    """Moving A's moderator's own row into B: the columns it sets, and the
    row's primary key once moved."""

    values: dict[str, Any]
    moved_pk: tuple[Any, ...]

    def statement(self, case: _Case, own: tuple[Any, ...]) -> sa.Update:
        """The move of ``own`` alone."""
        return (
            sa.update(case.table)
            .where(_matching(case.table, [own]))
            .values(**self.values)
        )

    def blind(self, case: _Case) -> sa.Update:
        """The move of every row the writer may update, reading no column:
        a statement that reads one is also held to the read policy on the
        row it writes, which would answer before the write policy did."""
        return sa.update(case.table).values(**self.values)


def _move(
    case: _Case, own: tuple[Any, ...], in_b: dict[str, Any], paths: dict[str, Any]
) -> _Move:
    """Repoint ``own`` at the parents of ``in_b``, a row built in B."""
    values = {c: in_b[c] for c in _locating(case.table, paths) if c in in_b}
    keys = [c.name for c in case.table.primary_key.columns]
    moved = tuple(values.get(k, v) for k, v in zip(keys, own, strict=True))
    return _Move(values, moved)


def _initiative_of(table: sa.Table, paths: dict[str, Any]) -> str:
    """The initiative of a row ``r`` of ``table``, by the lookup the change
    capture stamps events with, in the community whose paths are ``paths``."""
    return initiative_of(table.name, "r", paths=paths)


async def _initiative_of_row(
    session: AsyncSession,
    table: sa.Table,
    row: tuple[Any, ...],
    paths: dict[str, Any],
) -> int | None:
    """The initiative one row of ``table`` is in."""
    keys = [c.name for c in table.primary_key.columns]
    where = " AND ".join(f"r.{k} = :{k}" for k in keys)
    statement = sa.text(
        f"SELECT {_initiative_of(table, paths)} FROM {table.name} r WHERE {where}"
    )
    result = await session.exec(statement, params=dict(zip(keys, row, strict=True)))
    return result.scalar_one_or_none()


async def _outside(
    session: AsyncSession, case: _Case, initiative_id: int, paths: dict[str, Any]
) -> int:
    """How many of the rows made for ``case`` are not in ``initiative_id``."""
    rows = set(case.rows.values())
    columns = ", ".join(f"r.{c.name}" for c in case.table.primary_key.columns)
    statement = sa.text(
        f"SELECT {columns} FROM {case.table.name} r"
        f" WHERE {_initiative_of(case.table, paths)} = :initiative_id"
    )
    result = await session.exec(statement, params={"initiative_id": initiative_id})
    return len(rows - {tuple(row) for row in result.all()})


async def _keep_only(
    session: AsyncSession, table: sa.Table, initiative_id: int, paths: dict[str, Any]
) -> None:
    """Delete every row of ``table`` not in ``initiative_id``, with triggers
    off, so whatever a statement on the whole table reaches is A's."""
    await session.exec(sa.text("SET LOCAL session_replication_role = replica"))
    await session.exec(
        sa.text(
            f"DELETE FROM {table.name} r"
            f" WHERE {_initiative_of(table, paths)} IS DISTINCT FROM :initiative_id"
        ),
        params={"initiative_id": initiative_id},
    )
    await session.exec(sa.text("SET LOCAL session_replication_role = origin"))


async def _tools_on(
    role_session: Callable[[str], Awaitable[AsyncSession]],
    person: int,
    guild_id: int,
    initiative_id: int,
    tools: ToolSet,
) -> None:
    """Assert every tool is switched on in ``initiative_id`` for ``person``."""
    session = await role_session("app_user")
    context = await route_as(session, user_id=person, guild_id=guild_id)
    await session.rollback()
    expected = {f"{initiative_id}:{tool.kind}" for tool in tools}
    assert expected <= set(context.enabled_tools)


@pytest.mark.parametrize("converted", [False, True], ids=["installed", "converted"])
async def test_nobody_outside_an_initiative_reaches_its_rows(
    converted: bool,
    session: AsyncSession,
    acting_user: Callable[..., Awaitable[Actor]],
    reading_as: Callable[[int, int], Awaitable[AsyncSession]],
    role_session: Callable[[str], Awaitable[AsyncSession]],
    client: AsyncClient,
) -> None:
    # A and B are each in the hands of a moderator, the role with every tool
    # permission and full access to the initiative's content.
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild = admin.guild
    initiative_a = admin.initiative.id
    initiative_b = await create_initiative(session, guild, admin.user)
    initiative_b_id = initiative_b.id
    assert initiative_b_id is not None
    moderator_a = await acting_user(
        guild=guild, initiative=admin.initiative, initiative_role="moderator"
    )
    moderator_b = await acting_user(
        guild=guild, initiative=initiative_b, initiative_role="moderator"
    )
    outsider = await acting_user(guild=guild)
    people = _People(moderator_a.user.id, moderator_b.user.id, outsider.user.id)
    everyone = (people.moderator_a, people.moderator_b, people.outsider)

    # The operations community holds every table the others do and its own.
    await make_operations_community(session, guild.id)
    # A tool plug-in's tool, installed by the community's seat, is swept as a
    # built-in tool is: its tables are the community's paths.
    await session.commit()
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    install = await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(guild.id)
    assert [tool.kind for tool in tools.installed] == [
        f"counter_group.{COUNTERS_UID.lower()}"
    ]
    paths = paths_for(tools)
    not_a_moderators = _not_a_moderators(tools)
    await route_session_to_guild(session, guild.id)
    seeder = _Seeder(
        session,
        await _Catalog.read(session),
        initiative_a,
        grantor=people.moderator_a,
        grantees=people.outsiders,
        tools=tools,
    )
    cases: dict[str, _Case] = {}
    unseeded: dict[str, str] = {}
    for name in paths:
        table = seeder.table(name)
        owners = everyone if seeder.personal(table) else (people.moderator_a,)
        variants = _variants(name, tools)
        for label, inherit in variants:
            savepoint = await session.begin_nested()
            try:
                rows = {
                    p: _pk(table, await seeder.make(name, p, inherit)) for p in owners
                }
                candidates = {
                    p: await seeder.values(name, p, inherit) for p in everyone
                }
            except (DBAPIError, AssertionError) as error:
                await savepoint.rollback()
                unseeded[label] = str(error).splitlines()[0]
                continue
            await savepoint.commit()
            cases[label] = _Case(
                table,
                {p: rows.get(p, rows[people.moderator_a]) for p in everyone},
                candidates,
                inherit,
                one_of_several=len(variants) > 1,
            )
    assert not unseeded, (
        "The sweep could not put a row of these tables in an initiative; teach "
        f"_Seeder or give the table a shape in _SHAPES: {unseeded}"
    )

    swept = {case.table.name for case in cases.values()}
    plugin_tables = {
        table.name for tool in tools.installed for table in (tool.table, *tool.items)
    }
    assert plugin_tables <= swept, plugin_tables - swept
    for kind in _installed_kinds(tools):
        assert f"comments on a {kind}" in cases
        assert f"search_entries on a {kind}" in cases
    # The tool plug-in's rows were indexed as they were written, and those
    # entries are among the rows the outsiders below read none of.
    indexed = await session.exec(
        sa.select(sa.func.count())
        .select_from(seeder.table("search_entries"))
        .where(
            seeder.table("search_entries").c.entity_type.in_(_installed_kinds(tools)),
            seeder.table("search_entries").c.chunk_ix == 0,
        )
    )
    assert indexed.scalar_one() > 0

    misplaced = [
        name
        for name, case in cases.items()
        if await _outside(session, case, initiative_a, paths)
    ]
    assert not misplaced, f"rows meant for initiative A that are not in it: {misplaced}"
    # The community's other rows (B's, and its own) are cleared, so the rows a
    # statement on a whole table reaches are A's.
    for table in {case.table for case in cases.values()}:
        await _keep_only(session, table, initiative_a, paths)
    await session.commit()
    if converted:
        # Counters turned back into the built-in tool and converted again, as
        # 20261119_0619 does in a community that uses it: every check below
        # then holds for the converted tables.
        install = {**install, "id": await convert_counters(session, guild.id)}
        await route_session_to_guild(session, guild.id)

    await _tools_on(role_session, people.moderator_a, guild.id, initiative_a, tools)
    await _tools_on(role_session, people.moderator_b, guild.id, initiative_b_id, tools)

    failures: list[str] = []
    for person, who in (
        (people.moderator_b, "a moderator of B"),
        (people.outsider, "a member of no initiative"),
    ):
        reader = await reading_as(person, guild.id)
        for name, case in cases.items():
            if (seen := await _count(reader, case.table, case.counted())) != 0:
                failures.append(f"{name}: {who} reads {seen} of A's rows")
            if (inserted := await _attempt(reader, _insert(case, person))) != _REFUSED:
                failures.append(f"{name}: {who} can INSERT in A ({inserted})")
            for command, statement in _blind_writes(case).items():
                if (answer := await _attempt(reader, statement)) not in (0, _REFUSED):
                    failures.append(f"{name}: {who} can {command} in A ({answer})")
        await reader.rollback()

    # Rows built in B, with every parent in B, for A's moderator, who is not
    # in B, to move A's rows to and to insert. Made after A's rows were the
    # only ones, so the whole-table statements above reached A's alone.
    readers = {
        "A's moderator": await reading_as(people.moderator_a, guild.id),
        "the community admin": await reading_as(admin.user.id, guild.id),
    }
    for name, case in cases.items():
        who = (
            "the community admin"
            if case.table.name in _ADMINISTERED
            else "A's moderator"
        )
        reader = readers[who]
        own = _matching(case.table, [case.rows[people.moderator_a]])
        if (seen := await _count(reader, case.table, own)) != 1:
            failures.append(f"{name}: {who} reads {seen} of its own row")
        for command, statement in _own_writes(case, people.moderator_a).items():
            if command in not_a_moderators.get(case.table.name, ()):
                continue
            if (answer := await _attempt(reader, statement)) != 1:
                failures.append(f"{name}: {who} cannot {command} in A ({answer})")
    for reader in readers.values():
        await reader.rollback()

    # Rows built in B, every parent in B, for A's moderator, who is not in B,
    # to move its own rows of A onto and to insert. Made after the
    # whole-table statements above, which were to reach A's rows alone.
    seeder.initiative_id = initiative_b_id
    seeder.grantees = (people.moderator_a,)
    moves: dict[str, sa.Update] = {}
    in_b: dict[str, dict[str, Any]] = {}
    for name, case in cases.items():
        if case.table.name in _ADMINISTERED:
            continue
        own = case.rows[people.moderator_a]
        in_b[name] = await seeder.values(
            case.table.name, people.moderator_a, case.inherit
        )
        move = _move(case, own, in_b[name], paths)
        moves[name] = move.blind(case)
        # Each lands its row in B: the move with triggers and foreign keys
        # off (a collection's entries hold it to its initiative by key).
        savepoint = await session.begin_nested()
        await session.exec(sa.text("SET LOCAL session_replication_role = replica"))
        await session.exec(move.statement(case, own))
        moved = await _initiative_of_row(session, case.table, move.moved_pk, paths)
        await savepoint.rollback()
        savepoint = await session.begin_nested()
        insert = sa.insert(case.table).values(**in_b[name])
        made = (await session.exec(insert.returning(*case.table.primary_key))).one()
        inserted = await _initiative_of_row(session, case.table, tuple(made), paths)
        await savepoint.rollback()
        assert (moved, inserted) == (initiative_b_id, initiative_b_id), (
            f"{name}: a row moved or built for B lands in {moved} and {inserted}"
        )
    # The freeze guards take a parent the writer cannot see for a frozen one
    # and refuse before the row security is asked; they are set aside here so
    # that the row security answers a move on its own.
    await session.exec(_SET_ASIDE_FREEZE_GUARDS)
    await session.commit()

    reader = await reading_as(people.moderator_a, guild.id)
    for name, move in moves.items():
        refused = {_REFUSED}
        if "UPDATE" in not_a_moderators.get(cases[name].table.name, ()):
            # Updating nothing at all, its move reaches no row or meets the
            # table's own refusal of any change.
            refused |= {0, _FROZEN}
        if (answer := await _attempt(reader, move)) not in refused:
            failures.append(f"{name}: A's moderator moves its row into B ({answer})")
        insert = sa.insert(cases[name].table).values(**in_b[name]).inline()
        if (answer := await _attempt(reader, insert)) != _REFUSED:
            failures.append(f"{name}: A's moderator inserts a row into B ({answer})")
    await reader.rollback()

    # A switched-off tool's rows read as absent to A's own moderator: each
    # tool off in turn, then every switch row gone, since no row is off.
    governed = {
        name: governing[0]
        for name, case in cases.items()
        if (governing := governing_walk(case.table.name, paths)) is not None
    }
    every = {tool.kind for tool in tools}
    assert {tool.kind for tool in governed.values()} == every
    for off in [{tool.kind} for tool in tools] + [every]:
        await route_session_to_guild(session, guild.id)
        if off == every:
            await session.exec(
                sa.delete(InitiativeRule).where(
                    InitiativeRule.initiative_id == initiative_a,
                    InitiativeRule.initiative_role_id.is_(None),
                    InitiativeRule.install_id.is_(None),
                )
            )
        else:
            await write_switches(
                session, initiative_a, {tool: tool.kind not in off for tool in tools}
            )
        await session.commit()
        state = "no switch rows" if len(off) > 1 else f"{next(iter(off))} off"
        reader = await reading_as(people.moderator_a, guild.id)
        for name, tool in governed.items():
            if tool.kind not in off:
                continue
            case = cases[name]
            if (seen := await _count(reader, case.table, case.counted())) != 0:
                failures.append(f"{name}: A's moderator reads {seen} with {state}")
            if (
                answer := await _attempt(reader, _insert(case, people.moderator_a))
            ) != _REFUSED:
                failures.append(
                    f"{name}: A's moderator can INSERT with {state} ({answer})"
                )
            for command, statement in _blind_writes(case).items():
                if (answer := await _attempt(reader, statement)) not in (0, _REFUSED):
                    failures.append(
                        f"{name}: A's moderator can {command} with {state} ({answer})"
                    )
        await reader.rollback()

    await route_session_to_guild(session, guild.id)
    await write_switches(session, initiative_a, dict.fromkeys(tools, True))
    await session.commit()
    plugin_kinds = {
        kind
        for tool in tools.installed
        for kind in (tool.kind, *(child.value for child in tool.children))
    }
    plugin_cases = {
        name: case
        for name, case in cases.items()
        if (name in governed and governed[name].installed)
        or plugin_kinds & set((case.inherit or {}).values())
    }
    assert {case.table.name for case in plugin_cases.values()} >= plugin_tables
    everybody = {
        "A's moderator": people.moderator_a,
        "the community admin": admin.user.id,
    }

    def in_a(case: _Case) -> sa.ColumnElement[bool]:
        """The case's own rows in A: B holds rows of these tables by now."""
        return _matching(case.table, list(set(case.rows.values())))

    def writes_in_a(case: _Case) -> dict[str, sa.Executable]:
        """An INSERT into A, and an UPDATE and DELETE of the case's rows in A."""
        key = next(iter(case.table.primary_key.columns))
        return {
            "INSERT": _insert(case, people.moderator_a),
            "UPDATE": sa.update(case.table).where(in_a(case)).values({key.name: key}),
            "DELETE": sa.delete(case.table).where(in_a(case)),
        }

    # A tool plug-in's placement is where its tool is there at all. Placed in
    # B and not in A, its rows in A are to each of A's people, the community
    # admin included, what they are with its switch in A off; placed in A
    # again, A's moderator reads and writes them.
    plugin_path = seat.g(f"/plugins/{install['id']}")
    member_a = await acting_user(
        guild=guild, initiative=admin.initiative, initiative_role="member"
    )
    in_a_people = {**everybody, "A's member": member_a.user.id}

    async def place(*initiative_ids: int) -> None:
        placed = await client.patch(
            plugin_path,
            headers=seat.headers,
            json={"placed_initiative_ids": list(initiative_ids)},
        )
        assert placed.status_code == 200, placed.text

    async def answers() -> dict[str, dict[str, tuple[int | str, ...]]]:
        """What each of A's people reads of every tool plug-in row in A, and
        what each write over them answers."""
        found: dict[str, dict[str, tuple[int | str, ...]]] = {}
        for who, person in in_a_people.items():
            reader = await reading_as(person, guild.id)
            found[who] = {
                name: (
                    await _count(reader, case.table, in_a(case)),
                    *[
                        await _attempt(reader, statement)
                        for statement in writes_in_a(case).values()
                    ],
                )
                for name, case in plugin_cases.items()
            }
            await reader.rollback()
        return found

    await place(initiative_b_id)
    unplaced = await answers()
    await place(initiative_a, initiative_b_id)
    placed = await answers()
    await route_session_to_guild(session, guild.id)
    await write_switches(
        session, initiative_a, {tool: not tool.installed for tool in tools}
    )
    await session.commit()
    switched_off = await answers()
    await route_session_to_guild(session, guild.id)
    await write_switches(session, initiative_a, dict.fromkeys(tools, True))
    await session.commit()
    for who in in_a_people:
        for name in plugin_cases:
            if unplaced[who][name] != switched_off[who][name]:
                failures.append(
                    f"{name}: {who} answers {unplaced[who][name]} with it placed"
                    f" in B alone, {switched_off[who][name]} with it off in A"
                )
    moderator = "A's moderator"
    for name in plugin_cases:
        if placed[moderator][name][0] == 0:
            failures.append(f"{name}: A's moderator reads none of it placed in A")
        if name in governed and unplaced[moderator][name][0] != 0:
            failures.append(f"{name}: A's moderator reads it placed in B alone")

    # A tool plug-in's state hides its tool from everyone, the community
    # admin included, as no switch does: suspended by staff, and uninstalled
    # by its community while its content waits out the deletion window. Read
    # only, its rows read and refuse every write. Installed again within the
    # window, everything is back.

    async def sweep_state(state: str, *, reads: bool) -> None:
        """Every row of the tool plug-in's in A reads as ``reads`` says, to A's
        moderator and the community admin, and none is written. With it read
        only, only the tool's own rows are held to that here: what is said,
        reacted and linked on them, by the sharing and holds sweep below."""
        for who, person in everybody.items():
            reader = await reading_as(person, guild.id)
            for name, case in plugin_cases.items():
                own = _matching(case.table, [case.rows[people.moderator_a]])
                seen = await _count(reader, case.table, own)
                if seen != int(reads):
                    failures.append(f"{name}: {who} reads {seen} with it {state}")
                if reads and case.table.name not in plugin_tables:
                    continue
                for command, statement in writes_in_a(case).items():
                    answer = await _attempt(reader, statement)
                    if answer not in (
                        (_REFUSED,) if command == "INSERT" else (0, _REFUSED)
                    ):
                        failures.append(
                            f"{name}: {who} can {command} with it {state} ({answer})"
                        )
            await reader.rollback()

    async def install_state(**values: Any) -> None:
        statement = pg_insert(PluginInstall).values(
            guild_id=guild.id,
            install_id=install["id"],
            listing_uid=COUNTERS_UID,
            enabled=True,
            **values,
        )
        await session.exec(
            statement.on_conflict_do_update(
                index_elements=["guild_id", "install_id"], set_=values
            )
        )
        await session.commit()

    await install_state(suspended_at=datetime.now(UTC))
    await sweep_state("suspended", reads=False)
    await install_state(suspended_at=None, status=PluginInstallStatus.read_only.value)
    await sweep_state("read-only", reads=True)
    await install_state(status=PluginInstallStatus.active.value)

    removed = await client.delete(
        plugin_path, headers=seat.headers, params={"delete_content": "true"}
    )
    assert removed.status_code == 204, removed.text
    await sweep_state("uninstalled", reads=False)
    back = await client.post(
        seat.g("/plugins/"), headers=seat.headers, json={"listing_uid": COUNTERS_UID}
    )
    assert back.status_code == 201, back.text
    reader = await reading_as(people.moderator_a, guild.id)
    for name, case in plugin_cases.items():
        own = _matching(case.table, [case.rows[people.moderator_a]])
        if (seen := await _count(reader, case.table, own)) != 1:
            failures.append(f"{name}: A's moderator reads {seen} once reinstalled")
        for command, statement in _own_writes(case, people.moderator_a).items():
            if command in not_a_moderators.get(case.table.name, ()):
                continue
            if (answer := await _attempt(reader, statement)) != 1:
                failures.append(
                    f"{name}: A's moderator cannot {command} once reinstalled ({answer})"
                )
    await reader.rollback()
    for person in people.outsiders:
        reader = await reading_as(person, guild.id)
        for name, case in plugin_cases.items():
            if (seen := await _count(reader, case.table, in_a(case))) != 0:
                failures.append(f"{name}: an outsider reads {seen} once reinstalled")
        await reader.rollback()

    # A custom role made after the install holds the tool plug-in's keys as a
    # built-in tool's, written from the community's tools: its member adds
    # the tool's row in A once the role is given its create permission, and
    # not before.
    tool = tools.installed[0]
    made = await client.post(
        admin.g(f"/initiatives/{initiative_a}/roles"),
        headers=admin.headers,
        json={"name": "tallier", "display_name": "Tallier"},
    )
    assert made.status_code == 201, made.text
    tallier = await acting_user(
        guild=guild, initiative=admin.initiative, initiative_role="tallier"
    )
    adding = sa.insert(tool.table).values(initiative_id=initiative_a, name="T").inline()
    for given in (False, True):
        await route_session_to_guild(session, guild.id)
        given_it = await session.exec(
            sa.update(InitiativeRule)
            .where(
                InitiativeRule.initiative_role_id == made.json()["id"],
                InitiativeRule.key == tool.create_permission,
            )
            .values(enabled=given)
        )
        assert given_it.rowcount == 1
        await session.commit()
        reader = await reading_as(tallier.user.id, guild.id)
        if (answer := await _attempt(reader, adding)) != (1 if given else _REFUSED):
            failures.append(f"a custom role given create={given} adds: {answer}")
        await reader.rollback()

    assert not failures, "\n".join(failures)


async def test_the_universal_routes_keep_a_tool_plugins_rows_in_their_initiative(
    session: AsyncSession,
    acting_user: Callable[..., Awaitable[Actor]],
    reading_as: Callable[[int, int], Awaitable[AsyncSession]],
    client: AsyncClient,
) -> None:
    """A tool plug-in's row and its item, in initiative A and shared by name
    with a moderator of B and a member of no initiative, are archived,
    commented on, found and taken out of the trash through the universal
    routes by A's moderator, and by neither of the others."""
    from app.services.tenant.soft_delete import trash

    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild = admin.guild
    initiative_b = await create_initiative(session, guild, admin.user)
    moderator_a = await acting_user(
        guild=guild, initiative=admin.initiative, initiative_role="moderator"
    )
    moderator_b = await acting_user(
        guild=guild, initiative=initiative_b, initiative_role="moderator"
    )
    outsider = await acting_user(guild=guild)
    await session.commit()
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(guild.id)
    tool = tools.installed[0]
    (item_kind,) = (child.value for child in tool.children)
    await route_session_to_guild(session, guild.id)
    seeder = _Seeder(
        session,
        await _Catalog.read(session),
        admin.initiative.id,
        grantor=moderator_a.user.id,
        grantees=(moderator_b.user.id, outsider.user.id),
        tools=tools,
    )
    item_row = await seeder.make(tool.items[0].name, moderator_a.user.id)
    rows = {
        tool.kind: item_row[f"{tool.kind.split('.')[0]}_id"],
        item_kind: item_row["id"],
    }
    await session.commit()

    for actor in (moderator_b, outsider):
        for kind, row_id in rows.items():
            for route in ("archive", "unarchive"):
                response = await client.post(
                    actor.g(f"/{route}/{kind}/{row_id}"), headers=actor.headers
                )
                assert response.status_code == 404, (route, kind, response.text)
            response = await client.post(
                actor.g("/comments/"),
                headers=actor.headers,
                json={"subject_type": kind, "subject_id": row_id, "content": "hi"},
            )
            assert response.status_code == 404, (kind, response.text)
            response = await client.get(
                actor.g("/comments/"),
                headers=actor.headers,
                params={"subject_type": kind, "subject_id": row_id},
            )
            assert response.status_code == 404, (kind, response.text)
            response = await client.get(
                actor.g("/search/"),
                headers=actor.headers,
                params={"search": "boundary", "types": [kind]},
            )
            assert response.status_code == 200, response.text
            assert response.json()["items"] == [], kind

    # A kind the community has not installed is not found.
    response = await client.post(
        moderator_a.g(f"/archive/stranger.{'x' * 14}/1"), headers=moderator_a.headers
    )
    assert response.status_code == 404, response.text

    for kind, row_id in rows.items():
        for route in ("archive", "unarchive"):
            response = await client.post(
                moderator_a.g(f"/{route}/{kind}/{row_id}"), headers=moderator_a.headers
            )
            assert response.status_code == 200, (route, kind, response.text)
            assert response.json()["entity_type"] == kind
        response = await client.post(
            moderator_a.g("/comments/"),
            headers=moderator_a.headers,
            json={"subject_type": kind, "subject_id": row_id, "content": "hi"},
        )
        assert response.status_code == 201, (kind, response.text)
        response = await client.get(
            moderator_a.g("/search/"),
            headers=moderator_a.headers,
            params={"search": "boundary", "types": [kind]},
        )
        assert [hit["entity_id"] for hit in response.json()["items"]] == [row_id]

    # Trashed by A's moderator, the item is theirs to take back out, and the
    # others do not find it in the bin.
    located = locate(tools, item_kind)
    assert located is not None
    mine = await reading_as(moderator_a.user.id, guild.id)
    row = await load_row(mine, located, tools, rows[item_kind])
    assert row is not None
    await trash(mine, row, deleted_by_user_id=moderator_a.user.id)
    await mine.commit()
    for actor in (moderator_b, outsider):
        response = await client.post(
            actor.g(f"/trash/{item_kind}/{rows[item_kind]}/restore"),
            headers=actor.headers,
        )
        assert response.status_code == 404, response.text
    response = await client.get(admin.g("/trash/"), headers=admin.headers)
    assert (item_kind, rows[item_kind]) in {
        (item["entity_type"], item["entity_id"]) for item in response.json()["items"]
    }, response.text
    response = await client.post(
        moderator_a.g(f"/trash/{item_kind}/{rows[item_kind]}/restore"),
        headers=moderator_a.headers,
    )
    assert response.status_code == 200, response.text


async def test_the_tool_plugin_routes_keep_its_rows_in_their_initiative(
    session: AsyncSession,
    acting_user: Callable[..., Awaitable[Actor]],
    reading_as: Callable[[int, int], Awaitable[AsyncSession]],
    client: AsyncClient,
) -> None:
    """A tool plug-in's row and its item, in initiative A and shared by name
    with a moderator of B and a member of no initiative, are read, listed,
    changed, added to, copied, acted on and watched through the tool plug-in
    routes by A's moderator, and by neither of the others: each of their
    requests, A's list, a new row in A and a step of the item's count among
    them, is answered 404."""
    from app.api.content_socket import tool_authorizer

    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild = admin.guild
    initiative_b = await create_initiative(session, guild, admin.user)
    moderator_a = await acting_user(
        guild=guild, initiative=admin.initiative, initiative_role="moderator"
    )
    moderator_b = await acting_user(
        guild=guild, initiative=initiative_b, initiative_role="moderator"
    )
    outsider = await acting_user(guild=guild)
    await session.commit()
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(guild.id)
    tool = tools.installed[0]
    (item_kind,) = (child.value for child in tool.children)
    await route_session_to_guild(session, guild.id)
    seeder = _Seeder(
        session,
        await _Catalog.read(session),
        admin.initiative.id,
        grantor=moderator_a.user.id,
        grantees=(moderator_b.user.id, outsider.user.id),
        tools=tools,
    )
    item_row = await seeder.make(tool.items[0].name, moderator_a.user.id)
    tool_id = item_row[f"{tool.kind.split('.')[0]}_id"]
    rows = {tool.kind: tool_id, item_kind: item_row["id"]}
    await session.commit()

    def addressed(kind: str, row_id: int) -> list[tuple[str, str, Any]]:
        """Every route that names one of A's rows, and its body."""
        at = f"/plugin-tools/{kind}/{row_id}"
        return [
            ("GET", at, None),
            ("PATCH", at, {"name": "Moved"}),
            ("POST", f"{at}/duplicate", {}),
            ("POST", f"{at}/actions/reset_all", {}),
            ("POST", f"{at}/step", {"field": "count"}),
        ]

    under = [
        ("GET", f"/plugin-tools/{item_kind}/?parent_id={tool_id}", None),
        ("POST", f"/plugin-tools/{item_kind}/", {"parent_id": tool_id, "name": "X"}),
    ]
    in_a = f"/plugin-tools/{tool.kind}/?initiative_id={admin.initiative.id}"
    new_in_a = {"initiative_id": admin.initiative.id, "name": "Mine"}

    for actor in (moderator_b, outsider):
        for kind, row_id in rows.items():
            for method, path, body in addressed(kind, row_id):
                response = await client.request(
                    method, actor.g(path), headers=actor.headers, json=body
                )
                assert response.status_code == 404, (method, path, response.text)
        for method, path, body in under:
            response = await client.request(
                method, actor.g(path), headers=actor.headers, json=body
            )
            assert response.status_code == 404, (method, path, response.text)
        response = await client.get(actor.g(in_a), headers=actor.headers)
        assert response.status_code == 404, response.text
        response = await client.post(
            actor.g(f"/plugin-tools/{tool.kind}/"), headers=actor.headers, json=new_in_a
        )
        assert response.status_code == 404, response.text
        watching = await reading_as(actor.user.id, guild.id)
        assert (
            await tool_authorizer(guild.id, tool.kind, tool_id)(watching, None) is None
        )
        await watching.rollback()

    for method, path, body in under:
        response = await client.request(
            method, moderator_a.g(path), headers=moderator_a.headers, json=body
        )
        assert response.status_code in (200, 201), (method, path, response.text)
    for kind, row_id in rows.items():
        for method, path, body in addressed(kind, row_id):
            if path.endswith("reset_all") and kind == item_kind:
                continue
            if path.endswith("step") and kind == tool.kind:
                continue
            response = await client.request(
                method, moderator_a.g(path), headers=moderator_a.headers, json=body
            )
            assert response.status_code in (200, 201), (method, path, response.text)
    response = await client.get(moderator_a.g(in_a), headers=moderator_a.headers)
    assert tool_id in {row["id"] for row in response.json()["items"]}, response.text
    response = await client.post(
        moderator_a.g(f"/plugin-tools/{tool.kind}/"),
        headers=moderator_a.headers,
        json=new_in_a,
    )
    assert response.status_code == 201, response.text
    watching = await reading_as(moderator_a.user.id, guild.id)
    assert await tool_authorizer(guild.id, tool.kind, tool_id)(watching, None)
    await watching.rollback()


async def test_tags_and_links_keep_a_tool_plugins_rows_in_their_initiative(
    session: AsyncSession,
    acting_user: Callable[..., Awaitable[Actor]],
    client: AsyncClient,
) -> None:
    """A tool plug-in's row and its item, in initiative A and shared by name
    with a moderator of B and a member of no initiative, are tagged, linked
    and have their tags and links listed by A's moderator, and by neither of
    the others. A kind the community does not have is not found."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild = admin.guild
    initiative_b = await create_initiative(session, guild, admin.user)
    moderator_a = await acting_user(
        guild=guild, initiative=admin.initiative, initiative_role="moderator"
    )
    moderator_b = await acting_user(
        guild=guild, initiative=initiative_b, initiative_role="moderator"
    )
    outsider = await acting_user(guild=guild)
    await session.commit()
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(guild.id)
    tool = tools.installed[0]
    (item_kind,) = (child.value for child in tool.children)
    await route_session_to_guild(session, guild.id)
    seeder = _Seeder(
        session,
        await _Catalog.read(session),
        admin.initiative.id,
        grantor=moderator_a.user.id,
        grantees=(moderator_b.user.id, outsider.user.id),
        tools=tools,
    )
    item_row = await seeder.make(tool.items[0].name, moderator_a.user.id)
    rows = {
        tool.kind: item_row[f"{tool.kind.split('.')[0]}_id"],
        item_kind: item_row["id"],
    }
    tag = await create_tag(session, guild)
    await session.commit()
    link = {
        "source": {"type": item_kind, "id": rows[item_kind]},
        "relationship_type": "related_to",
        "target": {"type": tool.kind, "id": rows[tool.kind]},
    }

    async def tag_and_link(actor: Actor) -> list[int]:
        """Every write's status for ``actor``, in one order."""
        statuses = [
            (
                await client.put(
                    actor.g(f"/tools/{tool.kind}/{rows[tool.kind]}/tags"),
                    headers=actor.headers,
                    json={"tag_ids": [tag.id]},
                )
            ).status_code,
            (
                await client.put(
                    actor.g(f"/tools/{tool.kind}/{rows[tool.kind]}/comments"),
                    headers=actor.headers,
                    json={"comments_enabled": True},
                )
            ).status_code,
            (
                await client.post(
                    actor.g("/relationships/"), headers=actor.headers, json=link
                )
            ).status_code,
        ]
        for kind, row_id in rows.items():
            response = await client.post(
                actor.g("/tags/bulk"),
                headers=actor.headers,
                json={
                    "target_type": kind,
                    "target_ids": [row_id],
                    "add_tag_ids": [tag.id],
                },
            )
            statuses.append(response.status_code)
        return statuses

    for actor in (moderator_b, outsider):
        assert await tag_and_link(actor) == [404] * 5, actor
    assert await tag_and_link(moderator_a) == [200, 200, 201, 200, 200]

    for actor in (moderator_b, outsider):
        for kind, row_id in rows.items():
            for path in ("/relationships/", "/relationships/neighbourhood"):
                response = await client.get(
                    actor.g(path),
                    headers=actor.headers,
                    params={"entity": f"{kind}:{row_id}"},
                )
                assert response.status_code == 404, (path, kind, response.text)
            response = await client.put(
                actor.g("/relationships/"),
                headers=actor.headers,
                params={
                    "entity": f"{kind}:{row_id}",
                    "relationship_type": "related_to",
                    "other_type": tool.kind,
                },
                json=[],
            )
            assert response.status_code == 404, (kind, response.text)
            response = await client.get(
                actor.g(f"/tags/{tag.id}/entities"),
                headers=actor.headers,
                params={"kind": kind},
            )
            assert response.json()["items"] == [], (kind, response.text)
        response = await client.get(
            actor.g(f"/tags/{tag.id}/counts"), headers=actor.headers
        )
        assert response.json()["counts"] == {}, response.text

    for kind, row_id in rows.items():
        response = await client.get(
            moderator_a.g("/relationships/"),
            headers=moderator_a.headers,
            params={"entity": f"{kind}:{row_id}", "relationship_type": "related_to"},
        )
        assert [e["other"]["type"] for e in response.json()] == [
            next(other for other in rows if other != kind)
        ], response.text
        response = await client.get(
            moderator_a.g(f"/tags/{tag.id}/entities"),
            headers=moderator_a.headers,
            params={"kind": kind},
        )
        assert [i["entity_id"] for i in response.json()["items"]] == [row_id]

    # A kind the community has not installed is not found.
    stranger = f"stranger.{'x' * 14}"
    for response in (
        await client.put(
            moderator_a.g(f"/tools/{stranger}/1/tags"),
            headers=moderator_a.headers,
            json={"tag_ids": [tag.id]},
        ),
        await client.post(
            moderator_a.g("/tags/bulk"),
            headers=moderator_a.headers,
            json={"target_type": stranger, "target_ids": [1], "add_tag_ids": [tag.id]},
        ),
        await client.get(
            moderator_a.g(f"/tags/{tag.id}/entities"),
            headers=moderator_a.headers,
            params={"kind": stranger},
        ),
        await client.get(
            moderator_a.g("/relationships/"),
            headers=moderator_a.headers,
            params={"entity": f"{stranger}:1"},
        ),
        await client.post(
            moderator_a.g("/relationships/"),
            headers=moderator_a.headers,
            json={**link, "target": {"type": stranger, "id": 1}},
        ),
    ):
        assert response.status_code == 404, response.text


async def test_exports_and_counts_keep_a_tool_plugins_rows_in_their_initiative(
    session: AsyncSession,
    acting_user: Callable[..., Awaitable[Actor]],
    client: AsyncClient,
) -> None:
    """A tool plug-in's row and its item in initiative A, shared by name with
    its moderator, a moderator of B and a member of no initiative, are
    exported, counted and read as a dashboard dataset by A's moderator, and
    by neither of the others: its export is not found, and their counts,
    backups and statements hold none of it. Its export is imported into A by
    A's moderator once the tool is placed there, and into an initiative the
    importer is not in by nobody."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild = admin.guild
    initiative_b = await create_initiative(session, guild, admin.user)
    moderator_a = await acting_user(
        guild=guild, initiative=admin.initiative, initiative_role="moderator"
    )
    moderator_b = await acting_user(
        guild=guild, initiative=initiative_b, initiative_role="moderator"
    )
    outsider = await acting_user(guild=guild)
    await session.commit()
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    install = await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(guild.id)
    tool = tools.installed[0]
    await route_session_to_guild(session, guild.id)
    seeder = _Seeder(
        session,
        await _Catalog.read(session),
        admin.initiative.id,
        grantor=moderator_a.user.id,
        # A's moderator too, as a count counts what is shared with its reader.
        grantees=(moderator_a.user.id, moderator_b.user.id, outsider.user.id),
        tools=tools,
    )
    item_row = await seeder.make(tool.items[0].name, moderator_a.user.id)
    tool_id = item_row[f"{tool.kind.split('.')[0]}_id"]
    await session.commit()
    a, b = admin.initiative.id, initiative_b.id
    # The dashboard dataset of the tool's items, named by its table.
    counted = f"SELECT count(*) FROM {tool.items[0].name}"

    for actor in (moderator_b, outsider):
        response = await client.get(
            actor.g(f"/exports/{tool.kind}"),
            headers=actor.headers,
            params={"ids": [tool_id], "format": "json"},
        )
        assert response.status_code == 404, response.text
        response = await client.get(
            actor.g("/tools/counts/by-initiative"), headers=actor.headers
        )
        assert response.json()["counts"][tool.kind] == {}, response.text
        response = await client.get(
            actor.g(f"/tools/{tool.kind}/counts"),
            headers=actor.headers,
            params={"initiative_id": a},
        )
        assert response.json()["views"] == {"active": 0, "archived": 0}
        response = await client.get("/api/v1/me/tools/counts", headers=actor.headers)
        assert response.json()["counts"][tool.kind] == 0, response.text
        response = await client.post(
            actor.g("/query"), headers=actor.headers, json={"sql": counted}
        )
        assert response.json()["rows"] == [[0]], response.text
    response = await client.get(
        moderator_b.g("/exports/estimate"),
        headers=moderator_b.headers,
        params={"scope": "initiative", "initiative_id": b},
    )
    assert response.json()["tools"][tool.kind]["count"] == 0, response.text
    response = await client.get(
        moderator_b.g("/exports/estimate"),
        headers=moderator_b.headers,
        params={"scope": "initiative", "initiative_id": a},
    )
    assert response.status_code == 404, response.text

    # A kind the community has not installed is not found.
    for path in (f"/exports/stranger.{'x' * 14}", f"/tools/stranger.{'x' * 14}/counts"):
        response = await client.get(
            moderator_a.g(path), headers=moderator_a.headers, params={"ids": [1]}
        )
        assert response.status_code == 404, (path, response.text)

    response = await client.get(
        moderator_a.g(f"/exports/{tool.kind}"),
        headers=moderator_a.headers,
        params={"ids": [tool_id], "format": "json"},
    )
    assert response.status_code == 200, response.text
    exported = response.json()
    assert exported["type"] == f"initiative-{tool.kind}"
    assert [counter["name"] for counter in exported["items"]["counter"]] == [
        item_row["name"]
    ]
    response = await client.get(
        moderator_a.g(f"/exports/{tool.kind}"),
        headers=moderator_a.headers,
        params={"ids": [tool_id], "format": "csv"},
    )
    assert response.status_code == 200, response.text
    assert item_row["name"] in response.text
    response = await client.get(
        moderator_a.g("/tools/counts/by-initiative"), headers=moderator_a.headers
    )
    assert response.json()["counts"][tool.kind] == {str(a): 1}, response.text
    response = await client.get(
        moderator_a.g(f"/tools/{tool.kind}/counts"),
        headers=moderator_a.headers,
        params={"initiative_id": a, "include_tags": True},
    )
    assert response.json() == {
        "views": {"active": 1, "archived": 0},
        "tag_counts": {},
        "untagged_count": 1,
    }, response.text
    response = await client.get("/api/v1/me/tools/counts", headers=moderator_a.headers)
    assert response.json()["counts"][tool.kind] == 1, response.text
    response = await client.post(
        moderator_a.g("/query"), headers=moderator_a.headers, json={"sql": counted}
    )
    assert response.json()["rows"] == [[1]], response.text
    response = await client.get(
        moderator_a.g("/exports/estimate"),
        headers=moderator_a.headers,
        params={"scope": "initiative", "initiative_id": a},
    )
    assert response.json()["tools"][tool.kind]["count"] == 1, response.text

    async def restore(actor: Actor, initiative_id: int) -> tuple[int, str | None]:
        response = await client.post(
            actor.g("/imports/envelope"),
            headers=actor.headers,
            json={"initiative_id": initiative_id, "envelope": exported},
        )
        return response.status_code, response.json().get("detail")

    refused = (404, ImportEngineMessages.IMPORT_INVALID_PARAMS)
    for actor in (moderator_b, outsider):
        assert await restore(actor, a) == refused, actor
    assert await restore(moderator_a, b) == refused
    response = await client.patch(
        seat.g(f"/plugins/{install['id']}"),
        headers=seat.headers,
        json={"placed_initiative_ids": [a, b]},
    )
    assert response.status_code == 200, response.text
    for actor in (moderator_b, outsider):
        assert await restore(actor, a) == refused, actor
    assert await restore(moderator_a, b) == refused
    assert (await restore(moderator_a, a))[0] == 201


async def test_sharing_holds_and_responses_keep_a_tool_plugins_rows_in_their_initiative(
    session: AsyncSession,
    acting_user: Callable[..., Awaitable[Actor]],
    reading_as: Callable[[int, int], Awaitable[AsyncSession]],
    client: AsyncClient,
) -> None:
    """A tool plug-in's row in initiative A, shared by name with a moderator
    of B and a member of no initiative, is shared, held and taken out of the
    trash by neither of them, and shared by A's moderator. With the plug-in
    read only, A's moderator reads the comments on its rows and says, reacts
    and links nothing more on them."""
    from app.services.tenant.soft_delete import trash

    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild = admin.guild
    initiative_b = await create_initiative(session, guild, admin.user)
    moderator_a = await acting_user(
        guild=guild, initiative=admin.initiative, initiative_role="moderator"
    )
    moderator_b = await acting_user(
        guild=guild, initiative=initiative_b, initiative_role="moderator"
    )
    outsider = await acting_user(guild=guild)
    await session.commit()
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    install = await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(guild.id)
    tool = tools.installed[0]
    (item_kind,) = (child.value for child in tool.children)
    mine = await reading_as(moderator_a.user.id, guild.id)
    rows: dict[str, int] = dict(
        zip(
            (tool.kind, item_kind),
            (await add_counter(mine, guild.id, admin.initiative.id))[1:],
        )
    )
    trashed, _ = (await add_counter(mine, guild.id, admin.initiative.id))[1:]
    mine.add_all(
        ResourceGrant(
            resource_type=tool.kind,
            resource_id=row_id,
            initiative_id=admin.initiative.id,
            user_id=person.user.id,
            level=ResourceAccessLevel.write,
        )
        for row_id in (rows[tool.kind], trashed)
        for person in (moderator_b, outsider)
    )
    await mine.flush()
    located = locate(tools, tool.kind)
    assert located is not None
    row = await load_row(mine, located, tools, trashed)
    assert row is not None
    await trash(mine, row, deleted_by_user_id=moderator_a.user.id)
    await mine.commit()

    def sharing(row_id: int, kind: str = tool.kind) -> dict[str, Any]:
        return {
            "items": [
                {
                    "resource_type": kind,
                    "resource_id": row_id,
                    "grants": [{"user_id": outsider.user.id, "level": "read"}],
                }
            ]
        }

    for actor in (moderator_b, outsider):
        response = await client.put(
            actor.g("/resource-grants/bulk"),
            headers=actor.headers,
            json=sharing(rows[tool.kind]),
        )
        assert response.status_code == 200, response.text
        assert response.json()["results"][0]["status"] == "not_found"
        for kind, row_id in rows.items():
            response = await client.post(
                actor.g("/holds"),
                headers=actor.headers,
                json={
                    "target_type": kind,
                    "target_id": row_id,
                    "reason": "legal_request",
                },
            )
            assert response.status_code == 404, (kind, response.text)
        response = await client.post(
            actor.g(f"/trash/{tool.kind}/{trashed}/restore"), headers=actor.headers
        )
        assert response.status_code == 404, response.text

    # A kind the community lacks is not found.
    stranger = f"stranger.{'x' * 14}"
    response = await client.put(
        moderator_a.g("/resource-grants/bulk"),
        headers=moderator_a.headers,
        json=sharing(rows[tool.kind], stranger),
    )
    assert response.json()["results"][0]["status"] == "not_found", response.text
    response = await client.post(
        moderator_a.g("/holds"),
        headers=moderator_a.headers,
        json={"target_type": stranger, "target_id": 1, "reason": "legal_request"},
    )
    assert response.status_code == 404, response.text

    response = await client.put(
        moderator_a.g("/resource-grants/bulk"),
        headers=moderator_a.headers,
        json=sharing(rows[tool.kind]),
    )
    assert response.json()["results"][0]["status"] == "ok", response.text

    # Said while the tool may be written, each comment is read once it is
    # read only, and nothing more is said, reacted or linked on its rows.
    comments: dict[str, int] = {}
    for kind, row_id in rows.items():
        response = await client.post(
            moderator_a.g("/comments/"),
            headers=moderator_a.headers,
            json={"subject_type": kind, "subject_id": row_id, "content": "hi"},
        )
        assert response.status_code == 201, (kind, response.text)
        comments[kind] = response.json()["id"]
    link = sa.text(
        "INSERT INTO relationships (source_type, source_id, relationship_type,"
        " target_type, target_id, provenance, created_at)"
        " VALUES (:s, :si, :ty, :t, :ti, 'manual', now())"
    )
    # An edge that describes its source, and the two that describe neither
    # end and are a response to each.
    linked = ("depends_on", "related_to", "attached")
    ends = {
        "s": tool.kind,
        "si": rows[tool.kind],
        "t": item_kind,
        "ti": rows[item_kind],
    }
    # A symmetric edge is stored with its lower node id first.
    flipped = {"s": ends["t"], "si": ends["ti"], "t": ends["s"], "ti": ends["si"]}
    lower_first = (tools.endpoint_codes[tool.kind], rows[tool.kind]) < (
        tools.endpoint_codes[item_kind],
        rows[item_kind],
    )
    for ty in linked:
        given = ends if ty == "depends_on" or lower_first else flipped
        linking = await reading_as(moderator_a.user.id, guild.id)
        assert await _attempt(linking, link.bindparams(**given, ty=ty)) == 1, ty
        await linking.rollback()

    read_only = {"status": PluginInstallStatus.read_only.value}
    await session.exec(
        pg_insert(PluginInstall)
        .values(
            guild_id=guild.id,
            install_id=install["id"],
            listing_uid=COUNTERS_UID,
            enabled=True,
            **read_only,
        )
        .on_conflict_do_update(
            index_elements=["guild_id", "install_id"], set_=read_only
        )
    )
    await session.commit()
    for kind, row_id in rows.items():
        response = await client.get(
            moderator_a.g("/comments/"),
            headers=moderator_a.headers,
            params={"subject_type": kind, "subject_id": row_id},
        )
        assert response.status_code == 200, (kind, response.text)
        assert [c["id"] for c in response.json()["comments"]] == [comments[kind]]
        response = await client.post(
            moderator_a.g("/comments/"),
            headers=moderator_a.headers,
            json={"subject_type": kind, "subject_id": row_id, "content": "again"},
        )
        assert response.status_code == 403, (kind, response.text)
        response = await client.put(
            moderator_a.g(f"/reactions/comment/{comments[kind]}"),
            headers=moderator_a.headers,
            json={"emoji": "👍"},
        )
        assert response.status_code == 403, (kind, response.text)
    for ty in linked:
        linking = await reading_as(moderator_a.user.id, guild.id)
        assert await _attempt(linking, link.bindparams(**ends, ty=ty)) == _REFUSED, ty
        await linking.rollback()


async def test_notices_and_marks_keep_a_tool_plugins_rows_in_their_initiative(
    session: AsyncSession,
    acting_user: Callable[..., Awaitable[Actor]],
    client: AsyncClient,
) -> None:
    """A reply, an @mention and a subscription on a tool plug-in's item in
    initiative A tell only people who can open it, and its line names it: a
    moderator of B and a member of no initiative hear nothing, though it is
    shared with them by name, they are mentioned and they subscribed to it
    and its tool. Neither of them views, bookmarks or subscribes to A's rows
    or sets a property on them, which A's moderators do; a kind the community
    lacks is not found."""
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild = admin.guild
    initiative_b = await create_initiative(session, guild, admin.user)
    moderators_a = [
        await acting_user(
            guild=guild, initiative=admin.initiative, initiative_role="moderator"
        )
        for _ in range(3)
    ]
    moderator_a, mentioned_a, subscriber_a = moderators_a
    moderator_b = await acting_user(
        guild=guild, initiative=initiative_b, initiative_role="moderator"
    )
    outsider = await acting_user(guild=guild)
    text = await create_property_definition(session, admin.initiative)
    person = await create_property_definition(
        session, admin.initiative, type=MetadataType.user_reference
    )
    seat = await acting_user(guild=guild, guild_role=CommunityRole.superadmin)
    await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(guild.id)
    tool = tools.installed[0]
    (item_kind,) = (child.value for child in tool.children)
    await route_session_to_guild(session, guild.id)
    seeder = _Seeder(
        session,
        await _Catalog.read(session),
        admin.initiative.id,
        grantor=moderator_a.user.id,
        grantees=(moderator_b.user.id, outsider.user.id),
        tools=tools,
    )
    item_row = await seeder.make(tool.items[0].name, moderator_a.user.id)
    rows = {
        tool.kind: item_row[f"{tool.kind.split('.')[0]}_id"],
        item_kind: item_row["id"],
    }
    # Subscribed before they were moved out of reach: kept, and not told.
    for actor in (moderator_b, outsider):
        for kind, row_id in rows.items():
            session.add(
                PersonalItem(
                    user_id=actor.user.id,
                    entity_type=kind,
                    entity_id=row_id,
                    subscribed_at=datetime.now(UTC),
                )
            )
    await session.commit()

    def properties(actor: Actor, kind: str, values: list[dict[str, Any]]) -> Any:
        return client.put(
            actor.g(f"/properties/{kind}/{rows.get(kind, 1)}"),
            headers=actor.headers,
            json={"values": values},
        )

    written = [{"property_id": text.id, "value": "boundary"}]
    for actor in (moderator_b, outsider):
        for kind, row_id in rows.items():
            for mark in ("view", "subscribe"):
                response = await client.put(
                    actor.g(f"/personal-items/{mark}/{kind}/{row_id}"),
                    headers=actor.headers,
                )
                assert response.status_code == 404, (mark, kind, response.text)
            response = await properties(actor, kind, written)
            assert response.status_code == 404, (kind, response.text)
        response = await client.put(
            actor.g(f"/personal-items/bookmark/{tool.kind}/{rows[tool.kind]}"),
            headers=actor.headers,
        )
        assert response.status_code == 404, response.text

    # A kind the community has not installed is not found, nor is an item
    # bookmarked: a bookmark is on a tool.
    stranger = f"stranger.{'X' * 14}"
    for method, path in (
        ("GET", f"/personal-items/{stranger}/1"),
        ("PUT", f"/personal-items/subscribe/{stranger}/1"),
        ("PUT", f"/personal-items/bookmark/{stranger}/1"),
        ("PUT", f"/personal-items/bookmark/{item_kind}/{rows[item_kind]}"),
    ):
        response = await client.request(
            method, moderator_a.g(path), headers=moderator_a.headers
        )
        assert response.status_code == 404, (path, response.text)
    response = await properties(moderator_a, stranger, written)
    assert response.status_code == 404, response.text

    response = await client.put(
        moderator_a.g(f"/personal-items/bookmark/{tool.kind}/{rows[tool.kind]}"),
        headers=moderator_a.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["entity_type"] == tool.kind
    response = await client.get(
        moderator_a.g("/personal-items"),
        headers=moderator_a.headers,
        params={"mark": "bookmark"},
    )
    assert [
        (item["entity_type"], item["entity_id"], item["initiative_id"])
        for item in response.json()
    ] == [(tool.kind, rows[tool.kind], admin.initiative.id)], response.text
    response = await client.put(
        subscriber_a.g(f"/personal-items/subscribe/{item_kind}/{rows[item_kind]}"),
        headers=subscriber_a.headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["subscribed"] is True
    for kind in rows:
        response = await properties(moderator_a, kind, written)
        assert response.status_code == 200, (kind, response.text)
        assert [value["value"] for value in response.json()] == ["boundary"]
        response = await properties(
            moderator_a, kind, [{"property_id": person.id, "value": outsider.user.id}]
        )
        assert response.status_code == 422, (kind, response.text)

    said = await client.post(
        moderator_a.g("/comments/"),
        headers=moderator_a.headers,
        json={
            "subject_type": item_kind,
            "subject_id": rows[item_kind],
            "content": "first",
        },
    )
    assert said.status_code == 201, said.text
    mentions = " ".join(
        f"@[someone]({actor.user.id})" for actor in (mentioned_a, moderator_b, outsider)
    )
    answered = await client.post(
        admin.g("/comments/"),
        headers=admin.headers,
        json={
            "subject_type": item_kind,
            "subject_id": rows[item_kind],
            "content": f"answer {mentions}",
            "parent_comment_id": said.json()["id"],
        },
    )
    assert answered.status_code == 201, answered.text
    await drain_notices()

    told = {
        user_id: kind
        for user_id, kind, data in (
            await session.exec(
                sa.select(Notification.user_id, Notification.type, Notification.data)
            )
        ).all()
        if data.get("comment_id") == answered.json()["id"]
        # A tool plug-in's row opens on its own page, in its initiative.
        and data.get("target_path")
        == f"/i/{admin.initiative.id}/t/{item_kind}/{rows[item_kind]}"
    }
    assert told == {
        moderator_a.user.id: NotificationType.comment_reply,
        mentioned_a.user.id: NotificationType.mention,
        subscriber_a.user.id: NotificationType.subscription_activity,
    }
    response = await client.get("/api/v1/notifications/", headers=moderator_a.headers)
    (line,) = (
        line
        for line in response.json()["notifications"]
        if line["data"].get("comment_id") == answered.json()["id"]
    )
    assert line["data"]["entity_name"] == item_row["name"], line


async def test_webhooks_tell_a_tool_plugins_changes_only_where_they_are_heard(
    session: AsyncSession,
    acting_user: Callable[..., Awaitable[Actor]],
    role_session: Callable[[str], Awaitable[AsyncSession]],
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A change to a tool plug-in's row and its item in initiative A is told
    by their kinds, as identifiers and changed field names, to an installed
    plug-in holding the tool's read scope and placed in A, and to the
    community's own subscription. Once the install's grant no longer holds
    the scope, it hears nothing; while the tool is placed outside A alone,
    nobody hears a change in A; placed in A again, its archive is told as
    an update of its ``archived_at``, as a built-in tool's is."""
    from app.models.tenant.guild_plugin import GuildPlugin
    from app.models.tenant.webhook_subscription import WebhookSubscription
    from app.services.tenant import outbox_poller as poller
    from app.testing.plugin_clients import install_plugin

    read = f"counter_group.{COUNTERS_UID.lower()}:read"
    installed = await install_plugin(
        session, acting_user, role_session, granted=[read], requested=[read]
    )
    seat, guild_id = installed.seat, installed.guild.id
    initiative_a, initiative_b = installed.placed.id, installed.unplaced.id
    install = await install_tool_plugin(client, session, seat)
    tools = await provisioned_tools(guild_id)
    (tool,) = tools.installed
    (item,) = tool.children
    events = [
        f"{kind}.{action}"
        for kind in (tool.kind, item.value)
        for action in ("created", "updated", "deleted")
    ]
    to_install, to_community = "https://install.test/in", "https://community.test/in"
    await route_session_to_guild(session, guild_id)
    now = datetime.now(UTC)
    for target, install_id in ((to_install, installed.plugin.id), (to_community, None)):
        session.add(
            WebhookSubscription(
                initiative_id=None,
                plugin_install_id=install_id,
                created_by=install_id or seat.user.id,
                created_by_kind=ActorKind.member
                if install_id is None
                else ActorKind.plugin,
                target_url=target,
                hmac_secret="secret",
                event_types=events,
                active=True,
                created_at=now,
                updated_at=now,
            )
        )
    await session.commit()

    told: dict[str, list[tuple[str, int, list[Any], list[str]]]] = {}

    async def accept(*, target_url: str, secret: str, envelope: dict[str, Any]) -> bool:
        told.setdefault(target_url, []).extend(
            (c["event_type"], c["resource"]["id"], c["parents"], c["changed"])
            for c in envelope["changes"]
        )
        return True

    monkeypatch.setattr(poller, "deliver", accept)
    system = await role_session("app_admin")

    async def heard() -> dict[str, list[tuple[str, int, list[Any], list[str]]]]:
        told.clear()
        await poller.drain_guild(system, guild_id, now=datetime.now(UTC))
        return dict(told)

    async def call(method: str, path: str, body: Any = None) -> Any:
        response = await client.request(
            method, seat.g(path), headers=seat.headers, json=body
        )
        assert response.status_code in (200, 201), (path, response.text)
        return response.json()

    group = (
        await call(
            "POST",
            f"/plugin-tools/{tool.kind}/",
            {"initiative_id": initiative_a, "name": "Scores"},
        )
    )["id"]
    counter = (
        await call(
            "POST", f"/plugin-tools/{item.value}/", {"parent_id": group, "name": "Laps"}
        )
    )["id"]
    under = [{"type": tool.kind, "id": group}]
    made = await heard()
    for target in (to_install, to_community):
        changes = made[target]
        assert (f"{tool.kind}.created", group, [], []) in changes, changes
        assert (f"{item.value}.created", counter, under, []) in changes, changes
        assert {event for event, *_ in changes} <= set(events), changes

    stepped = f"/plugin-tools/{item.value}/{counter}/step"
    step = (f"{item.value}.updated", counter, under, ["count"])
    await call("POST", stepped, {"field": "count"})
    assert await heard() == {to_install: [step], to_community: [step]}

    async def grant(*scopes: str) -> None:
        await route_session_to_guild(session, guild_id)
        await session.exec(
            sa.update(GuildPlugin)
            .where(GuildPlugin.id == installed.plugin.id)
            .values(granted_scopes=list(scopes))
        )
        await session.commit()

    # The install's grant no longer holds the tool's read scope.
    await grant()
    await call("POST", stepped, {"field": "count"})
    assert await heard() == {to_community: [step]}
    await grant(read)

    # The tool placed outside A alone: its rows in A change, and nobody hears.
    plugin_path = f"/plugins/{install['id']}"
    await call("PATCH", plugin_path, {"placed_initiative_ids": [initiative_b]})
    await route_session_to_guild(session, guild_id)
    counters = tools.tables[item.table]
    await session.exec(
        sa.update(counters).where(counters.c.id == counter).values(count=7)
    )
    await session.commit()
    assert await heard() == {}

    # Placed in A again: archiving its row is told as an update.
    await call("PATCH", plugin_path, {"placed_initiative_ids": [initiative_a]})
    await call("POST", f"/archive/{tool.kind}/{group}")
    archived = await heard()
    for target in (to_install, to_community):
        assert any(
            event == f"{tool.kind}.updated"
            and row_id == group
            and "archived_at" in changed
            for event, row_id, _parents, changed in archived[target]
        ), archived
