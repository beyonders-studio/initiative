"""Turn a structured description of a query into SQL.

The builder in the browser does not write SQL. It describes what somebody
clicked — a dataset, some columns, a filter, a grouping — and this writes the
statement, by building the parse tree and handing it to the same deparser that
writes every other statement this surface produces.

That is the whole reason it lives here rather than in the client. A statement a
person built by clicking must be one the validator accepts, and the two ways to
get that wrong are quoting and spelling: a name or a literal written into SQL by
hand has to be escaped exactly the way Postgres reads it, and a clause has to be
spelled the way the grammar expects. Building the tree settles both — there is
no string to escape, and a node that would not parse cannot be constructed.

The cutover migration writes its statements through the same functions, so the
SQL a stored definition was rewritten to and the SQL the builder produces are
the same SQL.

A description reads one of the registry's datasets, a range of a spreadsheet
(``sheet(file, range)``), or one of a plug-in's read endpoints
(``plugin(public id, endpoint, name => value, …)``). Their columns are what the
file holds and what the endpoint declares, so they are not checked here: the
description of the statement that follows refuses a column they do not have.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Union

from pglast import ast, parse_sql
from pglast.enums import A_Expr_Kind, BoolExprType, LimitOption, SortByDir
from pglast.enums.parsenodes import (
    FRAMEOPTION_END_CURRENT_ROW,
    FRAMEOPTION_RANGE,
    FRAMEOPTION_START_UNBOUNDED_PRECEDING,
)
from pglast.stream import RawStream

from app.core.messages import QueryMessages
from app.schemas.query import FilterOp
from app.services.fields import dataset
from app.services.fields.registry import dataset_names
from app.services.fields.spec import ControlKind
from app.services.query.resolve import (
    PLUGIN,
    SHEET,
    VIEWER,
    PluginCall,
    QueryError,
    SheetCall,
)

#: What a column may be reduced to. Aggregates only — a window function is a
#: different question and the validator does not admit one.
AGGREGATES = frozenset({"count", "sum", "avg", "min", "max"})

#: What a column may be added up as it goes: a running count, a running total.
RUNNING = frozenset({"count", "sum"})

#: Everything up to and including this row: Postgres's own default frame,
#: spelled out because a window written in the tree carries its frame.
_UP_TO_HERE = (
    FRAMEOPTION_RANGE
    | FRAMEOPTION_START_UNBOUNDED_PRECEDING
    | FRAMEOPTION_END_CURRENT_ROW
)

#: What a date column may be rounded to. The vocabulary ``date_trunc`` takes,
#: narrowed to the buckets a tile is drawn at.
BUCKETS = frozenset({"day", "week", "month", "quarter", "year"})

#: How each operator is spelled in the tree.
_OPERATORS = {
    FilterOp.eq: "=",
    FilterOp.lt: "<",
    FilterOp.lte: "<=",
    FilterOp.gt: ">",
    FilterOp.gte: ">=",
    FilterOp.ilike: "~~*",
}


@dataclass(frozen=True)
class Column:
    """One thing the query returns."""

    field: str
    #: Reduce the column across the group, rather than returning it as it is.
    aggregate: Optional[str] = None
    #: Round a date down before grouping by it.
    bucket: Optional[str] = None
    #: What the output column is called. Defaults to the field's own name, or
    #: the aggregate's, so a chart's legend reads as something.
    alias: Optional[str] = None
    #: Add the aggregate up along the grouping, so each row holds everything
    #: up to it: a burn-up rather than a count per week.
    running: bool = False


@dataclass(frozen=True)
class Condition:
    """One comparison, in the same vocabulary the filter DSL uses."""

    field: str
    op: FilterOp = FilterOp.eq
    value: Any = None
    #: The same comparison, answered the other way.
    negate: bool = False


@dataclass(frozen=True)
class Group:
    """Conditions held together by one word.

    The filter builder has always described nested groups, because "high or
    urgent, and mine" is an ordinary thing to ask and a flat list of ANDs
    cannot say it. This is that shape, so a description and a filter stay one
    vocabulary rather than two.
    """

    logic: str = "and"
    conditions: Sequence["Node"] = field(default_factory=tuple)


#: One line of a filter: a comparison, or a bracket around more of them.
Node = Union[Condition, Group]

#: The words a bracket may be held together by.
_LOGIC = {"and": BoolExprType.AND_EXPR, "or": BoolExprType.OR_EXPR}

#: How deep a description may bracket. The builder offers one level; this
#: bounds what may arrive, not what anybody clicks.
MAX_GROUP_DEPTH = 3


@dataclass(frozen=True)
class Sort:
    field: str
    descending: bool = False


@dataclass(frozen=True)
class QuerySpec:
    """What somebody clicked, before it is a statement: about one dataset, one
    range of a spreadsheet, or one of a plug-in's read endpoints."""

    dataset: Optional[str] = None
    sheet: Optional[SheetCall] = None
    plugin: Optional[PluginCall] = None
    columns: Sequence[Column] = field(default_factory=tuple)
    where: Sequence[Node] = field(default_factory=tuple)
    #: Columns to group by, named the way the select list names them.
    group_by: Sequence[str] = field(default_factory=tuple)
    order_by: Optional[Sort] = None
    limit: Optional[int] = None


