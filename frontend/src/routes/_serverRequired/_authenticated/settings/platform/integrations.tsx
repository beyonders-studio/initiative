import { createFileRoute } from "@tanstack/react-router";

import { IntegrationsPage } from "@/pages/platform/integrations/IntegrationsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/platform/integrations"
)({
  component: IntegrationsPage,
});
