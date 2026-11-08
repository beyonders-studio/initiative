import { createFileRoute } from "@tanstack/react-router";

import { InitiativeSettingsPropertiesPage } from "@/pages/initiativeSettings/InitiativeSettingsPropertiesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/properties"
)({
  component: InitiativeSettingsPropertiesPage,
});
