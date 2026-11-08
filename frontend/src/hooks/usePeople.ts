/**
 * Who there is to reach.
 *
 * The rosters are a single server-side aggregate — the backend walks the
 * reader's communities the way every other "my" page does. Growing one
 * community past its first page is a second read: a request for that
 * community alone.
 *
 * The new-conversation picker on My Messages makes these reads.
 */

import { useInfiniteQuery } from "@tanstack/react-query";

import {
  getListPeopleSectionsQueryKey,
  listPeopleSections,
  useListPeopleSections,
} from "@/api/generated/people/people";

/** Members read per community at a time. */
const PEOPLE_PAGE_SIZE = 20;

const sectionParams = (search: string) =>
  search.trim() ? { search, page_size: PEOPLE_PAGE_SIZE } : { page_size: PEOPLE_PAGE_SIZE };

/**
 * Every community's first page, under one term.
 *
 * ``enabled`` is for a surface that is not on screen yet — a dialog behind a
 * button — where the aggregate is a whole walk of the reader's communities and
 * there is no reason to walk it until somebody opens the thing.
 */
export const usePeopleSections = (search: string, options?: { enabled?: boolean }) =>
  useListPeopleSections(sectionParams(search), {
    query: { enabled: options?.enabled ?? true },
  });

/**
 * A page of one community beyond its first.
 *
 * The aggregate already carries page one of every section, so this only runs
 * once a reader pages a section forward. Each page is its own cache entry, so
 * stepping back to one already read is immediate.
 */

/**
 * Everybody else in one community, past the first page.
 *
 * For a surface that grows a list rather than paging it — a picker, where
 * stepping between pages loses the person somebody had just spotted. It starts
 * at page two because the aggregate already carries page one of every
 * community, and it does not run at all until the reader asks for more, so a
 * roster nobody reaches the bottom of costs nothing.
 */
export const useMoreCommunityPeople = (communityId: number, search: string, enabled: boolean) => {
  // One community's roster: the aggregate's own request, narrowed to it.
  const params = { community_ids: [communityId], ...sectionParams(search) };
  return useInfiniteQuery({
    // Under the aggregate's path, so whatever refreshes the rosters refreshes
    // this too. The last element keeps it apart from the aggregate's own
    // entry, which holds one answer rather than a list of pages.
    queryKey: [...getListPeopleSectionsQueryKey(params), "pages"],
    queryFn: ({ pageParam, signal }) =>
      listPeopleSections({ ...params, page: pageParam }, undefined, signal),
    initialPageParam: 2,
    // The section says whether there is one after it; the page number is how
    // many have been fetched, offset by the one that arrived with the walk.
    getNextPageParam: (last, all) => (last.sections?.[0]?.has_next ? all.length + 2 : undefined),
    enabled,
  });
};
