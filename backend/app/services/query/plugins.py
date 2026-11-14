"""Reading the rows a statement's ``plugin()`` calls name.

A call names one of an installed plug-in's read endpoints by the plug-in's
public id and the endpoint's name, which together are the endpoint's id. The
install is the enabled one its registration names by that public id, found
under the request's own session as the data route finds one. Its columns are
the returns the endpoint declares as lists, so a statement is described from
the pinned definition.

Each call is settled on the session first, one after another, and then the
plug-ins are called together
(:func:`~app.services.marketplace.plugin_data.prepare_for_session`), with the
cache, bounds and switches every plug-in read has. Rows are read before the
statement's transaction opens.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import PluginDataMessages
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import plugin_data
from app.services.marketplace.registration_lookup import registration_for_definition
from app.services.query.resolve import (
    PluginCall,
    PluginRows,
    QueryError,
    ResolvedQuery,
    resolve,
)

#: A call settled on the session: the columns it reads, and the plug-in call to
#: make, or none where only its columns are wanted.
Prepared = tuple[
    tuple[tuple[str, str], ...],
    Callable[[], Awaitable[plugin_data.PluginDataResult]] | None,
]


async def prepare(
    session: AsyncSession,
    calls: Iterable[object],
    *,
    initiative_id: int | None,
    as_installation: bool = False,
    fetch: bool = True,
) -> dict[PluginCall, Prepared | QueryError]:
    """Each ``plugin()`` call among *calls*, settled for the person *session*
    was routed for, read in *initiative_id*, or the code it is refused with.

    *as_installation* is a dashboard that runs as its initiative: each call
    is made as the installation, on the community's connections. With *fetch*
    off each call settles its columns alone, which describes a statement.
    """
    wanted = list(dict.fromkeys(call for call in calls if isinstance(call, PluginCall)))
    if not wanted:
        return {}
    installs: dict[str, GuildPlugin] = {}
    for install in (
        await session.exec(select(GuildPlugin).where(GuildPlugin.enabled.is_(True)))
    ).all():
        registration = await registration_for_definition(
            install.definition, listing_uid=install.listing_uid
        )
        if registration is not None:
            installs[registration.public_id] = install
    prepared: dict[PluginCall, Prepared | QueryError] = {}
    for call in wanted:
        install = installs.get(call.plugin)
        endpoint = (
            plugin_data.find_read_endpoint(install.definition, call.endpoint_id)
            if install is not None
            else None
        )
        if install is None or endpoint is None:
            prepared[call] = QueryError(
                PluginDataMessages.ENDPOINT_NOT_FOUND, call.endpoint_id
            )
            continue
        columns = plugin_data.row_columns(endpoint)
        if not fetch:
            prepared[call] = (columns, None)
            continue
        try:
            prepared[call] = (
                columns,
                await plugin_data.prepare_for_session(
                    session,
                    plugin=install,
                    endpoint_id=call.endpoint_id,
                    params={
                        name: list(value) if isinstance(value, tuple) else value
                        for name, value in call.params
                    },
                    initiative_id=initiative_id,
                    as_installation=as_installation,
                ),
            )
        except plugin_data.PluginDataError as refused:
            prepared[call] = QueryError(refused.code, call.endpoint_id)
    return prepared


async def answered(
    prepared: Mapping[PluginCall, Prepared | QueryError],
) -> dict[PluginCall, PluginRows | QueryError]:
    """What each settled call reads, its plug-in called together with the
    others', or the code it is refused with."""
    calling = {
        call: entry[1]
        for call, entry in prepared.items()
        if not isinstance(entry, QueryError) and entry[1] is not None
    }
    answers = dict(
        zip(
            calling,
            await asyncio.gather(
                *(make() for make in calling.values()), return_exceptions=True
            ),
        )
    )
    read_rows: dict[PluginCall, PluginRows | QueryError] = {}
    for call, entry in prepared.items():
        answer = answers.get(call)
        if isinstance(entry, QueryError):
            read_rows[call] = entry
        elif isinstance(answer, plugin_data.PluginDataError):
            read_rows[call] = QueryError(answer.code, call.endpoint_id)
        elif isinstance(answer, BaseException):
            raise answer
        else:
            read_rows[call] = PluginRows.from_rows(
                call, entry[0], answer.rows if answer is not None else ()
            )
    return read_rows


def resolved_with(
    sql: str,
    statement: ResolvedQuery,
    read_rows: Mapping[PluginCall, PluginRows | QueryError],
) -> ResolvedQuery:
    """*statement*, resolved again with what its ``plugin()`` calls read.

    Raises the first of its calls' refusals.
    """
    mine = [read_rows[call] for call in statement.unread if call in read_rows]
    refused = next((entry for entry in mine if isinstance(entry, QueryError)), None)
    if refused is not None:
        raise refused
    rows = {entry.call: entry for entry in mine if isinstance(entry, PluginRows)}
    return resolve(sql, rows) if rows else statement


async def with_rows(
    session: AsyncSession,
    sql: str,
    *,
    initiative_id: int | None,
    as_installation: bool = False,
    fetch: bool = True,
) -> ResolvedQuery:
    """*sql*, resolved with what its ``plugin()`` calls read in
    *initiative_id*. Its spreadsheets are read where it runs."""
    statement = resolve(sql)
    prepared = await prepare(
        session,
        statement.unread,
        initiative_id=initiative_id,
        as_installation=as_installation,
        fetch=fetch,
    )
    return resolved_with(sql, statement, await answered(prepared))
