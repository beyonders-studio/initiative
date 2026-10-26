/**
 * Turning a bare entity id into the URL that addresses it.
 *
 * Every tool entity now lives inside its initiative — `/i/{initiative}/{tool}/{id}` —
 * so a link needs the whole chain, not just the id. Most callers already hold
 * the parent and should build the route directly with `lib/tools.ts`. A few
 * genuinely can't: a `@mention` is an id embedded in comment text, a queue
 * item's linked entity is a bare id, and a notification's target path was
 * written to the database before anyone knew where the entity would live.
 *
 * Those go through `/go/{refType}/{id}`, whose loader calls
 * {@link resolveEntityPath} and replaces itself with the real address. It costs
 * one read — on the way to a page that was going to read that entity anyway.
 */

import type { QueryClient } from "@tanstack/react-query";

import {
  getReadCalendarEventQueryKey,
  readCalendarEvent,
} from "@/api/generated/calendar-events/calendar-events";
import { getReadCalendarQueryKey, readCalendar } from "@/api/generated/calendars/calendars";
import {
  getReadCatalogItemQueryKey,
  getReadCatalogQueryKey,
  readCatalog,
  readCatalogItem,
} from "@/api/generated/catalogs/catalogs";
import { getReadCommentQueryKey, readComment } from "@/api/generated/comments/comments";
import { getReadCounterGroupQueryKey, readCounterGroup } from "@/api/generated/counters/counters";
import { getReadDashboardQueryKey, readDashboard } from "@/api/generated/dashboards/dashboards";
import { getReadFileQueryKey, readFile } from "@/api/generated/files/files";
import { SearchEntityType, Tool } from "@/api/generated/initiativeAPI.schemas";
import { getReadPostQueryKey, readPost } from "@/api/generated/posts/posts";
import { getReadProjectQueryKey, readProject } from "@/api/generated/projects/projects";
import {
  getReadQueueItemQueryKey,
  getReadQueueQueryKey,
  readQueue,
  readQueueItem,
} from "@/api/generated/queues/queues";
import { getReadTaskQueryKey, readTask } from "@/api/generated/tasks/tasks";
import {
  getReadWikiPageQueryKey,
  getReadWikiQueryKey,
  readWiki,
  readWikiPage,
} from "@/api/generated/wikis/wikis";
import {
  catalogItemRoute,
  eventRoute,
  initiativeRoute,
  type PARENT_TOOL,
  TOOLS,
  taskRoute,
  toolDetailRoute,
  toolKebabSingular,
  wikiPageRoute,
} from "@/lib/tools";

const STALE_TIME = 30_000;

/** Reads one row through the query cache, so the page the resolver lands on
 *  finds it already there. */
type Read = <T>(queryKey: readonly unknown[], queryFn: () => Promise<T>) => Promise<T>;

/** How each tool's row is read by its id. Keyed by the whole `Tool` enum, so a
 *  tool without a reader does not compile. */
const TOOL_READS: Record<
  Tool,
  {
    key: (communityId: number, id: number) => readonly unknown[];
    read: (communityId: number, id: number) => Promise<{ initiative_id?: number | null }>;
  }
> = {
  [Tool.project]: {
    key: getReadProjectQueryKey,
    read: readProject,
  },
  [Tool.file]: {
    key: getReadFileQueryKey,
    read: readFile,
  },
  [Tool.queue]: {
    key: getReadQueueQueryKey,
    read: readQueue,
  },
  [Tool.counter_group]: {
    key: getReadCounterGroupQueryKey,
    read: readCounterGroup,
  },
  [Tool.calendar]: {
    key: getReadCalendarQueryKey,
    read: readCalendar,
  },
  [Tool.dashboard]: {
    key: getReadDashboardQueryKey,
    read: readDashboard,
  },
  [Tool.post]: {
    key: getReadPostQueryKey,
    read: readPost,
  },
  [Tool.catalog]: {
    key: getReadCatalogQueryKey,
    read: readCatalog,
  },
  [Tool.wiki]: {
    key: getReadWikiQueryKey,
    read: readWiki,
  },
};

