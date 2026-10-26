/**
 * THE tool registry — the single human-readable place a tool is defined.
 *
 * The canonical tool set is the backend `Tool` enum (mirrored into the
 * generated types). Every derived name follows one rule set, so a tool's
 * entry here is just its icon:
 *
 *   value            "counter_group"          (the enum / resource_type)
 *   plural           "counter_groups"         → permission keys, member flags
 *   kebab plural     "counter-groups"         → route segment, API path
 *   camel plural     "counterGroups"          → i18n namespace, palette group
 *   camel singular   "counterGroup"           → route param name
 *   pascal singular  "CounterGroup"           → nav create-label key
 *
 * ## Adding a tool
 * 1. Backend: add the `Tool` enum member + wire the registries there
 *    (`app/core/tools.py` — its drift tests walk you through the rest).
 * 2. Regenerate types (`pnpm generate:api`).
 * 3. Add ONE entry to `TOOL_ICONS` below.
 * 4. Add the i18n namespace file + nav keys, the route files, and a data
 *    hook — `src/lib/tools.test.ts` fails with a list of exactly what is
 *    missing until every surface exists.
 *
 * There is deliberately NO per-tool capability matrix. Every tool is
 * recentable, taggable, shareable, has a command-palette group, and has a
 * settings page. A tool that genuinely differs is named in ONE exception set
 * below with its reason — the same way `app/core/tools.py` states these facts
 * — so a new tool gets every surface by default and an omission has to be
 * written down to happen.
 */

import type { ParseKeys } from "i18next";
import {
  BookText,
  CalendarDays,
  Files,
  GalleryHorizontalEnd,
  Gauge,
  Images,
  LayoutDashboard,
  ListTodo,
  type LucideIcon,
  Megaphone,
} from "lucide-react";

import type { InitiativeRead, PermissionKey } from "@/api/generated/initiativeAPI.schemas";
import { ListingKind, Tool } from "@/api/generated/initiativeAPI.schemas";

/**
 * The icon each tool renders with everywhere (sidebar, recents, palette,
 * settings). The one fact about a tool that cannot be derived from its name.
 */
export const TOOL_ICONS: Record<Tool, LucideIcon> = {
  [Tool.project]: ListTodo,
  [Tool.file]: Files,
  [Tool.queue]: GalleryHorizontalEnd,
  [Tool.counter_group]: Gauge,
  [Tool.calendar]: CalendarDays,
  [Tool.dashboard]: LayoutDashboard,
  [Tool.post]: Megaphone,
  [Tool.catalog]: Images,
  [Tool.wiki]: BookText,
};

/** Every tool, in canonical enum order. */
export const TOOLS = Object.values(Tool) as Tool[];

/**
 * On unless an initiative says otherwise. Mirrors backend
 * `DEFAULT_ENABLED_TOOLS`.
 *
 * Projects and files used to be exempt from the master switch entirely —
 * always on, with no `{plural}_enabled` column. Relationships ended that: a
 * tool no longer needs either of them to be linkable, so an initiative that is
 * only a calendar is a coherent thing to want. What they keep is the default,
 * which is the part that was ever load-bearing.
 */
export const DEFAULT_ENABLED_TOOLS: ReadonlySet<Tool> = new Set([Tool.project, Tool.file]);

/**
 * Tools WITHOUT an export-engine source, and why. Stated as an exclusion so
 * the default is "a new tool is portable" — mirrors backend
 * `NON_EXPORTABLE_TOOLS`. Export and import are ONE capability (a tool's JSON
 * envelope round-trips through both), so this set governs each.
 */
export const NON_EXPORTABLE_TOOLS: ReadonlySet<Tool> = new Set<Tool>([
  // Empty, and that is the point: every tool has an export source. What used
  // to sit here (Tool.dashboard) is now handled where it belongs — an entity
  // built on a plug-in this build does not ship is filtered by provenance on the
  // server, which is a property of the ROW, not of the tool.
]);

