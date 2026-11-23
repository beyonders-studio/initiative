import { createFileRoute } from "@tanstack/react-router";

import { PluginServicePage } from "@/pages/platform/integrations/PluginServicePage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/platform/integrations_/plugins/$registrationId"
)({
  component: PluginServicePage,
});