/** The initiative a tool row lives in. `null` is a community-level row (an
 *  plugin-installed calendar), which keeps a community address — not a failure. */
const toolInitiative = async (
  read: Read,
  communityId: number,
  tool: Tool,
  id: number
): Promise<number | null> => {
  const { key, read: readRow } = TOOL_READS[tool];
  return (await read(key(communityId, id), () => readRow(communityId, id))).initiative_id ?? null;
};

type Resolve = (read: Read, communityId: number, id: number) => Promise<string>;

/**
 * The kinds that live inside a tool and can be read by their own id, keyed by
 * the child-kind registry ({@link PARENT_TOOL}). A counter is read by id
 * (`/counters/{id}`), but nothing links to one yet. A queue item opens its
 * queue: a moderation case about one links to it.
 */
const CHILD_RESOLVERS: Partial<Record<keyof typeof PARENT_TOOL, Resolve>> = {
  task: async (read, communityId, id) => {
    const task = await read(getReadTaskQueryKey(communityId, id), () => readTask(communityId, id));
    // The embedded project summary usually names the initiative; when the
    // task read omits it, the project itself is the authority.
    const initiativeId =
      task.project?.initiative_id ??
      (await toolInitiative(read, communityId, Tool.project, task.project_id));
    return taskRoute(initiativeId, task.project_id, id);
  },
  calendar_event: async (read, communityId, id) => {
    const event = await read(getReadCalendarEventQueryKey(communityId, id), () =>
      readCalendarEvent(communityId, id)
    );
    return eventRoute(event.initiative_id, event.calendar_id, id);
  },
  queue_item: async (read, communityId, id) => {
    const item = await read(getReadQueueItemQueryKey(communityId, id), () =>
      readQueueItem(communityId, id)
    );
    return toolDetailRoute(
      Tool.queue,
      await toolInitiative(read, communityId, Tool.queue, item.queue_id),
      item.queue_id
    );
  },
  catalog_item: async (read, communityId, id) => {
    const item = await read(getReadCatalogItemQueryKey(communityId, id), () =>
      readCatalogItem(communityId, id)
    );
    const initiativeId = await toolInitiative(read, communityId, Tool.catalog, item.catalog_id);
    return catalogItemRoute(initiativeId, item.catalog_id, id);
  },
  wiki_page: async (read, communityId, id) => {
    const page = await read(getReadWikiPageQueryKey(communityId, id), () =>
      readWikiPage(communityId, id)
    );
    const initiativeId = await toolInitiative(read, communityId, Tool.wiki, page.wiki_id);
    return wikiPageRoute(initiativeId, page.wiki_id, id);
  },
};

/**
 * What `/go/{refType}/{id}` can resolve, by ref type: every tool and every
 * child kind above, each named by its kebab singular (`counter-group`,
 * `calendar-event`). Derived from the tool registry and the child kinds, so a
 * new tool is addressable here the day it exists.
 */
const RESOLVERS = new Map<string, Resolve>([
  ...TOOLS.map((tool): [string, Resolve] => [
    toolKebabSingular(tool),
    async (read, communityId, id) =>
      toolDetailRoute(tool, await toolInitiative(read, communityId, tool, id), id),
  ]),
  ...Object.entries(CHILD_RESOLVERS).map(([kind, resolve]): [string, Resolve] => [
    kind.replaceAll("_", "-"),
    resolve as Resolve,
  ]),
]);

/** Where a comment lives: the address of what it is on, landing on the comment
 *  itself (`#comment-{id}`, which the thread scrolls to). Whatever it is on is
 *  named by the one `{kind}_id` the comment carries. */
const resolveComment: Resolve = async (read, communityId, id) => {
  const comment = await read(getReadCommentQueryKey(communityId, id), () =>
    readComment(communityId, id)
  );
  for (const [kind, resolve] of RESOLVERS) {
    const parentId = (comment as unknown as Record<string, unknown>)[
      `${kind.replaceAll("-", "_")}_id`
    ];
    if (typeof parentId === "number") {
      return `${await resolve(read, communityId, parentId)}${commentAnchor(id)}`;
    }
  }
  throw new Error(`comment ${id} names nothing it is on`);
};
RESOLVERS.set("comment", resolveComment);

