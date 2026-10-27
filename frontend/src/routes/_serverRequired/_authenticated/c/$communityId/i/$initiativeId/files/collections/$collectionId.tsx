import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { getReadCollectionQueryKey, readCollection } from "@/api/generated/files/files";

/**
 * A collection: in the initiative's Files, beside the files rather than inside
 * one of them, since a file can be in any number of collections.
 */
export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/collections/$collectionId"
)({
  loader: ({ context, params }) => {
    const collectionId = Number(params.collectionId);
    const communityId = Number(params.communityId);
    // Warm the cache without holding the navigation on it; the page reports a
    // failed read itself.
    void context.queryClient
      .ensureQueryData({
        queryKey: getReadCollectionQueryKey(communityId, collectionId),
        queryFn: () => readCollection(communityId, collectionId),
        staleTime: 30_000,
      })
      .catch(() => {});
  },
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/files/CollectionPage").then((m) => ({
      default: m.CollectionPage,
    }))
  ),
});
