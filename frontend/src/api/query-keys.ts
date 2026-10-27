/**
 * What a write made stale, described once and matched once.
 *
 * Orval keys queries by URL (e.g. `["/api/v1/tags/"]`), so a domain question
 * ("every task list") is a question about paths. The `q.*` builders answer it
 * as a **description** — a `Spec` naming paths, prefixes and thread ids — and
 * `invalidate()` merges however many of those it is handed and walks the cache
 * ONCE.
 *
 * That single walk is the point. A predicate filter makes React Query test
 * every cached query, so the old shape — one `invalidateQueries` per helper,
 * helpers called once per changed entity — cost a full pass per call. A
 * realtime batch of 300 comments came to 2,104 passes and 367ms of blocked
 * main thread; described and merged, it is one pass and under a millisecond,
 * and the cost stops growing with the size of the batch. Repeats collapse for
 * free: merging is into sets, so one list named by three hundred changes is one
 * entry.
 *
 * There are TWO disjoint families of keys, and a match MUST NOT cross between
 * them:
 *
 *  - COMMUNITY-scoped keys live under `/api/v1/c/{communityId}/...`. `communityExact` and
 *    `communityPrefix` reach these and ONLY for the ACTIVE community — never another
 *    community, and never a non-community key. This is the tenancy boundary: a mutation
 *    in one community can't touch another community's (or a personal) cached data.
 *  - PERSONAL / platform keys are everything else (`/api/v1/me/*`, `/settings`,
 *    `/users`, `/communities`, `/operator`, `/notifications`, `/version`, `/me/personal-items`).
 *    `personalExact` and `personalPrefix` reach these and ONLY these.
 *
 * A few resources genuinely span both (a community list plus its cross-community `/me`
 * aggregate; platform + community AI settings). Those name a bucket from each
 * family in one `Spec` — still two boundary-respecting tests, decided in one
 * place rather than blurred into one path test. The whole rule now lives in
 * `matches()` below, the only code in the app that decides whether a cached key
 * belongs to the current community.
 */
import { type PostRead, PropertyTarget, Tool } from "@/api/generated/initiativeAPI.schemas";
import { queryClient } from "@/lib/queryClient";
import { PARENT_TOOL, TOOLS, toolApiPath, toolRouteSegment } from "@/lib/tools";

// The active community is per-tab React state in `CommunityProvider`, mirrored here (a
// module var is per-JS-context, so it stays per-tab — unlike shared storage) so
// the community matchers can scope without every call site threading a community id.
let scopedCommunityId: number | null = null;

/** Mirror this tab's active community so community invalidation stays scoped to it. */
export const setInvalidationCommunity = (communityId: number | null) => {
  scopedCommunityId = communityId && communityId > 0 ? communityId : null;
};

const COMMUNITY_SEGMENT = /^\/api\/v1\/c\/(\d+)(\/.*)?$/;

// ── What a write made stale ──────────────────────────────────────────────────

/**
 * A description of cached queries — never an action on them.
 *
 * Every field is additive and optional, so specs merge by concatenation and a
 * builder names only the buckets it needs.
 */
export type Spec = {
  /** Community-relative paths matched whole: `/api/v1/tasks/7`. */
  communityExact?: readonly string[];
  /** Community-relative path prefixes: `/api/v1/tasks` reaches the lists under it. */
  communityPrefix?: readonly string[];
  /** Non-community paths matched whole: `/api/v1/version`. */
  personalExact?: readonly string[];
  /** Non-community path prefixes: `/api/v1/me/tasks`. */
  personalPrefix?: readonly string[];
  /**
   * Hand-written keys named by their first element and carrying their community in
   * the second (`["community-plugin", communityId, pluginId]`). Scoped to the active community by
   * that element, like every other community key.
   */
  communityNamed?: readonly string[];
  /** Hand-written keys matched by their first element alone (`["dm", …]`). */
  named?: readonly string[];
};

/** One or more specs, merged. Sets, so repeats cost nothing. */
type Matcher = {
  communityExact: Set<string>;
  communityPrefix: string[];
  personalExact: Set<string>;
  personalPrefix: string[];
  communityNamed: Set<string>;
  named: Set<string>;
};

