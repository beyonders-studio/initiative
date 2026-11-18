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

Then each tool is switched off in A in turn, and with every tool's switch row
gone: a moderator of A reads none of the rows of a table a switched-off tool
governs, and updates and deletes none of them.

A table the seeder cannot fill fails here; it is never skipped.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.guild_ddl import _WRITTEN_BY
from app.db.initiative_rls import (
    INITIATIVE_PATHS,
    entity_tables,
    governing_path,
    initiative_of,
)
from app.db.soft_delete_filter import SOFT_DELETE_TABLES
from app.models.platform.guild import CommunityRole
from app.models.tenant._mixins import ActorKind
from app.models.tenant.initiative import InitiativeRule
from app.services.tenant.initiative_tools import write_switches
from app.testing import (
    create_initiative,
    make_operations_community,
    route_as,
    route_session_to_guild,
)

pytestmark = pytest.mark.always

#: insufficient_privilege: a missing grant, and a row a policy refuses.
_REFUSED = "42501"

_TOOL_BY_TABLE: dict[str, Tool] = {tool.plural: tool for tool in Tool}


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
    # A comment hangs off exactly one parent.
    "comments": {"project_id": _Parent("projects")},
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
#: initiative's, which the positive control leaves out.
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

#: Tables the community's administration reads and writes rather than an
#: initiative's members, whose positive control is the community admin.
_ADMINISTERED: frozenset[str] = frozenset({"guest_invite_grants"})


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
    initiative_id: int
    people: _People
    counter: int = 0
    #: How many rows took a ``_DISTINCT`` value, by ``(table, column)``.
    taken: dict[tuple[str, str], int] = field(default_factory=dict)

    def table(self, name: str) -> sa.Table:
        return SQLModel.metadata.tables[name]

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
        return next(kind for kind in allowed if kind in entity_tables())

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
                entity_tables().get(kind, kind), owner, share=name != "resource_grants"
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
        """Write a row of ``name`` in A and return it. A tool's row is shared
        with both outsiders by name, at write."""
        table = self.table(name)
        values = await self.values(name, owner, inherit)
        statement = sa.insert(table).values(**values).returning(*table.c)
        row = dict((await self.session.exec(statement)).mappings().one())
        if name in _SEEN_WITH:
            child, column = _SEEN_WITH[name]
            await self.make(child, owner, inherit={column: row["id"]})
        tool = _TOOL_BY_TABLE.get(name)
        if tool is not None and share:
            grants = self.table("resource_grants")
            for person in self.people.outsiders:
                shared = await self.values(
                    "resource_grants",
                    self.people.moderator_a,
                    inherit={
                        "resource_type": tool.value,
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


def _initiative_of(table: sa.Table) -> str:
    """The initiative of a row ``r`` of ``table``, by the lookup the change
    capture stamps events with."""
    return initiative_of(table.name, "r")


async def _outside(session: AsyncSession, case: _Case, initiative_id: int) -> int:
    """How many of the rows made for ``case`` are not in ``initiative_id``."""
    rows = set(case.rows.values())
    columns = ", ".join(f"r.{c.name}" for c in case.table.primary_key.columns)
    statement = sa.text(
        f"SELECT {columns} FROM {case.table.name} r"
        f" WHERE {_initiative_of(case.table)} = :initiative_id"
    )
    result = await session.exec(statement, params={"initiative_id": initiative_id})
    return len(rows - {tuple(row) for row in result.all()})


async def _keep_only(session: AsyncSession, table: sa.Table, initiative_id: int):
    """Delete every row of ``table`` not in ``initiative_id``, with triggers
    off, so whatever a statement on the whole table reaches is A's."""
    await session.exec(sa.text("SET LOCAL session_replication_role = replica"))
    await session.exec(
        sa.text(
            f"DELETE FROM {table.name} r"
            f" WHERE {_initiative_of(table)} IS DISTINCT FROM :initiative_id"
        ),
        params={"initiative_id": initiative_id},
    )
    await session.exec(sa.text("SET LOCAL session_replication_role = origin"))


async def _tools_on(role_session, person: int, guild_id: int, initiative_id: int):
    """Assert every tool is switched on in ``initiative_id`` for ``person``."""
    session = await role_session("app_user")
    context = await route_as(session, user_id=person, guild_id=guild_id)
    await session.rollback()
    expected = {f"{initiative_id}:{tool.value}" for tool in Tool}
    assert expected <= set(context.enabled_tools)


async def test_nobody_outside_an_initiative_reaches_its_rows(
    session: AsyncSession, acting_user, reading_as, role_session
):
    # A and B are each in the hands of a moderator, the role with every tool
    # permission and full access to the initiative's content.
    admin = await acting_user(guild_role=CommunityRole.admin, initiative=True)
    guild = admin.guild
    initiative_a = admin.initiative.id
    initiative_b = await create_initiative(session, guild, admin.user)
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
    await route_session_to_guild(session, guild.id)
    seeder = _Seeder(session, await _Catalog.read(session), initiative_a, people)
    cases: dict[str, _Case] = {}
    unseeded: dict[str, str] = {}
    for name in INITIATIVE_PATHS:
        table = seeder.table(name)
        owners = everyone if seeder.personal(table) else (people.moderator_a,)
        savepoint = await session.begin_nested()
        try:
            rows = {p: _pk(table, await seeder.make(name, p)) for p in owners}
            candidates = {p: await seeder.values(name, p) for p in everyone}
        except (DBAPIError, AssertionError) as error:
            await savepoint.rollback()
            unseeded[name] = str(error).splitlines()[0]
            continue
        await savepoint.commit()
        cases[name] = _Case(
            table,
            {p: rows.get(p, rows[people.moderator_a]) for p in everyone},
            candidates,
        )
    assert not unseeded, (
        "The sweep could not put a row of these tables in an initiative; teach "
        f"_Seeder or give the table a shape in _SHAPES: {unseeded}"
    )

    misplaced = [
        name
        for name, case in cases.items()
        if await _outside(session, case, initiative_a)
    ]
    assert not misplaced, f"rows meant for initiative A that are not in it: {misplaced}"
    # The community's other rows (B's, and its own) are cleared, so the rows a
    # statement on a whole table reaches are A's.
    for case in cases.values():
        await _keep_only(session, case.table, initiative_a)
    await session.commit()

    await _tools_on(role_session, people.moderator_a, guild.id, initiative_a)
    await _tools_on(role_session, people.moderator_b, guild.id, initiative_b.id)

    failures: list[str] = []
    for person, who in (
        (people.moderator_b, "a moderator of B"),
        (people.outsider, "a member of no initiative"),
    ):
        reader = await reading_as(person, guild.id)
        for name, case in cases.items():
            if (seen := await _count(reader, case.table)) != 0:
                failures.append(f"{name}: {who} reads {seen} of A's rows")
            if (inserted := await _attempt(reader, _insert(case, person))) != _REFUSED:
                failures.append(f"{name}: {who} can INSERT in A ({inserted})")
            for command, statement in _blind_writes(case).items():
                if (answer := await _attempt(reader, statement)) not in (0, _REFUSED):
                    failures.append(f"{name}: {who} can {command} in A ({answer})")
        await reader.rollback()

    readers = {
        "A's moderator": await reading_as(people.moderator_a, guild.id),
        "the community admin": await reading_as(admin.user.id, guild.id),
    }
    for name, case in cases.items():
        who = "the community admin" if name in _ADMINISTERED else "A's moderator"
        reader = readers[who]
        own = _matching(case.table, [case.rows[people.moderator_a]])
        if (seen := await _count(reader, case.table, own)) != 1:
            failures.append(f"{name}: {who} reads {seen} of its own row")
        for command, statement in _own_writes(case, people.moderator_a).items():
            if command in _NOT_A_MODERATORS.get(name, ()):
                continue
            if (answer := await _attempt(reader, statement)) != 1:
                failures.append(f"{name}: {who} cannot {command} in A ({answer})")
    for reader in readers.values():
        await reader.rollback()

    # A switched-off tool's rows read as absent to A's own moderator: each
    # tool off in turn, then every switch row gone, since no row is off.
    governed = {
        name: governing[0]
        for name in cases
        if (governing := governing_path(name)) is not None
    }
    assert set(governed.values()) == set(Tool)
    for off in [{tool} for tool in Tool] + [set(Tool)]:
        await route_session_to_guild(session, guild.id)
        if off == set(Tool):
            await session.exec(
                sa.delete(InitiativeRule).where(
                    InitiativeRule.initiative_id == initiative_a,
                    InitiativeRule.initiative_role_id.is_(None),
                    InitiativeRule.install_id.is_(None),
                )
            )
        else:
            await write_switches(
                session, initiative_a, {tool: tool not in off for tool in Tool}
            )
        await session.commit()
        state = "no switch rows" if len(off) > 1 else f"{next(iter(off)).value} off"
        reader = await reading_as(people.moderator_a, guild.id)
        for name, tool in governed.items():
            if tool not in off:
                continue
            case = cases[name]
            if (seen := await _count(reader, case.table)) != 0:
                failures.append(f"{name}: A's moderator reads {seen} with {state}")
            for command, statement in _blind_writes(case).items():
                if (answer := await _attempt(reader, statement)) not in (0, _REFUSED):
                    failures.append(
                        f"{name}: A's moderator can {command} with {state} ({answer})"
                    )
        await reader.rollback()

    assert not failures, "\n".join(failures)
