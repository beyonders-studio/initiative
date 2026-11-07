import { createFileRoute } from "@tanstack/react-router";

import { ProjectSettingsTaskStatusesPage } from "@/pages/initiativeTools/projects/ProjectSettingsTaskStatusesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/task-statuses"
)({
  component: ProjectSettingsTaskStatusesPage,
});
