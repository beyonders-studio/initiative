"""Run a resolved query, inside everything that bounds it.

A statement arrives here already read, validated and rewritten
(:mod:`app.services.query.resolve`). What happens here is the running of it:
under which role, in which transaction, against which limits.

Five things bound a query, and they are independent of each other:

* a **pool of its own**, so these statements wait for each other rather than
  for the requests serving every other page;
* a **cap per guild** on how many run at once, held in the database so it is
  the whole deployment's cap rather than each process's;
* a **read-only transaction**, which refuses a write whatever the statement
  says;
* the **query role**, which holds ``SELECT`` and no more;
* **statement limits** — a time bound, a memory bound, no parallel workers —
  and a **planner estimate** checked before anything runs.

The last one is the only one that can refuse a statement that is otherwise
perfectly legal, and it does so without executing it.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, AsyncIterator, Mapping

from asyncpg.exceptions import (
    DatabaseDroppedError,
    DataError,
    QueryCanceledError,
    SerializationError,
    SyntaxOrAccessError,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.messages import QueryMessages
from app.db import cohorts
from app.db.advisory_locks import LockNamespace, advisory_lock
from app.db.request_context import QUERYABLE, ContentGrantee, Member, RequestContext
from app.db.session import set_rls_context
from app.services.fields.spec import FieldType
from app.services.query import sheets
from app.services.query.canvas import compile_canvas
from app.services.query.resolve import QueryError, ResolvedQuery, SheetCall, resolve


@dataclass(frozen=True)
class QueryResult:
    """What a query returned, and what it cost to say so."""

    #: The output columns, in order, named and typed. Not necessarily distinct
    #: — ``SELECT t.id, p.id`` is a legal query and names both columns ``id``.
    columns: tuple[QueryColumn, ...]
    #: One tuple per row, positional against :attr:`columns`. Positional rather
    #: than keyed for the reason above: a mapping keeps one value per name.
    #: Values arrive in the spellings a client holds (see :func:`_wire`).
    rows: tuple[tuple[Any, ...], ...]
    #: The planner's estimate for the statement that ran.
    cost: float
    #: Whether there were more rows than one query returns.
    truncated: bool
    #: The datasets the statement read. What a tile can honestly say it is
    #: showing, now that there is no source name to print.
    relations: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryColumn:
    """One output column, named and typed before anything runs."""

    name: str
    type: FieldType
    #: The period the column is rounded to (``date_trunc``'s unit), or ``None``.
    grain: str | None = None
    #: SQL DATE values retain their calendar day when rendered in any zone.
    date_only: bool = False


#: What a Postgres type is, in the vocabulary the field registry already uses.
#: Only the distinctions a reader's tile turns on: whether a value counts,
#: whether it falls on a timeline, whether it is a yes or no.
_NUMBER_TYPES = frozenset(
    {"int2", "int4", "int8", "numeric", "float4", "float8", "money"}
)
#: Only points on a timeline. A ``time`` has no day and an ``interval`` is a
#: length rather than a moment, so neither is something a tile can place on one;
#: both read as text, which is what they are to a reader.
_DATE_TYPES = frozenset({"date", "timestamp", "timestamptz"})


async def _enum_types(connection: Any, oids: set[int]) -> set[int]:
    """Which of these types are a closed vocabulary the database defines.

    Asked of the catalog rather than read off the description: a prepared
    statement reports every type as scalar, so an enum column is
    indistinguishable there from the text it is stored beside.
    """
    if not oids:
        return set()
    rows = await connection.fetch(
        "SELECT oid FROM pg_type WHERE oid = ANY($1::oid[]) AND typtype = 'e'",
        list(oids),
    )
    return {row["oid"] for row in rows}


def _column_type(attribute: Any, enum_oids: set[int]) -> FieldType:
    """What the database says an output column holds.

    The answer for an output the registry cannot name — a count, a case, a date
    truncated to its month — since a field selected on its own is described by
    the registry that declares it (:attr:`ResolvedQuery.column_types`). Only the
    distinctions a tile turns on, in the same words the registry uses.
    """
    postgres_type = attribute.type
    if postgres_type.oid in enum_oids:
        return FieldType.enum
    name = postgres_type.name
    if name in _NUMBER_TYPES:
        return FieldType.number
    if name in _DATE_TYPES:
        return FieldType.date
    if name == "bool":
        return FieldType.boolean
    return FieldType.text


def _wire(value: Any) -> Any:
    """One value, in a spelling a client can hold.

    Two conversions, both so that a query's rows read like every other part of
    the app's: a moment becomes epoch milliseconds UTC, which is the one
    spelling of a timestamp the widgets take; and an exact number becomes a
    number, where the database's arbitrary-precision type would otherwise arrive
    as a string and stop counting as one. A JSON document is its text, as a
    compiled canvas spells it. Anything else with no JSON spelling is written
    out rather than dropped.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    # Before date, because every datetime is one.
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(moment.timestamp() * 1000)
    if isinstance(value, date):
        midnight = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return int(midnight.timestamp() * 1000)
    return str(value)


