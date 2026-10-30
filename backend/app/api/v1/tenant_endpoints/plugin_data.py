"""External data reaching a dashboard widget.

Three reads, all guild-scoped, all under the caller's own session.

``/plugins/widget-catalog`` is the palette: which installed plug-ins contribute
widgets, what each widget draws, and the module the browser will run in its
sandbox. It comes from each install's **pinned** definition, so a canvas is
authored against the version the guild chose.

``/plugins/{plugin_id}/endpoints/{endpoint_id}`` is the proxy. A widget never names
an address — it names a read endpoint on an installed plug-in, and this route turns
that into one bounded call to the plug-in's own service. The request carries the dashboard the
widget sits on, and that is what makes the gates run **before** anything else:

* the URL is ``/c/{community_id}/…`` under a session that assumes the guild's own
  Postgres role, so the install row is reachable only from inside the guild;
* the dashboard is loaded through the ordinary resource path, so a member of the
  guild who is not in the dashboard's initiative gets the same answer they would
  get for the dashboard itself — nothing;
* the dashboard has to actually bind this endpoint, so holding one dashboard is
  not a key to every endpoint a plug-in offers;
* an endpoint marked ``admin_only`` is then read by the guild's admins alone.

Only after all of that does the service layer look at the response cache, which
is why the cache is a cache of *responses* rather than of decisions.

``/plugins/summaries`` lists the installs that say where the community stands with
them, and ``/plugins/{plugin_id}/summary`` reads one: the read its manifest names
as its ``community_summary``, drawn on the community's Usage settings. Both are
on the settings rung, so the list is not the content-gated install list. The caller names the install and nothing else — which endpoint
is read comes from the pinned definition — and it is the settings rung that
decides who may ask, the same as the storage figure beside it.

``/plugins/{plugin_id}/actions/{action_id}`` runs one of a plug-in's actions on
one item for the caller. What it checks before the plug-in is called is
:mod:`app.services.marketplace.plugin_actions`'s.

``/plugins/{plugin_id}/endpoints/{endpoint_id}/options`` fills a menu. It is the one
read here with no dashboard on it, because it exists to fill in a form for a
widget nobody has placed yet — and what stands in for that gate is that the
caller cannot name what gets called: the source comes from the plug-in's own
declaration, and it is fetched on the caller's own credentials.
"""

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select

from app.core.errors import CodedError
from app.api import resource_access
from app.api.deps import (
    AgeViewerDep,
    RLSSessionDep,
    GuildContextDep,
    CurrentUser,
    GuildContext,
    SettingsRLSSessionDep,
    require_surface,
)
from app.core.audit_events import AuditEventType
from app.core.messages import GuildPluginMessages, PluginDataMessages
from app.core.rate_limit import PLUGIN_ACTIONS_PER_MEMBER, take_allowance
from app.core.tools import Tool
from app.models.platform.guild import AdminSurface
from app.models.tenant.guild_plugin import GuildPlugin
from app.schemas.sql_query import QueryColumnDescription
from app.services.query import rows as rows_query
from app.schemas.tenant.plugin_data import (
    PluginActionResult,
    PluginActionRun,
    PluginDataTable,
    PluginDataResponse,
    PluginEndpointRead,
    PluginParamOption,
    PluginParamOptionsResponse,
    PluginSummaryListResponse,
    PluginWidgetCatalogEntry,
    PluginWidgetCatalogResponse,
    PluginWidgetRead,
)
from app.services import audit as audit_service
from app.services.marketplace import plugin_actions
from app.services.marketplace import plugin_data as plugin_data_service
from app.services.marketplace.service_plugins import plugin_widget_type, is_admin_only
from app.services.tenant import plugin_age