const merge = (specs: readonly Spec[]): Matcher => {
  const matcher: Matcher = {
    communityExact: new Set(),
    communityPrefix: [],
    personalExact: new Set(),
    personalPrefix: [],
    communityNamed: new Set(),
    named: new Set(),
  };
  for (const spec of specs) {
    for (const path of spec.communityExact ?? []) matcher.communityExact.add(path);
    for (const path of spec.personalExact ?? []) matcher.personalExact.add(path);
    for (const name of spec.communityNamed ?? []) matcher.communityNamed.add(name);
    for (const name of spec.named ?? []) matcher.named.add(name);
    // Prefixes stay a list: there are only ever a handful, and each has to be
    // tested against the path rather than looked up.
    for (const prefix of spec.communityPrefix ?? []) {
      if (!matcher.communityPrefix.includes(prefix)) matcher.communityPrefix.push(prefix);
    }
    for (const prefix of spec.personalPrefix ?? []) {
      if (!matcher.personalPrefix.includes(prefix)) matcher.personalPrefix.push(prefix);
    }
  }
  return matcher;
};

/**
 * Whether one cached query is named by the merged description.
 *
 * The only place in the app that decides which family a key belongs to, and the
 * only place the active community is compared. A key addressing a community is answered
 * from the community buckets and never falls through to the personal ones — another
 * community's key matches nothing at all.
 */
const matches = (matcher: Matcher, queryKey: readonly unknown[]): boolean => {
  const first = queryKey[0];
  if (typeof first !== "string") return false;

  const community = COMMUNITY_SEGMENT.exec(first);
  if (community) {
    if (scopedCommunityId !== null && Number(community[1]) !== scopedCommunityId) return false;
    const path = `/api/v1${community[2] ?? ""}`;
    if (matcher.communityExact.has(path)) return true;
    for (const prefix of matcher.communityPrefix) {
      if (path.startsWith(prefix)) return true;
    }
    return false;
  }

  if (matcher.communityNamed.has(first)) {
    return scopedCommunityId === null || queryKey[1] === scopedCommunityId;
  }
  if (matcher.named.has(first)) return true;
  if (matcher.personalExact.has(first)) return true;
  for (const prefix of matcher.personalPrefix) {
    if (first.startsWith(prefix)) return true;
  }
  return false;
};

/**
 * Refresh everything the given specs name, in one pass over the cache.
 *
 * Hand it as many as the caller has — a mutation's two, a realtime batch's
 * three hundred. It is one walk either way.
 */
export const invalidate = (...specs: readonly Spec[]) => {
  const named = describes(...specs);
  return queryClient.invalidateQueries({ predicate: (query) => named(query.queryKey) });
};

/**
 * Whether a cached key is one the given specs name — for a caller that has to
 * leave one of them out, and cannot say so with `invalidate`.
 */
export const describes = (...specs: readonly Spec[]) => {
  const matcher = merge(specs);
  return (queryKey: readonly unknown[]) => matches(matcher, queryKey);
};

// ── Builders ─────────────────────────────────────────────────────────────────
// Pure descriptions, grouped under `q` so a call site reads
// `invalidate(q.allTasks(), q.task(id))`, and so adding one cannot collide with
// a local name in any of the fifty-odd files that invalidate something.

export const compose = (...specs: Spec[]): Spec => ({
  communityExact: specs.flatMap((spec) => spec.communityExact ?? []),
  communityPrefix: specs.flatMap((spec) => spec.communityPrefix ?? []),
  personalExact: specs.flatMap((spec) => spec.personalExact ?? []),
  personalPrefix: specs.flatMap((spec) => spec.personalPrefix ?? []),
  communityNamed: specs.flatMap((spec) => spec.communityNamed ?? []),
  named: specs.flatMap((spec) => spec.named ?? []),
});

/**
 * A resource's community-scoped list AND its cross-community "my" aggregate.
 *
 * The `/api/v1/me/<r>` read is personal, so a community prefix never reaches it and
 * it has to be named explicitly or the "my <resource>" list goes stale until
 * remount.
 */
const resourceAndMe = (resource: string): Spec => ({
  communityPrefix: [`/api/v1/${resource}`],
  personalPrefix: [`/api/v1/me/${resource}`],
});

// ── Announcements (platform) ─────────────────────────────────────────────────