/** Tools with an export-engine source (single + bulk selection export), and
 *  equally the tools whose envelope can be imported. */
export const BULK_EXPORT_TOOLS = TOOLS.filter((t) => !NON_EXPORTABLE_TOOLS.has(t));

/**
 * Tools the marketplace has a shelf for, and the listing kind that carries
 * them. Stated as an inclusion — a tool has nothing to browse until the
 * catalog can hold its content — and as a map rather than a set so a browse
 * link addresses that tool's own shelf instead of the default one.
 *
 * The kinds mirror backend `LISTING_KINDS`. Not every kind belongs here: `plugin`
 * installs at community scope (the sidebar's plug-ins section and community settings own
 * that link), and `auto` names a vocabulary entry nothing installs yet.
 */
export const TOOL_LISTING_KINDS: Partial<Record<Tool, ListingKind>> = {
  [Tool.dashboard]: ListingKind.dashboard,
  [Tool.project]: ListingKind.project,
};

/** Which marketplace shelf a tool's list links to, or null when it has none. */
export const toolListingKind = (tool: Tool): ListingKind | null => TOOL_LISTING_KINDS[tool] ?? null;

/** The tool a listing of this kind installs into, or null when it is not a
 *  tool's listing (a plug-in, an automation, a profile pack). */
export const listingKindTool = (kind: ListingKind): Tool | null =>
  TOOLS.find((tool) => TOOL_LISTING_KINDS[tool] === kind) ?? null;

/** The slices a tool's list can show, in the order a page offers them. */
export const TOOL_VIEWS = ["active", "templates", "archived"] as const;

export type ToolView = (typeof TOOL_VIEWS)[number];

export const isToolView = (value: unknown): value is ToolView =>
  typeof value === "string" && (TOOL_VIEWS as readonly string[]).includes(value);

/** The list parameters that select a view. */
export interface ToolViewParams {
  archived?: true;
  is_template?: boolean;
}

type ToolViewSpec = Partial<Record<ToolView, ToolViewParams>>;

const DEFAULT_VIEWS: ToolViewSpec = { active: {}, archived: { archived: true } };

/** A tool with templates: its live rows without them, the templates on their
 *  own, and an archive holding both. */
const TEMPLATE_VIEWS: ToolViewSpec = {
  active: { is_template: false },
  templates: { is_template: true },
  archived: { archived: true },
};

/**
 * Each tool's views, as the list parameters that select them. Mirrors backend
 * `ToolListSpec.views`, which the counts endpoint counts by: every tool has
 * the live list and the archive, and the two with blueprints keep them in a
 * view of their own. Stated as the exceptions, so a new tool gets the two.
 */
const TOOL_VIEW_SPECS: Partial<Record<Tool, ToolViewSpec>> = {
  [Tool.project]: TEMPLATE_VIEWS,
  [Tool.file]: TEMPLATE_VIEWS,
};

/** The views a tool's list offers. */
export const toolViews = (tool: Tool): ToolView[] =>
  TOOL_VIEWS.filter((view) => view in (TOOL_VIEW_SPECS[tool] ?? DEFAULT_VIEWS));

/** What a tool's list endpoint is asked for to show `view`. Most tools' live
 *  view asks for nothing, which keeps its query key — and so its cache entry —
 *  the one every other caller of the list already uses. */
export const toolViewParams = (tool: Tool, view: ToolView): ToolViewParams =>
  (TOOL_VIEW_SPECS[tool] ?? DEFAULT_VIEWS)[view] ?? {};

/**
 * Sidebar display order within an initiative. Projects render last because the
 * initiative's project list expands directly beneath that row.
 */
export const SIDEBAR_TOOLS: Tool[] = [
  Tool.calendar,
  Tool.dashboard,
  Tool.file,
  Tool.catalog,
  Tool.post,
  Tool.queue,
  Tool.counter_group,
  Tool.wiki,
  Tool.project,
];

// ---------------------------------------------------------------------------
// Derived names — one rule each, no per-tool tables.
// ---------------------------------------------------------------------------

