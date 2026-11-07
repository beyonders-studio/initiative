"""Reading the rows a statement's ``plugin()`` calls name.

A call names one of an installed plug-in's read endpoints by the plug-in's
public id and the endpoint's name, which together are the endpoint's id. The
install is the enabled one its registration names by that public id, found
under the request's own session as the data route finds one, and the endpoint is called through
:func:`~app.services.marketplace.plugin_data.fetch_for_session`, with its
cache, its bounds and its switches. Its columns are the returns the endpoint
declares as lists, so a statement is described from the pinned definition.

Rows are read on the request's own session, before the statement's
transaction opens.
"""

from __future__ import annotations

from typing import Iterable

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


async def read(
    session: AsyncSession,
    calls: Iterable[object],
    *,
    as_installation: bool = False,
    fetch: bool = True,
) -> dict[PluginCall, PluginRows]:
    """What each ``plugin()`` call among *calls* reads, for the person
    *session* was routed for.

    *as_installation* is a dashboard that runs as its initiative: each call
    is made as the installation, on the community's connections. With *fetch*
    off each call reads its columns and no rows, which describes a statement.

    Raises :class:`QueryError` with the call's code.
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
    read_rows: dict[PluginCall, PluginRows] = {}
    for call in wanted:
        install = installs.get(call.plugin)
        endpoint = (
            plugin_data.find_read_endpoint(install.definition, call.endpoint_id)
            if install is not None
            else None
        )
        if install is None or endpoint is None:
            raise QueryError(PluginDataMessages.ENDPOINT_NOT_FOUND, call.endpoint_id)
        columns = plugin_data.row_columns(endpoint)
        if not fetch:
            read_rows[call] = PluginRows.from_rows(call, columns, ())
            continue
        try:
            answer = await plugin_data.fetch_for_session(
                session,
                plugin=install,
                endpoint_id=call.endpoint_id,
                params={
                    name: list(value) if isinstance(value, tuple) else value
                    for name, value in call.params
                },
                as_installation=as_installation,
            )
        except plugin_data.PluginDataError as refused:
            raise QueryError(refused.code, call.endpoint_id) from refused
        read_rows[call] = PluginRows.from_rows(call, columns, answer.rows)
    return read_rows


async def with_rows(
    session: AsyncSession,
    sql: str,
    *,
    as_installation: bool = False,
    fetch: bool = True,
) -> ResolvedQuery:
    """*sql*, resolved with what its ``plugin()`` calls read (:func:`read`).
    Its spreadsheets are read where it runs."""
    statement = resolve(sql)
    read_rows = await read(
        session, statement.unread, as_installation=as_installation, fetch=fetch
    )
    return resolve(sql, read_rows) if read_rows else statement