def _split(name: str) -> tuple[Optional[str], str]:
    """A field name, and the relation it is read through if it names one."""
    relation, _, field_name = name.rpartition(".")
    return (relation or None), field_name


def _column_ref(
    name: str, base: Optional[str] = None, whole: bool = False
) -> ast.ColumnRef:
    """One column, qualified by the relation it belongs to where it names one.

    A related field is written ``assignee.display_name``, and reaches the tree
    as the relation's own name qualifying the column — which is the alias the
    join below gives it.

    *base* names the dataset an unqualified field belongs to, and is passed
    only when the statement joins something. A join puts two tables in scope
    and a bare column name that exists on both is then ambiguous — which is
    not hypothetical: every tool carries ``archived_at`` and ``created_at``, so
    filtering one of those alongside any related field produced a statement
    Postgres refuses. Naming the base says which side is meant. It is left off
    when nothing is joined, where there is no second side and the qualification
    would only make the stored statement longer to read.

    *whole* is for a range's column, which reaches through no relation: its
    header is its name, dots and all (``No.``).
    """
    relation, field_name = (None, name) if whole else _split(name)
    parts = (
        (relation, field_name)
        if relation
        else ((base, field_name) if base else (field_name,))
    )
    return ast.ColumnRef(fields=tuple(ast.String(sval=part) for part in parts))


def _literal(value: Any) -> ast.Node:
    """A value as a constant. Written into the tree rather than the text, so
    what it contains is the deparser's problem and not a quoting rule of ours."""
    if value is None:
        return ast.A_Const(isnull=True)
    if isinstance(value, Mapping) and "relative" in value:
        return _relative(value["relative"])
    if isinstance(value, bool):
        return ast.A_Const(val=ast.Boolean(boolval=value))
    if isinstance(value, int):
        return ast.A_Const(val=ast.Integer(ival=value))
    if isinstance(value, float):
        return ast.A_Const(val=ast.Float(fval=repr(value)))
    return ast.A_Const(val=ast.String(sval=str(value)))


def _relative(days: Any) -> ast.Node:
    """A date the reader gave as a distance, kept as one.

    A dashboard is a standing question: "due in the next 30 days" has to still
    mean that next month, so what is written is the distance, and the day it is
    counted from is read when the tile runs.
    """
    # A whole number of days and nothing else: ``int()`` would read 1.9 as one
    # day and ``True`` as one day, and a date boundary quietly one place from
    # where it was asked for is worse than a refusal.
    if not isinstance(days, int) or isinstance(days, bool):
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "relative")
    offset = days
    return ast.A_Expr(
        kind=A_Expr_Kind.AEXPR_OP,
        name=(ast.String(sval="+" if offset >= 0 else "-"),),
        lexpr=ast.FuncCall(funcname=(ast.String(sval="now"),), args=()),
        rexpr=ast.TypeCast(
            arg=ast.A_Const(val=ast.String(sval=f"{abs(offset)} days")),
            typeName=ast.TypeName(names=(ast.String(sval="interval"),)),
        ),
    )


