"""Parse a reader's SQL, admit only a read of declared names, and rewrite it.

Three things happen here, over the parsed statement:

**Admit only a read.** The statement must be a single ``SELECT``. Every node in
it must be one this surface accepts, and every function must be one it names —
both allow-lists, so a construct nobody considered is refused rather than
carried through.

**Resolve every name.** Relations resolve through the field registry to the
model behind them; columns resolve to the field's own column. The statement
handed back is written out from the parsed tree rather than forwarded, so it
carries only names the registry produced.

**Read spreadsheets and plug-ins as relations.** ``sheet(file, range)`` in
``FROM`` names a range of a spreadsheet the way a dataset is named, and
``plugin(public id, endpoint, name => value, …)`` one of an installed plug-in's
read endpoints. Their columns are what was read, so a statement that names one
resolves fully only once its rows are read (:mod:`app.services.query.sheets`,
:mod:`app.services.query.plugins`); the rows are then bound into the statement
as one parameter, and nothing of them reaches the SQL text.

**Refuse what is structurally expensive.** A join whose condition pairs nothing
pairs every row with every row; a statement may name only so many relations.
Both are answered from the parsed statement, before anything is planned.

This layer is where a refusal gets a *reason*: a machine code and the word that
has to change. Execution settles the rest — the transaction, the role and the
cost ceiling are the executor's, and are described there.

The parser is PostgreSQL's own, through ``pglast``. That matters most where a
grammar is surprising: ``/* /* x */ */`` is one comment to Postgres and to this,
``EXTRACT`` arrives already rewritten to ``pg_catalog.extract``, and ``coalesce``
is not a function call but a node of its own. Reading a statement the way the
server reads it is what lets the rules below be written against what will run.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from typing import Any

from fastapi import status
from pglast import ast, parse_sql
from pglast.enums import A_Expr_Kind, SetOperation
from pglast.parser import ParseError, scan
from pglast.stream import RawStream
from pglast.visitors import Visitor
from sqlalchemy import column as sql_column
from sqlalchemy.dialects import postgresql

from app.core.errors import CodedError
from app.core.messages import QueryMessages
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.db import gucs
from app.services.fields import dataset
from app.services.fields.registry import dataset_names
from app.services.fields.spec import (
    ControlKind,
    Dataset,
    FieldSpec,
    FieldType,
    column,
)

#: ``EXPLAIN``'s options, as the grammar spells them.
_EXPLAIN_JSON = (ast.DefElem(defname="format", arg=ast.String(sval="json")),)

#: How many relations one statement may name. A dashboard tile asks about one
#: thing, sometimes joined to a second; the ceiling is what keeps a statement's
#: cost proportional to a guild's data rather than a power of it.
MAX_RELATIONS = 4


#: What each refusal is, as HTTP. Everything not named here is something the
#: reader can fix in the statement.
_REFUSAL_STATUS = {
    QueryMessages.BUSY: status.HTTP_429_TOO_MANY_REQUESTS,
    QueryMessages.TIMED_OUT: status.HTTP_504_GATEWAY_TIMEOUT,
    QueryMessages.INTERRUPTED: status.HTTP_503_SERVICE_UNAVAILABLE,
}


class QueryError(CodedError):
    """A query this surface will not run, and the word that has to change."""

    def __init__(self, code: str, subject: str = "") -> None:
        super().__init__(code, _REFUSAL_STATUS.get(code))
        self.subject = subject

    def __str__(self) -> str:
        return f"{self.code}: {self.subject}" if self.subject else self.code


#: The functions a statement reads a spreadsheet and a plug-in with, and the
#: name each is read under when the call gives itself no alias, as Postgres
#: names a function in ``FROM`` after itself.
SHEET = "sheet"
PLUGIN = "plugin"

#: What each type a range's column may hold is in the statement: the control
#: that filters it, and the Postgres type its cells are read as.
_SHEET_TYPES: dict[str, tuple[ControlKind, str]] = {
    "number": (ControlKind.number, "numeric"),
    "date": (ControlKind.date, "date"),
    "datetime": (ControlKind.date, "timestamp"),
    "boolean": (ControlKind.boolean, "boolean"),
    "text": (ControlKind.text, "text"),
}


#: The same for each type a plug-in endpoint's return may declare.
_PLUGIN_TYPES: dict[str, tuple[ControlKind, str]] = {
    "bool": _SHEET_TYPES["boolean"],
    "datetime": (ControlKind.date, "timestamptz"),
    "int": _SHEET_TYPES["number"],
    "string": _SHEET_TYPES["text"],
    "url": _SHEET_TYPES["text"],
}


@dataclass(frozen=True)
class SheetCall:
    """``sheet(file, range)`` as a statement wrote it: the spreadsheet by id or
    by name, and the range, or none for the first visible sheet."""

    file: int | str
    range: str | None = None


@dataclass(frozen=True)
class PluginCall:
    """``plugin(public id, endpoint, name => value, …)`` as a statement wrote
    it: the plug-in by its public id, its read endpoint by the name after the
    plug-in's prefix, and the parameters, by name. A list parameter's values
    are a tuple."""

    plugin: str
    endpoint: str
    params: tuple[tuple[str, Any], ...] = ()

    @property
    def endpoint_id(self) -> str:
        """The endpoint's id, as the plug-in's manifest declares it."""
        return f"plugin.{self.plugin}.{self.endpoint}"


class _SheetNames(dict):
    """A recordset's columns by name, matched ignoring case.

    A name two columns share is refused when a statement names it. A
    recordset not read yet holds every name, as text, so a statement can be
    checked before its rows are read.
    """

    def __init__(self, fields: Sequence[FieldSpec], read: bool) -> None:
        super().__init__()
        self.read = read
        self.shared: set[str] = set()
        for spec in fields:
            key = spec.name.lower()
            if dict.__contains__(self, key):
                self.shared.add(key)
            dict.__setitem__(self, key, spec)

    def __contains__(self, key: object) -> bool:
        return not self.read or (
            isinstance(key, str) and dict.__contains__(self, key.lower())
        )

    def get(self, key: Any, default: Any = None, /) -> Any:
        if not self.read:
            return column(key, sql_column(key), kind=ControlKind.text)
        if key.lower() in self.shared:
            raise QueryError(QueryMessages.AMBIGUOUS_FIELD, key)
        return dict.get(self, key.lower(), default)


@dataclass(frozen=True)
class Recordset(Dataset):
    """Rows a statement reads that are not a table's, as a dataset it names.

    Each column is read as ``c1``, ``c2``, … of the recordset the rows are
    bound into, so a name a column was given never reaches the SQL.
    """

    call: Any = None
    #: The Postgres type each column's values are read as, in order.
    types: tuple[str, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    #: Whether the rows were read. A statement is checked before they are, and
    #: runs only after.
    read: bool = True

    @property
    def by_name(self) -> dict[str, FieldSpec]:
        return _SheetNames(self.fields, self.read)

    @property
    def offered(self) -> tuple[FieldSpec, ...]:
        """Every column, in order."""
        return self.fields


def _columns(
    names: Sequence[str], kinds: Sequence[ControlKind]
) -> tuple[FieldSpec, ...]:
    return tuple(
        column(str(name), sql_column(f"c{index}"), kind=kind, sortable=True)
        for index, (name, kind) in enumerate(zip(names, kinds), start=1)
    )


@dataclass(frozen=True)
class Sheet(Recordset):
    """A range of a spreadsheet: its columns named by its header row or by
    their letters. Governed by the files tool, whose rows it is read from."""

    #: The workbook's visible sheets, for somebody picking one.
    sheet_names: tuple[str, ...] = ()

    @classmethod
    def unread(cls, call: SheetCall) -> Sheet:
        return cls(model=None, fields=(), tool=Tool.file, call=call, read=False)

    @classmethod
    def from_range(cls, call: SheetCall, answer: Mapping[str, Any]) -> Sheet:
        """The sheet a range read (``lib/spreadsheet/range.ts``)."""
        columns = answer.get("columns") or ()
        kinds = [_SHEET_TYPES[entry["type"]] for entry in columns]
        return cls(
            model=None,
            fields=_columns(
                [entry["name"] for entry in columns], [kind for kind, _ in kinds]
            ),
            tool=Tool.file,
            call=call,
            types=tuple(postgres for _, postgres in kinds),
            rows=tuple(tuple(row) for row in answer.get("rows") or ()),
            sheet_names=tuple(answer.get("sheets") or ()),
        )


def _plugin_value(value: Any, postgres: str) -> Any:
    """One value a plug-in answered with, as its column reads it: ``None``
    where it is not of the column's type."""
    if value is None:
        return None
    if postgres == "boolean":
        return value if isinstance(value, bool) else None
    if postgres == "numeric":
        return (
            value
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else None
        )
    if postgres == "timestamptz":
        try:
            datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None
        return value
    return value if isinstance(value, str) else json.dumps(value)