/**
 * "counter_group" → "counter_groups", "catalog" → "catalogs".
 *
 * One rule, mirrored from the backend's `Tool.plural`: a trailing `y` after a
 * consonant becomes `ies`, and everything else takes an `s`.
 */
export const toolPlural = (tool: Tool | ChildKind): string =>
  /[^aeiou]y$/.test(tool) ? `${tool.slice(0, -1)}ies` : `${tool}s`;

/**
 * Inverse of {@link toolPlural} for any table-ish plural the bus names —
 * "catalogs" → "catalog", "counter_groups" → "counter_group". The one
 * spelling rule, read backwards, so a resource type is never singularized by
 * chopping an `s` off.
 */
export const singularOf = (plural: string): string =>
  plural.endsWith("ies") ? `${plural.slice(0, -3)}y` : plural.replace(/s$/, "");

/** "counter_group" → "counter-groups" — route segment AND API path segment.
 *  A child kind's API path follows the same rule ("calendar_event" →
 *  "calendar-events"). */
export const toolRouteSegment = (tool: Tool | ChildKind): string =>
  toolPlural(tool).replaceAll("_", "-");

/** Inverse of {@link toolRouteSegment}: which tool a route segment names, or
 *  null for anything unrecognized. Lets a URL carry a readable tool selector. */
export const toolForRouteSegment = (segment: string): Tool | null =>
  TOOLS.find((tool) => toolRouteSegment(tool) === segment) ?? null;

/**
 * The tool entity a path is inside, e.g. "/c/1/i/2/projects/3/tasks/5" →
 * project 3. The OUTERMOST one wins: a task, a wiki's page, a file read
 * inside a wiki and a tool's settings all nest under their tool's id, so they
 * read as that tool. Null anywhere that is no tool's page.
 */
export const toolInPath = (pathname: string): { tool: Tool; id: number } | null => {
  const segments = pathname.split("/");
  for (let i = 0; i < segments.length - 1; i++) {
    const tool = toolForRouteSegment(segments[i]);
    const id = Number(segments[i + 1]);
    if (tool && /^\d+$/.test(segments[i + 1]) && id > 0) {
      return { tool, id };
    }
  }
  return null;
};

/** "counter_group" → "counterGroups" — i18n namespace, palette group key. */
export const toolCamelPlural = (tool: Tool): string =>
  toolPlural(tool).replace(/_(\w)/g, (_, c: string) => c.toUpperCase());

/** "counter_group" → "counterGroup" — the stem of the route param name. */
export const toolCamelSingular = (tool: Tool): string =>
  tool.replace(/_(\w)/g, (_, c: string) => c.toUpperCase());

/** "counter_group" → "CounterGroup" */
export const toolPascalSingular = (tool: Tool): string =>
  tool.replace(/(?:^|_)(\w)/g, (_, c: string) => c.toUpperCase());

/** "counter_group" → "CounterGroups", "catalog" → "Catalogs" — the stem of
 *  the per-tool permission label keys. */
export const toolPascalPlural = (tool: Tool): string =>
  toolPlural(tool).replace(/(?:^|_)(\w)/g, (_, c: string) => c.toUpperCase());

/** Resource-relative API path (WITHOUT the `/c/{communityId}` segment), e.g. "/api/v1/counter-groups".
 *  Callers must prepend `/api/v1/c/${communityId}` when building community-scoped requests. */
export const toolApiPath = (tool: Tool): string => `/api/v1/${toolRouteSegment(tool)}`;

// ---------------------------------------------------------------------------
// Routes — a tool entity's URL names the whole chain it belongs to:
// /c/{community}/i/{initiative}/{tool}/{id}. There is no community-wide tool list;
// My Tools is the cross-initiative browse surface, so a tool's "list" is one
// initiative's tab, or the community's own for a community-level entity. Every
// builder here returns a COMMUNITY-relative path — callers prepend the community prefix with `useCommunityPath`.
// ---------------------------------------------------------------------------

