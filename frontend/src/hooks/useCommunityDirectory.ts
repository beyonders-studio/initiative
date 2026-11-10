/**
 * The community directory.
 *
 * Platform-level, like the marketplace: one shared surface with no community in the
 * request, so entries are keyed on what was asked for and nothing else. Joining
 * changes which communities the caller belongs to, so the mutation refreshes the
 * community switcher as well as the directory it was invoked from. Asking to join,
 * and withdrawing the ask, change only the caller's own card.
 */

import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";

import {
  askToJoinCommunity,
  getListDirectoryCommunitiesQueryKey,
  joinDirectoryCommunity,
  listDirectoryCommunities,
  withdrawCommunityJoinRequest,
} from "@/api/generated/communities/communities";
import type {
  CommunityRead,
  DirectoryCommunityPage,
  ListDirectoryCommunitiesParams,
} from "@/api/generated/initiativeAPI.schemas";

/** The directory turns over when a community opts in or out, not while someone
 *  scrolls it. */
const DIRECTORY_STALE_MS = 60 * 1000;

/** Cards per request. The endpoint caps a page at 60, so "show more" fetches
 *  the next page rather than asking for a bigger one — a growing page_size
 *  runs into that ceiling and takes the whole grid down with it. */
export const COMMUNITIES_PAGE_SIZE = 24;

/** Everything except the page number, which the query owns. */
export type CommunityFilters = Omit<ListDirectoryCommunitiesParams, "page" | "page_size">;

/** ``enabled`` is how the page skips the request where the platform owner runs
 *  no directory — the endpoint refuses it there, and a refusal is not a result
 *  worth rendering. */
export const useDirectoryCommunities = (
  filters: CommunityFilters,
  options?: { enabled?: boolean }
) =>
  useInfiniteQuery<DirectoryCommunityPage>({
    queryKey: getListDirectoryCommunitiesQueryKey(filters),
    queryFn: ({ pageParam, signal }) =>
      listDirectoryCommunities(
        { ...filters, page: pageParam as number, page_size: COMMUNITIES_PAGE_SIZE },
        undefined,
        signal
      ),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.has_next ? last.page + 1 : undefined),
    // Keeps the grid on screen while the next search or category loads, rather
    // than blanking it out on every keystroke.
    placeholderData: keepPreviousData,
    staleTime: DIRECTORY_STALE_MS,
    ...options,
  });

// The bare path is a prefix of every filter combination: a card that was
// `already_member: false`, or `request_pending: false`, no longer is, on any page.
const useRefreshDirectory = () => {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: getListDirectoryCommunitiesQueryKey() });
  };
};

export const useJoinDirectoryCommunity = () =>
  useMutation<CommunityRead, unknown, number>({
    mutationFn: (communityId: number) => joinDirectoryCommunity(communityId),
    onSuccess: useRefreshDirectory(),
  });

export const useAskToJoinDirectoryCommunity = () =>
  useMutation<void, unknown, { communityId: number; message: string | null }>({
    mutationFn: ({ communityId, message }) => askToJoinCommunity(communityId, { message }),
    onSuccess: useRefreshDirectory(),
  });

export const useWithdrawDirectoryJoinRequest = () =>
  useMutation<void, unknown, number>({
    mutationFn: (communityId: number) => withdrawCommunityJoinRequest(communityId),
    onSuccess: useRefreshDirectory(),
  });