/** Both the reader's queue and the authoring list — one write moves both. */
const announcements = (): Spec => ({ personalPrefix: ["/api/v1/announcements"] });

// ── Tags (community) ─────────────────────────────────────────────────────────────

const allTags = (): Spec => ({ communityPrefix: ["/api/v1/tags"] });

const tag = (tagId: number): Spec => ({ communityExact: [`/api/v1/tags/${tagId}`] });

const tagEntities = (tagId: number): Spec => ({
  communityExact: [`/api/v1/tags/${tagId}/entities`],
});

// ── Tasks (community + me) ───────────────────────────────────────────────────────

// Also names the calendar-entries aggregate (a derived events+tasks view), so a
// task mutation reflects on the calendar surfaces.
const allTasks = (): Spec => compose(resourceAndMe("tasks"), resourceAndMe("calendar-entries"));

const task = (taskId: number): Spec => ({ communityExact: [`/api/v1/tasks/${taskId}`] });

// ── Projects (community) ─────────────────────────────────────────────────────────

const projectTaskStatuses = (projectId: number): Spec => ({
  communityExact: [`/api/v1/projects/${projectId}/task-statuses/`],
});

const projectTaskTypes = (projectId: number): Spec => ({
  communityExact: [`/api/v1/projects/${projectId}/task-types/`],
});

// What the reader keeps about items: a community's stars and each item's
// state, and every community's tabs and stars (`/me/personal-items`).
// The activity feed, whose order follows what the reader subscribes to.
const activity = (): Spec => ({ communityPrefix: ["/api/v1/activity"] });

const personalItems = (): Spec => ({
  communityPrefix: ["/api/v1/personal-items"],
  personalExact: ["/api/v1/me/personal-items"],
});

// ── Files (community) ────────────────────────────────────────────────────────

/** Every read of the graph. One path serves them all, so one bucket does. */
const relationships = (): Spec => ({
  communityPrefix: ["/api/v1/relationships"],
});

const fileVersions = (fileId: number): Spec => ({
  communityExact: [`/api/v1/files/${fileId}/versions`],
});

// ── Comments (community) ─────────────────────────────────────────────────────────

const allComments = (): Spec => ({ communityPrefix: ["/api/v1/comments"] });

const recentComments = (): Spec => ({ communityPrefix: ["/api/v1/comments/recent"] });

// ── Notifications (personal) ─────────────────────────────────────────────────

const notifications = (): Spec => ({ personalPrefix: ["/api/v1/notifications"] });

// ── Contacts: who may reach you, and who you have agreed with ────────────────

/** The policy and its per-community toggles. */
const dmSettings = (): Spec => ({ personalExact: ["/api/v1/me/dm-settings"] });

/** Connections and message requests — one channel moves both. */
const contactGrants = (): Spec => ({
  personalPrefix: ["/api/v1/me/connections", "/api/v1/me/message-requests"],
});

/** The accounts this person has chosen not to hear from. */
const ignoredAccounts = (): Spec => ({ personalPrefix: ["/api/v1/me/ignored"] });

/** Everyone the reader may reach: the community sections. */
const contacts = (): Spec => ({ personalPrefix: ["/api/v1/me/contacts"] });

/**
 * The direct-message mailbox.
 *
 * Keyed on `["dm", …]` rather than a path, because a thread is read out of this
 * device's own store rather than from an endpoint — the server deletes a
 * message once it has been collected.
 */
const directMessages = (): Spec => ({ named: ["dm"] });

// ── Initiatives (community) ──────────────────────────────────────────────────────

const allInitiatives = (): Spec => ({ communityPrefix: ["/api/v1/initiatives"] });

const initiative = (initiativeId: number): Spec => ({
  communityExact: [`/api/v1/initiatives/${initiativeId}`],
});

const initiativeRoles = (initiativeId: number): Spec => ({
  communityExact: [`/api/v1/initiatives/${initiativeId}/roles`],
});

const initiativeMembers = (initiativeId: number): Spec => ({
  communityExact: [`/api/v1/initiatives/${initiativeId}/members`],
});

// One prefix reaches every reader of the queue: the manager's list (keyed with
// its `status` filter), the requester's own `/me` rows, and any narrower status
// view — so a request or an answer never leaves one of them showing the old
// truth. The directory's own badge rides on `allInitiatives`.
const initiativeJoinRequests = (initiativeId: number): Spec => ({
  communityPrefix: [`/api/v1/initiatives/${initiativeId}/join-requests`],
});

