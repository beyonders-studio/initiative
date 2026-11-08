import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityUsagePage } from "@/pages/SettingsCommunityUsagePage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/usage"
)({
  component: SettingsCommunityUsagePage,
});
