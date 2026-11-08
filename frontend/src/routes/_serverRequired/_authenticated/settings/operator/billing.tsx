import { createFileRoute } from "@tanstack/react-router";

import { OperatorDashboardBillingPage } from "@/pages/OperatorDashboardBillingPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/billing")({
  component: OperatorDashboardBillingPage,
});