def _expression(
    column: Column, base: Optional[str] = None, whole: bool = False
) -> ast.Node:
    """The select-list expression for one column, innermost first: the field,
    rounded if it is bucketed, reduced if it is aggregated."""
    inner: ast.Node = _column_ref(column.field, base, whole)
    if column.bucket:
        if column.bucket not in BUCKETS:
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, column.bucket)
        inner = ast.FuncCall(
            funcname=(ast.String(sval="date_trunc"),),
            args=(ast.A_Const(val=ast.String(sval=column.bucket)), inner),
        )
    if column.aggregate:
        if column.aggregate not in AGGREGATES:
            raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, column.aggregate)
        # count with nothing to count is count(*), which is the one aggregate
        # that takes no argument.
        if column.aggregate == "count" and column.field == "*":
            return ast.FuncCall(funcname=(ast.String(sval="count"),), agg_star=True)
        inner = ast.FuncCall(
            funcname=(ast.String(sval=column.aggregate),), args=(inner,)
        )
    return inner


def _alias(column: Column) -> str:
    if column.alias:
        return column.alias
    if column.aggregate and column.field == "*":
        name = column.aggregate
    elif column.aggregate:
        name = f"{column.field}_{column.aggregate}"
    else:
        return column.field
    return f"running_{name}" if column.running else name


def _running(reduced: ast.Node, keys: Sequence[ast.Node], name: str) -> ast.FuncCall:
    """*reduced*, added up along the grouping.

    Ordered by the first grouped column and restarted for each value of the
    rest, which is how a chart reads them: the first is the axis and the next
    splits the series, so each series climbs on its own.
    """
    if not keys:
        # One row has nothing to add up along.
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, name)
    return ast.FuncCall(
        funcname=(ast.String(sval="sum"),),
        args=(reduced,),
        over=ast.WindowDef(
            partitionClause=tuple(keys[1:]) or None,
            orderClause=(ast.SortBy(node=keys[0], sortby_dir=SortByDir.SORTBY_ASC),),
            frameOptions=_UP_TO_HERE,
        ),
    )


def _viewer_value(dataset_name: str, condition: Condition) -> bool:
    """Whether this condition is somebody picking themselves.

    Only against a field that holds a person: everywhere else ``"me"`` is the
    two-letter word, and a title is allowed to be it.
    """
    if not _names_a_person(dataset_name, condition.field):
        return False
    values = (
        condition.value
        if isinstance(condition.value, (list, tuple))
        else [condition.value]
    )
    return any(value == VIEWER for value in values)


def _names_a_person(dataset_name: str, field_name: str) -> bool:
    if dataset_name in (SHEET, PLUGIN):
        return False
    relation_name, plain = _split(field_name)
    holder = dataset_name
    if relation_name is not None:
        relation = dataset(dataset_name).by_relation.get(relation_name)
        if relation is None:
            return False
        holder = relation.dataset
    spec = dataset(holder).by_name.get(plain)
    return spec is not None and spec.kind is ControlKind.member


def _value_node(is_viewer: bool, value: Any) -> ast.Node:
    """One value on the right of a comparison: the reader, or a constant."""
    if is_viewer and value == VIEWER:
        return ast.ColumnRef(fields=(ast.String(sval=VIEWER),))
    return _literal(value)


