import { createFileRoute } from "@tanstack/react-router";

import { InitiativeSettingsRolesPage } from "@/pages/initiativeSettings/InitiativeSettingsRolesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/roles"
)({
  component: InitiativeSettingsRolesPage,
});
