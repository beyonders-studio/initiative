import { createFileRoute } from "@tanstack/react-router";

import { RolesPage } from "@/pages/community/initiatives/settings/roles/RolesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/roles"
)({
  component: RolesPage,
});
