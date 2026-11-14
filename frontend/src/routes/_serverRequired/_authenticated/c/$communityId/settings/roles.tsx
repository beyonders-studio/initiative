import { createFileRoute } from "@tanstack/react-router";

import { RolesPage } from "@/pages/community/settings/RolesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/roles"
)({
  component: RolesPage,
});