// ── Settings (personal / platform) ───────────────────────────────────────────

// "All settings" is a blunt flush spanning two DELIBERATELY separate backend
// scopes: app/platform config (`/api/v1/settings/*`, owner-only) and a community's
// AI settings (`/api/v1/c/{id}/settings/ai/*`, RLS-scoped). They live on
// different paths by design — app config isn't community-specific, and community AI
// settings must carry community context — so name a bucket in each family rather
// than let one path test cross the boundary. (Not a backend inconsistency.)
const allSettings = (): Spec => ({
  personalPrefix: ["/api/v1/settings"],
  communityPrefix: ["/api/v1/settings"],
});

const emailSettings = (): Spec => ({ personalExact: ["/api/v1/settings/email"] });

const authSettings = (): Spec => ({ personalExact: ["/api/v1/settings/auth"] });

const authProviders = (): Spec => ({ personalExact: ["/api/v1/settings/auth/providers/"] });

/** What one community says its own arrivals look like, and who has agreed. */
const communityNarrowings = (communityId: number): Spec => ({
  personalExact: [`/api/v1/settings/communities/${communityId}/narrowings`],
});

const storageSettings = (): Spec => ({ personalExact: ["/api/v1/settings/storage"] });

/** The registration captcha: provider, site key, and whether a secret is stored. */
const captchaSettings = (): Spec => ({ personalExact: ["/api/v1/settings/captcha"] });

/** The Firebase connection push notifications are sent through. */
const pushSettings = (): Spec => ({ personalExact: ["/api/v1/settings/push"] });

// The public half of the Firebase connection, which the app reads to register
// for push. An owner's write to the push settings changes what it answers.
const fcmConfig = (): Spec => ({ personalExact: ["/api/v1/settings/fcm-config"] });

// The community-directory switch is written under /settings but read from the
// SPA's boot config, so an owner's write has to reach the config key rather
// than a settings one.
const appConfig = (): Spec => ({ personalExact: ["/api/v1/config"] });

/** The owner's own read of the three community-wide decisions. */
const communitySettings = (): Spec => ({ personalExact: ["/api/v1/settings/community"] });

/** Where sign-in is configured, which ways in are permitted, and the counts a
 *  change to either would turn on. */
const platformAuthSettings = (): Spec => ({
  personalExact: ["/api/v1/settings/auth/platform"],
});

/** What this deployment permits a notification to leave the app carrying. */
const notificationSettings = (): Spec => ({
  personalExact: ["/api/v1/settings/notifications"],
});

/** Where each stream of operations work lands, and what it could land in. */
const intakeSettings = (): Spec => ({ personalExact: ["/api/v1/settings/intake"] });

const intakeOptions = (): Spec => ({ personalExact: ["/api/v1/settings/intake/options"] });

/** What each kind of ticket offers the reader. Moves with the intake settings
 *  and with a community's help-request switch. */
const ticketAvailability = (): Spec => ({
  personalExact: ["/api/v1/me/tickets/availability"],
});

/** The tickets the reader filed. Moves when they file or answer one. */
const filedTickets = (): Spec => ({
  personalExact: ["/api/v1/me/tickets"],
});

/** One initiative's moderation reports. A prefix, so the open list and the
 *  settled one — which differ only in their params — both move on a write. */
const moderationReports = (initiativeId: number): Spec => ({
  communityPrefix: [`/api/v1/initiatives/${initiativeId}/reports`],
});

// The platform Communities tab reads/writes only shared public tables (owner-only),
// so its list lives in the personal/platform family, not under any /c/ key.
const platformCommunities = (): Spec => ({ personalExact: ["/api/v1/settings/communities"] });

// ── Plug-in services (personal / platform) ──────────────────────────────────
// Orval keys the list as `/api/v1/plugin-services/` (trailing slash) and each row
// as `/api/v1/plugin-services/{id}` (no slash), so they are siblings rather than a
// prefix pair. Name the shared path so one description reaches the list and
// every detail read.
const pluginServices = (): Spec => ({ personalPrefix: ["/api/v1/plugin-services"] });