def _predicate(
    dataset_name: str, condition: Condition, base: Optional[str] = None
) -> ast.Node:
    viewer = _viewer_value(dataset_name, condition)
    left = _column_ref(condition.field, base, whole=dataset_name in (SHEET, PLUGIN))
    if condition.op is FilterOp.is_null:
        # The DSL's is_null carries whether it means null or not-null.
        return ast.NullTest(arg=left, nulltesttype=0 if condition.value else 1)
    if condition.op is FilterOp.in_:
        values = (
            condition.value
            if isinstance(condition.value, (list, tuple))
            else [condition.value]
        )
        return ast.A_Expr(
            kind=A_Expr_Kind.AEXPR_IN,
            name=(ast.String(sval="="),),
            lexpr=left,
            rexpr=tuple(_value_node(viewer, value) for value in values),
        )
    operator = _OPERATORS.get(condition.op)
    if operator is None:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, str(condition.op))
    return ast.A_Expr(
        kind=A_Expr_Kind.AEXPR_OP,
        name=(ast.String(sval=operator),),
        lexpr=left,
        rexpr=_value_node(viewer, condition.value),
    )


def _where(
    dataset_name: str,
    nodes: Sequence[Node],
    depth: int = 0,
    base: Optional[str] = None,
) -> Optional[ast.Node]:
    """Everything the description asks of a row.

    A list is AND-ed, which is what a reader means by writing two lines. A
    group says its own word instead, over a list of its own.
    """
    predicates = tuple(
        held
        for node in nodes
        for held in (_node(dataset_name, node, depth, base),)
        if held is not None
    )
    if not predicates:
        return None
    if len(predicates) == 1:
        return predicates[0]
    return ast.BoolExpr(boolop=BoolExprType.AND_EXPR, args=predicates)


def _node(
    dataset_name: str, node: Node, depth: int, base: Optional[str] = None
) -> Optional[ast.Node]:
    if depth > MAX_GROUP_DEPTH:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "group depth")
    if isinstance(node, Group):
        if node.logic not in _LOGIC:
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, str(node.logic))
        inner = tuple(
            held
            for entry in node.conditions
            for held in (_node(dataset_name, entry, depth + 1, base),)
            if held is not None
        )
        if not inner:
            # A bracket somebody opened and did not fill asks nothing, which is
            # better than refusing to save what they were part way through.
            return None
        if len(inner) == 1:
            return inner[0]
        return ast.BoolExpr(boolop=_LOGIC[node.logic], args=inner)
    predicate = _predicate(dataset_name, node, base)
    if node.negate:
        return ast.BoolExpr(boolop=BoolExprType.NOT_EXPR, args=(predicate,))
    return predicate


def _check_field(name: str, field_name: str) -> None:
    """That a field exists, on this dataset or on one it declares a way to.

    A dotted name is read through the relation it prefixes, so a name that is
    not a field of what that relation reaches is refused here rather than
    becoming a statement the validator would refuse afterwards.
    """
    relation_name, plain = _split(field_name)
    if relation_name is None:
        if plain not in dataset(name).by_name:
            raise QueryError(QueryMessages.UNKNOWN_FIELD, f"{name}.{plain}")
        return
    relation = dataset(name).by_relation.get(relation_name)
    if relation is None:
        raise QueryError(QueryMessages.UNKNOWN_RELATION, f"{name}.{relation_name}")
    if plain not in dataset(relation.dataset).by_name:
        raise QueryError(QueryMessages.UNKNOWN_FIELD, f"{relation_name}.{plain}")


def _check_depth(nodes: Sequence[Node]) -> None:
    """That a description does not bracket deeper than it may.

    Walked with a stack of its own rather than by recursion, and before
    anything else reads the description — so the bound below is what stops a
    deep one, rather than whichever traversal happens to reach it first.
    """
    pending = [(node, 0) for node in nodes]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_GROUP_DEPTH:
            raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "group depth")
        if isinstance(node, Group):
            pending.extend((entry, depth + 1) for entry in node.conditions)