@dataclass(frozen=True)
class PluginRows(Recordset):
    """The rows one of a plug-in's read endpoints answered with: a column for
    each return it declares as a list, named by its key."""

    @classmethod
    def unread(cls, call: PluginCall) -> PluginRows:
        return cls(
            model=None, fields=(), name_override="plugins", call=call, read=False
        )

    @classmethod
    def from_rows(
        cls,
        call: PluginCall,
        columns: Sequence[tuple[str, str]],
        rows: Sequence[Mapping[str, Any]],
    ) -> PluginRows:
        """The rows, under *columns*: each return's key and declared type."""
        kinds = [_PLUGIN_TYPES.get(kind, _SHEET_TYPES["text"]) for _, kind in columns]
        return cls(
            model=None,
            fields=_columns([key for key, _ in columns], [kind for kind, _ in kinds]),
            name_override="plugins",
            call=call,
            types=tuple(postgres for _, postgres in kinds),
            rows=tuple(
                tuple(
                    _plugin_value(row.get(key), postgres)
                    for (key, _), (_, postgres) in zip(columns, kinds)
                )
                for row in rows
            ),
        )


@dataclass(frozen=True)
class ResolvedQuery:
    """A statement built from declared names, ready to be planned."""

    #: The statement, written out from the tree. Physical names, ``$1``-style
    #: parameters, and nothing of the reader's own text.
    sql: str
    #: The literal values, in the order the parameters number them.
    parameters: tuple[Any, ...] = ()
    #: The datasets this statement reads, for the caller that decides whether
    #: the reader may read them.
    relations: tuple[str, ...] = ()
    #: What the registry calls each output column, by position, where it can
    #: name one. ``None`` where the output is an expression rather than a
    #: field, and the database is the one to describe it.
    column_types: tuple[FieldType | None, ...] = ()
    #: The period each output column is rounded to, by position: the unit of a
    #: ``date_trunc`` the column is, or ``None``. A chart labels a point by it
    #: ("Mar 2026", "Q1 2026") instead of guessing from the dates it got back.
    column_grains: tuple[str | None, ...] = ()
    #: Whether the statement asked about whoever is reading it. A caller that
    #: needs one answer for everybody has to know, because this is the one
    #: thing in the language that makes a statement answer differently per
    #: person.
    names_the_reader: bool = False
    #: The spreadsheets and plug-ins the statement reads, by the name each is
    #: read under. Until every one is :attr:`Recordset.read`, the statement is
    #: checked but not runnable.
    sheets: tuple[tuple[str, Sheet], ...] = ()
    plugins: tuple[tuple[str, PluginRows], ...] = ()
    #: The statement as written, kept while it has rows to read: once they are
    #: read it is resolved again with what they read.
    source: str = ""

    @property
    def unread(self) -> tuple[SheetCall | PluginCall, ...]:
        """The calls whose rows still have to be read before it runs."""
        return tuple(
            dict.fromkeys(
                recordset.call
                for _, recordset in (*self.sheets, *self.plugins)
                if not recordset.read
            )
        )

    @property
    def read(self) -> dict[Any, Recordset]:
        """What the calls already read, by call."""
        return {
            recordset.call: recordset
            for _, recordset in (*self.sheets, *self.plugins)
            if recordset.read
        }

    def explain(self) -> str:
        """This statement, asking for its plan instead of its rows.

        ``EXPLAIN`` takes a statement where a value would go, so there is no
        parameter to bind it as. It is built in the tree and written out by the
        deparser that wrote the statement, rather than composed around the text
        of one — the same deparser, over one tree, saying both things.
        """
        root = ast.ExplainStmt(query=parse_sql(self.sql)[0].stmt, options=_EXPLAIN_JSON)
        return RawStream()(root)


# --- what the surface accepts ------------------------------------------------

#: Node types a statement may contain. An allow-list: a construct absent here
#: is refused by name, which is what keeps "we did not think about it" from
#: meaning "it runs". Subqueries and CTEs are absent deliberately — admitting
#: them is adding a scope to resolve names against.
_ALLOWED_NODES: frozenset[type] = frozenset(
    {
        # shape
        ast.SelectStmt,
        ast.ResTarget,
        ast.RangeVar,
        ast.Alias,
        ast.JoinExpr,
        ast.SortBy,
        # names and values
        ast.ColumnRef,
        ast.A_Const,
        ast.ParamRef,
        ast.String,
        ast.Integer,
        ast.Float,
        ast.Boolean,
        # predicates and arithmetic
        ast.A_Expr,
        ast.BoolExpr,
        ast.NullTest,
        ast.BooleanTest,
        # things Postgres parses as their own node rather than a call
        ast.CaseExpr,
        ast.CaseWhen,
        ast.CoalesceExpr,
        ast.MinMaxExpr,
        ast.TypeCast,
        ast.TypeName,
        # calls, checked by name below
        ast.FuncCall,
        # ``OVER (...)``: a running total, a rank. It reads the rows the
        # statement already reads and adds no relation to resolve names in.
        ast.WindowDef,
    }
)

