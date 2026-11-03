/**
 * The user's view-preference maps, addressed outside React: the account's own,
 * and each community's, which keeps their views of the lists inside it.
 *
 * The cache keys and the eager fetch live here rather than in
 * `@/hooks/useViewPreference` so that `useAuth` — which starts the fetch the
 * moment it knows who is signed in — does not have to import a module that
 * imports `useAuth` back.
 */

import type { UserViewPreferencesMap } from "@/api/generated/initiativeAPI.schemas";
import {
  getListCommunityViewPreferencesQueryKey,
  getListViewPreferencesQueryKey,
  listCommunityViewPreferences,
  listViewPreferences,
} from "@/api/generated/user-view-preferences/user-view-preferences";
import { queryClient } from "@/lib/queryClient";

/** The cache key of a preference map: `communityId`'s, or the account's. */
export const viewPreferencesQueryKey = (communityId?: number) =>
  communityId === undefined
    ? getListViewPreferencesQueryKey()
    : getListCommunityViewPreferencesQueryKey(communityId);

/**
 * The cache key for the account's map. Exported so the one-shot localStorage
 * migration can prime the cache before the query runs.
 */
export const VIEW_PREFERENCES_QUERY_KEY = viewPreferencesQueryKey();

/**
 * Filter state changes rarely from the server's perspective; this client owns
 * the source of truth and writes through, so a long stale time is fine.
 */
export const PREFERENCES_STALE_TIME_MS = 5 * 60 * 1000;

/** The query for a preference map: `communityId`'s, or the account's. */
export const viewPreferencesQuery = (communityId?: number) => ({
  queryKey: viewPreferencesQueryKey(communityId),
  queryFn: ({ signal }: { signal: AbortSignal }): Promise<UserViewPreferencesMap> =>
    communityId === undefined
      ? listViewPreferences(undefined, signal)
      : listCommunityViewPreferences(communityId, undefined, signal),
  staleTime: PREFERENCES_STALE_TIME_MS,
});

/**
 * Start a preference map's fetch without waiting for a screen to ask for it:
 * the account's, or `communityId`'s.
 *
 * Consumers that gate a list query on their saved filters — My Tasks holds its
 * table back until its sort is in hand, because the table seeds its headers at
 * mount — otherwise turn this into a serial hop: authenticate, then fetch
 * preferences, then fetch the list; and a list that asks with its defaults
 * first asks twice. Called as soon as the signed-in account is known, and as
 * soon as a community is entered, the map is already in flight (usually
 * already answered) by the time the page mounts, and `useViewPreference`'s own
 * query dedupes onto it.
 *
 * Errors are swallowed: nothing waits on this, and every consumer falls back to
 * its defaults when the map cannot be read.
 */
export const prefetchViewPreferences = (communityId?: number): void => {
  void queryClient.prefetchQuery(viewPreferencesQuery(communityId)).catch(() => {});
};
