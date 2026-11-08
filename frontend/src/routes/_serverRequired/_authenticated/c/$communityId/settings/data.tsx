import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityDataPage } from "@/pages/SettingsCommunityDataPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/data"
)({
  component: SettingsCommunityDataPage,
});