/** Community-relative initiatives list. */
export const INITIATIVES_ROUTE = "/i";

/** Community-relative route for one initiative, e.g. "/i/12". */
export const initiativeRoute = (initiativeId: number): string =>
  `${INITIATIVES_ROUTE}/${initiativeId}`;

/**
 * Community-relative list route for a tool inside one initiative — which is also
 * the initiative page with that tool's tab selected, e.g. "/i/12/counter-groups".
 *
 * `initiativeId === null` names a COMMUNITY-LEVEL entity. Calendars are the only
 * tool that has any (an plugin-installed calendar has no `initiative_id`), and
 * they keep their community routes. Treat `null` as "address me at the community
 * route", never as "initiative unknown".
 */
export const toolListRoute = (tool: Tool, initiativeId: number | null): string =>
  initiativeId === null
    ? `/${toolRouteSegment(tool)}`
    : `${initiativeRoute(initiativeId)}/${toolRouteSegment(tool)}`;

/** Community-relative detail route for one entity, e.g. "/i/12/counter-groups/3". */
export const toolDetailRoute = (tool: Tool, initiativeId: number | null, id: number): string =>
  `${toolListRoute(tool, initiativeId)}/${id}`;

/** Community-relative settings route, e.g. "/i/12/counter-groups/3/settings". */
export const toolSettingsRoute = (tool: Tool, initiativeId: number | null, id: number): string =>
  `${toolDetailRoute(tool, initiativeId, id)}/settings`;

/**
 * The sections every tool's settings page is divided into, in tab-bar order.
 * Each is a route of its own, so a section can be linked to and bookmarked and
 * the back button steps through the ones you visited.
 *
 * Details is served at `/settings` itself rather than at a `/settings/details`
 * alias — it is what the page opens on. A tool with a section of its own
 * (a project's task statuses) adds a route beside these; it does not need an
 * entry here.
 */
export const TOOL_SETTINGS_SECTIONS = ["details", "access", "advanced"] as const;

export type ToolSettingsSection = (typeof TOOL_SETTINGS_SECTIONS)[number];

/** The section a tool's settings open on, addressed as `/settings` itself. */
export const TOOL_SETTINGS_DEFAULT_SECTION: ToolSettingsSection = "details";

/** Community-relative route for one section of a tool's settings, e.g.
 *  "/i/12/counter-groups/3/settings/access". */
export const toolSettingsSectionRoute = (
  tool: Tool,
  initiativeId: number | null,
  id: number,
  section: string
): string => {
  const base = toolSettingsRoute(tool, initiativeId, id);
  return section === TOOL_SETTINGS_DEFAULT_SECTION ? base : `${base}/${section}`;
};

// --- The tools with a child entity -----------------------------------------
// Stated here once rather than left to each page: a task belongs to a project,
// an event to a calendar, a counter to its group, a page to its wiki, and each
// child nests under its parent so the URL reads end to end.

/** e.g. "/i/1/projects/2/tasks/5". */
export const taskRoute = (initiativeId: number | null, projectId: number, taskId: number): string =>
  `${toolDetailRoute(Tool.project, initiativeId, projectId)}/tasks/${taskId}`;

/** e.g. "/i/1/calendars/2/events/9". */
export const eventRoute = (
  initiativeId: number | null,
  calendarId: number,
  eventId: number
): string => `${toolDetailRoute(Tool.calendar, initiativeId, calendarId)}/events/${eventId}`;

/** e.g. "/i/1/counter-groups/3/counter/7". */
export const counterRoute = (
  initiativeId: number | null,
  groupId: number,
  counterId: number
): string => `${toolDetailRoute(Tool.counter_group, initiativeId, groupId)}/counter/${counterId}`;

/** e.g. "/i/1/wikis/4/pages/11". */
export const wikiPageRoute = (
  initiativeId: number | null,
  wikiId: number,
  pageId: number
): string => `${toolDetailRoute(Tool.wiki, initiativeId, wikiId)}/pages/${pageId}`;

