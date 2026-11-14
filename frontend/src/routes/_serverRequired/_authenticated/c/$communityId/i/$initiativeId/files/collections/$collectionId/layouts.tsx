import { createFileRoute } from "@tanstack/react-router";

import { parseLayoutKind } from "@/lib/filters/layoutSearch";
import { LayoutEditorPage } from "@/pages/community/tools/files/collection/LayoutEditorPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/files/collections/$collectionId/layouts"
)({
  // Which of the collection's layouts the editor opens on.
  validateSearch: (search: Record<string, unknown>) => ({
    layout: parseLayoutKind(search.layout),
  }),
  component: LayoutEditorPage,
});
