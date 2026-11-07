import { createFileRoute } from "@tanstack/react-router";

import { OperatorDashboardPlacementPage } from "@/pages/OperatorDashboardPlacementPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/placement")(
  {
    component: OperatorDashboardPlacementPage,
  }
);
