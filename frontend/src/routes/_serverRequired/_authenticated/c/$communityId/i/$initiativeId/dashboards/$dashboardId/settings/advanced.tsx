import { createFileRoute } from "@tanstack/react-router";

import { ToolSettingsAdvancedPage } from "@/pages/toolSettings/ToolSettingsAdvancedPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/dashboards/$dashboardId/settings/advanced"
)({
  component: ToolSettingsAdvancedPage,
});