#: Functions a query may call. Postgres reports the name it resolved, so these
#: are the names as the server sees them — ``extract`` arrives qualified with
#: ``pg_catalog`` because the grammar rewrites it, and ``coalesce`` never
#: arrives at all because it is a node rather than a call.
#:
#: Public, because a client helping somebody write a statement has to offer the
#: same set this refuses everything outside of.
#: Functions that only mean something over a window: a rank, the row before.
#: Public, because a statement over a plug-in's rows has no window to run them
#: in and refuses them by this list.
WINDOW_FUNCTIONS: frozenset[str] = frozenset(
    {
        "row_number",
        "rank",
        "dense_rank",
        "percent_rank",
        "cume_dist",
        "ntile",
        "lag",
        "lead",
        "first_value",
        "last_value",
        "nth_value",
    }
)

ALLOWED_FUNCTIONS: frozenset[str] = WINDOW_FUNCTIONS | frozenset(
    {
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "abs",
        "round",
        "length",
        "lower",
        "upper",
        "concat",
        "date_trunc",
        "extract",
        "now",
    }
)

#: The only schema a function name may carry. It is the one Postgres itself
#: puts there when it rewrites a spelling into a call.
_FUNCTION_SCHEMA = "pg_catalog"

#: The one name a statement may use that is not a column: the reader.
#:
#: A saved statement holds no reader in it, so ``where created_by = me`` is one
#: widget answering differently for each person who opens the dashboard —
#: which is the only way a dashboard can be about you. The filter path has
#: taken the same word for as long as it has had an assignee filter; this is
#: that idea in the language rather than in one field's handler.
#:
#: It is a value and nothing more: the reader's own id, on the right of a
#: comparison. Which rows a statement reads is settled elsewhere — the guild by
#: the routing, the initiative by the dashboard the tile sits on — and naming
#: the reader narrows within that, one comparison like any other. It is not the
#: ``/me/`` routes' cross-guild sense of the word.
#:
#: Public, because a client offering what a statement may contain has to offer
#: this beside the datasets and the functions.
VIEWER = "me"

#: What ``me`` is written as, once. The request already says who is asking, so
#: this reads it there rather than being handed it — which keeps resolution
#: pure, keeps the reader's id out of anything stored, and leaves the answer to
#: the moment the statement runs rather than the moment it was written.
#:
#: Unset it reads as null, and a comparison against null selects nothing.
_VIEWER_EXPRESSION = gucs.USER_ID.sql


def _viewer_node() -> ast.Node:
    """``me`` as a tree, parsed rather than assembled.

    Built fresh per use: each occurrence is its own node, and a tree is not
    something to share between two places in another tree.
    """
    target = parse_sql(f"SELECT {_VIEWER_EXPRESSION}")[0].stmt.targetList[0]
    return target.val


def _name_parts(parts: Any) -> list[str]:
    """The words of a dotted name, as the parser reports them.

    A node's name list is optional in the grammar's own types, so a name that
    is not there reads as no words and is refused by the caller rather than
    assumed to be well formed.
    """
    return [part.sval for part in (parts or ()) if isinstance(part, ast.String)]


def _physical_table(dataset_name: str) -> tuple[str | None, str]:
    """The schema and name of the table behind a dataset. A community's own
    tables carry no schema, and resolve to the routed one."""
    table = dataset(dataset_name).model.__table__
    return table.schema, table.name


def _derived(source: Dataset, spec: Any) -> bool:
    """Whether a field is read through an expression over its table's columns
    rather than as one of them: the author, a person only where its kind is
    ``member``."""
    return (
        not isinstance(source, Recordset)
        and spec.column is not None
        and not hasattr(spec.column, "property")
    )


def _physical_column(source: Dataset, field_name: str, handle: str) -> Any:
    """The column a field names, or for a derived field its expression as a
    statement node, its columns read from ``handle``."""
    spec = source.by_name.get(field_name)
    if spec is None:
        raise QueryError(QueryMessages.UNKNOWN_FIELD, f"{source.name}.{field_name}")
    if spec.column is None:
        raise QueryError(
            QueryMessages.FIELD_NOT_SELECTABLE, f"{source.name}.{field_name}"
        )
    if isinstance(source, Recordset):
        return spec.column.name
    if not _derived(source, spec):
        return spec.column.property.columns[0].name
    compiled = spec.column.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    )
    expression = parse_sql(f"SELECT {compiled}")[0].stmt.targetList[0].val

    class Qualify(Visitor):
        def visit_ColumnRef(self, ancestors: Any, ref: ast.ColumnRef) -> None:
            ref.fields = (ast.String(sval=handle), *(ref.fields or ())[-1:])

    Qualify()(expression)
    return expression


def _parse(sql: str) -> ast.SelectStmt:
    try:
        statements = parse_sql(sql)
    except ParseError as err:
        raise QueryError(QueryMessages.UNPARSEABLE, str(err).splitlines()[0]) from err
    if not statements:
        raise QueryError(QueryMessages.UNPARSEABLE)
    if len(statements) > 1:
        raise QueryError(QueryMessages.ONE_STATEMENT_ONLY)
    root = statements[0].stmt
    if not isinstance(root, ast.SelectStmt):
        raise QueryError(QueryMessages.READ_ONLY, type(root).__name__)
    _check_select_shape(root)
    return root


def _check_select_shape(select: ast.SelectStmt) -> None:
    """The parts of a SELECT this surface does not take."""
    if select.op != SetOperation.SETOP_NONE:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "SET_OPERATION")
    for attribute, name in (
        ("withClause", "WITH"),
        ("lockingClause", "LOCKING"),
        ("intoClause", "INTO"),
        ("valuesLists", "VALUES"),
    ):
        if getattr(select, attribute, None):
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, name)
    for target in select.targetList or ():
        if isinstance(target, ast.ResTarget) and target.name == VIEWER:
            # An output column called ``me`` would make ``order by me`` mean
            # two things, and the word already means one.
            raise QueryError(QueryMessages.RESERVED_NAME, VIEWER)


def _swap(node: Any, swaps: Mapping[int, ast.Node]) -> Any:
    """*node*, with the relations in *swaps* replaced wherever a join holds
    them."""
    if id(node) in swaps:
        return swaps[id(node)]
    if isinstance(node, ast.JoinExpr):
        node.larg = _swap(node.larg, swaps)
        node.rarg = _swap(node.rarg, swaps)
    return node


def _sheet_call(args: Sequence[Any]) -> SheetCall:
    """``sheet()``'s arguments: the file, and the range if there is one."""
    values = [
        _value(arg) for arg in args if isinstance(arg, ast.A_Const) and not arg.isnull
    ]
    if (
        not 1 <= len(args) <= 2
        or len(values) != len(args)
        or isinstance(values[0], (bool, float))
        or (len(values) == 2 and not isinstance(values[1], str))
    ):
        raise QueryError(QueryMessages.SHEET_ARGUMENTS, SHEET)
    return SheetCall(file=values[0], range=values[1] if len(values) == 2 else None)


