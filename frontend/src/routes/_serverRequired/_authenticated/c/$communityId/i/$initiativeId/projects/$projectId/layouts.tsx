import { createFileRoute } from "@tanstack/react-router";

import { parseLayoutKind } from "@/lib/filters/layoutSearch";
import { LayoutEditorPage } from "@/pages/community/tools/projects/project/LayoutEditorPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/layouts"
)({
  // Which of the project's layouts the editor opens on.
  validateSearch: (search: Record<string, unknown>) => ({
    layout: parseLayoutKind(search.layout),
  }),
  component: LayoutEditorPage,
});
