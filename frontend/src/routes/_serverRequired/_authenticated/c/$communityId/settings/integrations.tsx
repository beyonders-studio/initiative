import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityIntegrationsPage } from "@/pages/SettingsCommunityIntegrationsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/integrations"
)({
  component: SettingsCommunityIntegrationsPage,
});
