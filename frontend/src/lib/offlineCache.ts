/**
 * What a phone with no signal still shows: the read-only content it last
 * loaded, kept for a day.
 *
 * How the cache behaves, in four rules.
 *
 *   1. It is only ever read when the device cannot reach the server. Online,
 *      every query still goes out and the server's answer is the one used;
 *      `staleTime` stays 0, so restored data refetches as soon as there is
 *      signal.
 *   2. It expires on a fixed clock.
 *   3. It belongs to one user on one server, and is erased when either changes
 *      or the user signs out.
 *   4. It holds only read-only content: default deny, an allowlist of paths,
 *      and a denylist over the top of that.
 */

import { Capacitor } from "@capacitor/core";
import { hydrate, type Query } from "@tanstack/react-query";

import { readStoredCommunityId } from "@/lib/activeCommunityStorage";
import { createIdbStore } from "@/lib/idbStore";
import {
  createShardedPersister,
  type PersistedClientLike,
  type ShardedPersister,
} from "@/lib/offlineShards";
import { queryClient } from "@/lib/queryClient";
import { getItem, removeItem, setItem } from "@/lib/storage";
import { type ChildKind, PARENT_TOOL, TOOLS, toolRouteSegment } from "@/lib/tools";

/**
 * How long the persisted cache lives on disk.
 *
 * A day: short enough that "removed from the initiative on Tuesday, still
 * reading it on Friday" cannot happen, long enough that a basement, a flight or
 * a bad building is still covered. It sits well inside the 30-day refresh TTL,
 * so the device never shows content it could not re-fetch if it *were* online.
 */
export const OFFLINE_CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

/**
 * Bumped when the shape of what we persist changes in a way that would make an
 * older blob misleading rather than merely stale. Part of the buster, so a bump
 * discards every existing cache instead of half-reading it.
 */
const OFFLINE_CACHE_SCHEMA_VERSION = 2;

/**
 * When the cache was last written — i.e. the last moment this device was online
 * with a confirmed session. Kept as its own small value rather than read back
 * out of the blob, so the banner can ask for it synchronously at render.
 */
const SYNCED_AT_KEY = "initiative-offline-synced-at";

const IDB_NAME = "initiative-offline";
const IDB_STORE = "query-cache";

/** The shard holding everything that is not one community's content. */
const PLATFORM_SHARD = "platform";

const communityShard = (communityId: number) => `g${communityId}`;

/**
 * Read-only content surfaces worth having on a train. Matched as prefixes
 * against the query key's first element, which for every generated hook is the
 * request path (`/api/v1/c/3/tasks/12`) — see `src/api/generated/*`.
 *
 * `{g}` stands in for the `/c/{communityId}` segment so one entry covers every
 * community without the prefix list having to know any community ids.
 */
const PERSIST_ALLOWLIST = [
  // Community content — the things somebody actually opened: every tool, and
  // everything a tool holds.
  ...[...TOOLS, ...(Object.keys(PARENT_TOOL) as ChildKind[])].map(
    (kind) => `/api/v1/c/{g}/${toolRouteSegment(kind)}`
  ),
  "/api/v1/c/{g}/initiatives",
  "/api/v1/c/{g}/task-statuses",
  "/api/v1/c/{g}/calendar-entries",
  "/api/v1/c/{g}/comments",
  "/api/v1/c/{g}/tags",
  "/api/v1/c/{g}/property-definitions",
  "/api/v1/c/{g}/fields",
  "/api/v1/c/{g}/tools",
  // Cross-community "my" reads that the home screens are built from.
  "/api/v1/me/tasks",
  "/api/v1/me/projects",
  "/api/v1/me/tools",
  // Enough identity and structure to render the shell around all of it.
  "/api/v1/me",
  "/api/v1/communities",
  "/api/v1/recents",
] as const;

/**
 * Paths that are never written, whatever the allowlist above says. Settings and
 * the operator surfaces are configuration rather than content; search and trash are
 * derived surfaces; none of them is "what I was reading".
 */
const PERSIST_DENYLIST = [
  "/api/v1/auth/",
  "/api/v1/config",
  "/api/v1/settings",
  "/api/v1/c/{g}/settings",
  "/api/v1/c/{g}/members",
  "/api/v1/c/{g}/webhooks",
  "/api/v1/c/{g}/plugins",
  "/api/v1/operator",
  "/api/v1/access-grants",
  "/api/v1/ai-settings",
  "/api/v1/webhooks",
  "/api/v1/exports",
  "/api/v1/imports",
  "/api/v1/storage",
  "/api/v1/native",
  "/api/v1/search",
  "/api/v1/trash",
  "/api/v1/me/trash",
  // The account's own settings, credentials and addresses.
  "/api/v1/me/api-keys",
  "/api/v1/me/emails",
  "/api/v1/me/ai",
  "/api/v1/me/notification-preferences",
  "/api/v1/me/reports",
  // Messages keep their own store, with its own rules about what stays on a
  // device (see `src/crypto/`). They are not duplicated here.
  "/api/v1/me/dm",
  "/api/v1/me/connections",
  "/api/v1/me/contacts",
  "/api/v1/me/ignored",
  "/api/v1/me/message-requests",
  "/dm/",
] as const;

