import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunitySecurityPage } from "@/pages/SettingsCommunitySecurityPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/security"
)({
  component: SettingsCommunitySecurityPage,
});