def _leaves(nodes: Sequence[Node]) -> list[Condition]:
    """Every comparison a description holds, however it is bracketed."""
    found: list[Condition] = []
    for node in nodes:
        if isinstance(node, Group):
            found.extend(_leaves(node.conditions))
        else:
            found.append(node)
    return found


def _relations_named(spec: QuerySpec) -> list[str]:
    """The relations this description reads through, in the order first met."""
    if spec.dataset is None:
        return []
    named: list[str] = []
    for name in (
        [column.field for column in spec.columns]
        + [condition.field for condition in _leaves(spec.where)]
        + ([spec.order_by.field] if spec.order_by else [])
        + list(spec.group_by)
    ):
        relation, _ = _split(name)
        if relation and relation not in named:
            named.append(relation)
    return named


def _from(spec: QuerySpec, relations: Sequence[str]) -> ast.Node:
    """The dataset, joined to everything the description reached through.

    Each hop is written as an ordinary inner join with a condition relating the
    two sides, which is what the validator asks of a join — so a statement the
    builder produces is checked the same way as one somebody wrote.

    The last hop of a relation is aliased to the relation's own name, so a
    reader's ``assignee.display_name`` is what the statement says.
    """
    if spec.sheet is not None:
        reading = parse_sql(f"SELECT FROM {SHEET}()")[0].stmt.fromClause[0]
        reading.functions[0][0].args = tuple(
            _literal(value)
            for value in (spec.sheet.file, spec.sheet.range)
            if value is not None
        )
        return reading
    if spec.plugin is not None:
        reading = parse_sql(f"SELECT FROM {PLUGIN}()")[0].stmt.fromClause[0]
        reading.functions[0][0].args = (
            _literal(spec.plugin.plugin),
            _literal(spec.plugin.endpoint),
            *(
                ast.NamedArgExpr(
                    name=name,
                    arg=ast.A_ArrayExpr(elements=tuple(map(_literal, value)))
                    if isinstance(value, tuple)
                    else _literal(value),
                    argnumber=-1,
                )
                for name, value in spec.plugin.params
            ),
        )
        return reading
    declared = dataset(spec.dataset).by_relation
    node: ast.Node = ast.RangeVar(relname=spec.dataset, inh=True)
    for name in relations:
        relation = declared.get(name)
        if relation is None:
            raise QueryError(QueryMessages.UNKNOWN_RELATION, f"{spec.dataset}.{name}")
        left_handle = spec.dataset
        for index, hop in enumerate(relation.hops):
            last = index == len(relation.hops) - 1
            handle = name if last else f"{name}__{hop.dataset}"
            node = ast.JoinExpr(
                jointype=0,
                larg=node,
                rarg=ast.RangeVar(
                    relname=hop.dataset,
                    inh=True,
                    alias=ast.Alias(aliasname=handle),
                ),
                quals=ast.A_Expr(
                    kind=A_Expr_Kind.AEXPR_OP,
                    name=(ast.String(sval="="),),
                    lexpr=ast.ColumnRef(
                        fields=(
                            ast.String(sval=left_handle),
                            ast.String(sval=hop.left),
                        )
                    ),
                    rexpr=ast.ColumnRef(
                        fields=(ast.String(sval=handle), ast.String(sval=hop.right))
                    ),
                ),
            )
            left_handle = handle
    return node


