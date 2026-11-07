import { createFileRoute } from "@tanstack/react-router";

import { OperatorDashboardLayout } from "@/pages/OperatorDashboardLayout";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator")({
  component: OperatorDashboardLayout,
});