const COMMUNITY_SEGMENT = /^\/api\/v1\/c\/(\d+)(?=\/|$)/;

/**
 * Communities the user reaches only through a live, time-bound grant rather than
 * membership. Their content is not written to disk, since the grant can end
 * while the device is away. `useCommunities` marks these `accessType: "grant"` and
 * keeps this set current; the dehydrate filter reads it.
 */
let grantOnlyCommunityIds: ReadonlySet<number> = new Set();

/**
 * Replace the set. Only for a reading that actually came back — a narrower set
 * than the truth would let a grant community's content through.
 */
export const setGrantOnlyCommunityIds = (ids: Iterable<number>): void => {
  grantOnlyCommunityIds = new Set(ids);
};

/**
 * Widen the set without narrowing it, for when the grant list could not be
 * read. The cost of keeping a community in here that has since become an ordinary
 * membership is only that its content is not cached until the next good read.
 */
export const addGrantOnlyCommunityIds = (ids: Iterable<number>): void => {
  grantOnlyCommunityIds = new Set([...grantOnlyCommunityIds, ...ids]);
};

/** Test seam. */
export const resetGrantOnlyCommunityIds = (): void => {
  grantOnlyCommunityIds = new Set();
};

/** The community a request path addresses, or null for a platform-level path. */
export const communityIdOfPath = (path: string): number | null => {
  const match = COMMUNITY_SEGMENT.exec(path);
  return match ? Number(match[1]) : null;
};

/** A list entry with its `{g}` filled in from the path it is matched against. */
const resolveEntry = (entry: string, path: string): string =>
  entry.replace("/c/{g}", `/c/${communityIdOfPath(path) ?? ""}`);

const matchesAllowlist = (path: string): boolean =>
  PERSIST_ALLOWLIST.some((entry) => {
    const prefix = resolveEntry(entry, path);
    return path === prefix || path.startsWith(`${prefix}/`) || path.startsWith(`${prefix}?`);
  });

const matchesDenylist = (path: string): boolean =>
  PERSIST_DENYLIST.some((entry) => path.includes(resolveEntry(entry, path)));

/**
 * Whether one request path may be written to disk. Default deny: a path has to
 * be named by the allowlist, must not be named by the denylist, and must not
 * belong to a community reached only by a grant.
 */
export const isPersistablePath = (path: string): boolean => {
  if (!path.startsWith("/api/v1/")) return false;
  if (matchesDenylist(path)) return false;
  if (!matchesAllowlist(path)) return false;

  const communityId = communityIdOfPath(path);
  if (communityId !== null && grantOnlyCommunityIds.has(communityId)) return false;

  return true;
};

/**
 * The dehydrate filter. Only successful reads of allowlisted paths are kept —
 * a cached error is noise, and every hand-written query key (`["dm", …]`,
 * `["contacts", …]`) falls out here because its first element is not a path.
 */
export const shouldPersistQuery = (query: Query): boolean => {
  if (query.state.status !== "success") return false;
  const [first] = query.queryKey;
  if (typeof first !== "string") return false;
  return isPersistablePath(first);
};

/**
 * Native only, for now. Extending this to installed PWAs is a separate
 * decision.
 */
export const isOfflineCacheEnabled = (): boolean => Capacitor.isNativePlatform();

const store = createIdbStore(IDB_NAME, IDB_STORE);

/**
 * Ties the cache to one server: `persistQueryClient` discards any blob whose
 * buster differs, so pointing the app at another deployment starts empty.
 *
 * The user half cannot be done here, since nobody is confirmed at boot — that
 * is `restoredIdentityMismatch` below.
 */
export const offlineCacheBuster = (serverUrl: string): string =>
  `v${OFFLINE_CACHE_SCHEMA_VERSION}|${serverUrl}`;

/** Whose answers the query client holds: the account last confirmed here, or,
 *  at boot, whoever the restored cache was saved for. */
let restoredForUserId: number | null = null;

export const noteRestoredIdentity = (userId: number | null): void => {
  restoredForUserId = userId;
};

/**
 * True when the server confirms a different user than the one whose answers
 * the client holds: a sign-in over a live session, or a sign-out that did not
 * complete. Used on every platform; the caller clears the query client and
 * purges the blob.
 */
export const restoredIdentityMismatch = (confirmedUserId: number): boolean => {
  const mismatch = restoredForUserId !== null && restoredForUserId !== confirmedUserId;
  restoredForUserId = confirmedUserId;
  return mismatch;
};

/**
 * Whether anything may be written to disk right now: false until the server has
 * confirmed who is here, so only content it has just served is recorded.
 *
 * This is also what keeps the max age meaningful. Every save restamps the
 * blob's timestamp, and a launch with no signal re-dehydrates the cache it just
 * restored — so without this, a device opened offline each morning would renew
 * its own expiry indefinitely.
 */
let writesAllowed = false;

export const setOfflineWritesAllowed = (allowed: boolean): void => {
  writesAllowed = allowed;
};

