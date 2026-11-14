import { createFileRoute } from "@tanstack/react-router";

import { PropertiesPage } from "@/pages/community/tools/projects/settings/PropertiesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/projects/$projectId/settings/properties"
)({
  component: PropertiesPage,
});