def _plugin_call(args: Sequence[Any]) -> PluginCall:
    """``plugin()``'s arguments: the plug-in's public id and the endpoint's
    name, then its parameters by name, each a constant or an ``ARRAY`` of
    them."""

    def constant(node: Any, *, listed: bool = False) -> Any:
        if isinstance(node, ast.A_Const) and not node.isnull:
            return _value(node)
        if listed and isinstance(node, ast.A_ArrayExpr) and node.elements:
            return tuple(constant(element) for element in node.elements)
        raise QueryError(QueryMessages.PLUGIN_ARGUMENTS, PLUGIN)

    named = [arg for arg in args[2:] if isinstance(arg, ast.NamedArgExpr)]
    if len(args) < 2 or len(named) != len(args) - 2:
        raise QueryError(QueryMessages.PLUGIN_ARGUMENTS, PLUGIN)
    plugin, endpoint = (constant(arg) for arg in args[:2])
    params = {arg.name: constant(arg.arg, listed=True) for arg in named}
    if (
        not isinstance(plugin, str)
        or not isinstance(endpoint, str)
        or len(params) != len(named)
    ):
        raise QueryError(QueryMessages.PLUGIN_ARGUMENTS, PLUGIN)
    return PluginCall(plugin, endpoint, tuple(sorted(params.items())))


def _take_calls(
    select: ast.SelectStmt,
) -> dict[int, tuple[str, SheetCall | PluginCall]]:
    """The ``sheet()`` and ``plugin()`` calls in ``FROM``, each replaced by a
    relation named after its function under the call's own alias, so the rest
    of the statement is read the way any other is. Keyed by that relation,
    which is how the call is found again once its rows are read, with the
    handle it is read under.

    They are the only functions ``FROM`` takes, called plainly with constants.
    """
    calls: dict[int, tuple[str, SheetCall | PluginCall]] = {}
    swaps: dict[int, ast.Node] = {}

    def walk(node: Any) -> None:
        if isinstance(node, ast.JoinExpr):
            walk(node.larg)
            walk(node.rarg)
        if not isinstance(node, ast.RangeFunction):
            return
        functions: tuple[Any, ...] = node.functions or ()
        for flag, name in (
            (node.lateral, "LATERAL"),
            (node.ordinality, "WITH ORDINALITY"),
            (node.is_rowsfrom or len(functions) != 1, "ROWS FROM"),
            (node.coldeflist or (node.alias and node.alias.colnames), "column list"),
        ):
            if flag:
                raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, name)
        call, definitions = functions[0]
        names = _name_parts(call.funcname) if isinstance(call, ast.FuncCall) else []
        if names not in ([SHEET], [PLUGIN]):
            raise QueryError(
                QueryMessages.UNSUPPORTED_FUNCTION,
                ".".join(names) or type(call).__name__,
            )
        name = names[0]
        if (
            definitions
            or call.agg_star
            or call.agg_distinct
            or call.func_variadic
            or call.agg_order is not None
            or call.agg_filter is not None
            or call.over is not None
        ):
            raise QueryError(
                QueryMessages.SHEET_ARGUMENTS
                if name == SHEET
                else QueryMessages.PLUGIN_ARGUMENTS,
                name,
            )
        args = tuple(call.args or ())
        handle = node.alias.aliasname if node.alias else name
        standing = ast.RangeVar(
            relname=name, inh=True, alias=ast.Alias(aliasname=handle)
        )
        calls[id(standing)] = (
            handle,
            _sheet_call(args) if name == SHEET else _plugin_call(args),
        )
        swaps[id(node)] = standing

    for node in select.fromClause or ():
        walk(node)
    if swaps:
        select.fromClause = tuple(
            _swap(node, swaps) for node in select.fromClause or ()
        )
    return calls


def _column_refs(node: Any) -> list[ast.ColumnRef]:
    """Every column reference under *node*, in the order they are met."""
    found: list[ast.ColumnRef] = []

    class Collect(Visitor):
        def visit_ColumnRef(self, ancestors: Any, inner: ast.ColumnRef) -> None:
            found.append(inner)

    if node is not None:
        Collect()(node)
    return found


def joined(base: str, relation: Any, node: ast.Node, handle: str) -> ast.Node:
    """*node*, joined to everything *relation* passes through.

    Each hop is an ordinary inner join whose condition relates the two sides,
    which is what a join is asked to be here — so a statement that reaches
    through a relation is checked exactly like one that spelled the join out.
    The last hop is aliased to the relation's own name, so the columns read
    ``assignee.display_name``.

    Shared with the builder, which writes the same joins from the same
    declarations: one way of getting there, whether somebody clicked it or
    typed it.
    """
    left = base
    for index, hop in enumerate(relation.hops):
        last = index == len(relation.hops) - 1
        alias = handle if last else f"{handle}__{hop.dataset}"
        node = ast.JoinExpr(
            jointype=0,
            larg=node,
            rarg=ast.RangeVar(
                relname=hop.dataset, inh=True, alias=ast.Alias(aliasname=alias)
            ),
            quals=ast.A_Expr(
                kind=A_Expr_Kind.AEXPR_OP,
                name=(ast.String(sval="="),),
                lexpr=ast.ColumnRef(
                    fields=(ast.String(sval=left), ast.String(sval=hop.left))
                ),
                rexpr=ast.ColumnRef(
                    fields=(ast.String(sval=alias), ast.String(sval=hop.right))
                ),
            ),
        )
        left = alias
    return node


def _declared_handles(node: Any, found: dict[str, str]) -> None:
    """The relations a ``FROM`` names, by the handle a column would use, read
    before anything is rewritten."""
    if isinstance(node, ast.JoinExpr):
        _declared_handles(node.larg, found)
        _declared_handles(node.rarg, found)
        return
    if isinstance(node, ast.RangeVar):
        found[node.alias.aliasname if node.alias else node.relname] = node.relname


def _expand_relations(select: ast.SelectStmt) -> None:
    """Join in the datasets a statement reached through without saying so.

    A dataset declares what it can be read alongside, so ``assignee.display_name``
    over ``tasks`` is a person's name without anybody writing two joins to reach
    one. The expansion happens here, before names are resolved, so everything
    downstream sees a statement that spelled its joins out — including the
    checks on how many relations one statement may name and on each join being
    bound.
    """
    if not select.fromClause:
        return
    handles: dict[str, str] = {}
    _declared_handles(select.fromClause[0], handles)

    wanted: list[str] = []
    for node in _column_refs(select):
        parts = _name_parts(node.fields)
        if len(parts) == 2 and parts[0] not in handles and parts[0] not in wanted:
            wanted.append(parts[0])
    if not wanted:
        return

    node = select.fromClause[0]
    for name in wanted:
        sources = [
            (handle, dataset(known).by_relation[name])
            for handle, known in handles.items()
            if known in dataset_names() and name in dataset(known).by_relation
        ]
        if not sources:
            # Not a relation anybody declared. Left as it is, so the name is
            # refused where every other unknown relation is.
            continue
        if len(sources) > 1:
            raise QueryError(QueryMessages.AMBIGUOUS_FIELD, name)
        base, relation = sources[0]
        node = joined(base, relation, node, name)
    select.fromClause = (node,)


