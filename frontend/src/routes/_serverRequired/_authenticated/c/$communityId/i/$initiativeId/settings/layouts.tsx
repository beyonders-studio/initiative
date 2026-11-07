import { createFileRoute } from "@tanstack/react-router";

import { InitiativeSettingsLayoutsPage } from "@/pages/initiativeSettings/InitiativeSettingsLayoutsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/layouts"
)({
  component: InitiativeSettingsLayoutsPage,
});