/** The fragment a link to one comment ends in. */
export const commentAnchor = (commentId: number): string => `#comment-${commentId}`;

/** The comment a location's fragment names, or `null`. */
export const linkedCommentId = (hash: string): number | null => {
  const match = /^#?comment-(\d+)$/.exec(hash);
  return match ? Number(match[1]) : null;
};

export const isEntityRefType = (value: string): boolean => RESOLVERS.has(value);

export const isSearchEntityType = (value: string): value is SearchEntityType =>
  Object.hasOwn(SearchEntityType, value);

/**
 * The ref type addressing an entity of a given kind — its kebab singular — or
 * `null` for a kind that has no address of its own (a counter, a queue item, a
 * tag).
 */
export const entityRefTypeFor = (type: SearchEntityType): string | null => {
  const kebab = type.replaceAll("_", "-");
  return isEntityRefType(kebab) ? kebab : null;
};

/**
 * The community-relative path an entity lives at, or `null` when it can't be
 * resolved — it was deleted, the reader can't see it, or its parent is gone.
 * Callers send `null` to the community home rather than guessing at an address.
 */
export async function resolveEntityPath(
  queryClient: QueryClient,
  communityId: number,
  refType: string,
  entityId: number
): Promise<string | null> {
  const resolve = RESOLVERS.get(refType);
  if (!Number.isFinite(entityId) || !resolve) return null;

  const read = <T>(queryKey: readonly unknown[], queryFn: () => Promise<T>) =>
    queryClient.ensureQueryData({ queryKey, queryFn, staleTime: STALE_TIME });

  try {
    return await resolve(read, communityId, entityId);
  } catch {
    // Deleted, or the reader can't see it. The caller lands on the community home.
    return null;
  }
}

/**
 * Rewrite a community-relative path written before tools were addressed inside
 * their initiative onto the `/go` resolver.
 *
 * Notification rows persist their `target_path`, so links minted by an older
 * build are still arriving. This is a data migration for those rows, not a
 * revival of the old routes — nothing renders at these paths any more.
 */
const LEGACY_TARGETS: Array<[RegExp, (id: string) => string]> = [
  [/^\/tasks\/(\d+)(\/.*)?$/, (id) => `/go/task/${id}`],
  [/^\/projects\/(\d+)(\/.*)?$/, (id) => `/go/project/${id}`],
  [/^\/files\/(\d+)(\/.*)?$/, (id) => `/go/file/${id}`],
  [/^\/calendar-events\/(\d+)(\/.*)?$/, (id) => `/go/calendar-event/${id}`],
  // A calendar event's ref type was `event` before every ref type became its
  // kind's kebab singular.
  [/^\/go\/event\/(\d+)$/, (id) => `/go/calendar-event/${id}`],
  [/^\/initiatives\/(\d+)(\/.*)?$/, (id) => initiativeRoute(Number(id))],
];

/** Community-relative paths that used to name a list page and no longer exist.
 *  (`/initiatives` among them: that list is part of the community home now.) */
const LEGACY_LISTS = new Set([
  "/initiatives",
  "/tasks",
  "/projects",
  "/files",
  "/queues",
  "/dashboards",
  "/counter-groups",
  "/calendars",
  "/calendar",
]);

/**
 * App-level (community-less) paths that a notification may still name.
 *
 * `/settings/profile` never existed as a route — your account lives under
 * `/profile`. Notification rows persist the path they were written with, so
 * the ones already sent have to be rewritten on the way out; the server no
 * longer mints it.
 */
const LEGACY_PLUGIN_TARGETS = new Map([
  ["/settings/profile", "/profile/account"],
  ["/settings/account", "/profile/account"],
]);

/** As {@link normalizeLegacyTarget}, for a path that names no community. */
export function normalizePluginTarget(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return LEGACY_PLUGIN_TARGETS.get(normalized) ?? normalized;
}

export function normalizeLegacyTarget(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  for (const [pattern, build] of LEGACY_TARGETS) {
    const match = normalized.match(pattern);
    if (match) return build(match[1]);
  }
  if (LEGACY_LISTS.has(normalized)) return "/";
  return normalized;
}