def _relations(
    select: ast.SelectStmt, recordsets: Mapping[int, Recordset] | None = None
) -> dict[str, Dataset]:
    """The relations in scope, by the name a column may qualify with.

    Rewrites each dataset to the table behind it as it goes, so the tree
    carries physical names by the time it is written out. *recordsets* holds the
    relations :func:`_take_calls` stood in for ``sheet()`` and ``plugin()``
    calls, and what
    each read.
    """
    recordsets = recordsets or {}
    if not select.fromClause:
        raise QueryError(QueryMessages.MISSING_RELATION)
    if len(select.fromClause) > 1:
        # Relations listed side by side, which pairs every row with every row.
        raise QueryError(QueryMessages.JOIN_WITHOUT_CONDITION, "FROM")

    known = set(dataset_names())
    scope: dict[str, Dataset] = {}

    # Each join, with the relations on either side of it. A join is bound by a
    # condition relating what it *adds* to what was already there, so knowing
    # which relations those are is part of reading the tree.
    joins: list[tuple[ast.JoinExpr, set[str], set[str]]] = []

    def visit(node: Any) -> set[str]:
        if isinstance(node, ast.JoinExpr):
            if node.usingClause:
                # ``USING`` names columns positionally rather than as column
                # references, so the resolving pass below never sees them.
                # ``ON`` says the same thing in a form that resolves.
                raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "USING")
            left = visit(node.larg)
            right = visit(node.rarg)
            joins.append((node, left, right))
            return left | right
        if not isinstance(node, ast.RangeVar):
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(node).__name__)
        if node.schemaname or node.catalogname:
            raise QueryError(QueryMessages.QUALIFIED_RELATION, node.relname)
        recordset = recordsets.get(id(node))
        if recordset is None and node.relname not in known:
            raise QueryError(QueryMessages.UNKNOWN_RELATION, node.relname)
        handle = node.alias.aliasname if node.alias else node.relname
        if handle == VIEWER:
            raise QueryError(QueryMessages.RESERVED_NAME, VIEWER)
        if handle in scope:
            raise QueryError(QueryMessages.DUPLICATE_ALIAS, handle)
        if recordset is not None:
            scope[handle] = recordset
            return {handle}
        scope[handle] = dataset(node.relname)
        node.schemaname, node.relname = _physical_table(node.relname)
        return {handle}

    visit(select.fromClause[0])

    # After the relations, so a statement gets the more specific answer: an
    # alias used twice is named as that, not as the join it sits in.
    for join, left, right in joins:
        if not _join_is_bound(join, left, right):
            raise QueryError(QueryMessages.JOIN_WITHOUT_CONDITION, "JOIN")

    if len(scope) > MAX_RELATIONS:
        raise QueryError(QueryMessages.TOO_MANY_RELATIONS, str(len(scope)))
    return scope


def _relations_named(node: Any) -> set[str]:
    """The relations one side of a comparison reads from."""
    named: set[str] = set()

    class Qualifiers(Visitor):
        def visit_ColumnRef(self, ancestors: Any, inner: ast.ColumnRef) -> None:
            parts = _name_parts(inner.fields)
            if len(parts) > 1:
                named.add(parts[0])

    if node is not None:
        Qualifiers()(node)
    return named


def _join_is_bound(join: ast.JoinExpr, left: set[str], right: set[str]) -> bool:
    """Whether a join's condition ties what it adds to what was already there.

    The test is one comparison reading a relation from each side of *this*
    join. Weaker readings each let a cross product through:

    * "the condition is not empty" admits ``ON true``;
    * "it mentions two relations" admits ``ON tasks.id > 0 AND
      projects.id > 0``, which filters each relation and still pairs every
      surviving row with every other;
    * "it relates some two relations" admits a third join whose condition
      relates the first two, leaving the one being added unconstrained.
    """
    if join.quals is None:
        return False
    relating = False

    class Relating(Visitor):
        def visit_A_Expr(self, ancestors: Any, node: ast.A_Expr) -> None:
            nonlocal relating
            near = _relations_named(node.lexpr)
            far = _relations_named(node.rexpr)
            if (near & left and far & right) or (near & right and far & left):
                relating = True

    Relating()(join.quals)
    return relating


def _check_nodes(select: ast.SelectStmt) -> None:
    class Check(Visitor):
        # pglast's stub declares ``visit`` an optional callable attribute; its
        # visitors define it as a method, the default for every node.
        def visit(self, ancestors: Any, node: Any) -> None:  # ty: ignore[invalid-mutable-override]
            if type(node) not in _ALLOWED_NODES:
                raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(node).__name__)

        def visit_FuncCall(self, ancestors: Any, node: ast.FuncCall) -> None:
            names = _name_parts(node.funcname)
            if not names:
                raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION)
            if len(names) > 2 or (len(names) == 2 and names[0] != _FUNCTION_SCHEMA):
                raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, ".".join(names))
            if names[-1] not in ALLOWED_FUNCTIONS:
                raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, names[-1])

        def visit_A_Star(self, ancestors: Any, node: ast.A_Star) -> None:
            # A query names the columns it wants; ``*`` would mean whatever the
            # table happens to hold, which is not something a saved tile can
            # rely on. ``count(*)`` carries a flag rather than a column, so it
            # never reaches here.
            raise QueryError(QueryMessages.STAR_NOT_ALLOWED)

    Check()(select)


def _alias_ordinals(
    select: ast.SelectStmt, scope: dict[str, Dataset]
) -> dict[int, int]:
    """The names that are an output column, and the position of that column.

    Postgres reads a name as an output column in two places only: standing
    alone as an ``ORDER BY`` entry, and standing alone as a ``GROUP BY`` entry
    that no relation has a column for. Inside an expression or a window the
    same word is a column, and is resolved as one. Each of these is written
    out as the position it names, so what reaches the database is an ordinal
    rather than a word.
    """
    positions: dict[str, list[int]] = {}
    for position, target in enumerate(select.targetList or (), start=1):
        if isinstance(target, ast.ResTarget) and target.name:
            positions.setdefault(target.name, []).append(position)

    def output(node: Any) -> tuple[ast.ColumnRef, str] | None:
        if not isinstance(node, ast.ColumnRef):
            return None
        names = _name_parts(node.fields)
        if len(names) != 1 or names[0] not in positions:
            return None
        return node, names[0]

    found: list[tuple[ast.ColumnRef, str]] = []
    for entry in select.sortClause or ():
        named = output(entry.node if isinstance(entry, ast.SortBy) else entry)
        if named is not None:
            found.append(named)
    for entry in select.groupClause or ():
        named = output(entry)
        if named is not None and not any(
            named[1] in source.by_name for source in scope.values()
        ):
            found.append(named)

    ordinals: dict[int, int] = {}
    for node, name in found:
        if len(positions[name]) > 1:
            raise QueryError(QueryMessages.AMBIGUOUS_FIELD, name)
        ordinals[id(node)] = positions[name][0]
    return ordinals


