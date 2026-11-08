import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityPage } from "@/pages/SettingsCommunityPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/community"
)({
  component: SettingsCommunityPage,
});
