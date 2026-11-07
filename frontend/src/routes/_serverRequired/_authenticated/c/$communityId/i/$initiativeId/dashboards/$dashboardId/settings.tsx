import { createFileRoute } from "@tanstack/react-router";

import { DashboardSettingsPage } from "@/pages/initiativeTools/dashboards/DashboardSettingsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/dashboards/$dashboardId/settings"
)({
  component: DashboardSettingsPage,
});
