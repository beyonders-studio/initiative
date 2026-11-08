import { createFileRoute } from "@tanstack/react-router";

import { getGetTagCountsQueryOptions, getGetTagQueryOptions } from "@/api/generated/tags/tags";
import { TagPage } from "@/pages/community/tags/TagPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/c/$communityId/tags_/$tagId")(
  {
    // The tab open, as the tool's route segment (`?tool=wikis`), so a tab is a
    // link and the back button returns to it.
    validateSearch: (search: Record<string, unknown>): { tool?: string } => ({
      tool: typeof search.tool === "string" ? search.tool : undefined,
    }),
    loader: ({ context, params }) => {
      const communityId = Number(params.communityId);
      const tagId = Number(params.tagId);
      const { queryClient } = context;

      // Warm the cache without holding the navigation on it: the page draws
      // its placeholder at once and the reads land into it. A failed prefetch
      // is swallowed here; the page fetches for itself and reports the error.
      void Promise.all([
        queryClient.ensureQueryData(
          getGetTagQueryOptions(communityId, tagId, undefined, { query: { staleTime: 60_000 } })
        ),
        queryClient.ensureQueryData(getGetTagCountsQueryOptions(communityId, tagId)),
      ]).catch(() => {});
    },
    component: TagPage,
  }
);
