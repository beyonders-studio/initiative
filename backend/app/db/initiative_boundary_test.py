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

Last, the tool plug-in's state: suspended, and uninstalled by its community
with its content kept for the deletion window, its rows (and the comments on
them) read as absent to A's moderator and to the community's admin, and every
write is refused; read-only, they read and every write is refused; installed
again, A's moderator reads and writes its row and nobody outside A reads it.
A custom role made after the install adds the tool's row in A once given its
create permission, and not before. Through the universal routes and the tool
plug-in routes (``tenant_endpoints/plugin_tools.py``), the tool plug-in's row
and its item answer A's moderator and are not found by the other two.

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
from app.models.platform.plugin_install import PluginInstall, PluginInstallStatus
from app.models.tenant._mixins import ActorKind
from app.models.tenant.initiative import InitiativeRule
from app.services.tenant.initiative_tools import write_switches
from app.testing import (
    COUNTERS_UID,
    Actor,
    create_initiative,
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


def _variants(name: str, tools: ToolSet) -> list[tuple[str, dict[str, Any] | None]]:
    """The cases one table is swept as: once, or once per subject kind."""
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
            if column in table.c:
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


async def test_nobody_outside_an_initiative_reaches_its_rows(
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

    # A tool plug-in's state hides its tool from everyone, the community
    # admin included, as no switch does: suspended by staff, and uninstalled
    # by its community while its content waits out the deletion window. Read
    # only, its rows read and refuse every write. Installed again within the
    # window, everything is back.
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

    async def sweep_state(state: str, *, reads: bool) -> None:
        """Every row of the tool plug-in's in A reads as ``reads`` says, to A's
        moderator and the community admin, and none is written. A comment on
        a read-only tool's row is said, changed and removed as on any row its
        reader reads, so only the tool's own rows are held to that there."""
        for who, person in everybody.items():
            reader = await reading_as(person, guild.id)
            for name, case in plugin_cases.items():
                own = _matching(case.table, [case.rows[people.moderator_a]])
                seen = await _count(reader, case.table, own)
                if seen != int(reads):
                    failures.append(f"{name}: {who} reads {seen} with it {state}")
                if reads and case.table.name not in plugin_tables:
                    continue
                key = next(iter(case.table.primary_key.columns))
                writes = {
                    "INSERT": _insert(case, people.moderator_a),
                    "UPDATE": sa.update(case.table)
                    .where(in_a(case))
                    .values({key.name: key}),
                    "DELETE": sa.delete(case.table).where(in_a(case)),
                }
                for command, statement in writes.items():
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

    plugin_path = seat.g(f"/plugins/{install['id']}")
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
    requests, A's list and a new row in A among them, is answered 404."""
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