async def _described(
    connection: Any, prepared: Any, statement: ResolvedQuery
) -> tuple[QueryColumn, ...]:
    """The output columns of a prepared statement, named and typed.

    Shared by running a statement and describing one, because they are the same
    question asked at two moments — a tile that draws a query needs to know what
    its columns hold, and asking twice would be asking the same statement twice.
    """
    attributes = prepared.get_attributes()
    enum_oids = await _enum_types(
        connection, {attribute.type.oid for attribute in attributes}
    )
    declared = statement.column_types
    grains = statement.column_grains
    return tuple(
        QueryColumn(
            name=attribute.name,
            type=(
                declared[position]
                if position < len(declared) and declared[position] is not None
                else _column_type(attribute, enum_oids)
            ),
            grain=grains[position] if position < len(grains) else None,
            date_only=attribute.type.name == "date",
        )
        for position, attribute in enumerate(attributes)
    )


#: How many queries one guild may have running at once, across the deployment.
QUERY_MAX_CONCURRENT_PER_GUILD = 2
#: How long one statement may run.
QUERY_STATEMENT_TIMEOUT_MS = 5_000
#: How long a whole canvas's compiled statement may run. Past it, each widget
#: is run on its own under :data:`QUERY_STATEMENT_TIMEOUT_MS`.
QUERY_CANVAS_TIMEOUT_MS = 10_000
#: Sort/hash memory per statement, as a PostgreSQL size.
QUERY_WORK_MEM = "16MB"
#: The planner's estimate above which a statement is refused unrun.
QUERY_MAX_COST = 1_000_000.0
#: Rows one query may return.
QUERY_MAX_ROWS = 5_000


async def _claim_a_slot(connection: AsyncConnection, guild_id: int) -> bool:
    """Take one of this guild's slots, or report that it has none free.

    The slots are advisory locks rather than a counter in this process, so the
    cap is the deployment's however many workers or replicas serve it. Each is
    held for the transaction and released when it ends, so a query that fails
    or is cancelled gives its slot back without anything having to notice.
    """
    for slot in range(QUERY_MAX_CONCURRENT_PER_GUILD):
        if await advisory_lock(
            connection, LockNamespace.QUERY_SLOT, f"{guild_id}:{slot}", wait=False
        ):
            return True
    return False


#: The statement limits, as one bound statement. ``set_config`` is the function
#: form of ``SET LOCAL`` and takes its value as a parameter, where ``SET`` takes
#: only a literal — so the settings arrive bound rather than written into SQL.
#: The last two are constants: one query is one backend's worth of the server's
#: attention, and it is not compiled.
_TRANSACTION_LIMITS = text(
    "SELECT set_config('statement_timeout', :statement_timeout, true),"
    " set_config('work_mem', :work_mem, true),"
    " set_config('max_parallel_workers_per_gather', '0', true),"
    " set_config('jit', 'off', true)"
)


