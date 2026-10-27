import { createFileRoute } from "@tanstack/react-router";

import { LazyLibraryDetailPage } from "@/lib/initiativeDetailRoute";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/libraries/$libraryId/items/$itemId"
)({
  component: LazyLibraryDetailPage,
});
