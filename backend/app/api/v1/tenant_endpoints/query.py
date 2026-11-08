"""Run a reader's own SQL against their guild's data.

Guild-scoped, and gated by nothing more than reaching it: the dependency that
admits the request decides who the reader is, and the query then runs under
exactly the context that dependency established — same identity, same guild,
same grant if there is one. A query therefore returns what its author reaches
through any other part of the app, which is why membership is the whole of the
permission question here.

A statement names datasets rather than a scope, so a caller that belongs to
one initiative sends its id and the rows come back narrowed to it. That only
ever removes rows — the reader still reaches exactly what they reach elsewhere —
and it is what lets an initiative's dashboard ask a guild-scoped question.

What the statement may say, and what running it may cost, are answered in
:mod:`app.services.query`.
"""

from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import GuildContext, RLSSessionDep, get_guild_membership
from app.db.session import routed_context
from app.schemas.field_catalog import FieldDescription
from app.schemas.sql_query import (
    QueryBuildRequest,
    QueryBuildResponse,
    QueryColumnDescription,
    QueryFilterGroupSpec,
    QueryFilterNode,
    QueryPluginDescription,
    QueryRequest,
    QueryResponse,
    QueryShapeResponse,
    QuerySheetDescription,
)
from app.services import fields as fields_registry
from app.services import query as query_service
from app.services.query import build as query_builder
from app.services.query import plugins as query_plugins
from app.services.query.resolve import PluginCall, SheetCall

router = APIRouter()


@router.post("/query/describe", response_model=QueryShapeResponse)
async def describe_query(
    payload: QueryRequest,
    session: RLSSessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> QueryShapeResponse:
    """Say what one statement would return, without running it.

    Costs a plan and no rows, so a builder may ask as often as it likes: a
    plug-in it reads is described from its declaration, not called.
    """
    columns, statement = await query_service.describe(
        await query_plugins.with_rows(session, payload.sql, fetch=False),
        context=routed_context(session),
        initiative_id=payload.initiative_id,
    )
    return QueryShapeResponse(
        columns=_described(columns),
        relations=list(statement.relations),
        sheets=_sheets(statement),
        plugins=_plugins(statement),
    )


def _sheets(statement: query_service.ResolvedQuery) -> list[QuerySheetDescription]:
    """The ranges a statement read, as both endpoints describe them."""
    return [
        QuerySheetDescription(
            alias=alias,
            sheets=list(sheet.sheet_names),
            fields=[
                FieldDescription(**entry) for entry in fields_registry.describe(sheet)
            ],
        )
        for alias, sheet in statement.sheets
    ]


def _plugins(statement: query_service.ResolvedQuery) -> list[QueryPluginDescription]:
    """The plug-in endpoints a statement read, as both endpoints describe them."""
    return [
        QueryPluginDescription(
            alias=alias,
            fields=[
                FieldDescription(**entry) for entry in fields_registry.describe(rows)
            ],
        )
        for alias, rows in statement.plugins
    ]


def _described(
    columns: Iterable[query_service.QueryColumn],
) -> list[QueryColumnDescription]:
    """The executor's columns on the wire. Both endpoints answer with them."""
    return [
        QueryColumnDescription(
            name=column.name,
            type=column.type,
            grain=column.grain,
            date_only=column.date_only,
        )
        for column in columns
    ]


@router.post("/query", response_model=QueryResponse)
async def run_query(
    payload: QueryRequest,
    session: RLSSessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> QueryResponse:
    """Read one statement and return its rows."""
    result = await query_service.execute(
        await query_plugins.with_rows(session, payload.sql),
        context=routed_context(session),
        initiative_id=payload.initiative_id,
    )
    return QueryResponse(
        columns=_described(result.columns),
        rows=[list(row) for row in result.rows],
        truncated=result.truncated,
        relations=list(result.relations),
    )


@router.post("/query/build", response_model=QueryBuildResponse)
async def build_query(
    payload: QueryBuildRequest,
    session: RLSSessionDep,
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> QueryBuildResponse:
    """Write the statement a builder described, and say what it would return.

    Two answers in one call because the builder needs both on every edit: the
    SQL to store, and the columns to offer its slot pickers. Describing costs a
    plan and no rows, so asking on each click is affordable.
    """
    sql = query_builder.build(_spec(payload))
    columns, statement = await query_service.describe(
        await query_plugins.with_rows(session, sql, fetch=False),
        context=routed_context(session),
        initiative_id=payload.initiative_id,
    )
    return QueryBuildResponse(
        sql=sql,
        columns=_described(columns),
        relations=list(statement.relations),
        sheets=_sheets(statement),
        plugins=_plugins(statement),
    )


def _node(node: QueryFilterNode) -> query_builder.Node:
    """One line of a filter, as the builder says it."""
    if isinstance(node, QueryFilterGroupSpec):
        return query_builder.Group(
            logic=node.logic,
            conditions=tuple(_node(entry) for entry in node.conditions),
        )
    return query_builder.Condition(
        field=node.field, op=node.op, value=node.value, negate=node.negate
    )


def _spec(payload: QueryBuildRequest) -> query_builder.QuerySpec:
    """The request as the builder's own vocabulary."""
    return query_builder.QuerySpec(
        dataset=payload.dataset,
        sheet=SheetCall(file=payload.sheet.file, range=payload.sheet.range)
        if payload.sheet
        else None,
        plugin=PluginCall(
            plugin=payload.plugin.plugin,
            endpoint=payload.plugin.endpoint,
            params=tuple(
                sorted(
                    (name, tuple(value) if isinstance(value, list) else value)
                    for name, value in payload.plugin.params.items()
                )
            ),
        )
        if payload.plugin
        else None,
        columns=tuple(
            query_builder.Column(
                field=column.field,
                aggregate=column.aggregate,
                bucket=column.bucket,
                alias=column.alias,
                running=column.running,
            )
            for column in payload.columns
        ),
        where=tuple(_node(node) for node in payload.where),
        group_by=tuple(payload.group_by),
        order_by=query_builder.Sort(
            field=payload.order_by.field, descending=payload.order_by.descending
        )
        if payload.order_by
        else None,
        limit=payload.limit,
    )