def _holder(scope: dict[str, Dataset], field_name: str) -> str | None:
    """The relation in scope that has this field, where exactly one does, by
    its handle.

    An unqualified name is resolved the way the server resolves one: against
    whichever relation actually has it. ``None`` where none does or more than
    one does — the caller says which of those it is.

    Counted per relation in scope, not per dataset: the same table joined to
    itself is two relations, and a bare column of it names both. A recordset
    not read yet holds every name, so it holds one only when nothing read does.
    """
    holders = [
        handle for handle, source in scope.items() if field_name in source.by_name
    ]
    read = [
        handle
        for handle in holders
        if not (isinstance(scope[handle], Recordset) and not scope[handle].read)
    ]
    if read:
        return read[0] if len(read) == 1 else None
    return holders[0] if holders else None


def _output_types(
    select: ast.SelectStmt, scope: dict[str, Dataset]
) -> tuple[FieldType | None, ...]:
    """What the registry calls each output column.

    A target that is a field and nothing else *is* that field, and carries the
    registry's answer about it — an id that names a person is a person on the
    way out as much as on the way in, where the type it is stored as says only
    that it is a whole number. Read before the names are rewritten, because the
    registry is asked by the name the reader wrote.

    Anything built from a field rather than being one has no field to ask, and
    is left ``None`` for the database to describe.
    """
    return tuple(_target_type(target, scope) for target in select.targetList or ())


#: The units of ``date_trunc`` a column may be labelled by.
GRAINS = frozenset({"day", "week", "month", "quarter", "year"})


def _output_grains(select: ast.SelectStmt) -> tuple[str | None, ...]:
    """The period each output column is rounded to, read before the literals
    are bound: a target that is ``date_trunc('<unit>', …)`` is that unit."""
    return tuple(_target_grain(target) for target in select.targetList or ())


def _target_grain(target: ast.ResTarget) -> str | None:
    call = target.val
    # A rounded date cast to another date type is still rounded to that unit.
    while isinstance(call, ast.TypeCast):
        call = call.arg
    if not isinstance(call, ast.FuncCall):
        return None
    if _name_parts(call.funcname)[-1:] != ["date_trunc"]:
        return None
    args = call.args or ()
    if not args or not isinstance(args[0], ast.A_Const):
        return None
    unit = getattr(args[0].val, "sval", None)
    return unit.lower() if isinstance(unit, str) and unit.lower() in GRAINS else None


def _target_type(target: ast.ResTarget, scope: dict[str, Dataset]) -> FieldType | None:
    spec = _field_named(scope, target.val)
    return spec.type if spec is not None else None


def _field_named(scope: dict[str, Dataset], node: Any) -> Any:
    """The field a column reference names, or ``None`` when it is not one."""
    if not isinstance(node, ast.ColumnRef):
        return None
    names = _name_parts(node.fields)
    if len(names) == 2:
        handle, field_name = names[0], names[1]
    elif len(names) == 1:
        handle, field_name = _holder(scope, names[0]), names[0]
    else:
        return None
    source = scope.get(handle) if handle is not None else None
    return source.by_name.get(field_name) if source is not None else None


def _resolve_columns(select: ast.SelectStmt, scope: dict[str, Dataset]) -> set[int]:
    """Name every field by its column, and return the constants of the
    expressions a derived field was replaced with: the surface wrote them,
    so they are not bound as the reader's."""
    ordinals = _alias_ordinals(select, scope)
    for target in select.targetList or ():
        # A recordset's column is read as ``c1``, so an output that is one
        # keeps the name it was given.
        if not isinstance(target, ast.ResTarget) or target.name is not None:
            continue
        names = _name_parts(getattr(target.val, "fields", None))
        handle = names[0] if len(names) == 2 else None
        if len(names) == 1:
            handle = _holder(scope, names[0])
        spec = _field_named(scope, target.val)
        source = scope.get(handle or "")
        # A derived field is read as an expression, which would otherwise
        # name the output after itself.
        if spec is not None and (
            isinstance(source, Recordset)
            or (source is not None and _derived(source, spec))
        ):
            target.name = spec.name

    written: set[int] = set()

    class Resolve(Visitor):
        def visit_ColumnRef(self, ancestors: Any, node: ast.ColumnRef) -> Any:
            names = _name_parts(node.fields)
            if not names:
                raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "ColumnRef")
            if len(names) > 2:
                raise QueryError(QueryMessages.QUALIFIED_RELATION, ".".join(names))
            if len(names) == 2:
                source = scope.get(names[0])
                if source is None:
                    raise QueryError(QueryMessages.UNKNOWN_RELATION, names[0])
                column = _physical_column(source, names[1], names[0])
                if not isinstance(column, str):
                    written.update(_constants_in(column))
                    return column
                node.fields = (ast.String(sval=names[0]), ast.String(sval=column))
                return
            if names[0] == VIEWER:
                # Expanded once the literals are bound, so what it expands to
                # is not read as something the reader wrote.
                return
            if id(node) in ordinals:
                # An output column, where Postgres reads the name as one:
                # ``ORDER BY n`` names the count.
                return ast.A_Const(val=ast.Integer(ival=ordinals[id(node)]))
            holder = _holder(scope, names[0])
            if holder is None:
                # Nothing in scope has it, or more than one does. Which of
                # those it is decides what the reader has to change.
                known = any(names[0] in source.by_name for source in scope.values())
                raise QueryError(
                    QueryMessages.AMBIGUOUS_FIELD
                    if known
                    else QueryMessages.UNKNOWN_FIELD,
                    names[0],
                )
            column = _physical_column(scope[holder], names[0], holder)
            if not isinstance(column, str):
                written.update(_constants_in(column))
                return column
            # A recordset's columns are all named ``c<n>``, so one is always
            # written with the handle it is read under.
            node.fields = tuple(
                ast.String(sval=part)
                for part in (
                    (holder, column)
                    if isinstance(scope[holder], Recordset)
                    else (column,)
                )
            )

    Resolve()(select)
    return written


def _is_viewer(node: Any) -> bool:
    return isinstance(node, ast.ColumnRef) and _name_parts(node.fields) == [VIEWER]


def _holds_a_person(node: Any, scope: dict[str, Dataset]) -> bool:
    """Whether *node* is a field that holds a person.

    Read by the name the reader wrote, so this is asked before the names are
    rewritten — the registry answers about ``assignee.id``, not about whatever
    column the members view keeps it in.
    """
    spec = _field_named(scope, node)
    return spec is not None and spec.kind is ControlKind.member