/**
 * A file read inside the wiki it was put in, e.g.
 * "/i/12/wikis/3/files/8".
 *
 * Its own address stays what it always was — this one says "this file, as
 * a page of that wiki", which is what keeps the wiki's navigation standing
 * beside it.
 */
export const wikiFileRoute = (
  initiativeId: number | null,
  wikiId: number,
  fileId: number
): string => `${toolDetailRoute(Tool.wiki, initiativeId, wikiId)}/files/${fileId}`;

/**
 * Community-relative resolver route for an entity whose initiative isn't in hand,
 * e.g. "/go/file/42". The resolver reads the entity and replaces itself
 * with the canonical address.
 *
 * Use ONLY where the caller genuinely holds nothing but an id — a @mention, a
 * queue item's linked entity, a stored notification target. Anywhere the parent
 * is already loaded, build the real route: the resolver costs a round trip.
 */
export const entityRefRoute = (refType: string, id: number): string => `/go/${refType}/${id}`;

/** The router path param carrying a tool entity's id, e.g. "counterGroupId".
 *  Every tool's detail/settings route names its param this way, so the shared
 *  settings page reads the id without a per-tool lookup. */
export const toolParamName = (tool: Tool): string => `${toolCamelSingular(tool)}Id`;

/** "counter_group" → "counter-group". The KEBAB SINGULAR: envelope
 * discriminator and entity-ref segment. */
export const toolKebabSingular = (tool: Tool): string => tool.replaceAll("_", "-");

/** Export endpoint (relative to /c/{communityId}), e.g. "/exports/counter_group".
 * It takes the selection as `ids`. */
export const toolExportEndpoint = (tool: Tool): string => `/exports/${tool}`;

/**
 * The `{tool}_id` field that names one tool entity in a payload, e.g.
 * "counter_group_id".
 *
 * One spelling, two uses: the comment column a thread hangs off (backend
 * `_COMMENT_PARENTS`) and the id the realtime bus puts in a comment envelope.
 * They agree because they are this rule.
 */
export const toolIdParam = (tool: Tool): string => `${tool}_id`;

/** The envelope ``type`` discriminator a tool's single-entity export emits —
 * the same value its importer registers under: the kebab-singular. */
export const toolEnvelopeType = (tool: Tool): string => `initiative-${toolKebabSingular(tool)}`;

/** Inverse of {@link toolEnvelopeType}: which tool an envelope belongs to,
 * or null for an unknown/backup type. */
export const toolForEnvelopeType = (type: string): Tool | null =>
  BULK_EXPORT_TOOLS.find((tool) => toolEnvelopeType(tool) === type) ?? null;

/** nav.json label key, e.g. "counterGroups". Typed against the nav namespace
 * so `t(toolNavLabelKey(tool))` satisfies typed i18next — the drift test
 * asserts the key actually exists for every tool. */
export const toolNavLabelKey = (tool: Tool): ParseKeys<"nav"> =>
  toolCamelPlural(tool) as ParseKeys<"nav">;

/** nav.json create-label key, e.g. "createCounterGroup". */
export const toolCreateLabelKey = (tool: Tool): ParseKeys<"nav"> =>
  `create${toolPascalSingular(tool)}` as ParseKeys<"nav">;

/**
 * The forms of a kind's name (`common:kinds`) that wording about it is filled
 * in with: `{{kind}}` as a sentence starts with it, `{{thisKind}}` and
 * `{{kinds}}`. A kind is any addressable thing — a tool, or what lives in one
 * (mirrors backend `KINDS`) — and `messages_test` holds every locale to naming
 * each one.
 */
export const kindNames = (
  kind: string,
  t: (key: string) => string
): { kind: string; thisKind: string; kinds: string } => ({
  kind: t(`common:kinds.${kind}.name`),
  thisKind: t(`common:kinds.${kind}.this`),
  kinds: t(`common:kinds.${kind}.plural`),
});

/** Role permission key gating viewing, e.g. "counter_groups_enabled". */
export const toolViewPermission = (tool: Tool): PermissionKey =>
  `${toolPlural(tool)}_enabled` as PermissionKey;