def _projected_sample(raw: Any, endpoints: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """A widget's own sample, read the way its live answer will be.

    A publisher supplies what the endpoint would answer with, and this projects
    it through that endpoint's returns exactly as the proxy does — so the tile
    somebody chooses a widget by is the tile they get once it is bound. A sample
    for an endpoint the definition does not read is dropped.
    """
    if not isinstance(raw, dict):
        return {}
    projected: dict[str, Any] = {}
    for endpoint_id, result in raw.items():
        endpoint = endpoints.get(endpoint_id)
        if endpoint is None or not isinstance(result, dict):
            continue
        rows, values = plugin_data_service.project_returns(result, endpoint)
        projected[endpoint_id] = {"rows": rows, "values": values}
    return projected


#: The community's usage page, where its admins read what each plug-in
#: reports.
UsageContext = Annotated[
    GuildContext, Depends(require_surface(AdminSurface.usage, settings=True))
]

router = APIRouter()


def _bound_bindings(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    *,
    plugin_uid: str,
    endpoint_id: str,
) -> dict[str, dict[str, Any]]:
    """The widgets of this dashboard that display this endpoint, by widget id.

    The instance config layers over the definition's binding exactly as the
    canvas resolves it, so a slot a listing left open and the guild filled in
    counts the same as one the definition named outright.
    """
    widgets = (definition or {}).get("widgets")
    if not isinstance(widgets, list):
        return {}
    stored = config if isinstance(config, dict) else {}
    overrides = stored.get("widgets") or {}
    bound: dict[str, dict[str, Any]] = {}
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        override = overrides.get(widget.get("id"))
        effective = {**binding, **(override if isinstance(override, dict) else {})}
        if (
            effective.get("source") == "plugin"
            and effective.get("plugin_uid") == plugin_uid
            and effective.get("endpoint_id") == endpoint_id
        ):
            bound[str(widget.get("id"))] = effective
    return bound


# Declared before ``/{plugin_id}`` on the plug-ins router so the literal path wins the
# match (this router is included first for that reason).
@router.get("/widget-catalog", response_model=PluginWidgetCatalogResponse)
async def read_plugin_widget_catalog(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> PluginWidgetCatalogResponse:
    """Which widgets this guild's installed plug-ins contribute.

    Every member may read it: a plug-in's existence is guild-wide knowledge and the
    palette carries no guild data — declarations, module source, and sample
    rows, all from the pinned definition. An endpoint declared for guild admins
    is still listed, and still refused at fetch time to anyone else.

    Disabled installs are left out entirely: their widgets have nothing to draw,
    so offering them would be offering a binding that cannot resolve.
    """
    plugins = (
        await session.exec(
            select(GuildPlugin).order_by(GuildPlugin.name, GuildPlugin.id)
        )
    ).all()

    items: list[PluginWidgetCatalogEntry] = []
    for plugin in plugins:
        definition = plugin.definition or {}
        if not plugin.enabled or definition.get("plugin_kind") != "service":
            continue
        declared = definition.get("widgets")
        if not isinstance(declared, list):
            continue
        widgets = [
            entry
            for entry in declared
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        ]
        if not widgets:
            continue

        # Reads only. A picker offering a write would offer a tile that makes
        # the plug-in act every time somebody looks at a dashboard.
        readable = {
            endpoint["id"]: endpoint
            for endpoint in definition.get("endpoints") or []
            if isinstance(endpoint, dict)
            and isinstance(endpoint.get("id"), str)
            and endpoint.get("direction") == "read"
        }
        endpoints = [
            PluginEndpointRead(
                id=endpoint["id"],
                admin_only=is_admin_only(endpoint),
                cache_ttl_seconds=endpoint.get("cache_ttl_seconds") or 0,
                params=endpoint.get("params") or [],
                returns=endpoint.get("returns") or [],
            )
            for endpoint in readable.values()
        ]
        items.append(
            PluginWidgetCatalogEntry(
                plugin_id=plugin.id,
                plugin_uid=plugin.listing_uid,
                name=plugin.name,
                enabled=plugin.enabled,
                widgets=[
                    PluginWidgetRead(
                        type=plugin_widget_type(plugin.listing_uid, widget["id"]),
                        id=widget["id"],
                        meta=widget.get("meta") or {},
                        module_source=widget.get("module_source") or "",
                        endpoints=widget.get("endpoints") or [],
                        sample_data=_projected_sample(
                            widget.get("sample_data"), readable
                        ),
                    )
                    for widget in widgets
                ],
                endpoints=endpoints,
            )
        )
    return PluginWidgetCatalogResponse(items=items)


@router.get("/{plugin_id}/endpoints/{endpoint_id}", response_model=PluginDataResponse)
async def read_plugin_data(
    plugin_id: int,
    endpoint_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
    dashboard_id: Annotated[
        int,
        Query(
            description=(
                "The dashboard the widget sits on. Its own gates decide whether "
                "this caller may see anything here at all."
            )
        ),
    ],
    params: Annotated[
        Optional[str],
        Query(description="The binding's parameters, as a JSON object."),
    ] = None,
    widget_id: Annotated[
        Optional[str],
        Query(
            description=(
                "Which widget on that dashboard is asking. Only needed where "
                "its binding carries a statement: what runs is the one stored "
                "on the widget, never one the request supplies."
            )
        ),
    ] = None,
) -> PluginDataResponse:
    """One of a plug-in's read endpoints, resolved for this viewer.

    Returns the plug-in's rows verbatim with the time they were obtained. A plug-in
    that is unreachable, slow, oversized, or answering in a shape this build
    does not accept comes back as a named message code, so the canvas draws one
    error tile instead of the request becoming a server fault.
    """
    # Gates 1–4 for the surface the data is being drawn on: RLS scopes the row
    # to this guild, initiative membership decides whether it exists for this
    # caller, and the resource's own grants decide whether they may read it.
    dashboard = await resource_access.load_authorized(
        session, Tool.dashboard, dashboard_id, current_user, guild_context
    )

    plugin = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
    ).first()
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ENDPOINT_NOT_FOUND,
        )
    # What a tile shows is the plug-in's, so a viewer too young for it reads none.
    if not plugin_age.age_allows(plugin.definition, viewer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildPluginMessages.AGE_RESTRICTED,
        )
    bound = _bound_bindings(
        dashboard.definition,
        dashboard.config,
        plugin_uid=plugin.listing_uid,
        endpoint_id=endpoint_id,
    )
    if not bound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ENDPOINT_NOT_FOUND,
        )

    result = await plugin_data_service.fetch_plugin_source(
        session,
        plugin=plugin,
        endpoint_id=endpoint_id,
        raw_params=params,
        user_id=current_user.id,
        is_guild_admin=guild_context.is_admin,
    )

    # After the fetch, so a statement is a transformation of a shared answer:
    # twenty viewers of the same binding are still one upstream call, whatever
    # each of their widgets asks of the rows.
    table = _transformed(plugin, endpoint_id, bound.get(widget_id or ""), result)
    return PluginDataResponse(
        rows=result.rows,
        table=table,
        values=result.values,
        fetched_at=result.fetched_at,
        cached=result.cached,
    )