/**
 * Which shard a query key belongs to: the community it addresses, or the
 * platform shard for everything that is not one community's content.
 */
export const shardOfQueryKey = (queryKey: readonly unknown[]): string => {
  const [first] = queryKey;
  if (typeof first !== "string") return PLATFORM_SHARD;
  const communityId = communityIdOfPath(first);
  return communityId === null ? PLATFORM_SHARD : communityShard(communityId);
};

/**
 * Hydrated at startup: the platform shard, plus the community this tab would
 * open by default. The rest wait until somebody opens them, which is what keeps
 * a launch from parsing every community's content before the first frame.
 */
const bootShards = (): string[] => {
  const stored = readStoredCommunityId();
  return stored === null ? [PLATFORM_SHARD] : [PLATFORM_SHARD, communityShard(stored)];
};

let persister: ShardedPersister | null = null;

const getPersister = (): ShardedPersister => {
  if (!persister) {
    persister = createShardedPersister({
      store,
      maxAgeMs: OFFLINE_CACHE_MAX_AGE_MS,
      shardOf: shardOfQueryKey,
      bootShards,
    });
  }
  return persister;
};

export const createOfflineCachePersister = () => {
  const sharded = getPersister();
  return {
    persistClient: (client: PersistedClientLike) => {
      if (!writesAllowed) return undefined;
      setItem(SYNCED_AT_KEY, String(client.timestamp));
      return sharded.persistClient(client);
    },
    restoreClient: () => sharded.restoreClient(),
    removeClient: () => sharded.removeClient(),
  };
};

/**
 * Bring a community's cached content into the query client when it is opened
 * after startup. Does nothing when the shard is absent or past the window; the
 * queries then simply have no cached data, which is the same position they were
 * in before any of this existed.
 */
export const hydrateCommunityShard = async (communityId: number): Promise<void> => {
  if (!isOfflineCacheEnabled()) return;
  try {
    const queries = await getPersister().readShard(communityShard(communityId));
    if (!queries || queries.length === 0) return;
    hydrate(queryClient, { mutations: [], queries });
  } catch {
    // A shard that will not load is a shard the app does without.
  }
};

/**
 * Keep only these communities and drop the rest, in memory and on disk.
 *
 * Called with lists the server has just confirmed. A community somebody has
 * left, been removed from, or now reaches only by a time-bound grant stops
 * appearing, and its content goes rather than waiting out the 24 hours — when
 * we learn while online that a membership is over, there is no reason to leave
 * the content sitting there.
 *
 * The order matters. Deleting the shard alone would not hold: the departed
 * community's queries are still in the query client, and the next save would
 * write the shard straight back from memory. So the queries go first, and then
 * the shard — a save landing in between writes a client that no longer has
 * them.
 *
 * @param reachable every community the user can reach right now, memberships
 *   and live grants alike. Their queries stay in the client.
 * @param cacheable the subset whose content may live on disk: memberships
 *   only, since a grant can end while the device is away.
 *
 * Only ever call this with authoritative lists. The remembered list a launch
 * with no signal falls back to is not one, and neither is a membership list
 * whose grants could not be read — pruning against either would throw away
 * content that is still perfectly reachable.
 */
export const retainOnlyCommunities = async (
  reachable: Iterable<number>,
  cacheable: Iterable<number>
): Promise<void> => {
  if (!isOfflineCacheEnabled()) return;

  const stillReachable = new Set(reachable);
  queryClient.removeQueries({
    predicate: (query) => {
      const [first] = query.queryKey;
      if (typeof first !== "string") return false;
      const communityId = communityIdOfPath(first);
      return communityId !== null && !stillReachable.has(communityId);
    },
  });

  const keep = new Set([...cacheable].map(communityShard));
  try {
    await getPersister().retainShards((shard) => shard === PLATFORM_SHARD || keep.has(shard));
  } catch {
    // Best effort; anything missed still ages out on its own clock.
  }
};

/** Epoch ms of the last write, or null if this device has never cached. */
export const offlineCacheSyncedAt = (): number | null => {
  const raw = getItem(SYNCED_AT_KEY);
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
};

/**
 * The `persistOptions` half. Kept beside the filter so the two cannot drift:
 * a persisted blob is only ever restored when it is inside the window *and*
 * belongs to this user on this server, and only ever written for a query the
 * filter approved. Mutations are never persisted — that is the line that keeps
 * offline reading from quietly becoming offline writing.
 */
export const offlinePersistOptions = (buster: string) => ({
  persister: createOfflineCachePersister(),
  maxAge: OFFLINE_CACHE_MAX_AGE_MS,
  buster,
  dehydrateOptions: {
    shouldDehydrateQuery: shouldPersistQuery,
    shouldDehydrateMutation: () => false,
  },
});

/** Erase the persisted cache. Called on sign-out and on a rejected session. */
export const purgeOfflineCache = async (): Promise<void> => {
  removeItem(SYNCED_AT_KEY);
  try {
    await getPersister().removeClient();
  } catch {
    // Best effort: a cache we cannot delete is one we also could not read, and
    // the buster means the next session will not accept it either way.
  }
};