async def _bound_transaction(connection: Any, *, timeout_ms: int | None = None) -> None:
    """Put the limits on the transaction, before anything of the reader's runs.

    Issued through SQLAlchemy rather than the driver underneath it, so they
    land inside the transaction it is managing — all four are local to one, and
    ``SET TRANSACTION READ ONLY`` has to be the first thing in it, ahead of the
    statement that sets the rest. *timeout_ms* defaults to one statement's
    bound.
    """
    await connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    await connection.execute(
        _TRANSACTION_LIMITS,
        {
            "statement_timeout": str(timeout_ms or QUERY_STATEMENT_TIMEOUT_MS),
            "work_mem": QUERY_WORK_MEM,
        },
    )


async def _estimated_cost(connection: Any, statement: ResolvedQuery) -> float:
    plan = await connection.fetchval(statement.explain(), *statement.parameters)
    document = json.loads(plan) if isinstance(plan, str) else plan
    return float(document[0]["Plan"]["Total Cost"])


@asynccontextmanager
async def _translated_failures() -> AsyncIterator[None]:
    """Turn what the database says into what this surface answers.

    Three things a statement this surface accepted can still do. It can run out
    of the time it is allowed. It can be stopped by the server for reasons of
    its own — a read replica cancels a statement that is in the way of what it
    is replaying — which says nothing about the statement. And it can be a
    statement the server will not
    run: a value that will not convert or a division by zero, or a shape the
    grammar allows and the planner rejects — a column selected beside an
    aggregate without being grouped, a function called with types it does not
    take. Every one of them is the reader's statement rather than the app's, so
    each is told back with a code and what the database said, whether the
    statement was run or only described.
    """
    try:
        yield
    except QueryCanceledError as cancelled:
        raise QueryError(QueryMessages.TIMED_OUT) from cancelled
    except (SerializationError, DatabaseDroppedError) as interrupted:
        raise QueryError(QueryMessages.INTERRUPTED) from interrupted
    except (DataError, SyntaxOrAccessError) as failed:
        raise QueryError(QueryMessages.EXECUTION_FAILED, str(failed)) from failed


def _as_query(
    context: RequestContext,
    initiative_id: int | None,
) -> Member | ContentGrantee:
    """The request's own context, as the query role, narrowed to one initiative.

    Every entry point below establishes the same thing, so it is said once: the
    reader is whoever the request admitted, the role is the query role, and the
    scope is the surface's if it named one. Only a member or a content grantee
    reads here, and a guest is neither.
    """
    if not isinstance(context, QUERYABLE) or (
        isinstance(context, Member) and context.standing.routes_as_guest
    ):
        raise QueryError(QueryMessages.MISSING_RELATION)
    return replace(
        context,
        query=True,
        scope_initiative_id=initiative_id,
    )


async def _with_cells(
    session: Any, statement: ResolvedQuery, guild_id: int
) -> ResolvedQuery:
    """*statement*, resolved again with what its sheets read, in *session*'s
    routed transaction: the files are found as the statement's own rows are.
    What its other calls already read is kept."""
    unread = [call for call in statement.unread if isinstance(call, SheetCall)]
    if not unread:
        return statement
    return resolve(
        statement.source,
        {**statement.read, **await sheets.read(session, unread, guild_id)},
    )


