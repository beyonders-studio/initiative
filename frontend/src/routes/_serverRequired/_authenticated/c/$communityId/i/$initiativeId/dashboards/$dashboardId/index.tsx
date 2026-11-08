import { createFileRoute } from "@tanstack/react-router";

import { DashboardDetailPage } from "@/pages/initiativeTools/dashboards/DashboardDetailPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/i/$initiativeId/dashboards/$dashboardId/"
)({
  component: DashboardDetailPage,
});