// ── Installed plug-ins (community) ──────────────────────────────────────────────
// The other half of the same domain: a service is the platform's registration
// of a plug-in, an install is one community's copy of it.
//
// One description for every read of an install, because one write moves all of
// them — the sidebar's list, the settings dialog's detail, the members view —
// and because the bus names the install community-wide, with no parent to carry it.
// Two key shapes: the list is Orval's URL key, while the detail and members
// reads are hand-written and keyed by name. The named pair carries its community in
// element 1, so it is scoped like every other community key rather than by name.
const plugins = (): Spec => ({
  communityPrefix: ["/api/v1/plugins"],
  communityNamed: ["community-plugin", "community-plugin-members"],
});

// ── AI Settings (platform config is personal; community/resolved are community) ──

const allAISettings = (): Spec => ({
  personalPrefix: ["/api/v1/settings/ai"],
  communityPrefix: ["/api/v1/settings/ai"],
});

/** The platform owner's global mode. */
const platformAIMode = (): Spec => ({ personalExact: ["/api/v1/settings/ai/platform/mode"] });

/** The operator-defined connections list. */
const platformAIConnections = (): Spec => ({
  personalExact: ["/api/v1/settings/ai/platform/connections"],
});

/** A community admin's own connections list (`/c/{id}/settings/ai/connections`). */
const communityAIConnections = (): Spec => ({
  communityExact: ["/api/v1/settings/ai/connections"],
});

const resolvedAISettings = (): Spec => ({ communityExact: ["/api/v1/settings/ai/resolved"] });

// ── Users / Operator (personal / platform) ──────────────────────────────────────

const currentUser = (): Spec => ({ personalExact: ["/api/v1/me"] });

const userStats = (): Spec => ({ personalPrefix: ["/api/v1/me/stats"] });

const operatorUsers = (): Spec => ({ personalPrefix: ["/api/v1/operator"] });

// ── Community Members (community) ────────────────────────────────────────────────────
// The member roster is community-scoped (`/api/v1/c/{id}/users/`), even though the
// membership *mutations* go through the platform `/api/v1/communities/{id}/members/…`
// path. It must stay in the community bucket. The member search rides along: the
// pickers read each person's community role from it. So does the sidebar's people
// roster.

const communityMembers = (): Spec => ({
  communityExact: ["/api/v1/users/", "/api/v1/users/search", "/api/v1/users/roster"],
});

// ── Communities (personal / platform) ─────────────────────────────────────────────

const allCommunities = (): Spec => ({ personalPrefix: ["/api/v1/communities"] });

const communityInvites = (communityId: number): Spec => ({
  personalExact: [`/api/v1/communities/${communityId}/invites`],
});

// ── Calendar Events (community + me) ─────────────────────────────────────────────

// The calendar-entries aggregate unions events + task markers; name it too so
// event mutations reflect on the calendar surfaces.
const allCalendarEntries = (): Spec => resourceAndMe("calendar-entries");

const allCalendarEvents = (): Spec =>
  compose({ communityPrefix: ["/api/v1/calendar-events"] }, allCalendarEntries());

const calendarEvent = (eventId: number): Spec => ({
  communityExact: [`/api/v1/calendar-events/${eventId}`],
});

/** Access requests: where the reader stands on each thing, and the requests
 *  waiting on their answer. Asking or answering moves both. */
const shareRequests = (): Spec => ({ communityPrefix: ["/api/v1/share-requests"] });

/** Files' collections: every list of them and each one's own read and files.
 *  What is in one shows on its card (a count, a cover) and in its list. */
const allCollections = (): Spec => ({ communityPrefix: ["/api/v1/collections"] });

/** One collection's own read and its files. The trailing slash keeps
 *  collection 1 from reaching collection 10. */
const collection = (id: number): Spec => ({
  communityExact: [`/api/v1/collections/${id}`],
  communityPrefix: [`/api/v1/collections/${id}/`],
});

const counter = (counterId: number): Spec => ({
  communityExact: [`/api/v1/counters/${counterId}`],
});

const queueItem = (itemId: number): Spec => ({
  communityExact: [`/api/v1/queue-items/${itemId}`],
});

// ── Posts (community) ────────────────────────────────────────────────────────────