def _transformed(
    plugin: GuildPlugin,
    endpoint_id: str,
    binding: dict[str, Any] | None,
    result: "plugin_data_service.PluginDataResult",
) -> PluginDataTable | None:
    """What this widget's statement made of the rows, or nothing.

    A binding with no statement draws the plug-in's own rows, as it always has —
    the plug-in's widget module reads them by the names its manifest declared. A
    binding with one gets a table beside them: described, and positional, so a
    built-in widget can be pointed at a plug-in.
    """
    statement = (binding or {}).get("sql")
    if not isinstance(statement, str) or not statement.strip():
        return None

    endpoint = plugin_data_service.find_read_endpoint(plugin.definition, endpoint_id)
    if endpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ENDPOINT_NOT_FOUND,
        )
    planned = rows_query.plan(statement, plugin_data_service.row_columns(endpoint))
    answered = rows_query.evaluate(planned, result.rows)

    return PluginDataTable(
        columns=[
            QueryColumnDescription(name=column.name, type=column.type)
            for column in planned.columns
        ],
        rows=[list(row) for row in answered],
    )


@router.get("/summaries", response_model=PluginSummaryListResponse)
async def list_plugin_summaries(
    session: SettingsRLSSessionDep,
    _guild_context: UsageContext,
) -> PluginSummaryListResponse:
    """The installs whose pinned definition names a community summary, with
    what each declares it returns."""
    return await plugin_data_service.community_summaries(session)


@router.get("/{plugin_id}/summary", response_model=PluginDataResponse)
async def read_plugin_summary(
    plugin_id: int,
    session: SettingsRLSSessionDep,
    current_user: CurrentUser,
    _guild_context: UsageContext,
) -> PluginDataResponse:
    """Where the community stands with one installed plug-in.

    The endpoint is the one the pinned definition names as its
    ``community_summary``; an install that names none, or is switched off,
    has nothing to draw and answers 404. A plug-in that does not answer comes
    back as the proxy's own message code, so the page draws "unavailable"
    rather than failing. The settings rung is the community's admin standing,
    which is what an admin-only summary asks for.
    """
    return await plugin_data_service.read_community_summary(
        session, plugin_id=plugin_id, user_id=current_user.id
    )


