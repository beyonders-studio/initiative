from typing import Any

from fastapi import APIRouter

from app.api.deps import DirectMessagesEnabledDep
from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS
from app.core.tools import Tool

# Endpoints are organized by the kind of data they touch (they must never mix —
# this mirrors the tenant/ vs platform/ split in models/, schemas/, services/):
#   platform_endpoints/  — public-schema tables (auth, users, guilds, settings,
#                          …); not tied to a single guild.
#   tenant_endpoints/    — per-guild-schema tables (projects, tasks, files,
#                          …), including the cross-guild "my" aggregates that read
#                          them — the one place tenant data is read without a
#                          single guild context (see /me routes below).
from app.api.v1.tenant_endpoints import (
    moderation,
    evidence,
    holds,
    archive,
    query,
    smart_chips,
    search as guild_search,
    ai_settings,
    plugin_data,
    attachments,
    webhooks,
    calendar_entries,
    calendar_events,
    calendars,
    dashboards,
    guild_plugins,
    collaboration,
    comments,
    counters,
    files,
    events,
    exports,
    imports,
    initiatives,
    marketplace as guild_marketplace,
    me_ai,
    me_tools,
    galleries,
    me_trash,
    posts,
    projects,
    property_definitions,
    property_values,
    queues,
    reactions,
    recents,
    relationships,
    resource_grants,
    storage,
    tags,
    task_statuses,
    tasks,
    tool_grants,
    tool_lifecycle,
    tool_lists,
    tool_views,
    tools,
    trash,
    wikis,
)
from app.api.v1.platform_endpoints import (
    account_change,
    held_changes,
    field_catalog,
    recurrence,
    access_grants,
    announcements,
    ai_settings as platform_ai_settings,
    plugin_consent_requests,
    plugin_oauth,
    plugin_platform,
    plugin_installation,
    plugin_hub,
    plugin_connection_callbacks,
    plugin_hooks,
    plugin_services,
    auth,
    auth_providers,
    provider_placement,
    billing,
    config,
    contacts,
    demo,
    guild_reference,
    guild_provider_connections,
    guilds,
    health,
    legal,
    marketplace,
    native,
    notification_prefs,
    notifications,
    operator,
    push,
    intake,
    passkeys,
    email_otp,
    passwordless,
    second_factor,
    sessions,
    settings,
    tickets,
    user_view_preferences,
    users,
    version,
    dm,
    dm_transport,
)

api_router = APIRouter()