async def execute(
    statement: ResolvedQuery,
    *,
    context: RequestContext,
    initiative_id: int | None = None,
) -> QueryResult:
    """Run an already-resolved statement under *context*.

    *context* is what the request's own session established
    (:func:`app.db.session.routed_context`), replayed here with the query
    role selected. The rows that come back are therefore the rows that reader
    reaches through any other part of the app — a member's, a read-only
    member's, a grantee's — decided once, by the dependency that admitted the
    request, rather than again here.

    *initiative_id* narrows that to one initiative. A statement names datasets
    rather than a scope, so an initiative-scoped surface says which initiative
    it is asking about and the policies on the tables it reads answer for that
    one. It removes rows and never adds any, so a caller may always pass it.
    The spreadsheets a statement reads are read under the same narrowing.
    """
    routed = _as_query(context, initiative_id)
    guild_id = routed.guild_id
    async with _translated_failures():
        async with cohorts.query_sessionmaker(guild_id)() as session:
            # Opened before anything else touches the connection. The bounds
            # below and the context after it are transaction-local, so they
            # need a transaction that is already open to be local *to*.
            await session.begin()
            sqlalchemy_connection = await session.connection()
            raw = await sqlalchemy_connection.get_raw_connection()
            connection = raw.driver_connection

            await _bound_transaction(sqlalchemy_connection)
            if not await _claim_a_slot(sqlalchemy_connection, guild_id):
                raise QueryError(QueryMessages.BUSY, str(guild_id))
            await set_rls_context(session, routed)
            statement = await _with_cells(session, statement, guild_id)

            cost = await _estimated_cost(connection, statement)
            if cost > QUERY_MAX_COST:
                raise QueryError(QueryMessages.TOO_EXPENSIVE, f"{cost:.0f}")

            prepared = await connection.prepare(statement.sql)
            columns = await _described(connection, prepared, statement)

            limit = QUERY_MAX_ROWS
            rows: list[tuple[Any, ...]] = []
            truncated = False
            async for record in prepared.cursor(*statement.parameters):
                if len(rows) >= limit:
                    truncated = True
                    break
                rows.append(tuple(_wire(value) for value in record))

            await session.rollback()
            return QueryResult(
                columns=columns,
                rows=tuple(rows),
                cost=cost,
                truncated=truncated,
                relations=statement.relations,
            )


async def run(
    sql: str,
    *,
    context: RequestContext,
    initiative_id: int | None = None,
) -> QueryResult:
    """Read *sql* and run what it resolves to."""
    return await execute(
        resolve(sql),
        context=context,
        initiative_id=initiative_id,
    )


async def describe(
    statement: ResolvedQuery,
    *,
    context: RequestContext,
    initiative_id: int | None = None,
) -> tuple[tuple[QueryColumn, ...], ResolvedQuery]:
    """What *statement* would return, without returning it, and the statement
    it resolved to once its sheets were read, which says what each read.

    The statement is prepared and its description read back. Preparing plans;
    it does not execute, so this costs a plan and no rows however much data the
    statement would have touched — which is what makes it usable at save time,
    on every keystroke of a builder if need be.

    It runs in the same transaction and role as the real thing, because a
    statement is only preparable against the schema its reader is routed to.
    """
    routed = _as_query(context, initiative_id)
    guild_id = routed.guild_id

    async with _translated_failures():
        async with cohorts.query_sessionmaker(guild_id)() as session:
            await session.begin()
            sqlalchemy_connection = await session.connection()
            raw = await sqlalchemy_connection.get_raw_connection()
            connection = raw.driver_connection

            await _bound_transaction(sqlalchemy_connection)
            await set_rls_context(session, routed)
            statement = await _with_cells(session, statement, guild_id)
            prepared = await connection.prepare(statement.sql)
            columns = await _described(connection, prepared, statement)
            await session.rollback()
            return columns, statement


def _from_json(value: Any, type_name: str) -> Any:
    """One value of a compiled canvas's rows, in the spelling :func:`_wire`
    gives the same value read on its own.

    The compiled statement returns its rows as JSON, which spells a moment as
    ISO text and a JSON document as structure; the widgets take epoch
    milliseconds and the document's text, as they do from a single query.
    """
    if value is None:
        return None
    if type_name in _DATE_TYPES and isinstance(value, str):
        try:
            moment = (
                date.fromisoformat(value)
                if type_name == "date"
                else datetime.fromisoformat(value)
            )
        except ValueError:
            # ``infinity`` and its like have no instant to convert to.
            return value
        return _wire(moment)
    if type_name == "numeric" and isinstance(value, (int, float)):
        return float(value)
    if type_name in {"json", "jsonb"}:
        return json.dumps(value)
    return value


