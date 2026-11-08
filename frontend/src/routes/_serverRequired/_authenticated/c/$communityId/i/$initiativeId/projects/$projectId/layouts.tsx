import { createFileRoute } from "@tanstack/react-router";

import { parseLayoutKind } from "@/lib/filters/layoutSearch";
import { ProjectLayoutEditorPage } from "@/pages/initiativeTools/projects/ProjectLayoutEditorPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/layouts"
)({
  // Which of the project's layouts the editor opens on.
  validateSearch: (search: Record<string, unknown>) => ({
    layout: parseLayoutKind(search.layout),
  }),
  component: ProjectLayoutEditorPage,
});
