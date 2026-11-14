"""A dashboard's query widgets, compiled into one statement.

A canvas asks many questions of the same few datasets. Asked one at a time,
every widget scans those tables and answers their policies for every row
again. Compiled, each dataset two or more widgets read is read **once**, into
a materialized CTE that carries the same name as the table, and every widget
runs over those rows:

.. code-block:: sql

    WITH tasks AS MATERIALIZED (SELECT id, title, … FROM tasks)
    SELECT (SELECT json_agg(ROW(q.*)) FROM (SELECT * FROM (<widget>) AS w
            LIMIT 5001) AS q) AS w0,
           …

The widget statements are placed as the resolver wrote them. A non-recursive
CTE's name is not visible inside its own body, so the body reads the table
while every widget beside it reads the CTE. A dataset only one widget reads is
left alone, so that widget keeps the table's indexes.

The inputs are :class:`~app.services.query.resolve.ResolvedQuery` values:
statements the resolver has already admitted and written out from its own tree.
Nothing here reads a reader's text.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any

from pglast import ast, parse_sql
from pglast.stream import RawStream
from pglast.visitors import Visitor

from app.services.fields import dataset
from app.services.fields.registry import dataset_names
from app.services.query.resolve import ResolvedQuery


@dataclass(frozen=True)
class CompiledCanvas:
    """One statement answering every widget, one output column each."""

    sql: str
    parameters: tuple[Any, ...]
    #: The tables read once and shared, for a caller that wants to say so.
    shared: tuple[str, ...]


@cache
def _table_columns() -> dict[str, frozenset[str]]:
    """Every dataset's table, and the columns it has."""
    columns: dict[str, set[str]] = {}
    for name in dataset_names():
        table = dataset(name).model.__table__
        columns.setdefault(table.name, set()).update(c.name for c in table.columns)
    return {table: frozenset(names) for table, names in columns.items()}


def _parsed(sql: str) -> ast.SelectStmt:
    root = parse_sql(sql)[0].stmt
    if not isinstance(root, ast.SelectStmt):
        raise TypeError("a resolved statement is always a SELECT")
    return root


class _Nodes(Visitor):
    """Collects the nodes a pass over one statement needs."""

    def __init__(self) -> None:
        self.ranges: list[ast.RangeVar] = []
        self.columns: list[ast.ColumnRef] = []
        self.params: list[ast.ParamRef] = []

    def visit_RangeVar(self, _ancestors: Any, node: ast.RangeVar) -> None:
        self.ranges.append(node)

    def visit_ColumnRef(self, _ancestors: Any, node: ast.ColumnRef) -> None:
        self.columns.append(node)

    def visit_ParamRef(self, _ancestors: Any, node: ast.ParamRef) -> None:
        self.params.append(node)


def _words(node: ast.ColumnRef) -> list[str]:
    return [part.sval for part in node.fields or () if isinstance(part, ast.String)]


def _columns_read(select: ast.SelectStmt, nodes: _Nodes) -> dict[str, set[str]]:
    """Which columns of which tables a statement reads.

    A qualified column belongs to the relation its qualifier names. An
    unqualified one could be any relation in the statement that has it, so it
    counts for each — reading a column too many is harmless, one too few is an
    error. A name that is no table's column (an output alias an ``ORDER BY``
    names) belongs to nothing.
    """
    tables = _table_columns()
    handles: dict[str, str] = {}
    for node in nodes.ranges:
        if node.relname is None:
            continue
        handle = node.alias.aliasname if node.alias else None
        handles[handle or node.relname] = node.relname
    read: dict[str, set[str]] = {table: set() for table in handles.values()}
    for node in nodes.columns:
        words = _words(node)
        if len(words) == 2 and words[0] in handles:
            table = handles[words[0]]
            if words[1] in tables.get(table, ()):
                read[table].add(words[1])
        elif len(words) == 1:
            for table, names in read.items():
                if words[0] in tables.get(table, ()):
                    names.add(words[0])
    return read


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def compile_canvas(
    statements: Sequence[ResolvedQuery], *, row_limit: int
) -> CompiledCanvas:
    """One statement whose column ``w<i>`` holds statement *i*'s rows.

    Each column is a JSON array with one object per row, keyed ``f1``, ``f2``,
    … by position, because a statement may name two columns the same thing.
    At most ``row_limit`` rows come back per widget, so a caller asking for one
    more than it returns can tell whether it truncated.
    """
    readers: Counter[str] = Counter()
    wanted: dict[str, set[str]] = {}
    written: list[str] = []
    parameters: list[Any] = []

    for statement in statements:
        select = _parsed(statement.sql)
        nodes = _Nodes()
        nodes(select)
        for table, columns in _columns_read(select, nodes).items():
            readers[table] += 1
            wanted.setdefault(table, set()).update(columns)
        offset = len(parameters)
        for param in nodes.params:
            param.number += offset
        parameters.extend(statement.parameters)
        written.append(RawStream()(select))

    shared = sorted(table for table, count in readers.items() if count > 1)
    ctes = []
    for table in shared:
        # ``id`` keeps the list non-empty for a table read only by counts.
        columns = sorted(wanted[table] | ({"id"} & _table_columns().get(table, set())))
        listed = ", ".join(_quoted(column) for column in columns)
        ctes.append(
            f"{_quoted(table)} AS MATERIALIZED (SELECT {listed} FROM {_quoted(table)})"
        )

    outputs = [
        f"(SELECT json_agg(ROW(q.*)) FROM (SELECT * FROM ({sql}) AS w "
        f"LIMIT {int(row_limit)}) AS q) AS w{index}"
        for index, sql in enumerate(written)
    ]
    head = f"WITH {', '.join(ctes)} " if ctes else ""
    return CompiledCanvas(
        sql=f"{head}SELECT {', '.join(outputs)}",
        parameters=tuple(parameters),
        shared=tuple(shared),
    )
