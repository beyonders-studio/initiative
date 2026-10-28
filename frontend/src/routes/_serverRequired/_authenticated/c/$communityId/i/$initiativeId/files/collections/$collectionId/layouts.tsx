import { createFileRoute, lazyRouteComponent } from "@tanstack/react-router";

import { parseLayoutKind } from "@/lib/filters/layoutSearch";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/collections/$collectionId/layouts"
)({
  // Which of the collection's layouts the editor opens on.
  validateSearch: (search: Record<string, unknown>) => ({
    layout: parseLayoutKind(search.layout),
  }),
  component: lazyRouteComponent(() =>
    import("@/pages/initiativeTools/files/CollectionLayoutEditorPage").then((m) => ({
      default: m.CollectionLayoutEditorPage,
    }))
  ),
});
