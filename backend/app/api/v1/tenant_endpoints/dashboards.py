"""Dashboard endpoints — a canvas of widgets over existing data.

Creation is gated at the initiative level (dashboards_enabled +
create_dashboards); everything after that flows from the dashboard's
resource-grant DAC (``resource_grants`` + ``PUT /{id}/grants``), like every
other tool.

A dashboard's ``definition`` is normalized on every write, so only known widget
and binding vocabulary is ever stored. The definition is a presentation spec —
it names where data comes from and never carries content or actions — and each
widget's data is fetched per viewer through that source's own gated endpoint.
Sharing a dashboard therefore shares the *view*, never the underlying data:
a viewer who cannot read a bound counter simply sees an empty widget.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    GuildContextDep,
    IncludeDeletedDep,
    RLSSessionDep,
    get_current_active_user,
)
from app.core.audit_events import AuditEventType
from app.core.messages import (
    DashboardMessages,
    MarketplaceMessages,
    PluginDataMessages,
)
from app.core.tools import Tool
from app.db.session import routed_context, routed_guild_id
from app.models.platform.marketplace import (
    MarketplaceListingVersion,
)
from app.models.platform.user import User
from app.models.tenant.dashboard import Dashboard, DashboardViewMode
from app.models.tenant.guild_plugin import GuildPlugin
from app.schemas.sql_query import QueryColumnDescription, QueryResponse
from app.schemas.tenant.dashboard import (
    DashboardCreate,
    DashboardDataResponse,
    DashboardInstalledListings,
    DashboardRead,
    DashboardUpdate,
    DashboardViewModeRequest,
    DashboardWidgetData,
    WidgetCatalog,
    build_widget_catalog,
)
from app.schemas.tenant.plugin_data import PluginDataResponse
from app.schemas.tenant.tool import serialize_tool
from app.services import audit as audit_service
from app.services import query as query_service
from app.services.marketplace import plugin_data
from app.services.marketplace.installs import (
    count_install,
    resolve_listing_install,
)
from app.services.query import plugins as query_plugins
from app.services.tenant import attachments as attachments_service
from app.services.tenant import dashboards as dashboards_service
from app.services.tenant import metadata as metadata_service
from app.services.tenant import tags as tags_service
from app.services.tenant import view_as
from app.services.tenant.dashboard_definition import (
    normalize_dashboard_config,
    normalize_dashboard_definition,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_body(definition: dict, config: dict) -> tuple[dict, dict]:
    """Validate a definition + its config together. Raises 422 with the
    validator's machine code so the client can localize it."""
    clean_definition = normalize_dashboard_definition(definition or {})
    clean_config = normalize_dashboard_config(config or {}, clean_definition)
    return clean_definition, clean_config


def _listing_canvas(version: MarketplaceListingVersion) -> dict:
    """The canvas a dashboard listing installs.

    A listing stores the dashboard's export envelope; the canvas is its
    ``definition``. Validated again by the caller on the way in: the catalog
    validated it at publish time, but this build decides what it can render
    *now*.
    """
    return dict((version.definition or {}).get("definition") or {})


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