# ---------------------------------------------------------------------------
# Top-level routes: unauthenticated, user-scoped, operator, and cross-guild.
# These do NOT take a guild path segment.
# ---------------------------------------------------------------------------
api_router.include_router(field_catalog.router, tags=["fields"])
api_router.include_router(recurrence.router, prefix="/recurrence", tags=["recurrence"])
api_router.include_router(version.router, tags=["version"])
api_router.include_router(health.router, tags=["health"])
api_router.include_router(native.router, tags=["native"])
api_router.include_router(config.router, tags=["config"])
# This deployment's terms and privacy policy, if it has any.
# Unauthenticated: the signup form links to them.
api_router.include_router(legal.router, tags=["legal"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
# The demo deployment's routes; 404 unless the deployment runs as the demo.
api_router.include_router(demo.router, prefix="/demo", tags=["demo"])
# Mounted on the same prefix: the factor routes are part of /auth, kept in
# their own module rather than growing the sign-in one.
api_router.include_router(second_factor.router, prefix="/auth", tags=["auth"])
api_router.include_router(passkeys.router, prefix="/auth", tags=["auth"])
api_router.include_router(passwordless.router, prefix="/auth", tags=["auth"])
api_router.include_router(account_change.router, prefix="/auth", tags=["auth"])
api_router.include_router(email_otp.router, prefix="/auth", tags=["auth"])
api_router.include_router(sessions.router, prefix="/auth", tags=["auth"])
api_router.include_router(operator.router, prefix="/operator", tags=["operator"])
api_router.include_router(guilds.router, prefix="/communities", tags=["communities"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
# Direct messages, both halves, gated on the platform switch in one place: a
# deployment that does not offer messaging refuses the whole surface rather
# than each route deciding for itself.
api_router.include_router(
    dm_transport.user_router,
    prefix="/users",
    tags=["direct-messages"],
    dependencies=[DirectMessagesEnabledDep],
)
# What this deployment carries: the operator's catalog rescan, the signed
# registry, and the mirrored listing artwork. A property of the deployment
# rather than of any guild, so it takes no guild segment. Reading the
# marketplace is guild-addressed (see /c/{community_id}/marketplace below).
api_router.include_router(
    marketplace.router, prefix="/marketplace", tags=["marketplace"]
)
api_router.include_router(push.router, prefix="/push", tags=["push"])
# Deployment-wide notices: what changed, who should hear about it, and what
# each person has already dealt with. Platform-addressed — one announcement
# reaches every guild — so no guild segment.
api_router.include_router(
    announcements.router, prefix="/announcements", tags=["announcements"]
)
# Platform / app-wide config (owner-only) and cross-guild PAM management — NOT
# guild-scoped (SystemSessionDep / capability-gated), so they stay top-level.
api_router.include_router(
    access_grants.router, prefix="/access-grants", tags=["access-grants"]
)
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(intake.router, prefix="/settings", tags=["intake"])
# Deployment-level plug-in service wiring (plugins.manage — owner). Platform-addressed
# like the catalog: a registration belongs to the deployment, never to a guild.
api_router.include_router(
    plugin_services.router, prefix="/plugin-services", tags=["plugin-services"]
)
api_router.include_router(
    plugin_services.publishers_router,
    prefix="/plugin-publishers",
    tags=["plugin-services"],
)
# Public: plug-ins verify the context JWTs we send them against this key set. No
# credential, because requiring one to fetch a verification key is circular.
api_router.include_router(
    plugin_platform.router, prefix="/plugin-platform", tags=["plugin-platform"]
)
api_router.include_router(
    guild_reference.router, prefix="/plugin-platform", tags=["plugin-platform"]
)
# The token endpoint: a plug-in authenticates with a JWT it signs and is issued a
# plug-in or installation token. The listing of its installs takes the plug-in token.
api_router.include_router(
    plugin_oauth.router, prefix="/plugin-platform", tags=["plugin-platform"]
)
# An installed plug-in asking a member to let it act as them, on its installation
# token. The member answers on their own consent screen.
api_router.include_router(
    plugin_consent_requests.router, prefix="/plugin-platform", tags=["plugin-platform"]
)
# An installed plug-in's calls about its own installation — its configuration, its
# members' connections, its verdict on the configuration and the events it
# re-emits — on its installation token. The install comes from the token.
api_router.include_router(
    plugin_installation.router, prefix="/plugin-platform", tags=["plugin-platform"]
)
# An installed plug-in calling another plug-in's public endpoint, on its installation
# or member token. Initiative checks the call and makes it.
api_router.include_router(
    plugin_hub.router, prefix="/plugin-platform", tags=["plugin-platform"]
)
# Where a vendor returns a person during a plug-in connection's flow. The two
# addresses an operator registers with each vendor client; they act on the
# flow's sealed state alone.
api_router.include_router(
    plugin_connection_callbacks.router,
    prefix="/plugin-connections",
    tags=["plugin-platform"],
)
# Where a vendor sends a plug-in's webhooks, one address per plug-in. A delivery is
# admitted by its signature and routed by the install index.
api_router.include_router(
    plugin_hooks.router, prefix="/plugin-hooks", tags=["plugin-platform"]
)
api_router.include_router(
    auth_providers.router, prefix="/settings/auth/providers", tags=["auth-providers"]
)
api_router.include_router(
    provider_placement.router,
    prefix="/settings/placement",
    tags=["provider-placement"],
)
api_router.include_router(
    guild_provider_connections.router,
    prefix="/communities",
    tags=["community-provider-connections"],
)
# Service-to-service endpoints for the external billing service.
api_router.include_router(billing.router, prefix="/billing", tags=["billing"])
api_router.include_router(
    platform_ai_settings.platform_router, prefix="/settings", tags=["ai-settings"]
)
# Notifications are user-scoped (cross-guild) — not under /c.
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
# Recents tabs bar is cross-guild (GET list). The addressed delete lives under
# the guild router below.
api_router.include_router(recents.router, prefix="/recents", tags=["recents"])
api_router.include_router(
    user_view_preferences.router,
    prefix="/user-view-preferences",
    tags=["user-view-preferences"],
)

# ---------------------------------------------------------------------------
# Guild-scoped routes: everything that resolves a single guild's data lives
# under /c/{community_id}. The guild is taken from the path (see
# deps.get_guild_membership); a guild-scoped router mounted outside this prefix
# fails at startup (missing path param) — a useful guard.
# ---------------------------------------------------------------------------
guild_router = APIRouter(prefix="/c/{community_id}")


def _tool_mount(tool: Tool) -> dict[str, Any]:
    """Where a tool's own router is mounted: under its route segment, with the
    OpenAPI tag its list is published under."""
    return {
        "prefix": f"/{tool.route_segment}",
        "tags": [TOOL_LISTS[tool].tag or tool.plural],
    }


guild_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
# Every tool's list, mounted once per Tool at each tool's own path, and the
# one sidebar-counts route beside them (see tenant_endpoints/tool_lists.py).
# The routes carry their own tags.
guild_router.include_router(tool_lists.router)
guild_router.include_router(projects.router, **_tool_mount(Tool.project))
guild_router.include_router(task_statuses.router, tags=["task-statuses"])
guild_router.include_router(task_statuses.initiative_router, tags=["task-statuses"])
guild_router.include_router(tool_views.router, tags=["views"])
guild_router.include_router(query.router, tags=["query"])
guild_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
# A community's own moderation: its reports, and settling them. No prefix —
# the reports of an initiative lead with the initiative, and settling one leads
# with the report. Who may read any of it is the tables' RLS, not a check here.
guild_router.include_router(moderation.router, tags=["moderation"])
# Files attached to a report or a case, opened for whoever may read the one
# they hang off.
guild_router.include_router(evidence.router, prefix="/evidence", tags=["evidence"])
guild_router.include_router(holds.router, prefix="/holds", tags=["holds"])
# Asking whoever runs the deployment for help. Guild-scoped because whether
# it is offered at all is the community's own setting.
guild_router.include_router(comments.router, prefix="/comments", tags=["comments"])
guild_router.include_router(reactions.router, prefix="/reactions", tags=["reactions"])
# Guild-scoped AI config (guild/user levels). Platform AI config is top-level.
guild_router.include_router(
    ai_settings.router, prefix="/settings", tags=["ai-settings"]
)
guild_router.include_router(
    initiatives.router, prefix="/initiatives", tags=["initiatives"]
)
guild_router.include_router(files.router, **_tool_mount(Tool.file))
guild_router.include_router(
    attachments.router, prefix="/attachments", tags=["attachments"]
)
guild_router.include_router(exports.router, prefix="/exports", tags=["exports"])
guild_router.include_router(demo.community_router, prefix="/demo", tags=["demo"])
guild_router.include_router(demo.sales_router, prefix="/demo", tags=["demo"])
guild_router.include_router(imports.router, prefix="/imports", tags=["imports"])
guild_router.include_router(queues.router, **_tool_mount(Tool.queue))
# Flat read-back routes, at the guild root: an event envelope names a
# resource by its own id, so every evented resource must resolve from one.
guild_router.include_router(queues.items_router, tags=_tool_mount(Tool.queue)["tags"])

guild_router.include_router(counters.router, **_tool_mount(Tool.counter_group))
guild_router.include_router(counters.counters_router, tags=["counters"])
guild_router.include_router(calendars.router, **_tool_mount(Tool.calendar))
guild_router.include_router(dashboards.router, **_tool_mount(Tool.dashboard))
guild_router.include_router(posts.router, **_tool_mount(Tool.post))
guild_router.include_router(galleries.router, **_tool_mount(Tool.gallery))
guild_router.include_router(wikis.router, **_tool_mount(Tool.wiki))
guild_router.include_router(wikis.pages_router, tags=_tool_mount(Tool.wiki)["tags"])
# Plug-ins installed at guild scope. Every member reads them (the sidebar needs to
# know what is there); installing and removing are guild-admin actions.
#
# The data plane is included FIRST so its literal ``/plugins/widget-catalog`` wins
# the match against ``/plugins/{plugin_id}`` below — the same ordering rule the
# dashboards router uses for its own widget catalog.
guild_router.include_router(plugin_data.router, prefix="/plugins", tags=["plugins"])
guild_router.include_router(guild_plugins.router, prefix="/plugins", tags=["plugins"])
# The same installs reached from inside one initiative. Its own router because
# the initiative leads the path: it is what the request is scoped to.
guild_router.include_router(guild_plugins.initiative_router, tags=["plugins"])
guild_router.include_router(
    calendar_events.router, prefix="/calendar-events", tags=["calendar-events"]
)
# Aggregate view: events + task markers in one request (calendar surfaces).
guild_router.include_router(
    calendar_entries.router, prefix="/calendar-entries", tags=["calendar-entries"]
)
# Reading the marketplace — the shelf and a listing's page. Guild-addressed
# because what a guild is offered depends on which plug-ins it has: a dashboard
# bundled with a plug-in appears only where that plug-in is installed. Maintaining
# the catalog stays platform-addressed (top-level /marketplace).
guild_router.include_router(
    guild_marketplace.router, prefix="/marketplace", tags=["marketplace"]
)
guild_router.include_router(
    resource_grants.router, prefix="/resource-grants", tags=["resource-grants"]
)
guild_router.include_router(storage.router, prefix="/storage", tags=["storage"])
guild_router.include_router(
    relationships.router, prefix="/relationships", tags=["relationships"]
)
guild_router.include_router(tags.router, prefix="/tags", tags=["tags"])
# Generic per-tool surfaces addressed by the Tool enum ({tool} path param).
guild_router.include_router(tools.router, prefix="/tools", tags=["tools"])
# Sharing: PUT /{tool}/{id}/grants, mounted once per Tool at each tool's own
# path. The routes carry their own tags (see tenant_endpoints/tool_grants.py),
# so none is added here.
guild_router.include_router(tool_grants.router)
# Deleting: DELETE /{tool}/{id}, the same way (tenant_endpoints/tool_lifecycle.py).
guild_router.include_router(tool_lifecycle.router)
guild_router.include_router(guild_search.router, prefix="/search", tags=["search"])
guild_router.include_router(
    smart_chips.router, prefix="/smart-chips", tags=["smart-chips"]
)
guild_router.include_router(
    property_definitions.router,
    prefix="/property-definitions",
    tags=["property-definitions"],
)
guild_router.include_router(
    property_values.router, prefix="/properties", tags=["properties"]
)
guild_router.include_router(trash.router, prefix="/trash", tags=["trash"])
# No prefix: the two routes are /archive/{kind}/{id} and /unarchive/{kind}/{id},
# one pair for every archivable kind (see tenant_endpoints/archive.py).
guild_router.include_router(archive.router, tags=["archive"])
# Guild member management (guild-admin). The signed-in account's own routes are
# under /me below; users.router keeps the routes about other people.
guild_router.include_router(users.guild_router, prefix="/users", tags=["users"])
guild_router.include_router(users.members_router, prefix="/members", tags=["users"])
# Recents: the addressed DELETE is guild-scoped (the cross-guild GET list stays
# top-level — fully separate endpoints, see recents.py).
guild_router.include_router(recents.guild_router, prefix="/recents", tags=["recents"])
# WebSockets (guild-scoped). Mounting under /c fixes the URL shape now; the
# handlers are rewired to read the path guild in a follow-up step.
guild_router.include_router(events.router, prefix="/events", tags=["events"])
guild_router.include_router(
    collaboration.router, prefix="/collaboration", tags=["collaboration"]
)
api_router.include_router(guild_router)

# ---------------------------------------------------------------------------
# Everything about the signed-in account: its profile and settings, and the
# cross-guild "my X" aggregates for the personal pages, which route per the
# user's member guilds. No guild context. Tagged per DOMAIN so Orval generates
# each hook into its existing domain file.
# ---------------------------------------------------------------------------
me_router = APIRouter(prefix="/me")
me_router.include_router(tasks.me_router, tags=["tasks"])
me_router.include_router(tickets.me_router, tags=["tickets"])
# The My Tools page: every tool's cross-guild list, mounted once per tool from
# MY_TOOL_LISTS, plus the tab counts. One tag, because they are one page rather
# than nine domains reaching across guilds for their own reasons.
me_router.include_router(me_tools.me_router, tags=["my-tools"])
me_router.include_router(calendar_entries.me_router, tags=["calendar-entries"])
me_router.include_router(me_trash.me_router, tags=["trash"])
me_router.include_router(me_ai.me_router, tags=["ai-settings"])
me_router.include_router(notification_prefs.me_router, tags=["notifications"])
me_router.include_router(contacts.me_router, tags=["contacts"])
me_router.include_router(
    dm.me_router, tags=["direct-messages"], dependencies=[DirectMessagesEnabledDep]
)
me_router.include_router(
    dm_transport.me_router,
    tags=["direct-messages"],
    dependencies=[DirectMessagesEnabledDep],
)
api_router.include_router(me_router)
# The account itself (GET/PATCH /me): mounted with its own prefix, since a
# router included without one cannot carry an empty path.
api_router.include_router(users.me_router, prefix="/me", tags=["users"])
api_router.include_router(held_changes.me_router, prefix="/me", tags=["users"])
