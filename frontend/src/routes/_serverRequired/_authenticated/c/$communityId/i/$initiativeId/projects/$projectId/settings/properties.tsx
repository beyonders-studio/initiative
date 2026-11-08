import { createFileRoute } from "@tanstack/react-router";

import { ProjectSettingsPropertiesPage } from "@/pages/initiativeTools/projects/ProjectSettingsPropertiesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/properties"
)({
  component: ProjectSettingsPropertiesPage,
});
