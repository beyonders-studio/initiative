import { createFileRoute } from "@tanstack/react-router";

import { DashboardLayout } from "@/pages/operator/DashboardLayout";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator")({
  component: DashboardLayout,
});
