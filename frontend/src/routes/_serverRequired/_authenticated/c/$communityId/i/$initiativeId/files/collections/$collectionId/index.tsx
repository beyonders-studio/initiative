import { createFileRoute } from "@tanstack/react-router";

import { getReadCollectionQueryOptions } from "@/api/generated/files/files";
import { CollectionPage } from "@/pages/community/tools/files/collection/CollectionPage";

/**
 * A collection: in the initiative's Files, beside the files rather than inside
 * one of them, since a file can be in any number of collections.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/collections/$collectionId/"
)({
  loader: ({ context, params }) => {
    const collectionId = Number(params.collectionId);
    const communityId = Number(params.communityId);
    // Warm the cache without holding the navigation on it; the page reports a
    // failed read itself.
    void context.queryClient
      .ensureQueryData(getReadCollectionQueryOptions(communityId, collectionId))
      .catch(() => {});
  },
  component: CollectionPage,
});