def _check_viewer(select: ast.SelectStmt, scope: dict[str, Dataset]) -> None:
    """That ``me`` is somewhere it means something.

    The reader is a person, so the only thing to say about them is which person
    a field holds. Anywhere else the word would expand into a number beside
    something that is not one, and the statement would be a statement the
    database refuses — on a tile, long after it was written. This is the same
    rule the builder writes by, asked of a statement somebody typed.
    """
    placed: set[int] = set()

    class Compare(Visitor):
        def visit_A_Expr(self, ancestors: Any, node: ast.A_Expr) -> None:
            if node.kind == A_Expr_Kind.AEXPR_IN:
                against = node.lexpr
                sides = tuple(node.rexpr or ())
            elif node.kind == A_Expr_Kind.AEXPR_OP:
                against, sides = None, (node.lexpr, node.rexpr)
            else:
                return
            for index, side in enumerate(sides):
                if not _is_viewer(side):
                    continue
                other = against if against is not None else sides[1 - index]
                if not _holds_a_person(other, scope):
                    raise QueryError(QueryMessages.VIEWER_NEEDS_A_PERSON, VIEWER)
                placed.add(id(side))

    Compare()(select)

    for node in _column_refs(select):
        if _is_viewer(node) and id(node) not in placed:
            raise QueryError(QueryMessages.VIEWER_NEEDS_A_PERSON, VIEWER)


def _resolve_viewer(select: ast.SelectStmt) -> bool:
    """Write the reader in wherever the statement said ``me``.

    Answers whether it said so anywhere, for the caller that has to know.
    """
    named = False

    class Expand(Visitor):
        def visit_ColumnRef(self, ancestors: Any, node: ast.ColumnRef) -> Any:
            nonlocal named
            if _name_parts(node.fields) == [VIEWER]:
                named = True
                return _viewer_node()
            return None

    Expand()(select)
    return named


def _constants_in(node: Any) -> set[int]:
    """Every constant anywhere under *node*."""
    found: set[int] = set()

    class Collect(Visitor):
        def visit_A_Const(self, ancestors: Any, inner: ast.A_Const) -> None:
            found.add(id(inner))

    if node is not None:
        Collect()(node)
    return found


def _grouped_expressions(select: ast.SelectStmt) -> tuple[set[int], set[str]]:
    """Constants inside what a statement groups or orders by, and how those
    expressions are written.

    ``GROUP BY`` finds its output column by matching the expression, so the two
    copies of one have to be written the same way. A parameter is numbered by
    where it is met, and the two copies are met in different places — so a
    constant under either clause stays the constant it was, and so does its
    twin in the select list.
    """
    marked: set[int] = set()
    written: set[str] = set()
    stream = RawStream()
    for entry in select.groupClause or ():
        if isinstance(entry, ast.A_Const):
            continue
        marked |= _constants_in(entry)
        written.add(stream(entry))
    for entry in select.sortClause or ():
        node = entry.node if isinstance(entry, ast.SortBy) else entry
        if node is None or isinstance(node, ast.A_Const):
            continue
        marked |= _constants_in(node)
        written.add(stream(node))
    return marked, written


def _function_arguments(node: Any) -> set[int]:
    """Constants handed straight to a function.

    An argument takes its type from the parameter it fills, and several of the
    functions this surface admits have none to give: ``concat`` and ``count``
    take ``"any"``, ``sum`` and ``avg`` are spelled once per numeric type, and
    ``EXTRACT`` names its field in the grammar rather than passing it. A
    parameter in any of those places is one Postgres will not plan, so a
    constant filling one stays the constant the reader wrote.
    """
    found: set[int] = set()

    class Collect(Visitor):
        def visit_FuncCall(self, ancestors: Any, call: ast.FuncCall) -> None:
            found.update(
                id(argument)
                for argument in call.args or ()
                if isinstance(argument, ast.A_Const)
            )

    if node is not None:
        Collect()(node)
    return found


def _cast_arguments(node: Any) -> set[int]:
    """Constants a cast is there to give a type to.

    ``CAST('30 days' AS interval)`` says what the constant *is*, so binding it
    as a parameter hands the driver a string where the type it just declared
    expects something else — an interval wants a ``timedelta``, and the bind
    fails at execution. Nothing catches it earlier: preparing the statement
    plans fine, and only running it binds anything, so the surface accepted a
    statement it could never answer.

    Writing the constant through, as the reader wrote it, is what the cast was
    asking for.
    """
    found: set[int] = set()

    class Collect(Visitor):
        def visit_TypeCast(self, ancestors: Any, cast: ast.TypeCast) -> None:
            if isinstance(cast.arg, ast.A_Const):
                found.add(id(cast.arg))

    if node is not None:
        Collect()(node)
    return found


def _window_constants(node: Any) -> set[int]:
    """Constants inside a window's definition.

    A frame's offset takes its type from the ordering it counts along, an
    interval beside a date, which a parameter is not told. And an ordering
    inside the window is the same expression as its twin in ``GROUP BY``,
    whose constants stay as they were written.
    """
    found: set[int] = set()

    class Collect(Visitor):
        def visit_WindowDef(self, ancestors: Any, window: ast.WindowDef) -> None:
            found.update(_constants_in(window))

    if node is not None:
        Collect()(node)
    return found


def _literal_positions(select: ast.SelectStmt) -> set[int]:
    """Constants that stay constants.

    Four kinds. ``GROUP BY 1`` and ``ORDER BY 1`` select an output column, and
    a parameter there would be the number one. A constant standing alone in the
    select list has nothing to take a type from — Postgres reads an unadorned
    parameter there as text — where the same constant compared against a column
    takes that column's type, which is what makes ``priority = $1`` work
    against an enum. And a constant inside a grouped or ordered expression is
    part of how that expression is written, which is what the output column is
    found by. A constant filling a function's argument stays one, because not
    every function can say what type it takes. A constant a cast names the
    type of stays one — the cast is the type, and a parameter there is bound
    as the wrong thing. And last, every constant inside a window's definition
    (:func:`_window_constants`), and inside an output ``GROUP BY`` names by
    its position, which a window may repeat.
    """
    marked, grouped = _grouped_expressions(select)
    marked |= _function_arguments(select)
    marked |= _cast_arguments(select)
    marked |= _window_constants(select)
    targets = list(select.targetList or ())
    for entry in select.groupClause or ():
        if isinstance(entry, ast.A_Const):
            marked.add(id(entry))
            # ``GROUP BY 1`` groups the whole expression it names, and a window
            # may repeat that expression, so it is written as the window writes it.
            position = getattr(entry.val, "ival", None)
            if isinstance(position, int) and 0 < position <= len(targets):
                named = targets[position - 1]
                if isinstance(named, ast.ResTarget):
                    marked |= _constants_in(named.val)
    for entry in select.sortClause or ():
        if isinstance(entry, ast.SortBy) and isinstance(entry.node, ast.A_Const):
            marked.add(id(entry.node))
    stream = RawStream()
    for target in select.targetList or ():
        if not isinstance(target, ast.ResTarget):
            continue
        if isinstance(target.val, ast.A_Const):
            marked.add(id(target.val))
        elif target.val is not None and stream(target.val) in grouped:
            marked |= _constants_in(target.val)
    return marked


