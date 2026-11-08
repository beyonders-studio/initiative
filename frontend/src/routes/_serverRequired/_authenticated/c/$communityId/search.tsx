import { createFileRoute } from "@tanstack/react-router";

import { validatePage } from "@/lib/routeSearch";
import {
  DEFAULT_SEARCH_CATEGORY,
  isSearchCategory,
  type SearchCategory,
} from "@/lib/searchResults";
import { SearchPage } from "@/pages/community/search/SearchPage";

/** What the reader searched for, which slice they are reading, and how far in.
 *  All optional — `/search` with nothing on it is the empty search page. */
export interface SearchPageSearch {
  q?: string;
  tab?: SearchCategory;
  page?: number;
  /** Archived work is left out unless the reader asks for it. */
  archived?: true;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/search")({
  validateSearch: (search: Record<string, unknown>): SearchPageSearch => ({
    q: typeof search.q === "string" && search.q.length > 0 ? search.q : undefined,
    // Tools is where a search lands, so it stays out of the URL.
    tab:
      isSearchCategory(search.tab) && search.tab !== DEFAULT_SEARCH_CATEGORY
        ? search.tab
        : undefined,
    page: validatePage(search.page),
    // Only ever present when on, so the default stays out of the URL.
    archived: search.archived === true || search.archived === "true" ? true : undefined,
  }),
  component: SearchPage,
});
