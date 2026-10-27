import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/collections/$collectionId/layouts"
)({
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/files/CollectionLayoutEditorPage").then((m) => ({
      default: m.CollectionLayoutEditorPage,
    }))
  ),
});
