import { createFileRoute } from "@tanstack/react-router";

import { DashboardPage } from "@/pages/community/tools/dashboards/dashboard/DashboardPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/dashboards/$dashboardId/"
)({
  component: DashboardPage,
});