/**
 * The board's timeline rail only.
 *
 * Read state is patched into the post caches rather than refetched, because
 * refetching the feed mid-scroll moves rows under the cursor. The rail is a
 * separate, cheap aggregate — and with the unread filter on it is *made of*
 * read state, so leaving it alone would show months that have since emptied.
 * This names that one query and nothing else.
 */
const postTimeline = (): Spec => ({ communityPrefix: ["/api/v1/posts/timeline"] });

// ── Wikis (community) ────────────────────────────────────────────────────────────

/** A wiki's pages — the tree and each page's own read — without the wiki row
 *  itself. A page is read by its own id (`/wiki-pages/{id}`), which names no
 *  wiki, so every page read goes too. */
const wikiPages = (wikiId: number): Spec => ({
  communityPrefix: [`/api/v1/wikis/${wikiId}/pages`, "/api/v1/wiki-pages"],
});

/** One page's own read. */
const wikiPage = (pageId: number): Spec => ({ communityExact: [`/api/v1/wiki-pages/${pageId}`] });

// ── References (community) ───────────────────────────────────────────────────

/** Every chip, link and embed answer about one thing. `useSmartChips` keeps
 *  them at the thing's address, so a change to it names them all. */
const references = (kind: string, id: number): Spec => ({
  communityExact: [`/api/v1/smart-chips/${kind}/${id}`, `/api/v1/smart-chips/embeds/${kind}/${id}`],
});

/** Every chip and embed answer, or every one about a kind of thing. */
const allReferences = (kind?: string): Spec => ({
  communityPrefix: kind
    ? [`/api/v1/smart-chips/${kind}/`, `/api/v1/smart-chips/embeds/${kind}/`]
    : ["/api/v1/smart-chips/"],
});

// ── Layouts (community) ──────────────────────────────────────────────────────

/** An initiative's list of its tools' layouts, for its settings. */
const initiativeLayouts = (): Spec => ({ communityExact: ["/api/v1/layouts/initiative"] });

/** How full each limited board column is, which a board's limits change. */
const columnLimits = (): Spec => ({ communityExact: ["/api/v1/tasks/column-limits"] });

/** Every set of layouts (one path serves them all, its target in the params),
 *  and the initiatives' lists of them. */
const layouts = (): Spec => compose({ communityExact: ["/api/v1/layouts/"] }, initiativeLayouts());

// ── Version (personal) ───────────────────────────────────────────────────────

const version = (): Spec => ({ personalExact: ["/api/v1/version"] });

const latestVersion = (): Spec => ({ personalExact: ["/api/v1/version/latest"] });

// ── Properties (community) ───────────────────────────────────────────────────────

const allProperties = (): Spec => ({ communityPrefix: ["/api/v1/property-definitions"] });

// ── Tools (community + me) ───────────────────────────────────────────────────────
// Every tool is cached the same way, so its keys are one rule over the `Tool`
// enum rather than a table per tool: a new member is covered the day it lands.

/** The sidebar's per-initiative counts, one query for every tool. */
const toolCounts = (): Spec => ({ communityExact: ["/api/v1/tools/counts/by-initiative"] });

/**
 * Every list of one tool — its community-wide list and the cross-community `/me` twin
 * every tool has — and its page's counts, whose tag tree moves when a row's
 * tags do. A calendar's also reaches the events and entries views, which show
 * its name and colour, and a project's or post's the entries, which show their
 * dates. Not the sidebar's counts: changing what a row says
 * leaves those where they were.
 */
const toolLists = (which: Tool): Spec => {
  const lists = compose(resourceAndMe(toolRouteSegment(which)), {
    communityPrefix: [`/api/v1/tools/${which}/counts`],
  });
  if (which === Tool.calendar) return compose(lists, allCalendarEvents());
  // An initiative's list of layouts names its projects, queues and counter
  // groups, by name. The entries carry projects by their dates and posts by their
  // polls' closing.
  if (which === Tool.project) return compose(lists, initiativeLayouts(), allCalendarEntries());
  if (which === Tool.queue || which === Tool.counter_group) {
    return compose(lists, initiativeLayouts());
  }
  if (which === Tool.post) return compose(lists, allCalendarEntries());
  return lists;
};

/** Every list of one tool and the counts beside them — what adding or
 *  removing one makes stale. */
const toolList = (which: Tool): Spec => compose(toolLists(which), toolCounts());