/** Role permission key gating creation, e.g. "create_counter_groups". */
export const toolCreatePermission = (tool: Tool): PermissionKey =>
  `create_${toolPlural(tool)}` as PermissionKey;

/**
 * The shape every tool's read schema shares where comments are concerned: the
 * row's id, the initiative it lives in (null for a community-level entity), and its
 * own comment switch. `tools_test.py` holds every tool's model and read schema
 * to carrying `comments_enabled`, so a tool entity satisfies this by
 * construction — which is what lets one panel serve all of them.
 */
export interface ToolCommentEntity {
  id: number;
  initiative_id?: number | null;
  comments_enabled?: boolean;
}

/**
 * The shape a relations panel needs off a tool's read schema: the row's id and
 * the initiative it lives in. Deliberately the same two fields
 * {@link ToolCommentEntity} opens with, so a tool page hands the same object to
 * both panels.
 */
export interface ToolRelationEntity {
  id: number;
  initiative_id?: number | null;
}

/**
 * The tool an entity that is not one of its own is addressed inside.
 *
 * A link is cached against a TOOL, so writing one from a child has to refresh
 * the container's copy: a task's is its project, an event's its calendar, a
 * counter's its group. Exactly the non-tool entity kinds the search vocabulary
 * names, minus the two nothing links from — a comment, which no edge may name,
 * and a tag, which is picked with the tag picker.
 */
export const PARENT_TOOL = {
  task: Tool.project,
  calendar_event: Tool.calendar,
  counter: Tool.counter_group,
  catalog_item: Tool.catalog,
  queue_item: Tool.queue,
  wiki_page: Tool.wiki,
} as const satisfies Record<string, Tool>;

/** An entity kind a tool holds: a task, an event, a page. */
export type ChildKind = keyof typeof PARENT_TOOL;

/**
 * Tools whose detail page does NOT carry a relations panel, and why. Stated as
 * an exclusion, like {@link NON_EXPORTABLE_TOOLS}, so a tool is linkable on its
 * own page by default and leaving one out has to be written down.
 */
export const NO_RELATIONS_PANEL: ReadonlySet<Tool> = new Set<Tool>([
  // A wiki already draws its links: every page shows the pages it points at and
  // the ones pointing back, read out of the `[[ ]]` in its body. A second panel
  // beside that one would be two answers to "what is this connected to", and
  // the one that writes itself is the better answer for a wiki.
  Tool.wiki,
]);

/** Whether this tool's own detail page shows a relations panel. */
export const showsRelations = (tool: Tool): boolean => !NO_RELATIONS_PANEL.has(tool);

/**
 * Tools whose pages do NOT carry the activity drawer, and why. Stated as an
 * exclusion, like {@link NO_RELATIONS_PANEL}, so a tool's activity is beside it
 * by default and leaving one out has to be written down.
 */
export const NO_ACTIVITY_DRAWER: ReadonlySet<Tool> = new Set<Tool>([
  // A wiki's side of the page is its tree of pages, which is how it is read.
  Tool.wiki,
]);

/** Whether this tool's pages carry the activity drawer. */
export const showsActivity = (tool: Tool): boolean => !NO_ACTIVITY_DRAWER.has(tool);

/**
 * The initiative master-switch field for a tool (same spelling as the view
 * permission). Every tool has one.
 */
export const isToolEnabled = (tool: Tool, initiative: InitiativeRead): boolean =>
  Boolean(initiative[`${toolPlural(tool)}_enabled` as keyof InitiativeRead]);

/** Community-relative create target for a tool inside an initiative: the tool's
 *  own tab, with its create dialog open (`?create=true`). Callers prepend the
 *  community prefix (`useCommunityPath`). */
export const toolCreateTarget = (
  tool: Tool,
  initiativeId: number
): { to: string; search: Record<string, string> } => ({
  to: toolListRoute(tool, initiativeId),
  search: { create: "true" },
});