async def _run_compiled(
    statements: Mapping[str, ResolvedQuery],
    *,
    guild_id: int,
    routed: RequestContext,
) -> dict[str, QueryResult | QueryError]:
    """Every statement in *statements*, as one compiled statement, in one
    transaction holding one slot. A statement whose sheet cannot be read
    answers with that refusal, and the rest run without it."""
    outcomes: dict[str, QueryResult | QueryError] = {}
    async with cohorts.query_sessionmaker(guild_id)() as session:
        await session.begin()
        sqlalchemy_connection = await session.connection()
        raw = await sqlalchemy_connection.get_raw_connection()
        connection = raw.driver_connection

        await _bound_transaction(
            sqlalchemy_connection, timeout_ms=QUERY_CANVAS_TIMEOUT_MS
        )
        if not await _claim_a_slot(sqlalchemy_connection, guild_id):
            raise QueryError(QueryMessages.BUSY, str(guild_id))
        await set_rls_context(session, routed)

        runnable: dict[str, ResolvedQuery] = {}
        for key, statement in statements.items():
            try:
                runnable[key] = await _with_cells(session, statement, guild_id)
            except QueryError as refused:
                outcomes[key] = refused
        statements = runnable
        keys = list(statements)
        if not keys:
            await session.rollback()
            return outcomes

        # Each widget is prepared — planned, not run — for the columns it
        # returns, which the JSON the compiled statement answers with does not
        # carry.
        shapes = []
        for key in keys:
            prepared = await connection.prepare(statements[key].sql)
            columns = await _described(connection, prepared, statements[key])
            type_names = [a.type.name for a in prepared.get_attributes()]
            shapes.append((columns, type_names))

        compiled = compile_canvas(
            [statements[key] for key in keys], row_limit=QUERY_MAX_ROWS + 1
        )
        plan = await connection.fetchval(
            "EXPLAIN (FORMAT JSON) " + compiled.sql, *compiled.parameters
        )
        document = json.loads(plan) if isinstance(plan, str) else plan
        cost = float(document[0]["Plan"]["Total Cost"])
        if cost > QUERY_MAX_COST * len(keys):
            raise QueryError(QueryMessages.TOO_EXPENSIVE, f"{cost:.0f}")

        record = await connection.fetchrow(compiled.sql, *compiled.parameters)
        await session.rollback()

    for index, key in enumerate(keys):
        columns, type_names = shapes[index]
        answered = record[index] if record is not None else None
        rows = json.loads(answered) if isinstance(answered, str) else (answered or [])
        truncated = len(rows) > QUERY_MAX_ROWS
        outcomes[key] = QueryResult(
            columns=columns,
            rows=tuple(
                tuple(
                    _from_json(row.get(f"f{position + 1}"), type_name)
                    for position, type_name in enumerate(type_names)
                )
                for row in rows[:QUERY_MAX_ROWS]
            ),
            cost=cost,
            truncated=truncated,
            relations=statements[key].relations,
        )
    return outcomes


async def execute_canvas(
    statements: Mapping[str, ResolvedQuery],
    *,
    context: RequestContext,
    initiative_id: int | None = None,
) -> dict[str, QueryResult | QueryError]:
    """Run every widget on a canvas, keyed as *statements* is.

    The statements are compiled into one (:mod:`app.services.query.canvas`)
    and run in one transaction holding one of the guild's slots, under the
    same context, role, limits and narrowing as :func:`execute`. A dataset
    several widgets read is read once.

    One widget failing, or the whole canvas running past its time or cost,
    fails the compiled statement. The widgets are then run one at a time
    through :func:`execute`, so each answers or refuses on its own. A guild
    with no free slot refuses the canvas as a whole.
    """
    if not statements:
        return {}
    routed = _as_query(context, initiative_id)
    guild_id = routed.guild_id
    try:
        async with _translated_failures():
            return dict(
                await _run_compiled(statements, guild_id=guild_id, routed=routed)
            )
    except QueryError as refused:
        if refused.code == QueryMessages.BUSY:
            raise

    outcomes: dict[str, QueryResult | QueryError] = {}
    for key, statement in statements.items():
        try:
            outcomes[key] = await execute(
                statement,
                context=context,
                initiative_id=initiative_id,
            )
        except QueryError as refused:
            outcomes[key] = refused
    return outcomes
