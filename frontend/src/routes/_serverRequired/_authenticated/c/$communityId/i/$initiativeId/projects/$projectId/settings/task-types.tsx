import { createFileRoute } from "@tanstack/react-router";

import { ProjectSettingsTaskTypesPage } from "@/pages/initiativeTools/projects/ProjectSettingsTaskTypesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/task-types"
)({
  component: ProjectSettingsTaskTypesPage,
});