/** One tool entity's own read. */
const toolEntity = (which: Tool, id: number): Spec => ({
  communityExact: [`${toolApiPath(which)}/${id}`],
});

/**
 * One tool entity's own read and every read under its address — a wiki's
 * pages, a project's activity and statuses. What a change
 * inside it makes stale. The trailing slash keeps project 1 from reaching
 * project 10.
 */
const toolSubtree = (which: Tool, id: number): Spec => ({
  communityExact: [`${toolApiPath(which)}/${id}`],
  communityPrefix: [`${toolApiPath(which)}/${id}/`],
});

/** One entity and every list it sits in — what a generic per-tool write makes stale. */
const tool = (which: Tool, id: number): Spec => compose(toolEntity(which, id), toolList(which));

// The same two, by name, for the call sites that already know their tool.
const allProjects = (): Spec => toolList(Tool.project);
const project = (id: number): Spec => toolEntity(Tool.project, id);
// A file shows in the collections it is in (their rows, covers and counts),
// so a change to one refreshes them too.
const allFiles = (): Spec => compose(toolList(Tool.file), allCollections());
const file = (id: number): Spec => compose(toolEntity(Tool.file, id), allCollections());
const allQueues = (): Spec => toolList(Tool.queue);
const allCounterGroups = (): Spec => toolList(Tool.counter_group);
const counterGroup = (id: number): Spec => toolEntity(Tool.counter_group, id);
const allCalendars = (): Spec => toolList(Tool.calendar);
const calendar = (id: number): Spec => toolEntity(Tool.calendar, id);
const allDashboards = (): Spec => toolList(Tool.dashboard);
const dashboard = (id: number): Spec => toolEntity(Tool.dashboard, id);
const allPosts = (): Spec => toolList(Tool.post);
const post = (id: number): Spec => toolEntity(Tool.post, id);
const allWikis = (): Spec => toolList(Tool.wiki);
const wiki = (id: number): Spec => toolEntity(Tool.wiki, id);

// ── Property values (community) ──────────────────────────────────────────────────

/**
 * Every read that shows one kind of row's property values: the kind's own
 * reads, and for a row a tool holds, the tool's, whose pages show its rows. A
 * task also shows in the calendar's entries, which `allTasks` names.
 */
const propertyHolder = (target: PropertyTarget): Spec => {
  const own = target === PropertyTarget.task ? allTasks() : resourceAndMe(toolRouteSegment(target));
  const parent: Tool | undefined = (PARENT_TOOL as Partial<Record<PropertyTarget, Tool>>)[target];
  return parent ? compose(own, toolLists(parent)) : own;
};

/** Every row that can carry property values — what a definition's change reaches. */
const allPropertyHolders = (): Spec =>
  compose(...Object.values(PropertyTarget).map(propertyHolder));

// ── Everything this community shows (cross-tool) ─────────────────────────────────
// Two callers, one description. Gaining (or losing) a membership row changes
// what the community returns for every tool, not just the initiative list: the
// sidebar tree, the discovery directory, and each tool's community-wide list all
// read differently afterwards. And a realtime frame for a write too large to
// name its rows one by one says so instead, and this is the answer.

const communityContent = (): Spec =>
  compose(
    allInitiatives(),
    ...TOOLS.map(toolList),
    allCollections(),
    allTasks(),
    allComments(),
    allReferences()
  );

