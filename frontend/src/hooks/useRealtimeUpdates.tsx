import { useParams } from "@tanstack/react-router";
import { useEffect } from "react";

import { getAuthToken } from "@/api/client";
import type { DashboardDataResponse } from "@/api/generated/initiativeAPI.schemas";
import { readMe } from "@/api/generated/users/users";
import { compose, invalidate, q, type Spec } from "@/api/query-keys";
import { syncComments } from "@/hooks/useComments";
import { canvasIsStale, dashboardDataKey } from "@/hooks/useSqlQuery";
import { openLiveSocket } from "@/lib/liveSocket";
import { queryClient } from "@/lib/queryClient";
import { singularOf, TOOLS, toolPlural } from "@/lib/tools";
import { buildCommunityWsUrl } from "@/lib/wsUrl";

import { useAuth } from "./useAuth";

const buildWebsocketUrl = (communityId: number) => {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    // Token is sent via MSG_AUTH message, not URL params
    return buildCommunityWsUrl(communityId, "events/updates");
  } catch {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.host}/api/v1/c/${communityId}/events/updates`;
  }
};

/** One thing the bus can name: what changed, or something it sits inside. */
export type ResourceRef = { type: string; id: number };

/** One change off the wire. Identifiers only — never a serialized model. */
export type RealtimeChange = {
  resource?: ResourceRef;
  parents?: ResourceRef[];
  /** The initiative the change is in, or null for the community's own. */
  initiative_id?: number | null;
  action?: string;
  /** The columns an update touched, by name. Empty on create and delete. */
  changed?: string[];
};

/**
 * A burst of frames costs one round of invalidation rather than one per frame.
 * The server already batches a transaction into a single frame, so this only
 * has to cover separate writes landing together — somebody dragging cards, an
 * import committing in chunks.
 */
const FRAME_DEBOUNCE_MS = 250;

/**
 * The columns whose update moves a tool row onto or off a count: which
 * initiative it is in, whether it is archived or a template, and who it is
 * shared with. Any other update leaves every count where it was.
 */
const COUNTED_COLUMNS = new Set(["initiative_id", "archived_at", "is_template", "sharing"]);

/** Whether a change can move the counts: a row arriving or leaving, or an
 *  update to one of the columns above. */
const recounts = (change: RealtimeChange) =>
  change.action !== "updated" ||
  (change.changed ?? []).some((column) => COUNTED_COLUMNS.has(column));

/**
 * What a change to one kind of resource makes stale — as a description, not an
 * action. `recount` says whether the change can have moved the counts.
 *
 * Tools come from the registry, so a new tool's events are live the day it
 * ships. The rest are the things the bus can name that are not a tool of their
 * own. A type nothing here claims is ignored on purpose: its parents carry the
 * surfaces that matter.
 */
const RESOURCE_SPECS: Record<string, (id: number, recount: boolean) => Spec[]> = {
  ...Object.fromEntries(
    TOOLS.map((tool) => [
      toolPlural(tool),
      (id: number, recount: boolean) => [
        q.toolSubtree(tool, id),
        recount ? q.toolList(tool) : q.toolLists(tool),
      ],
    ])
  ),
  tasks: (id) => [q.task(id), q.allTasks()],
  // The community's recent-activity list is a comment feed of its own. Which thread
  // moved is a question about the parent, below.
  comments: () => [q.recentComments()],
  calendar_events: (id) => [q.calendarEvent(id), q.allCalendarEvents()],
  // Their own reads, which an opened item shows; the tool is named as parent.
  queue_items: (id) => [q.queueItem(id)],
  counters: (id) => [q.counter(id)],
  // The wiki it is in is named as its parent, which refreshes the tree.
  wiki_pages: (id) => [q.wikiPage(id)],
  // The library it is in is named as its parent, which refreshes the list.
  library_items: (id) => [q.libraryItem(id)],
  // An initiative's roster, its roles, what those roles permit and its
  // property definitions all report against the initiative itself — none of
  // those rows has a route of its own — so "the initiative changed" has to
  // name them all.
  initiatives: (id) => [
    q.initiative(id),
    q.allInitiatives(),
    q.initiativeMembers(id),
    q.initiativeRoles(id),
    q.allProperties(),
  ],
  tags: (id) => [q.tag(id), q.allTags()],
  // An install belongs to no initiative, so it arrives community-wide with no
  // parent to carry it — this is the only thing that refreshes the sidebar's
  // plug-in list and the settings dialog for another admin's install, rename or
  // configuration. Takes no id: the reads are keyed by community, not by install.
  plugins: () => [q.plugins()],
};

/**
 * What a change INSIDE a resource makes stale on it: its own read and the
 * reads under its address — a project's activity, a library's pictures.
 *
 * The resource a change sits directly in (`direct`) also has its lists read
 * again, because a list row carries what is inside it: a comment count, a
 * queue's items, a board's reactions and polls. Nothing further out does, and
 * nothing here touches a count — a task is not a project, and a comment is
 * not a tool. An initiative is absent on purpose: a change in one of its tools
 * leaves its own read, its roster and its roles as they were.
 */
const CONTAINER_SPECS: Record<string, (id: number, direct: boolean) => Spec[]> = {
  ...Object.fromEntries(
    TOOLS.map((tool) => [
      toolPlural(tool),
      (id: number, direct: boolean) =>
        direct ? [q.toolSubtree(tool, id), q.toolLists(tool)] : [q.toolSubtree(tool, id)],
    ])
  ),
  tasks: (id, direct) => (direct ? [q.task(id), q.allTasks()] : [q.task(id)]),
  calendar_events: (id) => [q.calendarEvent(id)],
  wiki_pages: (id) => [q.wikiPage(id)],
  library_items: (id) => [q.libraryItem(id)],
};

/**
 * What a change to one facet of a resource makes stale, by the facet's label in
 * `changed`, where the facet is read at an address of its own rather than under
 * the resource's: a project's views, or an initiative's calendar views. A
 * project's columns are read by every chip showing a task's status, and the
 * change names the project rather than its tasks, so it reaches them all. Its
 * types are carried by every task of them, in lists and on its page as well.
 */
const FACET_SPECS: Record<string, Spec> = {
  layouts: q.layouts(),
  statuses: q.allReferences("task"),
  types: compose(q.allTasks(), q.allReferences("task")),
};

const isRef = (value: unknown): value is ResourceRef => {
  const ref = value as ResourceRef | undefined;
  return typeof ref?.type === "string" && Number.isFinite(ref?.id);
};

const refKey = (ref: ResourceRef) => `${ref.type}:${ref.id}`;

/** Note `ref` with `flag`, keeping a flag an earlier change already raised. */
const note = (into: Map<string, [ResourceRef, boolean]>, ref: ResourceRef, flag: boolean) => {
  into.set(refKey(ref), [ref, flag || (into.get(refKey(ref))?.[1] ?? false)]);
};

/**
 * Refresh everything a batch of changes made stale, in one pass over the cache.
 *
 * The batch is read once into what changed and what it sits in, and nothing
 * is matched until both are in hand, so three hundred changes on one task cost
 * the same single walk as one — and the repeats among them collapse when the
 * specs merge.
 *
 * A comment thread is the exception: it is keyed by the thing it hangs off,
 * and it is brought up to date rather than read again — the comments the batch
 * named are read back one by one and put into the pages already open.
 */
export const applyChanges = (changes: readonly RealtimeChange[], communityId: number) => {
  const resources = new Map<string, [ResourceRef, boolean]>();
  const containers = new Map<string, [ResourceRef, boolean]>();
  const threads = new Map<string, { parent: ResourceRef; commentIds: Set<number> }>();
  const specs: Spec[] = [];

  for (const change of changes) {
    const resource = change.resource;
    const parents = (change.parents ?? []).filter(isRef);
    for (const facet of change.changed ?? []) {
      const spec = FACET_SPECS[facet];
      if (spec) specs.push(spec);
    }
    if (isRef(resource)) {
      note(resources, resource, recounts(change));
      // The innermost parent is what the comment's thread hangs off.
      const parent = parents[0];
      if (resource.type === "comments" && parent) {
        const thread = threads.get(refKey(parent)) ?? { parent, commentIds: new Set() };
        thread.commentIds.add(resource.id);
        threads.set(refKey(parent), thread);
      }
    }
    for (const [index, parent] of parents.entries()) {
      note(containers, parent, index === 0);
    }
  }

  for (const [ref, recount] of resources.values()) {
    specs.push(...(RESOURCE_SPECS[ref.type]?.(ref.id, recount) ?? []));
    // What a chip, link or embed says about it — its name, its status, its body.
    specs.push(q.references(singularOf(ref.type), ref.id));
  }
  for (const [ref, direct] of containers.values()) {
    specs.push(...(CONTAINER_SPECS[ref.type]?.(ref.id, direct) ?? []));
    // A reading about the thing a change sits directly in: a project's
    // progress moves with its tasks.
    if (direct) specs.push(q.references(singularOf(ref.type), ref.id));
  }
  if (specs.length > 0) void invalidate(...specs);

  for (const { parent, commentIds } of threads.values()) {
    void syncComments(communityId, parent, [...commentIds]);
  }

  // A dashboard's answer is keyed by the dashboard, not by anything a change
  // names, so it is matched by what its widgets read: stale when a change is
  // to one of those tables, in its initiative. Initiative ids are per community,
  // so only this community's canvases are asked.
  const [scope, kind] = dashboardDataKey(communityId, 0);
  void queryClient.invalidateQueries({
    predicate: (query) =>
      query.queryKey[0] === scope &&
      query.queryKey[1] === kind &&
      query.queryKey[2] === communityId &&
      canvasIsStale(query.state.data as DashboardDataResponse | undefined, changes),
  });
};

export const useRealtimeUpdates = () => {
  const { user } = useAuth();
  // Keyed on the id, not the object: an account re-read replaces the object
  // without changing who is signed in, and rebuilding the socket for that would
  // drop every subscription over a no-op.
  const userId = user?.id ?? null;
  // Key the socket off THIS tab's URL community (the /c/{communityId} route param), so
  // each tab streams its own community. On personal routes (/, /me/*) there's no
  // param → null → no socket. The backend authorizes the socket from the same
  // path segment, so the URL is the single source of truth.
  const params = useParams({ strict: false }) as { communityId?: string };
  const routeCommunityId = params.communityId ? Number(params.communityId) : null;

  useEffect(() => {
    // The socket is scoped to a single community — in personal mode there's
    // nothing to subscribe to, and the backend would reject the auth payload.
    if (userId === null || routeCommunityId === null) {
      return;
    }
    const wsUrl = buildWebsocketUrl(routeCommunityId);
    if (!wsUrl) {
      return;
    }

    // Effect-scoped, so unmount and community-switch clear the timer with the
    // socket rather than invalidating for a community this tab has left.
    let pending: RealtimeChange[] = [];
    let frameTimer: number | null = null;

    const enqueue = (changes: RealtimeChange[]) => {
      pending.push(...changes);
      if (frameTimer !== null) {
        return;
      }
      frameTimer = window.setTimeout(() => {
        frameTimer = null;
        const batch = pending;
        pending = [];
        applyChanges(batch, routeCommunityId);
      }, FRAME_DEBOUNCE_MS);
    };

    const connection = openLiveSocket({
      url: wsUrl,
      // The community is in the address, so the frame carries the credential and
      // the gap this tab is asking to have answered. The credential is read as
      // the frame is written rather than captured, so a socket that reconnects
      // presents the one current then — it renews on its own clock while the
      // socket stays open. Empty is fine: the server reads the session cookie,
      // which is the web path after a reload.
      auth: (awaySeconds) => {
        const token = getAuthToken();
        return awaySeconds === null ? { token } : { token, away_seconds: awaySeconds };
      },
      onFrame: (payload) => {
        // A content-free invalidation bus: every frame is one transaction's
        // worth of {resource, parents, action}, never a serialized model. We
        // read the identifiers and refetch through the normal (RLS + DAC
        // gated) REST path — that refetch is the authorization gate.
        const frame = payload as { changes?: RealtimeChange[]; more?: boolean };
        if (frame.more) {
          // A write too large to name row by row — an import, a purge — or a
          // gap this socket was away for. Either way the frame says so instead
          // of carrying ids, and the answer is to read the community again.
          void invalidate(q.communityContent());
          return;
        }
        const changes = frame.changes ?? [];
        if (changes.length) {
          enqueue(changes);
        }
      },
      onAuthRejected: () => {
        // Stop, and read the account, which is the answer this cannot work out
        // for itself. It matters for a tab left open: nothing else here would
        // ask, and it would go on showing what it last drew.
        console.warn("Realtime socket was not admitted; reading the account");
        void readMe().catch(() => {
          // Whatever it was, the answer has already been acted on.
        });
      },
    });

    return () => {
      connection.close();
      if (frameTimer !== null) {
        window.clearTimeout(frameTimer);
        frameTimer = null;
      }
    };
  }, [userId, routeCommunityId]);
};
