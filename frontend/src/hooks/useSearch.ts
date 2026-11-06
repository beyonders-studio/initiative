import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type {
  SearchCommunityParams,
  SearchResults,
  SearchSuggestion,
  SuggestCommunityParams,
} from "@/api/generated/initiativeAPI.schemas";
import {
  getRecentCommunityQueryKey,
  getSearchCommunityQueryKey,
  getSuggestCommunityQueryKey,
  recentCommunity,
  searchCommunity,
  suggestCommunity,
} from "@/api/generated/search/search";
import { useActiveCommunityId } from "@/hooks/useActiveCommunityId";
import type { QueryOpts } from "@/types/query";

/**
 * Ranked matches across everything in the active community.
 *
 * `keepPreviousData` is what makes the results page usable while typing: the
 * previous answer stays on screen instead of the list emptying between
 * keystrokes.
 */
export const useCommunitySearch = (
  params: SearchCommunityParams,
  options?: QueryOpts<SearchResults>
) => {
  const communityId = useActiveCommunityId();
  return useQuery<SearchResults>({
    queryKey: getSearchCommunityQueryKey(communityId, params),
    queryFn: () => searchCommunity(communityId, params),
    placeholderData: keepPreviousData,
    ...options,
  });
};

/** What a caller narrows a lookup to, beyond the words themselves. */
export type SuggestFilters = Omit<SuggestCommunityParams, "search">;

/**
 * Every field a lookup narrows by, named once.
 *
 * Both hooks below take one object holding two different things — the
 * narrowing the server is sent, and the React Query options it is not — and
 * have to tell them apart. The type is what makes that safe: `Record` over
 * `keyof SuggestFilters` demands an entry for each, so a field the backend
 * adds is a compile error here until it is listed, rather than something that
 * silently lands in the query options and is never sent.
 */
const FILTER_FIELDS: Record<keyof SuggestFilters, true> = {
  types: true,
  initiative_id: true,
  is_template: true,
  subject: true,
  limit: true,
};

/**
 * A caller's object split into what the server is sent and what React Query is
 * given. A field left unset is omitted rather than sent empty, so it stays out
 * of the request and out of the cache key.
 */
const splitFilters = <TData>(
  options: (QueryOpts<TData> & SuggestFilters) | undefined
): { filters: SuggestFilters; queryOptions: QueryOpts<TData> } => {
  const filters: Record<string, unknown> = {};
  const queryOptions: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(options ?? {})) {
    if (key in FILTER_FIELDS) {
      if (value != null) filters[key] = value;
    } else {
      queryOptions[key] = value;
    }
  }
  return {
    filters: filters as SuggestFilters,
    queryOptions: queryOptions as QueryOpts<TData>,
  };
};

/**
 * Titles to jump to. Matches a partial last word, so it answers while the
 * reader is still typing.
 *
 * This is the ONE lookup behind every picker in the app — the command palette,
 * a mention, a wikilink, a link, a template. They differ only in what
 * they narrow to: `types` for what kind of thing, `initiative_id` for where,
 * and `is_template` for whether it is a blueprint. A picker built on this gets
 * ranking, prefix matching and every access gate without asking for them.
 *
 * It answers only the half of a picker's job that starts with typed words;
 * `useCommunityPickerSuggestions` is what a picker asks, and calls this in turn.
 */
export const useCommunitySearchSuggest = (
  query: string,
  options?: QueryOpts<SearchSuggestion[]> & SuggestFilters
) => {
  const communityId = useActiveCommunityId();
  const { filters, queryOptions } = splitFilters<SearchSuggestion[]>(options);
  const params: SuggestCommunityParams = { search: query, ...filters };
  return useQuery<SearchSuggestion[]>({
    queryKey: getSuggestCommunityQueryKey(communityId, params),
    queryFn: () => suggestCommunity(communityId, params),
    placeholderData: keepPreviousData,
    ...queryOptions,
  });
};

/**
 * What a picker offers before anything has been typed.
 *
 * The most recently changed things the caller could name, narrowed the same way
 * the lookup is — so a picker's suggestions and its search are the same set of
 * things, and picking from the list can never offer what typing could not find.
 *
 * Not exported: a picker asks `useCommunityPickerSuggestions`, which switches to
 * this on its own. Asking for recents directly is asking half a question.
 */
const useCommunityRecentSuggestions = (
  options?: QueryOpts<SearchSuggestion[]> & SuggestFilters
) => {
  const communityId = useActiveCommunityId();
  const { filters, queryOptions } = splitFilters<SearchSuggestion[]>(options);
  const params = { ...filters };
  return useQuery<SearchSuggestion[]>({
    queryKey: getRecentCommunityQueryKey(communityId, params),
    queryFn: () => recentCommunity(communityId, params),
    ...queryOptions,
  });
};

// One stable empty answer, so a picker's own memos do not recompute on every
// render while a lookup is in flight.
const NOTHING: SearchSuggestion[] = [];

/** What a picker has to show, and what it is currently able to say about it. */
export interface PickerSuggestions {
  /** The rows to offer. */
  items: SearchSuggestion[];
  /** Whether these answer typed words, or are what was there to begin with. */
  searched: boolean;
  /**
   * True while what is on screen answers a query the reader has moved on from.
   * Shown, so the list does not blink shut between keystrokes — but not
   * offered to the keyboard, since it is not an answer to what is typed now.
   */
  stale: boolean;
  /** No answer yet. `isFetching` also covers refetching a list already shown. */
  isLoading: boolean;
  isFetching: boolean;
}

/**
 * Everything a picker shows, whichever of its two questions it is asking.
 *
 * A picker asks one question before anything is typed — "what could I point
 * at" — and another once something is: "which of them did I mean". The lookup
 * only answers the second, because it matches words and there are none yet, so
 * a picker built on it alone opens empty and teaches nothing: not what kind of
 * thing belongs here, not whether there is anything to point at at all.
 *
 * Both questions take the same narrowing and run under the same gates, so the
 * list a picker opens on can never hold something typing would refuse to find.
 */
export const useCommunityPickerSuggestions = (
  query: string,
  options?: QueryOpts<SearchSuggestion[]> & SuggestFilters
): PickerSuggestions => {
  const { enabled = true, ...narrowing } = options ?? {};
  const searched = query.trim().length > 0;
  // Both are called every render and only one is switched on: a switched-off
  // query keeps the answer it was last given, which belongs to the other
  // question.
  const recents = useCommunityRecentSuggestions({ ...narrowing, enabled: enabled && !searched });
  const matches = useCommunitySearchSuggest(query, { ...narrowing, enabled: enabled && searched });
  const active = searched ? matches : recents;
  return {
    items: active.data ?? NOTHING,
    searched,
    stale: searched && matches.isPlaceholderData,
    isLoading: active.isLoading,
    isFetching: active.isFetching,
  };
};