def _bind_literals(select: ast.SelectStmt, written: set[int]) -> tuple[Any, ...]:
    ordinals = _literal_positions(select) | written
    values: list[Any] = []

    class Bind(Visitor):
        def visit_A_Const(self, ancestors: Any, node: ast.A_Const) -> Any:
            if id(node) in ordinals or node.isnull:
                return None
            values.append(_value(node))
            return ast.ParamRef(number=len(values))

    Bind()(select)
    return tuple(values)


def _value(node: ast.A_Const) -> Any:
    held = node.val
    if isinstance(held, ast.Integer):
        return held.ival
    if isinstance(held, ast.Float):
        return float(held.fval)
    if isinstance(held, ast.Boolean):
        return held.boolval
    if isinstance(held, ast.String):
        return held.sval
    raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, type(held).__name__)


def resolve(
    sql: str, read: Mapping[SheetCall | PluginCall, Recordset] | None = None
) -> ResolvedQuery:
    """Read *sql*, and return the statement this surface will run instead.

    *read* holds what each ``sheet()`` and ``plugin()`` call read. A call it
    does not hold is left unread: its columns are taken on trust and the
    statement is checked but not runnable (:attr:`ResolvedQuery.unread`).

    Raises :class:`QueryError` naming what has to change.
    """
    select = _parse(sql)
    calls = _take_calls(select)
    recordsets = {key: _read_by(read, call) for key, (_, call) in calls.items()}
    _check_nodes(select)
    _expand_relations(select)
    scope = _relations(select, recordsets)
    column_types = _output_types(select, scope)
    column_grains = _output_grains(select)
    _check_viewer(select, scope)
    written = _resolve_columns(select, scope)
    parameters = list(_bind_literals(select, written))
    names_the_reader = _resolve_viewer(select)
    # A read recordset is its rows, bound as one parameter and read as a
    # recordset of ``c1``, ``c2``, … typed as its columns. An empty one is one
    # column and no rows.
    swaps: dict[int, ast.Node] = {}
    for key, recordset in recordsets.items():
        if not recordset.read:
            continue
        parameters.append(
            json.dumps(
                [
                    {f"c{index}": value for index, value in enumerate(row, start=1)}
                    for row in recordset.rows
                ]
            )
        )
        columns = ", ".join(
            f"c{index} {postgres}"
            for index, postgres in enumerate(recordset.types or ("text",), start=1)
        )
        bound = parse_sql(
            f"SELECT FROM pg_catalog.json_to_recordset(${len(parameters)}) "
            f"AS h({columns})"
        )[0].stmt.fromClause[0]
        bound.alias.aliasname = calls[key][0]
        swaps[key] = bound
    if swaps:
        select.fromClause = tuple(
            _swap(node, swaps) for node in select.fromClause or ()
        )
    named = [(calls[key][0], recordset) for key, recordset in recordsets.items()]
    return ResolvedQuery(
        sql=RawStream()(select),
        parameters=tuple(parameters),
        relations=tuple(sorted({source.name for source in scope.values()})),
        column_types=column_types,
        column_grains=column_grains,
        names_the_reader=names_the_reader,
        sheets=tuple(entry for entry in named if isinstance(entry[1], Sheet)),
        plugins=tuple(entry for entry in named if isinstance(entry[1], PluginRows)),
        source=sql if any(not entry.read for entry in recordsets.values()) else "",
    )


def _read_by(
    read: Mapping[SheetCall | PluginCall, Recordset] | None,
    call: SheetCall | PluginCall,
) -> Recordset:
    """What *call* read, or the call unread."""
    found = (read or {}).get(call)
    if found is not None:
        return found
    return (
        Sheet.unread(call) if isinstance(call, SheetCall) else PluginRows.unread(call)
    )


def remap_ids(sql: str, remap: Callable[[SearchEntityType, int], int]) -> str:
    """*sql*, with each row id it names as a constant put through *remap*.

    A constant names a row where it is compared with ``=``, ``<>`` or ``IN`` to
    a column that is a table's own id or a key into one, and where it is the
    file ``sheet()`` reads; the row is of the kind that table holds
    (:data:`~app.db.search_index.SEARCH_SOURCES`), so a person, who is not one,
    is left alone. Each constant is replaced where it is written, so the rest
    of the text, comments included, stays as it was. A statement that does not
    resolve, and a constant written in a shape this does not read (a cast, a
    comparison with the constant first), come back unchanged.
    """
    from app.db.search_index import SEARCH_SOURCES

    numbers = [token for token in scan(sql) if token.name == "ICONST"]
    # Where each constant to replace starts, its kind, and its value: found by
    # what it is written after, since a parsed constant keeps no position.
    found: list[tuple[int, SearchEntityType, int]] = []

    def after(location: Any, values: Sequence[Any], kind: SearchEntityType) -> None:
        if not isinstance(location, int):
            # A join the resolver wrote in, which nobody typed.
            return
        # Each integer a value holds is written as one number token, in order,
        # so a value takes as many tokens as it holds integers, and only a
        # value that is one integer names a row.
        tokens = iter([token for token in numbers if token.start > location])
        for value in values:
            held = 0

            class Count(Visitor):
                def visit_A_Const(self, ancestors: Any, constant: ast.A_Const) -> None:
                    nonlocal held
                    held += isinstance(constant.val, ast.Integer)

            Count()(value)
            taken = list(islice(tokens, held))
            if (
                isinstance(value, ast.A_Const)
                and isinstance(value.val, ast.Integer)
                and len(taken) == 1
                and sql[taken[0].start : taken[0].end + 1] == str(value.val.ival)
            ):
                found.append((taken[0].start, kind, value.val.ival))

    class Sheets(Visitor):
        def visit_FuncCall(self, ancestors: Any, call: ast.FuncCall) -> None:
            if _name_parts(call.funcname) == [SHEET] and call.args:
                after(call.location, call.args[:1], SearchEntityType.file)

    try:
        select = _parse(sql)
        Sheets()(select)
        recordsets = {
            key: _read_by(None, call) for key, (_, call) in _take_calls(select).items()
        }
        _expand_relations(select)
        scope = _relations(select, recordsets)
    except QueryError:
        return sql

    class Ids(Visitor):
        def visit_A_Expr(self, ancestors: Any, node: ast.A_Expr) -> None:
            if node.kind == A_Expr_Kind.AEXPR_IN:
                values = tuple(node.rexpr or ())
            elif _name_parts(node.name) in (["="], ["<>"]):
                values = (node.rexpr,)
            else:
                return
            spec = _field_named(scope, node.lexpr)
            try:
                column = spec.column.property.columns[0]
            except AttributeError:
                return
            tables = (
                [column.table.name]
                if column.primary_key
                else [key.column.table.name for key in column.foreign_keys]
            )
            source = SEARCH_SOURCES.get(tables[0]) if len(tables) == 1 else None
            if source is not None:
                after(node.lexpr.location, values, source.entity_type)

    Ids()(select)
    for start, kind, value in sorted(found, key=lambda entry: entry[0], reverse=True):
        sql = f"{sql[:start]}{remap(kind, value)}{sql[start + len(str(value)) :]}"
    return sql
