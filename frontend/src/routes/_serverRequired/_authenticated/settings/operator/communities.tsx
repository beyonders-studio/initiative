import { createFileRoute } from "@tanstack/react-router";

import { OperatorDashboardCommunitiesPage } from "@/pages/OperatorDashboardCommunitiesPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/operator/communities"
)({
  component: OperatorDashboardCommunitiesPage,
});
