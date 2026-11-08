import { createFileRoute } from "@tanstack/react-router";

import { SettingsPlatformIntegrationsPage } from "@/pages/SettingsPlatformIntegrationsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/settings/platform/integrations"
)({
  component: SettingsPlatformIntegrationsPage,
});