/** Every description, by name. The only export a call site needs beside `invalidate`. */
export const q = {
  allAISettings,
  allCalendarEntries,
  allCalendarEvents,
  allCalendars,
  allComments,
  allCounterGroups,
  allDashboards,
  allFiles,
  allCollections,
  allCommunities,
  allInitiatives,
  allPosts,
  allProjects,
  allProperties,
  allPropertyHolders,
  allReferences,
  allQueues,
  allSettings,
  allTags,
  allWikis,
  allTasks,
  announcements,
  appConfig,
  pluginServices,
  plugins,
  references,
  authProviders,
  communityNarrowings,
  authSettings,
  calendar,
  captchaSettings,
  calendarEvent,
  queueItem,
  counter,
  communitySettings,
  notificationSettings,
  platformAuthSettings,
  intakeOptions,
  intakeSettings,
  ticketAvailability,
  filedTickets,
  moderationReports,
  contactGrants,
  contacts,
  counterGroup,
  currentUser,
  dashboard,
  directMessages,
  dmSettings,
  file,
  fileVersions,
  emailSettings,
  personalItems,
  activity,
  fcmConfig,
  communityAIConnections,
  communityContent,
  communityInvites,
  communityMembers,
  ignoredAccounts,
  initiative,
  initiativeJoinRequests,
  initiativeMembers,
  initiativeRoles,
  latestVersion,
  notifications,
  operatorUsers,
  platformAIConnections,
  platformAIMode,
  platformCommunities,
  collection,
  post,
  postTimeline,
  project,
  projectTaskStatuses,
  projectTaskTypes,
  propertyHolder,
  pushSettings,
  recentComments,
  relationships,
  resolvedAISettings,
  shareRequests,
  storageSettings,
  tag,
  tagEntities,
  task,
  tool,
  toolList,
  toolLists,
  toolSubtree,
  userStats,
  version,
  initiativeLayouts,
  columnLimits,
  layouts,
  wiki,
  wikiPage,
  wikiPages,
};

// ── Community Switch ─────────────────────────────────────────────────────────────

/**
 * Drop the departing community's cached data on a community switch.
 *
 * Only keys that address a community (`/api/v1/c/{communityId}/…`) are reset, and not
 * the arriving community's own: those hold its data, not the departing community's.
 * Online that changes nothing observable — they are stale on mount and refetch
 * anyway — but it is the difference between a cached page and an empty one
 * when the device has no connection to refetch from.
 *
 * Everything else survives. A platform or personal path (`/me/*`, `/users`,
 * `/communities`, `/me/personal-items`) answers the same in every community, and a
 * hand-written key that holds community data (`["query", communityId, …]`) carries the
 * community's id, so another community's entry is never the one read.
 */
export const resetCommunityScopedQueries = (arrivingCommunityId?: number | null) =>
  queryClient.resetQueries({
    predicate: (query) => {
      const first = query.queryKey[0];
      if (typeof first !== "string") return false;
      const match = COMMUNITY_SEGMENT.exec(first);
      return match !== null && Number(match[1]) !== arrivingCommunityId;
    },
  });

// ── Rewriting a cached post in place (not an invalidation) ───────────────────

type CachedPage = { items?: PostRead[] };

/**
 * One page of posts, with this post rewritten. Returns the SAME object when
 * the page does not hold it, so the caches that do not change keep their
 * identity and the cards on them do not re-render.
 */
const patchPostPage = (
  page: unknown,
  postId: number,
  update: (post: PostRead) => PostRead
): unknown => {
  const asList = page as CachedPage;
  if (!Array.isArray(asList.items)) return page;
  if (!asList.items.some((item) => item.id === postId)) return page;
  return {
    ...asList,
    items: asList.items.map((item) => (item.id === postId ? update(item) : item)),
  };
};

/**
 * Rewrite one post wherever it is already cached, without refetching.
 *
 * Read state changes as somebody scrolls, and invalidating for it would refetch
 * the board mid-scroll — moving rows under the cursor, and with the unread
 * filter on, deleting the one being read. The server is already told; this is
 * only the copy on screen catching up.
 *
 * Three shapes hold a post, and the board is the one that is easy to miss: it
 * scrolls rather than pages, so its cache is an infinite query's
 * `{ pages: [...] }` rather than a single page of items. Patching only the
 * other two would leave every optimistic update invisible on the surface it
 * was made from.
 */
export const patchCachedPost = (postId: number, update: (post: PostRead) => PostRead) => {
  const matcher = merge([allPosts()]);
  queryClient.setQueriesData<unknown>(
    { predicate: (query) => matches(matcher, query.queryKey) },
    (data: unknown) => {
      if (!data || typeof data !== "object") return data;

      const asInfinite = data as { pages?: unknown[] };
      if (Array.isArray(asInfinite.pages)) {
        const pages = asInfinite.pages.map((page) => patchPostPage(page, postId, update));
        if (pages.every((page, index) => page === asInfinite.pages?.[index])) return data;
        return { ...asInfinite, pages };
      }

      const patched = patchPostPage(data, postId, update);
      if (patched !== data) return patched;

      const asPost = data as PostRead;
      return asPost.id === postId ? update(asPost) : data;
    }
  );
};
