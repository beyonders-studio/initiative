import { createFileRoute } from "@tanstack/react-router";

import { ToolSettingsLayoutsPage } from "@/pages/toolSettings/ToolSettingsLayoutsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/counter-groups/$counterGroupId/settings/layouts"
)({
  component: ToolSettingsLayoutsPage,
});
