import { createFileRoute } from "@tanstack/react-router";

import { BillingPage } from "@/pages/operator/BillingPage";

export const Route = createFileRoute("/_serverRequired/_authenticated/settings/operator/billing")({
  component: BillingPage,
});
