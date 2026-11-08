import { createFileRoute } from "@tanstack/react-router";

import { InitiativeSettingsExportPage } from "@/pages/initiativeSettings/InitiativeSettingsExportPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/settings/export"
)({
  component: InitiativeSettingsExportPage,
});