# Declared before /{dashboard_id} so the literal path wins the match.
@router.get("/installed-listings", response_model=DashboardInstalledListings)
async def read_installed_listings(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardInstalledListings:
    """Which marketplace listings this guild has installed, and how many of each.

    One row per distinct listing rather than per dashboard, so the answer is
    complete in one response — the dashboard list is paginated, and a partial
    page would mark some installs and miss others.

    RLS-scoped like every other read here: it counts the dashboards the caller
    can see.
    """
    rows = (
        await session.exec(
            select(Dashboard.listing_uid, func.count())
            .where(Dashboard.listing_uid.is_not(None))
            .group_by(Dashboard.listing_uid)
        )
    ).all()
    return DashboardInstalledListings(
        counts={uid: int(count) for uid, count in rows if uid}
    )


# Declared before /{dashboard_id} so the literal path wins the match.
@router.get("/widget-catalog", response_model=WidgetCatalog)
async def read_widget_catalog(
    guild_context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> WidgetCatalog:
    """The widget vocabulary this build supports — size floors, bindable
    sources, and display options per primitive, plus the named presets.

    Static app metadata rather than guild data (it reads no tables), but it
    stays on the guild-scoped router because it only means anything to someone
    already inside a guild, and that keeps every dashboard route addressed the
    same way. Serving it is what lets the editor's palette avoid carrying a
    second copy of the registry.
    """
    return build_widget_catalog()


@router.get("/{dashboard_id}", response_model=DashboardRead)
async def read_dashboard(
    dashboard_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> DashboardRead:
    dashboard = await resource_access.load_authorized(
        session,
        Tool.dashboard,
        dashboard_id,
        current_user,
        guild_context,
        hydrated=True,
    )
    return serialize_tool(
        DashboardRead, dashboard, user_id=current_user.id, context=guild_context
    )


@router.post("/", response_model=DashboardRead, status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    dashboard_in: DashboardCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Create a dashboard. Requires create_dashboards permission on the
    initiative (or guild admin); the creator gets the owner grant."""
    initiative = await resource_access.prepare_create(
        session, Tool.dashboard, dashboard_in.initiative_id, current_user, guild_context
    )

    listing_id: int | None = None
    listing_version: str | None = None
    if dashboard_in.listing_uid:
        listing, version = await resolve_listing_install(
            session, dashboard_in.listing_uid, kind="dashboard"
        )
        listing_id, listing_version = listing.id, version.version
        # Validated again on the way in: the catalog validated it at publish
        # time, but this build decides what it can render *now*.
        definition, config = _normalize_body(
            _listing_canvas(version), dashboard_in.config
        )
    else:
        definition, config = _normalize_body(
            dashboard_in.definition, dashboard_in.config
        )

    dashboard = Dashboard(
        initiative_id=initiative.id,
        name=dashboard_in.name.strip(),
        description=dashboard_in.description,
        definition=definition,
        config=config,
        listing_uid=dashboard_in.listing_uid,
        listing_version=listing_version,
    )
    session.add(dashboard)
    await session.flush()
    await resource_access.grant_initial_sharing(
        session,
        guild_context,
        Tool.dashboard,
        user=current_user,
        resource_id=dashboard.id,
        initiative_id=initiative.id,
        payload=dashboard_in,
        grants=dashboard_in.grants,
    )

    if dashboard_in.tag_ids:
        await tags_service.set_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.dashboard],
            guild_id=guild_context.guild_id,
            entity_id=dashboard.id,
            tag_ids=dashboard_in.tag_ids,
        )

    await attachments_service.claim_uploads(session, dashboard)
    await metadata_service.write_on_create(session, dashboard, dashboard_in.properties)
    await session.commit()
    if listing_id is not None:
        await count_install(guild_context.guild_id, listing_id)
    return await read_after_write(session, dashboard.id, current_user, guild_context)


@router.patch("/{dashboard_id}", response_model=DashboardRead)
async def update_dashboard(
    dashboard_id: int,
    dashboard_in: DashboardUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Update a dashboard — rename, or re-author its canvas. Requires write
    access. This is the only kind of write a dashboard has: authoring what it
    hooks up to. It never writes the data it displays."""
    dashboard = await resource_access.load_authorized(
        session,
        Tool.dashboard,
        dashboard_id,
        current_user,
        guild_context,
        access="write",
    )
    updated = False
    update_data = dashboard_in.model_dump(exclude_unset=True)

    if "name" in update_data and update_data["name"] is not None:
        dashboard.name = update_data["name"].strip()
        updated = True
    if "description" in update_data:
        dashboard.description = update_data["description"]
        updated = True

    # Definition and config are validated as a pair even when only one is sent,
    # so config can never outlive the widgets it configures.
    if "definition" in update_data or "config" in update_data:
        definition = update_data.get("definition", dashboard.definition)
        config = update_data.get("config", dashboard.config)
        normalized, normalized_config = _normalize_body(definition, config)
        if (normalized, normalized_config) != (dashboard.definition, dashboard.config):
            _check_view_mode_allows(dashboard, guild_context)
        dashboard.definition, dashboard.config = normalized, normalized_config
        updated = True

    if updated:
        dashboard.updated_at = datetime.now(UTC)
        session.add(dashboard)
        await attachments_service.claim_uploads(session, dashboard)
        await session.commit()

    return await read_after_write(session, dashboard.id, current_user, guild_context)


@router.post("/{dashboard_id}/upgrade", response_model=DashboardRead)
async def upgrade_dashboard(
    dashboard_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Re-pin an installed dashboard to its listing's current version.

    Nothing is ever pushed into a guild: a new version sits in the catalog until
    someone with write access here asks for it. Applying one replaces this
    instance's definition and nothing else — other instances of the same
    listing, in this guild or any other, are untouched.

    The instance's own config survives. A binding slot the new version dropped
    takes its config key with it, which is the same normalization an edit does,
    so config can never outlive the widget it configured.
    """
    dashboard = await resource_access.load_authorized(
        session,
        Tool.dashboard,
        dashboard_id,
        current_user,
        guild_context,
        access="write",
    )
    if not dashboard.listing_uid:
        # Authored here, not installed — there is no listing to re-pin to.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.NOT_INSTALLED_FROM_LISTING,
        )

    _, version = await resolve_listing_install(
        session, dashboard.listing_uid, kind="dashboard"
    )
    if version.version == dashboard.listing_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MarketplaceMessages.ALREADY_LATEST_VERSION,
        )

    definition, config = _normalize_body(_listing_canvas(version), dashboard.config)
    # A new version replaces what this dashboard asks, which is the same act as
    # editing it.
    _check_view_mode_allows(dashboard, guild_context)
    dashboard.definition = definition
    dashboard.config = config
    dashboard.listing_version = version.version
    dashboard.updated_at = datetime.now(UTC)
    session.add(dashboard)
    await session.commit()

    return await read_after_write(session, dashboard.id, current_user, guild_context)


def _check_view_mode_allows(dashboard: Dashboard, guild_context: GuildContext) -> None:
    """Whether the caller may change what this dashboard's widgets ask.

    A dashboard that runs as its initiative reads everything in it, so what its
    statements ask is what everybody who opens it sees. Changing them takes
    the same permission as turning it on; anybody else with write access can
    switch it back to Individual first.
    """
    if view_as.runs_as_initiative(dashboard) and not view_as.may_run_as_initiative(
        guild_context, dashboard.initiative_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DashboardMessages.VIEW_MODE_EDIT_NOT_ALLOWED,
        )


def _stored_binding(
    definition: dict[str, Any] | None,
    config: dict[str, Any] | None,
    widget_id: str,
) -> dict[str, Any] | None:
    """One widget's binding as the canvas resolves it.

    The instance config layers over the definition exactly as it does when the
    dashboard is drawn, so a slot a listing left open and the guild filled in
    counts the same as one the definition named outright.
    """
    widgets = (definition or {}).get("widgets")
    if not isinstance(widgets, list):
        return None
    overrides = (config or {}).get("widgets") or {}
    for widget in widgets:
        if not isinstance(widget, dict) or str(widget.get("id")) != widget_id:
            continue
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            return None
        override = overrides.get(widget_id)
        return {**binding, **(override if isinstance(override, dict) else {})}
    return None


def _widget_ids(definition: dict[str, Any] | None) -> list[str]:
    """Every widget placed on a canvas, in the order the definition lists them."""
    widgets = (definition or {}).get("widgets")
    if not isinstance(widgets, list):
        return []
    return [
        str(widget["id"])
        for widget in widgets
        if isinstance(widget, dict) and widget.get("id") is not None
    ]


def _query_response(result: query_service.QueryResult) -> QueryResponse:
    return QueryResponse(
        columns=[
            QueryColumnDescription(
                name=column.name,
                type=column.type,
                grain=column.grain,
                date_only=column.date_only,
            )
            for column in result.columns
        ],
        rows=[list(row) for row in result.rows],
        truncated=result.truncated,
        relations=list(result.relations),
    )


def _answered_as(session: Any, dashboard: Dashboard) -> Any:
    """Who this canvas's statements run as: the initiative's full read access
    when the dashboard runs as its initiative, otherwise the viewer's own.
    Asked only after the dashboard's own gates have admitted the reader."""
    routed = routed_context(session)
    return view_as.initiative_context(dashboard, routed) or routed


@router.get("/{dashboard_id}/data", response_model=DashboardDataResponse)
async def load_dashboard_data(
    dashboard_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardDataResponse:
    """Answer every query widget on this dashboard at once.

    The canvas is one unit of work: its gates are asked once, its widgets'
    statements run as one statement in one transaction, and every tile reads
    the same moment. A widget whose statement is refused says so in its own
    entry; the rest still answer. What runs is each widget's own stored
    statement, never one the request supplies.
    """
    dashboard = await resource_access.load_authorized(
        session, Tool.dashboard, dashboard_id, current_user, guild_context
    )
    widgets = await canvas_widget_data(session, dashboard, guild_context.guild_id)
    return DashboardDataResponse(initiative_id=dashboard.initiative_id, widgets=widgets)


async def canvas_widget_data(
    session: AsyncSession, dashboard: Dashboard, guild_id: int
) -> dict[str, DashboardWidgetData]:
    """Every widget on a dashboard the reader may already read that reads
    data, answered together: the canvas route's work.

    A statement and a plug-in widget each read with what the widget stores,
    as the dashboard's view mode says: a dashboard that runs as its initiative
    calls a plug-in as the installation.

    Raises :class:`query_service.QueryError` when the canvas as a whole is
    refused; a single widget's refusal is its own entry."""
    context = _answered_as(session, dashboard)
    as_installation = view_as.runs_as_initiative(dashboard)

    # Everything each widget needs from the session is read first, one widget
    # after another; then every plug-in is called together.
    widgets: dict[str, DashboardWidgetData] = {}
    sources: dict[str, tuple[str, query_service.ResolvedQuery]] = {}
    calls: dict[str, Callable[[], Awaitable[plugin_data.PluginDataResult]]] = {}
    installs: dict[str, GuildPlugin] | None = None
    for widget_id in _widget_ids(dashboard.definition):
        binding = _stored_binding(dashboard.definition, dashboard.config, widget_id)
        source = (binding or {}).get("source")
        sql = (binding or {}).get("sql")
        try:
            if source == "query" and isinstance(sql, str) and sql.strip():
                sources[widget_id] = (sql, query_service.resolve(sql))
            elif source == "plugin" and binding is not None:
                if installs is None:
                    installs = {
                        install.listing_uid: install
                        for install in (
                            await session.exec(
                                select(GuildPlugin).where(GuildPlugin.enabled.is_(True))
                            )
                        ).all()
                    }
                install = installs.get(str(binding.get("plugin_uid")))
                if install is None:
                    raise plugin_data.PluginDataError(
                        PluginDataMessages.ENDPOINT_NOT_FOUND, 404
                    )
                calls[widget_id] = await plugin_data.prepare_for_session(
                    session,
                    plugin=install,
                    endpoint_id=str(binding.get("endpoint_id")),
                    params=binding.get("params") or {},
                    as_installation=as_installation,
                )
        except (query_service.QueryError, plugin_data.PluginDataError) as refused:
            widgets[widget_id] = DashboardWidgetData(error=refused.code)
    prepared = await query_plugins.prepare(
        session,
        [call for _, statement in sources.values() for call in statement.unread],
        as_installation=as_installation,
    )

    read_rows, *answers = await asyncio.gather(
        query_plugins.answered(prepared),
        *(call() for call in calls.values()),
        return_exceptions=True,
    )
    if isinstance(read_rows, BaseException):
        raise read_rows
    for widget_id, answer in zip(calls, answers):
        if isinstance(answer, plugin_data.PluginDataError):
            widgets[widget_id] = DashboardWidgetData(error=answer.code)
        elif isinstance(answer, BaseException):
            raise answer
        else:
            widgets[widget_id] = DashboardWidgetData(
                plugin=PluginDataResponse(
                    rows=answer.rows,
                    values=answer.values,
                    fetched_at=answer.fetched_at,
                    cached=answer.cached,
                )
            )
    statements: dict[str, query_service.ResolvedQuery] = {}
    for widget_id, (sql, statement) in sources.items():
        try:
            statements[widget_id] = query_plugins.resolved_with(
                sql, statement, read_rows
            )
        except query_service.QueryError as refused:
            widgets[widget_id] = DashboardWidgetData(error=refused.code)

    outcomes = await query_service.execute_canvas(
        statements,
        context=context,
        initiative_id=dashboard.initiative_id,
    )
    for widget_id, outcome in outcomes.items():
        widgets[widget_id] = (
            DashboardWidgetData(error=outcome.code)
            if isinstance(outcome, query_service.QueryError)
            else DashboardWidgetData(result=_query_response(outcome))
        )
    return widgets


@router.put("/{dashboard_id}/view-mode", response_model=DashboardRead)
async def set_view_mode(
    dashboard_id: int,
    payload: DashboardViewModeRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> DashboardRead:
    """Choose whose access this dashboard's query widgets answer from.

    ``individual`` is each viewer's own. ``initiative`` is full read access to
    the dashboard's initiative, the same for everyone who can open it — the
    dashboard's access, not the caller's. Either takes write access to the
    dashboard; turning ``initiative`` on also takes the initiative role
    permission for it, which managers always hold.
    """
    dashboard = await resource_access.load_authorized(
        session,
        Tool.dashboard,
        dashboard_id,
        current_user,
        guild_context,
        access="write",
    )
    wanted = payload.mode.value
    if wanted == DashboardViewMode.initiative.value and not (
        view_as.may_run_as_initiative(guild_context, dashboard.initiative_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DashboardMessages.VIEW_MODE_NOT_ALLOWED,
        )
    if dashboard.view_mode != wanted:
        previous = dashboard.view_mode
        dashboard.view_mode = wanted
        dashboard.updated_at = datetime.now(UTC)
        session.add(dashboard)
        await audit_service.record(
            session,
            event_type=AuditEventType.SHARING_GRANT_CHANGED,
            actor_user_id=current_user.id,
            guild_id=routed_guild_id(session),
            target_type=Tool.dashboard.value,
            target_id=dashboard_id,
            detail={
                "initiative_id": dashboard.initiative_id,
                "view_mode": {"from": previous, "to": wanted},
            },
        )
        await session.commit()

    return await read_after_write(session, dashboard_id, current_user, guild_context)


# ---------------------------------------------------------------------------
# Sharing (resource grants)
# ---------------------------------------------------------------------------


async def read_after_write(
    session: RLSSessionDep,
    dashboard_id: int,
    user: User,
    guild_context: GuildContext,
) -> DashboardRead:
    """The dashboard a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    dashboard = await dashboards_service.get_dashboard_hydrated(
        session, dashboard_id, populate_existing=True
    )
    if not dashboard:
        raise Tool.dashboard.not_found()
    return serialize_tool(
        DashboardRead, dashboard, user_id=user.id, context=guild_context
    )