def build(spec: QuerySpec) -> str:
    """The statement *spec* describes.

    Written in the registry's own vocabulary — the dataset and field names a
    reader sees — so what is stored is what they built, and resolution to
    physical names happens when it runs, like any other statement.
    """
    if sum(read is not None for read in (spec.dataset, spec.sheet, spec.plugin)) != 1:
        raise QueryError(QueryMessages.MISSING_RELATION)
    if spec.dataset is not None and spec.dataset not in dataset_names():
        raise QueryError(QueryMessages.UNKNOWN_RELATION, spec.dataset)
    if not spec.columns:
        raise QueryError(QueryMessages.UNSUPPORTED_SYNTAX, "no columns")
    for column in spec.columns:
        if column.field != "*" and spec.dataset is not None:
            _check_field(spec.dataset, column.field)
        if column.running and column.aggregate not in RUNNING:
            raise QueryError(QueryMessages.UNSUPPORTED_FUNCTION, "running")
    _check_depth(spec.where)
    if spec.dataset is not None:
        for condition in _leaves(spec.where):
            _check_field(spec.dataset, condition.field)

    # A bare column is already named after itself, so an alias there would read
    # as "priority AS priority". Anything computed needs one, because Postgres
    # would otherwise name it after the function that made it.
    # A join puts a second table in scope, and a bare column that exists on
    # both sides is then ambiguous. Only then is the base named — a statement
    # about one table reads better without it.
    joined = bool(_relations_named(spec))
    base = spec.dataset if joined else None
    whole = spec.dataset is None

    targets = tuple(
        ast.ResTarget(
            name=None
            if column.alias is None and not column.aggregate and not column.bucket
            else _alias(column),
            val=_expression(column, base, whole),
        )
        for column in spec.columns
    )
    aliases = [
        target.name or column.field for target, column in zip(targets, spec.columns)
    ]

    select = ast.SelectStmt(
        targetList=targets,
        fromClause=(_from(spec, _relations_named(spec)),),
        whereClause=_where(
            spec.dataset or (SHEET if spec.sheet else PLUGIN), spec.where, base=base
        ),
        op=0,
    )

    # By output position, because a grouped expression and its select-list
    # twin have to be the same expression and an ordinal says so outright.
    # Every column a name matches that is not a count or a total: one date
    # rounded two ways is two columns under one name, and grouping only the
    # first leaves the other ungrouped, while an aggregate is never grouped. A
    # name only an aggregate has is grouped as it always was, and Postgres
    # refuses it.
    grouped: list[int] = []
    for name in spec.group_by:
        if name not in aliases:
            raise QueryError(QueryMessages.UNKNOWN_FIELD, name)
        plain = [
            position
            for position, (alias, column) in enumerate(
                zip(aliases, spec.columns), start=1
            )
            if alias == name and not column.aggregate
        ]
        grouped += [
            position
            for position in plain or [aliases.index(name) + 1]
            if position not in grouped
        ]
    if grouped:
        select.groupClause = tuple(
            ast.A_Const(val=ast.Integer(ival=position)) for position in grouped
        )

    for target, column in zip(targets, spec.columns):
        if column.running:
            # Each window gets expressions of its own: a node is not shared
            # between two places in a tree.
            keys = [
                _expression(spec.columns[position - 1], base, whole)
                for position in grouped
                if not spec.columns[position - 1].aggregate
            ]
            target.val = _running(target.val, keys, target.name or "running")

    if spec.order_by is None and grouped:
        # Rows in the order of what they are grouped by, so a time series
        # reads left to right instead of in whatever order the groups were
        # gathered. Ordinal for the same reason as the grouping.
        select.sortClause = tuple(
            ast.SortBy(
                node=ast.A_Const(val=ast.Integer(ival=position)),
                sortby_dir=SortByDir.SORTBY_ASC,
            )
            for position in grouped
        )

    if spec.order_by is not None:
        if spec.order_by.field not in aliases:
            raise QueryError(QueryMessages.UNKNOWN_FIELD, spec.order_by.field)
        select.sortClause = (
            ast.SortBy(
                node=ast.A_Const(
                    val=ast.Integer(ival=aliases.index(spec.order_by.field) + 1)
                ),
                sortby_dir=SortByDir.SORTBY_DESC
                if spec.order_by.descending
                else SortByDir.SORTBY_ASC,
            ),
        )

    if spec.limit is not None:
        select.limitCount = ast.A_Const(val=ast.Integer(ival=int(spec.limit)))
        select.limitOption = LimitOption.LIMIT_OPTION_COUNT

    return RawStream()(select)
