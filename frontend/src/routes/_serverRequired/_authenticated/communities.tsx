import { createFileRoute } from "@tanstack/react-router";

import type { CommunityCategory } from "@/api/generated/initiativeAPI.schemas";
import { asCommunityCategories } from "@/lib/communityCategories";
import { type NearSearch, nearSearchFrom } from "@/lib/directoryNear";
import { CommunitiesPage } from "@/pages/communities/CommunitiesPage";

/** What the endpoint accepts, so a hand-typed address cannot ask for more. */
const MAX_QUERY_LENGTH = 200;

export interface CommunitySearch extends NearSearch {
  /** Communities on any of these shelves. */
  category?: CommunityCategory[];
  q?: string;
}

export const Route = createFileRoute("/_serverRequired/_authenticated/communities")({
  // What is showing, so a filtered directory can be linked and survives a
  // reload. Both live here rather than in component state because the filters
  // and the results they narrow sit on opposite sides of the app layout — the
  // sidebar writes these, the page reads them. Anything unrecognized falls
  // back to the unfiltered shelf rather than filtering the grid down to
  // nothing.
  validateSearch: (search: Record<string, unknown>): CommunitySearch => {
    // One shelf arrives as a single value, several as a list.
    const category = asCommunityCategories(search.category);
    const raw = typeof search.q === "string" ? search.q.slice(0, MAX_QUERY_LENGTH) : "";
    return {
      ...(category.length ? { category } : {}),
      ...(raw.trim() ? { q: raw } : {}),
      // Where the reader is, which sorts the shelf rather than narrowing it.
      ...nearSearchFrom(search),
    };
  },
  component: CommunitiesPage,
});
