import { createFileRoute } from "@tanstack/react-router";

import { PropertiesPage } from "@/pages/community/initiatives/settings/PropertiesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/properties"
)({
  component: PropertiesPage,
});
