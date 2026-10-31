/**
 * Per-user view preferences hook.
 *
 * Drop-in shape for the old `useState` + `getItem`/`setItem` pattern:
 *
 * ```tsx
 * const [mode, setMode] = useViewPreference<CalendarViewMode>(
 *   CALENDAR_VIEW_MODE_KEY,
 *   "month",
 * );
 * ```
 *
 * Backed by one React Query per preference map, each fetched whole once per
 * session: the account's, and with a `communityId`, that community's, which
 * keeps the views of the lists inside it. Writes optimistically update the
 * cache and debounce a PUT to the server so rapid filter edits coalesce into
 * one network request. Pending writes are flushed on unmount.
 */

import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import {
  putCommunityViewPreference,
  putViewPreference,
} from "@/api/generated/user-view-preferences/user-view-preferences";
import { useAuth } from "@/hooks/useAuth";
import { viewPreferencesQuery, viewPreferencesQueryKey } from "@/lib/viewPreferences";

/** Coalesce rapid edits into one PUT after the user pauses for this long. */
const WRITE_DEBOUNCE_MS = 400;

// Re-exported so the many callers that read the map's cache key from this hook
// keep working; it lives in lib/ because useAuth warms the map and cannot
// import a module that imports useAuth back.
export { VIEW_PREFERENCES_QUERY_KEY } from "@/lib/viewPreferences";

type PendingWrite = {
  timer: ReturnType<typeof setTimeout>;
  value: unknown;
  scopeKey: string;
  communityId: number | undefined;
};

/**
 * Module-level debounce map keyed by the map and `scope_key` a write goes
 * to. Lifting this out of the hook means two consumers of the same scope
 * (rare, but possible) still share one outgoing write window — the most
 * recent target value wins. Survives hot-reload via the eager initialization.
 */
const pendingWrites = new Map<string, PendingWrite>();

const pendingKey = (scopeKey: string, communityId: number | undefined) =>
  `${viewPreferencesQueryKey(communityId)[0]}/${scopeKey}`;

const flushWrite = async (key: string): Promise<void> => {
  const pending = pendingWrites.get(key);
  if (!pending) return;
  pendingWrites.delete(key);
  const body = { value: pending.value };
  await (pending.communityId === undefined
    ? putViewPreference(pending.scopeKey, body)
    : putCommunityViewPreference(pending.communityId, pending.scopeKey, body));
};

/**
 * Set one preference outside the hook: shown at once from the cache, written
 * after the same pause. For a caller whose keys are not known up front (a
 * page with one preference per view it keeps). `communityId` names the
 * community whose map keeps it; without one, the account's does.
 */
export const writeViewPreference = (
  queryClient: QueryClient,
  scopeKey: string,
  value: unknown,
  communityId?: number
): void => {
  const queryKey = viewPreferencesQueryKey(communityId);
  queryClient.setQueryData<UserViewPreferencesMap>(queryKey, (old) => ({
    items: { ...(old?.items ?? {}), [scopeKey]: value },
  }));

  const key = pendingKey(scopeKey, communityId);
  const existing = pendingWrites.get(key);
  if (existing) clearTimeout(existing.timer);
  pendingWrites.set(key, {
    value,
    scopeKey,
    communityId,
    timer: setTimeout(() => {
      flushWrite(key).catch(() => {
        // Server rejected the write — drop our optimistic state and
        // resync from disk so the UI matches reality.
        pendingWrites.delete(key);
        void queryClient.invalidateQueries({ queryKey });
      });
    }, WRITE_DEBOUNCE_MS),
  });
};

/**
 * A whole preference map — `communityId`'s, or the account's — and whether it
 * has been read. Shared with every consumer of the same map.
 */
export function useViewPreferenceMap(communityId?: number): {
  isLoaded: boolean;
  items: Readonly<Record<string, unknown>> | undefined;
} {
  const { user } = useAuth();

  // Gated on auth: an anonymous bootstrap page (login, forgot password)
  // should not fire this query.
  const query = useQuery<UserViewPreferencesMap>({
    ...viewPreferencesQuery(communityId),
    enabled: user !== null,
    // We own the source of truth in this client and write through, so a
    // refetch on focus would clobber an optimistic value if a PUT was
    // still in flight.
    refetchOnWindowFocus: false,
  });

  // For unauthenticated callers (which shouldn't happen inside the
  // authenticated tree, but defensively) treat the fallback as loaded
  // so they don't block forever.
  const isLoaded = user === null || query.isSuccess || query.isError;
  return { isLoaded, items: query.data?.items };
}

/**
 * Returns `[value, setValue, { isLoaded, items }]`, from `communityId`'s map
 * where one is given, else the account's.
 *
 * `isLoaded` is false until the initial server fetch resolves; consumers
 * that gate other queries on the persisted filters being available can
 * use it to avoid a redundant "fetch-with-defaults then re-fetch" pair.
 * `items` is the whole map, for a reader that carries an older key over.
 */
export function useViewPreference<T>(
  scopeKey: string,
  fallback: T,
  communityId?: number
): [
  T,
  (next: T | ((prev: T) => T)) => void,
  { isLoaded: boolean; items: Readonly<Record<string, unknown>> | undefined },
] {
  const queryClient = useQueryClient();
  const { isLoaded, items } = useViewPreferenceMap(communityId);

  const value = (items?.[scopeKey] as T | undefined) ?? fallback;

  const setValue = useCallback(
    (next: T | ((prev: T) => T)) => {
      // Compute the resolved next value off the *current* cache, not the
      // captured `value` in this closure — multiple setValue calls in a
      // single render should compose.
      const current =
        (queryClient.getQueryData<UserViewPreferencesMap>(viewPreferencesQueryKey(communityId))
          ?.items?.[scopeKey] as T | undefined) ?? fallback;
      const resolved = typeof next === "function" ? (next as (prev: T) => T)(current) : next;

      writeViewPreference(queryClient, scopeKey, resolved, communityId);
    },
    [queryClient, scopeKey, fallback, communityId]
  );

  // Flush any pending write on unmount so navigating away doesn't drop
  // a still-debouncing edit. Pattern mirrors useSteppedCount.
  useEffect(() => {
    const key = pendingKey(scopeKey, communityId);
    return () => {
      const pending = pendingWrites.get(key);
      if (!pending) return;
      clearTimeout(pending.timer);
      void flushWrite(key);
    };
  }, [scopeKey, communityId]);

  return [value, setValue, { isLoaded, items }];
}