@router.get(
    "/{plugin_id}/endpoints/{endpoint_id}/options",
    response_model=PluginParamOptionsResponse,
)
async def read_plugin_param_options(
    plugin_id: int,
    endpoint_id: str,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
    param: Annotated[
        str,
        Query(description="Which of the endpoint's parameters to fill a menu for."),
    ],
    params: Annotated[
        Optional[str],
        Query(
            description=(
                "What the form has answered so far, as a JSON object. Only the "
                "answers a source's `needs` names are ever forwarded."
            )
        ),
    ] = None,
) -> PluginParamOptionsResponse:
    """The values one of an endpoint's parameters permits.

    This is what turns a declared ``options_from`` into a menu, and it is the
    one read here that carries no dashboard. It cannot: it exists to fill in a
    form for a widget that has not been placed yet, so there is no dashboard
    row whose gates could decide it.

    What decides it instead is that the caller never names what is called. The
    source is read out of the plug-in's own pinned declaration — the
    ``options_from`` of the parameter being filled in — so the reachable set is
    exactly the reads a publisher marked as menu sources, and the arguments are
    the ones that source's ``needs`` names, mapped from answers this same form
    already holds. The source is then fetched on the caller's own credentials,
    exactly as it is for a placed tile.

    A source that will not resolve is not an error: it comes back as
    ``unavailable`` with no options, and the parameter stays typeable.
    """
    plugin = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
    ).first()
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ENDPOINT_NOT_FOUND,
        )
    # What a tile shows is the plug-in's, so a viewer too young for it reads none.
    if not plugin_age.age_allows(plugin.definition, viewer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildPluginMessages.AGE_RESTRICTED,
        )

    options, unavailable = await plugin_data_service.resolve_param_options(
        session,
        plugin=plugin,
        endpoint_id=endpoint_id,
        param_key=param,
        raw_params=params,
        user_id=current_user.id,
        is_guild_admin=guild_context.is_admin,
    )

    return PluginParamOptionsResponse(
        options=[PluginParamOption(**option) for option in options],
        unavailable=unavailable,
    )


#: The counter namespace for actions' allowance.
_ACTION_LIMIT_NAMESPACE = "plugin-action"
#: How an action ended, in the audit line, when the plug-in answered.
_ACTION_OK = "ok"


@router.post("/{plugin_id}/actions/{action_id}", response_model=PluginActionResult)
async def run_plugin_action(
    plugin_id: int,
    action_id: str,
    payload: PluginActionRun,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    viewer: AgeViewerDep,
) -> PluginActionResult:
    """Run one of a plug-in's actions on one item.

    A container plug-in does the work, called as its installation with the
    caller and the item named; Initiative changes nothing itself. A
    declarative plug-in's action is run by Initiative: the call it names, on
    the credential the plug-in says, and the change it makes to the plug-in's
    values on the item. Either way the action's endpoint is sent what the
    caller answered for the parameters the action asks for. The answer is the
    values the plug-in shows on the item afterwards. Refused with
    ``PLUGIN_ACTION_NOT_FOUND`` when the install declares no such action on
    this kind of item, ``PLUGIN_ACTION_NOT_OFFERED`` when it is not offered on
    this item for the caller, ``PLUGIN_DATA_INVALID_PARAMS`` when what the
    caller answered is not what the action asks for or the element is not one
    it is offered on,
    ``PLUGIN_DATA_CONNECTION_REQUIRED`` when it needs the caller's own account
    and they have connected none, the item's own refusal when the caller
    cannot read it, and 429 past the allowance.
    """
    plugin = (
        await session.exec(select(GuildPlugin).where(GuildPlugin.id == plugin_id))
    ).first()
    if plugin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=PluginDataMessages.ACTION_NOT_FOUND,
        )
    kind = payload.entity_type.value

    def audit(outcome: str) -> None:
        audit_service.emit(
            event_type=AuditEventType.PLUGIN_ACTION,
            actor_user_id=current_user.id,
            guild_id=guild_context.guild_id,
            target_type=kind,
            target_id=payload.entity_id,
            detail={
                "install_id": plugin.id,
                "listing_uid": plugin.listing_uid,
                "action": action_id,
                "outcome": outcome,
            },
        )

    if not await take_allowance(
        PLUGIN_ACTIONS_PER_MEMBER,
        _ACTION_LIMIT_NAMESPACE,
        f"{guild_context.guild_id}:{plugin.id}:{current_user.id}",
    ):
        audit(PluginDataMessages.RATE_LIMITED)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=PluginDataMessages.RATE_LIMITED,
        )
    try:
        values = await plugin_actions.run_action(
            session,
            plugin=plugin,
            action_id=action_id,
            kind=kind,
            entity_id=payload.entity_id,
            context=guild_context,
            user_id=current_user.id,
            age_allows=plugin_age.age_allows(plugin.definition, viewer),
            params=payload.params,
            element=payload.element,
        )
    except CodedError as exc:
        audit(exc.code)
        raise
    except HTTPException as exc:
        audit(str(exc.detail))
        raise
    audit(_ACTION_OK)
    return PluginActionResult(values=values)
