import { createFileRoute } from "@tanstack/react-router";

import { SettingsCommunityGuestsPage } from "@/pages/SettingsCommunityGuestsPage";

export const Route = createFileRoute(
  "/_serverRequired/_authenticated/c/$communityId/settings/guests"
)({
  component: SettingsCommunityGuestsPage,
});
